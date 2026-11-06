import { defineConfig, devices } from "@playwright/test";

// The e2e run owns its servers: a freshly seeded API on :8100 and Vite on :5174, so it never
// touches (or depends on) a developer's own servers on :8000/:5173.
const baseURL = "http://127.0.0.1:5174";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  use: { baseURL, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } }],
  webServer: [
    {
      command: "node scripts/backend.mjs",
      url: "http://127.0.0.1:8100/health",
      reuseExistingServer: false,
      timeout: 240_000,
      stdout: "ignore",
    },
    {
      command: "npm --prefix ../frontend run dev -- --host 127.0.0.1 --port 5174 --strictPort",
      url: baseURL,
      env: { VITE_API_PROXY_TARGET: "http://127.0.0.1:8100" },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
