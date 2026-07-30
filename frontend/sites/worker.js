const SECURITY_HEADERS = {
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function withSecurityHeaders(response) {
  const secured = new Response(response.body, response);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    secured.headers.set(name, value);
  }
  return secured;
}

function acceptsHtml(request) {
  return request.headers.get("accept")?.includes("text/html") ?? false;
}

export default {
  async fetch(request, environment) {
    if (!environment.ASSETS?.fetch) {
      return withSecurityHeaders(
        new Response("Static asset binding is unavailable.", { status: 503 }),
      );
    }

    let response = await environment.ASSETS.fetch(request);
    if (request.method === "GET" && response.status === 404 && acceptsHtml(request)) {
      const indexUrl = new URL("/index.html", request.url);
      response = await environment.ASSETS.fetch(new Request(indexUrl, request));
    }

    return withSecurityHeaders(response);
  },
};
