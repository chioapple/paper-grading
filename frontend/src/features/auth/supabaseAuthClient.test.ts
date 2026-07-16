import { render, screen } from "@testing-library/react";
import { createElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { App } from "../../app/App";
import { AuthProvider, type AuthClient, type BrowserSession } from "./AuthContext";

class ExistingSessionClient implements AuthClient {
  private readonly session = { accessToken: "existing-invite-session" };

  async getSession() {
    return this.session;
  }

  subscribe() {
    return () => undefined;
  }

  async signIn() {
    return this.session;
  }

  async requestPasswordReset() {}

  async consumeRedirect(): Promise<BrowserSession> {
    throw new Error("URL 已清理时不应再次兑换邀请码");
  }

  async updatePassword() {}

  async signOut() {}
}

describe("Supabase 浏览器会话", () => {
  it("邀请链接兑换并清理 URL 后，刷新回调页仍复用现有会话", async () => {
    const client = new ExistingSessionClient();
    render(
      createElement(
        AuthProvider,
        {
          authClient: client,
          completeInvite: async () => ({
            id: "11111111-1111-4111-8111-111111111111",
            email: "teacher@example.edu",
            display_name: "张老师",
            role: "teacher" as const,
            status: "active" as const,
          }),
          loadAccount: async () => ({
            id: "11111111-1111-4111-8111-111111111111",
            email: "teacher@example.edu",
            display_name: "张老师",
            role: "teacher" as const,
            status: "invited" as const,
          }),
          children: createElement(
            MemoryRouter,
            { initialEntries: ["/auth/callback"] },
            createElement(App),
          ),
        },
      ),
    );

    expect(await screen.findByRole("heading", { name: "设置首次密码" })).toBeVisible();
  });
});
