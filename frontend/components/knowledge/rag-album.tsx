"use client";

import { useEffect, useState, type ReactNode } from "react";

import type { AffectedAgent, KnowledgeDocument } from "../../lib/api/platform";
import { useT } from "../../lib/i18n";
import { useSession } from "../session-provider";
import { Button } from "../ui/button";
import styles from "./rag-album.module.css";

const PATHS = {
  doc: "M6 3h9l4 4v14H6zM14 3v5h5",
  download: "M12 4v11m-5-5 5 5 5-5M5 20h14",
  close: "M6 6l12 12M18 6L6 18",
  refresh: "M20 11a8 8 0 1 0-2 5.3M20 5v6h-6",
  plus: "M12 5v14M5 12h14",
  upload: "M12 20V8m-5 5 5-5 5 5M5 4h14",
} as const;

export function AlbumIcon({
  name,
  size = 18,
  stroke = 2.4,
}: {
  name: keyof typeof PATHS;
  size?: number;
  stroke?: number;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

export const albumStyles = styles;

/** The album page class (the RAG page's <main>): dotted paper. */
export const ragAlbumClass = styles.alb;

/** The ring binder down the album's left edge. */
export function AlbumRings() {
  return (
    <div className={styles.rings} aria-hidden="true">
      {Array.from({ length: 7 }, (_, index) => (
        <i key={index} />
      ))}
    </div>
  );
}

/** Pink "+ New": the same accessible name as the old ModulePlus. */
export function AlbumPlus({
  label,
  onClick,
  disabled,
  busy,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  busy?: boolean;
}) {
  return (
    <Button
      variant="noShadow"
      className={styles.pn}
      aria-label={label}
      aria-busy={busy || undefined}
      disabled={disabled || busy}
      onClick={onClick}
    >
      {busy ? (
        <span className="spinner" aria-hidden="true" />
      ) : (
        <AlbumIcon name="plus" size={16} stroke={3} />
      )}
      <span aria-hidden="true">New</span>
    </Button>
  );
}

export function AlbumIconButton({
  icon,
  label,
  guide,
  danger,
  disabled,
  onClick,
}: {
  icon: keyof typeof PATHS;
  label: string;
  guide: string;
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      variant="noShadow"
      size="icon"
      className={`${styles.ib} ${danger ? styles.del : ""}`}
      aria-label={label}
      data-ui-guide={guide}
      disabled={disabled}
      onClick={onClick}
    >
      <AlbumIcon name={icon} />
    </Button>
  );
}

export function fileExt(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot + 1).toUpperCase() : "";
}

/**
 * Agents using each RAG, from the existing
 * GET /knowledge-documents/{id}/affected-agents (one call per card).
 */
export function useRagAgents(documents: KnowledgeDocument[]) {
  const { api } = useSession();
  const [agents, setAgents] = useState<Record<string, AffectedAgent[]>>({});
  const ids = documents.map((document) => document.id).join(",");
  useEffect(() => {
    let live = true;
    const list = ids ? ids.split(",") : [];
    void Promise.all(
      list.map(async (id) => {
        try {
          return [id, await api.knowledgeAffectedAgents(id)] as const;
        } catch {
          return [id, null] as const;
        }
      }),
    ).then((rows) => {
      if (!live) return;
      const next: Record<string, AffectedAgent[]> = {};
      for (const [id, value] of rows) if (value) next[id] = value;
      setAgents(next);
    });
    return () => {
      live = false;
    };
  }, [api, ids]);
  return agents;
}

/**
 * Last editor's username. The backend does not send either field yet
 * (see proposals/18-rag-album-final/API-CHANGES.md); the row stays bound
 * to them and shows an empty signature line until it does.
 */
export function lastEditor(document: KnowledgeDocument): string | null {
  const extra = document as KnowledgeDocument & {
    last_edited_by_username?: string | null;
    owner_username?: string | null;
  };
  return extra.last_edited_by_username || extra.owner_username || null;
}

/** Card B: art, plate (title, status, Used by, Last edited by), footer. */
export function RagCard({
  index,
  document,
  tone,
  agents,
  title,
  status,
  footer,
  badge,
}: {
  index: number;
  document: KnowledgeDocument;
  tone: "" | "failed" | "pending";
  agents: AffectedAgent[] | undefined;
  title: ReactNode;
  status: ReactNode;
  footer: ReactNode;
  badge: ReactNode;
}) {
  const t = useT();
  const editor = lastEditor(document);
  const used = agents ?? [];
  return (
    <li className={`${styles.card} ${tone ? styles[tone] : ""}`}>
      <div className={styles.art}>
        <span className={styles.no} aria-hidden="true">
          #{String(index + 1).padStart(2, "0")}
        </span>
        <span className={styles.ty} aria-hidden="true">
          {fileExt(document.source_filename)}
        </span>
        <span className={styles.cnt} aria-hidden="true">
          {used.length}
        </span>
      </div>
      <div className={styles.plate}>
        {title}
        {status}
        <dl className={styles.stats}>
          <dt>{t("ragUsedBy")}</dt>
          <dd>
            {used.length ? (
              <ol>
                {used.map((agent) => (
                  <li key={agent.agent_id}>{agent.name}</li>
                ))}
              </ol>
            ) : (
              <span className={styles.none}>{t("ragNoAgentsYet")}</span>
            )}
          </dd>
        </dl>
        <p className={styles.sig}>
          <span className={styles.lbl}>{t("ragLastEditedBy")}</span>{" "}
          {editor ? <span className={styles.sg}>@{editor}</span> : null}
        </p>
      </div>
      <div className={styles.ft}>{footer}</div>
      {badge}
    </li>
  );
}
