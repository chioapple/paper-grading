import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { App } from "../../../app/App";
import {
  AppApiProvider,
  type AssignmentDetail,
  type ProviderConfig,
  type ProviderConfigInput,
  type RubricView,
  type TeacherAccount,
} from "../../../features/api/AppApiContext";
import {
  AuthProvider,
  type AuthClient,
  type BrowserSession,
} from "../../../features/auth/AuthContext";
import { EmptyAppApi } from "../../../test/EmptyAppApi";

const session = { accessToken: "admin-token" };

class AdminAuthClient implements AuthClient {
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

class TestAppApi extends EmptyAppApi {
  async listAssignments() {
    return [];
  }

  async createAssignment(): Promise<AssignmentDetail> {
    throw new Error("本测试不使用作业创建");
  }

  async getAssignment(): Promise<AssignmentDetail> {
    throw new Error("本测试不使用作业详情");
  }

  async listTeacherProviders() {
    return [];
  }

  async structureRubric(): Promise<RubricView> {
    throw new Error("本测试不使用评分标准");
  }

  async confirmRubric(): Promise<AssignmentDetail> {
    throw new Error("本测试不使用评分标准");
  }

  async updateAssignmentStatus(): Promise<AssignmentDetail> {
    throw new Error("本测试不使用作业状态");
  }

  async createRubricDraft(): Promise<RubricView> {
    throw new Error("本测试不使用评分标准修订");
  }

  createdApiKey: string | null = null;
  provider: ProviderConfig = {
    id: "33333333-3333-4333-8333-333333333333",
    provider_type: "deepseek",
    name: "DeepSeek 主账号",
    base_url: "https://api.deepseek.com",
    api_key_configured: true,
    allowed_models: ["deepseek-v4-flash", "deepseek-v4-pro"],
    default_model: "deepseek-v4-flash",
    timeout_seconds: "60.000",
    max_concurrency: 2,
    monthly_budget: "20.00",
    status: "draft",
    configuration_tested: false,
    can_enable: false,
    tested_at: null,
    created_at: "2026-07-15T08:00:00Z",
    updated_at: "2026-07-15T08:00:00Z",
  };

  async listProviders() {
    return [this.provider];
  }

  async createProvider(
    session: BrowserSession,
    input: ProviderConfigInput & { apiKey: string },
  ) {
    void session;
    this.createdApiKey = input.apiKey;
    this.provider = {
      ...this.provider,
      name: input.name,
      allowed_models: input.allowedModels,
      default_model: input.defaultModel,
    };
    return this.provider;
  }

  async updateProvider() {
    return this.provider;
  }

  async testProvider() {
    this.provider = { ...this.provider, configuration_tested: true, can_enable: true };
    return { provider: this.provider, available_models: this.provider.allowed_models };
  }

  async enableProvider() {
    this.provider = { ...this.provider, status: "enabled" };
    return this.provider;
  }

  async disableProvider() {
    return this.provider;
  }

  async listTeachers() {
    return [];
  }

  async inviteTeacher(): Promise<TeacherAccount> {
    throw new Error("本测试不使用教师邀请");
  }

  async disableTeacher() {
    return undefined;
  }

  async enableTeacher() {
    return undefined;
  }
}

function renderProvidersPage(api = new TestAppApi()) {
  const admin = {
    id: "11111111-1111-4111-8111-111111111111",
    email: "admin@example.com",
    display_name: "管理员",
    role: "admin" as const,
    status: "active" as const,
  };
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <AppApiProvider api={api}>
      <AuthProvider
        authClient={new AdminAuthClient()}
        completeInvite={async () => admin}
        loadAccount={async () => admin}
      >
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/admin/providers"]}>
            <App />
          </MemoryRouter>
        </QueryClientProvider>
      </AuthProvider>
    </AppApiProvider>,
  );
  return api;
}

describe("管理员模型配置", () => {
  it("只显示 Key 已配置状态，未测试配置不能启用", async () => {
    renderProvidersPage();

    expect(await screen.findByRole("heading", { name: "模型配置" })).toBeVisible();
    expect(await screen.findByText("DeepSeek 主账号")).toBeVisible();
    expect(screen.getByText("Key 已配置")).toBeVisible();
    expect(screen.queryByText("stage-five-canary-key")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "启用" })).toBeDisabled();
  });

  it("编辑时 Key 输入框为空，创建后也不在页面回显", async () => {
    const api = renderProvidersPage();
    await screen.findByText("DeepSeek 主账号");

    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    expect(screen.getByLabelText("API Key")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "取消" }));

    fireEvent.click(screen.getByRole("button", { name: "添加供应商" }));
    fireEvent.change(screen.getByLabelText("配置名称"), { target: { value: "DeepSeek 新账号" } });
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "one-time-canary" } });
    fireEvent.change(screen.getByLabelText("允许模型"), { target: { value: "deepseek-v4-flash" } });
    fireEvent.change(screen.getByLabelText("默认模型"), { target: { value: "deepseek-v4-flash" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(await screen.findByText("DeepSeek 新账号")).toBeVisible();
    expect(api.createdApiKey).toBe("one-time-canary");
    expect(screen.queryByText("one-time-canary")).not.toBeInTheDocument();
  });

  it("只有当前配置测试通过后才允许启用", async () => {
    renderProvidersPage();
    const enableButton = await screen.findByRole("button", { name: "启用" });

    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));
    expect(await screen.findByText("连接测试通过。")).toBeVisible();
    await waitFor(() => expect(enableButton).toBeEnabled());
    fireEvent.click(enableButton);

    expect(await screen.findByText("已启用")).toBeVisible();
  });
});
