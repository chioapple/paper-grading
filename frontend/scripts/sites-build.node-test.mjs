import assert from "node:assert/strict";
import test from "node:test";

async function loadWorker() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  return (await import(workerUrl.href)).default;
}

function assetEnvironment() {
  return {
    ASSETS: {
      async fetch(request) {
        const pathname = new URL(request.url).pathname;
        if (pathname === "/index.html") {
          return new Response("<!doctype html><title>Paper Grading</title>", {
            headers: { "Content-Type": "text/html; charset=utf-8" },
          });
        }
        if (pathname === "/assets/app.js") {
          return new Response("export {}", {
            headers: { "Content-Type": "text/javascript" },
          });
        }
        return new Response("Not found", { status: 404 });
      },
    },
  };
}

function assertSecurityHeaders(response) {
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.equal(response.headers.get("x-frame-options"), "DENY");
  assert.equal(response.headers.get("referrer-policy"), "no-referrer");
  assert.equal(
    response.headers.get("permissions-policy"),
    "camera=(), microphone=(), geolocation=()",
  );
}

test("Sites Worker 为前端路由返回 SPA 入口", async () => {
  const worker = await loadWorker();
  const response = await worker.fetch(
    new Request("https://paper-grading.example/assignments", {
      headers: { Accept: "text/html" },
    }),
    assetEnvironment(),
  );

  assert.equal(response.status, 200);
  assert.match(await response.text(), /Paper Grading/);
  assertSecurityHeaders(response);
});

test("Sites Worker 在外部静态资源绑定为空时仍能返回已构建页面", async () => {
  const worker = await loadWorker();
  const environment = {
    ASSETS: {
      async fetch() {
        return new Response(null, { status: 404 });
      },
    },
  };
  const pageResponse = await worker.fetch(
    new Request("https://paper-grading.example/login", {
      headers: { Accept: "text/html" },
    }),
    environment,
  );

  assert.equal(pageResponse.status, 200);
  const page = await pageResponse.text();
  assert.match(page, /<div id="root"><\/div>/);
  assertSecurityHeaders(pageResponse);

  const scriptPath = page.match(/<script[^>]+src="([^"]+\.js)"/u)?.[1];
  assert.ok(scriptPath);
  const scriptResponse = await worker.fetch(
    new Request(new URL(scriptPath, "https://paper-grading.example")),
    environment,
  );
  assert.equal(scriptResponse.status, 200);
  assert.match(scriptResponse.headers.get("content-type"), /^text\/javascript/u);
  assert.ok((await scriptResponse.arrayBuffer()).byteLength > 100_000);
  assertSecurityHeaders(scriptResponse);
});

test("Sites Worker 保留静态资源并拒绝把非 GET 请求改写成页面", async () => {
  const worker = await loadWorker();
  const environment = assetEnvironment();
  const asset = await worker.fetch(
    new Request("https://paper-grading.example/assets/app.js"),
    environment,
  );
  const post = await worker.fetch(
    new Request("https://paper-grading.example/assignments", {
      method: "POST",
      headers: { Accept: "text/html" },
    }),
    environment,
  );

  assert.equal(asset.status, 200);
  assert.equal(post.status, 404);
  assertSecurityHeaders(asset);
  assertSecurityHeaders(post);
});
