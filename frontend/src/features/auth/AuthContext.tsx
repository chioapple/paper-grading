import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type BrowserSession = {
  accessToken: string;
};

export type Account = {
  id: string;
  email: string;
  display_name: string;
  role: "admin" | "teacher";
  status: "invited" | "active" | "disabled";
};

export interface AuthClient {
  getSession(): Promise<BrowserSession | null>;
  subscribe(listener: (session: BrowserSession | null) => void): () => void;
  signIn(email: string, password: string): Promise<BrowserSession>;
  requestPasswordReset(email: string, redirectTo: string): Promise<void>;
  consumeRedirect(search: string, hash: string): Promise<BrowserSession>;
  updatePassword(password: string): Promise<void>;
  signOut(): Promise<void>;
}

type AuthContextValue = {
  account: Account | null;
  authClient: AuthClient;
  error: string | null;
  isLoading: boolean;
  session: BrowserSession | null;
  activateInvite(session?: BrowserSession): Promise<Account>;
  signIn(email: string, password: string): Promise<Account>;
  signOut(): Promise<void>;
  refreshAccount(session?: BrowserSession): Promise<Account>;
};

type AuthProviderProps = {
  authClient: AuthClient;
  children: ReactNode;
  completeInvite(session: BrowserSession): Promise<Account>;
  loadAccount(session: BrowserSession): Promise<Account>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({
  authClient,
  children,
  completeInvite,
  loadAccount,
}: AuthProviderProps) {
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const syncSession = useCallback(
    async (nextSession: BrowserSession | null) => {
      setSession(nextSession);
      if (!nextSession) {
        setAccount(null);
        setError(null);
        setIsLoading(false);
        return null;
      }

      try {
        const nextAccount = await loadAccount(nextSession);
        setAccount(nextAccount);
        setError(null);
        return nextAccount;
      } catch (error) {
        await authClient.signOut();
        setAccount(null);
        setSession(null);
        setError("登录会话无法访问此账户，请重新登录。");
        throw error;
      } finally {
        setIsLoading(false);
      }
    },
    [authClient, loadAccount],
  );

  useEffect(() => {
    let isActive = true;

    void authClient
      .getSession()
      .then((initialSession) => {
        if (isActive) {
          void syncSession(initialSession).catch(() => undefined);
        }
      })
      .catch(() => {
        if (isActive) {
          setError("登录服务初始化失败，请刷新页面重试。");
          setIsLoading(false);
        }
      });

    const unsubscribe = authClient.subscribe((nextSession) => {
      if (isActive) {
        void syncSession(nextSession).catch(() => undefined);
      }
    });

    return () => {
      isActive = false;
      unsubscribe();
    };
  }, [authClient, syncSession]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const nextSession = await authClient.signIn(email, password);
      const nextAccount = await syncSession(nextSession);
      if (!nextAccount) {
        throw new Error("登录后未找到应用账户");
      }
      return nextAccount;
    },
    [authClient, syncSession],
  );

  const signOut = useCallback(async () => {
    await authClient.signOut();
    setSession(null);
    setAccount(null);
    setError(null);
  }, [authClient]);

  const refreshAccount = useCallback(
    async (nextSession = session ?? undefined) => {
      if (!nextSession) {
        throw new Error("当前没有登录会话");
      }
      const nextAccount = await loadAccount(nextSession);
      setSession(nextSession);
      setAccount(nextAccount);
      setError(null);
      return nextAccount;
    },
    [loadAccount, session],
  );

  const activateInvite = useCallback(
    async (nextSession = session ?? undefined) => {
      if (!nextSession) {
        throw new Error("当前没有登录会话");
      }
      const nextAccount = await completeInvite(nextSession);
      setSession(nextSession);
      setAccount(nextAccount);
      setError(null);
      return nextAccount;
    },
    [completeInvite, session],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      account,
      activateInvite,
      authClient,
      error,
      isLoading,
      session,
      signIn,
      signOut,
      refreshAccount,
    }),
    [
      account,
      activateInvite,
      authClient,
      error,
      isLoading,
      refreshAccount,
      session,
      signIn,
      signOut,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// Provider 与 hook 同文件，避免公开内部 Context。
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("AuthProvider 未挂载");
  }
  return value;
}
