import { defineConfig, devices } from "@playwright/test";

const apiPort = 8101;
const webPort = 3000;
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
      command: `npm.cmd --workspace apps/web run dev -- --port ${webPort}`,
      env: {
        ...process.env,
        NEXT_PUBLIC_API_BASE_URL: `http://127.0.0.1:${apiPort}`
      },
      timeout: 120_000,
      url: webBaseUrl,
      reuseExistingServer: true
    }
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ]
});
