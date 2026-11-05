"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useT } from "../../../lib/i18n";
import { teachingRoundLabel } from "../../../lib/debate-rounds";
import type { SegmentEvidence } from "../../../lib/evidence-grading";
import { SegmentGrade } from "../../evidence/segment-grade";

import { ErrorNotice, Notice, RetryPill } from "../../ui";
import { statusLabel, tm } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { buttonVariants } from "../../ui/button";
import { IconBust, IconEye, IconPlay } from "../../quiet-icons";
import {
  DEBATE_BUTTON,
  DEBATE_PAGE,
  DEBATE_PRIMARY,
  DEBATE_TAG,
  DEBATE_TAG_TONE,
  PREVIEW_TAPE,
  PREVIEW_TONES,
  PREVIEW_TURN,
  PREVIEW_TURN_PENDING,
} from "../debate-chrome";

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
  onRetryTurn?: (turnIds: string[]) => void;
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

  const tones = new Map(
    detail.participants.map((participant, index) => [
      participant.id,
      PREVIEW_TONES[index % PREVIEW_TONES.length],
    ]),
  );
  const perFighter = Math.max(
    1,
    Math.ceil(
      progress.expected_turns / Math.max(1, detail.participants.length),
    ),
  );
  const percent =
    progress.expected_turns > 0
      ? Math.min(100, (progress.prepared_turns / progress.expected_turns) * 100)
      : 0;

  return (
    <div className={DEBATE_PAGE}>
      <div className={PREVIEW_TAPE} data-testid="debate-preview">
        <div className="flex items-center gap-4 max-[600px]:flex-wrap">
          <h1 className="m-0 max-w-none min-w-0 flex-1 font-display text-[26px] leading-[normal] font-bold max-[600px]:text-xl">
            {detail.topic}
          </h1>
          {actions}
          {progress.ready ? (
            <Link
              className={cn(
                buttonVariants({ variant: "default" }),
                DEBATE_PRIMARY,
                "py-3 pr-[22px] pl-4 text-base leading-[normal]",
              )}
              href={openClassroomHref}
            >
              <IconPlay size={18} />
              Immerse
            </Link>
          ) : null}
        </div>

        {detail.participants.length > 0 ? (
          <div className="mt-4 grid grid-cols-3 gap-3 max-[600px]:grid-cols-1">
            {detail.participants.map((participant) => {
              const done = turns.filter(
                (turn) =>
                  turn.participant_id === participant.id && turnPrepared(turn),
              ).length;
              return (
                <div
                  key={participant.id}
                  className="flex min-w-0 items-center gap-2.5 rounded-full border-[2.5px] border-[#111] bg-(--tone) py-1.5 pr-4 pl-1.5 shadow-[3px_4px_0_#111]"
                  style={
                    {
                      "--tone": tones.get(participant.id),
                    } as React.CSSProperties
                  }
                >
                  <span
                    className="box-border grid size-11 flex-none place-items-end-center overflow-hidden rounded-full border-[2.5px] border-[#111] bg-white [&_svg]:w-[34px]"
                    aria-hidden="true"
                  >
                    <IconBust size={34} />
                  </span>
                  <div className="min-w-0 font-body text-base leading-[normal]">
                    <b className="font-body text-[15px] leading-[normal] font-extrabold">
                      {participant.agent_name}
                    </b>
                    <div className="mt-[5px] flex gap-[3px]" aria-hidden="true">
                      {Array.from({ length: perFighter }, (_, index) => (
                        <i
                          key={index}
                          className={cn(
                            "box-border size-[11px] rounded-full border-2 border-[#111]",
                            index < done ? "bg-[#111]" : "bg-white",
                          )}
                        />
                      ))}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}

        <div className="mt-4 flex justify-center" aria-hidden="true">
          <div className="relative box-border h-3.5 w-full overflow-hidden rounded-full border-[2.5px] border-[#111] bg-white">
            <i
              className="absolute inset-y-0 left-0 rounded-full bg-[#67E8F9]"
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>

        {error ? (
          <div className="mt-4">
            <ErrorNotice error={error} />
          </div>
        ) : null}

        {firstFailed ? (
          <div className="mt-4">
            <Notice
              inline
              tone="error"
              action={
                onRetryTurn ? (
                  <RetryPill
                    data-testid="preview-audio-failed-retry"
                    disabled={retryingTurnId !== null}
                    onClick={() =>
                      onRetryTurn(audioFailed.map((turn) => turn.id))
                    }
                  >
                    Retry
                  </RetryPill>
                ) : null
              }
            >
              <span data-testid="preview-audio-failed">
                {tm("debatePreviewAudioFailed", {
                  count: audioFailed.length,
                  code: firstFailed.safe_error_code ?? "turn_generation_failed",
                })}
              </span>
            </Notice>
          </div>
        ) : null}

        <div className="mt-4 grid gap-3">
          {background ? <BackgroundCard text={background} /> : null}
          {turns.length === 0 ? (
            <p className="m-0 font-body text-sm text-[#6B7280]">
              No saved turns yet.
            </p>
          ) : null}
          {turns.map((turn) => (
            <PreviewTurnCard
              key={turn.id}
              participantName={
                participantNames.get(turn.participant_id) ?? "Agent"
              }
              pendingShimmer={!progress.ready}
              retryBusy={retryingTurnId !== null}
              retrying={retryingTurnId === turn.id}
              teachingProtocol={detail.teaching_protocol === "four_round_v1"}
              tone={tones.get(turn.participant_id) ?? PREVIEW_TONES[0]}
              turn={turn}
              onRetry={
                onRetryTurn
                  ? (turnId) => onRetryTurn([turnId])
                  : undefined
              }
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function BackgroundCard({ text }: { text: string }) {
  return (
    <article
      className="rounded-[18px] border-[2.5px] border-[#111] bg-[#FFF7CC] px-3.5 py-3"
      data-testid="preview-background"
    >
      <h2 className="m-0 font-display text-[15px] leading-[normal] font-bold">
        Background
      </h2>
      <p className="mt-1 mb-0 font-body text-sm leading-[normal]">{text}</p>
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
  tone,
  pendingShimmer,
}: {
  tone: string;
  pendingShimmer: boolean;
  turn: DebatePreviewTurn;
  participantName: string;
  retryBusy: boolean;
  retrying: boolean;
  onRetry?: (turnId: string) => void;
  teachingProtocol?: boolean;
}) {
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
  const tagTone = turn.audio_ready ? "ready" : failed ? "stalled" : "thinking";
  return (
    <article
      className={cn(
        PREVIEW_TURN,
        pendingShimmer && !savedSpeech && PREVIEW_TURN_PENDING,
      )}
      style={{ "--tone": tone } as React.CSSProperties}
      data-testid={`preview-turn-${turn.id}`}
    >
      <div className="flex items-center gap-2.5">
        <span className="rounded-full border-2 border-[#111] bg-(--tone) px-[7px] py-0.5 font-body text-[11px] leading-[normal] font-extrabold text-[#111]">
          Round {turn.round_no}
          {teachingProtocol
            ? ` · ${teachingRoundLabel(turn.round_no, "en")}`
            : ""}
        </span>
        <h2 className="m-0 min-w-0 font-display text-base leading-[normal] font-bold">
          {participantName}
        </h2>
        <span
          className={cn(
            DEBATE_TAG,
            DEBATE_TAG_TONE[tagTone],
            "ml-auto px-[9px]",
            pendingShimmer && tagTone === "thinking" && "bg-[#FEF9C3]",
          )}
        >
          {statusLabel(
            turn.audio_ready
              ? "Audio Ready"
              : failed
                ? "Audio Not Ready"
                : "Preparing",
          )}
        </span>
      </div>

      {savedSpeech ? (
        <p className="mt-1.5 mb-0 font-body text-sm leading-[1.5]">
          {turn.speech}
        </p>
      ) : (
        <p className="mt-1.5 mb-0 font-body text-sm leading-[1.5] text-[#6B7280] italic">
          Speech is not available yet.
        </p>
      )}

      {failed ? (
        <div
          className="mt-2 flex items-center gap-2.5 rounded-[14px] border-2 border-[#111] bg-[#FFE4E4] px-2 py-1.5 font-body text-[13px] leading-[normal] font-medium"
          role="status"
          data-text-fallback-ready={textFallbackReady ? "true" : "false"}
        >
          <span>
            {savedSpeech ? "Audio needs attention." : "Speech needs attention."}
          </span>
          {turn.safe_error_code ? (
            <code
              className="font-mono text-xs font-bold text-[#B91C1C]"
              data-testid="preview-safe-error-code"
            >
              {turn.safe_error_code}
            </code>
          ) : null}
          {onRetry ? (
            <RetryPill
              className="ml-auto text-xs"
              aria-label={retrying ? "Retrying…" : "Retry turn"}
              aria-busy={retrying}
              disabled={retryBusy}
              onClick={() => onRetry(turn.id)}
            >
              {retrying ? "Retrying…" : "Retry turn"}
            </RetryPill>
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
    <details className="mt-2.5 border-0 border-t-2 border-dashed border-[#111] pt-2.5 font-body [&_summary]:min-h-0 [&_summary]:p-0">
      <summary
        className={cn(
          DEBATE_BUTTON,
          "list-none py-1 pr-2.5 pl-2 text-xs leading-[normal] [&::-webkit-details-marker]:hidden",
        )}
        data-testid="preview-check-rag"
      >
        <IconEye size={18} />
        <span>Check RAG</span>
        <span className="ml-0.5 inline-grid h-[1.35rem] min-w-[1.35rem] place-items-center rounded-full border-2 border-[#111] bg-[#FFE14D] text-[11px] font-extrabold">
          {sourceById.size}
        </span>
      </summary>
      <div className="mt-2.5 grid gap-2.5">
        {segments.map((segment, index) => (
          <div
            className="grid min-w-0 gap-2 border-0 border-l-[3px] border-[#FFE14D] pl-2.5"
            key={`${index}-${segment.text}`}
          >
            <SegmentGrade segment={segment} />
            <p className="m-0 text-sm leading-[1.5] [overflow-wrap:anywhere] whitespace-pre-wrap">
              {segment.text}
            </p>
            <div className="grid gap-2">
              {segment.source_ids.length === 0 ? (
                <span className="text-[13px] text-[#6B7280]">
                  General reasoning
                </span>
              ) : (
                segment.source_ids.map((sourceId) => {
                  const source = sourceById.get(sourceId);
                  return source ? (
                    // Folded (2026-11-03): the document first, its query
                    // and text on a second click, as in chat.
                    <details
                      className="grid min-w-0 gap-0.5 rounded-[12px] border-2 border-[#111] bg-[#F1F7FF] p-2.5 [&>*]:[overflow-wrap:anywhere]"
                      key={sourceId}
                    >
                      <summary className="cursor-pointer">
                        <strong>{source.source_filename}</strong>
                      </summary>
                      <span className="mt-1 block text-[13px] text-[#6B7280]">
                        {source.version_label} · query:{" "}
                        {source.query_text ?? "none recorded"}
                      </span>
                      <small className="block text-[13px] leading-[1.45] whitespace-pre-wrap text-[#6B7280]">
                        {source.excerpt}
                      </small>
                    </details>
                  ) : (
                    <span className="text-[13px] text-[#6B7280]" key={sourceId}>
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

function turnPrepared(turn: DebatePreviewTurn): boolean {
  return (
    ["final_ready", "ready", "completed"].includes(turn.generation_status) &&
    Boolean(turn.speech.trim())
  );
}

function deriveProgress(
  turns: readonly DebatePreviewTurn[],
): DebatePreviewProgress {
  const expected = turns.length;
  const prepared = turns.filter(turnPrepared).length;
  return {
    prepared_turns: prepared,
    expected_turns: expected,
    ready: expected > 0 && prepared === expected,
  };
}
