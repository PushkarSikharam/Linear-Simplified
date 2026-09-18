import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { sendAgentTurn } from "@/lib/agent-api";
import { ensureDemoLogin, RateLimitedError, setAuthToken } from "@/lib/product-data-api";

// The public page runs as an anonymous visitor. It must never sign in as an administrator,
// never reset the demo data every visitor shares, and never mistake a rate limit for an outage.
const WEB_ROOT = join(__dirname, "..");
const SOURCE_DIRS = ["app", "lib", "types"];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

const TURN = {
  sessionId: "session-1",
  turnId: 1,
  productId: "linear_simplified",
  message: "Show sprint planning",
  inputMode: "text" as const,
  currentPage: "dashboard",
  workspaceScopeId: "workspace-product-eng"
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAuthToken(null);
});

describe("public demo boundary", () => {
  const files = SOURCE_DIRS.flatMap((dir) => sourceFiles(join(WEB_ROOT, dir)));

  it("never names an administrator identity or the shared data reset", () => {
    const violations = files.flatMap((file) => {
      const source = readFileSync(file, "utf8");
      return [/demo-admin/, /demo-data\/reset/]
        .filter((pattern) => pattern.test(source))
        .map((pattern) => `${relative(WEB_ROOT, file)}: ${pattern}`);
    });
    expect(violations).toEqual([]);
  });

  it("signs in as the public demo visitor by default", async () => {
    const request = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(200, { token: "visitor-token" }));
    vi.stubGlobal("fetch", request);

    await ensureDemoLogin();

    const [, init] = request.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toEqual({ user_id: "demo-visitor" });
  });
});

describe("rate limits", () => {
  it("reports a throttled sign-in as a rate limit, not a failure", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(429, { detail: "Too many" })));

    await expect(ensureDemoLogin()).rejects.toBeInstanceOf(RateLimitedError);
  });

  it("reports a throttled turn as a rate limit, not a failure", async () => {
    setAuthToken("visitor-token");
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(429, { detail: "Too many" })));

    await expect(sendAgentTurn(TURN)).rejects.toBeInstanceOf(RateLimitedError);
  });

  it("still reports other failures as failures", async () => {
    setAuthToken("visitor-token");
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(503, { detail: "Down" })));

    const failure = sendAgentTurn(TURN);
    await expect(failure).rejects.toThrow("Agent request failed with 503");
    await expect(failure).rejects.not.toBeInstanceOf(RateLimitedError);
  });
});
