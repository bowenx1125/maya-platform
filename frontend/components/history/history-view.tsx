"use client";

import type { ReactNode } from "react";

import { useLocale } from "../locale";
import type {
  HistoryInteraction,
  HistoryReport,
  HistoryTranscript,
  ReportRevisionSummary,
  ReportRevisionView,
} from "./types";
import styles from "./history.module.css";

type TextPair = { en: string; zh: string };

function label(locale: string, value: TextPair): string {
  return locale === "zh" ? value.zh : value.en;
}

function statusClass(status: string): string {
  if (status === "ready" || status === "completed") return styles.statusReady;
  if (status === "failed") return styles.statusFailed;
  if (status === "generating" || status === "partial")
    return styles.statusGenerating;
  return "";
}

function Status({ status }: { status: string }) {
  return (
    <span className={`${styles.status} ${statusClass(status)}`}>{status}</span>
  );
}

export function TranscriptHistory({
  transcript,
  showTranslated = false,
}: {
  transcript: HistoryTranscript;
  showTranslated?: boolean;
}) {
  const { locale } = useLocale();
  return (
    <section
      className={styles.section}
      aria-labelledby="history-transcript-title"
    >
      <div className={styles.sectionHeader}>
        <div>
          <h2 id="history-transcript-title">
            {label(locale, { en: "Transcript", zh: "发言记录" })}
          </h2>
          <p>
            {label(locale, {
              en: "The English transcript is authoritative; translations are optional derived text.",
              zh: "英文发言是权威原文；译文只是可选的派生内容。",
            })}
          </p>
        </div>
        <span className={styles.status}>
          {transcript.turns.length} {label(locale, { en: "turns", zh: "段" })}
        </span>
      </div>
      {transcript.turns.length === 0 ? (
        <p className={styles.empty}>
          {label(locale, {
            en: "No public turns yet.",
            zh: "尚无已公开发言。",
          })}
        </p>
      ) : (
        <ol className={styles.turnList}>
          {transcript.turns.map((turn) => (
            <li className={styles.turn} key={turn.id}>
              <div className={styles.turnHeader}>
                <strong>
                  {label(locale, { en: "Turn", zh: "发言" })}{" "}
                  {turn.turn_index + 1}
                </strong>
                <span className={styles.muted}>
                  {turn.retrieval_status === "matched"
                    ? label(locale, { en: "RAG evidence", zh: "RAG 证据" })
                    : label(locale, {
                        en: "General reasoning / no match",
                        zh: "一般推理 / 未命中",
                      })}
                </span>
              </div>
              <p className={styles.speech}>
                {showTranslated && turn.translated_text
                  ? turn.translated_text
                  : turn.speech}
              </p>
              {showTranslated && turn.translated_text ? (
                <span className={styles.muted}>
                  {label(locale, {
                    en: "English source remains authoritative.",
                    zh: "英文原文仍是权威来源。",
                  })}
                </span>
              ) : null}
              {turn.sources.length > 0 ? (
                <ul className={styles.sources} aria-label="Sources / 来源">
                  {turn.sources.map((source) => (
                    <li
                      className={styles.source}
                      key={`${turn.id}-${source.source_filename}`}
                    >
                      {source.source_filename}
                    </li>
                  ))}
                </ul>
              ) : null}
              {turn.translated_text ? (
                <p className={styles.translation}>
                  <strong>
                    {label(locale, { en: "Test translation", zh: "测试译文" })}
                    {" / "}
                  </strong>
                  {turn.translated_text}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      )}
      <div className={styles.boundary}>
        <strong>
          {transcript.audio_retained
            ? label(locale, {
                en: "Audio retained for the current course debate",
                zh: "当前课程场次的语音仍保留",
              })
            : label(locale, {
                en: "Audio is no longer retained for this debate",
                zh: "本场语音已不再保留",
              })}
        </strong>
        <span>
          {label(locale, {
            en: "Text, sources and derived translations remain available in history.",
            zh: "文字、来源和派生译文仍保留在历史记录中。",
          })}
        </span>
      </div>
    </section>
  );
}

export function InteractionHistory({
  interaction,
}: {
  interaction: HistoryInteraction;
}) {
  const { locale } = useLocale();
  return (
    <section
      className={styles.section}
      aria-labelledby="history-interaction-title"
    >
      <div className={styles.sectionHeader}>
        <div>
          <h2 id="history-interaction-title">
            {label(locale, { en: "Classroom interaction", zh: "课堂互动" })}
          </h2>
          <p>
            {label(locale, {
              en: "Raw barrages remain named for the teacher display; vote records remain anonymous.",
              zh: "原始弹幕保留昵称供教师查看；投票记录保持匿名。",
            })}
          </p>
        </div>
        <Status status={interaction.status} />
      </div>
      <div className={styles.metaRow}>
        <strong>{label(locale, { en: "Vote totals", zh: "投票统计" })}</strong>
      </div>
      {interaction.votes.length > 0 ? (
        <ul className={styles.barrageList}>
          {interaction.votes.map((vote) => (
            <li className={styles.barrage} key={vote.participant_id}>
              <div className={styles.barrageHeader}>
                <strong>
                  {vote.slot ? `${vote.slot}. ` : ""}
                  {vote.participant_name ?? vote.participant_id}
                </strong>
                <span>
                  {vote.count} · {vote.percentage}%
                </span>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.empty}>
          {label(locale, { en: "No votes recorded.", zh: "尚无投票。" })}
        </p>
      )}
      <div className={styles.metaRow}>
        <strong>{label(locale, { en: "Raw barrages", zh: "原始弹幕" })}</strong>
        <span className={styles.muted}>{interaction.barrages.length}</span>
      </div>
      {interaction.barrages.length > 0 ? (
        <ol className={styles.barrageList}>
          {interaction.barrages.map((barrage) => (
            <li className={styles.barrage} key={barrage.id}>
              <div className={styles.barrageHeader}>
                <strong>{barrage.nickname}</strong>
                <span className={styles.muted}>#{barrage.sequence}</span>
              </div>
              <p className={styles.speech}>{barrage.raw_text}</p>
            </li>
          ))}
        </ol>
      ) : (
        <p className={styles.empty}>
          {label(locale, { en: "No barrages recorded.", zh: "尚无弹幕。" })}
        </p>
      )}
    </section>
  );
}

function RevisionCard({ revision }: { revision: ReportRevisionView }) {
  const { locale } = useLocale();
  return (
    <li className={styles.revision}>
      <div className={styles.revisionHeader}>
        <strong>
          {label(locale, { en: "Revision", zh: "修订" })} {revision.revision_no}
        </strong>
        <Status status={revision.status} />
      </div>
      {revision.status === "ready" && revision.english_markdown ? (
        <>
          <p className={styles.muted}>
            {revision.word_count} {label(locale, { en: "words", zh: "词" })}
          </p>
          <pre className={styles.report}>{revision.english_markdown}</pre>
          {revision.translated_markdown ? (
            <p className={styles.translation}>
              <strong>
                {label(locale, { en: "Test translation", zh: "测试译文" })}
              </strong>
              {"\n"}
              {revision.translated_markdown}
            </p>
          ) : null}
        </>
      ) : revision.safe_error_code ? (
        <p className={styles.muted}>
          {label(locale, { en: "Safe error", zh: "安全错误" })}:{" "}
          {revision.safe_error_code}
        </p>
      ) : null}
    </li>
  );
}

export function ReportHistory({ report }: { report: HistoryReport }) {
  const { locale } = useLocale();
  const current = report.current_success_revision;
  return (
    <section className={styles.section} aria-labelledby="history-report-title">
      <div className={styles.sectionHeader}>
        <div>
          <h2 id="history-report-title">
            {label(locale, { en: "Maya report history", zh: "Maya 报告历史" })}
          </h2>
          <p>
            {label(locale, {
              en: "Successful revisions stay available when a later attempt fails.",
              zh: "后续尝试失败时，历史成功修订仍然保留。",
            })}
          </p>
        </div>
        <Status status={report.generation_status} />
      </div>
      {current ? (
        <div className={styles.boundary}>
          <strong>
            {label(locale, {
              en: "Current successful revision",
              zh: "当前成功修订",
            })}
            : v{current.revision_no}
          </strong>
          <span>
            {label(locale, {
              en: "The report uses only the frozen debate, used evidence and validated anonymous insight.",
              zh: "报告只使用冻结辩论、实际使用证据和已验证匿名洞察。",
            })}
          </span>
        </div>
      ) : null}
      {report.revisions.length > 0 ? (
        <ul className={styles.revisionList}>
          {report.revisions.map((revision) => (
            <RevisionCard
              key={revision.id}
              revision={
                revision.id === current?.id && current
                  ? current
                  : { ...revision, english_markdown: null }
              }
            />
          ))}
        </ul>
      ) : (
        <p className={styles.empty}>
          {label(locale, {
            en: "No report revisions yet.",
            zh: "尚无报告修订。",
          })}
        </p>
      )}
    </section>
  );
}

export function HistoryView({
  topic,
  transcript,
  interaction,
  report,
  translation,
  showTranslated = false,
}: {
  topic?: string;
  transcript: HistoryTranscript;
  interaction?: HistoryInteraction;
  report?: HistoryReport;
  translation?: ReactNode;
  showTranslated?: boolean;
}) {
  const { locale } = useLocale();
  return (
    <div
      className={styles.root}
      aria-label={label(locale, { en: "Debate history", zh: "辩论历史" })}
    >
      {topic ? (
        <div className={styles.boundary}>
          <strong>{topic}</strong>
          <span>
            {label(locale, {
              en: "History is read-only; playback availability follows the course audio pointer.",
              zh: "历史记录只读；语音播放是否可用由课程当前音频指针决定。",
            })}
          </span>
        </div>
      ) : null}
      <TranscriptHistory
        transcript={transcript}
        showTranslated={showTranslated}
      />
      {interaction ? <InteractionHistory interaction={interaction} /> : null}
      {report ? <ReportHistory report={report} /> : null}
      {translation}
    </div>
  );
}

export type {
  HistoryInteraction,
  HistoryReport,
  HistoryTranscript,
  ReportRevisionSummary,
  ReportRevisionView,
};
