"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  BetaDebateStage,
  resolveBetaStageLabels,
} from "../../../../../components/debate-beta/stage";
import type { PlaybackAuthorityState } from "../../../../../components/debate/stage/types";
import {
  RouteGuard,
  useSession,
} from "../../../../../components/session-provider";
import { IconClose } from "../../../../../components/quiet-icons";
import { ReportPanel } from "../../../../../components/report";
import { AgentScores } from "../../../../../components/wave3/agent-scores";
import { ErrorNotice, LoadingCard } from "../../../../../components/ui";
import {
  createIdempotencyHandle,
  type DebateDetail,
  type IdempotencyHandle,
  type TeacherInteraction,
} from "../../../../../lib/api";
import { useLocale, useT } from "../../../../../components/locale";
import { localizeError } from "../../../../../lib/i18n";
import { expectedTurnCount } from "../../../../../lib/debate-rounds";
import styles from "./control.module.css";

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
/** Whether a command was refused only because this page held an older version. */
function isStaleControlVersion(cause: unknown): boolean {
  return (
    typeof cause === "object" &&
    cause !== null &&
    (cause as { code?: unknown }).code === "stale_control_version"
  );
}

function hasCompletePublicPlan(detail: DebateDetail): boolean {
  return (
    detail.public_turns.length === expectedTurnCount(detail) &&
    detail.participants.length >= 2 &&
    detail.playback.mode === "live"
  );
}

function canConcludeSegments(detail: DebateDetail): boolean {
  return (
    detail.turn_protocol === "segments_v2" &&
    (detail.status === "debate_finished" || detail.status === "completed") &&
    hasCompletePublicPlan(detail)
  );
}

export default function TeacherDebateControlPage() {
  const t = useT();
  const { locale } = useLocale();
  const params = useParams<{ debate_id: string | string[] }>();
  const rawDebateId = params?.debate_id;
  const debateId = Array.isArray(rawDebateId) ? rawDebateId[0] : rawDebateId;
  const { api } = useSession();
  const betaLabels = useMemo(() => resolveBetaStageLabels(locale), [locale]);
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
      finish: locale === "zh" ? "结束" : "End",
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
      phaseReady: locale === "zh" ? "就绪" : "Ready",
      phaseInProgress: locale === "zh" ? "生成中" : "Generating",
      phaseWaiting: locale === "zh" ? "等待继续" : "Waiting",
      phaseFinished: locale === "zh" ? "已完成" : "Completed",
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
  const [interaction, setInteraction] = useState<TeacherInteraction | null>(
    null,
  );
  const [joinUrl, setJoinUrl] = useState<string | null>(null);
  const [joinCodeVisible, setJoinCodeVisible] = useState(false);
  const [interactionBusy, setInteractionBusy] = useState(false);
  const [interactionError, setInteractionError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [finishBusy, setFinishBusy] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const reportDialogRef = useRef<HTMLDialogElement>(null);
  const [playbackAuthority, setPlaybackAuthority] =
    useState<PlaybackAuthorityState>(INITIAL_PLAYBACK_AUTHORITY);
  const playbackAuthorityRef = useRef<PlaybackAuthorityState>(
    INITIAL_PLAYBACK_AUTHORITY,
  );
  const finishInFlight = useRef(false);
  const finishKey = useRef<IdempotencyHandle | null>(null);
  const interactionInFlight = useRef(false);
  const initialReportKey = useRef<IdempotencyHandle | null>(null);
  const interactionOpenKey = useRef<IdempotencyHandle | null>(null);
  const interactionCloseKey = useRef<IdempotencyHandle | null>(null);

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

  const readInteraction = useCallback(async () => {
    if (!debateId) return null;
    try {
      const next: TeacherInteraction = await api.teacherInteraction(debateId);
      setInteraction(next);
      setJoinUrl(next.status === "open" ? next.public_url : null);
      return next;
    } catch {
      // A running beta stage cannot read its interaction through the
      // complete-history GET yet. Preserve the last known state so a
      // transient read failure never hides an open or finalized window.
      return null;
    }
  }, [api, debateId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void readInteraction(), 0);
    return () => window.clearTimeout(timer);
  }, [readInteraction]);

  const openInteraction = useCallback(async () => {
    if (!debateId || interactionInFlight.current) return;
    if (joinUrl) {
      setJoinCodeVisible((visible) => !visible);
      return;
    }
    interactionInFlight.current = true;
    setInteractionBusy(true);
    setInteractionError(null);
    const idempotency = interactionOpenKey.current ?? createIdempotencyHandle();
    interactionOpenKey.current = idempotency;
    try {
      const next = await api.openInteraction(debateId, { idempotency });
      interactionOpenKey.current = null;
      setInteraction(next);
      setJoinUrl(next.status === "open" ? next.public_url : null);
      setJoinCodeVisible(next.status === "open" && Boolean(next.public_url));
    } catch (cause) {
      setInteractionError(localizeError(cause, locale));
    } finally {
      interactionInFlight.current = false;
      setInteractionBusy(false);
    }
  }, [api, debateId, joinUrl, locale]);

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
    if (
      next.turn_protocol === "segments_v2" &&
      (next.status === "debate_finished" || next.status === "completed")
    ) {
      await readInteraction();
    }
    setError(null);
    return next;
  }, [api, debateId, readInteraction]);

  const conclude = useCallback(async () => {
    if (
      !detail ||
      !debateId ||
      !canConcludeSegments(detail) ||
      interactionInFlight.current
    ) {
      return;
    }
    interactionInFlight.current = true;
    setInteractionBusy(true);
    setInteractionError(null);
    const openReport = async () => {
      const key = initialReportKey.current ?? createIdempotencyHandle();
      initialReportKey.current = key;
      await api.regenerateReport(debateId, { idempotency: key, initial: true });
      initialReportKey.current = null;
      setReportOpen(true);
    };
    try {
      // Conclude must use the durable end-of-lesson state, not the interaction
      // cached when this page was first opened or before the final round.
      const latest = await refreshSnapshot();
      if (!canConcludeSegments(latest)) return;
      let current = await api.teacherInteraction(debateId);
      setInteraction(current);
      if (current?.status === "finalized") {
        setInteraction(current);
        await openReport();
        return;
      }
      if (!current || current.status === "closed") {
        const idempotency =
          interactionOpenKey.current ?? createIdempotencyHandle();
        interactionOpenKey.current = idempotency;
        try {
          current = await api.openInteraction(debateId, { idempotency });
          interactionOpenKey.current = null;
        } catch (cause) {
          // If the response was lost, the open mutation may already have
          // committed. Re-read once and continue to close the observed open
          // window instead of asking the teacher to reason about a conflict.
          const observed = await readInteraction();
          if (
            !observed ||
            (observed.status !== "open" && observed.status !== "finalized")
          ) {
            throw cause;
          }
          interactionOpenKey.current = null;
          current = observed;
        }
        setInteraction(current);
        setJoinUrl(current.status === "open" ? current.public_url : null);
      }
      if (current.status === "finalized") {
        setInteraction(current);
        setJoinUrl(null);
        await openReport();
        return;
      }
      if (current.status !== "open") {
        throw new Error("The classroom interaction is not open.");
      }
      const idempotency =
        interactionCloseKey.current ?? createIdempotencyHandle();
      interactionCloseKey.current = idempotency;
      const finalized = await api.closeInteraction(debateId, { idempotency });
      interactionCloseKey.current = null;
      setInteraction(finalized);
      setJoinUrl(null);
      await openReport();
      // Closing a segments interaction also promotes the Debate to its
      // completed report state. Refresh the page-owned snapshot so a reload
      // and the current screen expose the same lifecycle state.
      try {
        await refreshSnapshot();
      } catch {
        // The close is already durable and the finalized local projection is
        // sufficient to reveal Report even if this follow-up read is lost.
      }
    } catch (cause) {
      setInteractionError(localizeError(cause, locale));
    } finally {
      interactionInFlight.current = false;
      setInteractionBusy(false);
    }
  }, [api, debateId, detail, locale, readInteraction, refreshSnapshot]);

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
    // The version this page holds can be one event behind the server -- a turn
    // that became ready while the teacher was reading moves it. Telling them to
    // refresh and press End again put the work of re-syncing on the person
    // least able to do it, so the second attempt re-reads and retries once.
    const attempt = async (from: DebateDetail) =>
      api.finishDebate(
        debateId,
        {
          expected_control_version: from.playback.control_version,
          expected_current_turn_id: from.playback.current_turn_id,
        },
        { idempotency: handle },
      );
    try {
      let next: DebateDetail;
      try {
        next = await attempt(detail);
      } catch (cause) {
        if (!isStaleControlVersion(cause)) throw cause;
        const fresh = await api.debate(debateId);
        setDetail(fresh);
        // A fresh key: the first attempt was refused, not applied.
        finishKey.current = createIdempotencyHandle();
        next = await attempt(fresh);
      }
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
  const segmentsProtocol = detail?.turn_protocol === "segments_v2";
  const segmentsPlanComplete = detail ? canConcludeSegments(detail) : false;
  const playbackComplete = detail?.playback.status === "completed";
  const showSegmentsConclude =
    playbackComplete &&
    segmentsPlanComplete &&
    interaction?.status !== "finalized";
  const showSegmentsReport =
    playbackComplete && segmentsProtocol && interaction?.status === "finalized";
  useEffect(() => {
    if (reportOpen && showSegmentsReport) reportDialogRef.current?.showModal();
  }, [reportOpen, showSegmentsReport]);
  const showOpenInteraction =
    Boolean(detail) &&
    !playbackComplete &&
    detail?.status !== "draft" &&
    detail?.playback.mode !== "replay" &&
    interaction?.status !== "finalized" &&
    (Boolean(joinUrl) || !segmentsProtocol || detail?.status === "running");

  return (
    <RouteGuard role="teacher">
      {!detail || !debateId ? (
        <div className={styles.boot}>
          <Link className={styles.bootBack} href="/teacher/debates">
            {t("debateBack")}
          </Link>
          {loading ? <LoadingCard /> : null}
          {!loading && error ? (
            <ErrorNotice
              inline
              notFound="debateNotFound"
              error={error}
              onRetry={() => void load()}
            />
          ) : null}
        </div>
      ) : (
        <>
          {error ? (
            <ErrorNotice
              notFound="debateNotFound"
              error={error}
              onRetry={() => void refreshSnapshot()}
            />
          ) : null}
          <BetaDebateStage
            headerActions={(replayButton) => (
              <>
                <Link className="secondary-action" href="/teacher/debates">
                  {t("debateBack")}
                </Link>
                {!playbackComplete &&
                detail.status === "running" &&
                detail.playback.mode === "live" ? (
                  <>
                    <button
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
                  </>
                ) : null}
                {/* Beta opens classroom messages during the debate, not
                      after it, so the join code can go up on the stage while
                      the Agents are still speaking. */}
                {showOpenInteraction ? (
                  <button
                    aria-expanded={Boolean(joinUrl) && joinCodeVisible}
                    aria-controls="classroom-join-code"
                    className="secondary-action"
                    disabled={interactionBusy}
                    onClick={() => void openInteraction()}
                    type="button"
                  >
                    {interactionBusy
                      ? betaLabels.interactionOpening
                      : joinUrl && joinCodeVisible
                        ? betaLabels.hideInteraction
                        : betaLabels.openInteraction}
                  </button>
                ) : null}
                {replayButton}
                {showSegmentsConclude ? (
                  <button
                    className="primary-action"
                    disabled={interactionBusy}
                    onClick={() => void conclude()}
                    type="button"
                  >
                    {interactionBusy ? "Concluding…" : "Conclude"}
                  </button>
                ) : null}
                {showSegmentsReport ? (
                  <button
                    className="secondary-action"
                    disabled={
                      interactionBusy || detail.playback.mode === "replay"
                    }
                    type="button"
                    onClick={() => void conclude()}
                  >
                    Conclude
                  </button>
                ) : null}
                {interactionError ? (
                  <span role="status">{interactionError}</span>
                ) : null}
                {!segmentsProtocol &&
                (detail.status === "debate_finished" ||
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
            )}
            api={api}
            betaLabels={betaLabels}
            joinUrl={joinUrl}
            joinCodeVisible={
              joinCodeVisible &&
              !playbackComplete &&
              detail.playback.mode !== "replay"
            }
            onInteractionOpened={() => void readInteraction()}
            debateId={debateId}
            detail={detail}
            currentAudioDebateId={currentAudioDebateId}
            labels={stageLabels}
            onAuthorityChange={updatePlaybackAuthority}
            onDetailChange={setDetail}
            onCurrentAudioDebateIdChange={setCurrentAudioDebateId}
            outputLanguage={locale === "zh" ? "zh" : "en"}
            actionInFlight={finishBusy}
            refreshSnapshot={refreshSnapshot}
          />
          {showSegmentsReport && reportOpen ? (
            <dialog
              ref={reportDialogRef}
              className={styles.reportDialog}
              aria-label="Report"
              onClose={() => setReportOpen(false)}
            >
              <form method="dialog" className={styles.reportActions}>
                <button
                  className={`secondary-action ${styles.reportClose}`}
                  aria-label={locale === "zh" ? "关闭" : "Close"}
                  type="submit"
                  autoFocus
                >
                  <IconClose size={18} />
                </button>
              </form>
              <AgentScores
                participants={detail.participants}
                turns={detail.public_turns}
              />
              <ReportPanel canRegenerate debateId={debateId} api={api} />
            </dialog>
          ) : null}
        </>
      )}
    </RouteGuard>
  );
}
