"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  createIdempotencyHandle,
  PlatformApiError,
  type DebateDetail,
  type DebateCleanupRequest,
  type IdempotencyHandle,
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
  const audioRequests = useRef(new Map<string, IdempotencyHandle>());
  const loadDetailRef = useRef(loadDetail);
  useEffect(() => {
    loadDetailRef.current = loadDetail;
  }, [loadDetail]);

  useEffect(() => {
    const version = snapshotVersion.current;
    const timer = window.setTimeout(() => {
      if (!active.current && version === snapshotVersion.current)
        setRevoice(audioRestoreNeeded ?? missingAudioIds(detail).length > 0);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [detail, debateId, audioRestoreNeeded]);

  async function refresh() {
    try {
      await onVoiceDeleted();
      if (loadDetailRef.current) {
        const snapshot = await loadDetailRef.current();
        setRevoice(missingAudioIds(snapshot).length > 0);
      }
    } catch {
      /* A failed refresh does not undo a committed action. */
    }
  }

  async function generateAudio() {
    if (active.current) return;
    active.current = true;
    snapshotVersion.current += 1;
    setBusy(true);
    setGeneratingAudio(true);
    try {
      const snapshot = loadDetailRef.current
        ? await loadDetailRef.current()
        : detail;
      if (!snapshot) return;
      for (const turnId of missingAudioIds(snapshot)) {
        const key =
          audioRequests.current.get(turnId) ?? createIdempotencyHandle();
        audioRequests.current.set(turnId, key);
        const result = await api.regenerateDebateTurnAudio(
          snapshot.id,
          turnId,
          { expected_revision: snapshot.revision },
          { idempotency: key },
        );
        if (!result.audio_ready) {
          if (result.status !== "queued") audioRequests.current.delete(turnId);
          return;
        }
        audioRequests.current.delete(turnId);
      }
      setRevoice(false);
    } catch {
      /* Leave Revocalize available when restoration fails. */
    } finally {
      await refresh();
      active.current = false;
      setBusy(false);
      setGeneratingAudio(false);
    }
  }

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
        intent.current = null;
        if (onAllDeleted) await onAllDeleted();
        else router.push(backHref);
      } else if (result.cleanup_status !== "pending") {
        intent.current = null;
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
        title={labelled ? undefined : voiceLabel}
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
        title={labelled ? undefined : deleteLabel}
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
