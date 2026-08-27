import type { PlaybackStageLabels } from "./types";

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
  resume: "Resume",
  skip: "Skip current turn",
  stop: "Stop debate",
  replayAll: "Replay all",
  replayTurn: "Replay turn",
  retryPlayback: "Retry playback",
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
  waitingForAudio: "Waiting for the server to prepare audio…",
  audioPaused: "Audio is paused until the server confirms resume.",
  connectionReady: "Connected",
  connectionReconnecting: "Reconnecting…",
  connectionDisconnected: "Disconnected",
  connectionError: "The classroom connection needs attention.",
  controllerWaiting: "Waiting for the teacher controller…",
  controlBusy: "Updating classroom playback…",
  retryReason: "Playback did not start. You can retry this turn.",
  noPublishedSpeech: "The server has not published a speech for this turn yet.",
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
