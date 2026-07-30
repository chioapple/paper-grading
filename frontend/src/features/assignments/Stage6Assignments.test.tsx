import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { App } from "../../app/App";
import {
  AppApiProvider,
  type AppApi,
  type AssignmentCreateInput,
  type AssignmentDetail,
  type AssignmentSummary,
  type RubricDraftInput,
  type RubricView,
  type StructuredRubric,
} from "../api/AppApiContext";
import {
  AuthProvider,
  type AuthClient,
  type BrowserSession,
} from "../auth/AuthContext";

const session = { accessToken: "teacher-token" };
const assignmentId = "44444444-4444-4444-8444-444444444444";
const rubricId = "55555555-5555-4555-8555-555555555555";

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

function assignmentSummary(): AssignmentSummary {
  return {
    id: assignmentId,
    title: "议论文：社交媒体与学习",
    status: "draft" as const,
    current_rubric_status: "draft" as const,
    current_rubric_version: 1,
    current_draft_version: 1,
    current_confirmed_version: null,
    current_draft: { id: rubricId, version: 1, status: "draft" as const },
    current_confirmed: null,
    created_at: "2026-07-16T08:00:00Z",
    updated_at: "2026-07-16T08:30:00Z",
  };
}

function draftRubric(): RubricView {
  return {
    id: rubricId,
    assignment_id: assignmentId,
    version: 1,
    status: "draft" as const,
    original_rubric: "内容理解 10 分；语言组织 10 分。",
    structured_rubric: null,
    total_score: "20",
    score_step: "1",
    provider_config_id: null,
    model: null,
    confirmed_at: null,
    created_at: "2026-07-16T08:00:00Z",
  };
}

function assignmentDetail(): AssignmentDetail {
  return {
    ...assignmentSummary(),
    instructions: "阅读文章并用英文回答问题。",
    rubric_versions: [draftRubric()],
  };
}

function structuredRubric(): StructuredRubric {
  return {
    schema_version: 1 as const,
    total_score: "20",
    score_step: "1",
    dimensions: [
      {
        id: "content",
        name: "内容理解",
        description: "准确理解主旨和细节。",
        max_score: "10",
        bands: [
          { label: "需要改进", min_score: "0", max_score: "4", description: "理解有限。" },
          { label: "良好", min_score: "5", max_score: "7", description: "大体理解。" },
          { label: "优秀", min_score: "8", max_score: "10", description: "理解准确。" },
        ],
        evidence_requirements: ["引用文章中的具体信息"],
      },
      {
        id: "organization",
        name: "语言组织",
        description: "结构清晰，衔接自然。",
        max_score: "10",
        bands: [
          { label: "需要改进", min_score: "0", max_score: "4", description: "结构不清。" },
          { label: "良好", min_score: "5", max_score: "7", description: "结构基本合理。" },
          { label: "优秀", min_score: "8", max_score: "10", description: "结构清晰。" },
        ],
        evidence_requirements: ["段落之间衔接自然"],
      },
    ],
    deductions: [
      { id: "plagiarism", name: "抄袭", description: "照抄原文且未作答。", points: "2" },
    ],
  };
}

class Stage6Api {
  assignments: AssignmentSummary[] = [assignmentSummary()];
  createdInput: AssignmentCreateInput | null = null;
  updatedInput: { title: string; instructions: string } | null = null;
  detail: AssignmentDetail = assignmentDetail();
  structuredProviderId: string | null = null;
  confirmedRubricId: string | null = null;

  async listAssignments() {
    return this.assignments;
  }

  async createAssignment(
    _session: BrowserSession,
    input: AssignmentCreateInput,
  ): Promise<AssignmentDetail> {
    this.createdInput = input;
    return {
      ...assignmentSummary(),
      title: input.title,
      instructions: input.instructions,
      rubric_versions: [
        {
          id: rubricId,
          assignment_id: assignmentId,
          version: 1,
          status: "draft" as const,
          original_rubric: input.originalRubric,
          structured_rubric: null,
          total_score: input.totalScore,
          score_step: input.scoreStep,
          provider_config_id: null,
          model: null,
          confirmed_at: null,
          created_at: "2026-07-16T08:00:00Z",
        },
      ],
    };
  }

  async getAssignment() {
    return this.detail;
  }

  async updateAssignment(
    _session: BrowserSession,
    _assignmentId: string,
    input: { title: string; instructions: string },
  ) {
    this.updatedInput = input;
    this.detail = { ...this.detail, ...input };
    this.assignments = this.assignments.map((assignment) => (
      assignment.id === this.detail.id ? { ...assignment, title: input.title } : assignment
    ));
    return this.detail;
  }

  async listTeacherProviders() {
    return [
      {
        provider_id: "33333333-3333-4333-8333-333333333333",
        provider_name: "DeepSeek 主账号",
        provider_type: "deepseek" as const,
        allowed_models: ["deepseek-chat"],
        default_model: "deepseek-chat",
      },
    ];
  }

  async structureRubric(
    _session: BrowserSession,
    _assignmentId: string,
    _rubricId: string,
    providerId: string,
  ) {
    this.structuredProviderId = providerId;
    const generated = {
      ...draftRubric(),
      structured_rubric: structuredRubric(),
      provider_config_id: providerId,
      model: "deepseek-chat",
    };
    this.detail = { ...this.detail, rubric_versions: [generated] };
    return generated;
  }

  async confirmRubric(
    _session: BrowserSession,
    _assignmentId: string,
    selectedRubricId: string,
  ) {
    this.confirmedRubricId = selectedRubricId;
    const confirmed = {
      ...this.detail.rubric_versions[0],
      status: "confirmed" as const,
      confirmed_at: "2026-07-16T09:00:00Z",
    };
    this.detail = {
      ...this.detail,
      status: "ready" as const,
      current_rubric_status: "confirmed" as const,
      current_draft_version: null,
      current_confirmed_version: 1,
      current_draft: null,
      current_confirmed: { id: rubricId, version: 1, status: "confirmed" as const },
      rubric_versions: [confirmed],
    };
    return this.detail;
  }

  async updateAssignmentStatus(
    _session: BrowserSession,
    selectedAssignmentId: string,
    action: "archive" | "restore",
  ) {
    const current = this.assignments.find((assignment) => assignment.id === selectedAssignmentId);
    if (!current) {
      throw new Error("作业不存在");
    }
    const status: AssignmentSummary["status"] = action === "archive"
      ? "archived"
      : current.current_confirmed_version === null ? "draft" : "ready";
    const updated = { ...current, status };
    this.assignments = this.assignments.map((assignment) => assignment.id === selectedAssignmentId ? updated : assignment);
    this.detail = { ...this.detail, status };
    return { ...this.detail, ...updated };
  }

  async createRubricDraft(
    _session: BrowserSession,
    _assignmentId: string,
    input: RubricDraftInput,
  ): Promise<RubricView> {
    const revision = {
      ...draftRubric(),
      id: "66666666-6666-4666-8666-666666666666",
      version: 2,
      original_rubric: input.originalRubric,
      total_score: input.totalScore,
      score_step: input.scoreStep,
    };
    this.detail = {
      ...this.detail,
      current_rubric_status: "draft" as const,
      current_rubric_version: 2,
      current_draft_version: 2,
      current_draft: { id: revision.id, version: 2, status: "draft" as const },
      rubric_versions: [revision, ...this.detail.rubric_versions],
    };
    return revision;
  }

  async listTeachers() {
    return [];
  }

  async inviteTeacher() {
    throw new Error("本测试不使用教师邀请");
  }

  async disableTeacher() {
    return undefined;
  }

  async enableTeacher() {
    return undefined;
  }

  async listProviders() {
    return [];
  }

  async createProvider() {
    throw new Error("本测试不使用供应商管理");
  }

  async updateProvider() {
    throw new Error("本测试不使用供应商管理");
  }

  async testProvider() {
    throw new Error("本测试不使用供应商管理");
  }

  async enableProvider() {
    throw new Error("本测试不使用供应商管理");
  }

  async disableProvider() {
    throw new Error("本测试不使用供应商管理");
  }
}

function renderStage6(path = "/assignments", api = new Stage6Api()) {
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
    <AppApiProvider api={api as unknown as AppApi}>
      <AuthProvider
        authClient={new TeacherAuthClient()}
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
  return { api, queryClient };
}

describe("阶段六作业流程", () => {
  it("列出当前教师的作业并进入未确认评分标准", async () => {
    renderStage6();

    expect(await screen.findByRole("heading", { name: "作业" })).toBeVisible();
    expect(await screen.findByText("议论文：社交媒体与学习")).toBeVisible();
    expect(screen.getByText("草稿 v1")).toBeVisible();

    fireEvent.click(screen.getByRole("link", { name: "继续设置" }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "设置评分标准" })).toBeVisible();
    });
  });

  it("创建作业和首个评分标准草稿后进入结构化页面", async () => {
    const { api } = renderStage6();
    fireEvent.click(await screen.findByRole("link", { name: "创建作业" }));

    expect(await screen.findByRole("heading", { name: "创建作业" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("作业名称"), {
      target: { value: "英语阅读测验" },
    });
    fireEvent.change(screen.getByLabelText("题目要求"), {
      target: { value: "阅读文章并用英文回答问题。" },
    });
    fireEvent.change(screen.getByLabelText("原始评分标准"), {
      target: { value: "内容理解 10 分；语言组织 10 分。" },
    });
    fireEvent.change(screen.getByLabelText("总分"), { target: { value: "20" } });
    fireEvent.change(screen.getByLabelText("评分步长"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并继续" }));

    await waitFor(() => {
      expect(api.createdInput).toEqual({
        title: "英语阅读测验",
        instructions: "阅读文章并用英文回答问题。",
        originalRubric: "内容理解 10 分；语言组织 10 分。",
        totalScore: "20",
        scoreStep: "1",
      });
      expect(screen.getByRole("heading", { name: "设置评分标准" })).toBeVisible();
    });
  });

  it("教师可以从作业列表编辑草稿题目和要求", async () => {
    const { api } = renderStage6();

    fireEvent.click(await screen.findByRole("link", { name: "编辑作业" }));
    expect(await screen.findByRole("heading", { name: "编辑作业" })).toBeVisible();
    expect(screen.getByLabelText("作业名称")).toHaveValue("议论文：社交媒体与学习");
    fireEvent.change(screen.getByLabelText("作业名称"), {
      target: { value: "更新后的作业" },
    });
    fireEvent.change(screen.getByLabelText("题目要求"), {
      target: { value: "Write a revised response." },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));

    await waitFor(() => {
      expect(api.updatedInput).toEqual({
        title: "更新后的作业",
        instructions: "Write a revised response.",
      });
      expect(screen.getByRole("heading", { name: "作业" })).toBeVisible();
    });
  });

  it("使用精确十进制判断小数总分是否符合评分步长", async () => {
    const { api } = renderStage6();
    fireEvent.click(await screen.findByRole("link", { name: "创建作业" }));

    fireEvent.change(await screen.findByLabelText("作业名称"), {
      target: { value: "小数评分作业" },
    });
    fireEvent.change(screen.getByLabelText("题目要求"), {
      target: { value: "完成一项简短任务。" },
    });
    fireEvent.change(screen.getByLabelText("原始评分标准"), {
      target: { value: "完成度 0.3 分。" },
    });
    fireEvent.change(screen.getByLabelText("总分"), { target: { value: "0.3" } });
    fireEvent.change(screen.getByLabelText("评分步长"), { target: { value: "0.1" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并继续" }));

    await waitFor(() => {
      expect(api.createdInput?.totalScore).toBe("0.3");
      expect(api.createdInput?.scoreStep).toBe("0.1");
    });
  });

  it("只在浏览器内把 UTF-8 文本文件读入题目要求和评分标准", async () => {
    renderStage6();
    fireEvent.click(await screen.findByRole("link", { name: "创建作业" }));
    await screen.findByRole("heading", { name: "创建作业" });

    const file = new File(["从文件读取的题目要求"], "prompt.txt", {
      type: "text/plain;charset=utf-8",
    });
    fireEvent.change(screen.getByLabelText("从 .txt/.md 读取题目要求"), {
      target: { files: [file] },
    });
    const rubricFile = new File(["从文件读取的评分标准"], "rubric.md", {
      type: "text/markdown;charset=utf-8",
    });
    fireEvent.change(screen.getByLabelText("从 .txt/.md 读取原始评分标准"), {
      target: { files: [rubricFile] },
    });

    await waitFor(() => {
      expect(screen.getByLabelText("题目要求")).toHaveValue("从文件读取的题目要求");
      expect(screen.getByLabelText("原始评分标准")).toHaveValue("从文件读取的评分标准");
    });
    expect(screen.getAllByText("文件只在当前浏览器读取，不会上传原文件。")).toHaveLength(2);
  });

  it("教师显式选择供应商后生成并确认结构化评分标准", async () => {
    const { api } = renderStage6(`/assignments/${assignmentId}/rubric`);

    expect(await screen.findByRole("heading", { name: "设置评分标准" })).toBeVisible();
    const providerSelect = await screen.findByLabelText("结构化模型");
    expect(providerSelect).toHaveValue("");
    fireEvent.change(providerSelect, {
      target: { value: "33333333-3333-4333-8333-333333333333" },
    });
    expect(screen.getByText("管理员默认模型：deepseek-chat")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "生成结构化草稿" }));

    expect(await screen.findByRole("heading", { name: "内容理解" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "语言组织" })).toBeVisible();
    expect(screen.getByText("引用文章中的具体信息")).toBeVisible();
    expect(api.structuredProviderId).toBe("33333333-3333-4333-8333-333333333333");
    fireEvent.click(screen.getByRole("button", { name: "确认评分标准" }));

    expect(await screen.findByText("当前版本已确认并冻结。")).toBeVisible();
    expect(api.confirmedRubricId).toBe(rubricId);
  });

  it("教师可以归档并恢复作业", async () => {
    const api = new Stage6Api();
    await api.structureRubric(
      session,
      assignmentId,
      rubricId,
      "33333333-3333-4333-8333-333333333333",
    );
    await api.confirmRubric(session, assignmentId, rubricId);
    api.assignments = [api.detail];
    renderStage6("/assignments", api);
    await screen.findByText("议论文：社交媒体与学习");

    fireEvent.click(screen.getByRole("button", { name: "归档 议论文：社交媒体与学习" }));
    expect(await screen.findByText("已归档")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "恢复 议论文：社交媒体与学习" }));

    expect(await screen.findByText("可批改", { selector: "td" })).toBeVisible();
    expect(screen.getByRole("link", { name: "上传论文" })).toBeVisible();
  });

  it("修改已确认评分标准时创建新版本而不覆盖旧版", async () => {
    const api = new Stage6Api();
    await api.structureRubric(session, assignmentId, rubricId, "33333333-3333-4333-8333-333333333333");
    await api.confirmRubric(session, assignmentId, rubricId);
    renderStage6(`/assignments/${assignmentId}/rubric`, api);
    expect(await screen.findByText("当前版本已确认并冻结。")).toBeVisible();
    expect(screen.getByLabelText("结构化模型")).toHaveValue(
      "33333333-3333-4333-8333-333333333333",
    );

    fireEvent.click(screen.getByRole("button", { name: "创建新版本" }));
    fireEvent.change(screen.getByLabelText("新版原始评分标准"), {
      target: { value: "内容理解 12 分；语言组织 8 分。" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));

    expect(await screen.findByText("v2 草稿")).toBeVisible();
    expect(screen.getByText("v1 已确认")).toBeVisible();
    expect(api.detail.rubric_versions).toHaveLength(2);
    expect(api.detail.rubric_versions[1].status).toBe("confirmed");
  });

  it("历史替代版本与当前确认版本使用不同状态文案", async () => {
    const api = new Stage6Api();
    const confirmed = {
      ...draftRubric(),
      id: "66666666-6666-4666-8666-666666666666",
      version: 2,
      status: "confirmed" as const,
      structured_rubric: structuredRubric(),
      provider_config_id: "33333333-3333-4333-8333-333333333333",
      model: "deepseek-chat",
      confirmed_at: "2026-07-16T10:00:00Z",
    };
    const superseded = {
      ...draftRubric(),
      status: "superseded" as const,
      structured_rubric: structuredRubric(),
      provider_config_id: "33333333-3333-4333-8333-333333333333",
      model: "deepseek-chat",
      confirmed_at: "2026-07-16T09:00:00Z",
    };
    api.detail = {
      ...api.detail,
      status: "ready",
      current_rubric_status: "confirmed",
      current_rubric_version: 2,
      current_draft_version: null,
      current_confirmed_version: 2,
      current_draft: null,
      current_confirmed: { id: confirmed.id, version: 2, status: "confirmed" },
      rubric_versions: [confirmed, superseded],
    };

    renderStage6(`/assignments/${assignmentId}/rubric`, api);

    expect(await screen.findByText("v2 已确认")).toBeVisible();
    expect(screen.getByText("v1 已替代")).toBeVisible();
  });
});
