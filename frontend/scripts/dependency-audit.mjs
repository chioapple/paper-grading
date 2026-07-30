import { spawnSync } from "node:child_process";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ALLOWED_RSC_ADVISORY = "https://github.com/advisories/GHSA-qwww-vcr4-c8h2";
const RSC_MARKERS =
  /\b(?:RSCHydratedRouter|RSCStaticRouter|ServerRouter|StaticRouterProvider|createStaticHandler|getRSCStream|routeRSCServerRequest|unstable_[A-Za-z0-9_]*RSC)\b|react-router\/(?:dom\/server|server)|react-server/i;

export function assessAudit(audit) {
  if (!audit || audit.auditReportVersion !== 2 || !audit.vulnerabilities) {
    return { ok: false, reason: "npm audit 未返回可验证的漏洞报告" };
  }
  const names = Object.keys(audit.vulnerabilities).sort();
  if (names.length === 0) return { ok: true, reason: "没有已知漏洞" };
  if (names.join(",") !== "react-router,react-router-dom") {
    return { ok: false, reason: "存在未批准的依赖漏洞" };
  }

  const router = audit.vulnerabilities["react-router"];
  const dom = audit.vulnerabilities["react-router-dom"];
  const advisories = router.via.filter((item) => typeof item === "object");
  if (
    router.severity !== "high" ||
    dom.severity !== "high" ||
    advisories.length !== 1 ||
    advisories[0].url !== ALLOWED_RSC_ADVISORY ||
    dom.via.length !== 1 ||
    dom.via[0] !== "react-router"
  ) {
    return { ok: false, reason: "React Router 漏洞集合超出已审计的 RSC 公告" };
  }
  return { ok: true, reason: "唯一公告仅影响未使用的不稳定 RSC API" };
}

export function findRscUsage(rootDirectory) {
  const matches = [];
  const visit = (directory) => {
    for (const name of readdirSync(directory)) {
      const path = join(directory, name);
      const stat = statSync(path);
      if (stat.isDirectory()) {
        visit(path);
      } else if (/\.(?:ts|tsx|js|jsx|mjs)$/.test(name)) {
        const source = readFileSync(path, "utf8");
        if (RSC_MARKERS.test(source)) matches.push(path);
      }
    }
  };
  visit(rootDirectory);
  return matches;
}

function main() {
  const scriptDirectory = dirname(fileURLToPath(import.meta.url));
  const frontendRoot = resolve(scriptDirectory, "..");
  const packageJson = JSON.parse(readFileSync(join(frontendRoot, "package.json"), "utf8"));
  const packageLock = JSON.parse(readFileSync(join(frontendRoot, "package-lock.json"), "utf8"));
  const lockedRouter = packageLock.packages?.["node_modules/react-router-dom"]?.version;
  const lockedBrace = packageLock.packages?.["node_modules/brace-expansion"]?.version;
  if (
    packageJson.dependencies?.["react-router-dom"] !== "7.18.1" ||
    lockedRouter !== "7.18.1" ||
    packageJson.overrides?.["brace-expansion"] !== "5.0.8" ||
    lockedBrace !== "5.0.8"
  ) {
    throw new Error("依赖声明与已审计锁定版本不一致");
  }

  const rscUsage = findRscUsage(join(frontendRoot, "src"));
  if (rscUsage.length > 0) {
    throw new Error("检测到 RSC/SSR API；不得应用 RSC 公告例外");
  }

  const result = spawnSync("npm", ["audit", "--omit=dev", "--json"], {
    cwd: frontendRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  let audit;
  try {
    audit = JSON.parse(result.stdout);
  } catch {
    throw new Error("npm audit 无法解析；依赖门禁失败");
  }
  const assessment = assessAudit(audit);
  if (!assessment.ok) throw new Error(assessment.reason);
  console.log(`dependency_audit_passed: ${assessment.reason}`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  try {
    main();
  } catch (error) {
    console.error(`dependency_audit_failed: ${error.message}`);
    process.exitCode = 1;
  }
}
