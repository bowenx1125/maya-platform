"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import {
  PlatformApi,
  type AuthSession,
  type CurrentUser,
  type DemoIdentity,
  type RegisterRequest,
} from "../lib/api";
import { localizeError, roleLabel, type MessageKey } from "../lib/i18n";
import { sanitizeNextPath } from "../lib/navigation";
import { useSetAcademyMood } from "./academy/mood";
import { useLocale, useT } from "./locale";

type SessionStatus = "loading" | "authenticated" | "anonymous";

type SessionContextValue = {
  api: PlatformApi;
  status: SessionStatus;
  session: AuthSession | null;
  user: CurrentUser | null;
  error: unknown;
  refresh: () => Promise<AuthSession | null>;
  login: (username: string, password: string) => Promise<AuthSession>;
  register: (body: RegisterRequest) => Promise<AuthSession>;
  quickLogin: (userId: string) => Promise<AuthSession>;
  logout: () => Promise<void>;
  switchIdentity: (userId: string) => Promise<AuthSession>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

type SessionApiWithCsrfHelpers = PlatformApi & {
  getCsrfToken?: () => string | undefined;
  setCsrfToken?: (token: string | undefined) => void;
};

function readApiCsrfToken(api: PlatformApi): string | undefined {
  const candidate = api as SessionApiWithCsrfHelpers;
  try {
    const token = candidate.getCsrfToken?.();
    return typeof token === "string" ? token : undefined;
  } catch {
    return undefined;
  }
}

function writeApiCsrfToken(api: PlatformApi, token: string | undefined): void {
  const candidate = api as SessionApiWithCsrfHelpers;
  candidate.setCsrfToken?.(token);
}

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
  const sessionOperationEpoch = useRef(0);
  const sessionMutationTail = useRef<Promise<void>>(Promise.resolve());
  const currentSession = useRef<AuthSession | null>(null);
  const committedCsrfToken = useRef<string | undefined>(readApiCsrfToken(api));

  const enqueueSessionMutation = useCallback(
    <T,>(operation: () => Promise<T>): Promise<T> => {
      const run = sessionMutationTail.current.then(operation, operation);
      sessionMutationTail.current = run.then(
        () => undefined,
        () => undefined,
      );
      return run;
    },
    [],
  );

  const beginSessionOperation = useCallback(() => {
    const epoch = sessionOperationEpoch.current + 1;
    sessionOperationEpoch.current = epoch;
    // PlatformApi methods also update their in-memory token when they settle.
    // Restore the last accepted token before every request so a late method
    // cannot use a token left behind by an older operation.
    writeApiCsrfToken(api, committedCsrfToken.current);
    return epoch;
  }, [api]);

  const restoreCommittedCsrf = useCallback(() => {
    writeApiCsrfToken(api, committedCsrfToken.current);
  }, [api]);

  const commitAuthenticatedSession = useCallback(
    (epoch: number, next: AuthSession): void => {
      if (sessionOperationEpoch.current !== epoch) {
        restoreCommittedCsrf();
        return;
      }
      committedCsrfToken.current = next.csrf_token;
      writeApiCsrfToken(api, next.csrf_token);
      currentSession.current = next;
      setSession(next);
      setStatus("authenticated");
      setError(null);
    },
    [api, restoreCommittedCsrf],
  );

  const commitAnonymousSession = useCallback(
    (epoch: number, nextError: unknown = null): void => {
      if (sessionOperationEpoch.current !== epoch) {
        restoreCommittedCsrf();
        return;
      }
      committedCsrfToken.current = undefined;
      writeApiCsrfToken(api, undefined);
      currentSession.current = null;
      setSession(null);
      setStatus("anonymous");
      setError(nextError);
    },
    [api, restoreCommittedCsrf],
  );

  const refresh = useCallback(async (): Promise<AuthSession | null> => {
    // A mutation may already have rotated the real cookie while its response
    // is still settling. Wait for all queued auth mutations before starting a
    // new /me check; the epoch below still fences an already-running /me.
    while (true) {
      const mutationTail = sessionMutationTail.current;
      await mutationTail;
      if (mutationTail === sessionMutationTail.current) break;
    }
    const epoch = beginSessionOperation();
    try {
      const next = await api.me();
      commitAuthenticatedSession(epoch, next);
      return next;
    } catch (cause) {
      if (sessionOperationEpoch.current !== epoch) {
        restoreCommittedCsrf();
        return null;
      }
      commitAnonymousSession(
        epoch,
        cause instanceof Error && "status" in cause && cause.status === 401
          ? null
          : cause,
      );
      return null;
    }
  }, [
    api,
    beginSessionOperation,
    commitAnonymousSession,
    commitAuthenticatedSession,
    restoreCommittedCsrf,
  ]);

  const preserveSessionAfterFailure = useCallback(
    (epoch: number): void => {
      restoreCommittedCsrf();
      // A failed login can race the initial /me check. If no session has ever
      // been accepted, do not leave the provider stuck in its initial loading
      // state while the superseded refresh result is ignored.
      if (
        sessionOperationEpoch.current === epoch &&
        currentSession.current === null
      ) {
        setStatus("anonymous");
      }
    },
    [restoreCommittedCsrf],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refresh();
    }, 0);
    return () => {
      window.clearTimeout(timer);
      sessionOperationEpoch.current += 1;
    };
  }, [refresh]);

  const login = useCallback(
    (username: string, password: string) =>
      enqueueSessionMutation(async () => {
        const epoch = beginSessionOperation();
        try {
          const next = await api.login(username, password);
          commitAuthenticatedSession(epoch, next);
          return next;
        } catch (cause) {
          preserveSessionAfterFailure(epoch);
          throw cause;
        }
      }),
    [
      api,
      beginSessionOperation,
      commitAuthenticatedSession,
      enqueueSessionMutation,
      preserveSessionAfterFailure,
    ],
  );

  const register = useCallback(
    (body: RegisterRequest) =>
      enqueueSessionMutation(async () => {
        const epoch = beginSessionOperation();
        try {
          // Registration returns a started session, so it commits through the
          // same path as a login rather than leaving the caller signed out.
          const next = await api.register(body);
          commitAuthenticatedSession(epoch, next);
          return next;
        } catch (cause) {
          preserveSessionAfterFailure(epoch);
          throw cause;
        }
      }),
    [
      api,
      beginSessionOperation,
      commitAuthenticatedSession,
      enqueueSessionMutation,
      preserveSessionAfterFailure,
    ],
  );

  const quickLogin = useCallback(
    (userId: string) =>
      enqueueSessionMutation(async () => {
        const epoch = beginSessionOperation();
        try {
          const next = await api.quickLogin(userId);
          commitAuthenticatedSession(epoch, next);
          return next;
        } catch (cause) {
          preserveSessionAfterFailure(epoch);
          throw cause;
        }
      }),
    [
      api,
      beginSessionOperation,
      commitAuthenticatedSession,
      enqueueSessionMutation,
      preserveSessionAfterFailure,
    ],
  );

  const logout = useCallback(
    () =>
      enqueueSessionMutation(async () => {
        const epoch = beginSessionOperation();
        try {
          await api.logout();
          commitAnonymousSession(epoch);
        } catch (cause) {
          preserveSessionAfterFailure(epoch);
          throw cause;
        }
      }),
    [
      api,
      beginSessionOperation,
      commitAnonymousSession,
      enqueueSessionMutation,
      preserveSessionAfterFailure,
    ],
  );

  const switchIdentity = useCallback(
    (userId: string) =>
      enqueueSessionMutation(async () => {
        const epoch = beginSessionOperation();
        try {
          const next = await api.switchDemoIdentity(userId);
          commitAuthenticatedSession(epoch, next);
          return next;
        } catch (cause) {
          preserveSessionAfterFailure(epoch);
          throw cause;
        }
      }),
    [
      api,
      beginSessionOperation,
      commitAuthenticatedSession,
      enqueueSessionMutation,
      preserveSessionAfterFailure,
    ],
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
      register,
      quickLogin,
      logout,
      switchIdentity,
    }),
    [
      api,
      error,
      login,
      register,
      logout,
      quickLogin,
      refresh,
      session,
      status,
      switchIdentity,
    ],
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
            href={`/?next=${encodeURIComponent(pathname)}`}
          >
            {t("signIn")}
          </Link>
        </section>
      </main>
    );
  }

  // A teacher who has joined a group may open the student workspace for it.
  // That is the whole point of joining: the shared teaching account walks into
  // a group to see what its students see. Course role alone would keep every
  // teacher out of the surface they just gave themselves access to.
  const teachesCourse = user?.courses?.some(
    (membership) => membership.role === "teacher",
  );
  const sitsInGroup = (user?.groups?.length ?? 0) > 0;
  const hasRole = !role
    ? true
    : role === "student"
      ? user?.courses?.some((membership) => membership.role === "student") ||
        (teachesCourse && sitsInGroup)
      : teachesCourse;
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

export function LoginForm({ onRegister }: { onRegister?: () => void } = {}) {
  const t = useT();
  const { locale } = useLocale();
  const router = useRouter();
  const { status, login, quickLogin, api, switchIdentity } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [errorFallback, setErrorFallback] = useState<MessageKey>("loginFailed");
  const [identities, setIdentities] = useState<DemoIdentity[]>([]);
  const [emptyField, setEmptyField] = useState<MessageKey | null>(null);
  const setMood = useSetAcademyMood();

  useEffect(() => {
    // The shake is a one-shot reaction, not a state the panel stays in.
    if (!error) return;
    setMood("refused");
    const timer = window.setTimeout(() => setMood("idle"), 900);
    return () => window.clearTimeout(timer);
  }, [error, setMood]);

  useEffect(() => {
    let active = true;
    void api
      .demoIdentities()
      .then((next) => {
        if (active) setIdentities(Array.isArray(next) ? next : []);
      })
      .catch(() => {
        if (active) setIdentities([]);
      });
    return () => {
      active = false;
    };
  }, [api]);

  const requestedNext =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("next")
      : null;
  const nextPath = sanitizeNextPath(requestedNext);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = username.trim();
    // An empty field is a typo, not a rejected credential. Naming which one is
    // missing avoids a round trip that could only answer "that failed".
    if (!name || !password) {
      setError(null);
      setEmptyField(
        !name && !password
          ? "loginNeedBoth"
          : !name
            ? "loginNeedUsername"
            : "loginNeedPassword",
      );
      return;
    }
    setEmptyField(null);
    setBusy(true);
    setError(null);
    setErrorFallback("loginFailed");
    try {
      const session = await login(name, password);
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

  async function chooseDemoIdentity(userId: string) {
    setBusy(true);
    setError(null);
    setErrorFallback("demoSwitchUnavailable");
    try {
      // Retain the CSRF-protected switch for an already authenticated user;
      // anonymous login uses the dedicated passwordless route with no secret
      // account fields in the browser.
      const session =
        status === "authenticated"
          ? await switchIdentity(userId)
          : await quickLogin(userId);
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

  const hasDemoIdentities = identities.length > 0;

  return (
    <section className="login-panel" aria-labelledby="login-title">
      <h2 id="login-title">
        {hasDemoIdentities ? t("demoIdentity") : t("signIn")}
      </h2>
      {hasDemoIdentities ? (
        <div className="quick-switch" aria-label={t("demoIdentity")}>
          <div className="chip-row">
            {identities.map((identity) => (
              <button
                className="chip-button"
                key={identity.user_id}
                type="button"
                disabled={busy}
                onClick={() => void chooseDemoIdentity(identity.user_id)}
              >
                {identity.display_name}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      {emptyField ? (
        <p className="form-error" role="alert">
          {t(emptyField)}
        </p>
      ) : error ? (
        <p className="form-error" role="alert">
          {localizeError(error, locale, errorFallback)}
        </p>
      ) : null}
      {hasDemoIdentities ? (
        <div className="login-divider" aria-hidden="true">
          <span>{t("or")}</span>
        </div>
      ) : null}
      <form className="stack-form login-form" noValidate onSubmit={submit}>
        <label>
          <span>{t("username")}</span>
          <input
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            onFocus={() => setMood("attentive")}
            onBlur={() => setMood("idle")}
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
            onFocus={() => setMood("discreet")}
            onBlur={() => setMood("idle")}
            required
          />
        </label>
        <button className="primary-action" type="submit" disabled={busy}>
          {busy ? t("signingIn") : t("signIn")}
        </button>
        {onRegister ? (
          <p className="academy-switch">
            {t("needAccount")}{" "}
            <button
              className="academy-textlink"
              type="button"
              disabled={busy}
              onClick={onRegister}
            >
              {t("needAccountLink")}
            </button>
          </p>
        ) : null}
      </form>
    </section>
  );
}
