"use client";

import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";

import {
  EvidenceTraceInspector,
  SegmentRagInspector,
  type SegmentRagSegment,
  type SegmentRagSource,
} from "../../evidence";
import defaultStyles from "./debate-stage.module.css";
import replyStyles from "./speech-stream.module.css";
import { useT } from "../../../lib/i18n";
import type { PlaybackStageLabels } from "./types";

/** One published turn, in the shape the stream needs to render it. */
export type StreamTurn = {
  id: string;
  participant_id: string;
  round_no: number;
  speech: string;
  audio_ready?: boolean | null;
  evidence_trace?: unknown;
  sources?: { source_filename: string; chunk_id?: string | null }[];
  segment_turn?: {
    schema_version: "segment_turn_v2";
    segments: readonly SegmentRagSegment[];
  } | null;
  source_details?: readonly SegmentRagSource[];
  playback_resource?: { playback_url: string } | null;
};

type SpeechStreamProps = {
  styles?: Record<string, string>;
  turns: StreamTurn[];
  labels: PlaybackStageLabels;
  /** Slot letter and Agent name for a participant id. */
  describe: (participantId: string) => { slot: string; name: string };
  /** Phase caption for a turn, or null when the RuleSet has none. */
  phaseOf: (turn: StreamTurn) => string | null;
  emptyMessage: string;
  /** The lesson's state, shown with the heading rather than in a pill of its own. */
  status?: string;
  showTurnCount?: boolean;
  headerAction?: ReactNode;
  /** Replay the whole session, when the viewer may control playback. */
  onReplayAll?: () => void;
  replayAllDisabled?: boolean;
  activeReveal?: { turnId: string; progress: number } | null;
};

/**
 * How long a newly published speech takes to type out, end to end.
 *
 * A fixed characters-per-tick rate made the reveal as long as the speech: an
 * 800-character turn took over four seconds to finish appearing, so the room
 * waited on an animation after the words were already available. Budgeting a
 * duration instead keeps a short turn from flashing past and a long one from
 * outstaying the moment it is meant to mark.
 */
const TYPE_TOTAL_MS = 1200;
const TYPE_TICK_MS = 16;
const TYPE_MIN_CHARS_PER_TICK = 2;

function charsPerTick(length: number): number {
  const ticks = Math.max(1, Math.round(TYPE_TOTAL_MS / TYPE_TICK_MS));
  return Math.max(TYPE_MIN_CHARS_PER_TICK, Math.ceil(length / ticks));
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Reveal a speech progressively, but only the first time it arrives.
 *
 * A speech already on screen when the page loads appears in full. This is the
 * fallback for views without an audio timeline; the Beta stage supplies one.
 */
function useTypedSpeech(speech: string, animate: boolean): string {
  // Decided once, at mount: a viewer who prefers reduced motion never sees a
  // partial speech, and this keeps the decision out of an effect.
  const [reduced] = useState(prefersReducedMotion);
  const shouldType = animate && !reduced;
  const [typed, setTyped] = useState("");

  useEffect(() => {
    // The non-animating case is derived below rather than pushed into state,
    // so this effect never sets state on a render it did not cause.
    if (!shouldType) return;
    let index = 0;
    const step = charsPerTick(speech.length);
    const timer = window.setInterval(() => {
      index += step;
      if (index >= speech.length) {
        setTyped(speech);
        window.clearInterval(timer);
        return;
      }
      setTyped(speech.slice(0, index));
    }, TYPE_TICK_MS);
    return () => window.clearInterval(timer);
  }, [speech, shouldType]);

  return shouldType ? typed : speech;
}

function StreamItem({
  styles,
  turn,
  labels,
  describe,
  phaseOf,
  animate,
  revealProgress,
}: {
  styles: Record<string, string>;
  turn: StreamTurn;
  labels: PlaybackStageLabels;
  describe: SpeechStreamProps["describe"];
  phaseOf: SpeechStreamProps["phaseOf"];
  animate: boolean;
  revealProgress: number | null;
}) {
  const replyLabel = "In reply to a classroom message";
  const segments = turn.segment_turn?.segments ?? [];
  const hasStructuredRag =
    segments.length > 0 || (turn.source_details?.length ?? 0) > 0;
  const shown = useTypedSpeech(
    turn.speech,
    animate && !hasStructuredRag && revealProgress === null,
  );
  const progress =
    revealProgress === null || !Number.isFinite(revealProgress)
      ? null
      : Math.max(0, Math.min(1, revealProgress));
  const speechPoints = Array.from(turn.speech);
  const shownSpeech =
    progress === null
      ? shown
      : speechPoints
          .slice(0, Math.ceil(speechPoints.length * progress))
          .join("");
  const segmentLength = segments.reduce(
    (total, segment) => total + Array.from(segment.text).length,
    0,
  );
  const visibleSegmentChars = Math.ceil(segmentLength * (progress ?? 1));
  const who = describe(turn.participant_id);
  const phase = phaseOf(turn);
  return (
    <article className={styles.streamItem}>
      <div className={styles.streamItemTop}>
        <span className={styles.streamWho}>
          {who.slot ? `${who.slot} · ` : ""}
          {who.name}
        </span>
        <span className={styles.streamMeta}>
          {labels.round} {turn.round_no}
          {phase ? ` · ${phase}` : ""}
        </span>
      </div>
      {segments.length > 0 ? (
        <div className={styles.streamParagraphs}>
          {segments.map((segment, index) => {
            const points = Array.from(segment.text);
            const preceding = segments
              .slice(0, index)
              .reduce((total, item) => total + Array.from(item.text).length, 0);
            const visible = points
              .slice(0, Math.max(0, visibleSegmentChars - preceding))
              .join("");
            return visible ? (
              <Fragment key={`${turn.id}-segment-${index}`}>
                {segment.reply_to && segment.reply_text ? (
                  <blockquote
                    className={replyStyles.replyQuote}
                    aria-label={replyLabel}
                  >
                    <span className={replyStyles.replyLabel}>{replyLabel}</span>
                    <p>{segment.reply_text}</p>
                  </blockquote>
                ) : null}
                <p className={styles.streamSpeech}>{visible}</p>
              </Fragment>
            ) : null;
          })}
        </div>
      ) : (
        <p className={styles.streamSpeech}>
          {shownSpeech}
          {shownSpeech.length < turn.speech.length ? (
            <span aria-hidden="true" className={styles.caret} />
          ) : null}
        </p>
      )}
      {hasStructuredRag ? (
        <SegmentRagInspector
          segments={segments}
          sources={turn.source_details ?? []}
        />
      ) : (
        <>
          <EvidenceTraceInspector
            speech={turn.speech}
            trace={turn.evidence_trace as never}
          />
          {/* Which snapshot files backed this speech. It belongs with the
              speech it justifies, and merging the two panels must not quietly
              drop it. */}
          <p className={styles.streamSources}>
            <span className={styles.streamSourcesLabel}>{labels.sources}:</span>{" "}
            {turn.sources && turn.sources.length > 0
              ? turn.sources.map((source) => source.source_filename).join(", ")
              : labels.noSources}
          </p>
        </>
      )}
    </article>
  );
}

/**
 * The single place a classroom reads what was said.
 *
 * The stage used to show the current speech in one panel and the published
 * transcript in another, so the newest turn was on screen twice and the panel
 * sat blank whenever nothing was playing. One stream that grows downward keeps
 * the room looking in one place.
 */
export function SpeechStream({
  styles = defaultStyles,
  turns,
  labels,
  describe,
  phaseOf,
  emptyMessage,
  status,
  showTurnCount = true,
  headerAction,
  onReplayAll,
  replayAllDisabled,
  activeReveal,
}: SpeechStreamProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const seenRef = useRef<Set<string> | null>(null);
  const latestId = turns.length ? turns[turns.length - 1].id : null;
  // Which speech is mid-reveal is state, not a ref read during render: the
  // first render after a turn arrives is what starts its animation.
  const [typingId, setTypingId] = useState<string | null>(null);

  useEffect(() => {
    // The turns present on the first render are history and appear in full.
    if (seenRef.current === null) {
      seenRef.current = new Set(turns.map((turn) => turn.id));
      return;
    }
    const seen = seenRef.current;
    const arrived = turns.filter((turn) => !seen.has(turn.id));
    for (const turn of arrived) seen.add(turn.id);
    if (arrived.length) setTypingId(arrived[arrived.length - 1].id);
  }, [turns]);

  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [latestId]);

  return (
    <section className={styles.streamCard} aria-live="polite">
      <div className={styles.streamHeader}>
        {/* The heading says what this is and where the lesson stands, so the
            state is read in the place the room is already looking rather than
            in a separate pill under the face. */}
        <h2>
          {labels.transcript}
          {status ? (
            <>
              {" "}
              <span className={styles.streamState}>{status}</span>
            </>
          ) : null}
        </h2>
        {showTurnCount && turns.length ? (
          <span className={styles.streamCount}>{turns.length}</span>
        ) : null}
        {headerAction}
        {onReplayAll ? (
          // Replaying the whole session is a review action, not one of the
          // three controls that drive a live lesson, so it sits with the
          // speeches it replays rather than beside Start and Next.
          <button
            className={styles.streamReplayAll}
            disabled={replayAllDisabled}
            onClick={onReplayAll}
            type="button"
          >
            {labels.replayAll}
          </button>
        ) : null}
      </div>
      {turns.length === 0 ? (
        <p className={styles.streamEmpty}>{emptyMessage}</p>
      ) : (
        <div className={styles.streamList} data-stream-list="" ref={listRef}>
          {turns.map((turn) => (
            <StreamItem
              styles={styles}
              animate={turn.id === typingId}
              describe={describe}
              key={turn.id}
              labels={labels}
              phaseOf={phaseOf}
              revealProgress={
                activeReveal?.turnId === turn.id ? activeReveal.progress : null
              }
              turn={turn}
            />
          ))}
        </div>
      )}
    </section>
  );
}
