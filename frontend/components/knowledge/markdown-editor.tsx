"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import type { KnowledgeDocument } from "../../lib/api";
import { useT } from "../locale";

/** A narrow editable view with the authoritative replacement CAS fields. */
export type EditableKnowledgeDocument = Pick<
  KnowledgeDocument,
  | "id"
  | "source_filename"
  | "char_count"
  | "workspace_state"
  | "index_status"
  | "content_hash"
  | "index_revision"
>;

export type KnowledgeReplacementRequest = {
  documentId: string;
  file: File;
  expectedContentHash: string;
  expectedIndexRevision: number;
};

export type MarkdownEditorProps = {
  /** Present for copy-on-write edit mode; omitted for a library create. */
  document?: EditableKnowledgeDocument | null;
  initialFilename?: string;
  initialContent?: string;
  expectedContentHash?: string;
  expectedIndexRevision?: number;
  disabled?: boolean;
  /** Parent-owned callback that sends the generated File to the safe API. */
  onCreate?: (file: File) => Promise<unknown> | unknown;
  /** Parent-owned callback that sends the immutable replacement request. */
  onReplace?: (
    request: KnowledgeReplacementRequest,
  ) => Promise<unknown> | unknown;
  onCancel?: () => void;
};

/**
 * Build the exact Markdown File used by both create and replacement flows.
 * Keeping this helper outside the component makes the upload pipeline easy to
 * reuse from a group library page and an Agent workbench without duplicating
 * file validation or silently enabling a draft relation.
 */
export function buildMarkdownFile(filename: string, content: string): File {
  return new File([content], filename, { type: "text/markdown" });
}

/**
 * Small provider-neutral Markdown editor.
 *
 * The component intentionally knows nothing about PlatformApi, idempotency,
 * Agent versions, or document selection.  `onCreate` and `onReplace` remain
 * parent-owned seams, so a new library file can be persisted through the
 * existing secure multipart upload path without being enabled automatically.
 */
export function MarkdownEditor({
  document,
  initialFilename,
  initialContent = "",
  expectedContentHash,
  expectedIndexRevision,
  disabled = false,
  onCreate,
  onReplace,
  onCancel,
}: MarkdownEditorProps) {
  const t = useT();
  const replacing = Boolean(document);
  const [filename, setFilename] = useState(
    document?.source_filename ?? initialFilename ?? "notes.md",
  );
  const [content, setContent] = useState(initialContent);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setFilename(document?.source_filename ?? initialFilename ?? "notes.md");
      setContent(initialContent);
      setError(null);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [
    document?.id,
    document?.source_filename,
    initialFilename,
    initialContent,
  ]);

  const trimmedFilename = filename.trim();
  const validFilename =
    trimmedFilename.length > 0 && trimmedFilename.toLowerCase().endsWith(".md");
  const validContent = content.trim().length > 0;
  const canSubmit =
    !disabled &&
    !submitting &&
    validFilename &&
    validContent &&
    (replacing ? Boolean(onReplace) : Boolean(onCreate));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!validFilename || !validContent) {
      setError(t("knowledgeEditorInvalid"));
      return;
    }
    if (replacing && !onReplace) {
      setError(t("knowledgeEditorNoReplaceHandler"));
      return;
    }
    if (!replacing && !onCreate) {
      setError(t("knowledgeEditorNoCreateHandler"));
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const file = buildMarkdownFile(trimmedFilename, content);
      if (replacing && document && onReplace) {
        await onReplace({
          documentId: document.id,
          file,
          expectedContentHash: expectedContentHash ?? document.content_hash,
          expectedIndexRevision:
            expectedIndexRevision ?? document.index_revision,
        });
      } else if (!replacing && onCreate) {
        await onCreate(file);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("requestFallback"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      className="stack-form"
      onSubmit={submit}
      data-mode={replacing ? "replace" : "create"}
    >
      <label>
        <span>{t("knowledgeFilename")}</span>
        <input
          type="text"
          value={filename}
          disabled={disabled || submitting}
          onChange={(event) => setFilename(event.target.value)}
          placeholder={t("knowledgeFilenamePlaceholder")}
          aria-invalid={filename.length > 0 && !validFilename}
        />
      </label>
      <label>
        <span>{t("knowledgeContent")}</span>
        <textarea
          className="markdown-editor"
          value={content}
          disabled={disabled || submitting}
          onChange={(event) => setContent(event.target.value)}
          aria-label={t("knowledgeContent")}
          rows={10}
        />
      </label>
      {error ? (
        <div className="notice notice-error" role="alert">
          {error}
        </div>
      ) : null}
      <div className="button-row">
        <button className="primary-action" type="submit" disabled={!canSubmit}>
          {submitting
            ? t("knowledgeSaving")
            : replacing
              ? t("knowledgeReplace")
              : t("knowledgeAdd")}
        </button>
        {onCancel ? (
          <button
            className="secondary-action"
            type="button"
            disabled={disabled || submitting}
            onClick={onCancel}
          >
            {t("knowledgeCancel")}
          </button>
        ) : null}
      </div>
    </form>
  );
}

/** Descriptive aliases for callers that prefer a domain-specific component name. */
export const KnowledgeDocumentEditor = MarkdownEditor;
export const MarkdownCreateEditor = MarkdownEditor;
