import { access, copyFile, mkdir } from "node:fs/promises";

const buildRoot = new URL("../dist/", import.meta.url);
const workerSource = new URL("../sites/worker.js", import.meta.url);
const workerTarget = new URL("../dist/server/index.js", import.meta.url);

await access(new URL("index.html", buildRoot));
await mkdir(new URL("server/", buildRoot), { recursive: true });
await copyFile(workerSource, workerTarget);
