import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { App } from "../../app/App";
import {
  AppApiProvider,
  type AppApi,
  type AssignmentDetail,
  type SubmissionUploadResult,
  type SubmissionView,
} from "../api/AppApiContext";
import { AuthProvider, type AuthClient } from "../auth/AuthContext";
import { EmptyAppApi } from "../../test/EmptyAppApi";
import { ApiRequestError } from "../api/httpAppApi";

const assignmentId = "44444444-4444-4444-8444-444444444444";
const session = { accessToken: "teacher-token" };

class TeacherAuthClient implements AuthClient {
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

function readyAssignment(): AssignmentDetail {
  return {
    id: assignmentId,
    title: "阶段七上传验收",
    instructions: "Write an essay.",
    status: "ready",
    current_rubric_status: "confirmed",
    current_rubric_version: 1,
    current_draft_version: null,
    current_confirmed_version: 1,
    current_draft: null,
    current_confirmed: {
      id: "55555555-5555-4555-8555-555555555555",
      version: 1,
      status: "confirmed",
    },
    created_at: "2026-07-16T08:00:00Z",
    updated_at: "2026-07-16T09:00:00Z",
    rubric_versions: [],
  };
}

function submission(filename: string, id: string): SubmissionView {
  return {
    id,
    assignment_id: assignmentId,
    original_filename: filename,
    media_type: filename.endsWith(".pdf")
      ? "application/pdf"
      : "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    file_size_bytes: 12,
    status: "ready",
    error_code: null,
    created_at: "2026-07-16T09:30:00Z",
  };
}

class Stage7Api extends EmptyAppApi {
  uploaded: string[] = [];
  savedSubmissions: SubmissionView[] = [];
  gradingRequests: Array<{
    assignmentId: string;
    submissionIds: string[];
    idempotencyKey: string;
  }> = [];

  override async getAssignment() {
    return readyAssignment();
  }

  override async listSubmissions() {
    return this.savedSubmissions;
  }

  async createGradingJob(
    _session: typeof session,
    selectedAssignmentId: string,
    submissionIds: string[],
    idempotencyKey: string,
  ) {
    this.gradingRequests.push({
      assignmentId: selectedAssignmentId,
      submissionIds,
      idempotencyKey,
    });
    return {
      id: "88888888-8888-4888-8888-888888888888",
      assignment_id: selectedAssignmentId,
      status: "queued" as const,
      total: submissionIds.length,
    };
  }

  override async uploadSubmission(
    _session: typeof session,
    _assignmentId: string,
    file: File,
  ): Promise<SubmissionUploadResult> {
    this.uploaded.push(file.name);
    return {
      duplicate: file.name === "duplicate.pdf",
      submission: submission(file.name, `77777777-7777-4777-8777-${String(this.uploaded.length).padStart(12, "0")}`),
    };
  }
}

class RejectedStage7Api extends Stage7Api {
  override async uploadSubmission(): Promise<SubmissionUploadResult> {
    throw new ApiRequestError("rejected", 422, "docx_content_unsupported");
  }
}

class PendingAssignmentStage7Api extends Stage7Api {
  override async getAssignment(): Promise<AssignmentDetail> {
    return await new Promise<AssignmentDetail>(() => undefined);
  }
}

class RetryGradingStage7Api extends Stage7Api {
  attempts: string[] = [];

  override async createGradingJob(
    selectedSession: typeof session,
    selectedAssignmentId: string,
    submissionIds: string[],
    idempotencyKey: string,
  ) {
    this.attempts.push(idempotencyKey);
    if (this.attempts.length === 1) {
      throw new ApiRequestError(
        "供应商当前配置不可用于评分",
        409,
        "grading_job_provider_invalid",
      );
    }
    return super.createGradingJob(
      selectedSession,
      selectedAssignmentId,
      submissionIds,
      idempotencyKey,
    );
  }
}

class QuotaBlockedStage7Api extends Stage7Api {
  override async createGradingJob(): Promise<never> {
    throw new ApiRequestError(
      "internal capacity detail",
      507,
      "database_quota_exceeded",
    );
  }
}

class QuotaUnavailableStage7Api extends Stage7Api {
  override async createGradingJob(): Promise<never> {
    throw new ApiRequestError(
      "internal sampler detail",
      503,
      "database_usage_unavailable",
    );
  }
}

function renderStage7(api = new Stage7Api()) {
  const account = {
    id: "11111111-1111-4111-8111-111111111111",
    email: "teacher@example.com",
    display_name: "张老师",
    role: "teacher" as const,
    status: "active" as const,
  };
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <AppApiProvider api={api as AppApi}>
      <AuthProvider
        authClient={new TeacherAuthClient()}
        completeInvite={async () => account}
        loadAccount={async () => account}
      >
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={[`/assignments/${assignmentId}/submissions`]}>
            <App />
          </MemoryRouter>
        </QueryClientProvider>
      </AuthProvider>
    </AppApiProvider>,
  );
  return api;
}

describe("阶段七论文上传", () => {
  it("shows a loading state without falsely reporting an assignment failure", async () => {
    renderStage7(new PendingAssignmentStage7Api());

    expect(await screen.findByText("正在加载作业…")).toBeVisible();
    expect(screen.queryByText("暂时无法加载作业。")).not.toBeInTheDocument();
  });

  it("uploads valid files and keeps ready and duplicate results aligned", async () => {
    const api = renderStage7();

    expect(await screen.findByRole("heading", { name: "上传论文" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("选择 DOCX/PDF 文件"), {
      target: {
        files: [
          new File(["docx"], "essay.docx"),
          new File(["pdf"], "duplicate.pdf"),
        ],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始上传" }));

    await waitFor(() => {
      expect(api.uploaded).toEqual(["essay.docx", "duplicate.pdf"]);
      expect(screen.getByText("解析完成")).toBeVisible();
      expect(screen.getByText("重复文件")).toBeVisible();
    });
  });

  it("shows the parser rejection reason returned by the API", async () => {
    renderStage7(new RejectedStage7Api());

    expect(await screen.findByRole("heading", { name: "上传论文" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("选择 DOCX/PDF 文件"), {
      target: { files: [new File(["docx"], "unsupported.docx")] },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始上传" }));

    expect(
      await screen.findByText("Word 文件含首版无法可靠提取的正文结构。"),
    ).toBeVisible();
  });

  it("selects ready papers and creates a grading job without manual UUID input", async () => {
    const api = new Stage7Api();
    api.savedSubmissions = [
      submission("essay-one.docx", "77777777-7777-4777-8777-000000000001"),
      submission("essay-two.pdf", "77777777-7777-4777-8777-000000000002"),
    ];
    renderStage7(api);

    expect(await screen.findByText("essay-one.docx")).toBeVisible();
    expect(screen.getByText("请先勾选已解析论文，再创建批改任务。创建后会立即调用已配置模型并产生相应费用。")).toBeVisible();
    fireEvent.click(screen.getByRole("checkbox", { name: "选择全部可批改论文" }));
    fireEvent.click(screen.getByRole("button", { name: "创建批改任务" }));

    await waitFor(() => {
      expect(api.gradingRequests).toHaveLength(1);
      expect(api.gradingRequests[0]?.assignmentId).toBe(assignmentId);
      expect(api.gradingRequests[0]?.submissionIds).toEqual([
        "77777777-7777-4777-8777-000000000001",
        "77777777-7777-4777-8777-000000000002",
      ]);
      expect(api.gradingRequests[0]?.idempotencyKey).toMatch(/^grading-job-/);
      expect(screen.getByRole("heading", { name: "批改任务" })).toBeVisible();
    });
  });

  it("keeps the same idempotency key when a failed grading request is retried", async () => {
    const api = new RetryGradingStage7Api();
    api.savedSubmissions = [
      submission("essay.docx", "77777777-7777-4777-8777-000000000001"),
    ];
    renderStage7(api);

    await screen.findByText("essay.docx");
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 essay.docx" }));
    fireEvent.click(screen.getByRole("button", { name: "创建批改任务" }));
    expect(await screen.findByText("当前模型配置不可用于批改，请联系管理员检查后重试。")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "创建批改任务" }));
    await waitFor(() => {
      expect(api.attempts).toHaveLength(2);
      expect(api.attempts[1]).toBe(api.attempts[0]);
    });
  });

  it("shows a safe message when the database quota blocks a new grading job", async () => {
    const api = new QuotaBlockedStage7Api();
    api.savedSubmissions = [
      submission("essay.docx", "77777777-7777-4777-8777-000000000001"),
    ];
    renderStage7(api);

    await screen.findByText("essay.docx");
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 essay.docx" }));
    fireEvent.click(screen.getByRole("button", { name: "创建批改任务" }));

    expect(
      await screen.findByText("系统容量已达到安全上限，暂时不能创建新的评分批次。"),
    ).toBeVisible();
    expect(screen.queryByText("internal capacity detail")).not.toBeInTheDocument();
  });

  it("shows a safe message when remaining capacity cannot be verified", async () => {
    const api = new QuotaUnavailableStage7Api();
    api.savedSubmissions = [
      submission("essay.docx", "77777777-7777-4777-8777-000000000001"),
    ];
    renderStage7(api);

    await screen.findByText("essay.docx");
    fireEvent.click(screen.getByRole("checkbox", { name: "选择 essay.docx" }));
    fireEvent.click(screen.getByRole("button", { name: "创建批改任务" }));

    expect(
      await screen.findByText("系统暂时无法确认剩余容量，请稍后重试。"),
    ).toBeVisible();
    expect(screen.queryByText("internal sampler detail")).not.toBeInTheDocument();
  });
});
