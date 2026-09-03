"use client";

import { useEffect, useRef, useState } from "react";

import { EvidenceTraceInspector } from "../../evidence";
import styles from "./debate-stage.module.css";
import type { PlaybackStageLabels } from "./types";

/** One published turn, in the shape the stream needs to render it. */
export type StreamTurn = {
  id: string;
  participant_id: string;
  round_no: number;
  speech: string;
  evidence_trace?: unknown;
  sources?: { source_filename: string; chunk_id?: string | null }[];
  playback_resource?: { playback_url: string } | null;
};

type SpeechStreamProps = {
  turns: StreamTurn[];
  labels: PlaybackStageLabels;
  /** Slot letter and Agent name for a participant id. */
  describe: (participantId: string) => { slot: string; name: string };
  /** Phase caption for a turn, or null when the RuleSet has none. */
  phaseOf: (turn: StreamTurn) => string | null;
  emptyMessage: string;
  /** Replay the whole session, when the viewer may control playback. */
  onReplayAll?: () => void;
  replayAllDisabled?: boolean;
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
 * A speech already on screen when the page loads appears in full: making a
 * teacher watch history retype before they can read it would be theatre, not
 * information. The animation is a fixed-speed visual effect and is deliberately
 * not tied to the audio timeline, which pauses, seeks and replays.
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
  turn,
  labels,
  describe,
  phaseOf,
  animate,
}: {
  turn: StreamTurn;
  labels: PlaybackStageLabels;
  describe: SpeechStreamProps["describe"];
  phaseOf: SpeechStreamProps["phaseOf"];
  animate: boolean;
}) {
  const shown = useTypedSpeech(turn.speech, animate);
  const who = describe(turn.participant_id);
  const phase = phaseOf(turn);
  const audioUrl = turn.playback_resource?.playback_url ?? null;
  const reviewRef = useRef<HTMLAudioElement | null>(null);
  return (
    <article className={styles.streamItem}>
      <div className={styles.streamItemTop}>
        <span className={styles.streamWho}>
          {who.slot} · {who.name}
        </span>
        <span className={styles.streamMeta}>
          {labels.round} {turn.round_no}
          {phase ? ` · ${phase}` : ""}
        </span>
        {audioUrl ? (
          // Review playback uses its own element. The classroom audio is
          // driven by server media commands and reports its cursor back;
          // replaying a past speech through it would desynchronise that.
          <button
            aria-label={`${labels.replayTurn ?? "Replay"} — ${who.name}`}
            className={styles.streamReplay}
            onClick={() => {
              const element = reviewRef.current;
              if (!element) return;
              element.src = audioUrl;
              element.currentTime = 0;
              void element.play().catch(() => undefined);
            }}
            type="button"
          >
            ↻
          </button>
        ) : null}
      </div>
      <p className={styles.streamSpeech}>
        {shown}
        {shown.length < turn.speech.length ? (
          <span aria-hidden="true" className={styles.caret} />
        ) : null}
      </p>
      <EvidenceTraceInspector
        speech={turn.speech}
        trace={turn.evidence_trace as never}
      />
      {/* Which snapshot files backed this speech. It belongs with the speech
          it justifies, and merging the two panels must not quietly drop it. */}
      <div className={styles.streamSources}>
        <h3>{labels.sources}</h3>
        {turn.sources && turn.sources.length > 0 ? (
          <ul>
            {turn.sources.map((source) => (
              <li
                key={`${turn.id}:${source.source_filename}:${source.chunk_id ?? ""}`}
              >
                {source.source_filename}
              </li>
            ))}
          </ul>
        ) : (
          <p>{labels.noSources}</p>
        )}
      </div>
      {audioUrl ? <audio preload="none" ref={reviewRef} /> : null}
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
  turns,
  labels,
  describe,
  phaseOf,
  emptyMessage,
  onReplayAll,
  replayAllDisabled,
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
        <h2>{labels.transcript}</h2>
        {turns.length ? (
          <span className={styles.streamCount}>{turns.length}</span>
        ) : null}
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
        <div className={styles.streamList} ref={listRef}>
          {turns.map((turn) => (
            <StreamItem
              animate={turn.id === typingId}
              describe={describe}
              key={turn.id}
              labels={labels}
              phaseOf={phaseOf}
              turn={turn}
            />
          ))}
        </div>
      )}
    </section>
  );
}
