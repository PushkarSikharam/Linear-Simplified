import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "node:net";
import { expect, test, type Page } from "@playwright/test";

let apiPort: number;
let apiToken: string;
const agentApiRoute = "**/api/agent/**";
const agentTurnRoute = "**/api/agent/turn";
const agentCancelTurnOneRoute = "**/api/agent/turn/1/cancel";

declare global {
  interface Window {
    __demoVoiceSilenceTimeoutMs?: number;
    __disableAutoGreetingSpeech?: boolean;
    __disableTextResponseSpeech?: boolean;
    __emitVoiceTranscript?: (transcript: string) => void;
    __spokenAgentReplies?: string[];
  }
}

let apiProcess: ChildProcess | null = null;
let apiDataDir: string | null = null;
const browserErrors = new WeakMap<Page, string[]>();

test.beforeAll(async () => {
  apiPort = await new Promise<number>((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close();
        reject(new Error("Could not reserve an E2E API port."));
        return;
      }
      server.close(() => resolve(address.port));
    });
  });
  apiDataDir = await mkdtemp(join(tmpdir(), "pixel-e2e-"));
  apiProcess = spawn(
    ".venv\\Scripts\\python",
    ["-m", "uvicorn", "app.main:app", "--app-dir", "apps\\api", "--port", String(apiPort)],
    {
      cwd: process.cwd(),
      env: {
        ...process.env,
        PIXEL_DB_PATH: join(apiDataDir, "demo.sqlite3"),
        LLM_ENABLED: "false"
      },
      stdio: "ignore",
      windowsHide: true
    }
  );

  apiProcess.unref();
  await waitForApi();

  // Obtain an admin token for test-harness calls (reset, direct data reads).
  const loginResponse = await fetch(`http://127.0.0.1:${apiPort}/api/auth/demo-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: "demo-admin" })
  });
  const loginBody = (await loginResponse.json()) as { token: string };
  apiToken = loginBody.token;
});

test.afterAll(async () => {
  if (apiProcess?.exitCode === null) {
    const exited = new Promise<void>((resolve) => apiProcess!.once("exit", () => resolve()));
    apiProcess.kill();
    await exited;
  }
  apiProcess = null;
  if (apiDataDir) {
    await rm(apiDataDir, { recursive: true, force: true, maxRetries: 3 });
    apiDataDir = null;
  }
});

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" });
  expect(browserErrors.get(page) ?? [], "Unexpected browser runtime errors").toEqual([]);
});

test.beforeEach(async ({ page }, testInfo) => {
  const errors: string[] = [];
  browserErrors.set(page, errors);
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/tts", (route) => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ error: "External speech is disabled in automated tests." })
  }));
  await page.route("**/api/realtime-session", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({ success: false, mode: "local" })
  }));
  await fetch(`http://127.0.0.1:${apiPort}/api/demo-data/reset`, {
    method: "POST",
    headers: { Authorization: `Bearer ${apiToken}` }
  });
  await proxyApiToFreshBackend(page);
});

async function openApp(page: Page) {
  await page.addInitScript(() => {
    try { window.sessionStorage?.removeItem("demo_auth_token"); } catch { /* ignore */ }
    window.__disableAutoGreetingSpeech = true;
    if (typeof window.__demoVoiceSilenceTimeoutMs !== "number") {
      window.__disableTextResponseSpeech = true;
    }
  });
  const authDone = page.waitForResponse(
    (resp) => resp.url().includes("/auth/demo-login") && resp.status() === 200
  );
  await page.goto("/");
  await authDone;
  await expect(page.getByTestId("current-view-title")).toHaveText("Dashboard");
  await expect(page.getByTestId("chat-input")).toBeVisible();
  await expect(page.getByTestId("diagnostics-panel")).toBeHidden();
  await expect(page.getByTestId("session-summary")).toBeHidden();
  await expect(page.getByTestId("trace-status")).toBeHidden();
}

async function proxyApiToFreshBackend(page: Page) {
  await page.route(agentApiRoute, async (route) => {
    const request = route.request();
    const response = await route.fetch({
      url: freshBackendUrl(request.url())
    });
    await route.fulfill({ response });
  });
}

async function proxyNonTurnToFreshBackend(page: Page) {
  const nonTurnPattern = /\/api\/agent\/(?!turn)/;
  await page.route(nonTurnPattern, async (route) => {
    const request = route.request();
    const response = await route.fetch({
      url: freshBackendUrl(request.url())
    });
    await route.fulfill({ response });
  });
}

function freshBackendUrl(requestUrl: string): string {
  const url = new URL(requestUrl);
  const backendPath = url.pathname.replace("/api/agent", "/api");
  return `http://127.0.0.1:${apiPort}${backendPath}${url.search}`;
}

function apiAuthHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${apiToken}` };
}

async function waitForApi() {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    if (apiProcess?.exitCode !== null) {
      throw new Error(`E2E API server exited early with code ${apiProcess?.exitCode}`);
    }

    try {
      const response = await fetch(`http://127.0.0.1:${apiPort}/health`);
      if (response.ok) return;
    } catch {
      await delay(500);
    }
  }

  throw new Error(`Timed out waiting for E2E API server on port ${apiPort}.`);
}

function delay(ms: number) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function sendChat(page: Page, message: string) {
  await page.getByTestId("chat-input").fill(message);
  await page.getByTestId("chat-send").click();
  await expect(page.getByTestId("turn-status")).not.toHaveText("Thinking");
}

async function installMockVoice(page: Page) {
  await page.addInitScript(() => {
    window.__demoVoiceSilenceTimeoutMs = 100;
    window.__disableAutoGreetingSpeech = true;

    type MockRecognitionResult = {
      isFinal: boolean;
      0: {
        transcript: string;
      };
    };

    type MockRecognitionEvent = {
      resultIndex: number;
      results: {
        length: number;
        0: MockRecognitionResult;
      };
    };

    class MockSpeechRecognition {
      continuous = false;
      interimResults = false;
      lang = "en-US";
      onend: (() => void) | null = null;
      onerror: ((event: { error: string }) => void) | null = null;
      onresult: ((event: MockRecognitionEvent) => void) | null = null;
      onstart: (() => void) | null = null;

      start() {
        const testWindow = window as Window & { __activeRecognition?: MockSpeechRecognition };
        testWindow.__activeRecognition = this;
        window.setTimeout(() => this.onstart?.(), 0);
      }

      stop() {
        window.setTimeout(() => this.onend?.(), 0);
      }

      abort() {
        this.onend = null;
      }
    }

    const testWindow = window as Window & {
      SpeechRecognition?: typeof MockSpeechRecognition;
      webkitSpeechRecognition?: typeof MockSpeechRecognition;
      SpeechSynthesisUtterance?: new (text: string) => SpeechSynthesisUtterance;
      __activeRecognition?: MockSpeechRecognition;
      __activeUtterance?: SpeechSynthesisUtterance;
      __emitVoiceTranscript?: (transcript: string) => void;
    };

    Object.defineProperty(testWindow, "SpeechRecognition", {
      configurable: true,
      value: MockSpeechRecognition
    });
    Object.defineProperty(testWindow, "webkitSpeechRecognition", {
      configurable: true,
      value: MockSpeechRecognition
    });
    Object.defineProperty(testWindow, "speechSynthesis", {
      configurable: true,
      value: {
        getVoices: () => [],
        resume: () => undefined,
        cancel: () => {
          const utterance = testWindow.__activeUtterance;
          testWindow.__activeUtterance = undefined;
          utterance?.onend?.(new Event("end") as SpeechSynthesisEvent);
        },
        speak: (utterance: SpeechSynthesisUtterance) => {
          testWindow.__activeUtterance = utterance;
          window.setTimeout(() => utterance.onstart?.(new Event("start") as SpeechSynthesisEvent), 0);
        }
      }
    });
    Object.defineProperty(testWindow, "SpeechSynthesisUtterance", {
      configurable: true,
      value: function MockUtterance(this: SpeechSynthesisUtterance, text: string) {
        Object.defineProperty(this, "text", { configurable: true, value: text });
      }
    });

    testWindow.__emitVoiceTranscript = (transcript: string) => {
      const recognition = testWindow.__activeRecognition;
      if (!recognition) return;

      recognition.onresult?.({
        resultIndex: 0,
        results: {
          0: {
            0: { transcript },
            isFinal: true
          },
          length: 1
        }
      });
      recognition.onend?.();
    };
  });
}

test("phase 1 creates a ticket through the form with the selected owner", async ({ page }) => {
  await openApp(page);
  await page.getByTestId("nav-issues").click();
  await page.getByTestId("create-ticket-button").click();
  await page.getByTestId("ticket-title-input").fill("Audit form-created ticket");
  await page.getByTestId("ticket-assignee-select").selectOption("Noah Patel");
  const saved = page.waitForResponse((response) =>
    response.url().endsWith("/demo-data/issues") && response.request().method() === "POST"
  );
  await page.getByTestId("submit-create-ticket").click();
  expect((await saved).ok()).toBe(true);
  await expect(page.getByTestId("issue-detail-panel")).toContainText("Audit form-created ticket");
  await page.reload();
  await page.getByTestId("nav-issues").click();
  await expect(page.getByText("Audit form-created ticket", { exact: true })).toBeVisible();
  const data = await (await fetch(`http://127.0.0.1:${apiPort}/api/demo-data`, { headers: apiAuthHeaders() })).json();
  expect(data.issues.find((issue: { title: string }) => issue.title === "Audit form-created ticket").assignee)
    .toBe("Noah Patel");
});

for (const entity of ["project", "cycle"] as const) {
  test(`phase 1 creates and reloads a ${entity} without changing existing records`, async ({ page }) => {
    const before = await (await fetch(`http://127.0.0.1:${apiPort}/api/demo-data`, { headers: apiAuthHeaders() })).json();
    await openApp(page);
    await page.getByTestId(`nav-${entity}s`).click();
    await page.getByTestId(`create-${entity}-button`).click();
    const name = `Audit ${entity}`;
    await page.getByTestId(`${entity}-name-input`).fill(name);
    const saved = page.waitForResponse((response) =>
      response.url().includes(`/demo-data/${entity}s`) && response.request().method() === "POST"
    );
    await page.getByTestId(`submit-create-${entity}`).click();
    expect((await saved).ok()).toBe(true);
    await expect(page.getByText(name, { exact: true })).toBeVisible();
    await page.reload();
    await page.getByTestId(`nav-${entity}s`).click();
    await expect(page.getByText(name, { exact: true })).toBeVisible();
    const after = await (await fetch(`http://127.0.0.1:${apiPort}/api/demo-data`, { headers: apiAuthHeaders() })).json();
    for (const previous of before[`${entity}s`]) {
      expect(after[`${entity}s`].find((record: { id: string }) => record.id === previous.id)).toEqual(previous);
    }
  });
}

test("phase 1 failed saves do not report success", async ({ page }) => {
  await openApp(page);
  await page.getByTestId("nav-projects").click();
  await page.getByTestId("create-project-button").click();
  await page.getByTestId("project-name-input").fill("Unsaved audit project");
  await page.route("**/api/agent/demo-data/projects?**", (route) => route.fulfill({
    status: 503, contentType: "application/json", body: JSON.stringify({ error: "Unavailable" })
  }));
  const saved = page.waitForResponse((response) =>
    response.url().includes("/demo-data/projects") && response.request().method() === "POST"
  );
  await page.getByTestId("submit-create-project").click();
  expect((await saved).status()).toBe(503);
  await expect(page.getByTestId("project-create-panel")).toBeVisible({ timeout: 1000 });
  await expect(page.getByTestId("project-create-panel").getByRole("alert")).toContainText("Could not save");
  await expect(page.getByTestId("project-name-input")).toHaveValue("Unsaved audit project");
  await page.unroute("**/api/agent/demo-data/projects?**");
  const retried = page.waitForResponse((response) =>
    response.url().includes("/demo-data/projects") && response.request().method() === "POST"
  );
  await page.getByTestId("submit-create-project").click();
  expect((await retried).ok()).toBe(true);
  await expect(page.getByTestId("project-create-panel")).toBeHidden();
});

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`phase 1 layout evidence at ${viewport.width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await openApp(page);
    await page.screenshot({ path: testInfo.outputPath("dashboard.png"), fullPage: true });
    await expect(page.getByTestId("chat-input")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByTestId("nav-issues").click();
    await page.getByTestId("create-ticket-button").click();
    await page.screenshot({ path: testInfo.outputPath("issue-form.png"), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test("keeps the core demo controls visible and navigates every product area", async ({ page }) => {
  await openApp(page);

  const navCases = [
    ["nav-issues", "Issues"],
    ["nav-projects", "Projects"],
    ["nav-cycles", "Cycles"],
    ["nav-teams", "Teams"],
    ["nav-integrations", "Integrations"],
    ["nav-dashboard", "Dashboard"]
  ] as const;

  for (const [testId, title] of navCases) {
    await page.getByTestId(testId).click();
    await expect(page.getByTestId("current-view-title")).toHaveText(title);
    if (title === "Issues") {
      await expect(page.getByTestId("create-ticket-button")).toBeVisible();
    }
  }
});

test("shows only the current workspace scope across product views", async ({ page }) => {
  await openApp(page);

  await expect(page.getByTestId("workspace-scope-badge")).toHaveText("2 scoped projects");
  await expect(page.getByText("LIN-142 - Maya Chen - Integrations")).toBeVisible();
  await expect(page.getByText("LIN-131 - Avery Brooks - Planning")).toBeHidden();

  await page.getByTestId("nav-issues").click();
  await expect(page.getByTestId("issue-count-badge")).toHaveText("3 open");
  await expect(page.getByText("LIN-137 - Noah Patel - Issue Triage")).toBeVisible();
  await expect(page.getByText("LIN-131 - Avery Brooks - Planning")).toBeHidden();

  await page.getByTestId("nav-projects").click();
  await expect(page.getByText("GitHub Integration Hardening")).toBeVisible();
  await expect(page.getByText("Issue Triage Workflow")).toBeVisible();
  await expect(page.getByText("Cycle Planning Insights")).toBeHidden();

  await page.getByTestId("nav-teams").click();
  await expect(page.getByTestId("team-member-count")).toHaveText("2 members");
  await expect(page.getByText("Maya Chen")).toBeVisible();
  await expect(page.getByText("Avery Brooks")).toBeHidden();
});

test("switches workspace scope and updates product data boundaries", async ({ page }) => {
  await openApp(page);

  await page.getByTestId("workspace-switcher").selectOption("workspace-platform");

  await expect(page.getByRole("heading", { name: "Platform Workspace" })).toBeVisible();
  await expect(page.getByTestId("workspace-scope-badge")).toHaveText("2 scoped projects");
  await expect(page.getByText("LIN-131 - Avery Brooks - Planning")).toBeVisible();
  await expect(page.getByText("LIN-142 - Maya Chen - Integrations")).toBeHidden();
  await expect(page.getByText("Platform Cycle 21")).toBeVisible();

  await page.getByTestId("nav-projects").click();
  await expect(page.getByText("Cycle Planning Insights")).toBeVisible();
  await expect(page.getByText("Workspace Migration")).toBeVisible();
  await expect(page.getByText("GitHub Integration Hardening")).toBeHidden();

  await page.getByTestId("nav-teams").click();
  await expect(page.getByTestId("team-member-count")).toHaveText("2 members");
  await expect(page.getByText("Avery Brooks")).toBeVisible();
  await expect(page.getByText("Maya Chen")).toBeHidden();
});

test("keeps Edith inside the selected workspace scope", async ({ page }) => {
  await openApp(page);

  await page.getByTestId("workspace-switcher").selectOption("workspace-platform");
  await sendChat(page, "how many team members are there");
  await expect(page.getByTestId("current-view-title")).toHaveText("Teams");
  await expect(page.getByTestId("transcript")).toContainText(
    "There are 2 team members in Platform Workspace"
  );

  await sendChat(page, "open Maya's ticket");
  await expect(page.getByTestId("current-view-title")).toHaveText("Teams");
  await expect(page.getByTestId("transcript")).toContainText(
    "Maya Chen is outside Platform Workspace"
  );

  await sendChat(page, "open Avery's ticket");
  await expect(page.getByTestId("current-view-title")).toHaveText("Issue Detail");
  await expect(page.getByTestId("selected-issue-id")).toHaveText("LIN-131");
});

test("sends the selected workspace scope to the agent API", async ({ page }) => {
  let capturedWorkspaceScopeId = "";

  await page.unroute(agentApiRoute);
  await proxyNonTurnToFreshBackend(page);
  await page.route(agentTurnRoute, async (route) => {
    const body = route.request().postDataJSON();
    capturedWorkspaceScopeId = body.workspace_scope_id;
    const response = await route.fetch({
      url: freshBackendUrl(route.request().url())
    });
    await route.fulfill({ response });
  });

  await openApp(page);
  await page.getByTestId("workspace-switcher").selectOption("workspace-platform");
  await sendChat(page, "show sprint planning");

  expect(capturedWorkspaceScopeId).toBe("workspace-platform");
});

test("blocks local requests for people outside the current workspace", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "create a ticket for Avery");

  await expect(page.getByTestId("current-view-title")).toHaveText("Dashboard");
  await expect(page.getByTestId("transcript")).toContainText(
    "Avery Brooks is outside Product Engineering Workspace"
  );
  await expect(page.getByTestId("transcript")).not.toContainText("I created");
});

test("collapses and expands the assistant sidebar", async ({ page }) => {
  await openApp(page);

  await page.getByTestId("assistant-collapse").click();

  await expect(page.getByTestId("assistant-expand")).toBeVisible();
  await expect(page.getByTestId("chat-input")).toBeHidden();

  await page.getByTestId("assistant-expand").click();

  await expect(page.getByTestId("chat-input")).toBeVisible();
});

test("keeps assistant controls contained in a narrow desktop sidebar", async ({ page }) => {
  await page.setViewportSize({ width: 920, height: 860 });
  await openApp(page);

  const panelBox = await page.locator(".assistant-panel").boundingBox();
  expect(panelBox).not.toBeNull();

  const checkedSelectors = [
    "[data-testid='demo-path']",
    ".demo-prompt-strip",
    ".chat-form",
    ".voice-control-card"
  ];

  for (const selector of checkedSelectors) {
    const childBox = await page.locator(selector).boundingBox();
    expect(childBox).not.toBeNull();
    expect(childBox!.x).toBeGreaterThanOrEqual(panelBox!.x);
    expect(childBox!.x + childBox!.width).toBeLessThanOrEqual(panelBox!.x + panelBox!.width + 1);
  }
});

test("keeps the assistant voice controls visible on the first desktop viewport", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openApp(page);

  const voiceBox = await page.locator(".voice-control-card").boundingBox();
  expect(voiceBox).not.toBeNull();
  expect(voiceBox!.y + voiceBox!.height).toBeLessThanOrEqual(900);
});

test("opens the sprint planning view from chat and shows retrieved product context", async ({
  page
}) => {
  await openApp(page);

  await sendChat(page, "show sprint planning");

  await expect(page.getByTestId("current-view-title")).toHaveText("Cycles");
  await expect(page.getByTestId("source-list")).toBeHidden();
  await expect(page.getByTestId("transcript")).toContainText("I'll show you the current cycle.");
});

test("opens the system architecture from Edith chat", async ({ page }) => {
  await openApp(page);

  await page.getByTestId("chat-input").fill("open the system architecture");
  await page.getByTestId("chat-send").click();

  await expect(page).toHaveURL(/\/architecture$/);
  await expect(page.getByRole("heading", {
    name: "How Pixel turns conversation into scoped product action."
  })).toBeVisible();
});

test("runs suggested demo turns and resets to a fresh session", async ({ page }) => {
  await openApp(page);

  await page.getByTestId("demo-prompt-back-to-github-integrations").click();
  await expect(page.getByTestId("turn-status")).not.toHaveText("Thinking");
  await expect(page.getByTestId("current-view-title")).toHaveText("Integrations");
  await expect(page.getByTestId("github-integration-card")).toHaveClass(/highlighted-card/);

  await sendChat(page, "all tickets for Maya");
  await expect(page.getByTestId("issue-filter")).toContainText("Maya Chen");

  await page.getByTestId("reset-demo").click();

  await expect(page.getByTestId("current-view-title")).toHaveText("Dashboard");
  await expect(page.getByTestId("turn-status")).toHaveText("Ready");
  await expect(page.getByTestId("transcript")).toContainText("Welcome to Pixel");
  await expect(page.getByTestId("transcript")).not.toContainText("Maya Chen");
  await expect(page.getByTestId("source-list")).toBeHidden();
});

test("opens and highlights Maya Chen's issue from chat", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "open ticket for maya");
  await expect(page.getByTestId("current-view-title")).toHaveText("Issue Detail");
  await expect(page.getByTestId("selected-issue-id")).toHaveText("LIN-142");
  await expect(page.getByTestId("assignee-control")).toContainText("Maya Chen");

  await sendChat(page, "how do I assign Maya's ticket");
  await expect(page.getByTestId("current-view-title")).toHaveText("Issue Detail");
  await expect(page.getByTestId("assignee-control")).toHaveClass(/highlighted/);
  await expect(page.getByTestId("transcript")).toContainText("highlight the assignee control");
});

test("filters all tickets assigned to Maya instead of opening one ticket", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "all the tickets for Maya which are assigned to her");

  await expect(page.getByTestId("current-view-title")).toHaveText("Issues");
  await expect(page.getByTestId("issue-filter")).toContainText("Maya Chen");
  await expect(page.getByTestId("issue-count-badge")).toHaveText("1 open");
  await expect(page.getByTestId("transcript")).toContainText(
    "I found 1 ticket assigned to Maya Chen: LIN-142"
  );
});

test("asks clarification for incomplete all-items requests", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "open all the");

  await expect(page.getByTestId("current-view-title")).toHaveText("Dashboard");
  await expect(page.getByTestId("transcript")).toContainText(
    "Do you mean all issues, all projects, or all tickets for a specific person?"
  );
});

test("asks targeted clarifying questions for vague create and assignment requests", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "create something new");
  await expect(page.getByTestId("current-view-title")).toHaveText("Dashboard");
  await expect(page.getByTestId("transcript")).toContainText(
    "What should I create: a ticket, a project, a cycle, or a team member?"
  );

  await sendChat(page, "assign it");
  await expect(page.getByTestId("transcript")).toContainText(
    "Who should I assign the current ticket to?"
  );
});

test("blocks broad workspace requests instead of showing other project data", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "show me all company projects");

  await expect(page.getByTestId("current-view-title")).toHaveText("Dashboard");
  await expect(page.getByTestId("transcript")).toContainText(
    "I can only show work inside Product Engineering Workspace"
  );
});

test("uses previous issue context for person follow-ups", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "all tickets for Maya");
  await expect(page.getByTestId("issue-filter")).toContainText("Maya Chen");

  await sendChat(page, "what about Noah");

  await expect(page.getByTestId("current-view-title")).toHaveText("Issues");
  await expect(page.getByTestId("issue-filter")).toContainText("Noah Patel");
  await expect(page.getByTestId("issue-count-badge")).toHaveText("1 open");
});

test("shows an evaluator path and runs its first prompt", async ({ page }) => {
  await openApp(page);

  await expect(page.getByTestId("demo-path")).toContainText("Guided demo path");
  await expect(page.getByTestId("demo-path-1")).toContainText("Show sprint planning");

  await page.getByTestId("demo-path-1").click();
  await expect(page.getByTestId("turn-status")).not.toHaveText("Thinking");
  await expect(page.getByTestId("current-view-title")).toHaveText("Cycles");
});

test("answers capability and team-count questions conversationally", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "are you capable of doing");
  await expect(page.getByTestId("current-view-title")).toHaveText("Dashboard");
  await expect(page.getByTestId("transcript")).toContainText("I can guide this Pixel demo");

  await sendChat(page, "how many team members are there");
  await expect(page.getByTestId("current-view-title")).toHaveText("Teams");
  await expect(page.getByTestId("transcript")).toContainText("There are 2 team members");
});

test("understands misspellings, corrections, and current issue follow-ups", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "open tikit for maya");
  await expect(page.getByTestId("current-view-title")).toHaveText("Issue Detail");
  await expect(page.getByTestId("selected-issue-id")).toHaveText("LIN-142");

  await sendChat(page, "no not cycles show issues instead");
  await expect(page.getByTestId("current-view-title")).toHaveText("Issues");

  await page.getByLabel("Open LIN-137").click();
  await expect(page.getByTestId("selected-issue-id")).toHaveText("LIN-137");

  await sendChat(page, "how do I assign this issue");
  await expect(page.getByTestId("current-view-title")).toHaveText("Issue Detail");
  await expect(page.getByTestId("selected-issue-id")).toHaveText("LIN-137");
  await expect(page.getByTestId("assignee-control")).toHaveClass(/highlighted/);
});

test("updates the current issue from natural follow-up commands", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "open ticket for Maya");
  await expect(page.getByTestId("selected-issue-id")).toHaveText("LIN-142");

  await sendChat(page, "assign it to Noah");
  await expect(page.getByTestId("current-view-title")).toHaveText("Issue Detail");
  await expect(page.getByTestId("assignee-select")).toHaveValue("Noah Patel");
  await expect(page.getByText("Updated now")).toBeVisible();
  await expect(page.getByTestId("transcript")).toContainText(
    "Done. I updated LIN-142: assignee is now Noah Patel."
  );

  await sendChat(page, "make it low priority");
  const prioritySelect = page.locator(".property-row").filter({ hasText: "Priority" }).locator("select");
  await expect(prioritySelect).toHaveValue("Low");

  await sendChat(page, "what did we just change?");
  await expect(page.getByTestId("transcript")).toContainText("updated issue LIN-142");
});

test("creates a demo ticket and opens the new issue", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "open a fresh ticket for Maya");

  await expect(page.getByTestId("turn-status")).toHaveText("Ready");
  await expect(page.getByTestId("current-view-title")).toHaveText("Issue Detail");
  await expect(page.getByTestId("selected-issue-id")).toHaveText("PIX-143");
  await expect(page.getByTestId("assignee-control")).toContainText("Maya Chen");
  await expect(page.getByText("Created now")).toBeVisible();
  await expect(page.getByTestId("transcript")).toContainText("I created PIX-143");
  await expect(page.getByTestId("activity-popup")).toContainText(
    "Saved to Product Engineering Workspace: created PIX-143 for Maya Chen."
  );

  await page.getByTestId("nav-issues").click();
  await expect(page.getByText("PIX-143 - Maya Chen - Issue Triage")).toBeVisible();
});

test("keeps created demo records after a browser refresh", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "open a fresh ticket for Maya");
  await expect(page.getByTestId("selected-issue-id")).toHaveText("PIX-143");

  await page.reload();
  await expect(page.getByTestId("current-view-title")).toHaveText("Dashboard");
  await page.getByTestId("nav-issues").click();

  await expect(page.getByText("PIX-143 - Maya Chen - Issue Triage")).toBeVisible();
});

test("shows and highlights the create ticket entry point", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "where to create tickets for the users?");

  await expect(page.getByTestId("current-view-title")).toHaveText("Issues");
  await expect(page.getByTestId("create-ticket-button")).toHaveClass(/highlighted-action/);
  await expect(page.getByTestId("transcript")).toContainText("highlight Create ticket");
});

test("asks who should own a ticket before opening an incomplete create flow", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "create a ticket");

  await expect(page.getByTestId("current-view-title")).toHaveText("Issues");
  await expect(page.getByTestId("create-ticket-button")).toHaveClass(/highlighted-action/);
  await expect(page.getByTestId("issue-create-panel")).toBeHidden();
  await expect(page.getByTestId("transcript")).toContainText("Who should own this ticket?");
});

test("validates an unknown assignee before continuing ticket creation", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "create a high priority ticket for Lucifer about GitHub onboarding");

  await expect(page.getByTestId("current-view-title")).toHaveText("Teams");
  await expect(page.getByTestId("team-member-create-panel")).toBeVisible();
  await expect(page.getByTestId("member-name-input")).toHaveValue("Lucifer");
  await expect(page.getByTestId("transcript")).toContainText(
    "Lucifer is not in the team directory yet"
  );
  await expect(page.getByTestId("transcript")).not.toContainText("I created");

  await page.getByTestId("submit-create-member").click();

  await expect(page.getByTestId("current-view-title")).toHaveText("Issues");
  await expect(page.getByTestId("issue-create-panel")).toBeVisible();
  await expect(page.getByTestId("ticket-assignee-select")).toHaveValue("Lucifer");
  await expect(page.getByTestId("ticket-title-input")).toHaveValue("Github Onboarding");
  await expect(page.getByTestId("transcript")).toContainText(
    "Lucifer has been added. I'll open the ticket form with Lucifer selected."
  );

  await page.getByTestId("submit-create-ticket").click();

  await expect(page.getByTestId("current-view-title")).toHaveText("Issue Detail");
  await expect(page.getByTestId("assignee-control")).toContainText("Lucifer");
  await expect(page.getByText("Created now")).toBeVisible();
});

test("uses voice transcripts as voice-mode turns through the same action pipeline", async ({
  page
}) => {
  await installMockVoice(page);
  await page.unroute(agentApiRoute);
  await proxyNonTurnToFreshBackend(page);
  let sawVoiceMode = false;

  await page.route(agentTurnRoute, async (route) => {
    const body = route.request().postDataJSON();
    if (body?.message === "show sprint planning") {
      sawVoiceMode = body.input_mode === "voice";
    }
    const response = await route.fetch({
      url: freshBackendUrl(route.request().url())
    });
    await route.fulfill({ response });
  });

  await openApp(page);
  await expect(page.getByTestId("voice-status")).toHaveText("Voice: Ready");

  await page.getByTestId("voice-toggle").click();
  await expect(page.getByTestId("voice-status")).toHaveText("Voice: Listening");

  await page.evaluate(() => window.__emitVoiceTranscript?.("show sprint planning"));

  await expect(page.getByTestId("current-view-title")).toHaveText("Cycles");
  await expect(page.getByTestId("transcript")).toContainText("show sprint planning");
  expect(sawVoiceMode).toBe(true);
});

test("waits for voice silence before sending the completed spoken turn", async ({ page }) => {
  await installMockVoice(page);
  await page.unroute(agentApiRoute);
  await proxyNonTurnToFreshBackend(page);
  const voiceMessages: string[] = [];

  await page.route(agentTurnRoute, async (route) => {
    const body = route.request().postDataJSON();
    voiceMessages.push(body.message);
    const response = await route.fetch({
      url: freshBackendUrl(route.request().url())
    });
    await route.fulfill({ response });
  });

  await openApp(page);

  await page.getByTestId("voice-toggle").click();
  await page.evaluate(() => window.__emitVoiceTranscript?.("show sprint"));
  await page.waitForTimeout(25);
  await page.evaluate(() => window.__emitVoiceTranscript?.("planning"));

  await expect(page.getByTestId("current-view-title")).toHaveText("Cycles");
  expect(voiceMessages).toEqual(["show sprint planning"]);
});

test("handles voice typo input and voice-only demo issue creation", async ({ page }) => {
  await installMockVoice(page);
  await openApp(page);

  await page.getByTestId("voice-toggle").click();
  await page.evaluate(() => window.__emitVoiceTranscript?.("open tikit for maya"));

  await expect(page.getByTestId("current-view-title")).toHaveText("Issue Detail");
  await expect(page.getByTestId("selected-issue-id")).toHaveText("LIN-142");

  await page.getByTestId("voice-toggle").click();
  await expect(page.getByTestId("voice-status")).toHaveText("Voice: Listening");
  await page.evaluate(() => window.__emitVoiceTranscript?.("open a fresh ticket for maya"));

  await expect(page.getByTestId("turn-status")).toHaveText("Ready");
  await expect(page.getByTestId("selected-issue-id")).toContainText(/^PIX-\d+$/);
  await expect(page.getByTestId("transcript")).toContainText("I created PIX-");
  await expect(page.getByTestId("current-view-title")).toHaveText("Issue Detail");
});

test("speaks assistant replies after voice input", async ({ page }) => {
  await installMockVoice(page);
  await openApp(page);

  await page.getByTestId("voice-toggle").click();
  await page.evaluate(() => window.__emitVoiceTranscript?.("show sprint planning"));

  await expect(page.getByTestId("current-view-title")).toHaveText("Cycles");
  await expect
    .poll(async () => page.evaluate(() => window.__spokenAgentReplies ?? []))
    .toContainEqual(expect.stringContaining("I'll show you the current cycle"));
});

test("answers identity questions without generic routing", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "Hii there who are u");

  await expect(page.getByTestId("transcript")).toContainText(
    "I'm Edith, Pixel's live demo guide."
  );
});

test("handles greetings, capabilities, and visitor introduction naturally", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "Hii There?");
  await expect(page.getByTestId("transcript")).toContainText(
    "Hi there. What would you like to explore first in Pixel?"
  );

  await sendChat(page, "What are you capable of doing?");
  await expect(page.getByTestId("transcript")).toContainText(
    "I can guide this Pixel demo through Product Engineering Workspace"
  );

  await sendChat(page, "HI there i am Pushkar!");
  await expect(page.getByTestId("transcript")).toContainText(
    "Nice to meet you, Pushkar."
  );

  await sendChat(page, "Hi");
  await expect(page.getByTestId("transcript")).toContainText(
    "Hi Pushkar. What would you like to explore next in Pixel?"
  );
});

test("does not treat mixed create-and-assign phrasing as old ticket lookup", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "open a ticket for Maya and assign to Jen");

  await expect(page.getByTestId("current-view-title")).toHaveText("Teams");
  await expect(page.getByTestId("team-member-create-panel")).toBeVisible();
  await expect(page.getByTestId("member-name-input")).toHaveValue("Jen");
  await expect(page.getByTestId("transcript")).toContainText(
    "Jen is not in the team directory yet"
  );
});

test("opens add-member flow from natural member creation phrasing", async ({ page }) => {
  await openApp(page);

  await sendChat(page, "can you add a new member Lucife");

  await expect(page.getByTestId("current-view-title")).toHaveText("Teams");
  await expect(page.getByTestId("team-member-create-panel")).toBeVisible();
  await expect(page.getByTestId("member-name-input")).toHaveValue("Lucife");
});

test("turns agent speech into listening when the user presses voice", async ({ page }) => {
  await installMockVoice(page);
  await openApp(page);

  await page.getByTestId("voice-toggle").click();
  await page.evaluate(() => window.__emitVoiceTranscript?.("show sprint planning"));
  await expect(page.getByTestId("voice-status")).toHaveText("Voice: Speaking");

  await page.getByTestId("voice-toggle").click();

  await expect(page.getByTestId("voice-status")).toHaveText("Voice: Listening");
});

test("stops agent speech and listens when the visitor presses voice during speech", async ({ page }) => {
  await installMockVoice(page);
  await page.unroute(agentApiRoute);
  await proxyNonTurnToFreshBackend(page);
  const voiceMessages: string[] = [];

  await page.route(agentTurnRoute, async (route) => {
    const body = route.request().postDataJSON();
    voiceMessages.push(body.message);
    const response = await route.fetch({
      url: freshBackendUrl(route.request().url())
    });
    await route.fulfill({ response });
  });

  await openApp(page);

  await page.getByTestId("voice-toggle").click();
  await page.evaluate(() => window.__emitVoiceTranscript?.("show sprint planning"));
  await expect(page.getByTestId("voice-status")).toHaveText("Voice: Speaking");

  await page.getByTestId("voice-toggle").click();
  await expect(page.getByTestId("voice-status")).toHaveText("Voice: Listening");
  await page.evaluate(() => window.__emitVoiceTranscript?.("set up github integration"));

  await expect(page.getByTestId("current-view-title")).toHaveText("Integrations");
  await expect(page.getByTestId("github-setup-panel")).toContainText("Select repositories");
  expect(voiceMessages).toEqual(["show sprint planning", "set up github integration"]);
});

test("opens integrations for GitHub and Slack, then blocks out-of-product requests", async ({
  page
}) => {
  await openApp(page);

  await sendChat(page, "how does github integration work");
  await expect(page.getByTestId("current-view-title")).toHaveText("Integrations");
  await expect(page.getByTestId("github-integration-card")).toHaveClass(/highlighted-card/);

  await sendChat(page, "What can Pixel do with Slack?");
  await expect(page.getByTestId("current-view-title")).toHaveText("Integrations");
  await expect(page.getByTestId("slack-integration-card")).toHaveClass(/highlighted-card/);
  await expect(page.getByTestId("transcript")).toContainText("Slack lets teams create issues");

  await sendChat(page, "set up github integration");
  await expect(page.getByTestId("current-view-title")).toHaveText("Integrations");
  await expect(page.getByTestId("github-integration-card")).toHaveClass(/highlighted-card/);
  await expect(page.getByTestId("github-setup-panel")).toContainText("Select repositories");
  await expect(page.getByTestId("transcript")).toContainText("GitHub setup flow");

  await sendChat(page, "open salesforce");
  await expect(page.getByTestId("turn-status")).toHaveText("Action blocked");
  await expect(page.getByTestId("current-view-title")).toHaveText("Integrations");
  await expect(page.getByTestId("transcript")).toContainText(
    "I can only demonstrate Pixel workflows here"
  );
});

test("cancels an active turn and ignores the delayed stale result", async ({ page }) => {
  await page.unroute(agentApiRoute);
  await proxyNonTurnToFreshBackend(page);
  let turnRequestCount = 0;
  let releaseFirstTurn: () => void = () => undefined;
  const firstTurnCanContinue = new Promise<void>((resolve) => {
    releaseFirstTurn = resolve;
  });

  await page.route(agentCancelTurnOneRoute, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        session_id: "cancelled",
        turn_id: 1,
        status: "cancelled"
      }
    });
  });

  await page.route(agentTurnRoute, async (route) => {
    turnRequestCount += 1;
    if (turnRequestCount === 1) {
      await firstTurnCanContinue;
      await route.fulfill({
        contentType: "application/json",
        json: {
          session_id: "delayed",
          turn_id: 1,
          status: "completed",
          speech: "I'll show you the current cycle.",
          proposed_action: { type: "OPEN_CYCLES", payload: {} },
          validated_action: { type: "OPEN_CYCLES", payload: {} },
          intent_trace: {
            goal: "Sprint planning",
            relevant_feature: "Cycles",
            reason: "Delayed response used by the stale-turn test.",
            confidence: 0.8,
            status: "active"
          },
          signals: [],
          retrieved_context: []
        }
      });
      return;
    }
    const response = await route.fetch({
      url: freshBackendUrl(route.request().url())
    });
    await route.fulfill({ response });
  });

  await openApp(page);

  await page.getByTestId("chat-input").fill("show sprint planning");
  await page.getByTestId("chat-send").click();
  await expect(page.getByTestId("turn-status")).toHaveText("Thinking");

  try {
    const cancelRequest = page.waitForRequest((request) =>
      new URL(request.url()).pathname === "/api/agent/turn/1/cancel"
    );
    await page.getByTestId("chat-input").fill("open ticket for maya");
    await page.getByTestId("chat-send").click();
    await cancelRequest;

    await expect(page.getByTestId("current-view-title")).toHaveText("Issue Detail");
    await expect(page.getByTestId("selected-issue-id")).toHaveText("LIN-142");
  } finally {
    releaseFirstTurn();
  }


  await expect(page.getByTestId("current-view-title")).toHaveText("Issue Detail");
  await expect(page.getByTestId("selected-issue-id")).toHaveText("LIN-142");
});

test("shows a graceful chat error when the agent API cannot be reached", async ({ page }) => {
  await page.route(agentTurnRoute, (route) => route.abort());
  await openApp(page);

  await sendChat(page, "show sprint planning");

  await expect(page.getByTestId("turn-status")).toHaveText("Action blocked");
  await expect(page.getByTestId("transcript")).toContainText(
    "I could not reach the demo agent service"
  );
});
