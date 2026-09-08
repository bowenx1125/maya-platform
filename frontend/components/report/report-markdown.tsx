"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import styles from "./report-markdown.module.css";

export function ReportMarkdown({
  children,
  className,
  label,
}: {
  children: string;
  className?: string;
  label?: string;
}) {
  return (
    <article
      className={`${styles.document} ${className ?? ""}`}
      aria-label={label}
    >
      <ReactMarkdown skipHtml remarkPlugins={[remarkGfm]}>
        {children}
      </ReactMarkdown>
    </article>
  );
}
