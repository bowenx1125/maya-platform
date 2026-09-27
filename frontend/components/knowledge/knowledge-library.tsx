"use client";

import { useCallback, useEffect, useState } from "react";

import {
  isAmbiguousMutationFailure,
  isConflict,
  type KnowledgeDocument,
} from "../../lib/api";
import { useIdempotencyStore } from "../../lib/idempotency";
import type { MessageKey } from "../../lib/i18n";
import { useT } from "../locale";
import { IconClose, IconDownload, IconEdit, IconRefresh } from "../quiet-icons";
import { useSession } from "../session-provider";
import { WorkspaceAction } from "../workspace-actions";
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
  StatusBadge,
} from "../ui";
import {
  MarkdownEditor,
  type KnowledgeReplacementRequest,
} from "./markdown-editor";

import styles from "../library-cards.module.css";

type RetryAction =
  | { kind: "create"; file: File }
  | { kind: "replace"; request: KnowledgeReplacementRequest }
  | { kind: "reindex"; documentId: string }
  | { kind: "hide"; documentId: string }
  | null;

/**
 * Group Markdown library with real create and copy-on-write edit wiring.
 *
 * A create callback intentionally sends no target version.  A replacement
 * first downloads the immutable source bytes, then submits the old document
 * hash/index revision through the platform API.  The server decides which
 * current drafts to update; the page never auto-enables a new library file.
 */
export function KnowledgeLibrary({ groupId }: { groupId: string }) {
  const t = useT();
  const { api } = useSession();
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [editing, setEditing] = useState<KnowledgeDocument | null>(null);
  const [editingContent, setEditingContent] = useState("");
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<MessageKey | null>(null);
  const [retryAction, setRetryAction] = useState<RetryAction>(null);
  const [conflict, setConflict] = useState(false);
  const mutationStore = useIdempotencyStore();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDocuments(await api.knowledge(groupId));
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [api, groupId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  function clearMutationState() {
    setError(null);
    setNotice(null);
    setConflict(false);
    setRetryAction(null);
  }

  async function create(file: File) {
    const intent = `knowledge-create:${groupId}`;
    const handle = mutationStore.handleFor(intent);
    setBusyId("create");
    clearMutationState();
    try {
      const mutation = await api.createLibraryKnowledge(groupId, file, {
        idempotency: handle,
      });
      mutationStore.finish(intent, handle);
      setDocuments((current) => [...current, mutation.document]);
      setCreating(false);
      setNotice("knowledgeSaved");
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) {
        setRetryAction({ kind: "create", file });
      } else {
        mutationStore.abandon(intent, handle);
      }
      setError(cause);
    } finally {
      setBusyId(null);
    }
  }

  async function beginEdit(document: KnowledgeDocument) {
    setBusyId(document.id);
    clearMutationState();
    try {
      // Editing always starts from a server download, not a possibly stale
      // browser preview.  The original bytes remain immutable on the server.
      const source = await api.downloadKnowledge(document.id);
      setEditing(document);
      setEditingContent(source.content);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusyId(null);
    }
  }

  async function replace(request: KnowledgeReplacementRequest) {
    const intent = `knowledge-replace:${request.documentId}`;
    const handle = mutationStore.handleFor(intent);
    setBusyId(request.documentId);
    clearMutationState();
    try {
      const next = await api.replaceKnowledgeDocument(
        request.documentId,
        request.file,
        request.expectedContentHash,
        request.expectedIndexRevision,
        { idempotency: handle },
      );
      mutationStore.finish(intent, handle);
      setDocuments((current) => [
        ...current.filter((item) => item.id !== request.documentId),
        next,
      ]);
      setEditing(null);
      setEditingContent("");
      setNotice("knowledgeSaved");
    } catch (cause) {
      if (isConflict(cause)) {
        setConflict(true);
        setRetryAction(null);
        setEditing(null);
        setEditingContent("");
        // The old source may now be hidden and a replacement may be visible;
        // refresh the authoritative library after surfacing the conflict.
        await load();
      } else if (isAmbiguousMutationFailure(cause)) {
        setRetryAction({ kind: "replace", request });
      } else {
        mutationStore.abandon(intent, handle);
      }
      setError(cause);
    } finally {
      setBusyId(null);
    }
  }

  async function download(document: KnowledgeDocument) {
    setBusyId(document.id);
    clearMutationState();
    try {
      const downloaded = await api.downloadKnowledge(document.id);
      downloadText(downloaded.content, downloaded.filename);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusyId(null);
    }
  }

  async function reindex(document: KnowledgeDocument) {
    const intent = `knowledge-reindex:${document.id}`;
    const handle = mutationStore.handleFor(intent);
    mutationStore.abandon(`knowledge-hide:${document.id}`);
    setBusyId(document.id);
    clearMutationState();
    try {
      await api.reindex(document.id, { idempotency: handle });
      mutationStore.finish(intent, handle);
      await load();
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) {
        setRetryAction({ kind: "reindex", documentId: document.id });
      } else {
        mutationStore.abandon(intent, handle);
      }
      setError(cause);
    } finally {
      setBusyId(null);
    }
  }

  async function hide(document: KnowledgeDocument, retry = false) {
    if (
      !retry &&
      !window.confirm(
        t("deleteFileConfirm", { filename: document.source_filename }),
      )
    ) {
      return;
    }
    const intent = `knowledge-hide:${document.id}`;
    const handle = mutationStore.handleFor(intent);
    if (!retry) mutationStore.abandon(`knowledge-reindex:${document.id}`);
    setBusyId(document.id);
    clearMutationState();
    try {
      await api.hideKnowledge(document.id, {
        idempotency: handle,
      });
      mutationStore.finish(intent, handle);
      setDocuments((current) =>
        current.filter((item) => item.id !== document.id),
      );
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) {
        setRetryAction({ kind: "hide", documentId: document.id });
      } else {
        mutationStore.abandon(intent, handle);
      }
      setError(cause);
    } finally {
      setBusyId(null);
    }
  }

  function retry() {
    if (!retryAction) {
      void load();
    } else if (retryAction.kind === "create") {
      void create(retryAction.file);
    } else if (retryAction.kind === "replace") {
      void replace(retryAction.request);
    } else {
      const document = documents.find(
        (item) => item.id === retryAction.documentId,
      );
      if (!document) return;
      if (retryAction.kind === "reindex") void reindex(document);
      else void hide(document, true);
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
  if (error && documents.length === 0 && !creating && !editing) {
    return (
      <>
        <WorkspaceAction name="new" disabled />
        <ErrorNotice error={error} onRetry={retry} />
      </>
    );
  }

  const visible = documents.filter(
    (document) => document.workspace_state === "active",
  );

  return (
    <>
      <PageIntro title={t("knowledgePageTitle")} />
      <WorkspaceAction
        name="new"
        disabled={busyId !== null || creating || editing !== null}
        onClick={() => setCreating(true)}
      />
      {error ? <ErrorNotice error={error} onRetry={retry} /> : null}
      {conflict ? (
        <div className="notice notice-warning" role="status">
          {t("knowledgeConflict")}
        </div>
      ) : null}
      {notice ? (
        <div className="notice notice-success" role="status">
          {t(notice)}
        </div>
      ) : null}
      {creating ? (
        <SectionCard>
          <MarkdownEditor
            disabled={busyId !== null}
            onCreate={create}
            onChange={() => {
              mutationStore.abandon(`knowledge-create:${groupId}`);
              clearMutationState();
            }}
            onCancel={() => {
              mutationStore.abandon(`knowledge-create:${groupId}`);
              clearMutationState();
              setCreating(false);
            }}
          />
        </SectionCard>
      ) : null}
      {editing ? (
        <SectionCard title={t("knowledgeEditTitle")}>
          <MarkdownEditor
            key={editing.id + editing.content_hash}
            document={editing}
            initialContent={editingContent}
            disabled={busyId !== null}
            onReplace={replace}
            onChange={() => {
              mutationStore.abandon(`knowledge-replace:${editing.id}`);
              clearMutationState();
            }}
            onCancel={() => {
              mutationStore.abandon(`knowledge-replace:${editing.id}`);
              clearMutationState();
              setEditing(null);
              setEditingContent("");
            }}
          />
        </SectionCard>
      ) : null}
      {!creating && !editing ? (
        <SectionCard
          title={`${t("filesHeading")} · ${visible.length}`}
          guide="knowledge.files"
        >
          {visible.length === 0 ? (
            <EmptyCard title={t("knowledgeNoFiles")} />
          ) : (
            <div className={`knowledge-tile-grid ${styles.grid}`}>
              {visible.map((document) => (
                <div
                  className={`knowledge-tile ${styles.tile}`}
                  key={document.id}
                >
                  <span className="document-main">
                    <strong title={document.source_filename}>
                      {document.source_filename}
                    </strong>
                    <small>
                      {document.char_count.toLocaleString()} {t("characters")}
                    </small>
                  </span>
                  <div className={`icon-action-row ${styles.actions}`}>
                    <button
                      className="icon-action"
                      type="button"
                      disabled={busyId !== null}
                      aria-label={t("edit")}
                      data-ui-guide="knowledge.edit"
                      onClick={() => void beginEdit(document)}
                    >
                      <IconEdit />
                    </button>
                    <button
                      className="icon-action"
                      type="button"
                      disabled={busyId !== null}
                      aria-label={t("download")}
                      data-ui-guide="knowledge.download"
                      onClick={() => void download(document)}
                    >
                      <IconDownload />
                    </button>
                    {document.index_status === "failed" ? (
                      <button
                        className="icon-action"
                        type="button"
                        disabled={busyId !== null}
                        aria-label={t("reindex")}
                        data-ui-guide="knowledge.reindex"
                        onClick={() => void reindex(document)}
                      >
                        <IconRefresh />
                      </button>
                    ) : null}
                    <button
                      className="icon-action icon-action-danger"
                      type="button"
                      disabled={busyId !== null}
                      aria-label={t("delete")}
                      data-ui-guide="knowledge.hide"
                      onClick={() => void hide(document)}
                    >
                      <IconClose />
                    </button>
                  </div>
                  {document.index_status !== "ready" ? (
                    <div className={styles.status}>
                      <StatusBadge
                        status={document.index_status}
                        tone={
                          document.index_status === "failed" ? "bad" : "warn"
                        }
                      />
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </SectionCard>
      ) : null}
    </>
  );
}

function downloadText(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
