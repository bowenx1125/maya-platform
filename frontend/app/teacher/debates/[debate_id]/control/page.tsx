"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DebateStage } from "../../../../../components/debate/stage";
import { AppShell } from "../../../../../components/app-shell";
import {
  RouteGuard,
  useSession,
} from "../../../../../components/session-provider";
import {
  ErrorNotice,
  LoadingCard,
  PageIntro,
} from "../../../../../components/ui";
import {
  createIdempotencyHandle,
  type DebateDetail,
  type IdempotencyHandle,
  type PlatformApi,
} from "../../../../../lib/api";
import { useT } from "../../../../../components/locale";

type FinishCapableApi = PlatformApi & {
  finishDebate?: (
    debateId: string,
    body: {
      expected_control_version: number;
      expected_current_turn_id?: string | null;
    },
    options?: { idempotency?: IdempotencyHandle },
  ) => Promise<DebateDetail>;
};

export default function TeacherDebateControlPage() {
  const t = useT();
  const params = useParams<{ debate_id: string | string[] }>();
  const rawDebateId = params?.debate_id;
  const debateId = Array.isArray(rawDebateId) ? rawDebateId[0] : rawDebateId;
  const { api } = useSession();
  const finishApi = api as FinishCapableApi;
  const stageLabels = useMemo(
    () => ({
      stageTitle: t("debateStageTitle"),
      stageDescription: t("debateStageDescription"),
      start: t("debateStart"),
      pause: t("debatePause"),
      resume: t("debateResume"),
      skip: t("debateSkip"),
      next: t("debateNext"),
      stop: t("debateStop"),
      replayAll: t("debateReplayAll"),
      replayTurn: t("debateReplayTurn"),
      retryPlayback: t("debateRetryPlayback"),
      transcript: t("debateTranscript"),
      sources: t("debateSources"),
      noSources: t("debateNoSources"),
      round: t("debateRound"),
      current: t("debateCurrent"),
      prepared: t("debatePrepared"),
      debateComplete: t("debateComplete"),
      debateStopped: t("debateStopped"),
      debateFailed: t("debateFailed"),
      statusPreparing: t("statusPreparing"),
      statusReady: t("statusReady"),
      statusPlaying: t("statusPlaying"),
      statusPaused: t("statusPaused"),
      waitingNext: t("debateWaitingNext"),
      waitingForAudio: t("debateWaitingForAudio"),
      audioPaused: t("debateAudioPaused"),
      connectionReady: t("debateConnectionReady"),
      connectionReconnecting: t("debateConnectionReconnecting"),
      connectionDisconnected: t("debateConnectionDisconnected"),
      connectionError: t("debateConnectionError"),
      controllerWaiting: t("debateControllerWaiting"),
      controlBusy: t("debateControlBusy"),
      retryReason: t("debateRetryReason"),
      noPublishedSpeech: t("debateNoPublishedSpeech"),
      audioNotRetained: t("errorAudioNotRetained"),
      selectedTurn: t("debateSelectedTurn"),
      replaceRetainedAudioConfirm: t("debateReplaceAudioConfirm"),
      audioLabel: t("debateAudioLabel"),
    }),
    [t],
  );
  const [detail, setDetail] = useState<DebateDetail | null>(null);
  const [currentAudioDebateId, setCurrentAudioDebateId] = useState<
    string | null | undefined
  >(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [finishBusy, setFinishBusy] = useState(false);
  const finishKey = useRef<IdempotencyHandle | null>(null);

  const load = useCallback(async () => {
    if (!debateId) {
      setError(new Error("Debate id is missing."));
      setLoading(false);
      return null;
    }
    setError(null);
    setLoading(true);
    try {
      const next = await api.debate(debateId);
      setDetail(next);
      try {
        const course = await api.course(next.course_id);
        setCurrentAudioDebateId(course.current_audio_debate_id ?? null);
      } catch {
        // The debate snapshot remains usable if the optional course pointer cannot be read.
        setCurrentAudioDebateId(undefined);
      }
      return next;
    } catch (cause) {
      setError(cause);
      return null;
    } finally {
      setLoading(false);
    }
  }, [api, debateId]);

  const refreshSnapshot = useCallback(async () => {
    if (!debateId) throw new Error("Debate id is missing.");
    const next = await api.debate(debateId);
    setDetail(next);
    try {
      const course = await api.course(next.course_id);
      setCurrentAudioDebateId(course.current_audio_debate_id ?? null);
    } catch {
      // Unknown retention state must fail closed for replay.
      setCurrentAudioDebateId(undefined);
    }
    setError(null);
    return next;
  }, [api, debateId]);

  const finish = useCallback(async () => {
    if (!detail || !debateId || typeof finishApi.finishDebate !== "function") {
      return;
    }
    setFinishBusy(true);
    setError(null);
    const handle = finishKey.current ?? createIdempotencyHandle();
    finishKey.current = handle;
    try {
      const next = await finishApi.finishDebate(
        debateId,
        {
          expected_control_version: detail.playback.control_version,
          expected_current_turn_id: detail.playback.current_turn_id,
        },
        { idempotency: handle },
      );
      finishKey.current = null;
      setDetail(next);
      await refreshSnapshot();
    } catch (cause) {
      setError(cause);
    } finally {
      setFinishBusy(false);
    }
  }, [debateId, detail, finishApi, refreshSnapshot]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        {loading && !detail ? <LoadingCard /> : null}
        {!loading && error && !detail ? (
          <ErrorNotice error={error} onRetry={() => void load()} />
        ) : null}
        {detail && debateId ? (
          <>
            <PageIntro
              eyebrow={t("debateList")}
              title={detail.topic}
              description={t("debateListLede")}
              action={
                <div className="button-row">
                  <Link className="secondary-action" href="/teacher/debates">
                    {t("debateBack")}
                  </Link>
                  {detail.status === "running" &&
                  typeof finishApi.finishDebate === "function" ? (
                    <button
                      className="primary-action"
                      type="button"
                      onClick={() => void finish()}
                      disabled={finishBusy}
                    >
                      {finishBusy
                        ? "Finishing… / 正在结束…"
                        : "Finish debate / 结束辩论"}
                    </button>
                  ) : null}
                  {(detail.status === "debate_finished" ||
                    detail.status === "completed") && (
                    <Link
                      className="primary-action"
                      href={`/teacher/debates/${debateId}/interaction`}
                    >
                      Classroom interaction &amp; report / 课堂互动与报告
                    </Link>
                  )}
                </div>
              }
            />
            {error ? (
              <ErrorNotice
                error={error}
                onRetry={() => void refreshSnapshot()}
              />
            ) : null}
            <DebateStage
              api={api}
              debateId={debateId}
              detail={detail}
              currentAudioDebateId={currentAudioDebateId}
              labels={stageLabels}
              onDetailChange={setDetail}
              onCurrentAudioDebateIdChange={setCurrentAudioDebateId}
              refreshSnapshot={refreshSnapshot}
            />
          </>
        ) : null}
      </AppShell>
    </RouteGuard>
  );
}
