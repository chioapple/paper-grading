import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../../features/auth/AuthContext";
import { AuthLayout } from "./AuthLayout";
import { authCopy } from "./authCopy";

type LoginLocationState = {
  from?: string;
};

export function LoginPage() {
  const { signIn } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [hasError, setHasError] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setHasError(false);
    setIsSubmitting(true);
    const data = new FormData(event.currentTarget);

    try {
      const account = await signIn(
        String(data.get("email") ?? "").trim(),
        String(data.get("password") ?? ""),
      );
      const state = location.state as LoginLocationState | null;
      navigate(
        account.status === "invited" ? "/auth/callback" : (state?.from ?? "/assignments"),
        { replace: true },
      );
    } catch {
      setHasError(true);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthLayout>
      {(language) => {
        const text = authCopy[language];
        return (
          <main className="auth-main">
            <section className="auth-form-panel" aria-labelledby="login-title">
              <h1 id="login-title">{text.loginTitle}</h1>
              <p className="auth-subtitle">{text.loginSubtitle}</p>
              <form className="auth-form" onSubmit={handleSubmit}>
                <label htmlFor="login-email">{text.email}</label>
                <input
                  autoComplete="email"
                  id="login-email"
                  name="email"
                  placeholder={text.emailPlaceholder}
                  required
                  type="email"
                />
                <label htmlFor="login-password">{text.password}</label>
                <input
                  autoComplete="current-password"
                  id="login-password"
                  name="password"
                  placeholder={text.passwordPlaceholder}
                  required
                  type="password"
                />
                {hasError ? (
                  <p className="form-message form-message--error" role="alert">
                    {text.invalidCredentials}
                  </p>
                ) : null}
                <button
                  className="primary-button auth-submit"
                  disabled={isSubmitting}
                  type="submit"
                >
                  {isSubmitting ? text.signingIn : text.signIn}
                </button>
                <Link className="auth-link" to="/forgot-password">
                  {text.forgotPassword}
                </Link>
              </form>
            </section>
          </main>
        );
      }}
    </AuthLayout>
  );
}
