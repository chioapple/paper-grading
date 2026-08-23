import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "@playwright/test";

const baseURL = process.env.E2E_REAL_BASE_URL;
const outputDir = process.env.STAGE14_E2E_OUTPUT_DIR;
const configDir = path.dirname(fileURLToPath(import.meta.url));
let parsedBaseUrl: URL | undefined;
try {
  parsedBaseUrl = baseURL ? new URL(baseURL) : undefined;
} catch {
  parsedBaseUrl = undefined;
}
if (
  process.env.E2E_REAL !== "true" ||
  !parsedBaseUrl ||
  parsedBaseUrl.protocol !== "https:" ||
  parsedBaseUrl.username ||
  parsedBaseUrl.password ||
  parsedBaseUrl.pathname !== "/" ||
  parsedBaseUrl.search ||
  parsedBaseUrl.hash ||
  baseURL !== parsedBaseUrl.origin
) {
  throw new Error("真实浏览器验收必须显式设置 E2E_REAL=true 和 HTTPS E2E_REAL_BASE_URL");
}
if (!outputDir || !path.isAbsolute(outputDir)) {
  throw new Error("真实浏览器验收必须显式设置绝对路径 STAGE14_E2E_OUTPUT_DIR");
}

export default defineConfig({
  testDir: "../e2e",
  testMatch: "real-full-flow.spec.ts",
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  timeout: 1_800_000,
  outputDir: outputDir,
  reporter: [[path.resolve(configDir, "../e2e/stage14-playwright-reporter.mjs")]],
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
