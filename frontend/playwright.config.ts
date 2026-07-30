import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "../e2e",
  testMatch: "local-full-flow.spec.ts",
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  timeout: 60_000,
  reporter: [["line"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "desktop-chromium",
      use: { browserName: "chromium", viewport: { width: 1440, height: 900 } },
    },
    {
      name: "mobile-chromium",
      use: { browserName: "chromium", viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: [
    {
      command: "node ../e2e/local-mock-server.mjs",
      url: "http://127.0.0.1:54321/mock/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5173",
      url: "http://127.0.0.1:5173/login",
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        VITE_API_BASE_URL: "http://127.0.0.1:54321/mock/api",
        VITE_SUPABASE_URL: "http://127.0.0.1:54321/mock/supabase",
        VITE_SUPABASE_PUBLISHABLE_KEY: "test-publishable-key",
      },
    },
  ],
});
