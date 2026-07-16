import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import { App } from "./app/App";
import { readAppEnvironment } from "./app/env";
import { AppApiProvider } from "./features/api/AppApiContext";
import { createHttpAppApi } from "./features/api/httpAppApi";
import { AuthProvider } from "./features/auth/AuthContext";
import { createBrowserAuthClient } from "./features/auth/supabaseAuthClient";
import "./app/styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      staleTime: 30_000,
    },
  },
});

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("缺少 #root 挂载节点");
}

const environment = readAppEnvironment({
  VITE_API_BASE_URL: import.meta.env.VITE_API_BASE_URL,
  VITE_SUPABASE_PUBLISHABLE_KEY: import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY,
  VITE_SUPABASE_URL: import.meta.env.VITE_SUPABASE_URL,
});
const authClient = createBrowserAuthClient(
  environment.supabaseUrl,
  environment.supabasePublishableKey,
);
const appApi = createHttpAppApi(environment.apiBaseUrl);

createRoot(rootElement).render(
  <StrictMode>
    <AppApiProvider api={appApi}>
      <AuthProvider
        authClient={authClient}
        completeInvite={(session) => appApi.completeInvite(session)}
        loadAccount={(session) => appApi.loadAccount(session)}
      >
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      </AuthProvider>
    </AppApiProvider>
  </StrictMode>,
);
