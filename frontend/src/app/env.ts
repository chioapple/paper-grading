type BrowserEnv = {
  VITE_API_BASE_URL?: string;
  VITE_SUPABASE_PUBLISHABLE_KEY?: string;
  VITE_SUPABASE_URL?: string;
};

export type AppEnvironment = {
  apiBaseUrl: string;
  supabasePublishableKey: string;
  supabaseUrl: string;
};

function requireValue(value: string | undefined, name: string) {
  if (!value?.trim()) {
    throw new Error(`缺少 ${name}`);
  }
  return value.trim();
}

function requireHttpUrl(value: string, name: string) {
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
    throw new Error(`${name} 必须是无凭据的 HTTP(S) 地址`);
  }
  return value.replace(/\/$/, "");
}

export function readAppEnvironment(environment: BrowserEnv): AppEnvironment {
  return {
    apiBaseUrl: requireHttpUrl(
      requireValue(environment.VITE_API_BASE_URL, "VITE_API_BASE_URL"),
      "VITE_API_BASE_URL",
    ),
    supabasePublishableKey: requireValue(
      environment.VITE_SUPABASE_PUBLISHABLE_KEY,
      "VITE_SUPABASE_PUBLISHABLE_KEY",
    ),
    supabaseUrl: requireHttpUrl(
      requireValue(environment.VITE_SUPABASE_URL, "VITE_SUPABASE_URL"),
      "VITE_SUPABASE_URL",
    ),
  };
}
