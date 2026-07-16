import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import {
  useAuth,
  type Account,
  type BrowserSession,
} from "../../features/auth/AuthContext";
import { AuthLayout } from "./AuthLayout";
import { authCopy } from "./authCopy";

type CallbackState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; account: Account; session: BrowserSession };

export function AuthCallbackPage() {
  const { activateInvite, authClient, refreshAccount } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [state, setState] = useState<CallbackState>({ kind: "loading" });
  const [formError, setFormError] = useState<"mismatch" | "save" | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const sessionRequest = useRef<{
    key: string;
    promise: Promise<BrowserSession>;
  } | null>(null);

  useEffect(() => {
    let isActive = true;

    async function preparePasswordForm() {
      try {
        const hash = location.hash;
        const requestKey = `${location.search}\n${hash}`;
        if (sessionRequest.current?.key !== requestKey) {
          const promise =
            location.search || hash
              ? authClient.consumeRedirect(location.search, hash)
              : authClient.getSession().then((existingSession) => {
                  if (!existingSession) {
                    throw new Error("安全链接没有可用会话");
                  }
                  return existingSession;
                });
          sessionRequest.current = { key: requestKey, promise };
        }
        const callbackSession = await sessionRequest.current.promise;
        const account = await refreshAccount(callbackSession);
        if (isActive) {
          setState({ kind: "ready", account, session: callbackSession });
        }
      } catch {
        if (isActive) {
          setState({ kind: "error" });
        }
      }
    }

    void preparePasswordForm();
    return () => {
      isActive = false;
    };
  }, [authClient, location.hash, location.search, refreshAccount]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state.kind !== "ready") {
      return;
    }
    const data = new FormData(event.currentTarget);
    const password = String(data.get("password") ?? "");
    const confirmation = String(data.get("confirmation") ?? "");
    if (password !== confirmation) {
      setFormError("mismatch");
      return;
    }

    setFormError(null);
    setIsSubmitting(true);
    try {
      await authClient.updatePassword(password);
      if (state.account.status === "invited") {
        await activateInvite(state.session);
      } else {
        await refreshAccount(state.session);
      }
      navigate("/assignments", { replace: true });
    } catch {
      setFormError("save");
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
            <section className="auth-form-panel" aria-live="polite">
          {state.kind === "loading" ? (
            <div className="auth-result" role="status">
              {text.checkingLink}
            </div>
          ) : null}
          {state.kind === "error" ? (
            <div className="auth-result auth-result--error">
              <h1>{text.expiredTitle}</h1>
              <p>{text.expiredMessage}</p>
              <Link className="auth-link auth-link--start" to="/login">
                {text.backToLogin}
              </Link>
            </div>
          ) : null}
          {state.kind === "ready" ? (
            <>
              <h1>
                {state.account.status === "invited"
                  ? text.firstPasswordTitle
                  : text.newPasswordTitle}
              </h1>
              <p className="auth-subtitle">{text.passwordHint}</p>
              <form className="auth-form" onSubmit={handleSubmit}>
                <label htmlFor="new-password">{text.newPassword}</label>
                <input
                  autoComplete="new-password"
                  id="new-password"
                  minLength={8}
                  name="password"
                  required
                  type="password"
                />
                <label htmlFor="confirm-password">{text.confirmPassword}</label>
                <input
                  autoComplete="new-password"
                  id="confirm-password"
                  minLength={8}
                  name="confirmation"
                  required
                  type="password"
                />
                {formError ? (
                  <p className="form-message form-message--error" role="alert">
                    {formError === "mismatch"
                      ? text.passwordMismatch
                      : text.passwordSaveFailed}
                  </p>
                ) : null}
                <button
                  className="primary-button auth-submit"
                  disabled={isSubmitting}
                  type="submit"
                >
                  {isSubmitting ? text.saving : text.saveAndSignIn}
                </button>
              </form>
            </>
          ) : null}
            </section>
          </main>
        );
      }}
    </AuthLayout>
  );
}
