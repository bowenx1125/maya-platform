"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  apiErrorMessage,
  createIdempotencyHandle,
  PlatformApiError,
  type DebateDetail,
  type DebateCleanupRequest,
  type IdempotencyHandle,
  type PlatformApi,
} from "../../lib/api";

type Intent = {
  debateId: string;
  mode: "voice" | "all";
  body: DebateCleanupRequest;
  key: IdempotencyHandle;
};

export function DebateCleanupControls({
  detail,
  debateId,
  api,
  onVoiceDeleted,
  backHref = "/teacher/debates",
  loadDetail,
  onAllDeleted,
  className = "row-actions",
  showDeleteControls = true,
  showGenerateAudio = true,
}: {
  detail?: DebateDetail;
  debateId?: string;
  loadDetail?: () => Promise<DebateDetail>;
  onAllDeleted?: () => void | Promise<void>;
  className?: string;
  showDeleteControls?: boolean;
  showGenerateAudio?: boolean;
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [lockedMode, setLockedMode] = useState<"voice" | "all" | null>(null);

  const audioRequests = useRef(new Map<string, IdempotencyHandle>());
  const [generatingAudio, setGeneratingAudio] = useState(false);
  const missingAudio =
    detail?.turn_protocol === "segments_v2"
      ? [
          ...new Set([
            ...(detail.preview_turns ?? [])
              .filter(
                (turn) =>
                  turn.speech &&
                  !turn.audio_ready &&
                  turn.generation_status === "final_ready",
              )
              .map((turn) => turn.id),
            ...detail.public_turns
              .filter((turn) => turn.speech && turn.audio_ready === false)
              .map((turn) => turn.id),
          ]),
        ]
      : [];

  async function generateAudio() {
    if (!detail || active.current || lockedMode !== null) return;
    active.current = true;
    setBusy(true);
    setGeneratingAudio(true);
    setError(null);
    try {
      for (const turnId of missingAudio) {
        const key =
          audioRequests.current.get(turnId) ?? createIdempotencyHandle();
        audioRequests.current.set(turnId, key);
        const result = await api.regenerateDebateTurnAudio(
          detail.id,
          turnId,
          { expected_revision: detail.revision },
          { idempotency: key },
        );
        if (!result.audio_ready) {
          if (result.status !== "queued") audioRequests.current.delete(turnId);
          throw new Error(
            result.status === "queued"
              ? "Audio is still preparing. Refresh to check progress."
              : "Audio could not be prepared. Please try again.",
          );
        }
        audioRequests.current.delete(turnId);
        await onVoiceDeleted();
      }
    } catch (cause) {
      setError(apiErrorMessage(cause));
    } finally {
      active.current = false;
      setBusy(false);
      setGeneratingAudio(false);
      await onVoiceDeleted();
    }
  }

  async function remove(mode: "voice" | "all") {
    if (active.current) return;
    let request = intent.current;
    if (!request) {
      if (
        !window.confirm(
          mode === "voice"
            ? "Delete saved audio? Speeches and sources will remain."
            : "Delete this debate, audio, messages and report?",
        )
      )
        return;
      active.current = true;
      setBusy(true);
      setError(null);
      try {
        const snapshot =
          mode === "all" && (debateId || detail?.id)
            ? {
                id: debateId ?? detail!.id,
                revision: 0,
                playback: { control_version: 0 },
              }
            : (detail ?? (await loadDetail?.()));
        if (!snapshot)
          throw new Error("Debate is unavailable. Refresh and try again.");
        request = {
          debateId: snapshot.id,
          mode,
          key: createIdempotencyHandle(),
          body: {
            expected_revision: snapshot.revision,
            expected_control_version: snapshot.playback.control_version,
          },
        };
      } catch (cause) {
        setError(apiErrorMessage(cause));
        active.current = false;
        setBusy(false);
        return;
      }
      intent.current = request;
      setLockedMode(mode);
    }
    if (request.mode !== mode) return;
    active.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await (
        mode === "voice"
          ? api.deleteDebateVoice.bind(api)
          : api.deleteDebateAll.bind(api)
      )(request.debateId, request.body, { idempotency: request.key });
      if (result.cleanup_status === "pending") {
        if (mode === "all") {
          if (onAllDeleted) await onAllDeleted();
          else router.push(backHref);
          return;
        }
        setPending(true);
        return;
      }
      intent.current = null;
      setPending(false);
      setLockedMode(null);
      if (mode === "all") {
        if (onAllDeleted) await onAllDeleted();
        else router.push(backHref);
      } else await onVoiceDeleted();
    } catch (cause) {
      setError(apiErrorMessage(cause));
      if (
        cause instanceof PlatformApiError &&
        (cause.code === "stale_revision" ||
          cause.code === "stale_control_version")
      ) {
        intent.current = null;
        setLockedMode(null);
        await onVoiceDeleted();
      }
    } finally {
      active.current = false;
      setBusy(false);
    }
  }

  if (
    !showDeleteControls &&
    (!showGenerateAudio || missingAudio.length === 0) &&
    !busy &&
    !error &&
    !pending
  )
    return null;

  return (
    <div className={className}>
      {showDeleteControls ? (
        <>
          <button
            className="secondary-action"
            type="button"
            disabled={busy || (lockedMode !== null && lockedMode !== "voice")}
            onClick={() => void remove("voice")}
          >
            Unvoice
          </button>
          <button
            className="secondary-action"
            type="button"
            disabled={busy || (lockedMode !== null && lockedMode !== "all")}
            onClick={() => void remove("all")}
          >
            Destroy
          </button>
        </>
      ) : null}
      {showGenerateAudio && missingAudio.length > 0 ? (
        <button
          className="secondary-action"
          type="button"
          disabled={busy || lockedMode !== null}
          onClick={() => void generateAudio()}
        >
          Generate Audio
        </button>
      ) : null}
      {busy ? (
        <span role="status">
          {generatingAudio ? "Preparing audio…" : "Deleting…"}
        </span>
      ) : null}
      {pending && !showDeleteControls ? (
        <span role="status">Cleanup pending. Retry this action.</span>
      ) : null}
      {error && !showDeleteControls ? <span role="alert">{error}</span> : null}
    </div>
  );
}
