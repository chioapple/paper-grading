import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { App } from "../../../app/App";
import {
  AppApiProvider,
  type AssignmentDetail,
  type InviteTeacherInput,
  type ProviderConfig,
  type ProviderTestResult,
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

  accounts: TeacherAccount[] = [
    {
      id: "22222222-2222-4222-8222-222222222222",
      email: "zhang@example.com",
      display_name: "张老师",
      status: "active",
      invited_at: "2026-07-14T08:00:00Z",
    },
  ];

  async listTeachers() {
    return this.accounts;
  }

  async inviteTeacher(_session: BrowserSession, input: InviteTeacherInput) {
    const account: TeacherAccount = {
      id: "33333333-3333-4333-8333-333333333333",
      email: input.email,
      display_name: input.displayName,
      status: "invited",
      invited_at: "2026-07-14T09:00:00Z",
    };
    this.accounts = [...this.accounts, account];
    return account;
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

  async createProvider(): Promise<ProviderConfig> {
    throw new Error("本测试不使用供应商配置");
  }

  async updateProvider(): Promise<ProviderConfig> {
    throw new Error("本测试不使用供应商配置");
  }

  async testProvider(): Promise<ProviderTestResult> {
    throw new Error("本测试不使用供应商配置");
  }

  async enableProvider(): Promise<ProviderConfig> {
    throw new Error("本测试不使用供应商配置");
  }

  async disableProvider(): Promise<ProviderConfig> {
    throw new Error("本测试不使用供应商配置");
  }
}

function renderAdminApp(api = new TestAppApi()) {
  const authClient = new AdminAuthClient();
  const admin = {
    id: "11111111-1111-4111-8111-111111111111",
    email: "admin@example.com",
    display_name: "管理员",
    role: "admin" as const,
    status: "active" as const,
  };

  render(
    <AppApiProvider api={api}>
      <AuthProvider
        authClient={authClient}
        completeInvite={async () => admin}
        loadAccount={async () => admin}
      >
        <MemoryRouter initialEntries={["/admin/users"]}>
          <App />
        </MemoryRouter>
      </AuthProvider>
    </AppApiProvider>,
  );
  return api;
}

describe("教师账户管理", () => {
  it("管理员可以查看教师并发送新邀请", async () => {
    renderAdminApp();

    expect(await screen.findByText("zhang@example.com")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "邀请教师" }));
    fireEvent.change(screen.getByLabelText("姓名"), {
      target: { value: "李老师" },
    });
    fireEvent.change(screen.getByLabelText("邮箱"), {
      target: { value: "li@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送邀请" }));

    expect(await screen.findByText("li@example.com")).toBeVisible();
    expect(screen.getByText("待首次登录")).toBeVisible();
  });

  it("管理员可以停用并重新启用教师", async () => {
    renderAdminApp();

    fireEvent.click(await screen.findByRole("button", { name: "停用" }));
    expect(await screen.findByText("已停用")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "启用" }));
    expect(await screen.findByText("正常")).toBeVisible();
  });
});
