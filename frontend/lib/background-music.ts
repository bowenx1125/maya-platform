"use client";

import { useEffect, useSyncExternalStore } from "react";

/**
 * Background music (2026-11-03): two channels that never play together.
 *
 * - workspace: the music key beside Mayaform. On by default (2026-11-03):
 *   it starts when the site loads. It keeps playing across pages and stops
 *   at logout.
 * - stage: the 3D Debate stage's own music key. Entering the stage starts it
 *   (and hands the workspace music off); pressing its key pauses it. Leaving
 *   the stage stops it and gives the workspace music back if its key is on.
 *
 * Browsers refuse sound before the person has touched the page. Then the key
 * stays on and the music starts (fading in) on their first click, tap or key
 * press anywhere on the site. A key the person turns off is remembered per
 * channel (localStorage) and does not start by itself next time; turning it
 * back on forgets that.
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

const OFF_KEY: Record<MusicChannelName, string> = {
  workspace: "maya.bgm.off.workspace",
  stage: "maya.bgm.off.stage",
};

/** The person turned this key off themselves. */
function turnedOff(name: MusicChannelName): boolean {
  try {
    return window.localStorage.getItem(OFF_KEY[name]) === "1";
  } catch {
    return false;
  }
}

function rememberOff(name: MusicChannelName, off: boolean): void {
  try {
    if (off) window.localStorage.setItem(OFF_KEY[name], "1");
    else window.localStorage.removeItem(OFF_KEY[name]);
  } catch {
    // Private mode or no storage: the choice lasts this visit only.
  }
}

function isAutoplayRefusal(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { name?: unknown }).name === "NotAllowedError"
  );
}

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
  /** On, but the browser wants a gesture before it makes sound. */
  waiting = false;
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
    // Buffer ahead so a press gives sound quickly; the file streams.
    created.preload = "auto";
    const next = () => {
      this.trackIndex = (this.trackIndex + 1) % this.tracks.length;
      created.src = this.tracks[this.trackIndex];
      void created.play().catch((error: unknown) => this.playFailed(error));
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

  /** Nothing loads: the key turns off. */
  private refused(): void {
    this.stopFade();
    this.audible = false;
    this.waiting = false;
    this.wanted = false;
    emit();
  }

  /** play() failed: no gesture yet keeps the key on and waits for one. */
  private playFailed(error: unknown): void {
    if (!isAutoplayRefusal(error)) {
      this.refused();
      return;
    }
    this.stopFade();
    this.audible = false;
    this.waiting = true;
    armFirstGesture();
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
    this.waiting = false;
    emit();
    void element
      .play()
      .then(() => {
        if (this.audible) this.rampTo(CHANNEL_VOLUME[this.name]);
      })
      .catch((error: unknown) => this.playFailed(error));
  }

  fadeOut(): void {
    this.waiting = false;
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
    this.waiting = false;
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

const GESTURES = ["pointerdown", "pointerup", "keydown"] as const;
let gestureArmed = false;

function onFirstGesture(event: Event): void {
  // A press on a music key is handled by the key itself (toggleMusic).
  const target = event.target as Element | null;
  if (target?.closest?.("[data-music-key]")) return;
  disarmFirstGesture();
  const channel = current();
  if (channel.wanted && channel.waiting) channel.fadeIn();
}

/** Start the waiting music on the first click, tap or key press, once. */
function armFirstGesture(): void {
  if (gestureArmed || typeof document === "undefined") return;
  gestureArmed = true;
  for (const name of GESTURES) {
    document.addEventListener(name, onFirstGesture, true);
  }
}

function disarmFirstGesture(): void {
  if (!gestureArmed) return;
  gestureArmed = false;
  for (const name of GESTURES) {
    document.removeEventListener(name, onFirstGesture, true);
  }
}

/** The channel that owns the speakers now. */
function current(): Channel {
  return onStage ? channels.stage : channels.workspace;
}

/** Press a music key. Only the channel that owns the speakers can play. */
export function toggleMusic(name: MusicChannelName): void {
  const channel = channels[name];
  // On but waiting for a gesture: this press is the gesture, so it plays.
  if (channel.wanted && channel.waiting && channel === current()) {
    channel.fadeIn();
    return;
  }
  if (channel.wanted) {
    channel.wanted = false;
    rememberOff(name, true);
    channel.fadeOut();
    emit();
    return;
  }
  channel.wanted = true;
  rememberOff(name, false);
  if (channel === current()) channel.fadeIn();
  else emit();
}

/** The 3D stage opened: the workspace music fades out, the stage's fades in. */
export function enterStageMusic(): void {
  if (onStage) return;
  onStage = true;
  channels.workspace.fadeOut();
  if (turnedOff("stage")) {
    channels.stage.wanted = false;
    emit();
    return;
  }
  channels.stage.wanted = true;
  channels.stage.fadeIn();
}

/** The signed-in site loaded (AppShell mounted): workspace music is on by default. */
export function startDefaultMusic(): void {
  const channel = channels.workspace;
  if (channel.wanted || channel.tracks.length === 0) return;
  if (turnedOff("workspace")) return;
  channel.wanted = true;
  if (channel === current()) channel.fadeIn();
  else emit();
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
  disarmFirstGesture();
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
  disarmFirstGesture();
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
    waiting: channel.waiting,
    audio: channel.audio,
  };
}
