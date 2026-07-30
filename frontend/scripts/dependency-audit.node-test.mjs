import assert from "node:assert/strict";
import test from "node:test";

import { assessAudit } from "./dependency-audit.mjs";

const allowedAdvisory = {
  auditReportVersion: 2,
  vulnerabilities: {
    "react-router": {
      severity: "high",
      via: [
        {
          url: "https://github.com/advisories/GHSA-qwww-vcr4-c8h2",
        },
      ],
    },
    "react-router-dom": {
      severity: "high",
      via: ["react-router"],
    },
  },
};

test("accepts only the audited unstable RSC advisory", () => {
  assert.deepEqual(assessAudit(allowedAdvisory), {
    ok: true,
    reason: "唯一公告仅影响未使用的不稳定 RSC API",
  });
});

test("rejects any additional dependency vulnerability", () => {
  const report = structuredClone(allowedAdvisory);
  report.vulnerabilities["other-package"] = {
    severity: "high",
    via: [{ url: "https://example.invalid/advisory" }],
  };

  assert.deepEqual(assessAudit(report), {
    ok: false,
    reason: "存在未批准的依赖漏洞",
  });
});

test("rejects a changed React Router advisory set", () => {
  const report = structuredClone(allowedAdvisory);
  report.vulnerabilities["react-router"].via.push({
    url: "https://example.invalid/new-advisory",
  });

  assert.deepEqual(assessAudit(report), {
    ok: false,
    reason: "React Router 漏洞集合超出已审计的 RSC 公告",
  });
});
