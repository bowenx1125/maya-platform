"use client";

import { useT } from "../../lib/i18n";
import { KindSticker } from "../ui/error-kit";

export function buildMarkdownFile(filename: string, content: string): File {
  return new File([content], filename, { type: "text/markdown" });
}

export function downloadKnowledgeMarkdown(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function KnowledgeFilenameField({
  value,
  onChange,
  disabled = false,
  readOnly = false,
  className,
  describedBy,
  invalid = false,
  fileError = false,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  readOnly?: boolean;
  className?: string;
  describedBy?: string;
  invalid?: boolean;
  /** U3: the file sticker on the field a filename error points at. */
  fileError?: boolean;
}) {
  const t = useT();
  return (
    <label className={fileError ? `relative ${className ?? ""}` : className}>
      {fileError ? <KindSticker kind="file" on /> : null}
      <span>{t("knowledgeFilename")}</span>
      <input
        type="text"
        value={value}
        disabled={disabled}
        readOnly={readOnly}
        onChange={(event) => onChange(event.target.value)}
        placeholder={t("knowledgeFilenamePlaceholder")}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
      />
    </label>
  );
}

export function KnowledgeMarkdownField({
  value,
  onChange,
  disabled = false,
  readOnly = false,
  className,
  rows = 10,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  readOnly?: boolean;
  className?: string;
  rows?: number;
}) {
  const t = useT();
  return (
    <label className={className}>
      <span>{t("knowledgeContent")}</span>
      <textarea
        className="markdown-editor"
        value={value}
        disabled={disabled}
        readOnly={readOnly}
        onChange={(event) => onChange(event.target.value)}
        aria-label={t("knowledgeContent")}
        rows={rows}
      />
    </label>
  );
}
