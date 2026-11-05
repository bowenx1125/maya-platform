"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
    if (job && Object.keys(job.turns).length > 0) {
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
      active.current = true;
      snapshotVersion.current += 1;
      setBusy(true);
      setGeneratingAudio(true);
      try {
        const id = debateId ?? detail?.id;
        let job = id ? readAudioJob(id, restoreOwnerId) : null;
        let snapshot: DebateDetail | undefined;
        // A refresh may race a temporarily unavailable snapshot. Keep the already
        // authorized job rather than losing its unsent turns.
        for (;;) {
          try {
            snapshot = loadDetailRef.current
              ? await loadDetailRef.current()
              : detail;
            break;
          } catch (cause) {
            if (!resume || !job || !isAmbiguousMutationFailure(cause))
              throw cause;
            await wait(AUDIO_QUEUE_POLL_MS);
            if (!mounted.current) return;
          }
        }
        if (!snapshot || !mounted.current) return;
        if (job && job.revision !== snapshot.revision) {
          saveAudioJob(snapshot.id, null);
          job = null;
          if (resume) return;
        }
        const missing = [
          ...new Set([...missingAudioIds(snapshot), ...regenerableIds.current]),
        ];
        if (resume && !job) return;
        job ??= {
          ownerId: restoreOwnerId,
          revision: snapshot.revision,
          turns: {},
        };
        for (const turnId of Object.keys(job.turns)) {
          if (!missing.includes(turnId)) delete job.turns[turnId];
        }
        if (!resume) {
          for (const turnId of missing) {
            if (!job.turns[turnId] || job.turns[turnId].failed) {
              job.turns[turnId] = { key: createIdempotencyHandle().key };
            }
          }
        }
        const restore = job;
        // Persist the entire batch before dispatch, then submit every turn. A
        // page unload cannot strand the later turns behind one slow TTS call.
        saveAudioJob(snapshot.id, restore);
        await Promise.all(
          Object.entries(restore.turns).map(async ([turnId, request]) => {
            if (request.failed) return;
            const handle = new IdempotencyHandle(request.key);
            while (mounted.current) {
              try {
                const result = await api.regenerateDebateTurnAudio(
                  snapshot.id,
                  turnId,
                  { expected_revision: restore.revision },
                  { idempotency: handle },
                );
                if (!mounted.current) return;
                if (result.audio_ready) {
                  delete restore.turns[turnId];
                  regenerableIds.current = regenerableIds.current.filter(
                    (id) => id !== turnId,
                  );
                  saveAudioJob(snapshot.id, restore);
                  return;
                }
                if (result.status !== "queued") {
                  request.failed = true;
                  saveAudioJob(snapshot.id, restore);
                  return;
                }
              } catch (cause) {
                if (!isAmbiguousMutationFailure(cause)) {
                  request.failed = true;
                  saveAudioJob(snapshot.id, restore);
                  return;
                }
                // An ambiguous response must reuse its key, never bill a new retry.
              }
              await wait(AUDIO_QUEUE_POLL_MS);
            }
          }),
        );
        if (mounted.current && Object.keys(restore.turns).length === 0) {
          regenerableIds.current = [];
          setRevoice(false);
        }
      } catch {
        /* Leave Revocalize available when restoration fails. */
      } finally {
        if (mounted.current) {
          await refresh();
          active.current = false;
          setBusy(false);
          setGeneratingAudio(false);
        }
      }
    },
    [api, debateId, detail, refresh, restoreOwnerId],
  );

  useEffect(() => {
    const id = debateId ?? detail?.id;
    if (!id) return;
    const job = readAudioJob(id, restoreOwnerId);
    if (!job || !Object.values(job.turns).some((turn) => !turn.failed)) return;
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
