import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../../app/App";
import {
  AppApiProvider,
  type ExportView,
  type ExportType,
  type ReviewJobSummary,
} from "../api/AppApiContext";
import { AuthProvider, type AuthClient } from "../auth/AuthContext";
import { EmptyAppApi } from "../../test/EmptyAppApi";
import { ApiRequestError } from "../api/httpAppApi";

const session = { accessToken: "teacher-token" };
const JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";

function reviewJob(): ReviewJobSummary {
  return {
    id: JOB_ID,
    assignment_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    assignment_title: "Argumentative essay",
    model: "deepseek-v4-pro",
    status: "needs_review",
    total: 2,
    needs_review: 2,
    completed: 0,
    failed: 0,
    items: [
      {
        id: "11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        submission_id: "22222222-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        original_filename: "essay-01.pdf",
        position: 0,
        status: "needs_review",
        attempt_count: 1,
        error_code: null,
        review_available: true,
        review_id: "33333333-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        review_revision: 1,
        review_status: "draft",
      },
      {
        id: "44444444-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        submission_id: "55555555-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        original_filename: "essay-02.pdf",
        position: 1,
        status: "needs_review",
        attempt_count: 1,
        error_code: null,
        review_available: true,
        review_id: null,
        review_revision: null,
        review_status: null,
      },
    ],
    created_at: "2026-07-22T07:00:00Z",
    finished_at: null,
  };
}

function completedReviewJob(): ReviewJobSummary {
  const job = reviewJob();
  job.status = "completed";
  job.needs_review = 0;
  job.completed = job.total;
  job.finished_at = "2026-07-22T07:30:00Z";
  job.items = job.items.map((item, index) => ({
    ...item,
    status: "completed",
    review_id: `${index + 6}6666666-aaaa-4aaa-8aaa-aaaaaaaaaaaa`,
    review_revision: 1,
    review_status: "confirmed",
  }));
  return job;
}

function exportView(overrides: Partial<ExportView> = {}): ExportView {
  return {
    id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    assignment_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    assignment_title: "Argumentative essay",
    grading_job_id: JOB_ID,
    export_type: "draft",
    status: "completed",
    paper_count: 2,
    source_counts: { ai_suggestion: 1, teacher_draft: 1, teacher_confirmed: 0 },
    safe_filename: "argumentative-essay-draft.xlsx",
    error_code: null,
    snapshot_at: "2026-07-22T08:00:00Z",
    started_at: "2026-07-22T08:00:30Z",
    created_at: "2026-07-22T08:00:00Z",
    finished_at: "2026-07-22T08:01:00Z",
    ...overrides,
  };
}

class TestAuthClient implements AuthClient {
  async getSession() {
    return session;
  }
  subscribe() {
    return () => undefined;
  }
  async signIn() {
    return session;
  }
  async requestPasswordReset() {
    return undefined;
  }
  async consumeRedirect() {
    return session;
  }
  async updatePassword() {
    return undefined;
  }
  async signOut() {
    return undefined;
  }
}

class Stage12Api extends EmptyAppApi {
  async listExports(): Promise<ExportView[]> {
    return [exportView()];
  }

  async listReviewJobs() {
    return [reviewJob()];
  }
}

class RetryCreateApi extends Stage12Api {
  createRequests: Array<{ jobId: string; exportType: ExportType; key: string }> = [];

  async createExport(
    _session: typeof session,
    jobId: string,
    exportType: ExportType,
    key: string,
  ) {
    this.createRequests.push({ jobId, exportType, key });
    if (this.createRequests.length === 1) {
      throw new ApiRequestError("network", 500);
    }
    return exportView({ status: "queued", safe_filename: null, started_at: null, finished_at: null });
  }
}

class DownloadApi extends Stage12Api {
  downloadRequests: string[] = [];

  async createExportDownload(_session: typeof session, exportId: string) {
    this.downloadRequests.push(exportId);
    return {
      download_url: "https://storage.example/signed-export",
      expires_in_seconds: 60,
      filename: "argumentative-essay-draft.xlsx",
    };
  }
}

class RetryDownloadApi extends DownloadApi {
  override async createExportDownload(_session: typeof session, exportId: string) {
    this.downloadRequests.push(exportId);
    if (this.downloadRequests.length === 1) {
      throw new ApiRequestError("expired", 403);
    }
    return {
      download_url: "https://storage.example/fresh-signed-export",
      expires_in_seconds: 60,
      filename: "argumentative-essay-draft.xlsx",
    };
  }
}

class FailedExportApi extends Stage12Api {
  constructor(private readonly errorCode = "export_storage_failed") {
    super();
  }

  async listExports() {
    return [exportView({
      status: "failed",
      safe_filename: null,
      error_code: this.errorCode,
      started_at: "2026-07-22T08:00:30Z",
    })];
  }
}

class PollingApi extends Stage12Api {
  listAttempts = 0;

  async listExports() {
    this.listAttempts += 1;
    return [exportView(this.listAttempts === 1
      ? { status: "queued", safe_filename: null, started_at: null, finished_at: null }
      : {})];
  }
}

class FinalCreateApi extends Stage12Api {
  createRequests: Array<{ exportType: ExportType; key: string }> = [];

  async listReviewJobs() {
    return [completedReviewJob()];
  }

  async createExport(
    _session: typeof session,
    _jobId: string,
    exportType: ExportType,
    key: string,
  ) {
    this.createRequests.push({ exportType, key });
    return exportView({
      export_type: exportType,
      status: "queued",
      safe_filename: null,
      started_at: null,
      finished_at: null,
    });
  }
}

class RetryListApi extends Stage12Api {
  listAttempts = 0;

  async listExports() {
    this.listAttempts += 1;
    if (this.listAttempts === 1) {
      throw new ApiRequestError("expired", 401);
    }
    return [];
  }
}

class CreateErrorApi extends Stage12Api {
  constructor(private readonly status: number) {
    super();
  }

  async createExport(): Promise<ExportView> {
    throw new ApiRequestError("rejected", this.status);
  }
}

function renderStage12(path = "/exports", api = new Stage12Api()) {
  const account = {
    id: "11111111-1111-4111-8111-111111111111",
    email: "teacher@example.com",
    display_name: "张老师",
    role: "teacher" as const,
    status: "active" as const,
  };
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <AppApiProvider api={api}>
      <AuthProvider
        authClient={new TestAuthClient()}
        completeInvite={async () => account}
        loadAccount={async () => account}
      >
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={[path]}>
            <App />
          </MemoryRouter>
        </QueryClientProvider>
      </AuthProvider>
    </AppApiProvider>,
  );
  return api;
}

describe("stage 12 exports", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });
  it("lists the teacher's exports without manual UUID input", async () => {
    renderStage12();

    expect(await screen.findByRole("heading", { name: "成绩导出" })).toBeVisible();
    expect(await screen.findByText("Argumentative essay")).toBeVisible();
    expect(screen.getByText("草稿")).toBeVisible();
    expect(screen.getByText("已完成")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: /UUID/i })).not.toBeInTheDocument();
  });

  it("explains why a final export is unavailable before creation", async () => {
    renderStage12(`/exports?jobId=${JOB_ID}`);

    const panel = (await screen.findByRole("heading", { name: "新建导出" })).closest("section");
    expect(panel).not.toBeNull();
    expect(await within(panel as HTMLElement).findByRole("heading", { name: "Argumentative essay" })).toBeVisible();
    expect(within(panel as HTMLElement).getByText("2 篇论文")).toBeVisible();
    expect(within(panel as HTMLElement).getByText("AI 建议 1 · 教师草稿 1 · 已确认 0")).toBeVisible();
    expect(within(panel as HTMLElement).getByRole("radio", { name: /^草稿成绩/ })).toBeChecked();
    expect(within(panel as HTMLElement).getByRole("radio", { name: /^最终成绩/ })).toBeDisabled();
    expect(within(panel as HTMLElement).getByText("还有 2 篇论文未由教师确认，不能生成最终成绩。")).toBeVisible();
  });

  it("reuses the same idempotency key when a create request is retried", async () => {
    const api = new RetryCreateApi();
    renderStage12(`/exports?jobId=${JOB_ID}`, api);

    const create = await screen.findByRole("button", { name: "生成草稿工作簿" });
    fireEvent.click(create);
    expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法创建导出");
    fireEvent.click(create);

    await waitFor(() => expect(api.createRequests).toHaveLength(2));
    expect(api.createRequests[0]).toMatchObject({ jobId: JOB_ID, exportType: "draft" });
    expect(api.createRequests[1]?.key).toBe(api.createRequests[0]?.key);
    expect(api.createRequests[0]?.key).toMatch(/^export-/);
    expect(await screen.findByRole("status")).toHaveTextContent("导出已进入生成队列");
  });

  it("translates the queued message when the language changes", async () => {
    const api = new RetryCreateApi();
    renderStage12(`/exports?jobId=${JOB_ID}`, api);

    const create = await screen.findByRole("button", { name: "生成草稿工作簿" });
    fireEvent.click(create);
    expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法创建导出");
    fireEvent.click(create);
    expect(await screen.findByRole("status")).toHaveTextContent("导出已进入生成队列");

    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    expect(screen.getByRole("status")).toHaveTextContent("The export is queued");
  });

  it("enters export creation from a grading job card", async () => {
    renderStage12("/grading-jobs");

    const link = await screen.findByRole("link", { name: "导出成绩" });
    expect(link).toHaveAttribute("href", `/exports?jobId=${JOB_ID}`);
  });

  it("requests a fresh signed URL when a completed export is downloaded", async () => {
    const api = new DownloadApi();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderStage12("/exports", api);

    fireEvent.click(await screen.findByRole("button", {
      name: "下载 argumentative-essay-draft.xlsx",
    }));

    await waitFor(() => expect(api.downloadRequests).toEqual([
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    ]));
    expect(click).toHaveBeenCalledOnce();
  });

  it("can request a fresh signed URL after an expired download fails", async () => {
    const api = new RetryDownloadApi();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderStage12("/exports", api);
    const download = await screen.findByRole("button", {
      name: "下载 argumentative-essay-draft.xlsx",
    });

    fireEvent.click(download);
    expect(await screen.findByRole("alert")).toHaveTextContent("无法获取新的下载地址");
    fireEvent.click(download);

    await waitFor(() => expect(api.downloadRequests).toHaveLength(2));
    expect(click).toHaveBeenCalledOnce();
  });

  it("shows a safe actionable reason for a failed export", async () => {
    renderStage12("/exports", new FailedExportApi());

    expect(await screen.findByText("Excel 文件未能安全保存，请重新创建导出。")).toBeVisible();
    expect(screen.queryByText("export_storage_failed")).not.toBeInTheDocument();
  });

  it("explains a bounded worker-loss failure without exposing its code", async () => {
    renderStage12("/exports", new FailedExportApi("export_worker_lost"));

    expect(await screen.findByText("导出 Worker 多次中断，请重新创建导出。")).toBeVisible();
    expect(screen.queryByText("export_worker_lost")).not.toBeInTheDocument();
  });

  it("polls an active export until it reaches a terminal state", async () => {
    const api = new PollingApi();
    renderStage12("/exports", api);

    expect(await screen.findByText("等待生成")).toBeVisible();
    expect(await screen.findByText("已完成", {}, { timeout: 2_500 })).toBeVisible();
    expect(api.listAttempts).toBe(2);
  });

  it("uses a new key after success and rotates the key again when type changes", async () => {
    const api = new FinalCreateApi();
    renderStage12(`/exports?jobId=${JOB_ID}`, api);

    fireEvent.click(await screen.findByRole("button", { name: "生成草稿工作簿" }));
    await waitFor(() => expect(api.createRequests).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "生成草稿工作簿" }));
    await waitFor(() => expect(api.createRequests).toHaveLength(2));
    expect(api.createRequests[1]?.key).not.toBe(api.createRequests[0]?.key);
    const final = screen.getByRole("radio", { name: /^最终成绩/ });
    expect(final).toBeEnabled();
    fireEvent.click(final);
    fireEvent.click(screen.getByRole("button", { name: "生成最终工作簿" }));

    await waitFor(() => expect(api.createRequests).toHaveLength(3));
    expect(api.createRequests.map((request) => request.exportType)).toEqual([
      "draft",
      "draft",
      "final",
    ]);
    expect(api.createRequests[2]?.key).not.toBe(api.createRequests[1]?.key);

    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    expect(screen.getByRole("heading", { name: "Grade exports" })).toBeVisible();
    expect(screen.getByRole("radio", { name: /^Final grades/ })).toBeEnabled();
  });

  it.each([
    [401, "登录已失效，请重新登录后再创建导出。"],
    [403, "无法访问该批次，请返回批改任务重新选择。"],
    [404, "无法访问该批次，请返回批改任务重新选择。"],
    [409, "本次导出请求与先前请求不一致，请重新选择批次或类型。"],
  ])("shows a safe create error for HTTP %s", async (status, expected) => {
    renderStage12(`/exports?jobId=${JOB_ID}`, new CreateErrorApi(status));

    fireEvent.click(await screen.findByRole("button", { name: "生成草稿工作簿" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(expected);
  });

  it("shows an expired-session list error and lets the teacher retry", async () => {
    const api = new RetryListApi();
    renderStage12("/exports", api);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "登录已失效，请重新登录后再查看导出记录。",
    );
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));

    expect(await screen.findByRole("heading", { name: "还没有导出记录" })).toBeVisible();
    expect(api.listAttempts).toBe(2);
  });
});
