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

  override async getAssignment() {
    return readyAssignment();
  }

  override async listSubmissions() {
    return [];
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
});
