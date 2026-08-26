"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import {
  PlatformApi,
  type AuthSession,
  type CurrentUser,
  type DemoIdentity,
} from "../lib/api";
import { localizeError, roleLabel, type MessageKey } from "../lib/i18n";
import { LanguageSwitcher, useLocale, useT } from "./locale";

type SessionStatus = "loading" | "authenticated" | "anonymous";

type SessionContextValue = {
  api: PlatformApi;
  status: SessionStatus;
  session: AuthSession | null;
  user: CurrentUser | null;
  error: unknown;
  refresh: () => Promise<AuthSession | null>;
  login: (username: string, password: string) => Promise<AuthSession>;
  logout: () => Promise<void>;
  switchIdentity: (userId: string) => Promise<AuthSession>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({
  children,
  api: providedApi,
}: {
  children: ReactNode;
  api?: PlatformApi;
}) {
  const api = useMemo(() => providedApi ?? new PlatformApi(), [providedApi]);
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [session, setSession] = useState<AuthSession | null>(null);
  const [error, setError] = useState<unknown>(null);

  const refresh = useCallback(async (): Promise<AuthSession | null> => {
    try {
      const next = await api.me();
      setSession(next);
      setStatus("authenticated");
      setError(null);
      return next;
    } catch (cause) {
      setSession(null);
      setStatus("anonymous");
      setError(
        cause instanceof Error && "status" in cause && cause.status === 401
          ? null
          : cause,
      );
      return null;
    }
  }, [api]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refresh();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  const login = useCallback(
    async (username: string, password: string) => {
      const next = await api.login(username, password);
      setSession(next);
      setStatus("authenticated");
      setError(null);
      return next;
    },
    [api],
  );

  const logout = useCallback(async () => {
    await api.logout();
    setSession(null);
    setStatus("anonymous");
  }, [api]);

  const switchIdentity = useCallback(
    async (userId: string) => {
      const next = await api.switchDemoIdentity(userId);
      setSession(next);
      setStatus("authenticated");
      setError(null);
      return next;
    },
    [api],
  );

  const value = useMemo<SessionContextValue>(
    () => ({
      api,
      status,
      session,
      user: session?.user ?? null,
      error,
      refresh,
      login,
      logout,
      switchIdentity,
    }),
    [api, error, login, logout, refresh, session, status, switchIdentity],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}

export function RouteGuard({
  children,
  role,
}: {
  children: ReactNode;
  role?: "teacher" | "student";
}) {
  const t = useT();
  const { status, user } = useSession();
  const pathname = usePathname();

  if (status === "loading") {
    return (
      <main className="shell">
        <div className="loading-card" role="status">
          {t("loading")}
        </div>
      </main>
    );
  }
  if (status === "anonymous") {
    return (
      <main className="shell">
        <section className="empty-card">
          <span className="eyebrow">{t("appName")}</span>
          <h1>{t("signInContinue")}</h1>
          <p>{t("sessionRequired")}</p>
          <Link
            className="primary-action"
            href={`/login?next=${encodeURIComponent(pathname)}`}
          >
            {t("signIn")}
          </Link>
        </section>
      </main>
    );
  }

  const hasRole = role
    ? user?.courses.some((membership) => membership.role === role)
    : true;
  if (!hasRole) {
    return (
      <main className="shell">
        <section className="empty-card" role="alert">
          <span className="eyebrow">403</span>
          <h1>{t("viewUnavailable")}</h1>
          <p>{t("roleBoundary")}</p>
          <Link
            className="secondary-action"
            href={
              user?.courses.some((item) => item.role === "teacher")
                ? "/teacher"
                : "/student"
            }
          >
            {t("returnWorkspace")}
          </Link>
        </section>
      </main>
    );
  }

  return <>{children}</>;
}

export function LoginForm() {
  const t = useT();
  const { locale } = useLocale();
  const router = useRouter();
  const { status, login, api, switchIdentity } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [errorFallback, setErrorFallback] = useState<MessageKey>("loginFailed");
  const [identities, setIdentities] = useState<DemoIdentity[]>([]);

  useEffect(() => {
    if (status === "authenticated") {
      void api
        .demoIdentities()
        .then(setIdentities)
        .catch(() => setIdentities([]));
    }
  }, [api, status]);

  const nextPath =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("next")
      : null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setErrorFallback("loginFailed");
    try {
      const session = await login(username.trim(), password);
      router.replace(
        nextPath ||
          (session.user.courses.some((item) => item.role === "teacher")
            ? "/teacher"
            : "/student"),
      );
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function quickSwitch(userId: string) {
    setBusy(true);
    setError(null);
    setErrorFallback("demoSwitchUnavailable");
    try {
      const session = await switchIdentity(userId);
      router.replace(
        session.user.courses.some((item) => item.role === "teacher")
          ? "/teacher"
          : "/student",
      );
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="auth-card" aria-labelledby="login-title">
      <div className="auth-language">
        <LanguageSwitcher />
      </div>
      <div className="eyebrow">{t("heroEyebrow")}</div>
      <h1 id="login-title">{t("signIn")}</h1>
      <p className="lede">{t("loginLede")}</p>
      <form className="stack-form" onSubmit={submit}>
        <label>
          <span>{t("username")}</span>
          <input
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </label>
        <label>
          <span>{t("password")}</span>
          <input
            autoComplete="current-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error ? (
          <p className="form-error" role="alert">
            {localizeError(error, locale, errorFallback)}
          </p>
        ) : null}
        <button className="primary-action" type="submit" disabled={busy}>
          {busy ? t("signingIn") : t("login")}
        </button>
      </form>
      {status === "authenticated" && identities.length > 0 ? (
        <div className="quick-switch" aria-label={t("demoIdentity")}>
          <span className="section-label">{t("demoIdentity")}</span>
          <div className="chip-row">
            {identities.map((identity) => (
              <button
                className="chip-button"
                key={identity.user_id}
                type="button"
                disabled={busy}
                onClick={() => void quickSwitch(identity.user_id)}
              >
                {identity.display_name} · {roleLabel(identity.role, locale)}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
