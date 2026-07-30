import { afterEach, describe, expect, it, vi } from "vitest";

import type { BrowserSession } from "../auth/AuthContext";
import type { ExportView } from "./AppApiContext";
import { createHttpAppApi } from "./httpAppApi";

const session: BrowserSession = { accessToken: "teacher-token" };
const exportView: ExportView = {
  id: "33333333-3333-4333-8333-333333333333",
  assignment_id: "44444444-4444-4444-8444-444444444444",
  grading_job_id: "22222222-2222-4222-8222-222222222222",
  assignment_title: "Argumentative essay",
  export_type: "draft",
  status: "queued",
  paper_count: 100,
  source_counts: { ai_suggestion: 100 },
  safe_filename: null,
  error_code: null,
  snapshot_at: "2026-07-22T00:00:00Z",
  started_at: null,
  finished_at: null,
  created_at: "2026-07-22T00:00:00Z",
};

afterEach(() => vi.unstubAllGlobals());

describe("stage 12 HTTP transport", () => {
  it("uses the exact export paths, request body, auth, and idempotency header", async () => {
    const requests: Request[] = [];
    const responses: unknown[] = [
      [],
      exportView,
      exportView,
      {
        download_url: "https://storage.example.test/signed",
        expires_in_seconds: 60,
        filename: "grades.xlsx",
      },
    ];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      requests.push(new Request(input, init));
      return new Response(JSON.stringify(responses.shift()), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      });
    });
    const api = createHttpAppApi("https://api.example.test/");

    await api.listExports(session);
    await api.createExport(
      session,
      exportView.grading_job_id,
      "draft",
      "same-click-key",
    );
    await api.getExport(session, exportView.id);
    await api.createExportDownload(session, exportView.id);

    expect(requests.map((request) => [request.method, request.url])).toEqual([
      ["GET", "https://api.example.test/exports"],
      ["POST", "https://api.example.test/exports"],
      ["GET", `https://api.example.test/exports/${exportView.id}`],
      ["POST", `https://api.example.test/exports/${exportView.id}/download`],
    ]);
    expect(requests.every((request) => request.headers.get("Authorization") === "Bearer teacher-token")).toBe(true);
    expect(requests[1].headers.get("Idempotency-Key")).toBe("same-click-key");
    await expect(requests[1].clone().json()).resolves.toEqual({
      grading_job_id: exportView.grading_job_id,
      export_type: "draft",
    });
  });
});
