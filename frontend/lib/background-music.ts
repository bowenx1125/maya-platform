"use client";

import { useEffect, useSyncExternalStore } from "react";

/**
 * Background music (2026-11-03): two channels that never play together.
 *
 * - workspace: the music key beside Mayaform. Off by default; nothing plays
 *   until it is pressed. It keeps playing across pages and stops at logout.
 * - stage: the 3D Debate stage's own music key. Entering the stage starts it
 *   (and hands the workspace music off); pressing its key pauses it. Leaving
 *   the stage stops it and gives the workspace music back if its key is on.
 *
 * Every hand-off fades: the leaving channel fades out, the arriving one fades
 * in. Each channel loops its list (after the last track the first plays).
 *
 * The tracks come from the deployment, not the repository: the operator sets
 * NEXT_PUBLIC_BGM_TRACKS (workspace) and NEXT_PUBLIC_BGM_STAGE_TRACKS (stage)
 * at build time to comma-separated paths this site serves (the production
 * CSP allows media from the site only), for music they have the right to
 * play to students. Unset, that key stays disabled.
 */
export function parseTracks(raw: string | undefined): readonly string[] {
  return (raw ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter((item) => /^\/(?!\/)\S+$/.test(item));
}

export const BACKGROUND_TRACKS: readonly string[] = parseTracks(
  process.env.NEXT_PUBLIC_BGM_TRACKS,
);
export const STAGE_TRACKS: readonly string[] = parseTracks(
  process.env.NEXT_PUBLIC_BGM_STAGE_TRACKS,
);

export type MusicChannelName = "workspace" | "stage";

/** How long a hand-off fades, in milliseconds. */
export const MUSIC_FADE_MS = 900;
// The stage music sits under the Debate speeches.
const CHANNEL_VOLUME: Record<MusicChannelName, number> = {
  workspace: 0.6,
  stage: 0.35,
};

type Listener = () => void;
const listeners = new Set<Listener>();

function emit(): void {
  for (const listener of listeners) listener();
}

class Channel {
  audio: HTMLAudioElement | null = null;
  trackIndex = 0;
  /** The key is on (the person wants this music). */
  wanted = false;
  /** Sound is coming out (or fading in). */
  audible = false;
  tracks: readonly string[];
  private fade: ReturnType<typeof setInterval> | null = null;

  constructor(
    readonly name: MusicChannelName,
    tracks: readonly string[],
  ) {
    this.tracks = tracks;
  }

  private player(): HTMLAudioElement {
    if (this.audio) return this.audio;
    const created = new Audio();
    created.preload = "none";
    const next = () => {
      this.trackIndex = (this.trackIndex + 1) % this.tracks.length;
      created.src = this.tracks[this.trackIndex];
      void created.play().catch(() => this.refused());
    };
    created.addEventListener("ended", next);
    // A file that fails to load skips to the next one, once round the list
    // at most, so a list of broken files ends instead of looping.
    let failuresInRow = 0;
    created.addEventListener("error", () => {
      failuresInRow += 1;
      if (!this.audible || failuresInRow >= this.tracks.length) {
        failuresInRow = 0;
        this.refused();
        return;
      }
      next();
    });
    created.addEventListener("playing", () => {
      failuresInRow = 0;
    });
    this.audio = created;
    return created;
  }

  /** The browser refused to play (no gesture yet) or nothing loads. */
  private refused(): void {
    this.stopFade();
    this.audible = false;
    this.wanted = false;
    emit();
  }

  private stopFade(): void {
    if (this.fade !== null) clearInterval(this.fade);
    this.fade = null;
  }

  private rampTo(target: number, done?: () => void): void {
    const element = this.audio;
    this.stopFade();
    if (!element) return;
    const start = element.volume;
    const began = Date.now();
    const step = () => {
      const progress = Math.min(1, (Date.now() - began) / MUSIC_FADE_MS);
      element.volume = start + (target - start) * progress;
      if (progress >= 1) {
        this.stopFade();
        done?.();
      }
    };
    this.fade = setInterval(step, 40);
    step();
  }

  fadeIn(): void {
    if (this.tracks.length === 0 || typeof Audio === "undefined") {
      this.wanted = false;
      emit();
      return;
    }
    const element = this.player();
    if (!element.src) element.src = this.tracks[this.trackIndex];
    if (!this.audible) element.volume = 0;
    this.audible = true;
    emit();
    void element
      .play()
      .then(() => {
        if (this.audible) this.rampTo(CHANNEL_VOLUME[this.name]);
      })
      .catch(() => this.refused());
  }

  fadeOut(): void {
    if (!this.audible) return;
    this.audible = false;
    emit();
    const element = this.audio;
    this.rampTo(0, () => {
      if (!this.audible) element?.pause();
    });
  }

  /** Stop at once (logout). */
  stop(): void {
    this.stopFade();
    this.audio?.pause();
    this.audible = false;
    this.wanted = false;
    emit();
  }

  reset(tracks: readonly string[]): void {
    this.stop();
    this.audio = null;
    this.trackIndex = 0;
    this.tracks = tracks;
  }
}

const channels: Record<MusicChannelName, Channel> = {
  workspace: new Channel("workspace", BACKGROUND_TRACKS),
  stage: new Channel("stage", STAGE_TRACKS),
};
let onStage = false;

/** The channel that owns the speakers now. */
function current(): Channel {
  return onStage ? channels.stage : channels.workspace;
}

/** Press a music key. Only the channel that owns the speakers can play. */
export function toggleMusic(name: MusicChannelName): void {
  const channel = channels[name];
  if (channel.wanted) {
    channel.wanted = false;
    channel.fadeOut();
    emit();
    return;
  }
  channel.wanted = true;
  if (channel === current()) channel.fadeIn();
  else emit();
}

/** The 3D stage opened: the workspace music fades out, the stage's fades in. */
export function enterStageMusic(): void {
  if (onStage) return;
  onStage = true;
  channels.workspace.fadeOut();
  channels.stage.wanted = true;
  channels.stage.fadeIn();
}

/** The 3D stage closed: its music fades out, the workspace's comes back. */
export function leaveStageMusic(): void {
  if (!onStage) return;
  onStage = false;
  channels.stage.wanted = false;
  channels.stage.fadeOut();
  if (channels.workspace.wanted) channels.workspace.fadeIn();
  else emit();
}

/** Logout: everything stops at once. */
export function stopBackgroundMusic(): void {
  onStage = false;
  channels.stage.stop();
  channels.workspace.stop();
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Whether this channel's key is on. */
export function useMusicOn(name: MusicChannelName): boolean {
  return useSyncExternalStore(
    subscribe,
    () => channels[name].wanted,
    () => false,
  );
}

export function musicAvailable(name: MusicChannelName): boolean {
  return channels[name].tracks.length > 0;
}

/** Mount on the 3D stage: its music plays while the stage is open. */
export function useStageMusic(): void {
  useEffect(() => {
    enterStageMusic();
    return () => leaveStageMusic();
  }, []);
}

/** Tests only. */
export function resetBackgroundMusicForTests(
  tracks: { workspace?: readonly string[]; stage?: readonly string[] } = {},
): void {
  onStage = false;
  channels.workspace.reset(tracks.workspace ?? BACKGROUND_TRACKS);
  channels.stage.reset(tracks.stage ?? STAGE_TRACKS);
  emit();
}

/** Tests only: what a channel is doing. */
export function musicStateForTests(name: MusicChannelName) {
  const channel = channels[name];
  return {
    wanted: channel.wanted,
    audible: channel.audible,
    audio: channel.audio,
  };
}
