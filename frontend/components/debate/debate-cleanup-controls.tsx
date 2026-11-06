"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import {
  createIdempotencyHandle,
  PlatformApiError,
  isAmbiguousMutationFailure,
  IdempotencyHandle,
  type DebateDetail,
  type DebateCleanupRequest,
  type PlatformApi,
} from "../../lib/api";
import { cn } from "../../lib/utils";
import {
  IconBell,
  IconBellOff,
  IconClose,
  IconSpinner,
  IconDebateTrash,
} from "../quiet-icons";

type Intent = {
  debateId: string;
  mode: "voice" | "all";
  body: DebateCleanupRequest;
  key: IdempotencyHandle;
};

const AUDIO_QUEUE_POLL_MS = 1_000;
const AUDIO_RESTORE_CONCURRENCY = 3;
// Admission refused BEFORE synthesis; the backend stores this terminal receipt.
// A fresh key is safe only for this pre-provider failure, not a TTS timeout or
// interrupted/unknown acceptance (which require a teacher's explicit retry).
const RETRYABLE_ADMISSION_CODE = "tts_provider_unavailable";
type AudioRestoreJob = {
  ownerId?: string;
  revision: number;
  turns: Record<string, { key: string; failed?: boolean }>;
};

function audioJobKey(id: string) {
  return `maya:revocalize:v1:${id}`;
}

function readAudioJob(id: string, ownerId?: string): AudioRestoreJob | null {
  try {
    const job = JSON.parse(localStorage.getItem(audioJobKey(id)) ?? "null");
    if (
      !job ||
      job.ownerId !== ownerId ||
      !Number.isInteger(job.revision) ||
      !job.turns ||
      typeof job.turns !== "object" ||
      Array.isArray(job.turns)
    )
      return null;
    if (
      !Object.values(job.turns).every(
        (turn) =>
          turn &&
          typeof turn === "object" &&
          "key" in turn &&
          typeof turn.key === "string" &&
          turn.key.length > 0,
      )
    )
      return null;
    return job as AudioRestoreJob;
  } catch {
    return null;
  }
}

function saveAudioJob(id: string, job: AudioRestoreJob | null) {
  try {
    if (job) {
      localStorage.setItem(audioJobKey(id), JSON.stringify(job));
    } else {
      localStorage.removeItem(audioJobKey(id));
    }
  } catch {
    // Storage can be unavailable in private browsing; this page can still finish.
  }
}

function missingAudioIds(detail?: DebateDetail): string[] {
  if (detail?.turn_protocol !== "segments_v2") return [];
  return [
    ...new Set([
      ...(detail.preview_turns ?? [])
        .filter(
          (turn) =>
            turn.speech &&
            !turn.audio_ready &&
            turn.generation_status === "final_ready",
        )
        .map((turn) => turn.id),
      ...(detail.public_turns ?? [])
        .filter((turn) => turn.speech && turn.audio_ready === false)
        .map((turn) => turn.id),
    ]),
  ];
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

export function DebateCleanupControls({
  detail,
  debateId,
  api,
  onVoiceDeleted,
  backHref = "/teacher/debates",
  loadDetail,
  onAllDeleted,
  className = "row-actions",
  audioRestoreNeeded,
  restoreOwnerId,
  iconClassName = "",
  labelled = false,
  dangerClassName = "",
  afterVoice,
}: {
  detail?: DebateDetail;
  debateId?: string;
  loadDetail?: () => Promise<DebateDetail>;
  onAllDeleted?: () => void | Promise<void>;
  className?: string;
  audioRestoreNeeded?: boolean;
  restoreOwnerId?: string;
  iconClassName?: string;
  /** Draw icon + visible text (Debates list, final mockup F); the label
   * stays while busy, with a spinner and aria-busy. */
  labelled?: boolean;
  dangerClassName?: string;
  /** Rendered between Devocalize/Revocalize and Delete (list End). */
  afterVoice?: ReactNode;
  api: Pick<
    PlatformApi,
    "deleteDebateVoice" | "deleteDebateAll" | "regenerateDebateTurnAudio"
  >;
  onVoiceDeleted: () => void | Promise<void>;
  backHref?: string;
}) {
  const router = useRouter();
  const intent = useRef<Intent | null>(null);
  const active = useRef(false);
  const snapshotVersion = useRef(0);
  const [busy, setBusy] = useState(false);
  const [removal, setRemoval] = useState<"voice" | "all" | null>(null);
  const [revoice, setRevoice] = useState(
    () => audioRestoreNeeded ?? missingAudioIds(detail).length > 0,
  );
  const [generatingAudio, setGeneratingAudio] = useState(false);
  const [audioError, setAudioError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const regenerableIds = useRef<string[]>([]);
  const loadDetailRef = useRef(loadDetail);
  useEffect(() => {
    loadDetailRef.current = loadDetail;
  }, [loadDetail]);

  useEffect(() => {
    const version = snapshotVersion.current;
    const timer = window.setTimeout(() => {
      if (!active.current && version === snapshotVersion.current) {
        setRevoice(
          audioRestoreNeeded ??
            (missingAudioIds(detail).length > 0 ||
              regenerableIds.current.length > 0),
        );
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [detail, debateId, audioRestoreNeeded]);

  const refresh = useCallback(async () => {
    try {
      await onVoiceDeleted();
      if (loadDetailRef.current) {
        const snapshot = await loadDetailRef.current();
        setRevoice(
          missingAudioIds(snapshot).length > 0 ||
            regenerableIds.current.length > 0,
        );
      }
    } catch {
      /* A failed refresh does not undo a committed action. */
    }
  }, [onVoiceDeleted]);

  const generateAudio = useCallback(
    async (resume = false) => {
      if (active.current) return;
      const id = debateId ?? detail?.id;
      if (!id) return;
      let job = readAudioJob(id, restoreOwnerId);
      if (resume && !job) return;
      // Persist intent BEFORE fetching detail. Even navigation during the first
      // GET must leave a resumable marker, including when no turn IDs are known.
      job ??= { ownerId: restoreOwnerId, revision: -1, turns: {} };
      if (!resume) {
        for (const request of Object.values(job.turns)) {
          if (request.failed) {
            request.key = createIdempotencyHandle().key;
            delete request.failed;
          }
        }
      }
      saveAudioJob(id, job);
      active.current = true;
      snapshotVersion.current += 1;
      setBusy(true);
      setGeneratingAudio(true);
      setRevoice(true);
      setAudioError(null);
      // Only a detail-only caller needs local confirmation: its prop may be a
      // frozen snapshot. List rows always verify against a fresh detail GET.
      const confirmedReady = new Set<string>();
      try {
        while (mounted.current) {
          let snapshot: DebateDetail | undefined;
          try {
            snapshot = loadDetailRef.current
              ? await loadDetailRef.current()
              : detail;
          } catch (cause) {
            if (!isAmbiguousMutationFailure(cause)) throw cause;
            await wait(AUDIO_QUEUE_POLL_MS);
            continue;
          }
          if (!snapshot || !mounted.current) return;
          if (job.revision !== snapshot.revision) {
            // Reconcile the NEW snapshot, never drop the teacher's intent just
            // because cleanup/Rebirth advanced the revision. Old keys must not
            // be replayed with a different expected_revision/body.
            if (job.revision !== -1) regenerableIds.current = [];
            job = {
              ownerId: restoreOwnerId,
              revision: snapshot.revision,
              turns: {},
            };
            confirmedReady.clear();
          }
          const missing = [
            ...new Set([
              ...missingAudioIds(snapshot),
              ...regenerableIds.current,
            ]),
          ].filter(
            (turnId) => loadDetailRef.current || !confirmedReady.has(turnId),
          );
          for (const turnId of Object.keys(job.turns)) {
            if (!missing.includes(turnId)) delete job.turns[turnId];
          }
          // Resume also seeds IDs omitted from the stored batch (or exposed by
          // the new snapshot). Persist the WHOLE queue before any dispatch.
          for (const turnId of missing) {
            job.turns[turnId] ??= { key: createIdempotencyHandle().key };
          }
          saveAudioJob(id, job);
          if (missing.length === 0) {
            // Never clear intent just because the last request finished. Only
            // a reconciled snapshot (or ready receipts without a loader) can.
            saveAudioJob(id, null);
            regenerableIds.current = [];
            setRevoice(false);
            break;
          }
          const restore = job;
          const queue = Object.entries(restore.turns).filter(
            ([, turn]) => !turn.failed,
          );
          if (queue.length === 0) {
            const failedTurns = missing.map((turnId) => {
              const turn = [
                ...(snapshot.preview_turns ?? []),
                ...snapshot.public_turns,
              ].find((candidate) => candidate.id === turnId);
              return turn && Number.isInteger(turn.turn_index)
                ? turn.turn_index + 1
                : turnId;
            });
            setAudioError(
              `Audio could not be restored for ${missing.length} speech turn(s) (${failedTurns.join(", ")}). Click Revocalize to retry.`,
            );
            break;
          }
          let cursor = 0;
          let reconcile = false;
          await Promise.all(
            Array.from(
              { length: Math.min(AUDIO_RESTORE_CONCURRENCY, queue.length) },
              async () => {
                while (mounted.current && !reconcile && cursor < queue.length) {
                  const [turnId, request] = queue[cursor++];
                  let delay = AUDIO_QUEUE_POLL_MS;
                  while (mounted.current && !reconcile) {
                    // Construct from the persisted key each time: the API handle
                    // completes on terminal results, but the durable receipt key
                    // still identifies that attempt across reloads.
                    const handle = new IdempotencyHandle(request.key);
                    try {
                      const result = await api.regenerateDebateTurnAudio(
                        id,
                        turnId,
                        { expected_revision: restore.revision },
                        { idempotency: handle },
                      );
                      if (!mounted.current) return;
                      if (result.audio_ready) {
                        delete restore.turns[turnId];
                        confirmedReady.add(turnId);
                        regenerableIds.current = regenerableIds.current.filter(
                          (value) => value !== turnId,
                        );
                        saveAudioJob(id, restore);
                        break;
                      }
                      if (result.status === "queued")
                        delay = AUDIO_QUEUE_POLL_MS;
                      if (
                        result.status === "stale" ||
                        result.safe_error_code === "stale_revision"
                      ) {
                        if (loadDetailRef.current) {
                          reconcile = true;
                          break;
                        }
                        request.failed = true;
                      } else if (
                        result.safe_error_code === RETRYABLE_ADMISSION_CODE
                      ) {
                        // Definitively NOT submitted to the provider. Reusing its
                        // failed receipt would return the same failure forever.
                        request.key = createIdempotencyHandle().key;
                      } else if (
                        result.status !== "queued" &&
                        result.safe_error_code !== "claim_unavailable"
                      ) {
                        request.failed = true;
                      }
                      saveAudioJob(id, restore);
                      if (request.failed) break;
                    } catch (cause) {
                      if (!mounted.current) return;
                      if (
                        cause instanceof PlatformApiError &&
                        cause.code === "stale_revision" &&
                        loadDetailRef.current
                      ) {
                        reconcile = true;
                        break;
                      }
                      if (!isAmbiguousMutationFailure(cause)) {
                        request.failed = true;
                        saveAudioJob(id, restore);
                        break;
                      }
                      // Network, 408/425/429/5xx: keep the exact durable key;
                      // acceptance may be unknown, so never create a new attempt.
                    }
                    await wait(delay);
                    delay = Math.min(delay * 2, 15_000);
                  }
                }
              },
            ),
          );
          // Re-fetch before claiming success or stopping with surfaced failures.
          if (mounted.current && reconcile) await wait(AUDIO_QUEUE_POLL_MS);
        }
      } catch {
        if (mounted.current) {
          setAudioError(
            "Audio restoration is unavailable. Click Revocalize to retry.",
          );
        }
        // Keep the durable intent, including an empty queue, for the next mount.
      } finally {
        if (mounted.current) {
          await refresh();
          if (mounted.current) {
            active.current = false;
            setBusy(false);
            setGeneratingAudio(false);
          }
        }
      }
    },
    [api, debateId, detail, refresh, restoreOwnerId],
  );

  useEffect(() => {
    const id = debateId ?? detail?.id;
    if (!id || !readAudioJob(id, restoreOwnerId)) return;
    // Failed-only and empty queues still reconcile detail: new eligible turns
    // must be enqueued and definitive failures must remain visible after Back/F5.
    const timer = window.setTimeout(() => void generateAudio(true), 0);
    return () => window.clearTimeout(timer);
  }, [debateId, detail?.id, generateAudio, restoreOwnerId]);

  async function remove(mode: "voice" | "all") {
    if (active.current) return;
    let request = intent.current?.mode === mode ? intent.current : null;
    if (
      !request &&
      !window.confirm(
        mode === "voice"
          ? "Delete saved audio? Speeches and sources will remain."
          : "Delete this debate, audio, messages and report?",
      )
    )
      return;
    active.current = true;
    snapshotVersion.current += 1;
    setBusy(true);
    setRemoval(mode);
    try {
      if (!request) {
        const snapshot =
          mode === "all" && (debateId || detail?.id)
            ? {
                id: debateId ?? detail!.id,
                revision: 0,
                playback: { control_version: 0 },
              }
            : loadDetailRef.current
              ? await loadDetailRef.current()
              : detail;
        if (!snapshot) return;
        request = {
          debateId: snapshot.id,
          mode,
          key: createIdempotencyHandle(),
          body: {
            expected_revision: snapshot.revision,
            expected_control_version: snapshot.playback.control_version,
          },
        };
        intent.current = request;
      }
      const result = await (
        mode === "voice"
          ? api.deleteDebateVoice.bind(api)
          : api.deleteDebateAll.bind(api)
      )(request.debateId, request.body, { idempotency: request.key });
      if (mode === "all") {
        saveAudioJob(request.debateId, null);
        intent.current = null;
        regenerableIds.current = [];
        if (onAllDeleted) await onAllDeleted();
        else router.push(backHref);
      } else if (result.cleanup_status !== "pending") {
        saveAudioJob(request.debateId, null);
        intent.current = null;
        if (
          Array.isArray(result.regenerable_turn_ids) &&
          result.regenerable_turn_ids.length > 0
        ) {
          regenerableIds.current = [...result.regenerable_turn_ids];
        }
        setRevoice(true);
        await refresh();
      }
    } catch (cause) {
      if (
        cause instanceof PlatformApiError &&
        (cause.code === "stale_revision" ||
          cause.code === "stale_control_version")
      ) {
        intent.current = null;
      }
    } finally {
      active.current = false;
      setBusy(false);
      setRemoval(null);
    }
  }

  const voiceLabel =
    removal === "voice"
      ? "Devocalizing"
      : generatingAudio
        ? "Revocalize..."
        : revoice
          ? "Revocalize"
          : "Devocalize";
  const deleteLabel = removal === "all" ? "Deleting" : "Delete";
  // Bell = this debate has its audio; clicking devocalizes. Bell struck
  // through = audio removed; clicking revocalizes (lifts the strike).
  const voiceBusy = removal === "voice" || generatingAudio;
  const deleteBusy = removal === "all";
  return (
    <div className={className}>
      {audioError ? (
        <div
          role="alert"
          className="rounded-2xl border-2 border-[#111] bg-[#FFD6E7] px-4 py-3 text-[#111] shadow-[3px_3px_0_#111]"
        >
          {audioError}
        </div>
      ) : null}
      <button
        className={labelled ? iconClassName : `icon-action ${iconClassName}`}
        type="button"
        disabled={busy}
        aria-label={voiceLabel}
        aria-busy={labelled && voiceBusy ? true : undefined}
        data-vocalized={revoice ? "false" : "true"}
        onClick={() => void (revoice ? generateAudio() : remove("voice"))}
      >
        {labelled && voiceBusy ? (
          <IconSpinner size={18} />
        ) : revoice ? (
          <IconBellOff size={18} />
        ) : (
          <IconBell size={18} />
        )}
        {labelled ? <span>{voiceLabel}</span> : null}
      </button>
      {afterVoice}
      <button
        className={
          labelled
            ? cn(iconClassName, dangerClassName)
            : `icon-action icon-action-danger ${iconClassName}`
        }
        type="button"
        disabled={busy}
        aria-label={deleteLabel}
        aria-busy={labelled && deleteBusy ? true : undefined}
        onClick={() => void remove("all")}
      >
        {labelled && deleteBusy ? (
          <IconSpinner size={18} />
        ) : labelled ? (
          <IconDebateTrash size={18} />
        ) : (
          <IconClose size={18} />
        )}
        {labelled ? <span>{deleteLabel}</span> : null}
      </button>
    </div>
  );
}
