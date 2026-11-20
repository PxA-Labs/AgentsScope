import os from "node:os";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

/**
 * E2E smoke test against the real stack: the FastAPI server from
 * packages/server on a throwaway SQLite database, plus a production build of
 * this Next.js app (`next build && next start`).
 *
 * Environment:
 *   E2E_API_PORT / E2E_UI_PORT  ports to use (default 8765 / 3000, the
 *                               dashboard's defaults)
 *   E2E_PYTHON                  Python with packages/server/requirements.txt
 *                               installed (default "python3")
 */
const apiPort = Number(process.env.E2E_API_PORT || 8765);
const uiPort = Number(process.env.E2E_UI_PORT || 3000);
const python = process.env.E2E_PYTHON || "python3";

const API_URL = `http://127.0.0.1:${apiPort}`;
const WS_URL = `ws://127.0.0.1:${apiPort}`;
const UI_URL = `http://127.0.0.1:${uiPort}`;

// Read by the tests (which talk to the API directly) and the teardown.
process.env.E2E_API_URL = API_URL;
process.env.E2E_WS_URL = WS_URL;
// Computed once in the runner process; workers inherit it.
process.env.E2E_DB_PATH ||= path.join(os.tmpdir(), `agentscope-e2e-${Date.now()}.db`);
const dbPath = process.env.E2E_DB_PATH;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  globalTeardown: "./tests/e2e/global-teardown.ts",
  use: {
    baseURL: UI_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${python} -m uvicorn main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: path.join(__dirname, "..", "server"),
      url: `${API_URL}/health`,
      env: {
        DATABASE_URL: `sqlite+aiosqlite:///${dbPath}`,
        CORS_ALLOW_ORIGINS: `${UI_URL},http://localhost:${uiPort}`,
      },
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: `npx next build && npx next start --hostname 127.0.0.1 --port ${uiPort}`,
      url: UI_URL,
      env: {
        NEXT_PUBLIC_API_URL: API_URL,
        NEXT_PUBLIC_WS_URL: WS_URL,
      },
      reuseExistingServer: false,
      timeout: 240_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
