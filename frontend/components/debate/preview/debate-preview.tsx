"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useLocale } from "../../locale";
import { teachingRoundLabel } from "../../../lib/debate-rounds";
import type { SegmentEvidence } from "../../../lib/evidence-grading";
import { SegmentGrade } from "../../evidence/segment-grade";

import { ErrorNotice, Notice, SectionCard, StatusBadge } from "../../ui";
import { tm } from "../../../lib/i18n";
import { IconRefresh } from "../../quiet-icons";
import styles from "./debate-preview.module.css";

export type DebatePreviewProgress = {
  prepared_turns: number;
  expected_turns: number;
  ready: boolean;
};

export type DebatePreviewSegment = SegmentEvidence & {
  text: string;
  source_ids: readonly string[];
  reply_to: string | null;
};

export type DebatePreviewSource = {
  source_id: string;
  source_filename: string;
  excerpt: string;
  query_text?: string | null;
  version_label: string;
};

export type DebatePreviewTurn = {
  id: string;
  participant_id: string;
  round_no: number;
  turn_index: number;
  speech: string;
  generation_status: string;
  audio_ready: boolean;
  safe_error_code?: string | null;
  segments?: readonly DebatePreviewSegment[];
  sources?: readonly DebatePreviewSource[];
};

export type DebatePreviewParticipant = {
  id: string;
  agent_name: string;
  slot?: string;
};

export type DebatePreviewSnapshot = {
  teaching_protocol?: "four_round_v1" | null;
  topic: string;
  background?: string;
  participants: readonly DebatePreviewParticipant[];
  preview: DebatePreviewProgress | null;
  preview_turns?: readonly DebatePreviewTurn[];
};

export function DebatePreview({
  detail,
  openClassroomHref,
  onRetryTurn,
  retryingTurnId = null,
  error = null,
  actions,
}: {
  detail: DebatePreviewSnapshot;
  openClassroomHref: string;
  onRetryTurn?: (turnId: string) => void;
  retryingTurnId?: string | null;
  error?: string | null;
  actions?: ReactNode;
}) {
  const previewTurns = detail.preview_turns ?? [];
  const progress = detail.preview ?? deriveProgress(previewTurns);
  const participantNames = new Map(
    detail.participants.map((participant) => [
      participant.id,
      participant.agent_name,
    ]),
  );
  const turns = [...previewTurns].sort(
    (left, right) => left.turn_index - right.turn_index,
  );
  const background = (detail.background ?? "").trim();
  const { locale } = useLocale();
  // A turn whose audio failed used to show only on its own card, so a Preview
  // where every turn failed read as still preparing. Say so at the top.
  // An Agent with no voice is a teacher's choice, not a failure: its turns
  // simply play as text, so they never raise this banner.
  const audioFailed = turns.filter(
    (turn) =>
      !turn.audio_ready &&
      turn.safe_error_code !== "tts_voice_unavailable" &&
      (turn.generation_status === "failed" || Boolean(turn.safe_error_code)),
  );
  const firstFailed = audioFailed[0];

  return (
    <div className={styles.page} data-testid="debate-preview">
      <div className={styles.header}>
        <div>
          <h1>{detail.topic}</h1>
        </div>
        <div className={styles.headerActions}>
          {actions}
          <div className={styles.navigationActions}>
            {progress.ready ? (
              <Link className="primary-action" href={openClassroomHref}>
                Immerse
              </Link>
            ) : null}
          </div>
        </div>
      </div>

      {error ? <ErrorNotice error={error} /> : null}

      {firstFailed ? (
        <Notice
          inline
          tone="error"
          action={
            onRetryTurn ? (
              <button
                className="inline-button"
                type="button"
                data-testid="preview-audio-failed-retry"
                disabled={retryingTurnId !== null}
                onClick={() => onRetryTurn(firstFailed.id)}
              >
                {locale === "zh" ? "重试" : "Retry"}
              </button>
            ) : null
          }
        >
          <span data-testid="preview-audio-failed">
            {tm(
              "debatePreviewAudioFailed",
              {
                count: audioFailed.length,
                code: firstFailed.safe_error_code ?? "turn_generation_failed",
              },
              locale,
            )}
          </span>
        </Notice>
      ) : null}

      {turns.length === 0 && !background ? (
        <SectionCard>
          <p className={styles.empty}>No saved turns yet.</p>
        </SectionCard>
      ) : (
        <div className={styles.turns}>
          {background ? <BackgroundCard text={background} /> : null}
          {turns.length === 0 ? (
            <p className={styles.empty}>No saved turns yet.</p>
          ) : null}
          {turns.map((turn) => (
            <PreviewTurnCard
              key={turn.id}
              participantName={
                participantNames.get(turn.participant_id) ?? "Agent"
              }
              retryBusy={retryingTurnId !== null}
              retrying={retryingTurnId === turn.id}
              teachingProtocol={detail.teaching_protocol === "four_round_v1"}
              turn={turn}
              onRetry={onRetryTurn}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function BackgroundCard({ text }: { text: string }) {
  return (
    <article className={styles.turnCard} data-testid="preview-background">
      <div className={styles.turnHeader}>
        <div>
          <h2>Background</h2>
        </div>
      </div>
      <p className={styles.speech}>{text}</p>
    </article>
  );
}

function PreviewTurnCard({
  turn,
  participantName,
  retryBusy,
  retrying,
  onRetry,
  teachingProtocol,
}: {
  turn: DebatePreviewTurn;
  participantName: string;
  retryBusy: boolean;
  retrying: boolean;
  onRetry?: (turnId: string) => void;
  teachingProtocol?: boolean;
}) {
  const { locale } = useLocale();
  const failed =
    turn.generation_status === "failed" || Boolean(turn.safe_error_code);
  const savedSpeech = Boolean(turn.speech.trim());
  const textFallbackReady =
    turn.generation_status === "final_ready" &&
    turn.audio_ready === false &&
    savedSpeech &&
    [
      "tts_voice_unavailable",
      "tts_provider_unavailable",
      "tts_timeout",
      "tts_http_rejected",
      "tts_response_invalid",
      "tts_result_url_rejected",
      "tts_result_dns_failed",
      "tts_result_download_failed",
      "tts_audio_invalid",
    ].includes(turn.safe_error_code ?? "");
  return (
    <article
      className={styles.turnCard}
      data-testid={`preview-turn-${turn.id}`}
    >
      <div className={styles.turnHeader}>
        <div>
          <span className={styles.turnRound}>
            Round {turn.round_no}
            {teachingProtocol
              ? ` · ${teachingRoundLabel(turn.round_no, locale)}`
              : ""}
          </span>
          <h2>{participantName}</h2>
        </div>
        <div className={styles.turnStatus}>
          <StatusBadge
            status={
              turn.audio_ready
                ? "Audio Ready"
                : failed
                  ? "Audio Not Ready"
                  : "Preparing"
            }
            tone={turn.audio_ready ? "good" : failed ? "bad" : "warn"}
          />
        </div>
      </div>

      {savedSpeech ? (
        <p className={styles.speech}>{turn.speech}</p>
      ) : (
        <p className={styles.missingSpeech}>Speech is not available yet.</p>
      )}

      {failed ? (
        <div
          className={styles.errorRow}
          role="status"
          data-text-fallback-ready={textFallbackReady ? "true" : "false"}
        >
          <span>
            {savedSpeech ? "Audio needs attention." : "Speech needs attention."}
          </span>
          {turn.safe_error_code ? (
            <code data-testid="preview-safe-error-code">
              {turn.safe_error_code}
            </code>
          ) : null}
          {onRetry ? (
            <button
              className={`icon-action ${styles.retryButton}`}
              aria-label={retrying ? "Retrying…" : "Retry turn"}
              aria-busy={retrying}
              disabled={retryBusy}
              onClick={() => onRetry(turn.id)}
              type="button"
            >
              <IconRefresh />
            </button>
          ) : null}
        </div>
      ) : null}

      {(turn.segments?.length ?? 0) > 0 || (turn.sources?.length ?? 0) > 0 ? (
        <RagCheck segments={turn.segments ?? []} sources={turn.sources ?? []} />
      ) : null}
    </article>
  );
}

function RagCheck({
  segments,
  sources,
}: {
  segments: readonly DebatePreviewSegment[];
  sources: readonly DebatePreviewSource[];
}) {
  const sourceById = new Map(
    sources.map((source) => [source.source_id, source]),
  );
  return (
    <details className={styles.ragCheck}>
      <summary>
        Check RAG
        <span className={styles.evidenceCount}>{sourceById.size}</span>
      </summary>
      <div className={styles.segmentList}>
        {segments.map((segment, index) => (
          <div className={styles.segment} key={`${index}-${segment.text}`}>
            <SegmentGrade segment={segment} />
            <p>{segment.text}</p>
            <div className={styles.segmentSources}>
              {segment.source_ids.length === 0 ? (
                <span className={styles.noSource}>General reasoning</span>
              ) : (
                segment.source_ids.map((sourceId) => {
                  const source = sourceById.get(sourceId);
                  return source ? (
                    <div className={styles.source} key={sourceId}>
                      <strong>{source.source_filename}</strong>
                      <span>
                        {source.version_label} · query:{" "}
                        {source.query_text ?? "none recorded"}
                      </span>
                      <small>{source.excerpt}</small>
                    </div>
                  ) : (
                    <span className={styles.noSource} key={sourceId}>
                      Source unavailable
                    </span>
                  );
                })
              )}
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}

function deriveProgress(
  turns: readonly DebatePreviewTurn[],
): DebatePreviewProgress {
  const expected = turns.length;
  const prepared = turns.filter(
    (turn) =>
      ["final_ready", "ready", "completed"].includes(turn.generation_status) &&
      Boolean(turn.speech.trim()),
  ).length;
  return {
    prepared_turns: prepared,
    expected_turns: expected,
    ready: expected > 0 && prepared === expected,
  };
}
