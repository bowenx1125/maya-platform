"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { ErrorNotice, SectionCard, StatusBadge } from "../../ui";
import styles from "./debate-preview.module.css";

export type DebatePreviewProgress = {
  prepared_turns: number;
  expected_turns: number;
  ready: boolean;
};

export type DebatePreviewSegment = {
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
  topic: string;
  participants: readonly DebatePreviewParticipant[];
  preview: DebatePreviewProgress | null;
  preview_turns?: readonly DebatePreviewTurn[];
};

export function DebatePreview({
  detail,
  backHref,
  backLabel = "Back",
  openClassroomHref,
  onRetryTurn,
  retryingTurnId = null,
  error = null,
  actions,
}: {
  detail: DebatePreviewSnapshot;
  backHref?: string;
  backLabel?: string;
  openClassroomHref: string;
  onRetryTurn?: (turnId: string) => void;
  retryingTurnId?: string | null;
  error?: string | null;
  actions?: ReactNode;
}) {
  const previewTurns = detail.preview_turns ?? [];
  const progress = detail.preview ?? deriveProgress(previewTurns);
  const audioUnavailable = previewTurns.some(
    (turn) => turn.generation_status === "final_ready" && !turn.audio_ready,
  );
  const needsAttention = previewTurns.some((turn) =>
    Boolean(turn.safe_error_code),
  );
  const participantNames = new Map(
    detail.participants.map((participant) => [
      participant.id,
      participant.agent_name,
    ]),
  );
  const turns = [...previewTurns].sort(
    (left, right) => left.turn_index - right.turn_index,
  );

  return (
    <div className={styles.page} data-testid="debate-preview">
      <div className={styles.header}>
        <div>
          <div className="eyebrow">Preview</div>
          <h1>{detail.topic}</h1>
        </div>
        <div className={styles.headerActions}>
          {actions}
          {backHref ? (
            <Link className="secondary-action" href={backHref}>
              {backLabel}
            </Link>
          ) : null}
          {progress.ready ? (
            <Link className="primary-action" href={openClassroomHref}>
              Open Classroom
            </Link>
          ) : null}
        </div>
      </div>

      {error ? <ErrorNotice error={error} /> : null}

      <SectionCard className={styles.progressCard} title="Preview progress">
        <div className={styles.progressLine}>
          <strong>
            {progress.prepared_turns} / {progress.expected_turns} turns ready
          </strong>
          <span>
            {progress.ready
              ? "Ready for classroom"
              : audioUnavailable
                ? "Audio unavailable"
                : needsAttention
                  ? "Needs attention"
                  : "Preparing"}
          </span>
        </div>
        <div
          aria-label="Preview progress"
          aria-valuemax={progress.expected_turns}
          aria-valuemin={0}
          aria-valuenow={progress.prepared_turns}
          className={styles.progressTrack}
          role="progressbar"
        >
          <span
            style={{
              width: `${progress.expected_turns > 0 ? Math.min(100, (progress.prepared_turns / progress.expected_turns) * 100) : 0}%`,
            }}
          />
        </div>
      </SectionCard>

      {turns.length === 0 ? (
        <SectionCard>
          <p className={styles.empty}>No saved turns yet.</p>
        </SectionCard>
      ) : (
        <div className={styles.turns}>
          {turns.map((turn) => (
            <PreviewTurnCard
              key={turn.id}
              participantName={
                participantNames.get(turn.participant_id) ?? "Agent"
              }
              retryBusy={retryingTurnId !== null}
              retrying={retryingTurnId === turn.id}
              turn={turn}
              onRetry={onRetryTurn}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function PreviewTurnCard({
  turn,
  participantName,
  retryBusy,
  retrying,
  onRetry,
}: {
  turn: DebatePreviewTurn;
  participantName: string;
  retryBusy: boolean;
  retrying: boolean;
  onRetry?: (turnId: string) => void;
}) {
  const failed =
    turn.generation_status === "failed" || Boolean(turn.safe_error_code);
  const savedSpeech = Boolean(turn.speech.trim());
  return (
    <article
      className={styles.turnCard}
      data-testid={`preview-turn-${turn.id}`}
    >
      <div className={styles.turnHeader}>
        <div>
          <span className={styles.turnRound}>Round {turn.round_no}</span>
          <h2>{participantName}</h2>
        </div>
        <div className={styles.turnStatus}>
          <StatusBadge
            status={failed ? "failed" : savedSpeech ? "Saved" : "preparing"}
            tone={failed ? "bad" : savedSpeech ? "good" : "warn"}
          />
          <span
            className={
              turn.audio_ready ? styles.audioReady : styles.audioPending
            }
          >
            {turn.audio_ready ? "Audio ready" : "Audio not ready"}
          </span>
        </div>
      </div>

      {savedSpeech ? (
        <p className={styles.speech}>{turn.speech}</p>
      ) : (
        <p className={styles.missingSpeech}>Speech is not available yet.</p>
      )}

      {failed ? (
        <div className={styles.errorRow} role="status">
          <span>
            {savedSpeech ? "Audio needs attention." : "Speech needs attention."}
          </span>
          {onRetry ? (
            <button
              className="secondary-action"
              disabled={retryBusy}
              onClick={() => onRetry(turn.id)}
              type="button"
            >
              {retrying ? "Retrying…" : "Retry turn"}
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
      <summary>Check RAG</summary>
      <div className={styles.segmentList}>
        {segments.map((segment, index) => (
          <div className={styles.segment} key={`${index}-${segment.text}`}>
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
      turn.generation_status !== "pending" && Boolean(turn.speech.trim()),
  ).length;
  return {
    prepared_turns: prepared,
    expected_turns: expected,
    ready:
      expected > 0 &&
      prepared === expected &&
      turns.every((turn) => turn.audio_ready),
  };
}
