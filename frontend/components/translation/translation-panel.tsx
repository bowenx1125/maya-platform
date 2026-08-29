"use client";

import { useLocale } from "../locale";
import type { TranslationBatch, TranslationItemSummary } from "./types";
import styles from "./translation.module.css";

type TextPair = { en: string; zh: string };

function label(locale: string, value: TextPair): string {
  return locale === "zh" ? value.zh : value.en;
}

function statusClass(status: string): string {
  return styles[status as keyof typeof styles] ?? "";
}

function itemLabel(locale: string, item: TranslationItemSummary): string {
  return `${item.content_type === "turn" ? label(locale, { en: "Turn", zh: "发言" }) : label(locale, { en: "Maya report", zh: "Maya 报告" })} · ${item.content_id}`;
}

export function TranslationBatchList({
  batches,
}: {
  batches: TranslationBatch[];
}) {
  const { locale } = useLocale();
  if (batches.length === 0) {
    return (
      <p className={styles.muted}>
        {label(locale, {
          en: "No translation batches yet.",
          zh: "尚无翻译批次。",
        })}
      </p>
    );
  }
  return (
    <ol className={styles.batchList}>
      {batches.map((batch) => (
        <li className={styles.batch} key={batch.id}>
          <div className={styles.batchHeader}>
            <h3>
              {label(locale, { en: "Batch", zh: "批次" })} ·{" "}
              {batch.id.slice(0, 8)}
            </h3>
            <span className={`${styles.status} ${statusClass(batch.status)}`}>
              {batch.status}
            </span>
          </div>
          <p className={styles.summary}>
            <span>
              {batch.succeeded_items}/{batch.total_items}{" "}
              {label(locale, { en: "succeeded", zh: "成功" })}
            </span>
            <span>
              {batch.failed_items} {label(locale, { en: "failed", zh: "失败" })}
            </span>
            <span>
              {label(locale, {
                en: "Mock test representation",
                zh: "Mock 测试表示",
              })}
            </span>
          </p>
          {batch.items.some((item) => item.status === "failed") ? (
            <ul
              className={styles.itemList}
              aria-label="Translation item errors / 翻译项错误"
            >
              {batch.items
                .filter((item) => item.status === "failed")
                .map((item) => (
                  <li
                    className={styles.item}
                    key={`${batch.id}-${item.content_id}`}
                  >
                    <div className={styles.itemHeader}>
                      <strong>{itemLabel(locale, item)}</strong>
                      <span className={`${styles.status} ${styles.failed}`}>
                        failed
                      </span>
                    </div>
                    {item.safe_error_code ? (
                      <span className={styles.error}>
                        {item.safe_error_code}
                      </span>
                    ) : null}
                  </li>
                ))}
            </ul>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

export function TranslationPanel({
  batches,
  onTranslate,
  onToggleDisplay,
  translatedVisible = false,
  busy = false,
  error = null,
}: {
  batches: TranslationBatch[];
  onTranslate: () => void | Promise<void>;
  onToggleDisplay?: () => void;
  translatedVisible?: boolean;
  busy?: boolean;
  error?: string | null;
}) {
  const { locale } = useLocale();
  return (
    <section
      className={styles.section}
      aria-labelledby="translation-panel-title"
    >
      <div className={styles.header}>
        <div>
          <h2 id="translation-panel-title">
            {label(locale, { en: "Test translation", zh: "测试翻译" })}
          </h2>
          <p>
            {label(locale, {
              en: "Translate public English speeches on demand. English remains the authoritative source.",
              zh: "按需翻译公开英文发言；英文始终是权威来源。",
            })}
          </p>
        </div>
        <button
          className={styles.button}
          type="button"
          onClick={() => {
            if (translatedVisible && onToggleDisplay) {
              onToggleDisplay();
            } else {
              void onTranslate();
            }
          }}
          disabled={busy}
        >
          {busy
            ? label(locale, { en: "Translating…", zh: "翻译中…" })
            : translatedVisible
              ? label(locale, {
                  en: "Show English source",
                  zh: "显示英文原文",
                })
              : label(locale, {
                  en: "Translate current content",
                  zh: "翻译当前全部内容",
                })}
        </button>
      </div>
      <p className={styles.note}>
        {label(locale, {
          en: "Mock representation only; it does not claim translation quality and never feeds debate generation, RAG, TTS or reports.",
          zh: "仅为 Mock 测试表示，不代表翻译质量，也不会回流辩论生成、RAG、TTS 或报告。",
        })}
      </p>
      {error ? <p className={styles.error}>{error}</p> : null}
      <TranslationBatchList batches={batches} />
    </section>
  );
}

export const TranslationButton = TranslationPanel;

export type { TranslationBatch, TranslationItemSummary } from "./types";
