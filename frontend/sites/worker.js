const SECURITY_HEADERS = {
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

const BUNDLED_ASSETS = Object.freeze("__SITES_BUNDLED_ASSETS__");

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

function bundledAssetBody(asset) {
  if (typeof asset.body === "string") {
    return asset.body;
  }
  if (Array.isArray(asset.bodyBytes)) {
    return Uint8Array.from(asset.bodyBytes);
  }
  throw new Error("Bundled Sites asset body is invalid.");
}

function bundledAssetResponse(pathname, method) {
  const asset = BUNDLED_ASSETS[pathname];
  if (!asset) {
    return null;
  }

  return new Response(method === "HEAD" ? null : bundledAssetBody(asset), {
    headers: {
      "Content-Type": asset.contentType,
    },
  });
}

async function fetchExternalAsset(request, environment) {
  if (!environment.ASSETS?.fetch) {
    return new Response(null, { status: 404 });
  }
  return environment.ASSETS.fetch(request);
}

export default {
  async fetch(request, environment) {
    const pathname = new URL(request.url).pathname;
    let response = null;

    if (request.method === "GET" || request.method === "HEAD") {
      response = bundledAssetResponse(pathname, request.method);
    }

    response ??= await fetchExternalAsset(request, environment);
    if (request.method === "GET" && response.status === 404 && acceptsHtml(request)) {
      response = bundledAssetResponse("/index.html", request.method);
      if (!response) {
        const indexUrl = new URL("/index.html", request.url);
        response = await fetchExternalAsset(new Request(indexUrl, request), environment);
      }
    }

    return withSecurityHeaders(response);
  },
};
