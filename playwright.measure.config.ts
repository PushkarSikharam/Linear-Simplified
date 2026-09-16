import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";
import { venvPython } from "./scripts/venv-python.mjs";

// Provider usage measurement. Paid providers stay switched off unless MEASURE_PAID=true,
// which must only be set after spending has been explicitly authorized.
//
// MEASURE_BASE_URL   measure an already-running app instead of starting one (e.g. an older commit)
// MEASURE_ATTEMPT_CEILING, MEASURE_SPEECH_ATTEMPTS, MEASURE_ENABLE_VOICE: see the measurement spec.
const paid = process.env.MEASURE_PAID === "true";
const ceiling = process.env.MEASURE_ATTEMPT_CEILING ?? "20";
const apiPort = 8197;
const webPort = 3200;
// Computed once in the main process; workers inherit it.
process.env.PIXEL_MEASURE_DB ??= join(tmpdir(), `pixel-measure-${Date.now()}.sqlite3`);
process.env.MEASURE_API_URL ??= process.env.MEASURE_BASE_URL ? "" : `http://127.0.0.1:${apiPort}`;

const startServers = !process.env.MEASURE_BASE_URL;

export default defineConfig({
  testDir: "./tests/measure",
  testMatch: "*.measure.ts",
  timeout: 180_000,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.MEASURE_BASE_URL ?? `http://localhost:${webPort}`,
    ...devices["Desktop Chrome"]
  },
  webServer: startServers
    ? [
        {
          command: `"${venvPython()}" -m uvicorn app.main:app --app-dir apps/api --port ${apiPort}`,
          url: `http://127.0.0.1:${apiPort}/health`,
          reuseExistingServer: false,
          timeout: 60_000,
          env: {
            ...process.env,
            PIXEL_DB_PATH: process.env.PIXEL_MEASURE_DB,
            PIXEL_SYNTHETIC_DEMO: "true",
            PIXEL_DEPLOYMENT_ID: "measurement",
            // Authoritative server-side ceiling across every provider attempt in this run.
            PIXEL_TOTAL_ATTEMPT_CAP: ceiling,
            PIXEL_PAID_PROVIDERS_ENABLED: paid ? "true" : "false",
            PIXEL_BLOCK_EXTERNAL_HTTP: paid ? "false" : "true"
          }
        },
        {
          command: `npx next dev --port ${webPort}`,
          cwd: "apps/web",
          url: `http://localhost:${webPort}`,
          reuseExistingServer: false,
          timeout: 120_000,
          env: {
            ...process.env,
            PIXEL_TEST_BUILD: "1",
            NEXT_PUBLIC_API_BASE_URL: "/api/agent",
            PIXEL_AGENT_API_BASE_URL: `http://127.0.0.1:${apiPort}/api`
          }
        }
      ]
    : undefined
});
