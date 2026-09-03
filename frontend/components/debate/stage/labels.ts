import type { DebateRoundPhase, PlaybackStageLabels } from "./types";

/**
 * M12 keeps its copy injectable so the shared locale table does not become a
 * cross-module dependency.  The control page can pass translated static copy
 * later without recreating the socket or audio element.
 */
export const defaultPlaybackStageLabels: Required<PlaybackStageLabels> = {
  stageTitle: "Classroom debate",
  stageDescription: "A teacher-controlled, server-timed classroom stage.",
  start: "Start debate",
  pause: "Pause",
  resume: "Continue",
  replayAll: "Replay whole debate",
  reconnect: "Reconnect",
  finish: "Finish debate",
  transcript: "Published transcript",
  sources: "Sources",
  noSources: "No matched knowledge sources.",
  round: "Round",
  current: "Current",
  prepared: "Preparing the next classroom turn…",
  debateComplete: "Debate complete",
  debateStopped: "Debate stopped",
  debateFailed: "Debate needs attention",
  statusPreparing: "Preparing",
  statusReady: "Ready",
  statusPlaying: "Playing",
  statusPaused: "Paused",
  waitingNext: "Waiting for the teacher to continue…",
  phaseReady: "Ready to start",
  phaseInProgress: "In progress",
  phaseWaiting: "Waiting",
  phaseFinished: "Finished",
  phaseOpening: "Opening",
  phaseExchange: "Exchange",
  phaseFinalIntegration: "Final integration",
  next: "Next",
  waitingForAudio: "Waiting for the server to prepare audio…",
  connectionWaiting: "Waiting for the server to restore playback.",
  connectionReady: "Connected",
  connectionReconnecting: "Reconnecting…",
  connectionDisconnected: "Connection lost",
  connectionSequenceGap: "Classroom state needs to be resynchronized.",
  connectionSessionExpired: "Your login has expired. Please sign in again.",
  connectionOriginMismatch:
    "The classroom address does not match the server configuration.",
  connectionSuperseded: "Another teacher page has taken control.",
  connectionError: "The classroom connection needs attention.",
  controllerWaiting: "Waiting for the teacher controller…",
  controlBusy: "Updating classroom playback…",
  retryReason: "Playback did not start. You can retry this turn.",
  replayTurn: "Replay this speech",
  debatePartial: "The debate stopped early. Published speeches remain below.",
  // Defaults show the code itself; the app supplies a real translator.
  localizeCode: (code: string) => code,
  providerSetupIncomplete:
    "A real provider is selected but its reviewed policy is not installed. Retrying cannot help; an operator has to import it.",
  providerGateTitle: "External query confirmation is required.",
  providerGateLoading: "Loading the exact disclosure…",
  providerGateEmpty: "No retryable external query is currently pending.",
  providerGateReview: "Review exact disclosure",
  providerGateReviewAll: "Review all turn approvals",
  providerGateConfirmed: "Disclosure confirmed",
  providerGateRefresh: "Refresh confirmation",
  providerGateRetry: "Retry this turn",
  noPublishedSpeech: "The server has not published a speech for this turn yet.",
  audioNotRetained: "This audio is no longer retained.",
  selectedTurn: "Selected turn",
  replaceRetainedAudioConfirm:
    "Starting this debate will replace the previous retained audio. Its text remains available.",
  audioLabel: "Classroom audio",
};

export function resolvePlaybackStageLabels(
  labels?: PlaybackStageLabels,
): Required<PlaybackStageLabels> {
  return { ...defaultPlaybackStageLabels, ...labels };
}

/** Resolve a mutual-learning label from the explicit final-round marker. */
export function resolveDebateRoundPhase(
  roundNo: number,
  isFinalRound: boolean,
): DebateRoundPhase {
  if (!Number.isInteger(roundNo) || roundNo < 1) {
    throw new Error("round_no must be a positive integer");
  }
  if (roundNo === 1) return "opening";
  return isFinalRound ? "final_integration" : "exchange";
}

export function phaseLabel(
  phase: DebateRoundPhase,
  labels?: PlaybackStageLabels,
): string {
  const resolved = resolvePlaybackStageLabels(labels);
  if (phase === "opening") return resolved.phaseOpening;
  if (phase === "exchange") return resolved.phaseExchange;
  return resolved.phaseFinalIntegration;
}
