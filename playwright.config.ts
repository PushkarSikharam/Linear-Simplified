import { defineConfig, devices } from "@playwright/test";
import { E2E_SENTINEL_PORT } from "./tests/e2e/ports";

const webPort = 3100;
const webBaseUrl = `http://localhost:${webPort}`;

export default defineConfig({
  // Core browser tests, plus each product package's own browser tests.
  testDir: ".",
  testMatch: ["tests/e2e/**/*.spec.ts", "products/*/tests/**/*.spec.ts"],
  timeout: 30_000,
  expect: {
    timeout: 10_000
  },
  fullyParallel: false,
  // Every spec file starts its own isolated API and the fixed-port sentinel.
  workers: 1,
  // In CI, the github reporter turns each failure into a public annotation on the run.
  reporter: process.env.CI
    ? [["github"], ["list"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: webBaseUrl,
    trace: "on-first-retry"
  },
  webServer: [
    {
      command: `npx next dev --port ${webPort}`,
      cwd: "apps/web",
      env: {
        ...process.env,
        PIXEL_TEST_BUILD: "1",
        NEXT_PUBLIC_API_BASE_URL: "/api/agent",
        // The browser signs in exactly as a public visitor does in production, whatever a
        // developer's local environment files say.
        NEXT_PUBLIC_PIXEL_DEMO_USER: "demo-visitor",
        // Never let the test server fall through to the development backend.
        PIXEL_AGENT_API_BASE_URL: `http://127.0.0.1:${E2E_SENTINEL_PORT}/api`
      },
      timeout: 120_000,
      url: webBaseUrl,
      reuseExistingServer: false
    }
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ]
});
