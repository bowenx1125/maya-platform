"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { PlatformApiError, type ChatAgent, type ChatSession } from "../lib/api";
import {
  abandonChatRequest,
  beginChatRequest,
  clearSettledChatSession,
  getChatRequest,
  getSettledChatSession,
  subscribeChatRequest,
} from "../lib/chat-request-store";
import { ttsPlaybackPhase } from "../lib/chat-tts-playback";
import { chatStreamLanguage } from "../lib/i18n";
import { AvatarPreview } from "./avatar";
import { useLocale, useT } from "./locale";
import { IconClose } from "./quiet-icons";
import { ReportMarkdown } from "./report/report-markdown";
import { useSession } from "./session-provider";
import { EmptyCard, ErrorNotice, LoadingCard, PageIntro } from "./ui";
import { WorkspaceAction } from "./workspace-actions";
import styles from "./agent-chat.module.css";

export function AgentChat() {
  const { api, user } = useSession();
  const t = useT();
  const { locale } = useLocale();
  const courseId = user?.courses[0]?.course_id;
  const [agents, setAgents] = useState<ChatAgent[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [selected, setSelected] = useState<ChatSession | null>(null);
  const [versionId, setVersionId] = useState("");
  const [draft, setDraft] = useState("");
  const [pendingMessage, setPendingMessage] = useState(
    () => getChatRequest()?.message ?? "",
  );
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(() => getChatRequest() !== null);
  const [error, setError] = useState<unknown>(null);
  const [ttsPhase, setTtsPhase] = useState<
    "idle" | "playing" | "complete" | "incomplete"
  >("idle");
  const endRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  function syncTtsPlayback() {
    const audio = audioRef.current;
    if (!audio) return;
    if (
      ttsPlaybackPhase({
        ended: audio.ended,
        currentTime: audio.currentTime,
        duration: audio.duration,
      }) === "complete"
    ) {
      setTtsPhase("complete");
    }
  }

  function startTtsPlayback(url: string) {
    const audio = audioRef.current;
    if (!audio) return;
    setTtsPhase("playing");
    audio.src = url;
    void audio.play().catch(() => setTtsPhase("incomplete"));
  }

  function remember(value: ChatSession) {
    setSelected(value);
    setSessions((current) => [
      value,
      ...current.filter((item) => item.id !== value.id),
    ]);
  }

  useEffect(() => {
    if (!courseId) return;
    let active = true;
    void Promise.all([api.chatAgents(courseId), api.conversations()])
      .then(([catalog, history]) => {
        if (!active) return;
        setAgents(catalog);
        const pending = getChatRequest();
        const settled = getSettledChatSession();
        let nextHistory = history;
        if (settled) {
          nextHistory = [
            settled,
            ...history.filter((item) => item.id !== settled.id),
          ];
          clearSettledChatSession();
        }
        setSessions(nextHistory);
        if (pending) {
          const match =
            nextHistory.find((session) => session.id === pending.sessionId) ??
            null;
          setSelected(match);
          setVersionId(pending.versionId);
          setPendingMessage(pending.message);
          setBusy(true);
          return;
        }
        const recent = nextHistory.find((session) => session.turns.length > 0);
        setSelected(recent ?? null);
        setVersionId(recent?.agent.version_id ?? catalog[0]?.version_id ?? "");
      })
      .catch((cause) => {
        if (active) setError(cause);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, courseId]);

  useEffect(() => {
    return subscribeChatRequest(() => {
      const pending = getChatRequest();
      const settled = getSettledChatSession();
      if (settled) {
        remember(settled);
        clearSettledChatSession();
        setPendingMessage("");
        setBusy(false);
        setVersionId(settled.agent.version_id);
        return;
      }
      if (pending) {
        setBusy(true);
        setPendingMessage(pending.message);
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
      setBusy(false);
      setPendingMessage("");
    });
  }, [sessions]);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [selected?.id, selected?.turns.length, busy, pendingMessage]);

  function start(nextVersionId = versionId) {
    if (busy) return;
    setError(null);
    setSelected(null);
    setDraft("");
    abandonChatRequest();
    if (nextVersionId) setVersionId(nextVersionId);
  }

  async function removeChat(session: ChatSession) {
    if (busy) return;
    if (!window.confirm(t("deleteChatConfirm"))) return;
    setError(null);
    try {
      await api.deleteConversation(session.id);
      setSessions((current) =>
        current.filter((item) => item.id !== session.id),
      );
      if (selected?.id === session.id) {
        setSelected(null);
        setDraft("");
        abandonChatRequest();
      }
    } catch (cause) {
      setError(cause);
    }
  }

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const message = draft.trim();
    if (!message || busy) return;
    setBusy(true);
    setTtsPhase("idle");
    setPendingMessage(message);
    setDraft("");
    setError(null);
    try {
      const session = selected ?? (await api.createConversation(versionId));
      if (!selected) remember(session);
      const pending = getChatRequest();
      const reuse =
        pending &&
        pending.message === message &&
        (pending.sessionId === session.id || pending.sessionId === null)
          ? pending
          : null;
      const requestId = reuse?.requestId ?? crypto.randomUUID();
      const revision = reuse?.revision ?? session.revision;
      const promise =
        reuse?.promise ??
        api
          .streamConversation(
            session.id,
            {
              request_id: requestId,
              message,
              expected_revision: revision,
              lang: chatStreamLanguage(locale, message),
            },
            {
              onTextDone: (refreshed) => {
                remember(refreshed);
                abandonChatRequest(requestId);
                setPendingMessage("");
                setBusy(false);
              },
            },
          )
          .then((result) => {
            if (result.ttsErrorCode) {
              setError(
                new PlatformApiError(502, result.ttsErrorCode, {
                  code: result.ttsErrorCode,
                  message: result.ttsErrorCode,
                }),
              );
            }
            if (result.audioUrl) startTtsPlayback(result.audioUrl);
            else setTtsPhase("idle");
            return result.session;
          });
      beginChatRequest({
        sessionId: session.id,
        versionId,
        message,
        requestId,
        revision,
        promise,
      });
      const result = await promise;
      remember(result);
      if (
        !result.turns.some(
          (turn) => turn.id === requestId && turn.state === "pending",
        )
      ) {
        abandonChatRequest(requestId);
        setDraft("");
      }
    } catch (cause) {
      setError(cause);
      setDraft(message);
    } finally {
      const pending = getChatRequest();
      setPendingMessage(pending?.promise ? pending.message : "");
      setBusy(pending?.promise != null);
    }
  }

  if (loading) {
    return (
      <>
        <WorkspaceAction name="new" disabled />
        <LoadingCard />
      </>
    );
  }
  const character =
    selected?.agent ?? agents.find((agent) => agent.version_id === versionId);
  return (
    <>
      <PageIntro title="Chats" />
      <WorkspaceAction
        name="new"
        disabled={
          busy ||
          character?.available === false ||
          !agents.some((agent) => agent.version_id === versionId)
        }
        onClick={() => start()}
      />
      {error ? <ErrorNotice error={error} /> : null}
      {!agents.length && !selected ? (
        <EmptyCard title={t("noPublishedAgents")} />
      ) : (
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
            {character ? (
              <AvatarPreview
                className={styles.avatar}
                config={character.avatar_config}
                framing="full-body"
                fallbackLabel={character.name}
                state={busy ? "thinking" : "idle"}
              />
            ) : null}
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
                        setSelected(session);
                        setVersionId(session.agent.version_id);
                        setDraft("");
                        abandonChatRequest();
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
          <section className={styles.conversation} data-tts-playback={ttsPhase}>
            <audio
              ref={audioRef}
              hidden
              onTimeUpdate={syncTtsPlayback}
              onEnded={syncTtsPlayback}
              onError={() => setTtsPhase("incomplete")}
            />
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
                onChange={(event) => setDraft(event.target.value)}
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
              <button
                type="submit"
                className={`${styles.sendButton} primary-action`}
                aria-label={
                  character?.available === false ? "Read-only" : "Send"
                }
                title={character?.available === false ? "Read-only" : "Send"}
                disabled={
                  busy ||
                  character?.available === false ||
                  !draft.trim() ||
                  !versionId ||
                  selected?.turns.some(
                    (turn) =>
                      turn.state === "pending" ||
                      turn.state === "acceptance_unknown",
                  )
                }
              >
                <svg
                  viewBox="0 0 24 24"
                  width="22"
                  height="22"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M12 19V5m-7 7 7-7 7 7" />
                </svg>
              </button>
            </form>
          </section>
        </div>
      )}
    </>
  );
}
