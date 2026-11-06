"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { DebatePreview } from "../../../../../components/debate/preview";
import { AppShell } from "../../../../../components/app-shell";
import { PageAction } from "../../../../../components/page-action";
import {
  RouteGuard,
  useSession,
} from "../../../../../components/session-provider";
import { ErrorNotice, LoadingCard } from "../../../../../components/ui";
import {
  createIdempotencyHandle,
  type DebateDetail,
} from "../../../../../lib/api";
import { localizeError } from "../../../../../lib/i18n";
import { retryPreviewTurnsInOrder } from "../../../../../lib/retry-preview-turns";

/** The 3D Immerse stage that classic-format (legacy_v1) debates now open in. */
function immerseControlHref(debateId: string): string {
  return `/teacher/debates-beta/${debateId}/control`;
}

export default function TeacherDebateControlPage() {
  const params = useParams<{ debate_id: string | string[] }>();
  const rawDebateId = params?.debate_id;
  const debateId = Array.isArray(rawDebateId) ? rawDebateId[0] : rawDebateId;
  const { api } = useSession();
  const router = useRouter();
  const [detail, setDetail] = useState<DebateDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [retryingPreviewTurnId, setRetryingPreviewTurnId] = useState<
    string | null
  >(null);
  const snapshotRequest = useRef(0);
  const loadRequest = useRef(0);
  const retrySession = useRef(0);

  const readSnapshot = useCallback(async () => {
    if (!debateId) throw new Error("Debate id is missing.");
    const request = ++snapshotRequest.current;
    const next = await api.debate(debateId);
    if (request !== snapshotRequest.current) return next;
    setDetail((current) =>
      current?.id === next.id &&
      (current.revision > next.revision ||
        current.last_sequence > next.last_sequence ||
        current.playback.control_version > next.playback.control_version)
        ? current
        : next,
    );
    setError(null);
    return next;
  }, [api, debateId]);

  const refreshSnapshot = readSnapshot;

  const load = useCallback(async () => {
    const request = ++loadRequest.current;
    setError(null);
    setLoading(true);
    try {
      return await refreshSnapshot();
    } catch (cause) {
      if (request === loadRequest.current) setError(cause);
      return null;
    } finally {
      if (request === loadRequest.current) setLoading(false);
    }
  }, [refreshSnapshot]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => {
      loadRequest.current += 1;
      snapshotRequest.current += 1;
      window.clearTimeout(timer);
    };
  }, [load]);

  useEffect(() => {
    return () => {
      retrySession.current += 1;
    };
  }, []);

  const showingPreview = detail?.turn_protocol === "segments_v2";
  useEffect(() => {
    if (!showingPreview) return;
    let stopped = false;
    let inFlight = false;
    let timer: number;
    const refreshPreview = async () => {
      if (stopped || inFlight || document.visibilityState === "hidden") return;
      inFlight = true;
      try {
        // Preview does not mount the classroom WebSocket controller.
        await readSnapshot();
      } catch {
        // Keep saved turns visible while the next background read recovers.
      } finally {
        inFlight = false;
      }
    };
    const poll = async () => {
      await refreshPreview();
      if (!stopped) timer = window.setTimeout(() => void poll(), 2000);
    };
    const refreshVisible = () => void refreshPreview();
    timer = window.setTimeout(() => void poll(), 2000);
    window.addEventListener("focus", refreshVisible);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => {
      stopped = true;
      snapshotRequest.current += 1;
      window.clearTimeout(timer);
      window.removeEventListener("focus", refreshVisible);
      document.removeEventListener("visibilitychange", refreshVisible);
    };
  }, [readSnapshot, showingPreview]);

  // Classic-format debates no longer have a 2D stage of their own; they run
  // on the 3D Immerse page, which carries the same playback and interaction.
  const legacy = detail !== null && detail.turn_protocol !== "segments_v2";
  useEffect(() => {
    if (legacy && debateId) router.replace(immerseControlHref(debateId));
  }, [debateId, legacy, router]);

  const retryPreviewTurns = useCallback(
    async (turnIds: string[]) => {
      if (!detail || !debateId || retryingPreviewTurnId || turnIds.length === 0)
        return;
      setError(null);
      const session = ++retrySession.current;
      try {
        // One teacher click walks every remaining failed/timeout turn in
        // turn_index order and waits until that speech is ready before the
        // next retry. The server only permits the next unprepared speech.
        await retryPreviewTurnsInOrder({
          turnIds,
          controlVersion: detail.playback.control_version,
          isCancelled: () => retrySession.current !== session,
          onTurnStart: setRetryingPreviewTurnId,
          retry: async (turnId, controlVersion) => {
            await api.retryDebatePreparation(
              debateId,
              {
                turn_id: turnId,
                expected_control_version: controlVersion,
              },
              { idempotency: createIdempotencyHandle() },
            );
          },
          refresh: refreshSnapshot,
        });
      } catch (cause) {
        setError(cause);
      } finally {
        setRetryingPreviewTurnId(null);
      }
    },
    [api, debateId, detail, refreshSnapshot, retryingPreviewTurnId],
  );

  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <PageAction name="back" href="/teacher/debates" />
        {loading && !detail ? <LoadingCard /> : null}
        {!loading && error && !detail ? (
          <ErrorNotice
            inline
            notFound="debateNotFound"
            error={error}
            onRetry={() => void load()}
          />
        ) : null}
        {legacy ? <LoadingCard /> : null}
        {detail && debateId && !legacy ? (
          <DebatePreview
            detail={detail}
            error={error ? localizeError(error) : null}
            onRetryTurn={(turnIds) => void retryPreviewTurns(turnIds)}
            retryingTurnId={retryingPreviewTurnId}
            openClassroomHref={immerseControlHref(debateId)}
          />
        ) : null}
      </AppShell>
    </RouteGuard>
  );
}
