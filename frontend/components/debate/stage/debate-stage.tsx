"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type SyntheticEvent,
} from "react";

import { DismissibleAlert } from "../../dismissible-alert";
import type {
  DebateDetail,
  DebatePlaybackState,
  DebateTurn,
  IdempotencyHandle,
  ProviderDataCallManifestListResponse,
} from "../../../lib/api";
import { createIdempotencyHandle } from "../../../lib/api";
import { markDebateNextClicked } from "../../../lib/client-metrics";
import { SpeechStream, type StreamTurn } from "./speech-stream";
import { expectedTurnCount } from "../../../lib/debate-rounds";
import {
  AvatarPreview,
  AVATAR_EXPRESSIONS,
  AVATAR_EXPRESSION_STRENGTHS,
  AVATAR_STATES,
  type AvatarExpression,
  type AvatarState,
} from "../../avatar";
import styles from "./debate-stage.module.css";
import {
  phaseLabel,
  resolveDebateRoundPhase,
  resolvePlaybackStageLabels,
} from "./labels";
import { useImmerseAudioQueue } from "./next-audio-prefetch";
import {
  connectionIssueFromCloseCode,
  consumeEventSequence,
  debateSocketUrl,
  deriveAvatarStates,
  isSafeMediaUrl,
  parsePlaybackEvent,
  parsePrivatePlaybackMessage,
  normaliseVisiblePlaybackTurns,
  publicTurnById,
  visibleTurnFromPlaybackStarted,
} from "./protocol";
import type {
  AvatarVisualState,
  ClassroomPhase,
  DebateStageProps,
  PlaybackAction,
  PlaybackConnectionIssue,
  PlaybackConnectionState,
  PlaybackEvent,
  PlaybackSocket,
  PrivatePlaybackMessage,
  VisiblePlaybackTurn,
} from "./types";

type ControlAction = "start" | "next" | "replay" | "pause" | "resume";

function atFinalBoundary(
  detail: DebateDetail,
  playback: DebatePlaybackState,
): boolean {
  return (
    detail.turn_protocol === "segments_v2" &&
    playback.mode === "live" &&
    detail.public_turns.find((turn) => turn.id === playback.current_turn_id)
      ?.turn_index ===
      detail.participants.length * (detail.round_count - 1) - 1
  );
}

type ProviderGateState = {
  code: "provider_confirmation_required" | "provider_not_sent";
  loading: boolean;
  value: ProviderDataCallManifestListResponse | null;
  error: string | null;
  selectedManifestHash: string | null;
};

function visibleRoundPhase(
  turn: VisiblePlaybackTurn | null,
  detail: DebateDetail,
): ReturnType<typeof resolveDebateRoundPhase> | null {
  if (!turn) return null;
  const explicit = (turn as VisiblePlaybackTurn & { phase?: unknown }).phase;
  if (
    explicit === "opening" ||
    explicit === "exchange" ||
    explicit === "final_integration"
  ) {
    return explicit;
  }
  const roundCount = (detail as DebateDetail & { round_count?: unknown })
    .round_count;
  if (typeof roundCount !== "number" || !Number.isInteger(roundCount)) {
    return null;
  }
  return resolveDebateRoundPhase(turn.round_no, turn.round_no === roundCount);
}

const TERMINAL_PLAYBACK: readonly DebatePlaybackState["status"][] = [
  "completed",
  "stopped",
];

function isTerminalConnectionContext(
  detail: Pick<DebateDetail, "status" | "playback">,
): boolean {
  return (
    detail.status === "stopped" ||
    (detail.status === "completed" && detail.playback.mode !== "replay") ||
    (detail.playback.mode !== "replay" &&
      TERMINAL_PLAYBACK.includes(detail.playback.status))
  );
}

function isProductTerminalDetail(
  detail: Pick<DebateDetail, "status" | "playback">,
): boolean {
  if (detail.status === "failed" || detail.status === "stopped") return true;
  if (detail.status === "debate_finished" || detail.status === "completed") {
    // A retained Replay remains an active controller surface even though its
    // source Debate is finished. Its ordinary live terminal view does not.
    return detail.playback.mode !== "replay";
  }
  return (
    detail.playback.mode === "live" &&
    TERMINAL_PLAYBACK.includes(detail.playback.status)
  );
}

function hasReplayableSegmentAudio(
  detail: Pick<DebateDetail, "turn_protocol" | "public_turns">,
): boolean {
  if (detail.turn_protocol !== "segments_v2") return false;
  const turns = normalisePublicTurns(detail.public_turns);
  return (
    detail.public_turns.length > 0 &&
    turns.length === detail.public_turns.length &&
    turns.every((turn) => turn.audio_ready === true)
  );
}

function replayAudioAvailable(
  detail: Pick<DebateDetail, "turn_protocol" | "public_turns">,
  audioPointer: string | null | undefined,
  debateId: string,
): boolean {
  return detail.turn_protocol === "segments_v2"
    ? hasReplayableSegmentAudio(detail)
    : audioPointer === debateId;
}

function isReplayableTerminalSource(
  detail: Pick<
    DebateDetail,
    "status" | "playback" | "public_turns" | "turn_protocol"
  >,
  audioPointer: string | null | undefined,
  debateId: string,
): boolean {
  return (
    replayAudioAvailable(detail, audioPointer, debateId) &&
    detail.public_turns.length > 0 &&
    (detail.status === "debate_finished" || detail.status === "completed") &&
    detail.playback.mode === "live" &&
    detail.playback.status === "completed"
  );
}
function makeId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (typeof globalThis.crypto?.getRandomValues === "function") {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex
    .slice(6, 8)
    .join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function integer(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value)
    ? value
    : fallback;
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function isAvatarState(value: unknown): value is AvatarState {
  return (
    typeof value === "string" &&
    (AVATAR_STATES as readonly string[]).includes(value)
  );
}

function isAvatarExpression(value: unknown): value is AvatarExpression {
  return (
    typeof value === "string" &&
    (AVATAR_EXPRESSIONS as readonly string[]).includes(value)
  );
}

function isDebateStatus(value: unknown): value is DebateDetail["status"] {
  return (
    value === "draft" ||
    value === "running" ||
    value === "debate_finished" ||
    value === "completed" ||
    value === "failed" ||
    value === "stopped"
  );
}

function isPlaybackStatus(
  value: unknown,
): value is DebatePlaybackState["status"] {
  return (
    value === "preparing" ||
    value === "ready" ||
    value === "playing" ||
    value === "paused" ||
    value === "waiting_next" ||
    value === "completed" ||
    value === "stopped"
  );
}

function isPlaybackMode(value: unknown): value is DebatePlaybackState["mode"] {
  return value === "live" || value === "replay";
}

const CURRENT_ITEM_EVENT_TYPES = new Set<PlaybackEvent["event_type"]>([
  "playback.paused",
  "playback.resumed",
  "playback.skipped",
  "playback.completed",
]);

function isCurrentItemEvent(
  event: PlaybackEvent,
  currentTurnId: string | null,
): boolean {
  if (!CURRENT_ITEM_EVENT_TYPES.has(event.event_type)) return true;
  const eventTurnId = event.payload.turn_id;
  return isNonEmptyString(eventTurnId) && eventTurnId === currentTurnId;
}

function hasStaleControlVersion(
  event: PlaybackEvent,
  currentControlVersion: number,
): boolean {
  if (
    event.event_type !== "playback.paused" &&
    event.event_type !== "playback.resumed" &&
    event.event_type !== "playback.skipped" &&
    event.event_type !== "playback.completed" &&
    event.event_type !== "playback.waiting_next" &&
    event.event_type !== "replay.started"
  ) {
    return false;
  }
  const eventVersion = event.payload.control_version;
  return (
    typeof eventVersion === "number" &&
    Number.isInteger(eventVersion) &&
    eventVersion < currentControlVersion
  );
}

function normalisePublicTurns(value: unknown): VisiblePlaybackTurn[] {
  return normaliseVisiblePlaybackTurns(value);
}

function normaliseAvatarStates(value: unknown): AvatarVisualState[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isRecord(item) || !isNonEmptyString(item.participant_id)) return [];
    const motion = isAvatarState(item.motion_state)
      ? item.motion_state
      : "idle";
    const expression = isAvatarExpression(item.expression)
      ? item.expression
      : "neutral";
    const expressionStrength =
      typeof item.expression_strength === "string" &&
      (AVATAR_EXPRESSION_STRENGTHS as readonly string[]).includes(
        item.expression_strength,
      )
        ? (item.expression_strength as AvatarVisualState["expression_strength"])
        : "medium";
    const slot =
      item.slot === "A" ||
      item.slot === "B" ||
      item.slot === "C" ||
      item.slot === "D" ||
      item.slot === "E"
        ? item.slot
        : null;
    if (!slot) return [];
    return [
      {
        participant_id: item.participant_id,
        slot,
        motion_state: motion,
        expression,
        expression_strength: expressionStrength,
      },
    ];
  });
}

function playbackFromWire(
  value: unknown,
  current: DebatePlaybackState,
): DebatePlaybackState {
  if (!isRecord(value)) return current;
  const status = isPlaybackStatus(value.status) ? value.status : current.status;
  const mode = isPlaybackMode(value.mode) ? value.mode : current.mode;
  const currentTurnId = isNonEmptyString(value.current_turn_id)
    ? value.current_turn_id
    : value.current_turn_id === null
      ? null
      : (current.current_turn_id ?? null);
  return {
    status,
    mode,
    current_turn_id: currentTurnId,
    cursor_ms: Math.max(0, integer(value.cursor_ms, current.cursor_ms)),
    control_version: Math.max(
      0,
      integer(value.control_version, current.control_version),
    ),
    next_turn_ready:
      ["playing", "paused", "waiting_next"].includes(status) &&
      value.next_turn_ready === true,
  };
}

function hasCompletePublicPrefix(
  publicTurns: readonly VisiblePlaybackTurn[],
): boolean {
  if (publicTurns.length === 0) return false;
  const ordered = [...publicTurns].sort(
    (left, right) => left.turn_index - right.turn_index,
  );
  return ordered.every((turn, index) => turn.turn_index === index);
}

/**
 * Recover the browser media action from the authoritative snapshot rather
 * than from the HTTP request that may have been lost.  A waiting state does
 * not itself authorize media; it stays on the completed item until Next.
 */
function derivePendingPlaybackAction(
  playback: DebatePlaybackState,
  publicTurns: readonly VisiblePlaybackTurn[],
): PlaybackAction {
  if (playback.mode === "replay") return "replay";
  if (playback.status === "waiting_next") return "start";
  if (
    playback.current_turn_id &&
    publicTurns.some((turn) => turn.id === playback.current_turn_id)
  ) {
    return "resume";
  }
  if (
    playback.status === "ready" &&
    playback.current_turn_id &&
    hasCompletePublicPrefix(publicTurns)
  ) {
    return "next";
  }
  return "start";
}

/** The debate holding the course's running slot, if that is what failed. */
function blockingDebate(cause: unknown): { id: string; topic: string } | null {
  if (!isRecord(cause) || cause.code !== "debate_already_running") return null;
  const details = cause.details;
  if (!isRecord(details)) return null;
  const blocking = details.blocking_debate;
  if (!isRecord(blocking) || !isNonEmptyString(blocking.id)) return null;
  return {
    id: blocking.id,
    topic: isNonEmptyString(blocking.topic) ? blocking.topic : blocking.id,
  };
}

function errorText(cause: unknown, fallback: string): string {
  if (cause instanceof Error && cause.message.trim()) return cause.message;
  if (isRecord(cause) && isNonEmptyString(cause.message)) return cause.message;
  return fallback;
}

function isAuthenticationExpiredError(cause: unknown): boolean {
  return isRecord(cause) && cause.status === 401;
}

function mediaErrorCode(
  audio: HTMLAudioElement,
): "not_supported" | "decode_error" | "network_error" | "aborted" | "unknown" {
  switch (audio.error?.code) {
    case 1:
      return "aborted";
    case 2:
      return "network_error";
    case 3:
      return "decode_error";
    case 4:
      return "not_supported";
    default:
      return "unknown";
  }
}

function isNotAllowedError(cause: unknown): boolean {
  return (
    (isRecord(cause) && cause.name === "NotAllowedError") ||
    (cause instanceof Error && cause.name === "NotAllowedError")
  );
}

function socketMessageData(event: Event): unknown {
  const data = (event as MessageEvent<unknown>).data;
  if (typeof data !== "string") return data;
  try {
    return JSON.parse(data) as unknown;
  } catch {
    return null;
  }
}

/**
 * Classroom phase is a product state, not a transport-health state.  Keep the
 * two projections independent so a connected page can still be waiting, and
 * a finished page never looks disconnected just because its controller was
 * intentionally released.
 */
function deriveClassroomPhase(
  detailStatus: DebateDetail["status"],
  playbackStatus: DebatePlaybackState["status"],
  playbackMode: DebatePlaybackState["mode"],
  actionInFlight: boolean,
): ClassroomPhase {
  if (detailStatus === "draft") return "ready";
  if (detailStatus === "failed") return "failed";
  if (detailStatus === "stopped") return "stopped";
  // Replay is an active playback surface over a finished source Debate. Its
  // source status must not mask the current replay phase while a turn is
  // being prepared/played or waiting for the teacher to advance it.
  if (playbackMode === "replay") {
    if (!actionInFlight && playbackStatus === "waiting_next") {
      return "waiting";
    }
    if (playbackStatus === "stopped") return "stopped";
    return "in_progress";
  }
  if (detailStatus === "debate_finished" || detailStatus === "completed") {
    return "finished";
  }
  if (
    !actionInFlight &&
    playbackStatus === "waiting_next" &&
    (playbackMode === "live" || playbackMode === "replay")
  ) {
    return "waiting";
  }
  return "in_progress";
}

export function DebateStage({
  debateId,
  detail,
  api,
  onDetailChange,
  onAuthorityChange,
  refreshSnapshot,
  socketFactory,
  socketUrl,
  labels: suppliedLabels,
  readOnly = false,
  currentAudioDebateId,
  expectedCurrentAudioDebateId,
  onCurrentAudioDebateIdChange,
  actionInFlight = false,
  className,
  headerActions,
  outputLanguage = "en",
}: DebateStageProps) {
  const labels = useMemo(
    () => resolvePlaybackStageLabels(suppliedLabels),
    [suppliedLabels],
  );
  const [detailState, setDetailState] = useState<DebateDetail>(detail);
  const [playback, setPlayback] = useState<DebatePlaybackState>(
    detail.playback,
  );
  const [publicTurns, setPublicTurns] = useState<VisiblePlaybackTurn[]>(() =>
    normalisePublicTurns(detail.public_turns),
  );
  const [visibleTurn, setVisibleTurn] = useState<VisiblePlaybackTurn | null>(
    null,
  );
  const [avatarEventStates, setAvatarEventStates] = useState<
    AvatarVisualState[]
  >([]);
  const [connection, setConnection] =
    useState<PlaybackConnectionState>("connecting");
  const [connectionIssue, setConnectionIssueState] =
    useState<PlaybackConnectionIssue | null>(null);
  const [lastSequence, setLastSequence] = useState(detail.last_sequence);
  const [controllerReady, setControllerReady] = useState(false);
  const [activeParticipantId, setActiveParticipantId] = useState<string | null>(
    null,
  );
  const [busyAction, setBusyAction] = useState<ControlAction | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [mediaRetryNeeded, setMediaRetryNeeded] = useState(false);
  const [controlError, setControlError] = useState<string | null>(null);
  // Which debate is holding this course's running slot, when that is why a
  // command failed. Naming it here is what lets the recovery live beside the
  // failure instead of on a screen the teacher has to go find.
  const [blockedBy, setBlockedBy] = useState<{
    id: string;
    topic: string;
  } | null>(null);
  const [providerGate, setProviderGate] = useState<ProviderGateState | null>(
    null,
  );
  const [providerRetryBusy, setProviderRetryBusy] = useState(false);
  const audioPointerInput =
    currentAudioDebateId !== undefined
      ? currentAudioDebateId
      : expectedCurrentAudioDebateId;
  const detailRef = useRef(detailState);
  const playbackRef = useRef(playback);
  const publicTurnsRef = useRef(publicTurns);
  const visibleTurnRef = useRef<VisiblePlaybackTurn | null>(visibleTurn);
  const avatarEventStatesRef = useRef(avatarEventStates);
  const activeParticipantRef = useRef<string | null>(activeParticipantId);
  const sequenceRef = useRef(lastSequence);
  const socketRef = useRef<PlaybackSocket | null>(null);
  const socketCleanupRef = useRef<(() => void) | null>(null);
  const controllerEpochRef = useRef<string | null>(null);
  const controllerReadyRef = useRef(false);
  const acquirePendingRef = useRef(false);
  const controllerAcquireBlockedRef = useRef(false);
  const terminalReplayAcquirePendingRef = useRef(false);
  const connectionIssueRef = useRef<PlaybackConnectionIssue | null>(null);
  const authoritySnapshotRef = useRef({
    connection: "connecting" as PlaybackConnectionState,
    connectionIssue: null as PlaybackConnectionIssue | null,
    controllerReady: false,
    commandBusy: false,
  });
  const controlVersionRef = useRef(playback.control_version);
  const pendingActionRef = useRef<PlaybackAction>("start");
  const pendingReplayAcquireRef = useRef<{
    resolve: () => void;
    reject: (cause?: unknown) => void;
  } | null>(null);
  const mediaCommandBindingsRef = useRef(
    new Map<string, { generation: number; turnId: string; version: number }>(),
  );
  const prepareKeyRef = useRef<string | null>(null);
  const preparedMediaKeyRef = useRef<string | null>(null);
  const playbackGenerationRef = useRef(0);
  const playbackItemKeyRef = useRef(
    `${playback.mode}:${playback.current_turn_id ?? ""}`,
  );
  const mediaGenerationRef = useRef(0);
  const audioTurnRef = useRef<string | null>(null);
  const audioActionRef = useRef<PlaybackAction>("start");
  const startedAckRef = useRef(false);
  const cursorMsRef = useRef(playback.cursor_ms);
  const mountedRef = useRef(false);
  const closingRef = useRef(false);
  const replayCatalogRef = useRef<Map<string, VisiblePlaybackTurn>>(
    new Map(
      normalisePublicTurns(detail.public_turns).map((turn) => [
        turn.id,
        {
          ...turn,
          sources: turn.sources.map((source) => ({ ...source })),
        },
      ]),
    ),
  );
  const catalogDebateIdRef = useRef(debateId);
  const [reconnectBusy, setReconnectBusy] = useState(false);
  const socketGenerationRef = useRef(0);
  const connectAttemptRef = useRef(0);
  const recoveryFenceRef = useRef<{
    active: boolean;
    candidate: VisiblePlaybackTurn | null;
    generation: number;
    observedSequence: number;
    refreshInFlight: boolean;
    targetTurnId: string | null;
  }>({
    active: false,
    candidate: null,
    generation: 0,
    observedSequence: 0,
    refreshInFlight: false,
    targetTurnId: null,
  });
  const controlRequestRef = useRef<number | null>(null);
  const nextControlRequestRef = useRef(0);
  const startIdempotencyRef = useRef<IdempotencyHandle | null>(null);
  const pauseIdempotencyRef = useRef<IdempotencyHandle | null>(null);
  const resumeIdempotencyRef = useRef<IdempotencyHandle | null>(null);
  const providerRetryIdempotencyRef = useRef<{
    turnId: string;
    handle: IdempotencyHandle;
  } | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const labelsRef = useRef(labels);

  const [audioPointerOverride, setAudioPointerOverride] = useState<{
    source: string | null | undefined;
    value: string;
  } | null>(null);
  const audioPointer =
    audioPointerOverride !== null &&
    audioPointerOverride.source === audioPointerInput
      ? audioPointerOverride.value
      : audioPointerInput;

  useEffect(() => {
    if (catalogDebateIdRef.current === debateId) return;
    catalogDebateIdRef.current = debateId;
    providerRetryIdempotencyRef.current = null;
    setProviderGate(null);
    replayCatalogRef.current = new Map(
      normalisePublicTurns(detail.public_turns).map((turn) => [
        turn.id,
        {
          ...turn,
          sources: turn.sources.map((source) => ({ ...source })),
        },
      ]),
    );
  }, [debateId, detail.public_turns]);

  useEffect(() => {
    const timer = window.setTimeout(() => setAudioPointerOverride(null), 0);
    return () => window.clearTimeout(timer);
  }, [audioPointerInput]);

  const markCurrentAudioDebate = useCallback(
    (nextDebateId: string) => {
      setAudioPointerOverride({
        source: audioPointerInput,
        value: nextDebateId,
      });
      onCurrentAudioDebateIdChange?.(nextDebateId);
    },
    [audioPointerInput, onCurrentAudioDebateIdChange],
  );

  const rememberReplayCatalog = useCallback(
    (turns: readonly VisiblePlaybackTurn[]) => {
      const catalog = replayCatalogRef.current;
      for (const turn of turns) {
        // A replay catalog is immutable for the lifetime of this stage.  If a
        // later snapshot omits/clears public turns, the original speech and
        // source list remain available to replay.started.
        if (!catalog.has(turn.id)) {
          catalog.set(turn.id, {
            ...turn,
            sources: turn.sources.map((source) => ({ ...source })),
          });
        }
      }
    },
    [],
  );

  const catalogTurnById = useCallback(
    (turnId: string | null | undefined): VisiblePlaybackTurn | null => {
      if (!turnId) return null;
      const turn = replayCatalogRef.current.get(turnId);
      return turn
        ? { ...turn, sources: turn.sources.map((source) => ({ ...source })) }
        : null;
    },
    [],
  );

  const publishAuthority = useCallback(
    (patch: Partial<typeof authoritySnapshotRef.current>) => {
      const next = { ...authoritySnapshotRef.current, ...patch };
      authoritySnapshotRef.current = next;
      onAuthorityChange?.(next);
    },
    [onAuthorityChange],
  );

  const settlePendingReplayAcquire = useCallback((cause?: unknown) => {
    const pending = pendingReplayAcquireRef.current;
    if (!pending) return;
    pendingReplayAcquireRef.current = null;
    if (cause === undefined) pending.resolve();
    else pending.reject(cause);
  }, []);

  const markConnection = useCallback(
    (value: PlaybackConnectionState) => {
      setConnection(value);
      publishAuthority({ connection: value });
    },
    [publishAuthority],
  );

  const markControllerReady = useCallback(
    (value: boolean) => {
      controllerReadyRef.current = value;
      setControllerReady(value);
      publishAuthority({ controllerReady: value });
    },
    [publishAuthority],
  );

  const markConnectionIssue = useCallback(
    (value: PlaybackConnectionIssue | null) => {
      connectionIssueRef.current = value;
      setConnectionIssueState(value);
      publishAuthority({ connectionIssue: value });
    },
    [publishAuthority],
  );

  useEffect(() => {
    labelsRef.current = labels;
  }, [labels]);

  const markPlaybackItem = useCallback(
    (next: Pick<DebatePlaybackState, "mode" | "current_turn_id">) => {
      const key = `${next.mode}:${next.current_turn_id ?? ""}`;
      if (playbackItemKeyRef.current === key) return;
      playbackItemKeyRef.current = key;
      playbackGenerationRef.current += 1;
      setMediaRetryNeeded(false);
    },
    [],
  );

  const commitDetail = useCallback(
    (next: DebateDetail, notify = true) => {
      const turns = normalisePublicTurns(next.public_turns);
      rememberReplayCatalog(turns);
      const committed = {
        ...next,
        public_turns: turns as DebateTurn[],
      };
      publicTurnsRef.current = turns;
      setPublicTurns(turns);
      markPlaybackItem(committed.playback);
      pendingActionRef.current = derivePendingPlaybackAction(
        committed.playback,
        turns,
      );
      detailRef.current = committed;
      playbackRef.current = committed.playback;
      controlVersionRef.current = committed.playback.control_version;
      setDetailState(committed);
      setPlayback(committed.playback);
      if (notify) onDetailChange?.(committed);
    },
    [markPlaybackItem, onDetailChange, rememberReplayCatalog],
  );

  const updatePublicTurns = useCallback(
    (next: VisiblePlaybackTurn[]) => {
      rememberReplayCatalog(next);
      publicTurnsRef.current = next;
      setPublicTurns(next);
      const detailNext = {
        ...detailRef.current,
        public_turns: next as DebateTurn[],
      };
      detailRef.current = detailNext;
      setDetailState(detailNext);
      onDetailChange?.(detailNext);
    },
    [onDetailChange, rememberReplayCatalog],
  );

  const pauseAudio = useCallback((clearSource = false) => {
    mediaGenerationRef.current += 1;
    startedAckRef.current = false;
    const audio = audioRef.current;
    if (!audio) return;
    try {
      audio.pause();
    } catch {
      // Browsers may throw while tearing down a media element during navigation.
    }
    if (clearSource) {
      audio.removeAttribute("src");
      try {
        audio.load();
      } catch {
        // jsdom and a few embedded browsers do not implement load().
      }
      audioTurnRef.current = null;
      preparedMediaKeyRef.current = null;
      prepareKeyRef.current = null;
      cursorMsRef.current = 0;
    }
  }, []);

  const sendCommand = useCallback(
    (command: Record<string, unknown>): boolean => {
      const socket = socketRef.current;
      if (!socket) return false;
      try {
        if (
          typeof command.command_id === "string" &&
          typeof command.turn_id === "string"
        ) {
          const bindings = mediaCommandBindingsRef.current;
          bindings.set(command.command_id, {
            generation: playbackGenerationRef.current,
            turnId: command.turn_id,
            version:
              typeof command.expected_control_version === "number"
                ? command.expected_control_version
                : controlVersionRef.current,
          });
          if (bindings.size > 64)
            bindings.delete(bindings.keys().next().value!);
        }
        socket.send(JSON.stringify(command));
        return true;
      } catch {
        markConnection("disconnected");
        markConnectionIssue("network");
        return false;
      }
    },
    [markConnection, markConnectionIssue],
  );

  const sendControllerAcquire = useCallback(
    (allowTerminal = false): boolean => {
      const debateStatus = detailRef.current.status;
      if (
        readOnly ||
        debateStatus === "draft" ||
        (!allowTerminal && isProductTerminalDetail(detailRef.current)) ||
        controllerAcquireBlockedRef.current ||
        controllerReadyRef.current ||
        acquirePendingRef.current
      )
        return false;
      acquirePendingRef.current = true;
      const sent = sendCommand({
        command_id: makeId(),
        command_type: "playback.controller.acquire",
        command_version: 1,
        debate_id: debateId,
        expected_control_version: controlVersionRef.current,
      });
      if (!sent) acquirePendingRef.current = false;
      return sent;
    },
    [debateId, readOnly, sendCommand],
  );

  const scheduleControllerAcquire = useCallback(
    (allowTerminal = false) => {
      const generation = playbackGenerationRef.current;
      const socketGeneration = socketGenerationRef.current;
      const connectAttempt = connectAttemptRef.current;
      window.setTimeout(() => {
        if (
          !mountedRef.current ||
          generation !== playbackGenerationRef.current ||
          socketGeneration !== socketGenerationRef.current ||
          connectAttempt !== connectAttemptRef.current
        )
          return;
        sendControllerAcquire(allowTerminal);
      }, 0);
    },
    [sendControllerAcquire],
  );

  const acquireReplayControllerAfterTerminal = useCallback(() => {
    if (!terminalReplayAcquirePendingRef.current || !socketRef.current) return;
    const current = detailRef.current;
    if (
      (current.status !== "debate_finished" &&
        current.status !== "completed") ||
      current.playback.mode !== "live" ||
      current.playback.status !== "completed"
    ) {
      return;
    }
    terminalReplayAcquirePendingRef.current = false;
    controllerEpochRef.current = null;
    acquirePendingRef.current = false;
    markControllerReady(false);
    controllerAcquireBlockedRef.current = false;
    markConnection("connected");
    markConnectionIssue(null);
    scheduleControllerAcquire(true);
  }, [
    markConnection,
    markConnectionIssue,
    markControllerReady,
    scheduleControllerAcquire,
  ]);

  const requestReconnect = useCallback(() => {
    if (!mountedRef.current || closingRef.current) return;
    connectAttemptRef.current += 1;
    pauseAudio(false);
    // A sequence gap/state-consistency failure is surfaced separately from a
    // network close. Recovery is an explicit teacher action; there is no timer
    // or background reconnect that can change the page behind them.
    markConnection("disconnected");
    markConnectionIssue("sequence_gap");
    markControllerReady(false);
    settlePendingReplayAcquire(new Error("Replay controller unavailable."));
    acquirePendingRef.current = false;
    terminalReplayAcquirePendingRef.current = false;
    controllerEpochRef.current = null;
    setFailure(null);
    recoveryFenceRef.current.active = false;
    recoveryFenceRef.current.refreshInFlight = false;
    socketGenerationRef.current += 1;
    const staleSocket = socketRef.current;
    socketRef.current = null;
    try {
      staleSocket?.close(1012, "sequence recovery");
    } catch {
      // The close callback will still schedule recovery for normal sockets.
    }
  }, [
    markConnection,
    markConnectionIssue,
    markControllerReady,
    pauseAudio,
    settlePendingReplayAcquire,
  ]);

  const applyPlayback = useCallback(
    (
      patch: Partial<DebatePlaybackState>,
      debateStatus?: DebateDetail["status"],
    ): DebatePlaybackState => {
      const previous = playbackRef.current;
      const next: DebatePlaybackState = {
        ...previous,
        ...patch,
        current_turn_id:
          patch.current_turn_id === undefined
            ? (previous.current_turn_id ?? null)
            : patch.current_turn_id,
        next_turn_ready: patch.next_turn_ready ?? previous.next_turn_ready,
      };
      next.next_turn_ready =
        ["playing", "paused", "waiting_next"].includes(next.status) &&
        next.next_turn_ready === true;
      markPlaybackItem(next);
      pendingActionRef.current = derivePendingPlaybackAction(
        next,
        publicTurnsRef.current,
      );
      playbackRef.current = next;
      controlVersionRef.current = next.control_version;
      setPlayback(next);
      const nextDetail: DebateDetail = {
        ...detailRef.current,
        ...(debateStatus ? { status: debateStatus } : {}),
        playback: next,
      };
      detailRef.current = nextDetail;
      setDetailState(nextDetail);
      onDetailChange?.(nextDetail);
      return next;
    },
    [markPlaybackItem, onDetailChange],
  );

  const visibleTurnFromPublic = useCallback(
    (turnId: string | null | undefined): VisiblePlaybackTurn | null =>
      publicTurnById(publicTurnsRef.current, turnId),
    [],
  );

  const setVisible = useCallback((next: VisiblePlaybackTurn | null) => {
    visibleTurnRef.current = next;
    setVisibleTurn(next);
  }, []);

  const setAvatars = useCallback((next: AvatarVisualState[]) => {
    avatarEventStatesRef.current = next;
    setAvatarEventStates(next);
  }, []);

  const setActiveParticipant = useCallback((next: string | null) => {
    activeParticipantRef.current = next;
    setActiveParticipantId(next);
  }, []);

  const ensureMediaPrepare = useCallback(() => {
    if (readOnly || !controllerEpochRef.current) return;
    const current = playbackRef.current;
    const turnId = current.current_turn_id;
    if (current.status !== "ready" || !turnId) return;
    const action = pendingActionRef.current;
    const key = `${turnId}:${action}:${current.control_version}`;
    if (prepareKeyRef.current === key || preparedMediaKeyRef.current === key)
      return;
    prepareKeyRef.current = key;
    const sent = sendCommand({
      command_id: makeId(),
      command_type: "playback.media.prepare",
      command_version: 1,
      debate_id: debateId,
      expected_control_version: current.control_version,
      controller_epoch: controllerEpochRef.current,
      turn_id: turnId,
      playback_action: action,
    });
    if (!sent) prepareKeyRef.current = null;
  }, [debateId, readOnly, sendCommand]);

  const audioQueue = useImmerseAudioQueue({
    api,
    debateId,
    enabled: !readOnly && controllerReady,
    controllerEpochRef,
    controllerReady,
    // This stage has no 3D scene to wait for.
    sceneSettled: true,
    started: playback.status !== "preparing",
  });
  // A speech Next started before the media handshake answered.
  const earlyStartRef = useRef<{
    key: string;
    play: Promise<void>;
  } | null>(null);
  useEffect(() => {
    audioQueue.noteCurrent(playback.current_turn_id);
  }, [audioQueue, playback.current_turn_id]);

  /**
   * PR A2: start the new speech as soon as Next answers, from its blob or
   * from the URL Next returned, instead of waiting for the media handshake.
   * The handshake still runs and acks the playing speech; a refused play()
   * falls back to it.
   */
  const startEarly = useCallback(
    (next: DebatePlaybackState & { media_url?: string | null }) => {
      const turnId = next.current_turn_id;
      const audio = audioRef.current;
      if (readOnly || !audio || !turnId || next.status !== "ready") return;
      const key = `${turnId}:${pendingActionRef.current}:${next.control_version}`;
      const mediaUrl =
        next.media_url && isSafeMediaUrl(next.media_url)
          ? next.media_url
          : null;
      const play = (async () => {
        const source = await audioQueue.sourceFor(turnId, mediaUrl);
        if (!source) throw new Error("no early source");
        const current = playbackRef.current;
        if (current.current_turn_id !== turnId || current.status !== "ready") {
          throw new Error("stale early start");
        }
        audio.src = source;
        // Every Debate plays at 1.0: the speaking rate is in the audio (TTS rate).
        audio.playbackRate = 1;
        await audio.play();
      })();
      const pending = { key, play };
      earlyStartRef.current = pending;
      play.catch(() => {
        // The media handshake starts it the usual way.
        if (earlyStartRef.current === pending) earlyStartRef.current = null;
      });
    },
    [audioQueue, readOnly],
  );

  const scheduleMediaPrepare = useCallback(() => {
    const generation = playbackGenerationRef.current;
    window.setTimeout(() => {
      if (!mountedRef.current || generation !== playbackGenerationRef.current)
        return;
      ensureMediaPrepare();
    }, 0);
  }, [ensureMediaPrepare]);

  // A detail/snapshot update can win the race with the REST response. Drive
  // the saved-audio handshake from committed state as well as command callbacks.
  useEffect(() => {
    if (controllerReady && playback.status === "ready") {
      scheduleMediaPrepare();
    }
  }, [
    controllerReady,
    playback.status,
    playback.current_turn_id,
    playback.control_version,
    scheduleMediaPrepare,
  ]);

  const syncRefreshedSnapshot = useCallback(
    (next: DebateDetail, minimumSequence = 0, notify = true) => {
      if (!mountedRef.current || closingRef.current) return;
      if (
        !Number.isInteger(next.last_sequence) ||
        next.last_sequence < minimumSequence ||
        next.playback.control_version < controlVersionRef.current
      ) {
        return false;
      }
      commitDetail(next, false);
      const committedSequence = next.last_sequence;
      sequenceRef.current = committedSequence;
      setLastSequence(committedSequence);
      const synced = {
        ...detailRef.current,
        last_sequence: committedSequence,
      };
      detailRef.current = synced;
      setDetailState(synced);
      if (notify) onDetailChange?.(synced);
      const turns = publicTurnsRef.current;
      const snapshotTurn = publicTurnById(turns, next.playback.current_turn_id);
      // A snapshot consumes the same sequence as the corresponding WS event.
      // Commit its speaker and text together before that event becomes a duplicate.
      setActiveParticipant(snapshotTurn?.participant_id ?? null);
      setVisible(snapshotTurn ?? null);
      setAvatars([]);
      if (TERMINAL_PLAYBACK.includes(next.playback.status)) {
        pauseAudio(true);
        setVisible(null);
        setAvatars([]);
        setActiveParticipant(null);
      } else if (next.playback.status === "waiting_next") {
        pauseAudio(true);
      } else if (next.playback.status === "paused") {
        pauseAudio(false);
      }
      setFailure(null);
      return true;
    },
    [
      commitDetail,
      onDetailChange,
      pauseAudio,
      setActiveParticipant,
      setAvatars,
      setVisible,
    ],
  );

  const playbackRefreshInFlight = useRef<Promise<void> | null>(null);
  const automaticMediaRetry = useRef<string | null>(null);

  const recoverPlayback = useCallback(async () => {
    if (!refreshSnapshot || !mountedRef.current || closingRef.current) return;
    if (playbackRefreshInFlight.current) {
      await playbackRefreshInFlight.current;
      return;
    }
    const epoch = controllerEpochRef.current;
    const recovery = (async () => {
      try {
        // A preparation event can overtake a read. Re-read once without
        // accepting an older sequence or issuing another control mutation.
        for (let attempt = 0; attempt < 2; attempt += 1) {
          const next = await refreshSnapshot();
          if (
            !mountedRef.current ||
            closingRef.current ||
            epoch !== controllerEpochRef.current
          )
            return;
          if (
            next.playback.control_version < controlVersionRef.current ||
            !syncRefreshedSnapshot(next, sequenceRef.current)
          )
            continue;
          setControlError(null);
          setMediaRetryNeeded(
            ["ready", "paused"].includes(next.playback.status),
          );
          // Retry only the saved media handshake, once per turn. Never regenerate
          // speech or repeat a possibly successful Next mutation automatically.
          const key = `${next.playback.mode}:${next.playback.current_turn_id}`;
          if (
            next.playback.status === "ready" &&
            automaticMediaRetry.current !== key
          ) {
            automaticMediaRetry.current = key;
            scheduleMediaPrepare();
          }
          return;
        }
      } catch {
        setMediaRetryNeeded(true);
      }
    })();
    playbackRefreshInFlight.current = recovery;
    try {
      await recovery;
    } finally {
      if (playbackRefreshInFlight.current === recovery) {
        playbackRefreshInFlight.current = null;
      }
    }
  }, [refreshSnapshot, scheduleMediaPrepare, syncRefreshedSnapshot]);

  const sendPlayFailure = useCallback(
    (
      code:
        | "autoplay_blocked"
        | "not_supported"
        | "decode_error"
        | "network_error"
        | "aborted"
        | "unknown",
      cause?: unknown,
      mediaGeneration = mediaGenerationRef.current,
    ) => {
      if (mediaGeneration !== mediaGenerationRef.current) return;
      const turnId =
        audioTurnRef.current ?? playbackRef.current.current_turn_id;
      const epoch = controllerEpochRef.current;
      if (!turnId || !epoch || readOnly) return;
      const action = audioActionRef.current;
      const phase = startedAckRef.current ? "post_ack" : "pre_ack";
      sendCommand({
        command_id: makeId(),
        command_type: "playback.play_failed",
        command_version: 1,
        debate_id: debateId,
        expected_control_version: controlVersionRef.current,
        controller_epoch: epoch,
        turn_id: turnId,
        playback_action: action,
        failure_phase: phase,
        cursor_ms: Math.max(0, Math.floor(cursorMsRef.current)),
        safe_client_code: code,
      });
      prepareKeyRef.current = null;
      preparedMediaKeyRef.current = null;
      setFailure(null);
      setMediaRetryNeeded(true);
      pauseAudio(false);
    },
    [debateId, pauseAudio, readOnly, sendCommand],
  );

  const handlePrivateMessage = useCallback(
    (message: PrivatePlaybackMessage) => {
      const binding = message.command_id
        ? mediaCommandBindingsRef.current.get(message.command_id)
        : undefined;
      if (
        binding &&
        (binding.generation !== playbackGenerationRef.current ||
          binding.turnId !== playbackRef.current.current_turn_id ||
          binding.version < controlVersionRef.current)
      )
        return;
      switch (message.message_type) {
        case "controller.acquired":
          if (
            controllerAcquireBlockedRef.current ||
            !message.controller_epoch ||
            message.control_version === undefined
          )
            return;
          if (
            controllerReadyRef.current &&
            controllerEpochRef.current &&
            message.controller_epoch !== controllerEpochRef.current
          ) {
            return;
          }
          if (message.control_version < controlVersionRef.current) return;
          controllerEpochRef.current = message.controller_epoch;
          controlVersionRef.current = message.control_version;
          acquirePendingRef.current = false;
          terminalReplayAcquirePendingRef.current = false;
          markControllerReady(true);
          setFailure(null);
          applyPlayback({ control_version: message.control_version });
          if (playbackRef.current.status === "ready") {
            scheduleMediaPrepare();
          }
          settlePendingReplayAcquire();
          return;
        case "media.prepared": {
          if (message.text_only === true && message.media_url === null) {
            if (
              message.controller_epoch !== controllerEpochRef.current ||
              message.turn_id !== playbackRef.current.current_turn_id
            )
              return;
            setFailure(null);
            return;
          }
          if (
            !message.controller_epoch ||
            !message.turn_id ||
            !message.media_url ||
            !isSafeMediaUrl(message.media_url)
          ) {
            setFailure(labelsRef.current.connectionError);
            return;
          }
          const current = playbackRef.current;
          if (
            current.status !== "ready" ||
            current.current_turn_id !== message.turn_id ||
            message.controller_epoch !== controllerEpochRef.current
          ) {
            return;
          }
          const action = pendingActionRef.current;
          const key = `${message.turn_id}:${action}:${current.control_version}`;
          if (preparedMediaKeyRef.current === key) return;
          const mediaGeneration = ++mediaGenerationRef.current;
          preparedMediaKeyRef.current = key;
          audioTurnRef.current = message.turn_id;
          audioActionRef.current = action;
          startedAckRef.current = false;
          const audio = audioRef.current;
          if (!audio) return;
          const mediaUrl = message.media_url;
          const preparedTurnId = message.turn_id;
          const early = earlyStartRef.current;
          earlyStartRef.current = null;
          cursorMsRef.current = current.cursor_ms;
          const playFrom = (source: string): Promise<void> => {
            try {
              audio.src = source;
              // Every Debate plays at 1.0: the speaking rate is in the audio (TTS rate).
              audio.playbackRate = 1;
              if (current.cursor_ms > 0) {
                // A seek at 0 would only cost a second ranged request.
                try {
                  audio.currentTime = current.cursor_ms / 1000;
                } catch {
                  // A not-yet-loaded media element may reject a seek; playback starts at its saved server cursor.
                }
              }
              return Promise.resolve(audio.play());
            } catch (cause) {
              return Promise.reject(cause);
            }
          };
          let playResult: Promise<void>;
          if (early?.key === key) {
            // Next already started this speech from its blob or the URL Next
            // returned; the handshake only acks it.
            playResult = early.play;
          } else {
            const now = audioQueue.sourceNow(preparedTurnId, mediaUrl);
            playResult = now
              ? playFrom(now)
              : audioQueue
                  .sourceFor(preparedTurnId, mediaUrl)
                  .then((source) =>
                    mediaGeneration === mediaGenerationRef.current
                      ? playFrom(source ?? mediaUrl)
                      : undefined,
                  );
          }
          playResult.then(
            () => {
              if (
                !mountedRef.current ||
                mediaGeneration !== mediaGenerationRef.current ||
                message.controller_epoch !== controllerEpochRef.current ||
                audioTurnRef.current !== message.turn_id
              ) {
                return;
              }
              startedAckRef.current = true;
              audioQueue.notePlaying(message.turn_id);
              setMediaRetryNeeded(false);
              setFailure(null);
              sendCommand({
                command_id: makeId(),
                command_type: "playback.started_ack",
                command_version: 1,
                debate_id: debateId,
                expected_control_version: controlVersionRef.current,
                controller_epoch: message.controller_epoch,
                turn_id: message.turn_id,
                playback_action: action,
              });
            },
            (cause: unknown) => {
              sendPlayFailure(
                isNotAllowedError(cause) ? "autoplay_blocked" : "unknown",
                cause,
                mediaGeneration,
              );
            },
          );
          return;
        }
        case "controller.revoked": {
          if (
            !message.controller_epoch ||
            message.controller_epoch !== controllerEpochRef.current
          ) {
            return;
          }
          controllerEpochRef.current = null;
          acquirePendingRef.current = false;
          markControllerReady(false);
          settlePendingReplayAcquire(new Error("Replay controller revoked."));
          pauseAudio(true);
          setAvatars([]);
          const revocationIssue: PlaybackConnectionIssue =
            message.reason === "superseded"
              ? "superseded"
              : message.reason === "session_revoked"
                ? "session_expired"
                : message.reason === "start_next" ||
                    message.reason === "debate_terminal"
                  ? "terminal"
                  : "network";
          controllerAcquireBlockedRef.current = revocationIssue !== "network";
          terminalReplayAcquirePendingRef.current =
            message.reason === "debate_terminal";
          if (revocationIssue === "terminal") {
            setVisible(null);
            setActiveParticipant(null);
          }
          if (message.reason === "start_next") {
            applyPlayback(
              { status: "completed", mode: "live", current_turn_id: null },
              detailRef.current.status,
            );
          }
          markConnection(
            message.reason === "debate_terminal" ? "connected" : "disconnected",
          );
          markConnectionIssue(revocationIssue);
          setFailure(null);
          if (message.reason === "debate_terminal") {
            acquireReplayControllerAfterTerminal();
          }
          return;
        }
        case "command.rejected":
        case "command.duplicate": {
          if (message.message_type === "command.duplicate") return;
          const wasAcquiring = acquirePendingRef.current;
          acquirePendingRef.current = false;
          if (message.message_type === "command.rejected") {
            settlePendingReplayAcquire(
              new Error(message.code ?? labelsRef.current.connectionError),
            );
          }
          if (message.current_control_version !== undefined) {
            controlVersionRef.current = Math.max(
              controlVersionRef.current,
              message.current_control_version,
            );
          }
          if (message.recoverable && !wasAcquiring) {
            setFailure(null);
            setControlError(null);
            setMediaRetryNeeded(true);
            void recoverPlayback();
          }
          if (
            message.message_type === "command.rejected" &&
            message.code === "session_revoked"
          ) {
            controllerEpochRef.current = null;
            acquirePendingRef.current = false;
            terminalReplayAcquirePendingRef.current = false;
            markControllerReady(false);
            pauseAudio(true);
            setVisible(null);
            setAvatars([]);
            setActiveParticipant(null);
            markConnection("disconnected");
            controllerAcquireBlockedRef.current = true;
            markConnectionIssue("session_expired");
            setFailure(null);
            try {
              socketRef.current?.close(4401, "session revoked");
            } catch {
              // The server has already rejected this session; cleanup is local.
            }
          }
          return;
        }
      }
    },
    [
      applyPlayback,
      acquireReplayControllerAfterTerminal,
      debateId,
      audioQueue,
      markConnection,
      markConnectionIssue,
      markControllerReady,
      pauseAudio,
      scheduleMediaPrepare,
      sendCommand,
      sendPlayFailure,
      recoverPlayback,
      settlePendingReplayAcquire,
      setActiveParticipant,
      setAvatars,
      setVisible,
    ],
  );

  const handleSnapshot = useCallback(
    (event: PlaybackEvent) => {
      const payload = event.payload;
      const decision = consumeEventSequence(sequenceRef.current, event);
      if (decision.gap || !decision.accepted) {
        if (decision.gap) requestReconnect();
        return;
      }
      sequenceRef.current = decision.nextSequence;
      setLastSequence(decision.nextSequence);
      const turns = normalisePublicTurns(payload.public_turns);
      updatePublicTurns(turns);
      if (Array.isArray(payload.audio_ready_turn_ids)) {
        audioQueue.noteReady(
          payload.audio_ready_turn_ids.filter(isNonEmptyString),
        );
      }
      const nextPlayback = playbackFromWire(
        payload.playback,
        playbackRef.current,
      );
      markPlaybackItem(nextPlayback);
      pendingActionRef.current = derivePendingPlaybackAction(
        nextPlayback,
        turns,
      );
      playbackRef.current = nextPlayback;
      controlVersionRef.current = nextPlayback.control_version;
      setPlayback(nextPlayback);
      const nextStatus = isDebateStatus(payload.debate_status)
        ? payload.debate_status
        : detailRef.current.status;
      const nextDetail: DebateDetail = {
        ...detailRef.current,
        status: nextStatus,
        final_input_frozen: payload.final_input_frozen === true,
        last_sequence: decision.nextSequence,
        playback: nextPlayback,
        public_turns: turns as DebateTurn[],
      };
      detailRef.current = nextDetail;
      setDetailState(nextDetail);
      onDetailChange?.(nextDetail);
      const snapshotStates = normaliseAvatarStates(payload.avatar_states);
      if (nextPlayback.status === "waiting_next") {
        // The completed turn remains visible, but waiting is never a speaking
        // avatar state even if a reconnect races with a stale snapshot.
        setAvatars([]);
      } else if (snapshotStates.length > 0) {
        setAvatars(snapshotStates);
      }
      const snapshotTurn = publicTurnById(turns, nextPlayback.current_turn_id);
      if (snapshotTurn) {
        setActiveParticipant(snapshotTurn.participant_id);
        if (
          nextPlayback.status === "playing" ||
          nextPlayback.status === "paused" ||
          nextPlayback.status === "waiting_next"
        ) {
          setVisible(snapshotTurn);
        }
      } else if (
        nextPlayback.status === "playing" ||
        nextPlayback.status === "paused" ||
        nextPlayback.status === "waiting_next"
      ) {
        // Never retain a stale speech card if a playing/paused snapshot does
        // not contain the public current turn it claims to expose.
        setVisible(null);
      }
      if (TERMINAL_PLAYBACK.includes(nextPlayback.status)) {
        pauseAudio(true);
        setVisible(null);
        setAvatars([]);
        setActiveParticipant(null);
      } else if (nextPlayback.status === "paused") {
        pauseAudio(false);
      }
      if (
        !readOnly &&
        nextStatus !== "draft" &&
        !isProductTerminalDetail({ status: nextStatus, playback: nextPlayback })
      ) {
        scheduleControllerAcquire();
      }
      setFailure(null);
    },
    [
      audioQueue,
      onDetailChange,
      pauseAudio,
      requestReconnect,
      readOnly,
      scheduleControllerAcquire,
      setActiveParticipant,
      setAvatars,
      setVisible,
      markPlaybackItem,
      updatePublicTurns,
    ],
  );

  const refreshRecoverySnapshot = useCallback(() => {
    const fence = recoveryFenceRef.current;
    if (
      !fence.active ||
      !refreshSnapshot ||
      fence.refreshInFlight ||
      !mountedRef.current ||
      closingRef.current
    ) {
      return;
    }
    fence.refreshInFlight = true;
    const generation = fence.generation;
    const load = async () => {
      while (true) {
        const currentFence = recoveryFenceRef.current;
        if (
          !mountedRef.current ||
          closingRef.current ||
          !currentFence.active ||
          currentFence.generation !== generation
        ) {
          return;
        }
        let next: DebateDetail;
        try {
          next = await refreshSnapshot();
        } catch {
          const failedFence = recoveryFenceRef.current;
          if (
            failedFence.active &&
            failedFence.generation === generation &&
            mountedRef.current &&
            !closingRef.current
          ) {
            failedFence.active = false;
            failedFence.refreshInFlight = false;
            requestReconnect();
          }
          return;
        }

        const latestFence = recoveryFenceRef.current;
        if (
          !mountedRef.current ||
          closingRef.current ||
          !latestFence.active ||
          latestFence.generation !== generation
        ) {
          return;
        }
        if (
          !Number.isInteger(next.last_sequence) ||
          next.last_sequence < latestFence.observedSequence
        ) {
          // A response captured before a subsequent persistent event is not
          // authoritative for this recovery. Keep the fence up and fetch
          // again; never use Math.max to disguise a stale snapshot.
          continue;
        }

        const refreshedTurns = normalisePublicTurns(next.public_turns);
        const reflectsStartedTurn =
          latestFence.targetTurnId === null ||
          next.playback.current_turn_id === latestFence.targetTurnId ||
          refreshedTurns.some((turn) => turn.id === latestFence.targetTurnId);
        if (!reflectsStartedTurn) {
          latestFence.active = false;
          latestFence.refreshInFlight = false;
          requestReconnect();
          return;
        }
        const merged =
          latestFence.candidate &&
          !refreshedTurns.some((turn) => turn.id === latestFence.candidate?.id)
            ? [...refreshedTurns, latestFence.candidate]
            : refreshedTurns;
        latestFence.active = false;
        latestFence.refreshInFlight = false;
        const synced = syncRefreshedSnapshot(
          {
            ...next,
            public_turns: merged as DebateTurn[],
          },
          latestFence.observedSequence,
        );
        if (!synced) {
          // The mounted/sequence guard is intentionally exact. If it ever
          // rejects after the coverage check, reopen the fence and retry.
          latestFence.active = true;
          latestFence.refreshInFlight = true;
          continue;
        }
        return;
      }
    };
    void load();
  }, [refreshSnapshot, requestReconnect, syncRefreshedSnapshot]);

  const recoverFromStartedTurnMismatch = useCallback(
    (event: PlaybackEvent): boolean => {
      if (event.event_type !== "playback.started") return false;
      const startedTurnId = event.payload.turn_id;
      const current = playbackRef.current;
      if (
        !isNonEmptyString(startedTurnId) ||
        current.mode !== "live" ||
        !current.current_turn_id ||
        current.current_turn_id === startedTurnId ||
        TERMINAL_PLAYBACK.includes(current.status)
      ) {
        return false;
      }

      // Rapid Next can overtake delivery of an already-public prior turn.
      // Its delayed event must not restore that prior speaker or stop the new audio.
      if (publicTurnsRef.current.some((turn) => turn.id === startedTurnId))
        return true;

      const candidate = visibleTurnFromPlaybackStarted(
        detailRef.current.participants,
        publicTurnsRef.current,
        event.payload,
      );
      const expectedIndex = publicTurnsRef.current.length;
      const expectedParticipant =
        detailRef.current.participants.length > 0
          ? detailRef.current.participants[
              (expectedIndex +
                (detailRef.current.teaching_protocol === "four_round_v1"
                  ? Math.floor(
                      expectedIndex / detailRef.current.participants.length,
                    )
                  : 0)) %
                detailRef.current.participants.length
            ]
          : undefined;
      const safeSuccessor = Boolean(
        candidate &&
        hasCompletePublicPrefix(publicTurnsRef.current) &&
        candidate.turn_index === expectedIndex &&
        candidate.participant_id === expectedParticipant?.id,
      );

      if (refreshSnapshot) {
        const previousFence = recoveryFenceRef.current;
        recoveryFenceRef.current = {
          active: true,
          candidate: safeSuccessor ? candidate : null,
          generation: previousFence.generation + 1,
          observedSequence: event.sequence,
          refreshInFlight: false,
          targetTurnId: startedTurnId,
        };
        refreshRecoverySnapshot();
        return true;
      }

      if (!safeSuccessor || !candidate) {
        requestReconnect();
        return true;
      }

      // Test/observation integrations may not provide an HTTP reader.  The
      // started event itself is then the only authoritative public payload;
      // adopt it only after the deterministic adjacent-prefix check above.
      pauseAudio(true);
      setVisible(null);
      setAvatars([]);
      setActiveParticipant(null);
      updatePublicTurns([...publicTurnsRef.current, candidate]);
      setActiveParticipant(candidate.participant_id);
      setVisible(candidate);
      setAvatars(normaliseAvatarStates(event.payload.avatar_states));
      applyPlayback(
        {
          status: "playing",
          mode: "live",
          current_turn_id: startedTurnId,
          cursor_ms: Math.max(0, integer(event.payload.cursor_ms, 0)),
        },
        "running",
      );
      const adopted = {
        ...detailRef.current,
        last_sequence: Math.max(
          detailRef.current.last_sequence,
          event.sequence,
        ),
      };
      detailRef.current = adopted;
      setDetailState(adopted);
      setLastSequence(adopted.last_sequence);
      onDetailChange?.(adopted);
      return true;
    },
    [
      applyPlayback,
      onDetailChange,
      pauseAudio,
      requestReconnect,
      refreshSnapshot,
      refreshRecoverySnapshot,
      setActiveParticipant,
      setAvatars,
      setVisible,
      updatePublicTurns,
    ],
  );

  const refreshProviderGate = useCallback(
    async (code: ProviderGateState["code"]) => {
      setProviderGate((current) => ({
        code,
        loading: true,
        value: current?.code === code ? current.value : null,
        error: null,
        selectedManifestHash:
          current?.code === code ? current.selectedManifestHash : null,
      }));
      try {
        const value = await api.listProviderDataCallManifests(debateId);
        if (!mountedRef.current || closingRef.current) return;
        setProviderGate((current) => {
          const retained = current?.selectedManifestHash;
          const selected =
            (retained &&
            value.items.some((item) => item.manifest_hash === retained)
              ? retained
              : null) ??
            value.items.find((item) => !item.confirmed)?.manifest_hash ??
            value.items.find(
              (item) => item.turn_id === playbackRef.current.current_turn_id,
            )?.manifest_hash ??
            value.items[value.items.length - 1]?.manifest_hash ??
            null;
          return {
            code,
            loading: false,
            value,
            error: null,
            selectedManifestHash: selected,
          };
        });
      } catch (cause) {
        if (!mountedRef.current || closingRef.current) return;
        setProviderGate({
          code,
          loading: false,
          value: null,
          error: errorText(cause, labelsRef.current.connectionError),
          selectedManifestHash: null,
        });
      }
    },
    [api, debateId],
  );

  useEffect(() => {
    const code = providerGate?.code;
    if (!code) return;
    const syncApprovals = () => void refreshProviderGate(code);
    window.addEventListener("focus", syncApprovals);
    return () => window.removeEventListener("focus", syncApprovals);
  }, [providerGate?.code, refreshProviderGate]);

  const retryProviderPreparation = useCallback(
    async (turnId: string) => {
      if (readOnly || providerRetryBusy) return;
      setProviderRetryBusy(true);
      setControlError(null);
      const current = providerRetryIdempotencyRef.current;
      const idempotency =
        current?.turnId === turnId ? current.handle : createIdempotencyHandle();
      providerRetryIdempotencyRef.current = { turnId, handle: idempotency };
      try {
        const next = await api.retryDebatePreparation(
          debateId,
          {
            expected_control_version: playbackRef.current.control_version,
            turn_id: turnId,
          },
          { idempotency },
        );
        providerRetryIdempotencyRef.current = null;
        setProviderGate(null);
        setFailure(null);
        applyPlayback(next, "running");
      } catch (cause) {
        setControlError(errorText(cause, labelsRef.current.connectionError));
      } finally {
        setProviderRetryBusy(false);
      }
    },
    [api, applyPlayback, debateId, providerRetryBusy, readOnly],
  );

  const handleEvent = useCallback(
    (event: PlaybackEvent) => {
      const recoveryFence = recoveryFenceRef.current;
      if (recoveryFence.active) {
        const observedSequence =
          event.event_type === "snapshot"
            ? integer(event.payload.latest_sequence, -1)
            : event.sequence;
        if (observedSequence >= 0) {
          recoveryFence.observedSequence = Math.max(
            recoveryFence.observedSequence,
            observedSequence,
          );
        }
        // Persistent events and websocket snapshots observed during a
        // successor recovery are deliberately not consumed against the old
        // current turn. The in-flight HTTP snapshot must cover this updated
        // watermark before the fence can be released.
        refreshRecoverySnapshot();
        return;
      }
      const decision = consumeEventSequence(sequenceRef.current, event);
      if (event.event_type === "snapshot") {
        handleSnapshot(event);
        return;
      }
      if (decision.gap) {
        requestReconnect();
        return;
      }
      if (!decision.accepted) return;
      sequenceRef.current = decision.nextSequence;
      setLastSequence(decision.nextSequence);
      const payload = event.payload;
      if (recoverFromStartedTurnMismatch(event)) return;
      // Text-only publication has no playback.started payload. Recover its
      // committed public transcript before the old current-item guard runs.
      if (
        event.event_type === "playback.waiting_next" &&
        refreshSnapshot &&
        playbackRef.current.mode === "live" &&
        payload.mode !== "replay" &&
        !TERMINAL_PLAYBACK.includes(playbackRef.current.status) &&
        !hasStaleControlVersion(event, playbackRef.current.control_version) &&
        isNonEmptyString(payload.completed_turn_id) &&
        !publicTurnById(publicTurnsRef.current, payload.completed_turn_id)
      ) {
        recoveryFenceRef.current = {
          active: true,
          candidate: null,
          generation: recoveryFenceRef.current.generation + 1,
          observedSequence: event.sequence,
          refreshInFlight: false,
          targetTurnId: payload.completed_turn_id,
        };
        refreshRecoverySnapshot();
        return;
      }
      if (
        !isCurrentItemEvent(event, playbackRef.current.current_turn_id ?? null)
      ) {
        return;
      }
      if (hasStaleControlVersion(event, playbackRef.current.control_version)) {
        return;
      }
      switch (event.event_type) {
        case "turn.audio_ready":
          // PR A2: a speech's audio is saved; playback state is unchanged.
          if (isNonEmptyString(payload.turn_id)) {
            audioQueue.noteReady([payload.turn_id]);
          }
          break;
        case "turn.preparing":
          if (
            isNonEmptyString(payload.turn_id) &&
            playbackRef.current.mode === "live" &&
            !TERMINAL_PLAYBACK.includes(playbackRef.current.status) &&
            !(
              playbackRef.current.current_turn_id &&
              playbackRef.current.current_turn_id !== payload.turn_id
            ) &&
            !(
              playbackRef.current.current_turn_id === payload.turn_id &&
              playbackRef.current.status === "ready"
            )
          ) {
            const preparingParticipant = detailRef.current.participants.find(
              (participant) => participant.slot === payload.slot,
            );
            setActiveParticipant(preparingParticipant?.id ?? null);
            pendingActionRef.current = "start";
            prepareKeyRef.current = null;
            preparedMediaKeyRef.current = null;
            setVisible(null);
            setAvatars([]);
            applyPlayback(
              {
                status: "preparing",
                mode: "live",
                current_turn_id: payload.turn_id,
                cursor_ms: 0,
              },
              "running",
            );
          }
          break;
        case "turn.ready":
          if (
            isNonEmptyString(payload.turn_id) &&
            playbackRef.current.mode === "live" &&
            !(
              playbackRef.current.mode === "live" &&
              playbackRef.current.status === "waiting_next"
            ) &&
            !(
              playbackRef.current.current_turn_id &&
              playbackRef.current.current_turn_id !== payload.turn_id
            ) &&
            !(
              playbackRef.current.current_turn_id === payload.turn_id &&
              (playbackRef.current.status === "ready" ||
                playbackRef.current.status === "playing" ||
                playbackRef.current.status === "paused")
            )
          ) {
            setProviderGate(null);
            pendingActionRef.current = "start";
            const readyParticipant = detailRef.current.participants.find(
              (participant) => participant.slot === payload.slot,
            );
            setActiveParticipant(readyParticipant?.id ?? null);
            setAvatars([]);
            applyPlayback(
              {
                status: "ready",
                current_turn_id: payload.turn_id,
                mode: playbackRef.current.mode,
                cursor_ms: 0,
              },
              "running",
            );
            scheduleMediaPrepare();
          }
          break;
        case "playback.waiting_next": {
          const eventMode =
            payload.mode === "replay" || payload.mode === "live"
              ? payload.mode
              : playbackRef.current.mode;
          if (eventMode !== playbackRef.current.mode) break;
          const completedTurnId = payload.completed_turn_id;
          if (!isNonEmptyString(completedTurnId)) break;
          const eventControlVersion = integer(
            payload.control_version,
            playbackRef.current.control_version,
          );
          if (eventControlVersion < playbackRef.current.control_version) break;
          if (
            playbackRef.current.current_turn_id &&
            playbackRef.current.current_turn_id !== completedTurnId
          ) {
            break;
          }
          if (
            playbackRef.current.next_turn_ready &&
            eventControlVersion === playbackRef.current.control_version &&
            payload.next_turn_ready !== true
          ) {
            break;
          }
          const completedTurn = publicTurnById(
            publicTurnsRef.current,
            completedTurnId,
          );
          if (completedTurn) {
            setActiveParticipant(completedTurn.participant_id);
            setVisible(completedTurn);
          }
          pauseAudio(true);
          setAvatars([]);
          applyPlayback(
            {
              status: "waiting_next",
              mode: eventMode,
              current_turn_id: completedTurnId,
              cursor_ms: 0,
              control_version: Math.max(
                playbackRef.current.control_version,
                eventControlVersion,
              ),
              next_turn_ready: payload.next_turn_ready === true,
            },
            eventMode === "replay" ? detailRef.current.status : "running",
          );
          break;
        }
        case "playback.started": {
          if (!isNonEmptyString(payload.turn_id)) break;
          if (
            (playbackRef.current.mode === "live" &&
              TERMINAL_PLAYBACK.includes(playbackRef.current.status)) ||
            (playbackRef.current.current_turn_id !== null &&
              playbackRef.current.current_turn_id !== payload.turn_id)
          ) {
            break;
          }
          const nextVisible = visibleTurnFromPlaybackStarted(
            detailRef.current.participants,
            publicTurnsRef.current,
            payload,
          );
          if (nextVisible) {
            setActiveParticipant(nextVisible.participant_id);
            const merged = publicTurnsRef.current.some(
              (item) => item.id === nextVisible.id,
            )
              ? publicTurnsRef.current.map((item) =>
                  item.id === nextVisible.id ? nextVisible : item,
                )
              : [...publicTurnsRef.current, nextVisible];
            updatePublicTurns(merged);
            setVisible(nextVisible);
          } else {
            const startedParticipant = detailRef.current.participants.find(
              (participant) => participant.slot === payload.slot,
            );
            setActiveParticipant(startedParticipant?.id ?? null);
            // The snapshot has not caught up with the turn that just started.
            // That is a moment, not a fault: raising an alert for it put a red
            // card over the transcript during an ordinary lesson.
          }
          setAvatars(normaliseAvatarStates(payload.avatar_states));
          pendingActionRef.current =
            playbackRef.current.mode === "replay" ? "replay" : "start";
          applyPlayback(
            {
              status: "playing",
              current_turn_id: payload.turn_id,
              cursor_ms: Math.max(0, integer(payload.cursor_ms, 0)),
            },
            playbackRef.current.mode === "replay"
              ? detailRef.current.status
              : "running",
          );
          setFailure(null);
          break;
        }
        case "playback.resumed": {
          if (!isNonEmptyString(payload.turn_id)) break;
          if (
            playbackRef.current.current_turn_id &&
            playbackRef.current.current_turn_id !== payload.turn_id
          ) {
            break;
          }
          const resumedTurn =
            catalogTurnById(payload.turn_id) ??
            publicTurnById(publicTurnsRef.current, payload.turn_id);
          if (resumedTurn) {
            setActiveParticipant(resumedTurn.participant_id);
            setVisible(resumedTurn);
          }
          pendingActionRef.current = "resume";
          applyPlayback({
            status: "playing",
            mode: playbackRef.current.mode,
            current_turn_id: payload.turn_id,
            cursor_ms: Math.max(
              0,
              integer(payload.cursor_ms, playbackRef.current.cursor_ms),
            ),
            control_version: Math.max(
              playbackRef.current.control_version,
              integer(
                payload.control_version,
                playbackRef.current.control_version,
              ),
            ),
          });
          break;
        }
        case "replay.started": {
          if (!isNonEmptyString(payload.turn_id)) break;
          if (
            detailRef.current.status !== "debate_finished" &&
            detailRef.current.status !== "completed"
          ) {
            break;
          }
          pendingActionRef.current = "replay";
          const replayTurn =
            catalogTurnById(payload.turn_id) ??
            visibleTurnFromPublic(payload.turn_id);
          if (!replayTurn) {
            setFailure(labelsRef.current.noPublishedSpeech);
            requestReconnect();
            break;
          }
          setActiveParticipant(replayTurn?.participant_id ?? null);
          setVisible(replayTurn);
          setAvatars([]);
          applyPlayback(
            {
              status: "playing",
              mode: "replay",
              current_turn_id: payload.turn_id,
              cursor_ms: 0,
              control_version: Math.max(
                playbackRef.current.control_version,
                integer(
                  payload.control_version,
                  playbackRef.current.control_version,
                ),
              ),
            },
            detailRef.current.status,
          );
          break;
        }
        case "playback.completed":
          if (
            playbackRef.current.mode === "live" &&
            playbackRef.current.status === "waiting_next"
          )
            break;
          pauseAudio(true);
          if (playbackRef.current.mode === "replay") {
            setVisible(null);
            setAvatars([]);
            setActiveParticipant(null);
            applyPlayback(
              {
                status: "completed",
                mode: "live",
                current_turn_id: null,
                control_version: Math.max(
                  playbackRef.current.control_version,
                  integer(
                    payload.control_version,
                    playbackRef.current.control_version,
                  ),
                ),
              },
              detailRef.current.status,
            );
            break;
          }
          if (
            playbackRef.current.mode === "live" &&
            publicTurnsRef.current.length >=
              expectedTurnCount(detailRef.current)
          ) {
            pendingActionRef.current = "start";
            setActiveParticipant(null);
            applyPlayback(
              {
                status: "completed",
                current_turn_id: null,
                cursor_ms: 0,
                control_version: Math.max(
                  playbackRef.current.control_version,
                  integer(
                    payload.control_version,
                    playbackRef.current.control_version,
                  ),
                ),
              },
              "debate_finished",
            );
          } else {
            const completedTurnId = isNonEmptyString(payload.turn_id)
              ? payload.turn_id
              : playbackRef.current.current_turn_id;
            const completedTurn = publicTurnById(
              publicTurnsRef.current,
              completedTurnId,
            );
            if (completedTurn) {
              setActiveParticipant(completedTurn.participant_id);
              setVisible(completedTurn);
            }
            applyPlayback({
              status: "waiting_next",
              mode: "live",
              current_turn_id: completedTurnId,
              cursor_ms: 0,
              control_version: Math.max(
                playbackRef.current.control_version,
                integer(
                  payload.control_version,
                  playbackRef.current.control_version,
                ),
              ),
              next_turn_ready: false,
            });
          }
          setAvatars([]);
          break;
        case "replay.completed":
          pauseAudio(true);
          setVisible(null);
          setAvatars([]);
          setActiveParticipant(null);
          // The terminal replay event is followed by one same-socket
          // controller renewal. Set the intent before the async snapshot so
          // either event order converges on exactly one acquire.
          terminalReplayAcquirePendingRef.current = true;
          if (!refreshSnapshot) {
            // Observation-only/test integrations may not provide an HTTP
            // reader. The final replay event is still terminal locally.
            applyPlayback({
              status: "completed",
              mode: "live",
              current_turn_id: null,
              control_version: Math.max(
                playbackRef.current.control_version,
                integer(
                  payload.control_version,
                  playbackRef.current.control_version,
                ),
              ),
            });
            acquireReplayControllerAfterTerminal();
            break;
          }
          void refreshSnapshot()
            .then((next) => {
              if (!mountedRef.current || !next) return;
              commitDetail(next);
              acquireReplayControllerAfterTerminal();
            })
            .catch((cause: unknown) => {
              if (!mountedRef.current) return;
              setFailure(errorText(cause, labelsRef.current.connectionError));
            });
          break;
        case "debate.completed":
          pauseAudio(true);
          setVisible(null);
          setAvatars([]);
          setActiveParticipant(null);
          applyPlayback(
            { status: "completed", current_turn_id: null },
            "completed",
          );
          break;
        case "debate.failed":
          setProviderGate(null);
          pauseAudio(true);
          setVisible(null);
          setAvatars([]);
          setActiveParticipant(null);
          controllerEpochRef.current = null;
          acquirePendingRef.current = false;
          terminalReplayAcquirePendingRef.current = false;
          controllerAcquireBlockedRef.current = true;
          markControllerReady(false);
          applyPlayback({ status: "stopped", current_turn_id: null }, "failed");
          // "Needs attention" alone leaves a teacher with nowhere to go. When
          // the server names a cause it is a safe code the browser already
          // receives elsewhere, so say it.
          setFailure(
            payload.safe_error_code === "provider_preflight_blocked"
              ? (labelsRef.current.providerSetupIncomplete ??
                  labelsRef.current.debateFailed)
              : labelsRef.current.debateFailed,
          );
          break;
        case "debate.stopped": {
          setProviderGate(null);
          pauseAudio(true);
          setVisible(null);
          setAvatars([]);
          setActiveParticipant(null);
          controllerEpochRef.current = null;
          acquirePendingRef.current = false;
          terminalReplayAcquirePendingRef.current = false;
          controllerAcquireBlockedRef.current = true;
          markControllerReady(false);
          const terminalStates = isRecord(payload.final_states)
            ? payload.final_states
            : null;
          const isTeacherFinishedPartial =
            payload.safe_error_code === "debate_finished_partial" &&
            terminalStates?.debate === "debate_finished";
          applyPlayback(
            { status: "stopped", current_turn_id: null },
            isTeacherFinishedPartial ? "debate_finished" : "stopped",
          );
          break;
        }
        case "error":
          // A blocked preflight is an operator problem, not a transient one:
          // telling a teacher mid-class to retry something that cannot
          // succeed is worse than saying nothing.
          setFailure(
            payload.code === "provider_preflight_blocked"
              ? (labelsRef.current.providerSetupIncomplete ??
                  labelsRef.current.retryReason)
              : labelsRef.current.retryReason,
          );
          if (
            payload.code === "provider_confirmation_required" ||
            payload.code === "provider_not_sent"
          ) {
            const code = payload.code;
            applyPlayback({ status: "preparing" });
            void refreshProviderGate(code);
          } else if (payload.recoverable === true) {
            setProviderGate(null);
            setFailure(null);
            setMediaRetryNeeded(true);
            void recoverPlayback();
          } else {
            setProviderGate(null);
          }
          break;
        default:
          break;
      }
      acquireReplayControllerAfterTerminal();
      const nextDetail = {
        ...detailRef.current,
        last_sequence: decision.nextSequence,
      };
      detailRef.current = nextDetail;
      setDetailState(nextDetail);
      onDetailChange?.(nextDetail);
    },
    [
      audioQueue,
      applyPlayback,
      acquireReplayControllerAfterTerminal,
      commitDetail,
      handleSnapshot,
      markControllerReady,
      onDetailChange,
      pauseAudio,
      recoverFromStartedTurnMismatch,
      refreshSnapshot,
      recoverPlayback,
      catalogTurnById,
      setActiveParticipant,
      requestReconnect,
      refreshRecoverySnapshot,
      refreshProviderGate,
      setAvatars,
      setVisible,
      updatePublicTurns,
      visibleTurnFromPublic,
      scheduleMediaPrepare,
    ],
  );

  const handleSocketMessage = useCallback(
    (event: Event) => {
      const value = socketMessageData(event);
      if (!value) return;
      if (isRecord(value) && typeof value.message_type === "string") {
        const privateMessage = parsePrivatePlaybackMessage(value, debateId);
        if (privateMessage) {
          handlePrivateMessage(privateMessage);
          return;
        }
      }
      const playbackEvent = parsePlaybackEvent(value, debateId);
      if (playbackEvent) handleEvent(playbackEvent);
    },
    [debateId, handleEvent, handlePrivateMessage],
  );

  const installSocket = useCallback(
    (socket: PlaybackSocket, socketGeneration: number) => {
      const isCurrentSocket = () =>
        socketRef.current === socket &&
        socketGenerationRef.current === socketGeneration;
      const onOpen = () => {
        if (!isCurrentSocket()) return;
        // Terminal debates do not acquire a controller on connect.  A teacher
        // may still press Replay while the socket is connecting, though; the
        // request is intentionally held until the browser reports OPEN so a
        // native WebSocket.send() cannot throw and silently abort the action.
        const replayAcquirePending = terminalReplayAcquirePendingRef.current;
        const terminalReplayMayAcquire =
          replayAcquirePending &&
          (connectionIssueRef.current === null ||
            connectionIssueRef.current === "terminal");
        if (controllerAcquireBlockedRef.current && !terminalReplayMayAcquire)
          return;
        if (terminalReplayMayAcquire) {
          controllerAcquireBlockedRef.current = false;
        }
        markConnection("connected");
        markConnectionIssue(null);
        setFailure(null);
        if (replayAcquirePending) {
          acquireReplayControllerAfterTerminal();
          return;
        }
        if (!readOnly && !isProductTerminalDetail(detailRef.current)) {
          sendControllerAcquire();
        }
      };
      const onMessage = (event: Event) => {
        if (!isCurrentSocket()) return;
        handleSocketMessage(event);
      };
      const onError = () => {
        if (!isCurrentSocket()) return;
        // Browsers dispatch `error` before `close`. Wait for the close code so
        // 4401/4403 or an earlier private revocation cannot be overwritten by
        // a generic network label.
      };
      const onClose = (event?: Event) => {
        if (!mountedRef.current || closingRef.current || !isCurrentSocket())
          return;
        const closeCode =
          event && "code" in event ? Number((event as CloseEvent).code) : 0;
        const existingIssue = connectionIssueRef.current;
        const closeIssue = connectionIssueFromCloseCode(closeCode);
        const replayAcquirePending = pendingReplayAcquireRef.current !== null;
        const preciseIssue =
          existingIssue === "superseded" ||
          existingIssue === "terminal" ||
          existingIssue === "session_expired" ||
          existingIssue === "origin_mismatch"
            ? existingIssue
            : closeIssue === "session_expired" ||
                closeIssue === "origin_mismatch"
              ? closeIssue
              : isTerminalConnectionContext(detailRef.current) &&
                  !replayAcquirePending
                ? "terminal"
                : closeIssue;
        connectAttemptRef.current += 1;
        socketGenerationRef.current += 1;
        socketRef.current = null;
        markConnection("disconnected");
        if (replayAcquirePending && preciseIssue === "network") {
          setControlError(labelsRef.current.connectionDisconnected);
        }
        settlePendingReplayAcquire(new Error("Replay controller unavailable."));
        acquirePendingRef.current = false;
        terminalReplayAcquirePendingRef.current = false;
        markControllerReady(false);
        controllerEpochRef.current = null;
        controllerAcquireBlockedRef.current =
          preciseIssue === "superseded" ||
          preciseIssue === "terminal" ||
          preciseIssue === "session_expired" ||
          preciseIssue === "origin_mismatch";
        markConnectionIssue(preciseIssue);
        setFailure(null);
        pauseAudio(preciseIssue !== "network");
        if (preciseIssue !== "network") {
          setAvatars([]);
        }
      };
      if (socket.addEventListener) {
        socket.addEventListener("open", onOpen);
        socket.addEventListener("message", onMessage);
        socket.addEventListener("error", onError);
        socket.addEventListener("close", onClose);
        socketCleanupRef.current = () => {
          socket.removeEventListener?.("open", onOpen);
          socket.removeEventListener?.("message", onMessage);
          socket.removeEventListener?.("error", onError);
          socket.removeEventListener?.("close", onClose);
        };
      } else {
        socket.onopen = onOpen;
        socket.onmessage = (event) => onMessage(event);
        socket.onerror = onError;
        socket.onclose = onClose;
        socketCleanupRef.current = () => {
          socket.onopen = null;
          socket.onmessage = null;
          socket.onerror = null;
          socket.onclose = null;
        };
      }
    },
    [
      acquireReplayControllerAfterTerminal,
      handleSocketMessage,
      markConnection,
      markConnectionIssue,
      markControllerReady,
      pauseAudio,
      readOnly,
      sendControllerAcquire,
      settlePendingReplayAcquire,
      setAvatars,
    ],
  );

  const connect = useCallback(
    async (refresh: boolean) => {
      if (!mountedRef.current || closingRef.current) return;
      const connectAttempt = ++connectAttemptRef.current;
      if (refresh && refreshSnapshot) {
        try {
          const next = await refreshSnapshot();
          if (
            !mountedRef.current ||
            closingRef.current ||
            connectAttempt !== connectAttemptRef.current
          )
            return;
          commitDetail(next, false);
          publicTurnsRef.current = normalisePublicTurns(next.public_turns);
          setPublicTurns(publicTurnsRef.current);
          sequenceRef.current = next.last_sequence;
          setLastSequence(next.last_sequence);
          setFailure(null);
        } catch (cause) {
          // A failed manual attempt must not discard the current page or
          // trigger another refresh/retry in the background.
          markConnection("disconnected");
          if (isAuthenticationExpiredError(cause)) {
            controllerAcquireBlockedRef.current = true;
            terminalReplayAcquirePendingRef.current = false;
            acquirePendingRef.current = false;
            controllerEpochRef.current = null;
            markControllerReady(false);
            markConnectionIssue("session_expired");
            pauseAudio(true);
            setFailure(null);
            setReconnectBusy(false);
            socketGenerationRef.current += 1;
            const staleSocket = socketRef.current;
            socketRef.current = null;
            try {
              staleSocket?.close(4401, "session expired");
            } catch {
              // HTTP 401 is already authoritative; socket cleanup is local.
            }
            return;
          }
          markConnectionIssue(
            connectionIssueRef.current === "sequence_gap"
              ? "sequence_gap"
              : "network",
          );
          setFailure(errorText(cause, labelsRef.current.connectionError));
          setReconnectBusy(false);
          return;
        }
      }
      if (
        !mountedRef.current ||
        closingRef.current ||
        connectAttempt !== connectAttemptRef.current
      )
        return;
      socketCleanupRef.current?.();
      socketCleanupRef.current = null;
      socketRef.current = null;
      const socketGeneration = ++socketGenerationRef.current;
      try {
        const url = socketUrl ?? debateSocketUrl(debateId);
        const socket = socketFactory
          ? socketFactory(url)
          : (new WebSocket(url) as unknown as PlaybackSocket);
        socketRef.current = socket;
        markConnection("connecting");
        installSocket(socket, socketGeneration);
      } catch (cause) {
        markConnection("disconnected");
        markConnectionIssue("network");
        setFailure(errorText(cause, labelsRef.current.connectionError));
      } finally {
        if (refresh) setReconnectBusy(false);
      }
    },
    [
      commitDetail,
      debateId,
      installSocket,
      markConnection,
      markConnectionIssue,
      markControllerReady,
      pauseAudio,
      refreshSnapshot,
      socketFactory,
      socketUrl,
    ],
  );

  const reconnect = useCallback(() => {
    if (
      readOnly ||
      !mountedRef.current ||
      closingRef.current ||
      reconnectBusy ||
      connection === "connected" ||
      connection === "connecting" ||
      (connectionIssue !== "network" && connectionIssue !== "sequence_gap")
    ) {
      return;
    }
    setReconnectBusy(true);
    markConnection("reconnecting");
    void connect(true).catch((cause: unknown) => {
      if (!mountedRef.current || closingRef.current) return;
      markConnection("disconnected");
      setFailure(errorText(cause, labelsRef.current.connectionError));
      setReconnectBusy(false);
    });
  }, [
    connect,
    connection,
    connectionIssue,
    markConnection,
    readOnly,
    reconnectBusy,
  ]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      // Ignore our own parent echo; independent HTTP snapshots use exactly
      // the same complete projection as WS recovery, including visible text.
      if (detail === detailRef.current) return;
      syncRefreshedSnapshot(detail, sequenceRef.current, false);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [detail, syncRefreshedSnapshot]);

  useEffect(() => {
    mountedRef.current = true;
    closingRef.current = false;
    const timer = window.setTimeout(() => void connect(false), 0);
    return () => {
      window.clearTimeout(timer);
      mountedRef.current = false;
      closingRef.current = true;
      settlePendingReplayAcquire(new Error("Replay controller unavailable."));
      connectAttemptRef.current += 1;
      socketGenerationRef.current += 1;
      socketCleanupRef.current?.();
      socketCleanupRef.current = null;
      try {
        socketRef.current?.close(1000, "stage unmounted");
      } catch {
        // Socket may already have closed.
      }
      socketRef.current = null;
      pauseAudio(true);
    };
  }, [connect, pauseAudio, settlePendingReplayAcquire]);

  const onAudioEnded = useCallback(() => {
    if (readOnly || !startedAckRef.current || !audioRef.current?.ended) return;
    const turnId = audioTurnRef.current;
    if (turnId !== playbackRef.current.current_turn_id) return;
    const epoch = controllerEpochRef.current;
    if (!turnId || !epoch) return;
    sendCommand({
      command_id: makeId(),
      command_type: "playback.ended_ack",
      command_version: 1,
      debate_id: debateId,
      expected_control_version: controlVersionRef.current,
      controller_epoch: epoch,
      turn_id: turnId,
    });
    startedAckRef.current = false;
  }, [debateId, readOnly, sendCommand]);

  const onAudioError = useCallback(() => {
    const audio = audioRef.current;
    if (!audio?.error || !audioTurnRef.current || readOnly) return;
    sendPlayFailure(mediaErrorCode(audio));
  }, [readOnly, sendPlayFailure]);

  const onAudioTimeUpdate = useCallback(
    (event: SyntheticEvent<HTMLAudioElement>) => {
      const currentTime = event.currentTarget.currentTime;
      if (Number.isFinite(currentTime) && currentTime >= 0) {
        cursorMsRef.current = Math.floor(currentTime * 1000);
      }
    },
    [],
  );

  const runControl = useCallback(
    async (action: ControlAction) => {
      if (readOnly || busyAction !== null || controlRequestRef.current !== null)
        return;
      const replayableTerminalSource = isReplayableTerminalSource(
        detailRef.current,
        audioPointer,
        debateId,
      );
      const replayAudioReady = replayAudioAvailable(
        detailRef.current,
        audioPointer,
        debateId,
      );
      if (
        action === "replay" &&
        ((!controllerReadyRef.current && !replayableTerminalSource) ||
          acquirePendingRef.current ||
          !replayAudioReady)
      ) {
        return;
      }
      if (action === "next" && mediaRetryNeeded && controllerReadyRef.current) {
        if (playbackRef.current.status === "ready") {
          if (prepareKeyRef.current || preparedMediaKeyRef.current) return;
          setFailure(null);
          setControlError(null);
          scheduleMediaPrepare();
          return;
        }
      }
      if (
        action === "next" &&
        (!controllerReadyRef.current ||
          acquirePendingRef.current ||
          (playbackRef.current.mode !== "live" &&
            playbackRef.current.mode !== "replay") ||
          !["playing", "paused", "waiting_next"].includes(
            playbackRef.current.status,
          ) ||
          (playbackRef.current.status === "waiting_next" &&
            !playbackRef.current.next_turn_ready &&
            !(
              atFinalBoundary(detailRef.current, playbackRef.current) &&
              !detailRef.current.final_input_frozen
            )) ||
          !playbackRef.current.current_turn_id)
      ) {
        return;
      }
      if (
        action === "pause" &&
        (!controllerReadyRef.current ||
          acquirePendingRef.current ||
          playbackRef.current.status !== "playing" ||
          !playbackRef.current.current_turn_id)
      ) {
        return;
      }
      if (
        action === "resume" &&
        (!controllerReadyRef.current ||
          acquirePendingRef.current ||
          playbackRef.current.status !== "paused" ||
          !playbackRef.current.current_turn_id)
      ) {
        return;
      }
      const requestToken = ++nextControlRequestRef.current;
      controlRequestRef.current = requestToken;
      const requestGeneration = playbackGenerationRef.current;
      const requestTurnId = playbackRef.current.current_turn_id;
      let requestControlVersion = playbackRef.current.control_version;
      const isCurrentRequest = () =>
        controlRequestRef.current === requestToken &&
        playbackGenerationRef.current === requestGeneration &&
        playbackRef.current.current_turn_id === requestTurnId &&
        controlVersionRef.current === requestControlVersion;
      setBusyAction(action);
      // Publish commandBusy synchronously with the local guard. The header
      // Finish handler reads the same authority ref, so a same-event-loop
      // Next/Finish bypass cannot issue a second REST mutation.
      publishAuthority({ commandBusy: true });
      setControlError(null);
      setFailure(null);
      try {
        const current = playbackRef.current;
        if (action === "start") {
          pendingActionRef.current = "start";
          const idempotency =
            startIdempotencyRef.current ?? createIdempotencyHandle();
          startIdempotencyRef.current = idempotency;
          const started = await api.startDebate(
            debateId,
            {
              expected_revision: detailRef.current.revision,
              expected_current_audio_debate_id: audioPointer ?? null,
              confirm_previous_audio_cleanup: Boolean(audioPointer),
              output_language: detailRef.current.output_language ?? "en",
            },
            { idempotency },
          );
          // A successful start changes the course's retained-audio pointer.
          // Commit this local fact before stale-response handling so a
          // start response that loses a WS/controller race still enables
          // replay after the debate reaches a terminal state.
          markCurrentAudioDebate(debateId);
          if (!isCurrentRequest()) {
            // The start request races the draft socket becoming live.  The
            // socket's authoritative turn events may advance the playback
            // generation before this HTTP response arrives; never apply the
            // now-stale draft detail, but recover the controller boundary.
            if (
              detailRef.current.status === "running" &&
              !TERMINAL_PLAYBACK.includes(playbackRef.current.status) &&
              !controllerEpochRef.current &&
              !closingRef.current
            ) {
              scheduleControllerAcquire();
            }
            return;
          }
          // A draft socket is observation-only.  Starting the Debate changes
          // the server authority boundary, so acquire a fresh controller
          // epoch only after the start response is committed.
          controllerEpochRef.current = null;
          acquirePendingRef.current = false;
          markControllerReady(false);
          commitDetail(started);
          scheduleControllerAcquire();
          return;
        }
        if (action === "next") {
          const expectedCurrentTurnId = current.current_turn_id;
          if (!expectedCurrentTurnId) return;
          const interrupting =
            current.status === "playing" || current.status === "paused";
          if (interrupting) pauseAudio(false);
          const currentTurn = publicTurnById(
            publicTurnsRef.current,
            expectedCurrentTurnId,
          );
          if (
            interrupting &&
            currentTurn?.turn_index === expectedTurnCount(detailRef.current) - 1
          ) {
            sendCommand({
              command_id: makeId(),
              command_type: "playback.ended_ack",
              command_version: 1,
              debate_id: debateId,
              expected_control_version: current.control_version,
              controller_epoch: controllerEpochRef.current,
              turn_id: expectedCurrentTurnId,
            });
            return;
          }
          if (
            atFinalBoundary(detailRef.current, current) &&
            !detailRef.current.final_input_frozen
          ) {
            const finalEpoch = controllerEpochRef.current;
            const canRefreshFinal = () =>
              mountedRef.current &&
              !closingRef.current &&
              finalEpoch === controllerEpochRef.current &&
              controlRequestRef.current === requestToken &&
              playbackGenerationRef.current === requestGeneration;
            await api.freezeFinalInput(debateId, current.control_version);
            if (!canRefreshFinal()) return;
            await recoverPlayback();
            // A shared recovery may have started before Final committed.
            if (canRefreshFinal() && !detailRef.current.final_input_frozen) {
              await recoverPlayback();
            }
            return;
          }
          markDebateNextClicked();
          let next: DebatePlaybackState;
          try {
            next = await api.advanceDebatePlayback(debateId, {
              expected_control_version: current.control_version,
              expected_current_turn_id: expectedCurrentTurnId,
            });
          } catch (cause) {
            if (
              !isRecord(cause) ||
              cause.code !== "stale_control_version" ||
              !refreshSnapshot
            )
              throw cause;
            const latest = await refreshSnapshot();
            if (!syncRefreshedSnapshot(latest, sequenceRef.current)) return;
            // Natural audio completion can win the version race. Retry once
            // only if the requested source turn is still current; otherwise
            // the first Next already moved it and must never be repeated.
            if (
              latest.playback.current_turn_id !== expectedCurrentTurnId ||
              !["playing", "paused", "waiting_next"].includes(
                latest.playback.status,
              )
            )
              return;
            requestControlVersion = latest.playback.control_version;
            next = await api.advanceDebatePlayback(debateId, {
              expected_control_version: requestControlVersion,
              expected_current_turn_id: expectedCurrentTurnId,
            });
          }
          if (!isCurrentRequest()) {
            await recoverPlayback();
            return;
          }
          if (next.mode === "live" && next.status === "waiting_next") {
            applyPlayback(next);
            await recoverPlayback();
            return;
          }
          // Audio-backed Next reveals the transcript only after the media
          // handshake publishes playback.started.
          setVisible(null);
          setAvatars([]);
          setActiveParticipant(null);
          applyPlayback(next);
          pendingActionRef.current = next.mode === "replay" ? "replay" : "next";
          startEarly(next);
          scheduleMediaPrepare();
          return;
        }
        if (action === "replay") {
          pendingActionRef.current = "replay";
          if (!controllerReadyRef.current) {
            const socket = socketRef.current;
            const readyState = socket
              ? (socket as PlaybackSocket & { readyState?: unknown }).readyState
              : null;
            const socketState =
              typeof readyState === "number" ? readyState : null;
            // A native WebSocket throws when send() is called in CONNECTING
            // state. Hold the acquire until onOpen instead of turning a
            // perfectly valid terminal replay into a silent no-op.
            if (!socket || socketState === 2 || socketState === 3) {
              setControlError(labelsRef.current.connectionDisconnected);
              return;
            }
            const socketOpening =
              socketState === 0 ||
              (socketState === null && connection !== "connected");
            const acquireResult = new Promise<void>((resolve, reject) => {
              pendingReplayAcquireRef.current = { resolve, reject };
            });
            terminalReplayAcquirePendingRef.current = true;
            if (
              controllerAcquireBlockedRef.current &&
              connectionIssueRef.current === "terminal"
            ) {
              controllerAcquireBlockedRef.current = false;
              markConnectionIssue(null);
            }
            if (!socketOpening && !sendControllerAcquire(true)) {
              terminalReplayAcquirePendingRef.current = false;
              settlePendingReplayAcquire(
                new Error(labelsRef.current.connectionError),
              );
            }
            try {
              await acquireResult;
            } catch {
              return;
            }
            requestControlVersion = playbackRef.current.control_version;
          }
          const next = await api.replayDebate(
            debateId,
            playbackRef.current.control_version,
          );
          if (!isCurrentRequest()) return;
          // Replay is retained playback.  Keep the authoritative transcript
          // and sources visible while the immutable catalog advances; the
          // replay.started event moves only the current-turn highlight.
          applyPlayback(next);
          scheduleMediaPrepare();
          return;
        }
        if (action === "pause") {
          const idempotency =
            pauseIdempotencyRef.current ?? createIdempotencyHandle();
          pauseIdempotencyRef.current = idempotency;
          const paused = await api.pauseDebate(
            debateId,
            { expected_control_version: current.control_version },
            { idempotency },
          );
          if (!isCurrentRequest()) return;
          pauseIdempotencyRef.current = null;
          pauseAudio(false);
          applyPlayback({
            ...paused,
            status: "paused",
            current_turn_id: paused.current_turn_id ?? current.current_turn_id,
          });
          return;
        }
        if (action === "resume") {
          const idempotency =
            resumeIdempotencyRef.current ?? createIdempotencyHandle();
          resumeIdempotencyRef.current = idempotency;
          const resumed = await api.resumeDebate(
            debateId,
            { expected_control_version: current.control_version },
            { idempotency },
          );
          if (!isCurrentRequest()) return;
          resumeIdempotencyRef.current = null;
          applyPlayback({
            ...resumed,
            status: "ready",
            current_turn_id: resumed.current_turn_id ?? current.current_turn_id,
          });
          pendingActionRef.current = "resume";
          scheduleMediaPrepare();
          return;
        }
      } catch (cause) {
        if (controlRequestRef.current === requestToken) {
          if (
            action === "next" &&
            isRecord(cause) &&
            cause.code === "next_not_ready"
          ) {
            // Fake success Next is forbidden: Audio Not Ready / unfinished
            // prepare must stay on the current turn with a visible failure.
            if (
              ["playing", "paused"].includes(playbackRef.current.status) &&
              playbackRef.current.current_turn_id === requestTurnId
            ) {
              sendCommand({
                command_id: makeId(),
                command_type: "playback.ended_ack",
                command_version: 1,
                debate_id: debateId,
                expected_control_version: controlVersionRef.current,
                controller_epoch: controllerEpochRef.current,
                turn_id: requestTurnId,
              });
            }
            setFailure(null);
            await recoverPlayback();
            // recoverPlayback clears control errors and may re-apply a stale
            // next_turn_ready=true from the snapshot. Re-assert the failure
            // after sync so Next cannot look like a silent success.
            applyPlayback({ next_turn_ready: false });
            setControlError(
              labelsRef.current.nextNotReady ??
                labelsRef.current.prepared ??
                "Next turn is not ready yet.",
            );
          } else if (action === "next") {
            // Any Next failure (503 host_load_pressure, provider_unavailable,
            // etc.) must stay visible — never clear controlError and only
            // recover. Readiness comes from the refreshed snapshot: the turn
            // is still ready, so Next stays enabled for a retry instead of
            // dead-ending as disabled after a transient failure.
            setFailure(null);
            await recoverPlayback();
            setControlError(
              errorText(cause, labelsRef.current.connectionError),
            );
            setBlockedBy(blockingDebate(cause));
          } else if (action === "resume") {
            setControlError(null);
            setFailure(null);
            await recoverPlayback();
          } else {
            setControlError(
              errorText(cause, labelsRef.current.connectionError),
            );
            setBlockedBy(blockingDebate(cause));
          }
        }
      } finally {
        if (controlRequestRef.current === requestToken) {
          controlRequestRef.current = null;
          setBusyAction(null);
          publishAuthority({ commandBusy: false });
        }
      }
    },
    [
      startEarly,
      api,
      recoverPlayback,
      refreshSnapshot,
      syncRefreshedSnapshot,
      mediaRetryNeeded,
      applyPlayback,
      audioPointer,
      busyAction,
      commitDetail,
      connection,
      debateId,
      markControllerReady,
      markConnectionIssue,
      markCurrentAudioDebate,
      outputLanguage,
      readOnly,
      scheduleControllerAcquire,
      scheduleMediaPrepare,
      sendCommand,
      sendControllerAcquire,
      settlePendingReplayAcquire,
      setActiveParticipant,
      setAvatars,
      setVisible,
      pauseAudio,
      publishAuthority,
    ],
  );

  const participantById = useMemo(
    () =>
      new Map(
        detailState.participants.map((participant) => [
          participant.id,
          participant,
        ]),
      ),
    [detailState.participants],
  );
  const currentParticipantId = useMemo(() => {
    const active = playback.current_turn_id
      ? publicTurnById(publicTurns, playback.current_turn_id)
      : null;
    if (active) return active.participant_id;
    if (visibleTurn?.id === playback.current_turn_id && activeParticipantId)
      return activeParticipantId;
    const replayVisible =
      visibleTurn?.id === playback.current_turn_id ? visibleTurn : null;
    return replayVisible?.participant_id ?? null;
  }, [activeParticipantId, playback.current_turn_id, publicTurns, visibleTurn]);
  const derivedAvatars = useMemo(() => {
    const resolvedTurn = playback.current_turn_id
      ? publicTurnById(publicTurns, playback.current_turn_id)
      : null;
    return deriveAvatarStates(
      detailState.participants,
      playback,
      avatarEventStates,
      activeParticipantId ?? resolvedTurn?.participant_id,
    );
  }, [
    activeParticipantId,
    avatarEventStates,
    detailState.participants,
    playback,
    publicTurns,
  ]);
  const isTerminal =
    detailState.status === "failed" ||
    detailState.status === "stopped" ||
    (playback.mode !== "replay" && TERMINAL_PLAYBACK.includes(playback.status));
  const replayableTerminalSource = isReplayableTerminalSource(
    detailState,
    audioPointer,
    debateId,
  );
  const canReplay =
    !readOnly &&
    replayAudioAvailable(detailState, audioPointer, debateId) &&
    publicTurns.length > 0 &&
    (detailState.status === "debate_finished" ||
      detailState.status === "completed") &&
    playback.mode === "live" &&
    playback.status === "completed" &&
    connectionIssue === null &&
    (controllerReady || replayableTerminalSource);
  const finalBoundary = atFinalBoundary(detailState, playback);
  const finalActionLabel =
    finalBoundary && !detailState.final_input_frozen
      ? "Final"
      : finalBoundary && !playback.next_turn_ready
        ? "Preparing"
        : labels.next;
  const canAdvance =
    (playback.status === "playing" ||
      playback.status === "paused" ||
      (mediaRetryNeeded && ["ready", "paused"].includes(playback.status)) ||
      (playback.status === "waiting_next" &&
        (playback.next_turn_ready ||
          (finalBoundary && !detailState.final_input_frozen)))) &&
    controllerReady &&
    busyAction === null &&
    (playback.mode === "live" || playback.mode === "replay");
  const activeVisibleTurn =
    visibleTurn && visibleTurn.id === playback.current_turn_id
      ? visibleTurn
      : null;
  const activeRoundPhase = visibleRoundPhase(activeVisibleTurn, detailState);
  // Only whoever is speaking. Three idle faces beside the speeches told a
  // classroom nothing and took the width the speeches needed; before anyone
  // speaks the first participant stands in so the column is never empty.
  const speakingParticipants = (() => {
    const current = detailState.participants.find(
      (participant) => participant.id === currentParticipantId,
    );
    if (current) return [current];
    return detailState.participants.slice(0, 1);
  })();

  const replayAudioUnavailable =
    publicTurns.length > 0 &&
    (detailState.status === "debate_finished" ||
      detailState.status === "completed") &&
    !replayAudioAvailable(detailState, audioPointer, debateId);
  const phase = deriveClassroomPhase(
    detailState.status,
    playback.status,
    playback.mode,
    busyAction !== null || actionInFlight,
  );
  const visibleStatus =
    phase === "ready"
      ? labels.phaseReady
      : phase === "in_progress"
        ? labels.phaseInProgress
        : phase === "waiting"
          ? labels.phaseWaiting
          : phase === "finished"
            ? labels.phaseFinished
            : phase === "failed"
              ? labels.debateFailed
              : labels.debateStopped;
  const terminalConnectionContext = isTerminalConnectionContext({
    ...detailState,
    playback,
  });
  const suppressConnectionUi =
    connectionIssue === "terminal" ||
    (terminalConnectionContext &&
      (connectionIssue === null ||
        connectionIssue === "network" ||
        connectionIssue === "sequence_gap"));
  const connectionIssueCopy =
    connectionIssue === "superseded"
      ? labels.connectionSuperseded
      : connectionIssue === "session_expired"
        ? labels.connectionSessionExpired
        : connectionIssue === "origin_mismatch"
          ? labels.connectionOriginMismatch
          : connectionIssue === "sequence_gap"
            ? labels.connectionSequenceGap
            : connectionIssue === "network"
              ? labels.connectionDisconnected
              : null;
  const connectionCopy =
    connectionIssueCopy ??
    (connection === "connected"
      ? labels.connectionReady
      : connection === "disconnected"
        ? labels.connectionDisconnected
        : labels.connectionReconnecting);
  const canReconnectConnection =
    !readOnly &&
    connection === "disconnected" &&
    (connectionIssue === "network" || connectionIssue === "sequence_gap");
  // Every cause named an issue but only two of them offered anything to press,
  // so a teacher read an accurate diagnosis and had no way to act on it. Each
  // cause gets the one action that actually resolves it.
  const connectionRecovery: {
    label: string;
    kind: "sign-in" | "reload";
  } | null = readOnly
    ? null
    : connectionIssue === "session_expired"
      ? { label: labels.connectionSignIn ?? "", kind: "sign-in" }
      : connectionIssue === "superseded" ||
          connectionIssue === "origin_mismatch"
        ? { label: labels.connectionReload ?? "", kind: "reload" }
        : null;
  const showConnectionPill =
    !suppressConnectionUi &&
    (connectionIssue === null || connectionIssue === "network");

  return (
    <section
      className={`${styles.stage}${className ? ` ${className}` : ""}`}
      data-connection={connection}
      data-connection-reason={connectionIssue ?? "none"}
      data-last-sequence={lastSequence}
      data-playback-mode={playback.mode}
      data-playback-status={playback.status}
      data-classroom-phase={phase}
      aria-label={labels.stageTitle}
    >
      {/* No heading of its own: the page already titles this stage with the
          same topic, and the status it used to carry now sits with the
          controls under the face. A second copy of the title told a reader
          nothing and pushed the debate itself further down. */}

      {!suppressConnectionUi && connection !== "connected" ? (
        <div className={styles.connectionOverlay} role="status">
          <span className={styles.overlayDot} aria-hidden="true" />
          {connectionCopy}
          {connectionIssue === null ||
          connectionIssue === "network" ||
          connectionIssue === "sequence_gap" ? (
            <small>{labels.connectionWaiting}</small>
          ) : null}
          {canReconnectConnection ? (
            <button
              className={styles.reconnectButton}
              type="button"
              onClick={reconnect}
              disabled={reconnectBusy}
            >
              {reconnectBusy ? labels.connectionReconnecting : labels.reconnect}
            </button>
          ) : connectionRecovery ? (
            <button
              className={styles.reconnectButton}
              onClick={() => {
                if (connectionRecovery.kind === "sign-in") {
                  window.location.href = "/";
                } else {
                  window.location.reload();
                }
              }}
              type="button"
            >
              {connectionRecovery.label}
            </button>
          ) : null}
        </div>
      ) : null}

      <div className={styles.stageColumns}>
        <div
          className={styles.avatarColumn}
          role="list"
          aria-label={labels.stageTitle}
        >
          {speakingParticipants.map((participant) => {
            const visual =
              derivedAvatars.find(
                (item) => item.participant_id === participant.id,
              ) ??
              deriveAvatarStates(
                [participant],
                playback,
                [],
                currentParticipantId === participant.id ? participant.id : null,
              )[0];
            const isCurrent = participant.id === currentParticipantId;
            return (
              <article
                className={`${styles.avatarCard}${isCurrent ? ` ${styles.avatarCardCurrent}` : ""}`}
                data-current={isCurrent ? "true" : "false"}
                data-motion-state={visual?.motion_state ?? "idle"}
                data-expression={visual?.expression ?? "neutral"}
                key={participant.id}
                role="listitem"
                aria-label={`${participant.agent_name} ${visual?.motion_state ?? "idle"}`}
              >
                <div className={styles.avatarCardTop}>
                  <span className={styles.slotMark}>{participant.slot}</span>
                  {isCurrent ? (
                    <span className={styles.currentMark}>{labels.current}</span>
                  ) : null}
                </div>
                <AvatarPreview
                  className={styles.avatar}
                  config={participant.avatar_config}
                  fallbackLabel={participant.agent_name}
                  state={visual?.motion_state ?? "idle"}
                />
                <div className={styles.avatarIdentity}>
                  <h2>{participant.agent_name}</h2>
                  <span>{participant.version_label}</span>
                </div>
              </article>
            );
          })}

          {/* Controls and status sit in the blank space under the face
              instead of in bands of their own above the columns, so the
              stage reads as two rectangles ending on the same line. */}
          <div className={styles.stagePanel}>
            <div className={styles.statusCluster}>
              {showConnectionPill ? (
                <span
                  className={styles.connectionPill}
                  data-state={connection}
                  role="status"
                >
                  {connectionCopy}
                </span>
              ) : null}
            </div>
            {!readOnly ? (
              <div className={styles.controlsArea}>
                <div
                  className={styles.controlButtons}
                  role="group"
                  aria-label={labels.stageTitle}
                >
                  <button
                    className="primary-action"
                    type="button"
                    disabled={
                      busyAction !== null || detailState.status !== "draft"
                    }
                    onClick={() => void runControl("start")}
                  >
                    {labels.start}
                  </button>
                  <button
                    className="primary-action"
                    type="button"
                    disabled={!canAdvance}
                    onClick={() => void runControl("next")}
                  >
                    {finalActionLabel}
                  </button>
                </div>
                {busyAction ? (
                  <p className={styles.busyMessage} role="status">
                    {labels.controlBusy}
                  </p>
                ) : null}
              </div>
            ) : null}

            {/* Back, End and the classroom-interaction entry sit under Start
                and Next rather than up in the page header. They belong with
                the other things a teacher presses, and the header had grown a
                row of links that repeated what the stage already offered. */}
            {headerActions ? (
              <div className={styles.panelActions}>{headerActions}</div>
            ) : null}

            <audio
              ref={audioRef}
              aria-label={labels.audioLabel}
              preload="auto"
              onEnded={onAudioEnded}
              onError={onAudioError}
              onTimeUpdate={onAudioTimeUpdate}
            />
          </div>
        </div>

        <div className={styles.speechColumn}>
          {failure && failure !== labels.retryReason ? (
            <DismissibleAlert
              as="div"
              className={styles.failureCard}
              resetKey={failure}
            >
              {failure}
            </DismissibleAlert>
          ) : null}

          {providerGate ? (
            <section
              className={styles.providerGateCard}
              data-testid="provider-query-gate"
              aria-label={labels.providerGateTitle}
            >
              <strong>{labels.providerGateTitle}</strong>
              <a
                href={`/teacher/provider-approvals/debates/${debateId}`}
                target="_blank"
                rel="noreferrer"
              >
                {labels.providerGateReviewAll}
              </a>
              {providerGate.loading ? (
                <span>{labels.providerGateLoading}</span>
              ) : providerGate.error ? (
                <DismissibleAlert as="span">
                  {providerGate.error}
                </DismissibleAlert>
              ) : providerGate.value?.items.length ? (
                <ul>
                  {providerGate.value.items
                    .filter(
                      (item) =>
                        item.manifest_hash ===
                        providerGate.selectedManifestHash,
                    )
                    .map((item) => (
                      <li key={item.manifest_hash}>
                        {item.confirmed ? (
                          <span>{labels.providerGateConfirmed}</span>
                        ) : (
                          <a
                            href={`/teacher/provider-disclosures/${item.manifest_hash}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {labels.providerGateReview}
                          </a>
                        )}
                        {item.confirmed && item.turn_id ? (
                          <button
                            type="button"
                            disabled={providerRetryBusy || readOnly}
                            onClick={() =>
                              void retryProviderPreparation(
                                item.turn_id as string,
                              )
                            }
                          >
                            {labels.providerGateRetry}
                          </button>
                        ) : null}
                      </li>
                    ))}
                </ul>
              ) : (
                <span>{labels.providerGateEmpty}</span>
              )}
            </section>
          ) : null}

          {controlError ? (
            <DismissibleAlert
              as="div"
              className={styles.failureCard}
              resetKey={controlError}
            >
              <span>{controlError}</span>
              {blockedBy ? (
                <>
                  <span className={styles.blockingTopic}>
                    {blockedBy.topic}
                  </span>
                </>
              ) : null}
            </DismissibleAlert>
          ) : null}
          {replayAudioUnavailable ? (
            <DismissibleAlert
              as="div"
              className={styles.failureCard}
              role="status"
            >
              {labels.audioNotRetained}
            </DismissibleAlert>
          ) : null}
          {/* The panel under the face already carries this state. A second
              wording of it at the top-left of the speeches said the same
              thing twice and pushed the first speech down. */}

          <SpeechStream
            describe={(participantId) => {
              const owner = participantById.get(participantId);
              return {
                slot: owner?.slot ?? "",
                name: owner?.agent_name ?? participantId,
              };
            }}
            emptyMessage={labels.noPublishedSpeech ?? ""}
            labels={labels}
            status={visibleStatus}
            phaseOf={(turn) => {
              const phase = visibleRoundPhase(
                turn as unknown as VisiblePlaybackTurn,
                detailState,
              );
              return phase ? phaseLabel(phase, labels) : null;
            }}
            onReplayAll={readOnly ? undefined : () => void runControl("replay")}
            replayAllDisabled={busyAction !== null || !canReplay}
            turns={publicTurns as unknown as StreamTurn[]}
          />
        </div>
      </div>
    </section>
  );
}
