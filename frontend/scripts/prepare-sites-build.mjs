import { access, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { extname } from "node:path";

const buildRoot = new URL("../dist/", import.meta.url);
const workerSource = new URL("../sites/worker.js", import.meta.url);
const workerTarget = new URL("../dist/server/index.js", import.meta.url);
const assetMarker = JSON.stringify("__SITES_BUNDLED_ASSETS__");

const contentTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".gif", "image/gif"],
  [".html", "text/html; charset=utf-8"],
  [".ico", "image/x-icon"],
  [".jpeg", "image/jpeg"],
  [".jpg", "image/jpeg"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".map", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml; charset=utf-8"],
  [".txt", "text/plain; charset=utf-8"],
  [".wasm", "application/wasm"],
  [".webp", "image/webp"],
  [".woff", "font/woff"],
  [".woff2", "font/woff2"],
  [".xml", "application/xml; charset=utf-8"],
]);

const textExtensions = new Set([
  ".css",
  ".html",
  ".js",
  ".json",
  ".map",
  ".svg",
  ".txt",
  ".xml",
]);

async function collectAssets(directory, relativeDirectory = "") {
  const entries = await readdir(directory, { withFileTypes: true });
  entries.sort((left, right) => left.name.localeCompare(right.name));

  const assets = [];
  for (const entry of entries) {
    const relativePath = relativeDirectory
      ? `${relativeDirectory}/${entry.name}`
      : entry.name;
    if (relativePath === "server" || relativePath.startsWith("server/")) {
      continue;
    }
    if (relativePath === ".openai" || relativePath.startsWith(".openai/")) {
      continue;
    }

    const entryUrl = new URL(entry.name, directory);
    if (entry.isDirectory()) {
      assets.push(...(await collectAssets(new URL(`${entry.name}/`, directory), relativePath)));
      continue;
    }
    if (!entry.isFile()) {
      throw new Error(`Unsupported Sites build entry: ${relativePath}`);
    }

    const extension = extname(entry.name).toLowerCase();
    const body = await readFile(entryUrl);
    assets.push([
      `/${relativePath}`,
      {
        ...(textExtensions.has(extension)
          ? { body: body.toString("utf8") }
          : { bodyBytes: [...body] }),
        contentType:
          contentTypes.get(extension) ?? "application/octet-stream",
      },
    ]);
  }
  return assets;
}

await access(new URL("index.html", buildRoot));
const assets = await collectAssets(buildRoot);
if (!assets.some(([pathname]) => pathname === "/index.html")) {
  throw new Error("Sites build is missing /index.html");
}

const workerTemplate = await readFile(workerSource, "utf8");
if (workerTemplate.split(assetMarker).length !== 2) {
  throw new Error("Sites Worker must contain exactly one asset marker");
}

await mkdir(new URL("server/", buildRoot), { recursive: true });
await writeFile(
  workerTarget,
  workerTemplate.replace(assetMarker, () => JSON.stringify(Object.fromEntries(assets))),
  "utf8",
);
