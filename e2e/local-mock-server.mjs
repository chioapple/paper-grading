import { createServer } from "node:http";

const HOST = "127.0.0.1";
const PORT = 54321;
const NOW = "2026-07-28T00:00:00Z";
const IDS = {
  admin: "00000000-0000-4000-8000-000000000001",
  teacher: "00000000-0000-4000-8000-000000000002",
  provider: "00000000-0000-4000-8000-000000000003",
  assignment: "00000000-0000-4000-8000-000000000004",
  rubric: "00000000-0000-4000-8000-000000000005",
  submission: "00000000-0000-4000-8000-000000000006",
  job: "00000000-0000-4000-8000-000000000007",
  item: "00000000-0000-4000-8000-000000000008",
  attempt: "00000000-0000-4000-8000-000000000009",
  review: "00000000-0000-4000-8000-000000000010",
  export: "00000000-0000-4000-8000-000000000011",
};

function initialState() {
  return {
    invited: false,
    assignment: null,
    submission: null,
    reviewStatus: "draft",
    export: null,
  };
}

let state = initialState();

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "http://127.0.0.1:5173",
    "Access-Control-Allow-Headers":
      "Authorization, Content-Type, Idempotency-Key, apikey, x-client-info, x-supabase-api-version",
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
    "Access-Control-Max-Age": "600",
    Vary: "Origin",
  };
}

function send(response, status, payload, extraHeaders = {}) {
  const body = payload === undefined ? "" : JSON.stringify(payload);
  response.writeHead(status, {
    ...corsHeaders(),
    ...extraHeaders,
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
  });
  response.end(body);
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  if (chunks.length === 0) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function tokenOf(request) {
  return (request.headers.authorization ?? "").replace(/^Bearer /, "");
}

function accountForToken(token) {
  if (token === "admin-token") {
    return {
      id: IDS.admin,
      email: "admin@example.test",
      display_name: "系统管理员",
      role: "admin",
      status: "active",
    };
  }
  if (token === "teacher-token") {
    return {
      id: IDS.teacher,
      email: "teacher@example.test",
      display_name: "测试教师",
      role: "teacher",
      status: "active",
    };
  }
  return null;
}

function rubric(status = "draft") {
  return {
    id: IDS.rubric,
    assignment_id: IDS.assignment,
    version: 1,
    status,
    original_rubric: "Content 20 points.",
    structured_rubric:
      status === "draft" && !state.assignment?.structured
        ? null
        : {
            schema_version: 1,
            total_score: "20",
            score_step: "1",
            dimensions: [
              {
                id: "content",
                name: "Content",
                description: "Quality of reasoning",
                max_score: "20",
                bands: [
                  {
                    label: "Meets",
                    min_score: "0",
                    max_score: "20",
                    description: "Evidence-based response",
                  },
                ],
                evidence_requirements: ["Quote the essay"],
              },
            ],
            deductions: [],
          },
    total_score: "20",
    score_step: "1",
    provider_config_id: status === "draft" && !state.assignment?.structured ? null : IDS.provider,
    model: status === "draft" && !state.assignment?.structured ? null : "safe-test-model",
    confirmed_at: status === "confirmed" ? NOW : null,
    created_at: NOW,
  };
}

function assignmentDetail() {
  const confirmed = state.assignment?.confirmed === true;
  const currentRubric = rubric(confirmed ? "confirmed" : "draft");
  return {
    id: IDS.assignment,
    title: state.assignment?.title ?? "Stage 14 essay",
    instructions: state.assignment?.instructions ?? "Write an argumentative essay.",
    status: confirmed ? "ready" : "draft",
    current_rubric_status: currentRubric.status,
    current_rubric_version: 1,
    current_draft_version: confirmed ? null : 1,
    current_confirmed_version: confirmed ? 1 : null,
    current_draft: confirmed ? null : { id: IDS.rubric, version: 1, status: "draft" },
    current_confirmed: confirmed
      ? { id: IDS.rubric, version: 1, status: "confirmed" }
      : null,
    created_at: NOW,
    updated_at: NOW,
    rubric_versions: [currentRubric],
  };
}

function jobSummary() {
  const confirmed = state.reviewStatus === "confirmed";
  return {
    id: IDS.job,
    assignment_id: IDS.assignment,
    assignment_title: assignmentDetail().title,
    model: "safe-test-model",
    status: confirmed ? "completed" : "needs_review",
    total: 1,
    needs_review: confirmed ? 0 : 1,
    completed: confirmed ? 1 : 0,
    failed: 0,
    items: [
      {
        id: IDS.item,
        submission_id: IDS.submission,
        original_filename: "stage14.docx",
        position: 0,
        status: confirmed ? "completed" : "needs_review",
        attempt_count: 1,
        error_code: null,
        review_available: true,
        review_id: state.reviewStatus === "saved" || confirmed ? IDS.review : null,
        review_revision: state.reviewStatus === "saved" || confirmed ? 1 : null,
        review_status: confirmed ? "confirmed" : state.reviewStatus === "saved" ? "draft" : null,
      },
    ],
    created_at: NOW,
    finished_at: confirmed ? NOW : null,
  };
}

function reviewDraft(status = "draft") {
  return {
    id: IDS.review,
    attempt_id: IDS.attempt,
    revision_number: 1,
    status,
    criteria: [
      {
        dimension_id: "content",
        score: "18",
        reason: "The response presents a clear evidence-based argument.",
        revision_suggestions: ["Develop the counterargument further."],
      },
    ],
    deductions: [],
    evidence: [
      {
        block_id: "b000001",
        quote: "Public transport improves access.",
        target_type: "dimension",
        target_id: "content",
      },
    ],
    overall_feedback: "A clear argument with relevant evidence.",
    change_reason: null,
    subtotal: "18",
    deduction_total: "0",
    final_score: "18",
    confirmed_at: status === "confirmed" ? NOW : null,
  };
}

function reviewDetail() {
  return {
    job_id: IDS.job,
    item_id: IDS.item,
    item_status: state.reviewStatus === "confirmed" ? "completed" : "needs_review",
    assignment_id: IDS.assignment,
    assignment_title: assignmentDetail().title,
    assignment_instructions: assignmentDetail().instructions,
    rubric_version_id: IDS.rubric,
    rubric_version: 1,
    rubric: rubric("confirmed").structured_rubric,
    submission_id: IDS.submission,
    original_filename: "stage14.docx",
    document: {
      schema_version: "document-blocks.v1",
      parser_version: "1",
      media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      page_count: null,
      character_count: 33,
      blocks: [
        {
          block_id: "b000001",
          text: "Public transport improves access.",
          locator: { kind: "docx_paragraph", paragraph: 1 },
        },
      ],
    },
    attempt: {
      id: IDS.attempt,
      attempt_number: 1,
      scoring_round: 1,
      model: "safe-test-model",
      subtotal: "18",
      deduction_total: "0",
      total_score: "18",
      dimensions: [
        {
          dimension_id: "content",
          score: "18",
          reason: "The response presents a clear evidence-based argument.",
          evidence: [{ block_id: "b000001", quote: "Public transport improves access." }],
          revision_suggestions: ["Develop the counterargument further."],
        },
      ],
      deductions: [],
      overall_feedback: "A clear argument with relevant evidence.",
    },
    draft: state.reviewStatus === "saved" || state.reviewStatus === "confirmed"
      ? reviewDraft(state.reviewStatus === "confirmed" ? "confirmed" : "draft")
      : null,
  };
}

function exportView() {
  return {
    id: IDS.export,
    assignment_id: IDS.assignment,
    assignment_title: assignmentDetail().title,
    grading_job_id: IDS.job,
    export_type: "final",
    status: "completed",
    paper_count: 1,
    source_counts: { teacher_confirmed: 1 },
    safe_filename: "stage14-final.xlsx",
    error_code: null,
    snapshot_at: NOW,
    started_at: NOW,
    finished_at: NOW,
    created_at: NOW,
  };
}

async function handleSupabase(request, response, url) {
  if (request.method === "POST" && url.pathname.endsWith("/auth/v1/token")) {
    const body = await readJson(request);
    const isAdmin = body.email === "admin@example.test";
    const token = isAdmin ? "admin-token" : "teacher-token";
    return send(response, 200, {
      access_token: token,
      token_type: "bearer",
      expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      refresh_token: `${token}-refresh`,
      user: {
        id: isAdmin ? IDS.admin : IDS.teacher,
        aud: "authenticated",
        role: "authenticated",
        email: body.email,
        app_metadata: {},
        user_metadata: {},
        created_at: NOW,
      },
    });
  }
  if (request.method === "POST" && url.pathname.endsWith("/auth/v1/logout")) {
    return send(response, 204);
  }
  return send(response, 404, { error: "mock_supabase_route_not_found" });
}

async function handleApi(request, response, url) {
  const path = url.pathname.replace("/mock/api", "");
  const account = accountForToken(tokenOf(request));
  if (!account) return send(response, 401, { detail: { code: "invalid_session" } });

  if (request.method === "GET" && path === "/auth/me") return send(response, 200, account);
  if (request.method === "POST" && path === "/auth/complete-invite") {
    return send(response, 200, account);
  }
  if (request.method === "GET" && path === "/admin/users") {
    return send(
      response,
      200,
      state.invited
        ? [
            {
              id: IDS.teacher,
              email: "teacher@example.test",
              display_name: "测试教师",
              status: "invited",
              invited_at: NOW,
            },
          ]
        : [],
    );
  }
  if (request.method === "POST" && path === "/admin/users/invitations") {
    state.invited = true;
    return send(response, 201, {
      id: IDS.teacher,
      email: "teacher@example.test",
      display_name: "测试教师",
      status: "invited",
      invited_at: NOW,
    });
  }
  if (request.method === "GET" && path === "/assignments") {
    return send(response, 200, state.assignment ? [assignmentDetail()] : []);
  }
  if (request.method === "POST" && path === "/assignments") {
    const body = await readJson(request);
    state.assignment = {
      title: body.title,
      instructions: body.instructions,
      structured: false,
      confirmed: false,
    };
    return send(response, 201, assignmentDetail());
  }
  if (request.method === "GET" && path === `/assignments/${IDS.assignment}`) {
    return send(response, 200, assignmentDetail());
  }
  if (request.method === "GET" && path === "/providers/models") {
    return send(response, 200, [
      {
        provider_id: IDS.provider,
        provider_name: "Stage 14 provider",
        provider_type: "deepseek",
        allowed_models: ["safe-test-model"],
        default_model: "safe-test-model",
      },
    ]);
  }
  if (
    request.method === "POST" &&
    path === `/assignments/${IDS.assignment}/rubrics/${IDS.rubric}/structure`
  ) {
    state.assignment.structured = true;
    return send(response, 200, rubric("draft"));
  }
  if (
    request.method === "POST" &&
    path === `/assignments/${IDS.assignment}/rubrics/${IDS.rubric}/confirm`
  ) {
    state.assignment.confirmed = true;
    return send(response, 200, assignmentDetail());
  }
  if (request.method === "GET" && path === `/assignments/${IDS.assignment}/submissions`) {
    return send(response, 200, state.submission ? [state.submission] : []);
  }
  if (request.method === "POST" && path === `/assignments/${IDS.assignment}/submissions`) {
    state.submission = {
      id: IDS.submission,
      assignment_id: IDS.assignment,
      original_filename: "stage14.docx",
      media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      file_size_bytes: 32,
      status: "ready",
      error_code: null,
      created_at: NOW,
    };
    return send(response, 201, { duplicate: false, submission: state.submission });
  }
  if (
    request.method === "POST" &&
    path === `/assignments/${IDS.assignment}/grading-jobs`
  ) {
    return send(response, 201, {
      id: IDS.job,
      assignment_id: IDS.assignment,
      status: "needs_review",
      total: 1,
    });
  }
  if (request.method === "GET" && path === "/grading-jobs") {
    return send(response, 200, state.submission ? [jobSummary()] : []);
  }
  if (
    request.method === "GET" &&
    path === `/grading-jobs/${IDS.job}/items/${IDS.item}/review`
  ) {
    return send(response, 200, reviewDetail());
  }
  if (
    request.method === "PUT" &&
    path === `/grading-jobs/${IDS.job}/items/${IDS.item}/review`
  ) {
    state.reviewStatus = "saved";
    return send(response, 200, reviewDraft());
  }
  if (
    request.method === "POST" &&
    path === `/grading-jobs/${IDS.job}/items/${IDS.item}/review/confirm`
  ) {
    state.reviewStatus = "confirmed";
    return send(response, 200, {
      reviews: [reviewDraft("confirmed")],
      completed_job_ids: [IDS.job],
    });
  }
  if (request.method === "GET" && path === "/exports") {
    return send(response, 200, state.export ? [state.export] : []);
  }
  if (request.method === "POST" && path === "/exports") {
    state.export = exportView();
    return send(response, 201, state.export);
  }
  if (request.method === "GET" && path === `/exports/${IDS.export}`) {
    return send(response, 200, exportView());
  }
  if (request.method === "POST" && path === `/exports/${IDS.export}/download`) {
    return send(response, 200, {
      download_url: `http://${HOST}:${PORT}/mock/download/stage14-final.xlsx`,
      expires_in_seconds: 60,
      filename: "stage14-final.xlsx",
    });
  }
  return send(response, 404, { detail: { code: "mock_api_route_not_found", path } });
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", `http://${HOST}:${PORT}`);
  if (request.method === "OPTIONS") return send(response, 204);
  if (request.method === "GET" && url.pathname === "/mock/health") {
    return send(response, 200, { status: "ready" });
  }
  if (request.method === "POST" && url.pathname === "/mock/reset") {
    state = initialState();
    return send(response, 204);
  }
  if (request.method === "GET" && url.pathname === "/mock/download/stage14-final.xlsx") {
    const content = Buffer.from("stage14-local-mock-workbook");
    response.writeHead(200, {
      ...corsHeaders(),
      "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "Content-Length": content.length,
    });
    return response.end(content);
  }
  if (url.pathname.startsWith("/mock/supabase/")) {
    return handleSupabase(request, response, url);
  }
  if (url.pathname.startsWith("/mock/api/")) {
    return handleApi(request, response, url);
  }
  return send(response, 404, { error: "mock_route_not_found" });
});

server.listen(PORT, HOST);

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
