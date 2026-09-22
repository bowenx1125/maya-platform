"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import type { ChatAgent, ChatSession } from "../lib/api";
import { AvatarPreview } from "./avatar";
import { useT } from "./locale";
import { ReportMarkdown } from "./report/report-markdown";
import { useSession } from "./session-provider";
import { EmptyCard, ErrorNotice, LoadingCard, PageIntro } from "./ui";
import { WorkspaceAction } from "./workspace-actions";
import styles from "./agent-chat.module.css";

export function AgentChat() {
  const { api, user } = useSession();
  const t = useT();
  const courseId = user?.courses[0]?.course_id;
  const [agents, setAgents] = useState<ChatAgent[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [selected, setSelected] = useState<ChatSession | null>(null);
  const [versionId, setVersionId] = useState("");
  const [draft, setDraft] = useState("");
  const [pendingMessage, setPendingMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const request = useRef<{
    id: string;
    message: string;
    sessionId: string;
    revision: number;
  } | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!courseId) return;
    let active = true;
    void Promise.all([api.chatAgents(courseId), api.conversations()])
      .then(([catalog, history]) => {
        if (!active) return;
        setAgents(catalog);
        setSessions(history);
        const recent = history.find((session) => session.turns.length > 0);
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
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [selected?.id, selected?.turns.length, busy]);

  function remember(value: ChatSession) {
    setSelected(value);
    setSessions((current) => [
      value,
      ...current.filter((item) => item.id !== value.id),
    ]);
  }

  function start() {
    if (!versionId || busy) return;
    setError(null);
    setSelected(null);
    setDraft("");
    request.current = null;
  }

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const message = draft.trim();
    if (!message || busy) return;
    setBusy(true);
    setPendingMessage(message);
    setDraft("");
    setError(null);
    try {
      const session = selected ?? (await api.createConversation(versionId));
      if (!selected) remember(session);
      if (
        !request.current ||
        request.current.message !== message ||
        request.current.sessionId !== session.id
      ) {
        request.current = {
          id: crypto.randomUUID(),
          message,
          sessionId: session.id,
          revision: session.revision,
        };
      }
      const pending = request.current;
      const result = await api.sendConversation(session.id, {
        request_id: pending.id,
        message,
        expected_revision: pending.revision,
      });
      remember(result);
      if (
        !result.turns.some(
          (turn) => turn.id === pending.id && turn.state === "pending",
        )
      ) {
        request.current = null;
        setDraft("");
      }
    } catch (cause) {
      setError(cause);
      setDraft(message);
    } finally {
      setPendingMessage("");
      setBusy(false);
    }
  }

  if (loading) return <LoadingCard />;
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
        onClick={start}
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
                setVersionId(event.target.value);
                setSelected(
                  sessions.find(
                    (session) =>
                      session.agent.version_id === event.target.value &&
                      session.turns.length > 0,
                  ) ?? null,
                );
                setDraft("");
                request.current = null;
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
                  <button
                    key={session.id}
                    type="button"
                    disabled={busy}
                    aria-current={
                      selected?.id === session.id ? "page" : undefined
                    }
                    title={session.agent.name}
                    onClick={() => {
                      setSelected(session);
                      setVersionId(session.agent.version_id);
                      setDraft("");
                      request.current = null;
                    }}
                  >
                    <span>{session.turns[0]?.user_text ?? "New"}</span>
                    <small>
                      {new Date(session.created_at).toLocaleDateString()}
                    </small>
                  </button>
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
                      <span role="status">
                        {turn.state === "pending"
                          ? t("loading")
                          : turn.safe_error_code}
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
                maxLength={4000}
                rows={3}
                disabled={busy || character?.available === false}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    (event.metaKey || event.ctrlKey) &&
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
