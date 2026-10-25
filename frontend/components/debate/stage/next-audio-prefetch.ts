import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { PlatformApi } from "../../../lib/api/platform";
import { noteDebateSpeechPlaying } from "../../../lib/client-metrics";

type PrefetchApi = Partial<Pick<PlatformApi, "prefetchNextDebateAudio">>;

/** How long a speech waits for its own download before it plays from the URL. */
export const DOWNLOAD_WAIT_MS = 3_000;
/** The longest the queue waits for the 3D scene before downloading anyway. */
export const SCENE_WAIT_MS = 10_000;

type QueueInput = {
  api: PrefetchApi;
  debateId: string;
  /** The controller tab on a live stage; observers download nothing. */
  enabled: boolean;
  /** Read at request time; the stage owns this ref. */
  controllerEpochRef: { readonly current: string | null };
  /** True once the controller epoch exists (re-runs the queue). */
  controllerReady: boolean;
  /** The 3D scene finished (or failed) loading; plain stages pass true. */
  sceneSettled: boolean;
  /** The teacher pressed Start: download the first speech now. */
  started: boolean;
};

type InFlight = {
  turnId: string;
  abort: AbortController;
  done: Promise<string | null>;
};

/**
 * Download every ready speech in speaking order while the Immerse stage is
 * open, one at a time, independent of Next and of the playback state.
 *
 * PR A2 (2026-10-24): the server announces ready speeches (the snapshot's
 * ``audio_ready_turn_ids`` and ``turn.audio_ready``); this queue downloads
 * them as blobs after the 3D scene has loaded (or Start, or 10 s). Next,
 * pause and resume never cancel it. Playing a speech uses its blob, waits up
 * to 3 s for a download in progress, or plays the URL (and never downloads
 * the same file twice). Leaving the stage aborts and frees everything.
 */
export function useImmerseAudioQueue({
  api,
  debateId,
  enabled,
  controllerEpochRef,
  controllerReady,
  sceneSettled,
  started,
}: QueueInput) {
  const blobs = useRef(new Map<string, string>());
  const ready = useRef<string[]>([]);
  // Speeches that play (or played) from the URL, or failed twice: not queued.
  const skipped = useRef(new Set<string>());
  const failures = useRef(new Map<string, number>());
  const current = useRef<string | null>(null);
  const inFlight = useRef<InFlight | null>(null);
  const alive = useRef(true);
  const loadStartedAt = useRef<{ turnId: string; at: number } | null>(null);
  const [mountedAt] = useState(() => Date.now());
  const [sceneTimedOut, setSceneTimedOut] = useState(false);
  const [wake, setWake] = useState(0);
  const gateOpen = sceneSettled || started || sceneTimedOut;

  useEffect(() => {
    if (sceneSettled || started) return undefined;
    const timer = window.setTimeout(
      () => setSceneTimedOut(true),
      Math.max(0, SCENE_WAIT_MS - (Date.now() - mountedAt)),
    );
    return () => window.clearTimeout(timer);
  }, [mountedAt, sceneSettled, started]);

  const next = useCallback((): string | null => {
    const waiting = (turnId: string) =>
      !blobs.current.has(turnId) && !skipped.current.has(turnId);
    const head = current.current;
    if (head && ready.current.includes(head) && waiting(head)) return head;
    return ready.current.find(waiting) ?? null;
  }, []);

  const pump = useCallback(() => {
    const prefetch = api.prefetchNextDebateAudio?.bind(api);
    const epoch = controllerEpochRef.current;
    if (!alive.current || !enabled || !gateOpen || !prefetch || !epoch) return;
    if (inFlight.current) return;
    const turnId = next();
    if (!turnId) return;
    const abort = new AbortController();
    const startedAt = performance.now();
    const done = (async (): Promise<string | null> => {
      try {
        const ticket = await prefetch(debateId, {
          controller_epoch: epoch,
          turn_id: turnId,
        });
        const response = await fetch(ticket.media_url, {
          credentials: "same-origin",
          signal: abort.signal,
        });
        if (!response.ok) throw new Error(`prefetch ${response.status}`);
        const blob = await response.blob();
        if (abort.signal.aborted || !alive.current) return null;
        const url = URL.createObjectURL(blob);
        blobs.current.set(turnId, url);
        console.info(
          `[debate-timing] stage=audio_prefetch turn=${turnId} bytes=${blob.size} ms=${Math.round(performance.now() - startedAt)}`,
        );
        return url;
      } catch {
        if (!abort.signal.aborted) {
          const count = (failures.current.get(turnId) ?? 0) + 1;
          failures.current.set(turnId, count);
          // One retry later; a second failure leaves it to the URL.
          if (count >= 2) skipped.current.add(turnId);
        }
        return null;
      } finally {
        if (inFlight.current?.turnId === turnId) inFlight.current = null;
        if (alive.current) setWake((value) => value + 1);
      }
    })();
    inFlight.current = { turnId, abort, done };
  }, [api, controllerEpochRef, debateId, enabled, gateOpen, next]);

  useEffect(() => {
    pump();
  }, [pump, controllerReady, wake]);

  useEffect(() => {
    alive.current = true;
    const owned = blobs.current;
    const queue = ready;
    const flight = inFlight;
    return () => {
      // Leaving Immerse: stop the download, forget the queue, free the blobs.
      alive.current = false;
      flight.current?.abort.abort();
      flight.current = null;
      queue.current = [];
      for (const url of owned.values()) URL.revokeObjectURL(url);
      owned.clear();
    };
  }, []);

  /** Speeches whose audio the server says is ready (snapshot or event). */
  const noteReady = useCallback((turnIds: readonly string[]) => {
    let added = false;
    for (const turnId of turnIds) {
      if (!turnId || ready.current.includes(turnId)) continue;
      ready.current.push(turnId);
      added = true;
    }
    if (added) setWake((value) => value + 1);
  }, []);

  /** The speech the stage shows now; it goes first while it has not started. */
  const noteCurrent = useCallback((turnId: string | null | undefined) => {
    if (current.current === (turnId ?? null)) return;
    current.current = turnId ?? null;
    setWake((value) => value + 1);
  }, []);

  /**
   * What to play for ``turnId``: its blob, its download if that finishes
   * within the wait, else ``mediaUrl`` (the download is then aborted or
   * never started, so the file is fetched once). ``null`` when there is no
   * blob and no URL yet.
   */
  const sourceFor = useCallback(
    async (
      turnId: string,
      mediaUrl: string | null,
      waitMs: number = DOWNLOAD_WAIT_MS,
    ): Promise<string | null> => {
      loadStartedAt.current = { turnId, at: performance.now() };
      const cached = blobs.current.get(turnId);
      if (cached) return cached;
      const pending = inFlight.current;
      if (pending?.turnId === turnId) {
        let timer = 0;
        const timeout = new Promise<null>((resolve) => {
          timer = window.setTimeout(() => resolve(null), waitMs);
        });
        const url = await Promise.race([pending.done, timeout]);
        window.clearTimeout(timer);
        if (url) return url;
        const finished = blobs.current.get(turnId);
        if (finished) return finished;
        if (!mediaUrl) return null;
        pending.abort.abort();
      }
      if (!mediaUrl) return null;
      // Plays from the URL: never queue the same file as well.
      skipped.current.add(turnId);
      setWake((value) => value + 1);
      return mediaUrl;
    },
    [],
  );

  /**
   * The source to play right now, without waiting: the blob, or the URL when
   * no download of this speech is running. ``null`` means its download is in
   * flight; ``sourceFor`` waits for it.
   */
  const sourceNow = useCallback(
    (turnId: string, mediaUrl: string | null): string | null => {
      loadStartedAt.current = { turnId, at: performance.now() };
      const cached = blobs.current.get(turnId);
      if (cached) return cached;
      if (inFlight.current?.turnId === turnId || !mediaUrl) return null;
      skipped.current.add(turnId);
      setWake((value) => value + 1);
      return mediaUrl;
    },
    [],
  );

  /** The blob URL already downloaded for ``turnId``, if any. */
  const blobFor = useCallback(
    (turnId: string) => blobs.current.get(turnId) ?? null,
    [],
  );

  /** Log how long the browser waited between asking and playing. */
  const notePlaying = useCallback((turnId: string | null) => {
    noteDebateSpeechPlaying();
    const startedAt = loadStartedAt.current;
    if (!startedAt || startedAt.turnId !== turnId) return;
    loadStartedAt.current = null;
    console.info(
      `[debate-timing] stage=audio_start turn=${turnId} prefetched=${turnId ? blobs.current.has(turnId) : false} ms=${Math.round(performance.now() - startedAt.at)}`,
    );
  }, []);

  return useMemo(
    () => ({
      noteReady,
      noteCurrent,
      sourceNow,
      sourceFor,
      blobFor,
      notePlaying,
    }),
    [noteReady, noteCurrent, sourceNow, sourceFor, blobFor, notePlaying],
  );
}

export type ImmerseAudioQueue = ReturnType<typeof useImmerseAudioQueue>;
