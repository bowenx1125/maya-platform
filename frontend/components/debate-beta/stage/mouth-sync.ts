import type { AvatarState } from "../../avatar";

/**
 * Mouth motion must follow the audio element, not the server playback status.
 * startEarly / media prepare can make the turn audible while status is still
 * "ready"; deriveAvatarStates maps that to "thinking", and a status==="playing"
 * gate would keep the mouth idle until started_ack lands.
 */
export function stageMouthVisual(args: {
  derived: AvatarState;
  participantId: string;
  speakerId: string | null | undefined;
  audioPlayingTurnId: string | null;
  currentTurnId: string | null | undefined;
  mediaRetryNeeded: boolean;
}): AvatarState {
  const audioLive =
    !args.mediaRetryNeeded &&
    args.audioPlayingTurnId !== null &&
    args.audioPlayingTurnId === args.currentTurnId &&
    Boolean(args.speakerId) &&
    args.participantId === args.speakerId;
  if (audioLive) return "speaking";
  // Server may still report speaking after ended/pause until the next snapshot.
  if (args.derived === "speaking") return "idle";
  return args.derived;
}
