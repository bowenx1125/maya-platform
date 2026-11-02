"use client";

import { DismissibleAlert } from "./dismissible-alert";
import { StatusScreen } from "./status-screen";
import { LoadingPage, StickerBadge } from "./ui";
import {
  clearLoginQueue,
  loadLoginQueue,
  loginQueueProgress,
  saveLoginQueue,
  type LoginQueueNotice,
  type SavedLoginQueue,
} from "../lib/login-queue";
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
import { resetChatRequestIdentity } from "../lib/chat-request-store";
import {
  observeFirstRender,
  setClientMetricsTransport,
} from "../lib/client-metrics";
import { localizeError, roleLabel, type MessageKey } from "../lib/i18n";
import { sanitizeNextPath } from "../lib/navigation";
import { endTeacherEnter } from "../lib/teacher-visit";
import { useSetAcademyMood } from "./academy/mood";
import { useT } from "../lib/i18n";

type SessionStatus = "loading" | "authenticated" | "anonymous";

type SessionContextValue = {
  api: PlatformApi;
  status: SessionStatus;
  session: AuthSession | null;
  user: CurrentUser | null;
  identityGeneration: number;
  error: unknown;
  refresh: () => Promise<AuthSession | null>;
  login: (
    username: string,
    password: string,
    options?: {
      onQueued?: (notice: LoginQueueNotice) => void;
      signal?: AbortSignal;
      ticket?: string;
    },
  ) => Promise<AuthSession>;
  register: (body: RegisterRequest) => Promise<AuthSession>;
  quickLogin: (userId: string) => Promise<AuthSession>;
  logout: () => Promise<void>;
  /** A sign-out is under way: guarded pages wait instead of asking to sign in. */
  signingOut: boolean;
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

function identityKey(session: AuthSession): string {
  const activeCourseId = session.user.courses[0]?.course_id ?? null;
  const courses = session.user.courses
    .map((course) => `${course.course_id}:${course.role}`)
    .sort();
  return JSON.stringify([session.user.id, activeCourseId, courses]);
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
  const [identityGeneration, setIdentityGeneration] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [signingOut, setSigningOut] = useState(false);
  const pathname = usePathname();
  const sessionOperationEpoch = useRef(0);
  const sessionMutationTail = useRef<Promise<void>>(Promise.resolve());
  const currentSession = useRef<AuthSession | null>(null);
  const committedIdentityKey = useRef<string | null>(null);
  const identityGenerationRef = useRef(0);
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
      const nextIdentityKey = identityKey(next);
      if (committedIdentityKey.current !== nextIdentityKey) {
        committedIdentityKey.current = nextIdentityKey;
        identityGenerationRef.current += 1;
        resetChatRequestIdentity();
        setIdentityGeneration(identityGenerationRef.current);
      }
      committedCsrfToken.current = next.csrf_token;
      writeApiCsrfToken(api, next.csrf_token);
      currentSession.current = next;
      setSession(next);
      setStatus("authenticated");
      setSigningOut(false);
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
      committedIdentityKey.current = null;
      identityGenerationRef.current += 1;
      resetChatRequestIdentity();
      setIdentityGeneration(identityGenerationRef.current);
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

  useEffect(() => {
    observeFirstRender();
  }, []);

  useEffect(() => {
    if (status !== "authenticated") {
      if (status === "anonymous") setClientMetricsTransport(null);
      return;
    }
    setClientMetricsTransport((metrics) => api.reportClientMetrics(metrics));
  }, [api, status]);

  const login = useCallback(
    (
      username: string,
      password: string,
      options?: {
        onQueued?: (notice: LoginQueueNotice) => void;
        signal?: AbortSignal;
        ticket?: string;
      },
    ) =>
      enqueueSessionMutation(async () => {
        const epoch = beginSessionOperation();
        try {
          const next = await api.login(username, password, options);
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
        setSigningOut(true);
        try {
          await api.logout();
          commitAnonymousSession(epoch);
        } catch (cause) {
          setSigningOut(false);
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

  // Leaving the page the sign-out started on ends the wait, so a later
  // expired session on another page still gets the sign-in prompt.
  const signOutPath = useRef<string | null>(null);
  useEffect(() => {
    if (!signingOut) {
      signOutPath.current = null;
      return;
    }
    if (signOutPath.current === null) signOutPath.current = pathname;
    else if (signOutPath.current !== pathname) setSigningOut(false);
  }, [pathname, signingOut]);

  const value = useMemo<SessionContextValue>(
    () => ({
      api,
      status,
      session,
      user: session?.user ?? null,
      identityGeneration,
      error,
      refresh,
      login,
      register,
      quickLogin,
      logout,
      signingOut,
      switchIdentity,
    }),
    [
      api,
      error,
      identityGeneration,
      login,
      register,
      logout,
      quickLogin,
      refresh,
      session,
      signingOut,
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
  const { status, user, refresh, signingOut } = useSession();
  const pathname = usePathname();
  const [visitCheck, setVisitCheck] = useState<"idle" | "done">("idle");

  // A teacher who has joined a group may open the student workspace for it.
  // Explicit teacher access opens the same editing workspace as student membership.
  // Course role alone would keep every
  // teacher out of the surface they just gave themselves access to.
  const teachesCourse = user?.courses?.some(
    (membership) => membership.role === "teacher",
  );
  const sitsInGroup = (user?.groups?.length ?? 0) > 0;
  const enrolledStudent = user?.courses?.some(
    (membership) => membership.role === "student",
  );
  const hasRole = !role
    ? true
    : role === "student"
      ? enrolledStudent || (teachesCourse && sitsInGroup)
      : teachesCourse;
  // The group page is behind this guard, and the shell that would reload the
  // session only mounts after the guard opens. Refresh here, or a teacher who
  // just joined still looks group-less and stays on the 403.
  const awaitingTeacherVisit =
    status === "authenticated" &&
    role === "student" &&
    Boolean(teachesCourse) &&
    !enrolledStudent &&
    !sitsInGroup;

  useEffect(() => {
    if (status === "authenticated" && role === "student") endTeacherEnter();
  }, [role, status]);

  useEffect(() => {
    if (!awaitingTeacherVisit) return;
    let active = true;
    void refresh().finally(() => {
      if (active) setVisitCheck("done");
    });
    return () => {
      active = false;
    };
  }, [awaitingTeacherVisit, refresh]);

  if (
    status === "loading" ||
    (status === "anonymous" && signingOut) ||
    (awaitingTeacherVisit && visitCheck !== "done")
  ) {
    return <LoadingPage />;
  }
  if (status === "anonymous") {
    return (
      <StatusScreen
        eyebrow={t("appName")}
        title={t("signInContinue")}
        body={t("sessionRequired")}
        action={t("signIn")}
        href={`/?next=${encodeURIComponent(pathname)}`}
        mascot="wave"
        mood="attentive"
      />
    );
  }

  if (!hasRole) {
    return (
      <StatusScreen
        alert
        eyebrow="403"
        title={t("viewUnavailable")}
        body={t("roleBoundary")}
        action={t("returnWorkspace")}
        href={
          user?.courses.some((item) => item.role === "teacher")
            ? "/teacher"
            : "/student"
        }
        primary={false}
        mascot="tablet"
        mood="refused"
      />
    );
  }

  return <>{children}</>;
}

export function LoginForm({ onRegister }: { onRegister?: () => void } = {}) {
  const t = useT();
  const router = useRouter();
  const { status, login, quickLogin, api, switchIdentity } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [queue, setQueue] = useState<LoginQueueNotice | null>(null);
  const [savedQueue, setSavedQueue] = useState<SavedLoginQueue | null>(null);
  const [resumeQueue, setResumeQueue] = useState(false);
  const savedQueueRef = useRef<SavedLoginQueue | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [errorFallback, setErrorFallback] = useState<MessageKey>("loginFailed");
  const [identities, setIdentities] = useState<DemoIdentity[]>([]);
  const [emptyField, setEmptyField] = useState<MessageKey | null>(null);
  // Bumped on every submit, so a closed message shows again on a repeat.
  const [attempt, setAttempt] = useState(0);
  const setMood = useSetAcademyMood();
  const loginAbort = useRef<AbortController | null>(null);

  useEffect(() => () => loginAbort.current?.abort(), []);

  useEffect(() => {
    // After a refresh, keep the typed name and the place in line. The
    // password was never stored, so the student only re-types it.
    const timer = window.setTimeout(() => {
      const saved = loadLoginQueue();
      if (!saved) return;
      savedQueueRef.current = saved;
      setSavedQueue(saved);
      setResumeQueue(true);
      setUsername((current) => current || saved.username);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

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
    setAttempt((value) => value + 1);
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
    setQueue(null);
    setResumeQueue(false);
    setErrorFallback("loginFailed");
    const controller = new AbortController();
    loginAbort.current = controller;
    // The stored copy is checked for expiry; a stale ticket simply rejoins.
    const held = loadLoginQueue();
    try {
      const session = await login(name, password, {
        signal: controller.signal,
        ticket: held?.ticket,
        onQueued: (notice) => {
          setMood("attentive");
          setQueue(notice);
          const next = saveLoginQueue(name, notice, savedQueueRef.current);
          savedQueueRef.current = next;
          setSavedQueue(next);
        },
      });
      clearLoginQueue();
      savedQueueRef.current = null;
      setSavedQueue(null);
      setQueue(null);
      router.replace(
        nextPath ||
          (session.user.courses.some((item) => item.role === "teacher")
            ? "/teacher"
            : "/student"),
      );
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      // A rejected sign-in has left the line; a network failure keeps the
      // ticket so the next attempt resumes the same place.
      if (!(cause instanceof TypeError)) {
        clearLoginQueue();
        savedQueueRef.current = null;
        setSavedQueue(null);
      }
      setQueue(null);
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

  // Only the "empty field" message names its field(s); others stay bubble-only.
  const nameInvalid =
    emptyField === "loginNeedBoth" || emptyField === "loginNeedUsername";
  const passwordInvalid =
    emptyField === "loginNeedBoth" || emptyField === "loginNeedPassword";
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
      {queue ? (
        <div className="login-queue" role="status" aria-live="polite">
          <p className="lede">
            {queue.reconnecting
              ? t("loginQueueReconnecting")
              : queue.position === 0
                ? t("loginQueueNext")
                : t("loginQueueWaiting", { position: queue.position })}
          </p>
          <div
            className="login-queue-bar"
            role="progressbar"
            aria-label={t("loginQueueProgressLabel")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(
              loginQueueProgress(
                queue.position,
                savedQueue?.initialPosition ?? queue.position,
              ) * 100,
            )}
          >
            <span
              style={{
                width: `${Math.round(
                  loginQueueProgress(
                    queue.position,
                    savedQueue?.initialPosition ?? queue.position,
                  ) * 100,
                )}%`,
              }}
            />
          </div>
          <small>
            {t("loginQueueEta", {
              seconds: queue.estimatedWaitSeconds,
              total: queue.queueLength,
            })}
          </small>
        </div>
      ) : resumeQueue && savedQueue ? (
        <p className="lede" role="status" aria-live="polite">
          {t("loginQueueResume", { position: savedQueue.position })}
        </p>
      ) : null}
      {emptyField ? (
        <DismissibleAlert
          kind="field"
          n={1}
          id="login-field-error"
          className="form-error"
          resetKey={`${attempt}:${emptyField}`}
        >
          {t(emptyField)}
        </DismissibleAlert>
      ) : error ? (
        <DismissibleAlert className="form-error" resetKey={error}>
          {localizeError(error, errorFallback)}
        </DismissibleAlert>
      ) : null}
      {hasDemoIdentities ? (
        <div className="login-divider" aria-hidden="true">
          <span>{t("or")}</span>
        </div>
      ) : null}
      <form className="stack-form login-form" noValidate onSubmit={submit}>
        <label>
          <span>{t("username")}</span>
          <span className="relative block">
            {nameInvalid ? <StickerBadge n={1} /> : null}
            <input
              aria-invalid={nameInvalid || undefined}
              aria-describedby={nameInvalid ? "login-field-error" : undefined}
              className="aria-invalid:border-err! aria-invalid:shadow-[0_0_0_3px_#FFE4E4,3px_3px_0_#EF4444]!"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              onFocus={() => setMood("attentive")}
              onBlur={() => setMood("idle")}
              required
            />
          </span>
        </label>
        <label>
          <span>{t("password")}</span>
          <span className="relative block">
            {passwordInvalid ? <StickerBadge n={1} /> : null}
            <input
              aria-invalid={passwordInvalid || undefined}
              aria-describedby={
                passwordInvalid ? "login-field-error" : undefined
              }
              className="aria-invalid:border-err! aria-invalid:shadow-[0_0_0_3px_#FFE4E4,3px_3px_0_#EF4444]!"
              autoComplete="current-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              onFocus={() => setMood("discreet")}
              onBlur={() => setMood("idle")}
              required
            />
          </span>
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
