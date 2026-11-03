"use client";

import styles from "../agent-chat.module.css";

export type CheckRagSource = {
  chunk_id: string;
  filename: string;
  excerpt: string;
};

/**
 * Chat Check RAG, in two clicks: closed it reads "Check RAG" and the count;
 * open it lists the documents; each document opens to its text.
 */
export function CheckRag({ sources }: { sources: readonly CheckRagSource[] }) {
  if (sources.length === 0) return null;
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
    </details>
  );
}
