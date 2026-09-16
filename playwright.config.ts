import { defineConfig, devices } from "@playwright/test";
import { E2E_SENTINEL_PORT } from "./tests/e2e/ports";

const webPort = 3100;
const webBaseUrl = `http://localhost:${webPort}`;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: {
    timeout: 10_000
  },
  fullyParallel: false,
  reporter: [["list"], ["html", { open: "never" }]],
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
