import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "./AuthContext";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { account, error, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <main className="route-loading" aria-label="正在加载" />;
  }
  if (error) {
    return <AuthServiceError message={error} />;
  }
  if (!account) {
    const returnTo = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate replace state={{ from: returnTo }} to="/login" />;
  }
  if (account.status === "invited") {
    return <Navigate replace to="/auth/callback" />;
  }
  return children;
}

export function AdminRoute({ children }: { children: ReactNode }) {
  const { account } = useAuth();
  if (account?.role !== "admin" || account.status !== "active") {
    return <Navigate replace to="/assignments" />;
  }
  return children;
}

export function PublicOnlyRoute({ children }: { children: ReactNode }) {
  const { account, error, isLoading } = useAuth();
  const location = useLocation();
  if (isLoading) {
    return <main className="route-loading" aria-label="正在加载" />;
  }
  if (error) {
    return <AuthServiceError message={error} />;
  }
  if (account?.status === "invited") {
    return <Navigate replace to="/auth/callback" />;
  }
  if (account) {
    const state = location.state as { from?: string } | null;
    return <Navigate replace to={state?.from ?? "/assignments"} />;
  }
  return children;
}

function AuthServiceError({ message }: { message: string }) {
  return (
    <main className="auth-service-error">
      <h1>无法验证登录状态</h1>
      <p role="alert">{message}</p>
      <button onClick={() => window.location.reload()} type="button">
        刷新页面
      </button>
    </main>
  );
}
