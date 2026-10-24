import { useCallback, useEffect, useMemo, useRef } from "react";

import type { PlatformApi } from "../../../lib/api/platform";
import { noteDebateSpeechPlaying } from "../../../lib/client-metrics";

type PrefetchApi = Partial<Pick<PlatformApi, "prefetchNextDebateAudio">>;

type PrefetchInput = {
  api: PrefetchApi;
  debateId: string;
  enabled: boolean;
  mode: string;
  status: string;
  currentTurnId: string | null | undefined;
  controlVersion: number;
  /** Read at request time; the stage owns this ref. */
  controllerEpochRef: { readonly current: string | null };
  nextTurnReady: boolean;
};

const PREFETCH_STATUSES = new Set(["playing", "paused", "waiting_next"]);

/**
 * Download the next speech as soon as the server says its audio is ready.
 *
 * Owner decision (2026-10-24): Next should not wait for the audio download.
 * The ticket is the controller's own and names only the adjacent next turn;
 * the bytes stay in this tab as a blob URL that the media handshake plays
 * instead of fetching again. Any failure just falls back to the normal URL.
 */
export function useNextAudioPrefetch({
  api,
  debateId,
  enabled,
  mode,
  status,
  currentTurnId,
  controlVersion,
  controllerEpochRef,
  nextTurnReady,
}: PrefetchInput) {
  const blobs = useRef(new Map<string, string>());
  const requestedFor = useRef<string | null>(null);
  const loadStartedAt = useRef<{ turnId: string; at: number } | null>(null);

  useEffect(() => {
    const prefetch = api.prefetchNextDebateAudio?.bind(api);
    const epoch = controllerEpochRef.current;
    if (
      !prefetch ||
      !enabled ||
      mode !== "live" ||
      !nextTurnReady ||
      !epoch ||
      !currentTurnId ||
      !PREFETCH_STATUSES.has(status) ||
      requestedFor.current === currentTurnId
    )
      return;
    requestedFor.current = currentTurnId;
    let cancelled = false;
    const started = performance.now();
    void (async () => {
      try {
        const ticket = await prefetch(debateId, {
          expected_control_version: controlVersion,
          expected_current_turn_id: currentTurnId,
          controller_epoch: epoch,
        });
        if (blobs.current.has(ticket.turn_id)) return;
        const response = await fetch(ticket.media_url, {
          credentials: "same-origin",
        });
        if (!response.ok) throw new Error(`prefetch ${response.status}`);
        const blob = await response.blob();
        if (cancelled) return;
        blobs.current.set(ticket.turn_id, URL.createObjectURL(blob));
        console.info(
          `[debate-timing] stage=audio_prefetch turn=${ticket.turn_id} bytes=${blob.size} ms=${Math.round(performance.now() - started)}`,
        );
      } catch {
        // The turn still plays through the normal media handshake.
        if (!cancelled) requestedFor.current = null;
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    api,
    controlVersion,
    controllerEpochRef,
    currentTurnId,
    debateId,
    enabled,
    mode,
    nextTurnReady,
    status,
  ]);

  useEffect(() => {
    const owned = blobs.current;
    return () => {
      for (const url of owned.values()) URL.revokeObjectURL(url);
      owned.clear();
    };
  }, []);

  /** The prefetched blob URL for this turn, or the server's media URL. */
  const sourceFor = useCallback((turnId: string, mediaUrl: string) => {
    for (const [cached, url] of blobs.current) {
      if (cached !== turnId) {
        URL.revokeObjectURL(url);
        blobs.current.delete(cached);
      }
    }
    loadStartedAt.current = { turnId, at: performance.now() };
    return blobs.current.get(turnId) ?? mediaUrl;
  }, []);

  /** Log how long the browser waited between media.prepared and playback. */
  const notePlaying = useCallback((turnId: string | null) => {
    noteDebateSpeechPlaying();
    const started = loadStartedAt.current;
    if (!started || started.turnId !== turnId) return;
    loadStartedAt.current = null;
    console.info(
      `[debate-timing] stage=audio_start turn=${turnId} prefetched=${blobs.current.has(turnId)} ms=${Math.round(performance.now() - started.at)}`,
    );
  }, []);

  return useMemo(() => ({ sourceFor, notePlaying }), [sourceFor, notePlaying]);
}
