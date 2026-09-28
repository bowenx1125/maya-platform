"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";

import {
  ChatRequestPendingError,
  PlatformApiError,
  type PlatformApi,
  type ChatAgent,
  type ChatSession,
} from "../lib/api";
import {
  abandonChatRequest,
  adoptPendingChatRequest,
  adoptUncertainChatRequest,
  beginChatRequest,
  clearSettledChatSession,
  createChatRequestAttempt,
  getChatRequest,
  getSettledChatSession,
  isChatRequestAttemptCurrent,
  isChatRequestScopeActive,
  markChatRequestUncertain,
  observeChatRequestOnTurn,
  retryChatRequestAtRevision,
  setChatRequestScope,
  settleChatRequest,
  subscribeChatRequest,
} from "../lib/chat-request-store";
import { useT } from "./locale";
import { IconClose } from "./quiet-icons";
import { ReportMarkdown } from "./report/report-markdown";
import { useSession } from "./session-provider";
import { EmptyCard, ErrorNotice, LoadingCard, PageIntro } from "./ui";
import { WorkspaceAction } from "./workspace-actions";
import { TeamEntryFlow } from "./chats/team-entry-flow";
import styles from "./agent-chat.module.css";

function unknownChatOutcomeError() {
  return new PlatformApiError(503, "chat_acceptance_unknown", {
    code: "chat_acceptance_unknown",
    message: "chat_acceptance_unknown",
  });
}

export function AgentChat() {
  const { api, identityGeneration, user } = useSession();
  const courseId = user?.courses[0]?.course_id;
  const scopeKey =
    user && courseId ? `${identityGeneration}:${user.id}:${courseId}` : null;
  if (!scopeKey || !courseId) {
    return (
      <>
        <WorkspaceAction name="new" disabled />
        <LoadingCard />
      </>
    );
  }
  return (
    <AgentChatScope
      key={scopeKey}
      api={api}
      courseId={courseId}
      scopeKey={scopeKey}
    />
  );
}

function AgentChatScope({
  api,
  courseId,
  scopeKey,
}: {
  api: PlatformApi;
  courseId: string;
  scopeKey: string;
}) {
  const t = useT();
  const [agents, setAgents] = useState<ChatAgent[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [selected, setSelected] = useState<ChatSession | null>(null);
  const [versionId, setVersionId] = useState("");
  const [draft, setDraft] = useState(() => {
    const pending = getChatRequest(scopeKey);
    return pending &&
      (pending.status === "uncertain" ||
        (pending.status === "observing" &&
          pending.observedTurnId !== pending.requestId))
      ? pending.message
      : "";
  });
  const [pendingMessage, setPendingMessage] = useState(() => {
    const pending = getChatRequest(scopeKey);
    return pending?.promise && pending.status === "in_flight"
      ? pending.message
      : "";
  });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(() => {
    const pending = getChatRequest(scopeKey);
    return pending?.promise != null || pending?.status === "observing";
  });
  const [requestState, setRequestState] = useState(() =>
    getChatRequest(scopeKey),
  );
  const [error, setError] = useState<unknown>(null);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const [historyRefreshTarget, setHistoryRefreshTarget] =
    useState<ChatSession | null>(null);
  const [showNewEntry, setShowNewEntry] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const sendSequence = useRef(0);
  const uiRevision = useRef(0);
  const historyOpenSequence = useRef(0);

  const remember = useCallback(
    (value: ChatSession, activateIfEmpty = false) => {
      if (!isChatRequestScopeActive(scopeKey)) return;
      setSelected((current) => {
        if (!current) return activateIfEmpty ? value : current;
        if (current && current.id !== value.id) return current;
        return current && current.revision > value.revision ? current : value;
      });
      setSessions((current) => {
        const previous = current.find((item) => item.id === value.id);
        const next =
          previous && previous.revision > value.revision ? previous : value;
        return [next, ...current.filter((item) => item.id !== value.id)];
      });
    },
    [scopeKey],
  );

  useEffect(() => {
    let active = true;
    setChatRequestScope(scopeKey);
    void Promise.all([api.chatAgents(courseId), api.conversations()])
      .then(([catalog, history]) => {
        if (!active || !isChatRequestScopeActive(scopeKey)) return;
        setAgents(catalog);
        const settled = getSettledChatSession(scopeKey);
        let nextHistory = history;
        if (settled) {
          nextHistory = [
            settled,
            ...history.filter((item) => item.id !== settled.id),
          ];
          clearSettledChatSession(scopeKey);
        }
        setSessions(nextHistory);
        let pending = getChatRequest(scopeKey);
        const storedRequest = pending;
        let reconciledCurrentTerminal = false;
        if (storedRequest?.sessionId) {
          const savedSession = nextHistory.find(
            (session) => session.id === storedRequest.sessionId,
          );
          const savedTurn = savedSession?.turns.find(
            (turn) => turn.id === storedRequest.requestId,
          );
          if (savedTurn?.state === "ready" && savedSession) {
            settleChatRequest(
              storedRequest.requestId,
              savedSession,
              scopeKey,
              storedRequest.attemptId,
            );
            clearSettledChatSession(scopeKey);
            pending = null;
            reconciledCurrentTerminal = true;
            setDraft("");
            setPendingMessage("");
            setError(null);
          } else if (savedTurn?.state === "failed" && savedSession) {
            const code = savedTurn.safe_error_code ?? "chat_failed";
            setError(new PlatformApiError(503, code, { code, message: code }));
            settleChatRequest(
              storedRequest.requestId,
              savedSession,
              scopeKey,
              storedRequest.attemptId,
            );
            clearSettledChatSession(scopeKey);
            pending = null;
            reconciledCurrentTerminal = true;
            setDraft("");
            setPendingMessage("");
          } else if (
            savedTurn?.state === "acceptance_unknown" &&
            savedSession
          ) {
            markChatRequestUncertain(
              storedRequest.requestId,
              scopeKey,
              storedRequest.attemptId,
            );
            pending = getChatRequest(scopeKey);
            setError(unknownChatOutcomeError());
            setDraft((current) => current || pending?.message || "");
          } else if (savedTurn?.state === "pending") {
            observeChatRequestOnTurn(
              storedRequest.requestId,
              storedRequest.requestId,
              scopeKey,
              storedRequest.attemptId,
            );
            pending = getChatRequest(scopeKey);
          }
        }
        if (!pending) {
          const pendingSession = nextHistory.find((session) =>
            session.turns.some((turn) => turn.state === "pending"),
          );
          const pendingTurn = pendingSession?.turns.find(
            (turn) => turn.state === "pending",
          );
          if (pendingSession && pendingTurn) {
            pending = adoptPendingChatRequest(
              {
                sessionId: pendingSession.id,
                versionId: pendingSession.agent.version_id,
                message: pendingTurn.user_text,
                requestId: pendingTurn.id,
                revision: pendingSession.revision,
              },
              scopeKey,
            );
          }
        }
        if (!pending && !reconciledCurrentTerminal) {
          const unknownSession = nextHistory
            .filter(
              (session) => session.turns.at(-1)?.state === "acceptance_unknown",
            )
            .sort((left, right) =>
              right.created_at.localeCompare(left.created_at),
            )[0];
          const unknownTurn = unknownSession?.turns.at(-1);
          if (unknownSession && unknownTurn) {
            pending = adoptUncertainChatRequest(
              {
                sessionId: unknownSession.id,
                versionId: unknownSession.agent.version_id,
                message: unknownTurn.user_text,
                requestId: unknownTurn.id,
                revision: Math.max(0, unknownSession.revision - 1),
              },
              scopeKey,
            );
            setError(unknownChatOutcomeError());
          }
        }
        if (pending) {
          const match =
            nextHistory.find((session) => session.id === pending.sessionId) ??
            null;
          setSelected(match);
          setVersionId(pending.versionId);
          setRequestState(pending);
          setPendingMessage(
            pending.promise && pending.status === "in_flight"
              ? pending.message
              : "",
          );
          setBusy(pending.promise != null || pending.status === "observing");
          if (
            pending.status === "uncertain" ||
            (pending.status === "observing" &&
              pending.observedTurnId !== pending.requestId)
          ) {
            setDraft((current) => current || pending.message);
          }
          return;
        }
        const recent = nextHistory.find((session) => session.turns.length > 0);
        setSelected(recent ?? null);
        setVersionId(recent?.agent.version_id ?? catalog[0]?.version_id ?? "");
      })
      .catch((cause) => {
        if (active && isChatRequestScopeActive(scopeKey)) setError(cause);
      })
      .finally(() => {
        if (active && isChatRequestScopeActive(scopeKey)) {
          setLoadedScope(scopeKey);
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [api, courseId, scopeKey]);

  useEffect(() => {
    if (!scopeKey || loadedScope !== scopeKey) return;
    return subscribeChatRequest(() => {
      if (!isChatRequestScopeActive(scopeKey)) return;
      const pending = getChatRequest(scopeKey);
      const settled = getSettledChatSession(scopeKey);
      setRequestState(pending);
      if (settled) {
        remember(settled, true);
        clearSettledChatSession(scopeKey);
        setRequestState(null);
        setPendingMessage("");
        setBusy(false);
        return;
      }
      if (pending) {
        const observing = pending.status === "observing";
        const inFlight = pending.promise != null;
        setBusy(inFlight || observing);
        setPendingMessage(
          inFlight && pending.status === "in_flight" ? pending.message : "",
        );
        if (
          pending.status === "uncertain" ||
          (observing && pending.observedTurnId !== pending.requestId)
        ) {
          setDraft((current) => current || pending.message);
        }
        setVersionId(pending.versionId);
        if (pending.sessionId) {
          setSelected((current) =>
            current?.id === pending.sessionId
              ? current
              : (sessions.find((item) => item.id === pending.sessionId) ??
                current),
          );
        }
        return;
      }
      setRequestState(null);
      setBusy(false);
      setPendingMessage("");
    }, scopeKey);
  }, [remember, sessions, scopeKey, loadedScope]);

  useEffect(() => {
    const observed = requestState;
    if (
      !scopeKey ||
      loadedScope !== scopeKey ||
      observed?.scopeKey !== scopeKey ||
      observed.status !== "observing" ||
      !observed.sessionId
    ) {
      return;
    }
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let checking = false;

    const poll = async () => {
      if (!active || checking) return;
      checking = true;
      try {
        const session = await api.conversation(observed.sessionId!);
        if (
          !active ||
          !isChatRequestScopeActive(scopeKey) ||
          getChatRequest(scopeKey)?.attemptId !== observed.attemptId
        ) {
          return;
        }
        remember(session);
        const requestTurn = session.turns.find(
          (turn) => turn.id === observed.requestId,
        );
        if (requestTurn && requestTurn.state !== "pending") {
          if (requestTurn.state === "acceptance_unknown") {
            setError(unknownChatOutcomeError());
          } else if (requestTurn.state !== "ready") {
            const code = requestTurn.safe_error_code ?? "chat_failed";
            setError(new PlatformApiError(503, code, { code, message: code }));
          }
          if (requestTurn.state === "acceptance_unknown") {
            markChatRequestUncertain(
              observed.requestId,
              scopeKey,
              observed.attemptId,
            );
          } else {
            settleChatRequest(
              observed.requestId,
              session,
              scopeKey,
              observed.attemptId,
            );
          }
          return;
        }
        if (!session.turns.some((turn) => turn.state === "pending")) {
          retryChatRequestAtRevision(
            observed.requestId,
            session.revision,
            scopeKey,
            observed.attemptId,
          );
          return;
        }
      } catch (cause) {
        if (
          active &&
          isChatRequestScopeActive(scopeKey) &&
          getChatRequest(scopeKey)?.attemptId === observed.attemptId
        ) {
          setError(cause);
        }
      } finally {
        checking = false;
      }
      if (active) timer = setTimeout(() => void poll(), 1500);
    };

    void poll();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [api, remember, requestState, scopeKey, loadedScope]);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [selected?.id, selected?.turns.length, busy, pendingMessage]);

  function start(nextVersionId = versionId) {
    if (busy) return;
    createChatRequestAttempt(scopeKey);
    uiRevision.current += 1;
    sendSequence.current += 1;
    setError(null);
    setHistoryRefreshTarget(null);
    setSelected(null);
    setDraft("");
    abandonChatRequest(undefined, scopeKey);
    if (nextVersionId) setVersionId(nextVersionId);
  }

  async function openHistory(session: ChatSession) {
    if (!scopeKey || loadedScope !== scopeKey || busy) return;
    const openAttempt = createChatRequestAttempt(scopeKey);
    if (openAttempt === null) return;
    const openSequence = ++historyOpenSequence.current;
    const openUiRevision = ++uiRevision.current;
    const openSendSequence = ++sendSequence.current;
    const requestAtOpen = getChatRequest(scopeKey);
    const attemptAtOpen = requestAtOpen?.attemptId ?? null;
    const stillCurrent = () =>
      historyOpenSequence.current === openSequence &&
      uiRevision.current === openUiRevision &&
      sendSequence.current === openSendSequence &&
      isChatRequestScopeActive(scopeKey) &&
      isChatRequestAttemptCurrent(openAttempt, scopeKey) &&
      (getChatRequest(scopeKey)?.attemptId ?? null) === attemptAtOpen;

    setHistoryRefreshTarget(session);
    setBusy(true);
    try {
      const refreshed = await api.conversation(session.id);
      if (!stillCurrent()) return;
      remember(refreshed);
      setSelected(refreshed);
      setVersionId(refreshed.agent.version_id);
      setDraft("");
      setError(null);
      setHistoryRefreshTarget(null);

      const currentRequest = getChatRequest(scopeKey);
      if (currentRequest?.sessionId === refreshed.id) {
        const requestTurn = refreshed.turns.find(
          (turn) => turn.id === currentRequest.requestId,
        );
        if (requestTurn?.state === "ready") {
          settleChatRequest(
            currentRequest.requestId,
            refreshed,
            scopeKey,
            currentRequest.attemptId,
          );
        } else if (requestTurn?.state === "acceptance_unknown") {
          setDraft(currentRequest.message);
          setError(unknownChatOutcomeError());
          markChatRequestUncertain(
            currentRequest.requestId,
            scopeKey,
            currentRequest.attemptId,
          );
        } else if (requestTurn?.state === "failed") {
          const code = requestTurn.safe_error_code ?? "chat_failed";
          setError(new PlatformApiError(503, code, { code, message: code }));
          settleChatRequest(
            currentRequest.requestId,
            refreshed,
            scopeKey,
            currentRequest.attemptId,
          );
        } else if (requestTurn?.state === "pending") {
          observeChatRequestOnTurn(
            currentRequest.requestId,
            currentRequest.requestId,
            scopeKey,
            currentRequest.attemptId,
          );
        } else {
          const otherPending = refreshed.turns.find(
            (turn) => turn.state === "pending",
          );
          if (otherPending) {
            observeChatRequestOnTurn(
              currentRequest.requestId,
              otherPending.id,
              scopeKey,
              currentRequest.attemptId,
            );
          } else {
            retryChatRequestAtRevision(
              currentRequest.requestId,
              refreshed.revision,
              scopeKey,
              currentRequest.attemptId,
            );
          }
        }
        return;
      }

      if (currentRequest) {
        abandonChatRequest(
          currentRequest.requestId,
          scopeKey,
          currentRequest.attemptId,
        );
      }
      const pendingTurn = refreshed.turns.find(
        (turn) => turn.state === "pending",
      );
      if (pendingTurn) {
        const observed = adoptPendingChatRequest(
          {
            sessionId: refreshed.id,
            versionId: refreshed.agent.version_id,
            message: pendingTurn.user_text,
            requestId: pendingTurn.id,
            revision: refreshed.revision,
          },
          scopeKey,
        );
        if (observed) {
          setRequestState(observed);
          setBusy(true);
          return;
        }
      }
      const lastTurn = refreshed.turns.at(-1);
      if (lastTurn?.state === "acceptance_unknown") {
        const unknown = adoptUncertainChatRequest(
          {
            sessionId: refreshed.id,
            versionId: refreshed.agent.version_id,
            message: lastTurn.user_text,
            requestId: lastTurn.id,
            revision: Math.max(0, refreshed.revision - 1),
          },
          scopeKey,
        );
        if (unknown) {
          setRequestState(unknown);
          setDraft(unknown.message);
          setError(unknownChatOutcomeError());
          setBusy(false);
          setPendingMessage("");
          return;
        }
      }
      setRequestState(null);
      setBusy(false);
    } catch {
      if (!stillCurrent()) return;
      setError(
        new PlatformApiError(503, "chat_history_refresh_failed", {
          code: "chat_history_refresh_failed",
          message: "chat_history_refresh_failed",
        }),
      );
    } finally {
      if (stillCurrent()) {
        const pending = getChatRequest(scopeKey);
        setBusy(pending?.promise != null || pending?.status === "observing");
      }
    }
  }

  async function removeChat(session: ChatSession) {
    if (busy) return;
    if (!window.confirm(t("deleteChatConfirm"))) return;
    const removeUiRevision = ++uiRevision.current;
    const removeSendSequence = ++sendSequence.current;
    const removeScope = scopeKey;
    setError(null);
    try {
      await api.deleteConversation(session.id);
      if (
        !removeScope ||
        !isChatRequestScopeActive(removeScope) ||
        uiRevision.current !== removeUiRevision ||
        sendSequence.current !== removeSendSequence
      ) {
        return;
      }
      setSessions((current) =>
        current.filter((item) => item.id !== session.id),
      );
      if (selected?.id === session.id) {
        setSelected(null);
        setDraft("");
        abandonChatRequest(undefined, removeScope);
      }
    } catch (cause) {
      if (
        removeScope &&
        isChatRequestScopeActive(removeScope) &&
        uiRevision.current === removeUiRevision &&
        sendSequence.current === removeSendSequence
      ) {
        setError(cause);
      }
    }
  }

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const message = draft.trim();
    if (
      !message ||
      busy ||
      !scopeKey ||
      loadedScope !== scopeKey ||
      historyRefreshTarget ||
      getChatRequest(scopeKey)?.promise
    ) {
      return;
    }
    const sendAttempt = ++sendSequence.current;
    const attemptId = createChatRequestAttempt(scopeKey);
    if (attemptId === null) return;
    const interactionAtSend = uiRevision.current;
    let confirmedUnknownOutcome = false;
    const ownsSend = () =>
      sendSequence.current === sendAttempt &&
      uiRevision.current === interactionAtSend &&
      isChatRequestScopeActive(scopeKey) &&
      isChatRequestAttemptCurrent(attemptId, scopeKey);
    setBusy(true);
    setPendingMessage(message);
    setDraft("");
    setError(null);
    try {
      const session = selected ?? (await api.createConversation(versionId));
      if (!ownsSend()) return;
      if (!selected) remember(session, true);
      const pending = getChatRequest(scopeKey);
      const reuse =
        pending &&
        pending.status === "uncertain" &&
        pending.message === message &&
        (pending.sessionId === session.id || pending.sessionId === null)
          ? pending
          : null;
      const requestId = reuse?.requestId ?? crypto.randomUUID();
      const revision = reuse?.revision ?? session.revision;
      const promise = api
        .streamConversation(
          session.id,
          {
            request_id: requestId,
            message,
            expected_revision: revision,
          },
          {
            onTextDone: (refreshed) => {
              if (!ownsSend()) return;
              settleChatRequest(requestId, refreshed, scopeKey, attemptId);
              setPendingMessage("");
              setBusy(false);
            },
            onPending: (refreshed, pendingTurnId) => {
              if (!ownsSend()) return;
              remember(refreshed);
              observeChatRequestOnTurn(
                requestId,
                pendingTurnId,
                scopeKey,
                attemptId,
              );
            },
            onTerminalError: (refreshed, terminalError) => {
              if (!ownsSend()) return;
              if (refreshed) remember(refreshed);
              const requestTurn = refreshed?.turns.find(
                (turn) => turn.id === requestId,
              );
              const pendingTurn =
                (requestTurn?.state === "pending" ? requestTurn : undefined) ??
                refreshed?.turns.find((turn) => turn.state === "pending");
              if (pendingTurn) {
                observeChatRequestOnTurn(
                  requestId,
                  String(pendingTurn.id),
                  scopeKey,
                  attemptId,
                );
                return;
              }
              if (requestTurn?.state === "acceptance_unknown") {
                confirmedUnknownOutcome = true;
                setError(unknownChatOutcomeError());
                markChatRequestUncertain(requestId, scopeKey, attemptId);
              } else {
                settleChatRequest(requestId, refreshed, scopeKey, attemptId);
              }
            },
            onUncertain: (refreshed) => {
              if (!ownsSend()) return;
              if (refreshed) remember(refreshed);
              markChatRequestUncertain(requestId, scopeKey, attemptId);
            },
          },
        )
        .then((result) => result.session);
      beginChatRequest({
        sessionId: session.id,
        versionId,
        message,
        requestId,
        revision,
        scopeKey,
        attemptId,
        promise,
      });
      const result = await promise;
      if (ownsSend()) {
        remember(result);
        settleChatRequest(requestId, result, scopeKey, attemptId);
      }
    } catch (cause) {
      if (!(cause instanceof ChatRequestPendingError) && ownsSend()) {
        setError(confirmedUnknownOutcome ? unknownChatOutcomeError() : cause);
        setDraft(message);
      }
    } finally {
      if (ownsSend()) {
        const pending = getChatRequest(scopeKey);
        const inFlight = pending?.promise != null;
        const observing = pending?.status === "observing";
        setPendingMessage(
          inFlight && pending?.status === "in_flight" ? pending.message : "",
        );
        setBusy(inFlight || observing);
      }
    }
  }

  async function checkUncertainRequestStatus() {
    const request = scopeKey ? getChatRequest(scopeKey) : null;
    if (
      !scopeKey ||
      loadedScope !== scopeKey ||
      request?.status !== "uncertain" ||
      !request.sessionId ||
      busy
    ) {
      return;
    }
    const checkUiRevision = uiRevision.current;
    const checkSendSequence = sendSequence.current;
    const stillCurrent = () =>
      isChatRequestScopeActive(scopeKey) &&
      uiRevision.current === checkUiRevision &&
      sendSequence.current === checkSendSequence &&
      getChatRequest(scopeKey)?.attemptId === request.attemptId;
    setError(null);
    try {
      const session = await api.conversation(request.sessionId);
      if (!stillCurrent()) return;
      remember(session);
      const turn = session.turns.find((item) => item.id === request.requestId);
      if (turn?.state === "ready") {
        if (draft.trim() === request.message) setDraft("");
        settleChatRequest(
          request.requestId,
          session,
          scopeKey,
          request.attemptId,
        );
      } else if (turn?.state === "pending") {
        observeChatRequestOnTurn(
          request.requestId,
          request.requestId,
          scopeKey,
          request.attemptId,
        );
      } else if (
        turn?.state === "failed" ||
        turn?.state === "acceptance_unknown"
      ) {
        if (turn.state === "acceptance_unknown") {
          setError(unknownChatOutcomeError());
          markChatRequestUncertain(
            request.requestId,
            scopeKey,
            request.attemptId,
          );
        } else {
          const code = turn.safe_error_code ?? "chat_failed";
          setError(new PlatformApiError(503, code, { code, message: code }));
          settleChatRequest(
            request.requestId,
            session,
            scopeKey,
            request.attemptId,
          );
        }
      } else if (session.turns.some((item) => item.state === "pending")) {
        const pendingTurn = session.turns.find(
          (item) => item.state === "pending",
        );
        if (pendingTurn) {
          observeChatRequestOnTurn(
            request.requestId,
            String(pendingTurn.id),
            scopeKey,
            request.attemptId,
          );
        }
      } else {
        retryChatRequestAtRevision(
          request.requestId,
          session.revision,
          scopeKey,
          request.attemptId,
        );
      }
    } catch (cause) {
      if (stillCurrent()) setError(cause);
    }
  }

  const character =
    selected?.agent ?? agents.find((agent) => agent.version_id === versionId);
  if (!scopeKey || loadedScope !== scopeKey || loading) {
    return (
      <>
        <WorkspaceAction name="new" disabled />
        <LoadingCard />
      </>
    );
  }

  return (
    <>
      <PageIntro title="Chats" />
      <WorkspaceAction
        name="new"
        disabled={busy || showNewEntry}
        onClick={() => setShowNewEntry(true)}
      />
      {showNewEntry ? (
        <TeamEntryFlow
          api={api}
          courseId={courseId}
          agents={agents}
          onClose={() => setShowNewEntry(false)}
          onStartAgent={(nextVersionId) => {
            setShowNewEntry(false);
            start(nextVersionId);
          }}
        />
      ) : null}
      {!showNewEntry && error ? (
        <ErrorNotice
          error={error}
          onRetry={
            historyRefreshTarget
              ? () => void openHistory(historyRefreshTarget)
              : undefined
          }
        />
      ) : null}
      {!showNewEntry &&
      requestState?.status === "uncertain" &&
      requestState.sessionId ? (
        <button
          className="inline-button"
          type="button"
          onClick={() => void checkUncertainRequestStatus()}
        >
          {t("chatCheckStatus")}
        </button>
      ) : null}
      {!showNewEntry && !agents.length && !selected ? (
        <EmptyCard title={t("noPublishedAgents")} />
      ) : null}
      {!showNewEntry && (agents.length > 0 || selected) ? (
        <div className={styles.layout}>
          <aside className={styles.sidebar}>
            <select
              id="chat-agent"
              aria-label="Agent"
              value={versionId}
              disabled={busy}
              onChange={(event) => {
                start(event.target.value);
              }}
            >
              {selected &&
              !agents.some(
                (agent) => agent.version_id === selected.agent.version_id,
              ) ? (
                <option value={selected.agent.version_id}>
                  {selected.agent.name} · {selected.agent.version_label}
                </option>
              ) : null}
              {agents.map((agent) => (
                <option key={agent.version_id} value={agent.version_id}>
                  {agent.name} · {agent.version_label}
                </option>
              ))}
            </select>
            <div className={styles.history} aria-label="History">
              {sessions
                .filter((session) => session.turns.length > 0)
                .map((session) => (
                  <div className={styles.historyRow} key={session.id}>
                    <button
                      type="button"
                      className={styles.historySelect}
                      disabled={busy}
                      aria-current={
                        selected?.id === session.id ? "page" : undefined
                      }
                      title={session.agent.name}
                      onClick={() => {
                        void openHistory(session);
                      }}
                    >
                      <span>{session.turns[0]?.user_text ?? "New"}</span>
                    </button>
                    <span className={styles.historyMeta}>
                      <small className={styles.historyDate}>
                        {new Date(session.created_at).toLocaleDateString()}
                      </small>
                      <button
                        type="button"
                        className={styles.historyDelete}
                        disabled={busy}
                        aria-label={t("deleteChat")}
                        data-ui-guide="chat.delete"
                        onClick={(event) => {
                          event.stopPropagation();
                          void removeChat(session);
                        }}
                      >
                        <IconClose />
                      </button>
                    </span>
                  </div>
                ))}
            </div>
          </aside>
          <section className={styles.conversation}>
            <div
              className={styles.messages}
              role="log"
              aria-live="polite"
              aria-relevant="additions text"
            >
              {selected?.turns.map((turn) => (
                <div key={turn.id} className={styles.exchange}>
                  <div className={styles.userMessage}>{turn.user_text}</div>
                  <div className={styles.reply}>
                    {turn.assistant_text ? (
                      <ReportMarkdown>{turn.assistant_text}</ReportMarkdown>
                    ) : (
                      <span className={styles.pending} role="status">
                        {turn.state === "pending" ? (
                          <>
                            <span className="spinner" aria-hidden="true" />
                            {t("loading")}
                          </>
                        ) : turn.state === "acceptance_unknown" ? (
                          t("errorChatAcceptanceUnknown")
                        ) : (
                          turn.safe_error_code
                        )}
                      </span>
                    )}
                    {turn.sources.length ? (
                      <details>
                        <summary>Check RAG · {turn.sources.length}</summary>
                        {turn.sources.map((source) => (
                          <div className={styles.source} key={source.chunk_id}>
                            <strong>{source.filename}</strong>
                            <p>{source.excerpt}</p>
                          </div>
                        ))}
                      </details>
                    ) : null}
                  </div>
                </div>
              ))}
              {pendingMessage ? (
                <div className={styles.exchange}>
                  <div className={styles.userMessage}>{pendingMessage}</div>
                  <div className={styles.pending} role="status">
                    <span className="spinner" aria-hidden="true" />
                    {t("loading")}
                  </div>
                </div>
              ) : null}
              <div ref={endRef} />
            </div>
            <form
              className={styles.composer}
              onSubmit={(event) => void send(event)}
            >
              <textarea
                id="chat-message"
                aria-label="Message"
                value={draft}
                rows={1}
                disabled={busy || character?.available === false}
                onChange={(event) => {
                  uiRevision.current += 1;
                  setDraft(event.target.value);
                }}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    void send();
                  }
                }}
              />
              <div className={styles.composerBar}>
                <span className={styles.composerHint} aria-hidden="true" />
                <button
                  type="submit"
                  className={styles.sendButton}
                  aria-label={
                    character?.available === false ? "Read-only" : "Send"
                  }
                  data-ui-guide={
                    character?.available === false
                      ? "chat.readOnly"
                      : "chat.send"
                  }
                  title={
                    character?.available === false ? "Read-only" : undefined
                  }
                  disabled={
                    busy ||
                    historyRefreshTarget !== null ||
                    character?.available === false ||
                    !draft.trim() ||
                    !versionId ||
                    selected?.turns.some((turn) => turn.state === "pending")
                  }
                >
                  <svg
                    viewBox="0 0 24 24"
                    width="18"
                    height="18"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M12 19V5m-7 7 7-7 7 7" />
                  </svg>
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}
    </>
  );
}
