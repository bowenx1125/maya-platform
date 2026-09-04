"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DebateStage } from "../../../../../components/debate/stage";
import type { PlaybackAuthorityState } from "../../../../../components/debate/stage/types";
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
} from "../../../../../lib/api";
import { useLocale, useT } from "../../../../../components/locale";
import { localizeError, type Locale } from "../../../../../lib/i18n";
import { expectedTurnCount } from "../../../../../lib/debate-rounds";

const INITIAL_PLAYBACK_AUTHORITY: PlaybackAuthorityState = {
  connection: "connecting",
  connectionIssue: null,
  controllerReady: false,
  commandBusy: false,
};

function canFinishWithAuthority(
  detail: DebateDetail,
  authority: PlaybackAuthorityState,
): boolean {
  return (
    detail.status === "running" &&
    detail.playback.mode === "live" &&
    // Any live, non-terminal state. Offering Finish only from waiting_next
    // trapped a debate whose turn was prepared but never played.
    detail.playback.status !== "completed" &&
    detail.playback.status !== "stopped" &&
    authority.commandBusy !== true &&
    authority.connection === "connected" &&
    authority.connectionIssue === null &&
    authority.controllerReady
  );
}

function finishBlockedCopy(
  detail: DebateDetail,
  authority: PlaybackAuthorityState,
  locale: Locale,
): string {
  const zh = locale === "zh";
  switch (authority.connectionIssue) {
    case "superseded":
      return zh
        ? "暂不可结束：另一个教师页面已取得控制权"
        : "Finish unavailable: another teacher page has control.";
    case "session_expired":
      return zh
        ? "暂不可结束：登录已失效，请重新登录"
        : "Finish unavailable: please sign in again.";
    case "origin_mismatch":
      return zh
        ? "暂不可结束：课堂访问地址与服务器配置不一致"
        : "Finish unavailable: the classroom address does not match the server configuration.";
    case "terminal":
      return zh
        ? "暂不可结束：辩论正在结束"
        : "Finish unavailable: the debate is already ending.";
    case "network":
      return zh
        ? "连接恢复后才能结束辩论"
        : "Finish unavailable until the connection is restored.";
    case "sequence_gap":
      return zh
        ? "课堂状态重新同步后才能结束辩论"
        : "Finish unavailable until classroom state is resynchronized.";
    default:
      if (
        authority.commandBusy === true ||
        detail.playback.mode !== "live" ||
        detail.playback.status === "completed" ||
        detail.playback.status === "stopped"
      ) {
        return zh
          ? "本场辩论已结束或已停止"
          : "This debate has already ended or been stopped.";
      }
      return zh
        ? "当前页面取得教师控制权后才能结束辩论"
        : "Finish unavailable until this page has active teacher control.";
  }
}

/**
 * Whether this debate ran its whole plan, and so has history worth reviewing.
 *
 * The twin of `has_complete_finished_playback` on the server, and it must
 * agree with it: a turn is only public because it was played, so the counts
 * below already prove the run completed. Playback status is not consulted —
 * it is transient, and starting the next debate or resetting a stuck one
 * moves it, which used to take the classroom-interaction entry away from a
 * lesson that had finished perfectly well.
 */
function hasCompletePublicPlan(detail: DebateDetail): boolean {
  return (
    detail.public_turns.length === expectedTurnCount(detail) &&
    detail.participants.length >= 2 &&
    detail.playback.mode === "live"
  );
}

export default function TeacherDebateControlPage() {
  const t = useT();
  const { locale } = useLocale();
  const params = useParams<{ debate_id: string | string[] }>();
  const rawDebateId = params?.debate_id;
  const debateId = Array.isArray(rawDebateId) ? rawDebateId[0] : rawDebateId;
  const { api } = useSession();
  const stageLabels = useMemo(
    () => ({
      stageTitle: t("debateStageTitle"),
      stageDescription: t("debateStageDescription"),
      start: t("debateStart"),
      pause: locale === "zh" ? "暂停" : "Pause",
      resume: locale === "zh" ? "继续" : "Continue",
      next: locale === "zh" ? "下一步" : "Next",
      replayTurn: t("debateReplayTurn"),
      replayAll: t("debateReplayAll"),
      debatePartial: t("debatePartial"),
      reconnect: locale === "zh" ? "重新连接" : "Reconnect",
      finish: locale === "zh" ? "结束辩论" : "Finish debate",
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
      phaseReady: locale === "zh" ? "等待开始" : "Ready to start",
      phaseInProgress: locale === "zh" ? "进行中" : "In progress",
      phaseWaiting: locale === "zh" ? "等待中" : "Waiting",
      phaseFinished: locale === "zh" ? "已结束" : "Finished",
      phaseOpening: t("debatePhaseOpening"),
      phaseExchange: t("debatePhaseExchange"),
      phaseFinalIntegration: t("debatePhaseFinalIntegration"),
      waitingForAudio: t("debateWaitingForAudio"),
      connectionReady: t("debateConnectionReady"),
      connectionReconnecting: t("debateConnectionReconnecting"),
      connectionDisconnected: t("debateConnectionDisconnected"),
      connectionSequenceGap: t("debateConnectionSequenceGap"),
      connectionSessionExpired: t("debateConnectionSessionExpired"),
      connectionOriginMismatch: t("debateConnectionOriginMismatch"),
      connectionSuperseded: t("debateConnectionSuperseded"),
      connectionError: t("debateConnectionError"),
      controllerWaiting: t("debateControllerWaiting"),
      controlBusy: t("debateControlBusy"),
      retryReason: t("debateRetryReason"),
      connectionSignIn: t("debateConnectionSignIn"),
      connectionReload: t("debateConnectionReload"),
      regenerate: t("debateRegenerate"),
      localizeCode: (code: string) => localizeError({ code }, locale),
      providerSetupIncomplete: t("debateProviderSetupIncomplete"),
      providerGateTitle: t("debateProviderGateTitle"),
      providerGateLoading: t("debateProviderGateLoading"),
      providerGateEmpty: t("debateProviderGateEmpty"),
      providerGateReview: t("debateProviderGateReview"),
      providerGateReviewAll: t("debateProviderGateReviewAll"),
      providerGateConfirmed: t("debateProviderGateConfirmed"),
      providerGateRefresh: t("debateProviderGateRefresh"),
      providerGateRetry: t("debateProviderGateRetry"),
      noPublishedSpeech: t("debateNoPublishedSpeech"),
      audioNotRetained: t("errorAudioNotRetained"),
      selectedTurn: t("debateSelectedTurn"),
      replaceRetainedAudioConfirm: t("debateReplaceAudioConfirm"),
      audioLabel: t("debateAudioLabel"),
    }),
    [locale, t],
  );
  const [detail, setDetail] = useState<DebateDetail | null>(null);
  const [currentAudioDebateId, setCurrentAudioDebateId] = useState<
    string | null | undefined
  >(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [finishBusy, setFinishBusy] = useState(false);
  const [playbackAuthority, setPlaybackAuthority] =
    useState<PlaybackAuthorityState>(INITIAL_PLAYBACK_AUTHORITY);
  const playbackAuthorityRef = useRef<PlaybackAuthorityState>(
    INITIAL_PLAYBACK_AUTHORITY,
  );
  const finishInFlight = useRef(false);
  const finishKey = useRef<IdempotencyHandle | null>(null);

  const updatePlaybackAuthority = useCallback(
    (next: PlaybackAuthorityState) => {
      playbackAuthorityRef.current = next;
      setPlaybackAuthority(next);
    },
    [],
  );

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
    if (
      !detail ||
      !debateId ||
      finishInFlight.current ||
      !canFinishWithAuthority(detail, playbackAuthorityRef.current)
    ) {
      return;
    }
    finishInFlight.current = true;
    setFinishBusy(true);
    setError(null);
    const handle = finishKey.current ?? createIdempotencyHandle();
    finishKey.current = handle;
    try {
      const next = await api.finishDebate(
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
      finishInFlight.current = false;
      setFinishBusy(false);
    }
  }, [api, debateId, detail, refreshSnapshot]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const finishAllowed = detail
    ? canFinishWithAuthority(detail, playbackAuthority)
    : false;

  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        {loading && !detail ? <LoadingCard /> : null}
        {!loading && error && !detail ? (
          <ErrorNotice error={error} onRetry={() => void load()} />
        ) : null}
        {detail && debateId ? (
          <>
            <PageIntro eyebrow={t("debateList")} title={detail.topic} />
            {error ? (
              <ErrorNotice
                error={error}
                onRetry={() => void refreshSnapshot()}
              />
            ) : null}
            <DebateStage
              headerActions={
                <>
                  <Link className="secondary-action" href="/teacher/debates">
                    {t("debateBack")}
                  </Link>
                  {detail.status === "running" &&
                  detail.playback.mode === "live" ? (
                    <>
                      <button
                        aria-describedby={
                          finishAllowed ? undefined : "finish-authority-message"
                        }
                        className="primary-action"
                        disabled={finishBusy || !finishAllowed}
                        onClick={() => void finish()}
                        type="button"
                      >
                        {finishBusy
                          ? locale === "zh"
                            ? "正在结束…"
                            : "Finishing…"
                          : stageLabels.finish}
                      </button>
                      {finishAllowed ? null : (
                        <span id="finish-authority-message" role="status">
                          {finishBlockedCopy(detail, playbackAuthority, locale)}
                        </span>
                      )}
                    </>
                  ) : null}
                  {(detail.status === "debate_finished" ||
                    detail.status === "completed") &&
                  hasCompletePublicPlan(detail) ? (
                    <Link
                      className="primary-action"
                      href={`/teacher/debates/${debateId}/interaction`}
                    >
                      {t("wave3Title")}
                    </Link>
                  ) : null}
                </>
              }
              api={api}
              debateId={debateId}
              detail={detail}
              currentAudioDebateId={currentAudioDebateId}
              labels={stageLabels}
              onAuthorityChange={updatePlaybackAuthority}
              onDetailChange={setDetail}
              onCurrentAudioDebateIdChange={setCurrentAudioDebateId}
              actionInFlight={finishBusy}
              refreshSnapshot={refreshSnapshot}
            />
          </>
        ) : null}
      </AppShell>
    </RouteGuard>
  );
}
