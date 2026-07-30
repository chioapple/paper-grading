import { defineConfig } from "@playwright/test";

const baseURL = process.env.E2E_REAL_BASE_URL;
if (process.env.E2E_REAL !== "true" || !baseURL?.startsWith("https://")) {
  throw new Error("真实浏览器验收必须显式设置 E2E_REAL=true 和 HTTPS E2E_REAL_BASE_URL");
}

export default defineConfig({
  testDir: "../e2e",
  testMatch: "real-full-flow.spec.ts",
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  timeout: 900_000,
  reporter: [["line"]],
  use: {
    baseURL,
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  projects: [
    {
      name: "real-chromium",
      use: { browserName: "chromium", viewport: { width: 1440, height: 900 } },
    },
  ],
});
