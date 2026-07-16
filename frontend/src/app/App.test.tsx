import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import {
  AuthProvider,
  type AuthClient,
} from "../features/auth/AuthContext";
import { AppApiProvider } from "../features/api/AppApiContext";
import { EmptyAppApi } from "../test/EmptyAppApi";
import { App } from "./App";

const session = { accessToken: "teacher-token" };

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

function renderApp(path = "/assignments") {
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
  return render(
    <AppApiProvider api={new EmptyAppApi()}>
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
}

describe("App", () => {
  it("显示作业空状态", async () => {
    renderApp();

    expect(await screen.findByRole("heading", { name: "作业" })).toBeVisible();
    expect(
      await screen.findByRole("heading", { name: "还没有作业" }),
    ).toBeVisible();
  });

  it("创建入口进入创建页面", async () => {
    renderApp();

    fireEvent.click(await screen.findByRole("link", { name: "创建作业" }));
    expect(screen.getByRole("heading", { name: "创建作业" })).toBeVisible();
  });

  it("可以切换英文界面", async () => {
    renderApp();

    fireEvent.click(await screen.findByRole("button", { name: "Switch to English" }));
    expect(screen.getByRole("heading", { name: "Assignments" })).toBeVisible();
    expect(
      screen.getByRole("complementary", { name: "Main navigation" }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { name: "Assignments" })).toBeVisible();
    expect(document.documentElement.lang).toBe("en");
  });

  it("导航会切换到批改任务页面", async () => {
    renderApp();

    fireEvent.click(await screen.findByRole("link", { name: "批改任务" }));
    expect(screen.getByRole("heading", { name: "批改任务" })).toBeVisible();
  });

  it("账户入口会显示当前账户状态", async () => {
    renderApp();

    fireEvent.click(await screen.findByRole("button", { name: "张老师" }));
    expect(screen.getByRole("heading", { name: "当前账户" })).toBeVisible();
    expect(screen.getByText("角色：教师")).toBeVisible();
  });
});
