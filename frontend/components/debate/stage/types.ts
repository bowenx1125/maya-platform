import type { ReactNode } from "react";

import type {
  DebateDetail,
  DebatePlaybackState,
  DebateTurn,
  PlatformApi,
} from "../../../lib/api";
import type { AvatarConfig, AvatarExpression, AvatarState } from "../../avatar";
import type { EvidenceTraceRow } from "../../evidence";

export type PlaybackStatus = DebatePlaybackState["status"];
export type PlaybackMode = DebatePlaybackState["mode"];
export type PlaybackAction = "start" | "resume" | "next" | "replay";
export type DebateRoundPhase = "opening" | "exchange" | "final_integration";

export type PlaybackConnectionIssue =
  | "network"
  | "sequence_gap"
  | "session_expired"
  | "origin_mismatch"
  | "superseded"
  | "terminal";

export type PlaybackConnectionState =
  "connecting" | "connected" | "reconnecting" | "disconnected";

export type ClassroomPhase =
  "ready" | "in_progress" | "waiting" | "finished" | "stopped" | "failed";

export type PlaybackAuthorityState = {
  connection: PlaybackConnectionState;
  connectionIssue: PlaybackConnectionIssue | null;
  controllerReady: boolean;
  /** True while a stage-owned Start/Next/Replay command is awaiting REST. */
  commandBusy?: boolean;
};

/**
 * Keep the classroom component on the platform API boundary.  In particular,
 * this type does not expose a provider, model, or supplier voice identifier to
 * the browser.
 */
export type DebatePlaybackApi = Pick<
  PlatformApi,
  | "startDebate"
  | "advanceDebatePlayback"
  | "pauseDebate"
  | "resumeDebate"
  | "freezeFinalInput"
  | "retryDebatePreparation"
  | "listProviderDataCallManifests"
  | "replayDebate"
> &
  Partial<Pick<PlatformApi, "updateClassroomLive" | "debate" | "finishDebate">>;

export type DebateStartRequest = Parameters<PlatformApi["startDebate"]>[1];
export type AdvancePlaybackRequest = Parameters<
  PlatformApi["advanceDebatePlayback"]
>[1];

export type PlaybackStageLabels = {
  stageTitle?: string;
  stageDescription?: string;
  start?: string;
  pause?: string;
  resume?: string;
  replayAll?: string;
  reconnect?: string;
  finish?: string;
  transcript?: string;
  sources?: string;
  noSources?: string;
  round?: string;
  current?: string;
  prepared?: string;
  debateComplete?: string;
  debateStopped?: string;
  debateFailed?: string;
  statusPreparing?: string;
  statusReady?: string;
  statusPlaying?: string;
  statusPaused?: string;
  waitingNext?: string;
  phaseReady?: string;
  phaseInProgress?: string;
  phaseWaiting?: string;
  phaseFinished?: string;
  phaseOpening?: string;
  phaseExchange?: string;
  phaseFinalIntegration?: string;
  next?: string;
  nextNotReady?: string;
  waitingForAudio?: string;
  connectionWaiting?: string;
  connectionReady?: string;
  connectionReconnecting?: string;
  connectionDisconnected?: string;
  connectionSequenceGap?: string;
  connectionSessionExpired?: string;
  connectionOriginMismatch?: string;
  connectionSuperseded?: string;
  connectionError?: string;
  connectionSignIn?: string;
  connectionReload?: string;
  controllerWaiting?: string;
  controlBusy?: string;
  retryReason?: string;
  regenerate?: string;
  replayTurn?: string;
  debatePartial?: string;
  /** Turns a server safe code into a sentence a teacher can read. */
  localizeCode?: (code: string) => string;
  providerSetupIncomplete?: string;
  providerGateTitle?: string;
  providerGateLoading?: string;
  providerGateEmpty?: string;
  providerGateReview?: string;
  providerGateReviewAll?: string;
  providerGateConfirmed?: string;
  providerGateRetry?: string;
  noPublishedSpeech?: string;
  audioNotRetained?: string;
  selectedTurn?: string;
  replaceRetainedAudioConfirm?: string;
  audioLabel?: string;
};

export type AvatarVisualState = {
  participant_id: string;
  slot: "A" | "B" | "C" | "D" | "E";
  motion_state: AvatarState;
  expression: AvatarExpression;
  expression_strength: AvatarConfig["expression_strength"];
};

export type SegmentTurnPublic = {
  schema_version: "segment_turn_v2";
  segments: Array<{
    text: string;
    source_ids: string[];
    support_mode?: "direct" | "contextual" | "no_match" | null;
    reply_to: string | null;
    reply_text?: string | null;
  }>;
};

export type SegmentSourceDetail = {
  source_id: string;
  source_filename: string;
  excerpt: string;
  query_text?: string | null;
  version_label: string;
};

export type VisiblePlaybackTurn = Pick<
  DebateTurn,
  "id" | "participant_id" | "round_no" | "turn_index" | "speech" | "sources"
> & {
  /** Whether retained public audio is available for this turn. */
  audio_ready?: boolean | null;
  /** Present for the segments_v2 protocol; omitted from legacy turns. */
  segment_turn?: SegmentTurnPublic | null;
  /** Teacher-readable source receipts for the segments_v2 protocol. */
  source_details?: SegmentSourceDetail[];
  phase?: DebateRoundPhase;
  evidence_trace?: EvidenceTraceRow[];
};

export type PlaybackEventType =
  | "snapshot"
  | "debate.started"
  | "round.started"
  | "turn.preparing"
  | "turn.ready"
  | "playback.started"
  | "playback.paused"
  | "playback.resumed"
  | "playback.skipped"
  | "playback.completed"
  | "playback.waiting_next"
  | "replay.started"
  | "replay.completed"
  | "translation.batch_started"
  | "translation.batch_completed"
  | "translation.batch_failed"
  | "interaction.opened"
  | "interaction.vote_created"
  | "interaction.barrage_created"
  | "interaction.closed"
  | "barrage_insight.started"
  | "barrage_insight.completed"
  | "barrage_insight.failed"
  | "report.started"
  | "report.completed"
  | "report.failed"
  | "debate.completed"
  | "debate.failed"
  | "debate.stopped"
  | "error";

export type PlaybackEvent = {
  event_id: string;
  event_type: PlaybackEventType;
  event_version: 1;
  debate_id: string;
  sequence: number;
  occurred_at: string;
  payload: Record<string, unknown>;
};

export type PrivatePlaybackMessageType =
  | "controller.acquired"
  | "media.prepared"
  | "command.rejected"
  | "command.duplicate"
  | "controller.revoked";

export type PrivatePlaybackMessage = {
  message_id: string;
  message_type: PrivatePlaybackMessageType;
  result_version: 1;
  debate_id: string;
  occurred_at: string;
  command_id?: string;
  controller_epoch?: string;
  turn_id?: string;
  media_url?: string | null;
  text_only?: boolean;
  expires_at?: string;
  control_version?: number;
  current_control_version?: number;
  code?: string;
  recoverable?: boolean;
  reason?:
    | "superseded"
    | "disconnected"
    | "session_revoked"
    | "start_next"
    | "debate_terminal";
};

export type SocketListener = (event: Event) => void;

/** A deliberately small adapter surface makes protocol tests independent of a browser WebSocket. */
export type PlaybackSocket = {
  send: (data: string) => void;
  close: (code?: number, reason?: string) => void;
  addEventListener?: (type: string, listener: SocketListener) => void;
  removeEventListener?: (type: string, listener: SocketListener) => void;
  onopen?: ((event: Event) => void) | null;
  onmessage?: ((event: MessageEvent<unknown>) => void) | null;
  onclose?: ((event: CloseEvent) => void) | null;
  onerror?: ((event: Event) => void) | null;
};

export type PlaybackSocketFactory = (url: string) => PlaybackSocket;

export type DebateStageProps = {
  /**
   * The language the debate is generated in when Start is pressed.
   *
   * Fixed for the whole debate: every later turn's prompt carries the
   * speeches before it, and turns are prepared ahead of the teacher, so a
   * change midway would leave a bilingual record whose evidence chain was
   * embedded in the other language.
   */
  outputLanguage?: "en" | "zh";
  /** Page-owned actions rendered in the stage's own header row, so a
   *  teacher's Finish sits with Start and Next instead of a row apart. */
  headerActions?: ReactNode;
  debateId: string;
  detail: DebateDetail;
  api: DebatePlaybackApi;
  /** Called after a REST command or snapshot changes the page's authoritative DTO. */
  onDetailChange?: (detail: DebateDetail) => void;
  /** Exposes the minimum authority state required by controls outside the Stage. */
  onAuthorityChange?: (authority: PlaybackAuthorityState) => void;
  /** Re-read the authoritative HTTP snapshot before a reconnect. */
  refreshSnapshot?: () => Promise<DebateDetail>;
  socketFactory?: PlaybackSocketFactory;
  socketUrl?: string;
  labels?: PlaybackStageLabels;
  readOnly?: boolean;
  /**
   * Authoritative course audio pointer. `undefined` means the control page
   * could not establish the pointer; neither unknown nor null authorizes
   * replay.
   */
  currentAudioDebateId?: string | null;
  /**
   * Legacy name retained for callers that only provide the start CAS. New
   * callers should use currentAudioDebateId for both the CAS and replay gate.
   */
  expectedCurrentAudioDebateId?: string | null;
  /** Keep the page's local current-audio pointer in sync after a successful start. */
  onCurrentAudioDebateIdChange?: (debateId: string) => void;
  /** A parent-owned command (for example header Finish) is in flight. */
  actionInFlight?: boolean;
  className?: string;
};
