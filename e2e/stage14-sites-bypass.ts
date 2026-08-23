import type { Page } from "../frontend/node_modules/@playwright/test";

export async function applySitesBypassHeader(page: Page): Promise<void> {
  const baseUrl = process.env.E2E_REAL_BASE_URL;
  const token = process.env.STAGE14_SITES_BYPASS_TOKEN;
  if (!baseUrl || !token) {
    return;
  }

  const allowedOrigin = new URL(baseUrl).origin;
  await page.route("**/*", async (route) => {
    const request = route.request();
    const headers = { ...request.headers() };
    delete headers["oai-sites-authorization"];
    if (new URL(request.url()).origin === allowedOrigin) {
      headers["OAI-Sites-Authorization"] = `Bearer ${token}`;
    }
    await route.continue({ headers });
  });
}
