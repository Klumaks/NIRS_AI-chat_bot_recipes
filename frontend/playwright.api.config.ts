import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  outputDir: join(tmpdir(), "ai-chef-playwright-api"),
  testDir: "./e2e",
  testMatch: "api-mode.spec.ts",
  workers: 1,
  use: { ...devices["Desktop Chrome"], baseURL: "http://localhost:5174" },
  webServer: {
    command: "npm run dev:api -- --port 5174",
    url: "http://localhost:5174",
    reuseExistingServer: false,
    env: { VITE_API_BASE_URL: "http://127.0.0.1:58999/api/v1" },
    timeout: 60_000,
  },
});
