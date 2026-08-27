"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type SyntheticEvent,
} from "react";

import type {
  DebateDetail,
  DebatePlaybackState,
  DebateTurn,
  IdempotencyHandle,
} from "../../../lib/api";
import { createIdempotencyHandle } from "../../../lib/api";
import {
  AvatarPreview,
  AVATAR_EXPRESSIONS,
  AVATAR_EXPRESSION_STRENGTHS,
  AVATAR_STATES,
  type AvatarExpression,
  type AvatarState,
} from "../../avatar";
import styles from "./debate-stage.module.css";
import { resolvePlaybackStageLabels } from "./labels";
import {
  consumeEventSequence,
  debateSocketUrl,
  deriveAvatarStates,
  isSafeMediaUrl,
  parsePlaybackEvent,
  parsePrivatePlaybackMessage,
  publicTurnById,
  visibleTurnFromPlaybackStarted,
} from "./protocol";
import type {
  AvatarVisualState,
  DebateStageProps,
  PlaybackAction,
  PlaybackEvent,
  PlaybackSocket,
  PrivatePlaybackMessage,
  VisiblePlaybackTurn,
} from "./types";

type ConnectionState =
  "connecting" | "connected" | "reconnecting" | "disconnected";
type ControlAction =
  "start" | "pause" | "resume" | "skip" | "stop" | "replay" | "replay-turn";

const TERMINAL_PLAYBACK: readonly DebatePlaybackState["status"][] = [
  "completed",
  "stopped",
];
const TERMINAL_DEBATE: readonly DebateDetail["status"][] = [
  "completed",
  "failed",
  "stopped",
];

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
    value === "completed" ||
    value === "stopped"
  );
}

function isPlaybackMode(value: unknown): value is DebatePlaybackState["mode"] {
  return value === "live" || value === "replay";
}

function normaliseSources(value: unknown): VisiblePlaybackTurn["sources"] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((source) => {
    if (!isRecord(source) || !isNonEmptyString(source.source_filename))
      return [];
    return [
      {
        source_filename: source.source_filename,
        ...(isNonEmptyString(source.chunk_id)
          ? { chunk_id: source.chunk_id }
          : {}),
      },
    ];
  });
}

function normalisePublicTurns(value: unknown): VisiblePlaybackTurn[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isRecord(item)) return [];
    if (
      !isNonEmptyString(item.id) ||
      !isNonEmptyString(item.participant_id) ||
      !isNonEmptyString(item.speech)
    ) {
      return [];
    }
    return [
      {
        id: item.id,
        participant_id: item.participant_id,
        round_no: integer(item.round_no, 1),
        turn_index: integer(item.turn_index, 0),
        speech: item.speech,
        sources: normaliseSources(item.sources),
      },
    ];
  });
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
  const currentTurnId = isNonEmptyString(value.current_turn_id)
    ? value.current_turn_id
    : value.current_turn_id === null
      ? null
      : (current.current_turn_id ?? null);
  return {
    status: isPlaybackStatus(value.status) ? value.status : current.status,
    mode: isPlaybackMode(value.mode) ? value.mode : current.mode,
    current_turn_id: currentTurnId,
    cursor_ms: Math.max(0, integer(value.cursor_ms, current.cursor_ms)),
    playback_rate: numberValue(value.playback_rate, current.playback_rate),
    control_version: Math.max(
      0,
      integer(value.control_version, current.control_version),
    ),
  };
}

function errorText(cause: unknown, fallback: string): string {
  if (cause instanceof Error && cause.message.trim()) return cause.message;
  if (isRecord(cause) && isNonEmptyString(cause.message)) return cause.message;
  return fallback;
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

function statusCopy(
  detailStatus: DebateDetail["status"],
  playbackStatus: DebatePlaybackState["status"],
  labels: ReturnType<typeof resolvePlaybackStageLabels>,
): string {
  if (detailStatus === "debate_finished" || detailStatus === "completed") {
    return labels.debateComplete;
  }
  if (detailStatus === "stopped" || playbackStatus === "stopped") {
    return labels.debateStopped;
  }
  if (detailStatus === "failed") return labels.debateFailed;
  if (playbackStatus === "preparing") return labels.statusPreparing;
  if (playbackStatus === "ready") return labels.statusReady;
  if (playbackStatus === "playing") return labels.statusPlaying;
  if (playbackStatus === "paused") return labels.statusPaused;
  return labels.debateComplete;
}

export function DebateStage({
  debateId,
  detail,
  api,
  onDetailChange,
  refreshSnapshot,
  socketFactory,
  socketUrl,
  labels: suppliedLabels,
  readOnly = false,
  expectedCurrentAudioDebateId = null,
  className,
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
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [lastSequence, setLastSequence] = useState(detail.last_sequence);
  const [controllerReady, setControllerReady] = useState(false);
  const [activeParticipantId, setActiveParticipantId] = useState<string | null>(
    null,
  );
  const [busyAction, setBusyAction] = useState<ControlAction | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [controlError, setControlError] = useState<string | null>(null);

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
  const controlVersionRef = useRef(playback.control_version);
  const pendingActionRef = useRef<PlaybackAction>("start");
  const prepareKeyRef = useRef<string | null>(null);
  const preparedMediaKeyRef = useRef<string | null>(null);
  const audioTurnRef = useRef<string | null>(null);
  const audioActionRef = useRef<PlaybackAction>("start");
  const startedAckRef = useRef(false);
  const cursorMsRef = useRef(playback.cursor_ms);
  const mountedRef = useRef(false);
  const closingRef = useRef(false);
  const reconnectTimerRef = useRef<number | null>(null);
  const connectRef = useRef<((refresh: boolean) => Promise<void>) | undefined>(
    undefined,
  );
  const startIdempotencyRef = useRef<IdempotencyHandle | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const labelsRef = useRef(labels);

  const markControllerReady = useCallback((value: boolean) => {
    controllerReadyRef.current = value;
    setControllerReady(value);
  }, []);

  useEffect(() => {
    labelsRef.current = labels;
  }, [labels]);

  const commitDetail = useCallback(
    (next: DebateDetail, notify = true) => {
      detailRef.current = next;
      playbackRef.current = next.playback;
      controlVersionRef.current = next.playback.control_version;
      setDetailState(next);
      setPlayback(next.playback);
      if (notify) onDetailChange?.(next);
    },
    [onDetailChange],
  );

  const updatePublicTurns = useCallback(
    (next: VisiblePlaybackTurn[]) => {
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
    [onDetailChange],
  );

  const pauseAudio = useCallback((clearSource = false) => {
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
      startedAckRef.current = false;
      cursorMsRef.current = 0;
    }
  }, []);

  const sendCommand = useCallback(
    (command: Record<string, unknown>): boolean => {
      const socket = socketRef.current;
      if (!socket) return false;
      try {
        socket.send(JSON.stringify(command));
        return true;
      } catch {
        setConnection("reconnecting");
        return false;
      }
    },
    [],
  );

  const sendControllerAcquire = useCallback(() => {
    if (
      readOnly ||
      detailRef.current.status === "draft" ||
      controllerReadyRef.current ||
      acquirePendingRef.current
    )
      return;
    acquirePendingRef.current = true;
    const sent = sendCommand({
      command_id: makeId(),
      command_type: "playback.controller.acquire",
      command_version: 1,
      debate_id: debateId,
      expected_control_version: controlVersionRef.current,
    });
    if (!sent) acquirePendingRef.current = false;
  }, [debateId, readOnly, sendCommand]);

  const requestReconnect = useCallback(() => {
    if (!mountedRef.current || closingRef.current) return;
    pauseAudio(false);
    setConnection("reconnecting");
    markControllerReady(false);
    acquirePendingRef.current = false;
    controllerEpochRef.current = null;
    setFailure(labelsRef.current.connectionReconnecting);
    try {
      socketRef.current?.close(1012, "sequence recovery");
    } catch {
      // The close callback will still schedule recovery for normal sockets.
    }
    if (reconnectTimerRef.current === null) {
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        void connectRef.current?.(true);
      }, 700);
    }
  }, [markControllerReady, pauseAudio]);

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
      };
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
    [onDetailChange],
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
    ) => {
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
      setFailure(labelsRef.current.retryReason);
      pauseAudio(false);
    },
    [debateId, pauseAudio, readOnly, sendCommand],
  );

  const handlePrivateMessage = useCallback(
    (message: PrivatePlaybackMessage) => {
      switch (message.message_type) {
        case "controller.acquired":
          if (
            !message.controller_epoch ||
            message.control_version === undefined
          )
            return;
          controllerEpochRef.current = message.controller_epoch;
          controlVersionRef.current = message.control_version;
          acquirePendingRef.current = false;
          markControllerReady(true);
          setFailure(null);
          applyPlayback({ control_version: message.control_version });
          if (playbackRef.current.status === "ready") {
            window.setTimeout(() => ensureMediaPrepare(), 0);
          }
          return;
        case "media.prepared": {
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
          preparedMediaKeyRef.current = key;
          audioTurnRef.current = message.turn_id;
          audioActionRef.current = action;
          startedAckRef.current = false;
          const audio = audioRef.current;
          if (!audio) return;
          audio.src = message.media_url;
          audio.playbackRate = Math.min(
            1.25,
            Math.max(0.95, current.playback_rate),
          );
          cursorMsRef.current = current.cursor_ms;
          try {
            audio.currentTime = Math.max(0, current.cursor_ms / 1000);
          } catch {
            // A not-yet-loaded media element may reject a seek; playback starts at its saved server cursor.
          }
          let playResult: Promise<void> | void;
          try {
            playResult = audio.play();
          } catch (cause) {
            sendPlayFailure(
              isNotAllowedError(cause) ? "autoplay_blocked" : "unknown",
              cause,
            );
            return;
          }
          Promise.resolve(playResult).then(
            () => {
              if (
                !mountedRef.current ||
                message.controller_epoch !== controllerEpochRef.current ||
                audioTurnRef.current !== message.turn_id
              ) {
                return;
              }
              startedAckRef.current = true;
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
              );
            },
          );
          return;
        }
        case "controller.revoked":
          controllerEpochRef.current = null;
          acquirePendingRef.current = false;
          markControllerReady(false);
          pauseAudio(true);
          setVisible(null);
          setAvatars([]);
          setActiveParticipant(null);
          if (message.reason === "start_next") {
            applyPlayback(
              { status: "completed", mode: "live", current_turn_id: null },
              detailRef.current.status,
            );
          }
          setConnection("disconnected");
          setFailure(
            message.reason === "start_next"
              ? null
              : labelsRef.current.connectionReconnecting,
          );
          return;
        case "command.rejected":
        case "command.duplicate":
          acquirePendingRef.current = false;
          if (message.current_control_version !== undefined) {
            controlVersionRef.current = message.current_control_version;
          }
          setControlError(message.code ?? labelsRef.current.connectionError);
          if (message.recoverable) {
            setFailure(labelsRef.current.retryReason);
          }
          if (
            message.message_type === "command.rejected" &&
            message.code === "session_revoked"
          ) {
            controllerEpochRef.current = null;
            acquirePendingRef.current = false;
            markControllerReady(false);
            pauseAudio(true);
            setVisible(null);
            setAvatars([]);
            setActiveParticipant(null);
            setConnection("disconnected");
            try {
              socketRef.current?.close(4401, "session revoked");
            } catch {
              // The server has already rejected this session; cleanup is local.
            }
          }
          return;
      }
    },
    [
      applyPlayback,
      debateId,
      ensureMediaPrepare,
      markControllerReady,
      pauseAudio,
      sendCommand,
      sendPlayFailure,
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
      const nextPlayback = playbackFromWire(
        payload.playback,
        playbackRef.current,
      );
      pendingActionRef.current =
        nextPlayback.mode === "replay" ? "replay" : "start";
      playbackRef.current = nextPlayback;
      controlVersionRef.current = nextPlayback.control_version;
      setPlayback(nextPlayback);
      const nextStatus = isDebateStatus(payload.debate_status)
        ? payload.debate_status
        : detailRef.current.status;
      const nextDetail: DebateDetail = {
        ...detailRef.current,
        status: nextStatus,
        last_sequence: decision.nextSequence,
        playback: nextPlayback,
        public_turns: turns as DebateTurn[],
      };
      detailRef.current = nextDetail;
      setDetailState(nextDetail);
      onDetailChange?.(nextDetail);
      const snapshotStates = normaliseAvatarStates(payload.avatar_states);
      if (snapshotStates.length > 0) setAvatars(snapshotStates);
      const snapshotTurn = publicTurnById(turns, nextPlayback.current_turn_id);
      if (snapshotTurn) {
        setActiveParticipant(snapshotTurn.participant_id);
        if (
          nextPlayback.status === "playing" ||
          nextPlayback.status === "paused"
        ) {
          setVisible(snapshotTurn);
        }
      } else if (
        nextPlayback.status === "playing" ||
        nextPlayback.status === "paused"
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
      if (!readOnly && nextStatus !== "draft") {
        window.setTimeout(() => sendControllerAcquire(), 0);
      }
      setFailure(null);
    },
    [
      onDetailChange,
      pauseAudio,
      requestReconnect,
      readOnly,
      sendControllerAcquire,
      setActiveParticipant,
      setAvatars,
      setVisible,
      updatePublicTurns,
    ],
  );

  const handleEvent = useCallback(
    (event: PlaybackEvent) => {
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
      switch (event.event_type) {
        case "turn.preparing":
          if (isNonEmptyString(payload.turn_id)) {
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
          if (isNonEmptyString(payload.turn_id)) {
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
            window.setTimeout(() => ensureMediaPrepare(), 0);
          }
          break;
        case "playback.started": {
          if (!isNonEmptyString(payload.turn_id)) break;
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
            setFailure(labelsRef.current.noPublishedSpeech);
          }
          setAvatars(normaliseAvatarStates(payload.avatar_states));
          pendingActionRef.current =
            playbackRef.current.mode === "replay" ? "replay" : "start";
          applyPlayback(
            {
              status: "playing",
              current_turn_id: payload.turn_id,
              cursor_ms: Math.max(0, integer(payload.cursor_ms, 0)),
              playback_rate: numberValue(
                payload.playback_rate,
                playbackRef.current.playback_rate,
              ),
            },
            "running",
          );
          setFailure(null);
          break;
        }
        case "replay.started": {
          if (!isNonEmptyString(payload.turn_id)) break;
          pendingActionRef.current = "replay";
          const replayTurn = visibleTurnFromPublic(payload.turn_id);
          setActiveParticipant(replayTurn?.participant_id ?? null);
          setVisible(replayTurn);
          setAvatars([]);
          applyPlayback(
            {
              status: "playing",
              mode: "replay",
              current_turn_id: payload.turn_id,
              cursor_ms: 0,
            },
            detailRef.current.status,
          );
          break;
        }
        case "playback.paused":
          applyPlayback({
            status: "paused",
            current_turn_id: isNonEmptyString(payload.turn_id)
              ? payload.turn_id
              : playbackRef.current.current_turn_id,
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
            playback_rate: numberValue(
              payload.playback_rate,
              playbackRef.current.playback_rate,
            ),
          });
          pauseAudio(false);
          setAvatars([]);
          break;
        case "playback.resumed":
          pendingActionRef.current = "resume";
          applyPlayback({
            status: "playing",
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
        case "playback.skipped":
          pauseAudio(true);
          applyPlayback({
            status: "preparing",
            cursor_ms: 0,
            control_version: Math.max(
              playbackRef.current.control_version,
              integer(
                payload.control_version,
                playbackRef.current.control_version,
              ),
            ),
          });
          setVisible(null);
          setAvatars([]);
          setActiveParticipant(null);
          break;
        case "playback.completed":
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
              detailRef.current.participants.length * 2
          ) {
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
            applyPlayback({
              status: "preparing",
              cursor_ms: 0,
              control_version: Math.max(
                playbackRef.current.control_version,
                integer(
                  payload.control_version,
                  playbackRef.current.control_version,
                ),
              ),
            });
          }
          setAvatars([]);
          break;
        case "replay.completed":
          pauseAudio(true);
          setVisible(null);
          setAvatars([]);
          setActiveParticipant(null);
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
          void refreshSnapshot?.().then((next) => {
            if (!mountedRef.current || !next) return;
            commitDetail(next);
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
          pauseAudio(true);
          setVisible(null);
          setAvatars([]);
          setActiveParticipant(null);
          controllerEpochRef.current = null;
          acquirePendingRef.current = false;
          markControllerReady(false);
          applyPlayback({ status: "stopped", current_turn_id: null }, "failed");
          setFailure(labelsRef.current.debateFailed);
          break;
        case "debate.stopped":
          pauseAudio(true);
          setVisible(null);
          setAvatars([]);
          setActiveParticipant(null);
          controllerEpochRef.current = null;
          acquirePendingRef.current = false;
          markControllerReady(false);
          applyPlayback(
            { status: "stopped", current_turn_id: null },
            "stopped",
          );
          break;
        case "error":
          setFailure(labelsRef.current.retryReason);
          if (payload.recoverable === true) {
            applyPlayback({ status: "ready" });
          }
          break;
        default:
          break;
      }
      const nextDetail = {
        ...detailRef.current,
        last_sequence: decision.nextSequence,
      };
      detailRef.current = nextDetail;
      setDetailState(nextDetail);
      onDetailChange?.(nextDetail);
    },
    [
      applyPlayback,
      commitDetail,
      ensureMediaPrepare,
      handleSnapshot,
      markControllerReady,
      onDetailChange,
      pauseAudio,
      refreshSnapshot,
      setActiveParticipant,
      requestReconnect,
      setAvatars,
      setVisible,
      updatePublicTurns,
      visibleTurnFromPublic,
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
    (socket: PlaybackSocket) => {
      const onOpen = () => {
        setConnection("connected");
        setFailure(null);
        if (!readOnly) sendControllerAcquire();
      };
      const onMessage = (event: Event) => handleSocketMessage(event);
      const onError = () => {
        setConnection("reconnecting");
        setFailure(labelsRef.current.connectionError);
      };
      const onClose = (event?: Event) => {
        if (!mountedRef.current || closingRef.current) return;
        const closeCode =
          event && "code" in event ? Number((event as CloseEvent).code) : 0;
        if (closeCode === 4401 || closeCode === 4403) {
          setConnection("disconnected");
          acquirePendingRef.current = false;
          markControllerReady(false);
          controllerEpochRef.current = null;
          pauseAudio(true);
          setVisible(null);
          setAvatars([]);
          setActiveParticipant(null);
          return;
        }
        setConnection("reconnecting");
        acquirePendingRef.current = false;
        markControllerReady(false);
        controllerEpochRef.current = null;
        pauseAudio(false);
        if (reconnectTimerRef.current === null) {
          reconnectTimerRef.current = window.setTimeout(() => {
            reconnectTimerRef.current = null;
            void connectRef.current?.(true);
          }, 700);
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
      handleSocketMessage,
      markControllerReady,
      pauseAudio,
      readOnly,
      sendControllerAcquire,
      setActiveParticipant,
      setAvatars,
      setVisible,
    ],
  );

  const connect = useCallback(
    async (refresh: boolean) => {
      if (!mountedRef.current || closingRef.current) return;
      if (refresh && refreshSnapshot) {
        try {
          const next = await refreshSnapshot();
          if (!mountedRef.current || closingRef.current) return;
          commitDetail(next, false);
          publicTurnsRef.current = normalisePublicTurns(next.public_turns);
          setPublicTurns(publicTurnsRef.current);
          sequenceRef.current = next.last_sequence;
          setLastSequence(next.last_sequence);
          setFailure(null);
        } catch (cause) {
          setFailure(errorText(cause, labelsRef.current.connectionError));
        }
      }
      if (!mountedRef.current || closingRef.current) return;
      socketCleanupRef.current?.();
      socketCleanupRef.current = null;
      try {
        const url = socketUrl ?? debateSocketUrl(debateId);
        const socket = socketFactory
          ? socketFactory(url)
          : (new WebSocket(url) as unknown as PlaybackSocket);
        socketRef.current = socket;
        setConnection("connecting");
        installSocket(socket);
      } catch (cause) {
        setConnection("disconnected");
        setFailure(errorText(cause, labelsRef.current.connectionError));
      }
    },
    [
      commitDetail,
      debateId,
      installSocket,
      refreshSnapshot,
      socketFactory,
      socketUrl,
    ],
  );
  useEffect(() => {
    const timer = window.setTimeout(() => {
      detailRef.current = detail;
      playbackRef.current = detail.playback;
      controlVersionRef.current = detail.playback.control_version;
      setDetailState(detail);
      setPlayback(detail.playback);
      const turns = normalisePublicTurns(detail.public_turns);
      publicTurnsRef.current = turns;
      setPublicTurns(turns);
      sequenceRef.current = detail.last_sequence;
      setLastSequence(detail.last_sequence);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [detail]);

  useEffect(() => {
    mountedRef.current = true;
    closingRef.current = false;
    connectRef.current = connect;
    const timer = window.setTimeout(() => void connect(false), 0);
    return () => {
      window.clearTimeout(timer);
      mountedRef.current = false;
      closingRef.current = true;
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
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
  }, [connect, pauseAudio]);

  const onAudioEnded = useCallback(() => {
    if (readOnly || !startedAckRef.current) return;
    const turnId = audioTurnRef.current;
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
    if (!audio || !audioTurnRef.current || readOnly) return;
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
    async (action: ControlAction, turnId?: string) => {
      if (readOnly || busyAction !== null) return;
      setBusyAction(action);
      setControlError(null);
      setFailure(null);
      try {
        const current = playbackRef.current;
        if (action === "start") {
          pendingActionRef.current = "start";
          if (
            expectedCurrentAudioDebateId &&
            !window.confirm(labelsRef.current.replaceRetainedAudioConfirm)
          ) {
            return;
          }
          const idempotency =
            startIdempotencyRef.current ?? createIdempotencyHandle();
          startIdempotencyRef.current = idempotency;
          const started = await api.startDebate(
            debateId,
            {
              expected_revision: detailRef.current.revision,
              expected_current_audio_debate_id: expectedCurrentAudioDebateId,
              confirm_previous_audio_cleanup: Boolean(
                expectedCurrentAudioDebateId,
              ),
            },
            { idempotency },
          );
          // A draft socket is observation-only.  Starting the Debate changes
          // the server authority boundary, so acquire a fresh controller
          // epoch only after the start response is committed.
          controllerEpochRef.current = null;
          acquirePendingRef.current = false;
          markControllerReady(false);
          commitDetail(started);
          window.setTimeout(() => sendControllerAcquire(), 0);
          return;
        }
        if (action === "pause") {
          const next = await api.pauseDebate(debateId, current.control_version);
          pauseAudio(false);
          applyPlayback(next);
          return;
        }
        if (action === "resume") {
          pendingActionRef.current = "resume";
          const next = await api.resumeDebate(
            debateId,
            current.control_version,
          );
          applyPlayback(next);
          window.setTimeout(() => ensureMediaPrepare(), 0);
          return;
        }
        if (action === "skip") {
          const next = await api.skipDebateTurn(
            debateId,
            current.control_version,
          );
          pauseAudio(true);
          applyPlayback(next);
          return;
        }
        if (action === "stop") {
          const next = await api.stopDebate(debateId, current.control_version);
          pauseAudio(true);
          setVisible(null);
          setAvatars([]);
          setActiveParticipant(null);
          controllerEpochRef.current = null;
          acquirePendingRef.current = false;
          markControllerReady(false);
          commitDetail(next);
          return;
        }
        if (action === "replay") {
          pendingActionRef.current = "replay";
          const next = await api.replayDebate(
            debateId,
            current.control_version,
          );
          setVisible(null);
          applyPlayback(next);
          window.setTimeout(() => ensureMediaPrepare(), 0);
          return;
        }
        if (!turnId) return;
        pendingActionRef.current = "replay";
        const next = await api.replayDebateTurn(
          debateId,
          turnId,
          current.control_version,
        );
        setVisible(null);
        applyPlayback(next);
        window.setTimeout(() => ensureMediaPrepare(), 0);
      } catch (cause) {
        setControlError(errorText(cause, labelsRef.current.connectionError));
      } finally {
        setBusyAction(null);
      }
    },
    [
      api,
      applyPlayback,
      busyAction,
      commitDetail,
      debateId,
      ensureMediaPrepare,
      expectedCurrentAudioDebateId,
      markControllerReady,
      pauseAudio,
      readOnly,
      setActiveParticipant,
      setAvatars,
      setVisible,
      sendControllerAcquire,
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
    if (activeParticipantId) return activeParticipantId;
    if (active) return active.participant_id;
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
    TERMINAL_DEBATE.includes(detailState.status) ||
    TERMINAL_PLAYBACK.includes(playback.status);
  const canReplay =
    !readOnly &&
    publicTurns.length > 0 &&
    (detailState.status === "debate_finished" ||
      detailState.status === "completed") &&
    playback.status !== "playing";
  const activeVisibleTurn =
    visibleTurn && visibleTurn.id === playback.current_turn_id
      ? visibleTurn
      : null;
  const visibleStatus = statusCopy(detailState.status, playback.status, labels);

  return (
    <section
      className={`${styles.stage}${className ? ` ${className}` : ""}`}
      data-connection={connection}
      data-playback-status={playback.status}
      aria-label={labels.stageTitle}
    >
      <div className={styles.stageHeader}>
        <div>
          <span className={styles.eyebrow}>{labels.stageTitle}</span>
          <h1>{detailState.topic}</h1>
          <p>{labels.stageDescription}</p>
        </div>
        <div className={styles.statusCluster}>
          <span
            className={styles.connectionPill}
            data-state={connection}
            role="status"
          >
            {connection === "connected"
              ? labels.connectionReady
              : connection === "connecting"
                ? labels.connectionReconnecting
                : connection === "reconnecting"
                  ? labels.connectionReconnecting
                  : labels.connectionDisconnected}
          </span>
          <span className={styles.playbackStatus}>{visibleStatus}</span>
        </div>
      </div>

      {connection !== "connected" ? (
        <div className={styles.connectionOverlay} role="status">
          <span className={styles.overlayDot} aria-hidden="true" />
          {connection === "disconnected"
            ? labels.connectionDisconnected
            : labels.connectionReconnecting}
          <small>{labels.audioPaused}</small>
        </div>
      ) : null}

      <div
        className={styles.avatarGrid}
        role="list"
        aria-label={labels.stageTitle}
      >
        {detailState.participants.map((participant) => {
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
      </div>

      <div className={styles.stageColumns}>
        <div className={styles.speechColumn}>
          {activeVisibleTurn ? (
            <section className={styles.speechCard} aria-live="polite">
              <div className={styles.speechHeader}>
                <div>
                  <span className={styles.eyebrow}>{labels.current}</span>
                  <h2>
                    {participantById.get(activeVisibleTurn.participant_id)
                      ?.agent_name ?? activeVisibleTurn.participant_id}
                  </h2>
                </div>
                <span className={styles.roundMark}>
                  {labels.round} {activeVisibleTurn.round_no}
                </span>
              </div>
              <p className={styles.speechText}>{activeVisibleTurn.speech}</p>
              <div className={styles.sourceBlock}>
                <h3>{labels.sources}</h3>
                {activeVisibleTurn.sources.length > 0 ? (
                  <ul>
                    {activeVisibleTurn.sources.map((source) => (
                      <li
                        key={`${activeVisibleTurn.id}:${source.source_filename}:${source.chunk_id ?? ""}`}
                      >
                        {source.source_filename}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>{labels.noSources}</p>
                )}
              </div>
            </section>
          ) : (
            <section className={styles.waitingCard} role="status">
              {isTerminal
                ? detailState.status === "failed"
                  ? labels.debateFailed
                  : detailState.status === "stopped"
                    ? labels.debateStopped
                    : labels.debateComplete
                : playback.status === "ready" || playback.status === "preparing"
                  ? labels.waitingForAudio
                  : labels.noPublishedSpeech}
            </section>
          )}

          {failure ? (
            <div className={styles.failureCard} role="alert">
              <span>{failure}</span>
              {!readOnly && playback.current_turn_id ? (
                <button
                  className="secondary-action"
                  type="button"
                  onClick={() => {
                    prepareKeyRef.current = null;
                    preparedMediaKeyRef.current = null;
                    setFailure(null);
                    ensureMediaPrepare();
                  }}
                >
                  {labels.retryPlayback}
                </button>
              ) : null}
            </div>
          ) : null}

          {controlError ? (
            <div className={styles.failureCard} role="alert">
              <span>{controlError}</span>
            </div>
          ) : null}
        </div>

        <section className={styles.transcriptCard}>
          <div className={styles.transcriptHeader}>
            <div>
              <span className={styles.eyebrow}>{labels.transcript}</span>
              <h2>{labels.transcript}</h2>
            </div>
            {publicTurns.length ? <span>{publicTurns.length}</span> : null}
          </div>
          {publicTurns.length === 0 ? (
            <p className={styles.emptyTranscript}>{labels.noPublishedSpeech}</p>
          ) : (
            <div className={styles.transcriptList}>
              {publicTurns.map((turn) => {
                const owner = participantById.get(turn.participant_id);
                return (
                  <article className={styles.transcriptItem} key={turn.id}>
                    <div className={styles.transcriptItemTop}>
                      <span>
                        {owner?.slot ?? ""} ·{" "}
                        {owner?.agent_name ?? turn.participant_id}
                      </span>
                      <span>
                        {labels.round} {turn.round_no}
                      </span>
                    </div>
                    <p>{turn.speech}</p>
                    {!readOnly && (
                      <button
                        className="inline-button"
                        type="button"
                        disabled={busyAction !== null || !canReplay}
                        onClick={() => void runControl("replay-turn", turn.id)}
                      >
                        {labels.replayTurn}
                      </button>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </section>
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
              disabled={busyAction !== null || detailState.status !== "draft"}
              onClick={() => void runControl("start")}
            >
              {labels.start}
            </button>
            <button
              className="secondary-action"
              type="button"
              disabled={busyAction !== null || playback.status !== "playing"}
              onClick={() => void runControl("pause")}
            >
              {labels.pause}
            </button>
            <button
              className="secondary-action"
              type="button"
              disabled={
                busyAction !== null ||
                playback.status !== "paused" ||
                !controllerReady
              }
              onClick={() => void runControl("resume")}
            >
              {labels.resume}
            </button>
            <button
              className="secondary-action"
              type="button"
              disabled={
                busyAction !== null ||
                playback.status !== "playing" ||
                playback.mode !== "live"
              }
              onClick={() => void runControl("skip")}
            >
              {labels.skip}
            </button>
            <button
              className={styles.dangerAction}
              type="button"
              disabled={
                busyAction !== null ||
                detailState.status === "draft" ||
                detailState.status === "debate_finished" ||
                TERMINAL_DEBATE.includes(detailState.status)
              }
              onClick={() => void runControl("stop")}
            >
              {labels.stop}
            </button>
            <button
              className="secondary-action"
              type="button"
              disabled={busyAction !== null || !canReplay}
              onClick={() => void runControl("replay")}
            >
              {labels.replayAll}
            </button>
          </div>
          {busyAction ? (
            <p className={styles.busyMessage} role="status">
              {labels.controlBusy}
            </p>
          ) : null}
          {!controllerReady && detailState.status !== "draft" ? (
            <p className={styles.controllerMessage} role="status">
              {labels.controllerWaiting}
            </p>
          ) : null}
        </div>
      ) : null}

      <audio
        ref={audioRef}
        aria-label={labels.audioLabel}
        preload="auto"
        onEnded={onAudioEnded}
        onError={onAudioError}
        onTimeUpdate={onAudioTimeUpdate}
      />
    </section>
  );
}
