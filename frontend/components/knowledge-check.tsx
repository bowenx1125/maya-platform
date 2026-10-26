"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useT } from "../lib/i18n";
import { cn } from "../lib/utils";
import { IconClose, IconDownload, IconEye } from "./quiet-icons";
import { buttonVariants } from "./ui/button";
import { ReportMarkdown } from "./report/report-markdown";

export type KnowledgeCheck = { title: string; markdown: string };

export function downloadText(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

/** View (check overlay) and download for Brainform RAG and Knowledge rows. */
export function useKnowledgeCheck() {
  const [check, setCheck] = useState<KnowledgeCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const viewMarkdown = useCallback(
    async (title: string, load: () => Promise<string>) => {
      setBusy(true);
      setError(null);
      try {
        setCheck({ title, markdown: await load() });
      } catch (cause) {
        setError(cause);
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const downloadMarkdown = useCallback(
    async (filename: string, load: () => Promise<string>) => {
      setBusy(true);
      setError(null);
      try {
        downloadText(await load(), filename);
      } catch (cause) {
        setError(cause);
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const closeCheck = useCallback(() => setCheck(null), []);

  return { check, busy, error, viewMarkdown, downloadMarkdown, closeCheck };
}

/** The blurred full-page overlay that shows one Markdown text read-only. */
export function KnowledgeCheckOverlay({
  check,
  onClose,
}: {
  check: KnowledgeCheck | null;
  onClose: () => void;
}) {
  const t = useT();
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!check) return;
    closeRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [check, onClose]);

  const checkRoot = typeof document === "undefined" ? null : document.body;
  if (!check || !checkRoot) return null;
  return createPortal(
    <div className="knowledge-check" onClick={onClose}>
      <div
        className="knowledge-check-card"
        role="dialog"
        aria-modal="true"
        aria-label={check.title}
        onClick={(event) => event.stopPropagation()}
      >
        <button
          ref={closeRef}
          className={cn(buttonVariants({ variant: "neutral", size: "icon" }), "knowledge-check-close absolute top-3 right-3 z-[2] min-h-0 rounded-[10px] p-0")}
          type="button"
          aria-label={t("knowledgeCheckClose")}
          onClick={onClose}
        >
          <IconClose />
        </button>
        <ReportMarkdown label={check.title}>{check.markdown}</ReportMarkdown>
      </div>
    </div>,
    checkRoot,
  );
}

/** The eye (view) and download buttons of one Brainform row. */
export function KnowledgeRowActions({
  name,
  disabled,
  onView,
  onDownload,
}: {
  name: string;
  disabled: boolean;
  onView: () => void;
  onDownload: () => void;
}) {
  const t = useT();
  const icon = cn(
    buttonVariants({ variant: "neutral", size: "icon" }),
    "min-h-0 rounded-[10px] p-0",
  );
  return (
    <>
      <button
        className={icon}
        type="button"
        disabled={disabled}
        aria-label={t("brainformViewRagNamed", { name })}
        onClick={onView}
      >
        <IconEye />
      </button>
      <button
        className={icon}
        type="button"
        disabled={disabled}
        aria-label={t("brainformDownloadRagNamed", { name })}
        onClick={onDownload}
      >
        <IconDownload />
      </button>
    </>
  );
}
