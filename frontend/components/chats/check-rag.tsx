"use client";

import { useState } from "react";

import type { ModelInputCall } from "../../lib/api/platform";
import { useSession } from "../session-provider";
import styles from "../agent-chat.module.css";

export type CheckRagSource = {
  chunk_id: string;
  filename: string;
  excerpt: string;
};

/** The model call behind one reply: a Chat turn, or one Team member's reply. */
export type CheckRagDetails = {
  conversationId: string;
  turnId: string;
  resultId?: string;
};

/**
 * Chat Check RAG, in two clicks: closed it reads "Check RAG" and the count;
 * open it lists the documents; each document opens to its text. Details, at
 * the bottom, shows everything else this reply sent to the model (owner
 * decision 2026-11-05: nothing the model reads is hidden from the person
 * chatting).
 */
export function CheckRag({
  sources,
  details,
}: {
  sources: readonly CheckRagSource[];
  details?: CheckRagDetails | null;
}) {
  if (sources.length === 0 && !details) return null;
  return (
    <details className={styles.rag}>
      <summary className={styles.ragSummary}>
        <span>Check RAG</span>
        <span className={styles.ragCount}>{sources.length}</span>
      </summary>
      {sources.map((source) => (
        <details key={source.chunk_id} className={styles.ragSource}>
          <summary>{source.filename}</summary>
          <p>{source.excerpt}</p>
        </details>
      ))}
      {details ? <ModelInputDetails {...details} /> : null}
    </details>
  );
}

function ModelInputDetails({
  conversationId,
  turnId,
  resultId,
}: CheckRagDetails) {
  const { api } = useSession();
  const [calls, setCalls] = useState<ModelInputCall[] | null>(null);
  const [failed, setFailed] = useState(false);

  // Loaded on first open only: most replies are never inspected.
  function load(open: boolean) {
    if (!open || calls !== null) return;
    setFailed(false);
    api
      .chatTurnModelInput(conversationId, turnId, resultId)
      .then((value) => setCalls(value.calls))
      .catch(() => setFailed(true));
  }

  return (
    <details
      className={styles.ragSource}
      onToggle={(event) => load(event.currentTarget.open)}
    >
      <summary>Details</summary>
      {failed ? (
        <p>Details could not be loaded.</p>
      ) : calls === null ? (
        <p>Loading…</p>
      ) : calls.length === 0 ? (
        <p>Nothing was sent to the model for this reply.</p>
      ) : (
        calls.map((call, index) => (
          <div key={index} className={styles.ragDetailsCall}>
            {calls.length > 1 ? (
              <p className={styles.ragDetailsHeading}>
                Model call {index + 1} of {calls.length}
              </p>
            ) : null}
            <Part title="System prompt" text={call.system_prompt} />
            <Part title="AGENT.md" text={call.agent_md} />
            <Part title="Knowledge" text={call.knowledge} />
            <Part title="Attachments" text={call.attachments} />
            {call.tools.length ? (
              <details className={styles.ragSource}>
                <summary>Tools ({call.tools.length})</summary>
                {call.tools.map((tool) => (
                  <Part
                    key={tool.name}
                    title={tool.name}
                    text={`${tool.description}\n\n${tool.parameters}`}
                  />
                ))}
              </details>
            ) : null}
            {call.tool_messages.length ? (
              <details className={styles.ragSource}>
                <summary>Tool calls and results</summary>
                {call.tool_messages.map((item, position) => (
                  <Part
                    key={position}
                    title={`${item.role === "tool_call" ? "Call" : "Result"}${
                      item.name ? ` · ${item.name}` : ""
                    }`}
                    text={item.content}
                  />
                ))}
              </details>
            ) : null}
          </div>
        ))
      )}
    </details>
  );
}

function Part({ title, text }: { title: string; text: string | null }) {
  if (!text) return null;
  return (
    <details className={styles.ragSource}>
      <summary>{title}</summary>
      <pre className={styles.ragDetailsText}>{text}</pre>
    </details>
  );
}
