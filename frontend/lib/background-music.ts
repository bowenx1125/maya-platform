"use client";

import { useSyncExternalStore } from "react";

/**
 * Background music for the workspace (2026-11-03).
 *
 * Off by default and never started by the page: only the sidebar music key
 * starts it, and the browser may refuse even that until the person has
 * interacted. One player lives at module level, so it keeps playing while
 * the person moves between pages (each page mounts its own AppShell) and
 * stops at logout. The list loops: after the last track the first plays.
 *
 * The tracks come from the deployment, not the repository: the operator
 * sets NEXT_PUBLIC_BGM_TRACKS at build time to a comma-separated list of
 * paths this site serves (the production CSP allows media from the site
 * only), in play order, for music they have the right to play to students.
 * Unset, the key stays disabled.
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

type Listener = () => void;

const listeners = new Set<Listener>();
let audio: HTMLAudioElement | null = null;
let trackIndex = 0;
let playing = false;

function emit(): void {
  for (const listener of listeners) listener();
}

function setPlaying(next: boolean): void {
  if (playing === next) return;
  playing = next;
  emit();
}

function player(tracks: readonly string[]): HTMLAudioElement {
  if (audio) return audio;
  const created = new Audio();
  created.preload = "none";
  created.addEventListener("ended", () => {
    trackIndex = (trackIndex + 1) % tracks.length;
    created.src = tracks[trackIndex];
    void created.play().catch(() => setPlaying(false));
  });
  // A file that fails to load skips to the next one instead of stopping
  // the list (once round the list at most, so a list of broken files ends).
  let failuresInRow = 0;
  created.addEventListener("error", () => {
    failuresInRow += 1;
    if (!playing || failuresInRow >= tracks.length) {
      failuresInRow = 0;
      setPlaying(false);
      return;
    }
    trackIndex = (trackIndex + 1) % tracks.length;
    created.src = tracks[trackIndex];
    void created.play().catch(() => setPlaying(false));
  });
  created.addEventListener("playing", () => {
    failuresInRow = 0;
  });
  audio = created;
  return created;
}

export function startBackgroundMusic(
  tracks: readonly string[] = BACKGROUND_TRACKS,
): void {
  if (tracks.length === 0 || typeof Audio === "undefined") return;
  const element = player(tracks);
  if (!element.src) element.src = tracks[trackIndex % tracks.length];
  setPlaying(true);
  void element.play().catch(() => setPlaying(false));
}

export function stopBackgroundMusic(): void {
  audio?.pause();
  setPlaying(false);
}

export function toggleBackgroundMusic(
  tracks: readonly string[] = BACKGROUND_TRACKS,
): void {
  if (playing) stopBackgroundMusic();
  else startBackgroundMusic(tracks);
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Whether the background music is playing now. */
export function useBackgroundMusicPlaying(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => playing,
    () => false,
  );
}

/** Tests only: forget the player and start from the first track again. */
export function resetBackgroundMusicForTests(): void {
  audio?.pause();
  audio = null;
  trackIndex = 0;
  playing = false;
  emit();
}
