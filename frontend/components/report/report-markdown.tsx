"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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
      className={`whitespace-normal leading-[1.75] [overflow-wrap:anywhere] [&>:first-child]:mt-0 [&_h1]:mt-[1.5em] [&_h1]:mb-[0.6em] [&_h1]:text-[1.5rem] [&_h1]:leading-[1.35] [&_h1]:text-(--ink) [&_h2]:mt-[1.5em] [&_h2]:mb-[0.6em] [&_h2]:text-[1.2rem] [&_h2]:leading-[1.35] [&_h2]:text-(--ink) [&_h3]:mt-[1.5em] [&_h3]:mb-[0.6em] [&_h3]:text-[1.05rem] [&_h3]:leading-[1.35] [&_h3]:text-(--ink) [&_p]:my-[0.7em] [&_ul]:pl-[1.5em] [&_ol]:pl-[1.5em] [&_a]:text-(--muted,#62626a) [&_a]:underline [&_blockquote]:my-[1em] [&_blockquote]:border-l-2 [&_blockquote]:border-(--line,#dedee3) [&_blockquote]:pl-[1em] [&_table]:w-full [&_table]:border-collapse [&_th]:border-b [&_th]:border-(--line,#dedee3) [&_th]:p-[0.5em] [&_th]:text-left [&_td]:border-b [&_td]:border-(--line,#dedee3) [&_td]:p-[0.5em] [&_td]:text-left [&_pre]:overflow-x-auto [&_pre]:bg-(--surface-subtle,#f5f5f7) [&_pre]:p-[1em] ${className ?? ""}`}
      aria-label={label}
    >
      <ReactMarkdown skipHtml remarkPlugins={[remarkGfm]}>
        {children}
      </ReactMarkdown>
    </article>
  );
}
