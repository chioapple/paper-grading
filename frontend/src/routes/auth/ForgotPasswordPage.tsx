import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "../../features/auth/AuthContext";
import { AuthLayout } from "./AuthLayout";
import { authCopy } from "./authCopy";

export function ForgotPasswordPage() {
  const { authClient } = useAuth();
  const [hasError, setHasError] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSent, setIsSent] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setHasError(false);
    const data = new FormData(event.currentTarget);
    const redirectTo = `${window.location.origin}/auth/callback?flow=recovery`;

    try {
      await authClient.requestPasswordReset(
        String(data.get("email") ?? "").trim(),
        redirectTo,
      );
      setIsSent(true);
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
            <section className="auth-form-panel" aria-labelledby="forgot-title">
              <h1 id="forgot-title">{text.forgotTitle}</h1>
              <p className="auth-subtitle">{text.forgotSubtitle}</p>
              {isSent ? (
                <div className="auth-result" role="status">
                  <p>{text.resetSent}</p>
                  <Link className="auth-link auth-link--start" to="/login">
                    {text.backToLogin}
                  </Link>
                </div>
              ) : (
                <form className="auth-form" onSubmit={handleSubmit}>
                  <label htmlFor="forgot-email">{text.email}</label>
                  <input
                    autoComplete="email"
                    id="forgot-email"
                    name="email"
                    placeholder={text.emailPlaceholder}
                    required
                    type="email"
                  />
                  {hasError ? (
                    <p className="form-message form-message--error" role="alert">
                      {text.resetFailed}
                    </p>
                  ) : null}
                  <button
                    className="primary-button auth-submit"
                    disabled={isSubmitting}
                    type="submit"
                  >
                    {isSubmitting ? text.sendingReset : text.sendReset}
                  </button>
                  <Link className="auth-link" to="/login">
                    {text.backToLogin}
                  </Link>
                </form>
              )}
            </section>
          </main>
        );
      }}
    </AuthLayout>
  );
}
