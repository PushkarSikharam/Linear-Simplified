import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { expect, test, type Page, type Route } from "@playwright/test";

// Measures paid-provider traffic for one page load and a short scripted conversation.
//
// The browser-side ceiling is a harness safeguard: every request that can reach a paid
// provider is charged its worst-case number of provider attempts *before* it is forwarded,
// and nothing is forwarded once the ceiling would be exceeded. When this harness starts the
// API itself, PIXEL_TOTAL_ATTEMPT_CAP enforces the same ceiling authoritatively on the server.
const CEILING = Number(process.env.MEASURE_ATTEMPT_CEILING ?? 20);
// Worst-case provider attempts per speech request: the API caps fallbacks at 2.
// Older builds without that cap try every configured provider (up to 3).
const SPEECH_WORST_CASE = Number(process.env.MEASURE_SPEECH_ATTEMPTS ?? 2);
const ENABLE_VOICE = process.env.MEASURE_ENABLE_VOICE !== "false";
const API_URL = process.env.MEASURE_API_URL || "";
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1"]);
// Longer than the API's 10-second per-provider timeout, times two fallback attempts.
const SPEECH_WAIT_MS = 25_000;
const SETTLE_WAIT_MS = 25_000;
const PROMPTS = [
  "How does sprint planning work?",
  "Show me the current cycle",
  "What does the GitHub integration do?",
  "Who is working on the most tickets?",
  "How do I assign a ticket?"
];

type Kind = "speech" | "reasoning" | "realtime";

// Current API paths, plus the pre-Milestone-2 Next.js routes, so older builds can be measured.
function classify(pathname: string): Kind | null {
  if (pathname === "/api/agent/speech" || pathname === "/api/tts") return "speech";
  if (pathname === "/api/agent/turn") return "reasoning";
  if (pathname === "/api/realtime-session") return "realtime";
  return null;
}

class BrowserCeiling {
  reserved = 0;
  readonly forwarded: Record<Kind, number> = { speech: 0, reasoning: 0, realtime: 0 };
  readonly blocked: string[] = [];
  readonly external: string[] = [];

  cost(kind: Kind): number {
    return kind === "speech" ? SPEECH_WORST_CASE : 1;
  }

  // Route handlers run one at a time, so the check and the charge are atomic.
  async handle(route: Route, kind: Kind) {
    const path = new URL(route.request().url()).pathname;
    if (kind === "realtime") {
      this.blocked.push(`${path} (realtime is never allowed)`);
      return route.abort();
    }
    const cost = this.cost(kind);
    if (this.reserved + cost > CEILING) {
      this.blocked.push(`${path} (ceiling ${CEILING} reached)`);
      return route.abort();
    }
    this.reserved += cost;
    this.forwarded[kind] += 1;
    return route.continue();
  }

  get exhausted(): boolean {
    return this.reserved + Math.min(SPEECH_WORST_CASE, 1) > CEILING;
  }
}

type LedgerSummary = { rows: { status: string }[] };

/**
 * The server ledger once every dispatched attempt has settled. Attempts still open when
 * the wait expires are reported as-is: they were dispatched, so they stay counted.
 */
async function settledServerSummary(): Promise<unknown> {
  const deadline = Date.now() + SETTLE_WAIT_MS;
  let summary = await serverSummary();
  while (hasOpenAttempts(summary) && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 1_000));
    summary = await serverSummary();
  }
  return summary;
}

function hasOpenAttempts(summary: unknown): boolean {
  const rows = (summary as LedgerSummary | null)?.rows;
  return Array.isArray(rows) && rows.some((row) => row.status === "reserved");
}

async function serverSummary(): Promise<unknown> {
  if (!API_URL) return "not available: the harness did not start the API";
  const login = await fetch(`${API_URL}/api/auth/demo-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: "demo-admin" })
  });
  if (!login.ok) return `not available: login returned ${login.status}`;
  const { token } = (await login.json()) as { token: string };
  const summary = await fetch(`${API_URL}/api/usage/summary`, { headers: { Authorization: `Bearer ${token}` } });
  return summary.ok ? summary.json() : `not available: summary returned ${summary.status}`;
}

async function sendChat(page: Page, message: string) {
  await page.getByTestId("chat-input").fill(message);
  await page.getByTestId("chat-send").click();
  await expect(page.getByTestId("turn-status")).not.toHaveText("Thinking", { timeout: 30_000 });
}

test("provider usage for one page load and a five-turn conversation", async ({ page, context }, testInfo) => {
  const ceiling = new BrowserCeiling();
  await context.route((url) => !LOCAL_HOSTS.has(url.hostname), async (route) => {
    ceiling.external.push(new URL(route.request().url()).hostname);
    await route.abort();
  });
  await context.route((url) => classify(url.pathname) !== null, (route) =>
    ceiling.handle(route, classify(new URL(route.request().url()).pathname)!)
  );

  await page.goto("/");
  await expect(page.getByTestId("chat-input")).toBeVisible();
  await page.waitForLoadState("networkidle");
  const afterLoad = { ...ceiling.forwarded, reservedWorstCase: ceiling.reserved };

  const voiceToggle = page.getByTestId("tts-toggle");
  if (ENABLE_VOICE && (await voiceToggle.getAttribute("aria-pressed")) === "false") {
    await voiceToggle.click();
  }

  // A visitor listens to each reply before asking the next question. Sending the next
  // prompt earlier would cancel speech mid-request and skew the measurement.
  const speechAnswered = () => page.waitForResponse(
    (response) => classify(new URL(response.url()).pathname) === "speech",
    { timeout: SPEECH_WAIT_MS }
  ).catch(() => null);

  let turnsCompleted = 0;
  for (const prompt of PROMPTS) {
    if (ceiling.exhausted) break;
    const answered = ENABLE_VOICE ? speechAnswered() : Promise.resolve(null);
    await sendChat(page, prompt);
    await answered;
    await page.waitForLoadState("networkidle");
    turnsCompleted += 1;
  }

  const report = {
    measuredAt: new Date().toISOString(),
    baseURL: testInfo.project.use.baseURL,
    paidProvidersEnabled: process.env.MEASURE_PAID === "true",
    ceiling: CEILING,
    speechWorstCasePerRequest: SPEECH_WORST_CASE,
    voiceEnabledForReplies: ENABLE_VOICE,
    afterPageLoad: afterLoad,
    turnsCompleted,
    forwardedRequests: ceiling.forwarded,
    reservedWorstCaseAttempts: ceiling.reserved,
    blockedRequests: ceiling.blocked,
    externalHostsBlocked: ceiling.external,
    serverLedger: await settledServerSummary()
  };

  const outputDir = join("test-results", "measurements");
  await mkdir(outputDir, { recursive: true });
  const file = join(outputDir, `provider-usage-${Date.now()}.json`);
  await writeFile(file, JSON.stringify(report, null, 2));
  console.log(`Provider usage report: ${file}\n${JSON.stringify(report, null, 2)}`);

  expect(ceiling.reserved).toBeLessThanOrEqual(CEILING);
  expect(ceiling.external).toEqual([]);
});
