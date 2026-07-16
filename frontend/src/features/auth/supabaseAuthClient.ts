import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";

import type { AuthClient, BrowserSession } from "./AuthContext";

function toBrowserSession(session: Session | null): BrowserSession | null {
  return session ? { accessToken: session.access_token } : null;
}

class SupabaseBrowserAuthClient implements AuthClient {
  constructor(private readonly client: SupabaseClient) {}

  async getSession() {
    const { data, error } = await this.client.auth.getSession();
    if (error) {
      throw error;
    }
    return toBrowserSession(data.session);
  }

  subscribe(listener: (session: BrowserSession | null) => void) {
    const { data } = this.client.auth.onAuthStateChange((_event, session) => {
      listener(toBrowserSession(session));
    });
    return () => data.subscription.unsubscribe();
  }

  async signIn(email: string, password: string) {
    const { data, error } = await this.client.auth.signInWithPassword({ email, password });
    if (error || !data.session) {
      throw error ?? new Error("Supabase 登录未返回会话");
    }
    return { accessToken: data.session.access_token };
  }

  async requestPasswordReset(email: string, redirectTo: string) {
    const { error } = await this.client.auth.resetPasswordForEmail(email, { redirectTo });
    if (error) {
      throw error;
    }
  }

  async consumeRedirect(search: string, hash: string) {
    const query = new URLSearchParams(search);
    const code = query.get("code");
    if (code) {
      const { data, error } = await this.client.auth.exchangeCodeForSession(code);
      if (error || !data.session) {
        throw error ?? new Error("Supabase 安全链接未返回会话");
      }
      window.history.replaceState({}, document.title, window.location.pathname);
      return { accessToken: data.session.access_token };
    }

    const fragment = new URLSearchParams(hash.replace(/^#/, ""));
    const accessToken = fragment.get("access_token");
    const refreshToken = fragment.get("refresh_token");
    if (accessToken && refreshToken) {
      const { data, error } = await this.client.auth.setSession({
        access_token: accessToken,
        refresh_token: refreshToken,
      });
      if (error || !data.session) {
        throw error ?? new Error("Supabase 邀请链接未返回会话");
      }
      window.history.replaceState({}, document.title, window.location.pathname);
      return { accessToken: data.session.access_token };
    }

    throw new Error("安全链接没有可用会话");
  }

  async updatePassword(password: string) {
    const { error } = await this.client.auth.updateUser({ password });
    if (error) {
      throw error;
    }
  }

  async signOut() {
    const { error } = await this.client.auth.signOut({ scope: "local" });
    if (error) {
      throw error;
    }
  }
}

export function createBrowserAuthClient(url: string, publishableKey: string): AuthClient {
  const client = createClient(url, publishableKey, {
    auth: {
      detectSessionInUrl: false,
      flowType: "pkce",
      persistSession: true,
    },
  });
  return new SupabaseBrowserAuthClient(client);
}
