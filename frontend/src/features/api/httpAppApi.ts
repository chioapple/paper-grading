import type { Account, BrowserSession } from "../auth/AuthContext";
import type {
  AppApi,
  AssignmentCreateInput,
  AssignmentDetail,
  AssignmentSummary,
  InviteTeacherInput,
  ProviderConfig,
  ProviderConfigInput,
  ProviderTestResult,
  RubricView,
  RubricDraftInput,
  SubmissionDownload,
  SubmissionUploadResult,
  SubmissionView,
  TeacherAccount,
  TeacherProviderModels,
} from "./AppApiContext";

export type AuthApi = {
  completeInvite(session: BrowserSession): Promise<Account>;
  loadAccount(session: BrowserSession): Promise<Account>;
};

type ErrorPayload = {
  detail?: string | { code?: string; message?: string };
};

export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
  }
}

class HttpAppApi implements AppApi, AuthApi {
  constructor(private readonly baseUrl: string) {}

  async loadAccount(session: BrowserSession) {
    return this.request<Account>("/auth/me", session);
  }

  async completeInvite(session: BrowserSession) {
    return this.request<Account>("/auth/complete-invite", session, { method: "POST" });
  }

  async listAssignments(session: BrowserSession) {
    return this.request<AssignmentSummary[]>("/assignments", session);
  }

  async createAssignment(session: BrowserSession, input: AssignmentCreateInput) {
    return this.request<AssignmentDetail>("/assignments", session, {
      body: JSON.stringify({
        title: input.title,
        instructions: input.instructions,
        original_rubric: input.originalRubric,
        total_score: input.totalScore,
        score_step: input.scoreStep,
      }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    });
  }

  async getAssignment(session: BrowserSession, assignmentId: string) {
    return this.request<AssignmentDetail>(`/assignments/${assignmentId}`, session);
  }

  async listTeacherProviders(session: BrowserSession) {
    return this.request<TeacherProviderModels[]>("/providers/models", session);
  }

  async structureRubric(
    session: BrowserSession,
    assignmentId: string,
    rubricId: string,
    providerId: string,
  ) {
    return this.request<RubricView>(
      `/assignments/${assignmentId}/rubrics/${rubricId}/structure`,
      session,
      {
        body: JSON.stringify({ provider_config_id: providerId }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      },
    );
  }

  async confirmRubric(session: BrowserSession, assignmentId: string, rubricId: string) {
    return this.request<AssignmentDetail>(
      `/assignments/${assignmentId}/rubrics/${rubricId}/confirm`,
      session,
      { method: "POST" },
    );
  }

  async updateAssignmentStatus(
    session: BrowserSession,
    assignmentId: string,
    status: "draft" | "archived",
  ) {
    return this.request<AssignmentDetail>(`/assignments/${assignmentId}/status`, session, {
      body: JSON.stringify({ status }),
      headers: { "Content-Type": "application/json" },
      method: "PUT",
    });
  }

  async createRubricDraft(
    session: BrowserSession,
    assignmentId: string,
    input: RubricDraftInput,
  ) {
    return this.request<RubricView>(`/assignments/${assignmentId}/rubrics`, session, {
      body: JSON.stringify({
        original_rubric: input.originalRubric,
        total_score: input.totalScore,
        score_step: input.scoreStep,
      }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    });
  }

  async listSubmissions(session: BrowserSession, assignmentId: string) {
    return this.request<SubmissionView[]>(
      `/assignments/${assignmentId}/submissions`,
      session,
    );
  }

  async uploadSubmission(
    session: BrowserSession,
    assignmentId: string,
    file: File,
  ) {
    const body = new FormData();
    body.append("file", file);
    return this.request<SubmissionUploadResult>(
      `/assignments/${assignmentId}/submissions`,
      session,
      { body, method: "POST" },
    );
  }

  async createSubmissionDownload(
    session: BrowserSession,
    assignmentId: string,
    submissionId: string,
  ) {
    return this.request<SubmissionDownload>(
      `/assignments/${assignmentId}/submissions/${submissionId}/download`,
      session,
      { method: "POST" },
    );
  }

  async listTeachers(session: BrowserSession) {
    return this.request<TeacherAccount[]>("/admin/users", session);
  }

  async inviteTeacher(session: BrowserSession, input: InviteTeacherInput) {
    return this.request<TeacherAccount>("/admin/users/invitations", session, {
      body: JSON.stringify({
        display_name: input.displayName,
        email: input.email,
      }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    });
  }

  async disableTeacher(session: BrowserSession, teacherId: string) {
    await this.request<void>(`/admin/users/${teacherId}/disable`, session, {
      method: "POST",
    });
  }

  async enableTeacher(session: BrowserSession, teacherId: string) {
    await this.request<void>(`/admin/users/${teacherId}/enable`, session, {
      method: "POST",
    });
  }

  async listProviders(session: BrowserSession) {
    return this.request<ProviderConfig[]>("/admin/providers", session);
  }

  async createProvider(
    session: BrowserSession,
    input: ProviderConfigInput & { apiKey: string },
  ) {
    return this.request<ProviderConfig>("/admin/providers", session, {
      body: JSON.stringify(this.providerPayload(input, true)),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    });
  }

  async updateProvider(
    session: BrowserSession,
    providerId: string,
    input: ProviderConfigInput,
  ) {
    return this.request<ProviderConfig>(`/admin/providers/${providerId}`, session, {
      body: JSON.stringify(this.providerPayload(input, false)),
      headers: { "Content-Type": "application/json" },
      method: "PUT",
    });
  }

  async testProvider(session: BrowserSession, providerId: string) {
    return this.request<ProviderTestResult>(`/admin/providers/${providerId}/test`, session, {
      method: "POST",
    });
  }

  async enableProvider(session: BrowserSession, providerId: string) {
    return this.request<ProviderConfig>(`/admin/providers/${providerId}/enable`, session, {
      method: "POST",
    });
  }

  async disableProvider(session: BrowserSession, providerId: string) {
    return this.request<ProviderConfig>(`/admin/providers/${providerId}/disable`, session, {
      method: "POST",
    });
  }

  private providerPayload(input: ProviderConfigInput, requireApiKey: boolean) {
    const payload: Record<string, unknown> = {
      provider_type: input.providerType,
      name: input.name,
      base_url: input.baseUrl,
      allowed_models: input.allowedModels,
      default_model: input.defaultModel,
      timeout_seconds: input.timeoutSeconds,
      max_concurrency: input.maxConcurrency,
      monthly_budget: input.monthlyBudget,
    };
    if (requireApiKey || input.apiKey) {
      payload.api_key = input.apiKey;
    }
    return payload;
  }

  private async request<T>(
    path: string,
    session: BrowserSession,
    init: RequestInit = {},
  ): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        ...init.headers,
        Authorization: `Bearer ${session.accessToken}`,
      },
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as ErrorPayload;
      const detail = payload.detail;
      const message =
        typeof detail === "string"
          ? detail
          : (detail?.message ?? "服务器拒绝了请求");
      throw new ApiRequestError(message, response.status, detail && typeof detail !== "string" ? detail.code : undefined);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }
}

export function createHttpAppApi(baseUrl: string): AppApi & AuthApi {
  return new HttpAppApi(baseUrl.replace(/\/$/, ""));
}
