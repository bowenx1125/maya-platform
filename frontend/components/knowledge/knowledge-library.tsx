"use client";

import { useCallback, useEffect, useState } from "react";

import {
  apiErrorMessage,
  isAmbiguousMutationFailure,
  isConflict,
  type KnowledgeDocument,
} from "../../lib/api";
import { useIdempotencyStore } from "../../lib/idempotency";
import type { MessageKey } from "../../lib/i18n";
import { useT } from "../locale";
import { useSession } from "../session-provider";
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
      !window.confirm(t("hideConfirm", { filename: document.source_filename }))
    ) {
      return;
    }
    const intent = `knowledge-hide:${document.id}`;
    const handle = mutationStore.handleFor(intent);
    if (!retry) mutationStore.abandon(`knowledge-reindex:${document.id}`);
    setBusyId(document.id);
    clearMutationState();
    try {
      const next = await api.hideKnowledge(document.id, {
        idempotency: handle,
      });
      mutationStore.finish(intent, handle);
      setDocuments((current) =>
        current.map((item) => (item.id === next.id ? next : item)),
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

  if (loading) return <LoadingCard />;
  if (error && documents.length === 0) {
    return <ErrorNotice error={error} onRetry={retry} />;
  }

  return (
    <>
      <PageIntro
        eyebrow={t("knowledgePage")}
        title={t("knowledgePageTitle")}
        description={t("knowledgePageLede")}
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
      <SectionCard
        title={t("knowledgeCreateTitle")}
        description={t("knowledgeCreateLede")}
      >
        <MarkdownEditor
          disabled={busyId !== null}
          onCreate={(file) => void create(file)}
        />
      </SectionCard>
      {editing ? (
        <SectionCard
          title={t("knowledgeEditTitle")}
          description={t("knowledgeEditLede")}
        >
          <p className="muted-copy">{t("knowledgeEditDownload")}</p>
          <MarkdownEditor
            document={editing}
            initialContent={editingContent}
            disabled={busyId !== null}
            onReplace={(request) => void replace(request)}
            onCancel={() => {
              setEditing(null);
              setEditingContent("");
            }}
          />
        </SectionCard>
      ) : null}
      <SectionCard
        title={`${documents.length} ${t("fileCount")}`}
        description={t("draftEnableLede")}
      >
        {documents.length === 0 ? (
          <EmptyCard title={t("knowledgeNoFiles")} />
        ) : (
          <div className="document-list">
            {documents.map((document) => (
              <div className="document-row library-row" key={document.id}>
                <span className="document-main">
                  <strong>{document.source_filename}</strong>
                  <small>
                    {document.char_count.toLocaleString()} {t("characters")} ·{" "}
                    {document.index_revision} · {document.workspace_state}
                  </small>
                </span>
                <StatusBadge
                  status={document.index_status}
                  tone={
                    document.index_status === "ready"
                      ? "good"
                      : document.index_status === "failed"
                        ? "bad"
                        : "warn"
                  }
                />
                <div className="row-actions">
                  <button
                    className="inline-button"
                    type="button"
                    disabled={busyId === document.id}
                    onClick={() => void beginEdit(document)}
                  >
                    {t("edit")}
                  </button>
                  <button
                    className="inline-button"
                    type="button"
                    disabled={busyId === document.id}
                    onClick={() => void download(document)}
                  >
                    {t("download")}
                  </button>
                  {document.index_status === "failed" ? (
                    <button
                      className="inline-button"
                      type="button"
                      disabled={busyId === document.id}
                      onClick={() => void reindex(document)}
                    >
                      {t("reindex")}
                    </button>
                  ) : null}
                  {document.workspace_state === "active" ? (
                    <button
                      className="inline-button danger-button"
                      type="button"
                      disabled={busyId === document.id}
                      onClick={() => void hide(document)}
                    >
                      {t("hide")}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>
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

export function knowledgeErrorMessage(error: unknown): string {
  return apiErrorMessage(error);
}
