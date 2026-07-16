import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { App } from "../../app/App";
import { AppApiProvider } from "../api/AppApiContext";
import { EmptyAppApi } from "../../test/EmptyAppApi";
import {
  AuthProvider,
  type AuthClient,
  type BrowserSession,
} from "./AuthContext";

class TestAuthClient implements AuthClient {
  private session: BrowserSession | null;
  resetEmail: string | null = null;
  updatedPassword: string | null = null;

  constructor(session: BrowserSession | null = null) {
    this.session = session;
  }

  async getSession() {
    return this.session;
  }

  subscribe() {
    return () => undefined;
  }

  async signIn() {
    this.session = { accessToken: "teacher-token" };
    return this.session;
  }

  async requestPasswordReset(email: string) {
    this.resetEmail = email;
  }

  async consumeRedirect() {
    this.session = { accessToken: "invited-token" };
    return this.session;
  }

  async updatePassword(password: string) {
    this.updatedPassword = password;
  }

  async signOut() {
    this.session = null;
  }
}

class ExpiredLinkAuthClient extends TestAuthClient {
  override async consumeRedirect(): Promise<BrowserSession> {
    throw new Error("链接已过期");
  }
}

class FailingResetAuthClient extends TestAuthClient {
  override async requestPasswordReset(): Promise<void> {
    throw new Error("网络不可用");
  }
}

const activeTeacher = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "teacher@example.com",
  display_name: "张老师",
  role: "teacher" as const,
  status: "active" as const,
};

function renderAuthenticatedApp(path = "/assignments") {
  const client = new TestAuthClient({ accessToken: "teacher-token" });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return {
    client,
    view: render(
      <AppApiProvider api={new EmptyAppApi()}>
        <AuthProvider
          authClient={client}
          completeInvite={async () => activeTeacher}
          loadAccount={async () => activeTeacher}
        >
          <QueryClientProvider client={queryClient}>
            <MemoryRouter initialEntries={[path]}>
              <App />
            </MemoryRouter>
          </QueryClientProvider>
        </AuthProvider>
      </AppApiProvider>,
    ),
  };
}

function renderUnauthenticatedApp(
  path = "/assignments",
  status: "invited" | "active" = "active",
  client = new TestAuthClient(),
) {
  let currentStatus = status;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <AppApiProvider api={new EmptyAppApi()}>
      <AuthProvider
        authClient={client}
        loadAccount={async () => ({
          id: "11111111-1111-4111-8111-111111111111",
          email: "teacher@example.com",
          display_name: "张老师",
          role: "teacher",
          status: currentStatus,
        })}
        completeInvite={async () => {
          currentStatus = "active";
          return {
            id: "11111111-1111-4111-8111-111111111111",
            email: "teacher@example.com",
            display_name: "张老师",
            role: "teacher",
            status: "active",
          };
        }}
      >
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={[path]}>
            <App />
          </MemoryRouter>
        </QueryClientProvider>
      </AuthProvider>
    </AppApiProvider>,
  );
  return { client, view };
}

describe("登录流程", () => {
  it("未登录用户登录后进入受保护页面", async () => {
    renderUnauthenticatedApp();

    expect(await screen.findByRole("heading", { name: "欢迎登录" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("邮箱"), {
      target: { value: "teacher@example.com" },
    });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "correct-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "作业" })).toBeVisible();
    });
  });

  it("登录页语言开关会切换可见文案", async () => {
    renderUnauthenticatedApp("/login");

    fireEvent.click(await screen.findByRole("button", { name: "Switch to English" }));
    expect(screen.getByRole("heading", { name: "Welcome back" })).toBeVisible();
    expect(screen.getByLabelText("Email")).toBeVisible();
  });

  it("可以申请找回密码且不泄露邮箱是否存在", async () => {
    const { client } = renderUnauthenticatedApp();

    await screen.findByRole("heading", { name: "欢迎登录" });
    fireEvent.click(screen.getByRole("link", { name: "忘记密码？" }));
    fireEvent.change(screen.getByLabelText("邮箱"), {
      target: { value: "teacher@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送重置邮件" }));

    expect(
      await screen.findByText("如果邮箱已获邀请，你会收到密码重置邮件。"),
    ).toBeVisible();
    expect(client.resetEmail).toBe("teacher@example.com");
  });

  it("受邀教师通过有效链接设置首次密码并完成激活", async () => {
    const { client } = renderUnauthenticatedApp(
      "/auth/callback?code=valid-code",
      "invited",
    );

    expect(await screen.findByRole("heading", { name: "设置首次密码" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("新密码"), {
      target: { value: "safe-password-123" },
    });
    fireEvent.change(screen.getByLabelText("确认密码"), {
      target: { value: "safe-password-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存并登录" }));

    expect(await screen.findByRole("heading", { name: "作业" })).toBeVisible();
    expect(client.updatedPassword).toBe("safe-password-123");
  });

  it("已登录用户可以退出当前浏览器会话", async () => {
    renderAuthenticatedApp();

    fireEvent.click(await screen.findByRole("button", { name: "张老师" }));
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));

    expect(await screen.findByRole("heading", { name: "欢迎登录" })).toBeVisible();
  });

  it("过期邀请链接会明确提示重新申请", async () => {
    renderUnauthenticatedApp(
      "/auth/callback?code=expired-code",
      "invited",
      new ExpiredLinkAuthClient(),
    );

    expect(await screen.findByRole("heading", { name: "链接已失效" })).toBeVisible();
    expect(screen.getByText("邀请或重置链接无效或已过期，请重新申请。")).toBeVisible();
  });

  it("重置邮件请求失败时不会显示已发送", async () => {
    renderUnauthenticatedApp(
      "/forgot-password",
      "active",
      new FailingResetAuthClient(),
    );

    fireEvent.change(await screen.findByLabelText("邮箱"), {
      target: { value: "teacher@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送重置邮件" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "重置邮件发送失败，请稍后重试。",
    );
    expect(
      screen.queryByText("如果邮箱已获邀请，你会收到密码重置邮件。"),
    ).not.toBeInTheDocument();
  });

  it("教师不能进入管理员账户页面", async () => {
    renderAuthenticatedApp("/admin/users");

    expect(await screen.findByRole("heading", { name: "作业" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "教师账户管理" })).not.toBeInTheDocument();
  });

  it("后端拒绝旧会话时会清除浏览器持久会话", async () => {
    const client = new TestAuthClient({ accessToken: "disabled-token" });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <AppApiProvider api={new EmptyAppApi()}>
        <AuthProvider
          authClient={client}
          completeInvite={async () => activeTeacher}
          loadAccount={async () => {
            throw new Error("账户已停用");
          }}
        >
          <QueryClientProvider client={queryClient}>
            <MemoryRouter initialEntries={["/assignments"]}>
              <App />
            </MemoryRouter>
          </QueryClientProvider>
        </AuthProvider>
      </AppApiProvider>,
    );

    expect(await screen.findByRole("heading", { name: "无法验证登录状态" })).toBeVisible();
    expect(await client.getSession()).toBeNull();
  });
});
