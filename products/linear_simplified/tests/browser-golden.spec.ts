import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { openApp, sendChat, setupIsolatedApp } from "../../../tests/e2e/harness";

// Records what the web app does for each golden conversation, including turns the browser
// answers on its own without calling the backend. Milestone 3.3 moves every decision to the
// backend; this recording is how we prove that move keeps the demo's behaviour.
//
// Regenerate (only with a justified behaviour change): PIXEL_UPDATE_GOLDEN=1 npm run test:e2e

type GoldenCase = { id: string; workspace?: string; turns: string[] };
type TurnSnapshot = {
  message: string;
  handled_by: "browser" | "backend";
  path: string;
  view: string | null;
  reply: string | null;
  turn_status: string | null;
  highlighted: string[];
  issue_filter: string | null;
  open_issue: string | null;
};

const GOLDEN_DIR = join(__dirname, "golden");
const RECORDING = join(GOLDEN_DIR, "browser_decisions.json");
const UPDATING = process.env.PIXEL_UPDATE_GOLDEN === "1";
const cases: GoldenCase[] = JSON.parse(readFileSync(join(GOLDEN_DIR, "conversations.json"), "utf-8")).cases;
const recorded: Record<string, TurnSnapshot[]> = UPDATING ? {} : JSON.parse(readFileSync(RECORDING, "utf-8"));
const captured: Record<string, TurnSnapshot[]> = {};

setupIsolatedApp();

test.describe.configure({ mode: "serial" });

test.afterAll(() => {
  if (UPDATING) {
    const ordered = Object.fromEntries(cases.map(({ id }) => [id, captured[id]]));
    writeFileSync(RECORDING, `${JSON.stringify(ordered, null, 2)}\n`);
  }
});

test("golden recording covers every conversation", () => {
  test.skip(UPDATING, "Recording in progress.");
  expect(Object.keys(recorded).sort()).toEqual(cases.map(({ id }) => id).sort());
});

for (const goldenCase of cases) {
  test(`golden browser decisions: ${goldenCase.id}`, async ({ page }) => {
    await openApp(page);
    if (goldenCase.workspace) {
      await page.getByTestId("workspace-switcher").selectOption(goldenCase.workspace);
    }

    const snapshots: TurnSnapshot[] = [];
    for (const message of goldenCase.turns) {
      snapshots.push(await runTurn(page, message));
      if (snapshots.at(-1)?.path !== "/") break;
    }
    captured[goldenCase.id] = snapshots;

    if (!UPDATING) {
      expect(snapshots).toEqual(recorded[goldenCase.id]);
    }
  });
}

const agentReplies = (page: Page) => page.locator('[data-testid="transcript"] article.message:not(.visitor-message) p');

async function runTurn(page: Page, message: string): Promise<TurnSnapshot> {
  let backendTurns = 0;
  const countTurns = (request: { url(): string }) => {
    if (new URL(request.url()).pathname === "/api/agent/turn") backendTurns += 1;
  };
  page.on("request", countTurns);
  const repliesBefore = await agentReplies(page).count();

  await sendChat(page, message);
  await expect
    .poll(async () => new URL(page.url()).pathname !== "/" || (await agentReplies(page).count()) > repliesBefore)
    .toBe(true);
  await page.waitForLoadState("networkidle");
  page.off("request", countTurns);

  const path = new URL(page.url()).pathname;
  const onApp = path === "/";
  return {
    message,
    handled_by: backendTurns > 0 ? "backend" : "browser",
    path,
    view: onApp ? await textOf(page, '[data-testid="current-view-title"]') : null,
    reply: onApp ? (await agentReplies(page).last().textContent())?.trim() ?? null : null,
    turn_status: onApp ? await textOf(page, '[data-testid="turn-status"]') : null,
    highlighted: onApp ? await highlightedTargets(page) : [],
    issue_filter: onApp ? await textOf(page, '[data-testid="issue-filter"]') : null,
    open_issue: onApp ? await firstLineOf(page, '[data-testid="issue-detail-panel"]') : null
  };
}

async function textOf(page: Page, selector: string): Promise<string | null> {
  const element = page.locator(selector).first();
  if (!(await element.isVisible().catch(() => false))) return null;
  return ((await element.textContent()) ?? "").replace(/\s+/g, " ").trim();
}

async function firstLineOf(page: Page, selector: string): Promise<string | null> {
  const element = page.locator(selector).first();
  if (!(await element.isVisible().catch(() => false))) return null;
  return (await element.innerText()).split("\n").map((line) => line.trim()).find(Boolean) ?? null;
}

async function highlightedTargets(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll(".highlighted-action, .highlighted-card, .highlighted, .highlighted-bar"))
      .map((element) => element.closest("[data-testid]")?.getAttribute("data-testid") ?? element.className)
      .sort()
  );
}
