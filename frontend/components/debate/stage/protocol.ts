import { normaliseEvidenceTrace } from "../../evidence";
import type { DebateParticipant, DebatePlaybackState } from "../../../lib/api";
import {
  AVATAR_EXPRESSIONS,
  AVATAR_EXPRESSION_STRENGTHS,
  AVATAR_STATES,
  type AvatarExpression,
  type AvatarState,
} from "../../avatar";
import type {
  AvatarVisualState,
  PlaybackConnectionIssue,
  PlaybackEvent,
  PlaybackEventType,
  PrivatePlaybackMessage,
  SegmentSourceDetail,
  SegmentTurnPublic,
  VisiblePlaybackTurn,
} from "./types";

export function connectionIssueFromCloseCode(
  code: number,
): Extract<
  PlaybackConnectionIssue,
  "network" | "session_expired" | "origin_mismatch"
> {
  if (code === 4401) return "session_expired";
  if (code === 4403) return "origin_mismatch";
  return "network";
}

const PLAYBACK_EVENT_TYPES: readonly PlaybackEventType[] = [
  "snapshot",
  "debate.started",
  "round.started",
  "turn.preparing",
  "turn.ready",
  "playback.started",
  "playback.paused",
  "playback.resumed",
  "playback.skipped",
  "playback.completed",
  "playback.waiting_next",
  "replay.started",
  "replay.completed",
  "translation.batch_started",
  "translation.batch_completed",
  "translation.batch_failed",
  "interaction.opened",
  "interaction.vote_created",
  "interaction.barrage_created",
  "interaction.closed",
  "barrage_insight.started",
  "barrage_insight.completed",
  "barrage_insight.failed",
  "report.started",
  "report.completed",
  "report.failed",
  "debate.completed",
  "debate.failed",
  "debate.stopped",
  "error",
];

const PRIVATE_MESSAGE_TYPES: readonly PrivatePlaybackMessage["message_type"][] =
  [
    "controller.acquired",
    "media.prepared",
    "command.rejected",
    "command.duplicate",
    "controller.revoked",
  ];

const UUID_PATTERN =
  "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}";
const MEDIA_URL_PATTERN = new RegExp(
  `^/api/v1/debates/${UUID_PATTERN}/audio/${UUID_PATTERN}\\?media_ticket=[A-Za-z0-9_-]{43}$`,
);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isFiniteNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

/** Parse only the closed event envelope; payload semantics are handled per event. */
export function parsePlaybackEvent(
  value: unknown,
  debateId?: string,
): PlaybackEvent | null {
  if (!isRecord(value)) return null;
  const eventType = value.event_type;
  if (
    !isNonEmptyString(value.event_id) ||
    typeof eventType !== "string" ||
    !(PLAYBACK_EVENT_TYPES as readonly string[]).includes(eventType) ||
    value.event_version !== 1 ||
    !isNonEmptyString(value.debate_id) ||
    (debateId && value.debate_id !== debateId) ||
    !isFiniteNonNegativeInteger(value.sequence) ||
    !isNonEmptyString(value.occurred_at) ||
    !isRecord(value.payload)
  ) {
    return null;
  }
  if (eventType !== "snapshot" && value.sequence < 1) return null;
  return {
    event_id: value.event_id,
    event_type: eventType as PlaybackEventType,
    event_version: 1,
    debate_id: value.debate_id,
    sequence: value.sequence,
    occurred_at: value.occurred_at,
    payload: value.payload,
  };
}

/** Parse private command results without accepting persistent-event fields. */
export function parsePrivatePlaybackMessage(
  value: unknown,
  debateId?: string,
): PrivatePlaybackMessage | null {
  if (!isRecord(value)) return null;
  const messageType = value.message_type;
  if (
    !isNonEmptyString(value.message_id) ||
    typeof messageType !== "string" ||
    !(PRIVATE_MESSAGE_TYPES as readonly string[]).includes(messageType) ||
    value.result_version !== 1 ||
    !isNonEmptyString(value.debate_id) ||
    (debateId && value.debate_id !== debateId) ||
    !isNonEmptyString(value.occurred_at)
  ) {
    return null;
  }
  return {
    message_id: value.message_id,
    message_type: messageType as PrivatePlaybackMessage["message_type"],
    result_version: 1,
    debate_id: value.debate_id,
    occurred_at: value.occurred_at,
    command_id: isNonEmptyString(value.command_id)
      ? value.command_id
      : undefined,
    controller_epoch: isNonEmptyString(value.controller_epoch)
      ? value.controller_epoch
      : undefined,
    turn_id: isNonEmptyString(value.turn_id) ? value.turn_id : undefined,
    media_url: isNonEmptyString(value.media_url) ? value.media_url : undefined,
    expires_at: isNonEmptyString(value.expires_at)
      ? value.expires_at
      : undefined,
    control_version: isFiniteNonNegativeInteger(value.control_version)
      ? value.control_version
      : undefined,
    current_control_version: isFiniteNonNegativeInteger(
      value.current_control_version,
    )
      ? value.current_control_version
      : undefined,
    code: isNonEmptyString(value.code) ? value.code : undefined,
    recoverable:
      typeof value.recoverable === "boolean" ? value.recoverable : undefined,
    reason: isNonEmptyString(value.reason)
      ? (value.reason as PrivatePlaybackMessage["reason"])
      : undefined,
  };
}

export type EventSequenceDecision = {
  accepted: boolean;
  duplicate: boolean;
  gap: boolean;
  nextSequence: number;
};

/**
 * Apply the snapshot watermark/strictly-next sequence rule.  A duplicate is
 * harmless; a gap must stop local advancement until a fresh snapshot arrives.
 */
export function consumeEventSequence(
  lastSequence: number,
  event: Pick<PlaybackEvent, "event_type" | "sequence" | "payload">,
): EventSequenceDecision {
  if (event.event_type === "snapshot") {
    const latest = event.payload.latest_sequence;
    if (isFiniteNonNegativeInteger(latest) && latest <= lastSequence) {
      return {
        accepted: false,
        duplicate: true,
        gap: false,
        nextSequence: lastSequence,
      };
    }
    return isFiniteNonNegativeInteger(latest)
      ? { accepted: true, duplicate: false, gap: false, nextSequence: latest }
      : {
          accepted: false,
          duplicate: false,
          gap: true,
          nextSequence: lastSequence,
        };
  }
  if (event.sequence <= lastSequence) {
    return {
      accepted: false,
      duplicate: true,
      gap: false,
      nextSequence: lastSequence,
    };
  }
  if (event.sequence !== lastSequence + 1) {
    return {
      accepted: false,
      duplicate: false,
      gap: true,
      nextSequence: lastSequence,
    };
  }
  return {
    accepted: true,
    duplicate: false,
    gap: false,
    nextSequence: event.sequence,
  };
}

export const applyEventSequence = consumeEventSequence;

function avatarState(value: unknown, fallback: AvatarState): AvatarState {
  return typeof value === "string" &&
    (AVATAR_STATES as readonly string[]).includes(value)
    ? (value as AvatarState)
    : fallback;
}

function avatarExpression(
  value: unknown,
  fallback: AvatarExpression,
): AvatarExpression {
  return typeof value === "string" &&
    (AVATAR_EXPRESSIONS as readonly string[]).includes(value)
    ? (value as AvatarExpression)
    : fallback;
}

function avatarStrength(
  value: unknown,
  fallback: DebateParticipant["avatar_config"]["expression_strength"],
): DebateParticipant["avatar_config"]["expression_strength"] {
  return typeof value === "string" &&
    (AVATAR_EXPRESSION_STRENGTHS as readonly string[]).includes(value)
    ? (value as DebateParticipant["avatar_config"]["expression_strength"])
    : fallback;
}

function participantDefaultExpression(
  participant: DebateParticipant,
): AvatarExpression {
  const value = participant.avatar_config.default_expression;
  return avatarExpression(value, "neutral");
}

function participantSlot(
  participant: DebateParticipant,
): AvatarVisualState["slot"] {
  return participant.slot;
}

function idleState(participant: DebateParticipant): AvatarVisualState {
  return {
    participant_id: participant.id,
    slot: participantSlot(participant),
    motion_state: "idle",
    expression: participantDefaultExpression(participant),
    expression_strength: participant.avatar_config.expression_strength,
  };
}

function listeningState(participant: DebateParticipant): AvatarVisualState {
  return {
    participant_id: participant.id,
    slot: participantSlot(participant),
    motion_state: "listening",
    expression: "attentive",
    expression_strength: participant.avatar_config.expression_strength,
  };
}

/**
 * Pure state-to-avatar mapping for the V2 stage.  The optional event states
 * win because they are server-authored; the fallback mapping remains useful
 * for preparing/paused/terminal snapshots and deterministic tests.
 */
export function deriveAvatarStates(
  participants: readonly DebateParticipant[],
  playback: Pick<DebatePlaybackState, "status" | "mode" | "current_turn_id">,
  eventStates: readonly AvatarVisualState[] = [],
  currentParticipantId?: string | null,
): AvatarVisualState[] {
  const known = new Map(
    participants.map((participant) => [participant.id, participant]),
  );
  if (playback.status === "waiting_next") {
    return participants.map(idleState);
  }
  if (eventStates.length > 0) {
    return participants.map((participant) => {
      const eventState = eventStates.find(
        (item) => item.participant_id === participant.id,
      );
      if (!eventState) return idleState(participant);
      return {
        participant_id: participant.id,
        slot: participant.slot,
        motion_state: avatarState(eventState.motion_state, "idle"),
        expression: avatarExpression(
          eventState.expression,
          participantDefaultExpression(participant),
        ),
        expression_strength: avatarStrength(
          eventState.expression_strength,
          participant.avatar_config.expression_strength,
        ),
      };
    });
  }

  // PlaybackState stores a turn ID, while the visual grid is keyed by the
  // participant ID. The stage supplies the resolved participant when it has
  // the published turn; a direct ID keeps this helper useful in pure tests.
  const resolvedParticipantId =
    currentParticipantId ?? playback.current_turn_id;
  const currentParticipant = participants.find(
    (participant) =>
      known.has(participant.id) && participant.id === resolvedParticipantId,
  );
  if (!currentParticipant) return participants.map(idleState);

  if (playback.status === "playing") {
    return participants.map((participant) =>
      participant.id === currentParticipant.id
        ? {
            participant_id: participant.id,
            slot: participant.slot,
            motion_state: "speaking",
            expression: participantDefaultExpression(participant),
            expression_strength: participant.avatar_config.expression_strength,
          }
        : listeningState(participant),
    );
  }

  if (playback.status === "preparing" || playback.status === "ready") {
    return participants.map((participant) =>
      participant.id === currentParticipant.id
        ? {
            participant_id: participant.id,
            slot: participant.slot,
            motion_state: "thinking",
            expression: participantDefaultExpression(participant),
            expression_strength: participant.avatar_config.expression_strength,
          }
        : idleState(participant),
    );
  }

  if (playback.status === "paused") {
    return participants.map((participant) =>
      participant.id === currentParticipant.id
        ? idleState(participant)
        : listeningState(participant),
    );
  }

  return participants.map(idleState);
}

function sourceList(value: unknown): VisiblePlaybackTurn["sources"] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isRecord(item) || !isNonEmptyString(item.source_filename)) return [];
    return [
      {
        source_filename: item.source_filename,
        ...(isNonEmptyString(item.chunk_id) ? { chunk_id: item.chunk_id } : {}),
      },
    ];
  });
}

function audioReady(value: unknown): boolean | null | undefined {
  return value === true || value === false || value === null
    ? value
    : undefined;
}

function normaliseSegment(
  value: unknown,
): SegmentTurnPublic["segments"][number] | null {
  if (!isRecord(value) || !isNonEmptyString(value.text)) return null;
  if (!Array.isArray(value.source_ids)) return null;
  if (
    !Object.prototype.hasOwnProperty.call(value, "reply_to") ||
    (value.reply_to !== null && !isNonEmptyString(value.reply_to))
  ) {
    return null;
  }
  const sourceIds = value.source_ids.map((sourceId) =>
    isNonEmptyString(sourceId) ? sourceId : null,
  );
  if (sourceIds.some((sourceId) => sourceId === null)) return null;
  const supportMode = value.support_mode;
  if (
    supportMode !== undefined &&
    supportMode !== null &&
    supportMode !== "direct" &&
    supportMode !== "contextual" &&
    supportMode !== "no_match"
  )
    return null;
  return {
    text: value.text,
    source_ids: sourceIds as string[],
    reply_to: value.reply_to as string | null,
    ...(typeof value.reply_text === "string" && value.reply_to !== null
      ? { reply_text: value.reply_text }
      : {}),
    ...(supportMode !== undefined ? { support_mode: supportMode } : {}),
  };
}

/** Parse the closed segment projection while leaving legacy turns untouched. */
export function normaliseSegmentTurn(value: unknown): SegmentTurnPublic | null {
  if (!isRecord(value) || value.schema_version !== "segment_turn_v2") {
    return null;
  }
  if (!Array.isArray(value.segments) || value.segments.length === 0) {
    return null;
  }
  const segments = value.segments.map(normaliseSegment);
  if (segments.some((segment) => segment === null)) return null;
  return {
    schema_version: "segment_turn_v2",
    segments: segments as SegmentTurnPublic["segments"],
  };
}

/** Parse teacher-readable source receipts attached to a segment turn. */
export function normaliseSourceDetails(value: unknown): SegmentSourceDetail[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (
      !isRecord(item) ||
      !isNonEmptyString(item.source_id) ||
      !isNonEmptyString(item.source_filename) ||
      !isNonEmptyString(item.excerpt) ||
      !isNonEmptyString(item.version_label)
    ) {
      return [];
    }
    if (
      item.query_text !== undefined &&
      item.query_text !== null &&
      !isNonEmptyString(item.query_text)
    ) {
      return [];
    }
    return [
      {
        source_id: item.source_id,
        source_filename: item.source_filename,
        excerpt: item.excerpt,
        query_text:
          item.query_text === null || item.query_text === undefined
            ? null
            : item.query_text,
        version_label: item.version_label,
      },
    ];
  });
}

/**
 * Normalise one HTTP/WS public turn for both the classic and segments readers.
 * Invalid structured fields are ignored so a legacy speech remains readable.
 */
export function normaliseVisiblePlaybackTurn(
  value: unknown,
): VisiblePlaybackTurn | null {
  if (!isRecord(value)) return null;
  if (
    !isNonEmptyString(value.id) ||
    !isNonEmptyString(value.participant_id) ||
    !isNonEmptyString(value.speech)
  ) {
    return null;
  }
  const evidenceTrace = normaliseEvidenceTrace(value.evidence_trace);
  const segmentTurn = normaliseSegmentTurn(value.segment_turn);
  const sourceDetails = normaliseSourceDetails(value.source_details);
  const retainedAudio = audioReady(value.audio_ready);
  return {
    id: value.id,
    participant_id: value.participant_id,
    round_no:
      typeof value.round_no === "number" && Number.isInteger(value.round_no)
        ? value.round_no
        : 1,
    turn_index:
      typeof value.turn_index === "number" && Number.isInteger(value.turn_index)
        ? value.turn_index
        : 0,
    speech: value.speech,
    sources: sourceList(value.sources),
    ...(retainedAudio !== undefined ? { audio_ready: retainedAudio } : {}),
    ...(segmentTurn ? { segment_turn: segmentTurn } : {}),
    ...(sourceDetails.length > 0 ? { source_details: sourceDetails } : {}),
    ...(evidenceTrace.length > 0 ? { evidence_trace: evidenceTrace } : {}),
    ...(value.phase === "opening" ||
    value.phase === "exchange" ||
    value.phase === "final_integration"
      ? { phase: value.phase }
      : {}),
  };
}

/** Normalise the ordered public transcript without changing its legacy shape. */
export function normaliseVisiblePlaybackTurns(
  value: unknown,
): VisiblePlaybackTurn[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const turn = normaliseVisiblePlaybackTurn(item);
    return turn ? [turn] : [];
  });
}

/** Build the only speech-bearing object from a server playback.started payload. */
export function visibleTurnFromPlaybackStarted(
  participants: readonly DebateParticipant[],
  publicTurns: readonly VisiblePlaybackTurn[],
  payload: Record<string, unknown>,
): VisiblePlaybackTurn | null {
  if (!isNonEmptyString(payload.turn_id) || !isNonEmptyString(payload.speech)) {
    return null;
  }
  const existing = publicTurns.find((turn) => turn.id === payload.turn_id);
  const slot = typeof payload.slot === "string" ? payload.slot : null;
  const participant = existing
    ? participants.find((item) => item.id === existing.participant_id)
    : participants.find((item) => item.slot === slot);
  if (!participant && !existing) return null;
  const roundNo =
    typeof payload.round_no === "number" && Number.isInteger(payload.round_no)
      ? payload.round_no
      : (existing?.round_no ?? 1);
  // Public started events arrive in turn order. A participant's fixed slot
  // is not a turn index: discussion rounds rotate their speaking order.
  const turnIndex =
    existing?.turn_index ??
    (typeof payload.turn_index === "number" &&
    Number.isInteger(payload.turn_index)
      ? payload.turn_index
      : Math.max(-1, ...publicTurns.map((turn) => turn.turn_index)) + 1);
  const segmentTurn =
    normaliseSegmentTurn(payload.segment_turn) ?? existing?.segment_turn;
  const sourceDetails = normaliseSourceDetails(payload.source_details);
  const retainedAudio = audioReady(payload.audio_ready);
  const existingAudio = existing?.audio_ready;
  return {
    id: payload.turn_id,
    participant_id: existing?.participant_id ?? participant?.id ?? "",
    round_no: roundNo,
    turn_index: turnIndex,
    speech: payload.speech,
    sources: sourceList(payload.sources),
    ...(retainedAudio !== undefined
      ? { audio_ready: retainedAudio }
      : existingAudio !== undefined
        ? { audio_ready: existingAudio }
        : {}),
    ...(segmentTurn ? { segment_turn: segmentTurn } : {}),
    ...(sourceDetails.length > 0
      ? { source_details: sourceDetails }
      : existing?.source_details
        ? { source_details: existing.source_details }
        : {}),
    // The started event carries the claim lineage and this builder used to
    // drop it, so the turn rebuilt from the event replaced the one that had
    // it and the evidence chain vanished the moment a speech went public.
    // Falling back to the existing turn keeps a client whose event omits it.
    ...(() => {
      const fromEvent = normaliseEvidenceTrace(payload.evidence_trace);
      const trace = fromEvent.length > 0 ? fromEvent : existing?.evidence_trace;
      return trace && trace.length > 0 ? { evidence_trace: trace } : {};
    })(),
    ...(payload.phase === "opening" ||
    payload.phase === "exchange" ||
    payload.phase === "final_integration"
      ? { phase: payload.phase }
      : {}),
  };
}

export function isSafeMediaUrl(value: unknown): value is string {
  return typeof value === "string" && MEDIA_URL_PATTERN.test(value);
}

export function debateSocketUrl(debateId: string): string {
  if (typeof window === "undefined") {
    return `/api/v1/debates/${encodeURIComponent(debateId)}/events`;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/v1/debates/${encodeURIComponent(debateId)}/events`;
}

export function publicTurnById(
  publicTurns: readonly VisiblePlaybackTurn[],
  turnId: string | null | undefined,
): VisiblePlaybackTurn | null {
  if (!turnId) return null;
  return publicTurns.find((turn) => turn.id === turnId) ?? null;
}
