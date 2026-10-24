"use client";

import { ASSESSMENT_COMPLETED_EVENT } from "../lib/assessment-events";
import { recordClientMetric } from "../lib/client-metrics";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { flushSync } from "react-dom";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { ChatAttachments } from "./chats/chat-attachments";
import { DismissibleAlert } from "./dismissible-alert";
import {
  CHAT_BUSY_CODE,
  ChatRequestPendingError,
  isRefusedSend,
  PlatformApiError,
  SEND_REFUSED_BUSY_CODES,
  type PlatformApi,
  type ChatAgent,
  type ChatSession,
  type AgentChatSession,
  type KnowledgeGenerationChatProgress,
  type MemoryEntryResult,
  type MemoryEntrySource,
  type ConversationSession,
  type MayaTeamDirectoryDto,
  type TeamChatSession,
  type TeamChatTurn,
  type TeamRouting,
  type TeamMemberResult,
  type TeamSummaryDto,
} from "../lib/api";
import { cachedCall, requestCacheIdentity } from "../lib/request-cache";
import {
  nextPollDelay,
  notePollError,
  serverUnderPressure,
} from "../lib/poll-pacing";
import {
  abandonChatRequest,
  adoptPendingChatRequest,
  adoptUncertainChatRequest,
  beginChatRequest,
  clearSettledChatSession,
  createChatRequestAttempt,
  getChatRequest,
  getSettledChatSession,
  isChatRequestAttemptCurrent,
  isChatRequestScopeActive,
  markChatRequestUncertain,
  observeChatRequestOnTurn,
  retryChatRequestAtRevision,
  setChatRequestScope,
  settleChatRequest,
  subscribeChatRequest,
} from "../lib/chat-request-store";
import {
  applyMentionInsert,
  collapseMentionOnBackspace,
  insertedMentionAt,
  placeMentionCaret,
  type InsertedMention,
} from "../lib/mention-insert";
import { mentionedMembers } from "../lib/mention-parse";
import {
  ChatTargetPicker,
  type ChatTargetTeam,
} from "./chats/chat-target-picker";
import { useLocale, useT } from "./locale";
import { localizeError } from "../lib/i18n";
import { uiGuideText } from "../lib/ui-guide-copy";
import { IconClose, IconPin } from "./quiet-icons";
import { ReportMarkdown } from "./report/report-markdown";
import { useSession } from "./session-provider";
import { PageAction } from "./page-action";
import { ErrorNotice, LoadingCard, Notice, PageIntro } from "./ui";
import { WorkspaceAction } from "./workspace-actions";
import styles from "./agent-chat.module.css";

type MemoryRoute = {
  actionId: string;
  actorId: string;
  courseId: string;
  source: MemoryEntrySource;
};

const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const memoryRouteKeys = [
  "memory_action_id",
  "memory_actor_id",
  "memory_course_id",
  "memory_source_kind",
  "memory_source_id",
] as const;

/**
 * A refused send (busy server, or the previous message still running) keeps
 * the text in the box and asks the student, at the Send button, to send it
 * again; nothing resends it on its own.
 */
function isScoringRefusal(error: unknown): boolean {
  return (
    isRefusedSend(error) &&
    (error as PlatformApiError).code === CHAT_BUSY_CODE &&
    (error as PlatformApiError).details?.reason === "assessment_scoring"
  );
}

/**
 * The Team chat has moved past this send: its turn is answered, or the test
 * is being summarized / is done. A stale send error must not stay on screen.
 */
function teamSendSettled(
  session: TeamChatSession,
  requestId?: string,
): boolean {
  if (
    session.assessment_stage === "summarizing" ||
    session.assessment_stage === "completed"
  )
    return true;
  const turn = requestId
    ? session.turns.find((item) => item.id === requestId)
    : session.turns.at(-1);
  return turn?.state === "ready";
}

function announceAssessmentCompleted(session: TeamChatSession) {
  if (session.assessment_stage !== "completed" || typeof window === "undefined")
    return;
  window.dispatchEvent(
    new CustomEvent(ASSESSMENT_COMPLETED_EVENT, { detail: session.id }),
  );
}

/** How long a busy-refused Team send keeps resending on its own. */
const TEAM_BUSY_RETRY_LIMIT_MS = 20 * 60_000;

/** Server-full refusals (nothing stored); not chat_busy (a running turn). */
function isAutoRetriedBusyRefusal(error: unknown): boolean {
  return (
    error instanceof PlatformApiError &&
    error.code !== undefined &&
    SEND_REFUSED_BUSY_CODES.has(error.code)
  );
}

function sendRefusalHint(
  error: unknown,
  scoring = false,
):
  | "chatSendBusyRetry"
  | "chatSendPreviousRunning"
  | "chatSendScoringBusy"
  | null {
  if (!isRefusedSend(error)) return null;
  const refusal = error as PlatformApiError;
  if (refusal.code !== CHAT_BUSY_CODE) return "chatSendBusyRetry";
  // The Scorer is marking a finished test: a short wait, not an error.
  return scoring || isScoringRefusal(refusal)
    ? "chatSendScoringBusy"
    : "chatSendPreviousRunning";
}

function memoryParamsOf(search: string): string {
  const params = new URLSearchParams(search);
  const kept = new URLSearchParams();
  for (const key of memoryRouteKeys) {
    const value = params.get(key);
    if (value !== null) kept.set(key, value);
  }
  return kept.toString();
}

function parseMemoryRoute(
  search: string,
):
  | { kind: "none" }
  | { kind: "invalid" }
  | { kind: "valid"; value: MemoryRoute } {
  const params = new URLSearchParams(search);
  const actionId = params.get("memory_action_id");
  if (!actionId) return { kind: "none" };
  const actorId = params.get("memory_actor_id") ?? "";
  const courseId = params.get("memory_course_id") ?? "";
  const sourceKind = params.get("memory_source_kind");
  const sourceId = params.get("memory_source_id") ?? "";
  if (
    !uuidPattern.test(actionId) ||
    !uuidPattern.test(actorId) ||
    !uuidPattern.test(courseId) ||
    !uuidPattern.test(sourceId)
  ) {
    return { kind: "invalid" };
  }
  let source: MemoryEntrySource;
  if (sourceKind === "conversation")
    source = { kind: "conversation", id: sourceId };
  else if (sourceKind === "agent")
    source = { kind: "agent", agent_id: sourceId };
  else if (sourceKind === "team") source = { kind: "team", team_id: sourceId };
  else if (sourceKind === "maya_team")
    source = { kind: "maya_team", team_id: sourceId };
  else return { kind: "invalid" };
  return { kind: "valid", value: { actionId, actorId, courseId, source } };
}

function unknownChatOutcomeError() {
  return new PlatformApiError(503, "chat_acceptance_unknown", {
    code: "chat_acceptance_unknown",
    message: "chat_acceptance_unknown",
  });
}

// Classroom origins are plain HTTP on a .local name, which is not a secure
// context, so randomUUID is missing. Request ids still have to be UUIDs.
function newRequestId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (typeof globalThis.crypto?.getRandomValues === "function") {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex
    .slice(6, 8)
    .join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

function routingForMention(
  session: TeamChatSession,
  message: string,
): TeamRouting {
  // Bare sends: every member reads; the leader replies first and the rest
  // reply by relevance (an empty reply is not a failure). @Name matches the
  // longest member name (no space needed). An @ naming no available member,
  // or typed @All, is ignored and the default rules apply.
  const all: TeamRouting = { mode: "all", participant_ids: [] };
  const named = mentionedMembers(message, session.team.members);
  return named.length
    ? { mode: "selected", participant_ids: named.map((member) => member.id) }
    : all;
}

function isAgentSession(
  session: ConversationSession,
): session is AgentChatSession {
  return session.entry_kind === undefined || session.entry_kind === "agent";
}

const ASSESSMENT_STAGE_PERCENT = {
  scoring: 40,
  summarizing: 75,
  completed: 100,
} as const;
const ASSESSMENT_STAGE_LABEL = {
  scoring: "assessmentStageScoring",
  summarizing: "assessmentStageSummarizing",
  completed: "assessmentStageCompleted",
} as const;

/** Shown under the Summarizer message while the server finishes a formal test. */
function AssessmentProgress({
  stage,
}: {
  stage: keyof typeof ASSESSMENT_STAGE_PERCENT;
}) {
  const t = useT();
  const percent = ASSESSMENT_STAGE_PERCENT[stage];
  return (
    <div className={styles.assessmentProgress} data-stage={stage}>
      <div
        className={styles.assessmentProgressTrack}
        role="progressbar"
        aria-label={t("assessmentProgress")}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <span style={{ width: `${percent}%` }} />
      </div>
      <span className={styles.assessmentProgressLabel}>
        {t(ASSESSMENT_STAGE_LABEL[stage])} · {percent}%
      </span>
    </div>
  );
}

function knowledgeGenerationView(status: KnowledgeGenerationChatProgress): {
  percent: number;
  labelKey:
    | "knowledgeGenerationQueued"
    | "knowledgeGenerationRunning"
    | "knowledgeGenerationMaterializing"
    | "knowledgeGenerationCompleted"
    | "knowledgeGenerationFailed";
} {
  if (status.state === "completed") {
    return { percent: 100, labelKey: "knowledgeGenerationCompleted" };
  }
  if (
    status.state === "failed" ||
    status.state === "blocked" ||
    status.state === "interrupted"
  ) {
    return { percent: 100, labelKey: "knowledgeGenerationFailed" };
  }
  if (status.state === "pending") {
    return { percent: 15, labelKey: "knowledgeGenerationQueued" };
  }
  if (status.accepted_item_count > 0 || status.materialized_item_count > 0) {
    const total = Math.max(
      status.accepted_item_count,
      status.materialized_item_count + status.failed_item_count,
      1,
    );
    const done = status.materialized_item_count + status.failed_item_count;
    return {
      percent: Math.min(95, 45 + Math.round((done / total) * 50)),
      labelKey: "knowledgeGenerationMaterializing",
    };
  }
  return { percent: 40, labelKey: "knowledgeGenerationRunning" };
}

/** Owner Teacher Chat bar for the Agent's latest Knowledge generation. */
function KnowledgeGenerationProgress({
  status,
}: {
  status: KnowledgeGenerationChatProgress;
}) {
  const t = useT();
  const view = knowledgeGenerationView(status);
  return (
    <div
      className={styles.assessmentProgress}
      data-stage={status.state}
      data-knowledge-generation={status.run_id}
    >
      <div
        className={styles.assessmentProgressTrack}
        role="progressbar"
        aria-label={t("knowledgeGenerationProgress")}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={view.percent}
      >
        <span style={{ width: `${view.percent}%` }} />
      </div>
      <span className={styles.assessmentProgressLabel}>
        {t(view.labelKey)} · {view.percent}%
      </span>
    </div>
  );
}

function isFormalMicroRoundText(text: string | null | undefined): boolean {
  const value = text ?? "";
  return (
    value.includes("收到，第一题是") ||
    value.includes("已记录你的回答。") ||
    value.includes("答题全部结束") ||
    value.includes("正在总结答案") ||
    value.includes("做题者放弃作答") ||
    value.includes("已放弃作答")
  );
}

function sortTeamMemberResults(
  results: TeamMemberResult[],
  members: TeamChatSession["team"]["members"],
): TeamMemberResult[] {
  // A formal micro-round is already in speaker order. Other turns keep the
  // Guide last so member Loading cards appear first.
  if (results.some((result) => isFormalMicroRoundText(result.assistant_text))) {
    return [...results].sort((left, right) => left.ordinal - right.ordinal);
  }
  const leaderIds = new Set(
    members.filter((member) => member.is_leader).map((member) => member.id),
  );
  return [...results].sort((left, right) => {
    const leftLeader = leaderIds.has(left.participant_id) ? 1 : 0;
    const rightLeader = leaderIds.has(right.participant_id) ? 1 : 0;
    if (leftLeader !== rightLeader) return leftLeader - rightLeader;
    return left.ordinal - right.ordinal;
  });
}

function normalizedMemberText(result: TeamMemberResult): string {
  // U+2060 is the server's silent-member mark. trim() does not remove it.
  return (result.assistant_text ?? "").replace(/\u2060/g, "").trim();
}

function visibleTeamMemberResults(
  results: TeamMemberResult[],
): TeamMemberResult[] {
  // Empty ready cards are non-speakers. A word-joiner or invalid empty reply
  // is the same silence: no card, and no "could not reply" banner.
  return results.filter((result) => {
    if (
      result.state === "pending" ||
      result.state === "running" ||
      result.state === "acceptance_unknown"
    ) {
      return true;
    }
    if (normalizedMemberText(result)) return true;
    return (
      result.state === "failed" &&
      result.safe_error_code !== "team_response_invalid"
    );
  });
}

function studentEndFlowTurns(turns: TeamChatTurn[]): TeamChatTurn[] {
  // Once 正在总结答案 is on screen, that progress bar is the last thing the
  // student sees. The closing answer's "已记录" line, the scorer's review,
  // and a failed summary (banner plus member card) stay off this chat.
  const completion = turns.findIndex((turn) =>
    turn.member_results.some(
      (result) => (result.assistant_text ?? "").trim() === "正在总结答案",
    ),
  );
  if (completion < 0) return turns;
  return turns.flatMap((turn, index) => {
    if (index > completion && !(turn.user_text ?? "").trim()) {
      const texts = turn.member_results.map(
        (result) => result.assistant_text ?? "",
      );
      const keep = texts.some(
        (text) =>
          text.includes("下面是追问") ||
          text.includes("Next, a follow-up question") ||
          text.startsWith("老师已更改当前回合的 Knowledge"),
      );
      if (!keep) return [];
    }
    if (index !== completion) return [turn];
    return [
      {
        ...turn,
        member_results: turn.member_results.filter(
          (result) =>
            (result.assistant_text ?? "").trim() !== "已记录你的回答。",
        ),
      },
    ];
  });
}

function isTeamSession(
  session: ConversationSession,
): session is TeamChatSession {
  return session.entry_kind === "team" || session.entry_kind === "maya_team";
}

function upsertTeamResult(
  turns: TeamChatTurn[],
  requestId: string,
  result: TeamMemberResult,
): TeamChatTurn[] {
  return turns.map((turn) =>
    turn.id !== requestId
      ? turn
      : {
          ...turn,
          member_results: [
            result,
            ...turn.member_results.filter((item) => item.id !== result.id),
          ].sort((left, right) => left.ordinal - right.ordinal),
        },
  );
}

export function AgentChat() {
  const { api, identityGeneration, user } = useSession();
  const cacheIdentity = requestCacheIdentity(user?.id, identityGeneration);
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const role = pathname.startsWith("/teacher/") ? "teacher" : "student";
  const memoryCourseId = searchParams?.get("memory_course_id") ?? null;
  const roleCourses = (user?.courses ?? []).filter(
    (membership) => membership.role === role,
  );
  const requestedCourse = roleCourses.find(
    (membership) => membership.course_id === memoryCourseId,
  );
  const courseId = requestedCourse?.course_id ?? roleCourses[0]?.course_id;
  const scopeKey =
    user && courseId
      ? `${identityGeneration}:${user.id}:${role}:${courseId}`
      : null;
  if (!scopeKey || !courseId) {
    return (
      <>
        <WorkspaceAction name="new" disabled />
        <LoadingCard />
      </>
    );
  }
  return (
    <AgentChatScope
      key={scopeKey}
      api={api}
      courseId={courseId}
      actorId={user?.id ?? ""}
      scopeKey={scopeKey}
      cacheIdentity={cacheIdentity}
      role={role}
    />
  );
}

function AgentChatScope({
  api,
  courseId,
  actorId,
  scopeKey,
  cacheIdentity,
  role,
}: {
  api: PlatformApi;
  courseId: string;
  actorId: string;
  scopeKey: string;
  /** Shared page-load cache identity (user id + session generation). */
  cacheIdentity: string | null;
  role: "teacher" | "student";
}) {
  const t = useT();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const memoryRouteSearch = searchParams?.toString() ?? "";
  const newChatRouteFromUrl = searchParams?.get("mode") === "new";
  const [newChatRouteState, setNewChatRouteState] = useState({
    search: memoryRouteSearch,
    open: newChatRouteFromUrl,
  });
  if (newChatRouteState.search !== memoryRouteSearch) {
    setNewChatRouteState({
      search: memoryRouteSearch,
      open: newChatRouteFromUrl,
    });
  }
  const newChatRoute = newChatRouteState.open;
  // Opening or closing New changes only `mode`. Parsing just the memory
  // parameters keeps that URL change from reading history again, which
  // would drop the Chat that Done has just created and selected.
  const memoryRouteParams = useMemo(
    () => memoryParamsOf(memoryRouteSearch),
    [memoryRouteSearch],
  );
  const parsedMemoryRoute = useMemo(
    () => parseMemoryRoute(memoryRouteParams),
    [memoryRouteParams],
  );
  const invalidMemoryRoute =
    parsedMemoryRoute.kind === "invalid" ||
    (parsedMemoryRoute.kind === "valid" &&
      (parsedMemoryRoute.value.actorId !== actorId ||
        parsedMemoryRoute.value.courseId !== courseId));
  const { locale } = useLocale();
  const teamFailureText = (
    code: string | null | undefined,
    fallback: "teamMemberFailure" | "teamRequestFailure",
  ) => {
    if (code === "assessment_action_required")
      return t("teamAnswerNotRecorded");
    if (code === "assessment_executor_write_required")
      return t("teamSummaryNotSaved");
    if (code === "team_response_truncated") return t("teamReplyCutOff");
    if (code === "provider_confirmation_required") {
      return t(
        role === "teacher"
          ? "teamProviderConfirmationTeacher"
          : "teamProviderConfirmationStudent",
      );
    }
    if (
      code === "authorization_revoked" ||
      code === "provider_authorization_revoked" ||
      code === "tool_not_authorized" ||
      code === "forbidden"
    ) {
      return t("errorForbidden");
    }
    return t(fallback);
  };
  const teamErrorText = (cause: unknown) => {
    if (
      cause instanceof PlatformApiError &&
      cause.code === "chat_acceptance_unknown"
    ) {
      return t("errorChatAcceptanceUnknown");
    }
    if (cause instanceof ChatRequestPendingError) return t("teamTurnPending");
    // Owner rule (2026-10-20): one unfinished attempt per Team; the server asks.
    if (
      cause instanceof PlatformApiError &&
      cause.code === "assessment_resume_choice_required"
    ) {
      return "你有一份没做完的作答，要接着上次继续，还是重新做？";
    }
    if (
      cause instanceof PlatformApiError &&
      cause.code === "assessment_resume_original_conversation"
    ) {
      return "上次没做完的作答已恢复，点「打开上次的作答」接着做。";
    }
    return teamFailureText(
      cause instanceof PlatformApiError ? cause.code : null,
      "teamRequestFailure",
    );
  };
  const readOnlyHelp =
    uiGuideText("chat.readOnly", locale) ??
    "This Agent is unavailable for new messages.";
  const [agents, setAgents] = useState<ChatAgent[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [teamSessions, setTeamSessions] = useState<TeamChatSession[]>([]);
  const [selected, setSelected] = useState<AgentChatSession | null>(null);
  const [selectedTeam, setSelectedTeam] = useState<TeamChatSession | null>(
    null,
  );
  const [versionId, setVersionId] = useState("");
  const [pick, setPick] = useState("");
  const [creating, setCreating] = useState(false);
  const [closedNoticeDismissed, setClosedNoticeDismissed] = useState<
    string | null
  >(null);
  const mounted = useRef(true);
  const [teamChoices, setTeamChoices] = useState<TeamSummaryDto[]>([]);
  const [mayaChoices, setMayaChoices] = useState<MayaTeamDirectoryDto[]>([]);
  const selectedTeamIdRef = useRef<string | null>(null);
  const [draft, setDraft] = useState(() => {
    const pending = getChatRequest(scopeKey);
    return pending &&
      (pending.status === "uncertain" ||
        (pending.status === "observing" &&
          pending.observedTurnId !== pending.requestId))
      ? pending.message
      : "";
  });
  const [pendingMessage, setPendingMessage] = useState(() => {
    const pending = getChatRequest(scopeKey);
    return pending?.promise && pending.status === "in_flight"
      ? pending.message
      : "";
  });
  const [loading, setLoading] = useState(true);
  const [renaming, setRenaming] = useState<{
    session: ChatSession | TeamChatSession;
    initial: string;
    value: string;
  } | null>(null);
  const [arranging, setArranging] = useState<string | null>(null);
  const [busy, setBusy] = useState(() => {
    const pending = getChatRequest(scopeKey);
    return pending?.promise != null || pending?.status === "observing";
  });
  const [requestState, setRequestState] = useState(() =>
    getChatRequest(scopeKey),
  );
  const [error, setError] = useState<unknown>(null);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const [historyRefreshTarget, setHistoryRefreshTarget] =
    useState<ChatSession | null>(null);
  const [teamDraft, setTeamDraft] = useState("");
  const [teamRecipientMenu, setTeamRecipientMenu] = useState(false);
  const teamRecipientMenuRef = useRef<HTMLDivElement>(null);
  const insertedMention = useRef<InsertedMention | null>(null);
  const messageRef = useRef<HTMLTextAreaElement>(null);
  const [teamBusy, setTeamBusy] = useState(false);
  const [teamError, setTeamError] = useState<unknown>(null);
  // A send whose stream dropped while its turn is still running on the
  // server: shown as "scoring…" while polling, not as a red failure.
  const [teamStreamDropped, setTeamStreamDropped] = useState(false);
  // The server scores and summarizes after the last answer, with no message
  // from the student, so the open Chat keeps checking until it is finished.
  // So does a turn still running after the student left and came back,
  // which no stream on this page is following.
  const finishingTeamId =
    selectedTeam?.assessment_stage === "preparing" ||
    selectedTeam?.assessment_stage === "scoring" ||
    selectedTeam?.assessment_stage === "summarizing" ||
    (!teamBusy && selectedTeam?.turns.at(-1)?.state === "pending")
      ? selectedTeam.id
      : null;
  useEffect(() => {
    if (!finishingTeamId || typeof api.conversationSession !== "function")
      return;
    let active = true;
    let delay = 2500;
    let attempt = 0;
    let timer = 0;
    // Backs off (2.5 s up to 15 s): a long scoring run is not polled flat out.
    // A busy server (503 / Retry-After / poll-after hint) stretches it to
    // 5-10 s or whatever the server asked (lib/poll-pacing.ts).
    const tick = () => {
      timer = window.setTimeout(
        () => {
          void api
            .conversationSession(finishingTeamId)
            .then((next) => {
              if (active && isTeamSession(next)) {
                setSelectedTeam((current) =>
                  current?.id === next.id ? next : current,
                );
                // Polling stops once the test is done, so this fires once.
                announceAssessmentCompleted(next);
                // The chat moved on (answered, summarizing, done): an error
                // from an earlier send is stale.
                if (teamSendSettled(next)) {
                  setTeamError(null);
                  setTeamStreamDropped(false);
                }
                // Scoring finished (or failed): its "try again shortly" note
                // is done too.
                if (next.assessment_stage !== "scoring")
                  setTeamError((current: unknown) =>
                    isScoringRefusal(current) ? null : current,
                  );
              }
            })
            .catch((cause: unknown) => {
              // The next tick asks again; sending still reports a lasting failure.
              notePollError(cause);
            })
            .finally(() => {
              if (!active) return;
              delay = Math.min(15000, Math.round(delay * 1.5));
              attempt += 1;
              tick();
            });
        },
        nextPollDelay(delay, attempt),
      );
    };
    tick();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [api, finishingTeamId]);
  const knowledgeGenerationActive =
    selected &&
    isAgentSession(selected) &&
    selected.knowledge_generation &&
    (selected.knowledge_generation.state === "pending" ||
      selected.knowledge_generation.state === "running")
      ? selected.id
      : null;
  useEffect(() => {
    if (!knowledgeGenerationActive) return;
    let active = true;
    const timer = window.setInterval(() => {
      void api
        .conversation(knowledgeGenerationActive)
        .then((next) => {
          if (active && isAgentSession(next)) {
            setSelected((current) =>
              current?.id === next.id ? next : current,
            );
          }
        })
        .catch(() => {
          // The next tick asks again; generation status is also on refresh.
        });
    }, 2500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [api, knowledgeGenerationActive]);
  const [teamLastEventId, setTeamLastEventId] = useState(0);
  const [memoryRetryEntry, setMemoryRetryEntry] =
    useState<MemoryEntryResult | null>(null);
  const [memoryRetryBusy, setMemoryRetryBusy] = useState(false);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const teamSendSequence = useRef(0);
  const teamPendingRequest = useRef<{
    conversationId: string;
    body: {
      request_id: string;
      expected_revision: number;
      message: string;
      routing: TeamRouting;
    };
  } | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const sendSequence = useRef(0);
  const uiRevision = useRef(0);
  const historyOpenSequence = useRef(0);
  const idleHistoryRefreshSequence = useRef(0);
  const memoryActionHandled = useRef<string | null>(null);
  const skipHistoryReadOnce = useRef(false);
  const memoryDispatch = useRef<
    (entry: MemoryEntryResult, retry?: boolean) => Promise<void>
  >(async () => undefined);
  const requestToken = requestState
    ? `${requestState.attemptId}:${requestState.requestId}:${requestState.status}`
    : null;
  const idleHistoryContext = useRef({
    scopeKey,
    selectedTeamId: selectedTeam?.id ?? null,
    selectedTeamRevision: selectedTeam?.revision ?? null,
    selectedTeamReadOnly: selectedTeam?.read_only ?? null,
    newChatRoute,
    busy,
    teamBusy,
    teamSequence: 0,
    teamPendingToken: null as string | null,
    requestToken,
    loaded: loadedScope === scopeKey,
  });
  useLayoutEffect(() => {
    const teamPendingToken =
      teamPendingRequest.current?.body.request_id ?? null;
    idleHistoryContext.current = {
      scopeKey,
      selectedTeamId: selectedTeam?.id ?? null,
      selectedTeamRevision: selectedTeam?.revision ?? null,
      selectedTeamReadOnly: selectedTeam?.read_only ?? null,
      newChatRoute,
      busy,
      teamBusy,
      teamSequence: teamSendSequence.current,
      teamPendingToken,
      requestToken,
      loaded: loadedScope === scopeKey,
    };
  }, [
    busy,
    loadedScope,
    newChatRoute,
    requestToken,
    scopeKey,
    selectedTeam?.id,
    selectedTeam?.read_only,
    selectedTeam?.revision,
    teamBusy,
  ]);

  useLayoutEffect(() => {
    selectedTeamIdRef.current = selectedTeam?.id ?? null;
  }, [selectedTeam?.id]);

  const syncNewChatUrl = useCallback(
    (open: boolean) => {
      if (typeof window === "undefined") return;
      const params = new URLSearchParams(window.location.search);
      if (open) params.set("mode", "new");
      else if (params.get("mode") === "new") params.delete("mode");
      const query = params.toString();
      router.push(`${pathname}${query ? `?${query}` : ""}`, { scroll: false });
    },
    [pathname, router],
  );

  const openNewEntry = useCallback(() => {
    setPick("");
    setNewChatRouteState({ search: memoryRouteSearch, open: true });
    syncNewChatUrl(true);
  }, [memoryRouteSearch, syncNewChatUrl]);

  const closeNewEntry = useCallback(
    (skipHistoryRead = false) => {
      if (skipHistoryRead) skipHistoryReadOnce.current = true;
      setNewChatRouteState({ search: memoryRouteSearch, open: false });
      syncNewChatUrl(false);
    },
    [memoryRouteSearch, syncNewChatUrl],
  );

  useEffect(() => {
    if (!teamRecipientMenu) return;
    const closeUnlessInside = (event: PointerEvent) => {
      const target = event.target;
      if (
        target instanceof Node &&
        teamRecipientMenuRef.current?.contains(target)
      ) {
        return;
      }
      setTeamRecipientMenu(false);
    };
    const close = () => setTeamRecipientMenu(false);
    document.addEventListener("pointerdown", closeUnlessInside);
    window.addEventListener("blur", close);
    return () => {
      document.removeEventListener("pointerdown", closeUnlessInside);
      window.removeEventListener("blur", close);
    };
  }, [teamRecipientMenu]);

  const remember = useCallback(
    (value: ChatSession, activateIfEmpty = false) => {
      if (!isChatRequestScopeActive(scopeKey)) return;
      setSelected((current) => {
        if (!current) return activateIfEmpty ? value : current;
        if (current && current.id !== value.id) return current;
        return current && current.revision > value.revision ? current : value;
      });
      setSessions((current) => {
        const previous = current.find((item) => item.id === value.id);
        const next =
          previous && previous.revision > value.revision ? previous : value;
        return [next, ...current.filter((item) => item.id !== value.id)];
      });
    },
    [scopeKey],
  );

  const rememberTeam = useCallback(
    (value: TeamChatSession, activateIfEmpty = false) => {
      if (!isChatRequestScopeActive(scopeKey)) return;
      setSelectedTeam((current) => {
        if (!current) return activateIfEmpty ? value : current;
        if (current.id !== value.id) return current;
        return current.revision > value.revision ? current : value;
      });
      setTeamSessions((current) => {
        const previous = current.find((item) => item.id === value.id);
        const next =
          previous && previous.revision > value.revision ? previous : value;
        return [next, ...current.filter((item) => item.id !== value.id)];
      });
    },
    [scopeKey],
  );

  useEffect(() => {
    let active = true;
    setChatRequestScope(scopeKey);
    const preserveSelection = !newChatRoute && skipHistoryReadOnce.current;
    const skipHistoryRead = newChatRoute || skipHistoryReadOnce.current;
    skipHistoryReadOnce.current = false;
    const historyRequest = skipHistoryRead
      ? Promise.resolve([])
      : typeof api.conversationSessions === "function"
        ? api.conversationSessions()
        : api.conversations();
    // The catalog is a shared, briefly cached read; history is always read
    // fresh because pending sends are reconciled against it.
    void Promise.all([
      cachedCall(api, cacheIdentity, "chatAgents", [courseId], () =>
        api.chatAgents(courseId),
      ),
      historyRequest,
    ])
      .then(([catalog, allHistory]) => {
        if (!active || !isChatRequestScopeActive(scopeKey)) return;
        setAgents(catalog);
        if (preserveSelection) return;
        if (skipHistoryRead) {
          // Preserve the catalog already loaded in this mounted workspace,
          // while keeping the current conversation unselected. A direct
          // mode=new URL starts with empty lists and never reads old history.
          setSelected(null);
          setSelectedTeam(null);
          setVersionId("");
          return;
        }
        const history = allHistory.filter(isAgentSession);
        setTeamSessions(allHistory.filter(isTeamSession));
        const settled = getSettledChatSession(scopeKey);
        let nextHistory = history;
        if (settled) {
          nextHistory = [
            settled,
            ...history.filter((item) => item.id !== settled.id),
          ];
          clearSettledChatSession(scopeKey);
        }
        setSessions(nextHistory);
        if (parsedMemoryRoute.kind === "valid" && !invalidMemoryRoute) {
          // Memory opens a new chat. Do not show an older window while it is created.
          setSelected(null);
          setSelectedTeam(null);
          setVersionId("");
          return;
        }
        let pending = getChatRequest(scopeKey);
        const storedRequest = pending;
        let reconciledCurrentTerminal = false;
        if (storedRequest?.sessionId) {
          const savedSession = nextHistory.find(
            (session) => session.id === storedRequest.sessionId,
          );
          const savedTurn = savedSession?.turns.find(
            (turn) => turn.id === storedRequest.requestId,
          );
          if (savedTurn?.state === "ready" && savedSession) {
            settleChatRequest(
              storedRequest.requestId,
              savedSession,
              scopeKey,
              storedRequest.attemptId,
            );
            clearSettledChatSession(scopeKey);
            pending = null;
            reconciledCurrentTerminal = true;
            setDraft("");
            setPendingMessage("");
            setError(null);
          } else if (savedTurn?.state === "failed" && savedSession) {
            const code = savedTurn.safe_error_code ?? "chat_failed";
            setError(new PlatformApiError(503, code, { code, message: code }));
            settleChatRequest(
              storedRequest.requestId,
              savedSession,
              scopeKey,
              storedRequest.attemptId,
            );
            clearSettledChatSession(scopeKey);
            pending = null;
            reconciledCurrentTerminal = true;
            setDraft("");
            setPendingMessage("");
          } else if (
            savedTurn?.state === "acceptance_unknown" &&
            savedSession
          ) {
            markChatRequestUncertain(
              storedRequest.requestId,
              scopeKey,
              storedRequest.attemptId,
            );
            pending = getChatRequest(scopeKey);
            setError(unknownChatOutcomeError());
            setDraft((current) => current || pending?.message || "");
          } else if (savedTurn?.state === "pending") {
            observeChatRequestOnTurn(
              storedRequest.requestId,
              storedRequest.requestId,
              scopeKey,
              storedRequest.attemptId,
            );
            pending = getChatRequest(scopeKey);
          }
        }
        if (!pending) {
          const pendingSession = nextHistory.find((session) =>
            session.turns.some((turn) => turn.state === "pending"),
          );
          const pendingTurn = pendingSession?.turns.find(
            (turn) => turn.state === "pending",
          );
          if (pendingSession && pendingTurn) {
            pending = adoptPendingChatRequest(
              {
                sessionId: pendingSession.id,
                versionId: pendingSession.agent.version_id,
                message: pendingTurn.user_text,
                requestId: pendingTurn.id,
                revision: pendingSession.revision,
              },
              scopeKey,
            );
          }
        }
        if (!pending && !reconciledCurrentTerminal) {
          const unknownSession = nextHistory
            .filter(
              (session) => session.turns.at(-1)?.state === "acceptance_unknown",
            )
            .sort((left, right) =>
              right.created_at.localeCompare(left.created_at),
            )[0];
          const unknownTurn = unknownSession?.turns.at(-1);
          if (unknownSession && unknownTurn) {
            pending = adoptUncertainChatRequest(
              {
                sessionId: unknownSession.id,
                versionId: unknownSession.agent.version_id,
                message: unknownTurn.user_text,
                requestId: unknownTurn.id,
                revision: Math.max(0, unknownSession.revision - 1),
              },
              scopeKey,
            );
            setError(unknownChatOutcomeError());
          }
        }
        if (pending) {
          const match =
            nextHistory.find((session) => session.id === pending.sessionId) ??
            null;
          setSelected(match);
          setVersionId(pending.versionId);
          setRequestState(pending);
          setPendingMessage(
            pending.promise && pending.status === "in_flight"
              ? pending.message
              : "",
          );
          setBusy(pending.promise != null || pending.status === "observing");
          if (
            pending.status === "uncertain" ||
            (pending.status === "observing" &&
              pending.observedTurnId !== pending.requestId)
          ) {
            setDraft((current) => current || pending.message);
          }
          return;
        }
        const recent = nextHistory.find((session) => session.turns.length > 0);
        setSelected(recent ?? null);
        setSelectedTeam(null);
        setVersionId(recent?.agent.version_id ?? "");
      })
      .catch((cause) => {
        if (active && isChatRequestScopeActive(scopeKey)) setError(cause);
      })
      .finally(() => {
        if (active && isChatRequestScopeActive(scopeKey)) {
          setLoadedScope(scopeKey);
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [
    api,
    cacheIdentity,
    courseId,
    invalidMemoryRoute,
    newChatRoute,
    parsedMemoryRoute,
    scopeKey,
  ]);

  const loadTeamChoices = useCallback(async () => {
    const [teams, mayaTeams] = await Promise.all([
      typeof api.teams === "function"
        ? cachedCall(api, cacheIdentity, "teams", [courseId, undefined], () =>
            api.teams(courseId),
          ).catch(() => [])
        : Promise.resolve([]),
      typeof api.mayaTeams === "function"
        ? cachedCall(api, cacheIdentity, "mayaTeams", [courseId], () =>
            api.mayaTeams(courseId),
          ).catch(() => [])
        : Promise.resolve([]),
    ]);
    if (!isChatRequestScopeActive(scopeKey)) return;
    setTeamChoices(teams);
    setMayaChoices(mayaTeams);
  }, [api, cacheIdentity, courseId, scopeKey]);

  // Read beside the catalog and history, not after them: one round trip.
  useEffect(() => {
    if (!scopeKey) return;
    const timer = window.setTimeout(() => void loadTeamChoices(), 0);
    return () => window.clearTimeout(timer);
  }, [loadTeamChoices, newChatRoute, scopeKey]);

  useEffect(() => {
    if (!scopeKey || loadedScope !== scopeKey) return;
    return subscribeChatRequest(() => {
      if (!isChatRequestScopeActive(scopeKey)) return;
      const pending = getChatRequest(scopeKey);
      const settled = getSettledChatSession(scopeKey);
      setRequestState(pending);
      if (settled) {
        remember(settled, true);
        clearSettledChatSession(scopeKey);
        setRequestState(null);
        setPendingMessage("");
        setBusy(false);
        return;
      }
      if (pending) {
        const observing = pending.status === "observing";
        const inFlight = pending.promise != null;
        setBusy(inFlight || observing);
        setPendingMessage(
          inFlight && pending.status === "in_flight" ? pending.message : "",
        );
        if (
          pending.status === "uncertain" ||
          (observing && pending.observedTurnId !== pending.requestId)
        ) {
          setDraft((current) => current || pending.message);
        }
        setVersionId(pending.versionId);
        if (pending.sessionId) {
          setSelected((current) =>
            current?.id === pending.sessionId
              ? current
              : (sessions.find((item) => item.id === pending.sessionId) ??
                current),
          );
        }
        return;
      }
      setRequestState(null);
      setBusy(false);
      setPendingMessage("");
    }, scopeKey);
  }, [remember, sessions, scopeKey, loadedScope]);

  useEffect(() => {
    const observed = requestState;
    if (
      !scopeKey ||
      loadedScope !== scopeKey ||
      observed?.scopeKey !== scopeKey ||
      observed.status !== "observing" ||
      !observed.sessionId
    ) {
      return;
    }
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let checking = false;
    let attempt = 0;

    const poll = async () => {
      if (!active || checking) return;
      checking = true;
      try {
        const session = await api.conversation(observed.sessionId!);
        if (
          !active ||
          !isChatRequestScopeActive(scopeKey) ||
          getChatRequest(scopeKey)?.attemptId !== observed.attemptId
        ) {
          return;
        }
        remember(session);
        const requestTurn = session.turns.find(
          (turn) => turn.id === observed.requestId,
        );
        if (requestTurn && requestTurn.state !== "pending") {
          if (requestTurn.state === "acceptance_unknown") {
            setError(unknownChatOutcomeError());
          } else if (requestTurn.state !== "ready") {
            const code = requestTurn.safe_error_code ?? "chat_failed";
            setError(new PlatformApiError(503, code, { code, message: code }));
          }
          if (requestTurn.state === "acceptance_unknown") {
            markChatRequestUncertain(
              observed.requestId,
              scopeKey,
              observed.attemptId,
            );
          } else {
            settleChatRequest(
              observed.requestId,
              session,
              scopeKey,
              observed.attemptId,
            );
          }
          return;
        }
        if (!session.turns.some((turn) => turn.state === "pending")) {
          retryChatRequestAtRevision(
            observed.requestId,
            session.revision,
            scopeKey,
            observed.attemptId,
          );
          return;
        }
      } catch (cause) {
        notePollError(cause);
        if (
          active &&
          isChatRequestScopeActive(scopeKey) &&
          getChatRequest(scopeKey)?.attemptId === observed.attemptId
        ) {
          setError(cause);
        }
      } finally {
        checking = false;
      }
      // 1.5 s, then easing off to 5 s while the reply is still pending;
      // 5-10 s (or the server's wait) while the server is busy.
      if (active) {
        const base = Math.min(5000, Math.round(1500 * 1.5 ** attempt));
        timer = setTimeout(() => void poll(), nextPollDelay(base, attempt));
        attempt += 1;
      }
    };

    void poll();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [api, remember, requestState, scopeKey, loadedScope]);

  useEffect(() => {
    const selectedId = selectedTeam?.id;
    const contextAtStart = idleHistoryContext.current;
    if (
      !selectedId ||
      !scopeKey ||
      loadedScope !== scopeKey ||
      newChatRoute ||
      busy ||
      requestToken !== null ||
      teamBusy ||
      contextAtStart.teamPendingToken !== null ||
      typeof api.conversationSession !== "function"
    ) {
      return;
    }

    const sequence = ++idleHistoryRefreshSequence.current;
    const teamSequenceAtStart = contextAtStart.teamSequence;
    let active = true;
    let inFlight = false;
    let lastRefreshAt = 0;
    let busyRefreshes = 0;
    const ownsRefresh = () => {
      const current = idleHistoryContext.current;
      return (
        active &&
        idleHistoryRefreshSequence.current === sequence &&
        current.scopeKey === scopeKey &&
        current.selectedTeamId === selectedId &&
        !current.newChatRoute &&
        !current.busy &&
        !current.teamBusy &&
        current.teamSequence === teamSequenceAtStart &&
        current.teamPendingToken === null &&
        current.requestToken === null &&
        current.loaded &&
        contextAtStart.scopeKey === scopeKey &&
        isChatRequestScopeActive(scopeKey)
      );
    };
    const refreshSelectedConversation = async () => {
      if (
        inFlight ||
        !ownsRefresh() ||
        document.visibilityState !== "visible"
      ) {
        return;
      }
      // Busy server: the 5 s idle refresh waits out its 5-10 s pace.
      if (
        serverUnderPressure() &&
        Date.now() - lastRefreshAt < nextPollDelay(5000, busyRefreshes)
      ) {
        return;
      }
      busyRefreshes = serverUnderPressure() ? busyRefreshes + 1 : 0;
      lastRefreshAt = Date.now();
      inFlight = true;
      try {
        const latest = await api.conversationSession(selectedId);
        if (
          !ownsRefresh() ||
          latest.id !== selectedId ||
          !isTeamSession(latest) ||
          (idleHistoryContext.current.selectedTeamRevision !== null &&
            latest.revision <=
              idleHistoryContext.current.selectedTeamRevision) ||
          idleHistoryContext.current.selectedTeamReadOnly !==
            contextAtStart.selectedTeamReadOnly
        ) {
          return;
        }
        rememberTeam(latest);
      } catch (cause) {
        // Idle refresh is opportunistic; opening the history remains the
        // explicit path that reports a failed conversation read.
        notePollError(cause);
      } finally {
        inFlight = false;
      }
    };
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") {
        void refreshSelectedConversation();
      }
    };
    const timer = window.setInterval(
      () => void refreshSelectedConversation(),
      5000,
    );
    document.addEventListener("visibilitychange", refreshWhenVisible);
    window.addEventListener("focus", refreshWhenVisible);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      window.removeEventListener("focus", refreshWhenVisible);
      if (idleHistoryRefreshSequence.current === sequence) {
        idleHistoryRefreshSequence.current += 1;
      }
    };
  }, [
    api,
    busy,
    loadedScope,
    newChatRoute,
    rememberTeam,
    requestToken,
    scopeKey,
    selectedTeam?.id,
    selectedTeam?.read_only,
    selectedTeam?.revision,
    teamBusy,
  ]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // Opening or updating a Chat shows its newest message, Team Chats included.
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [
    selected?.id,
    selected?.turns.length,
    selectedTeam?.id,
    selectedTeam?.turns.length,
    selectedTeam?.assessment_stage,
    busy,
    pendingMessage,
  ]);

  function start(nextVersionId = versionId) {
    if (busy) return;
    createChatRequestAttempt(scopeKey);
    uiRevision.current += 1;
    sendSequence.current += 1;
    setError(null);
    setHistoryRefreshTarget(null);
    setSelected(null);
    setSelectedTeam(null);
    setTeamDraft("");
    setTeamError(null);
    setTeamRecipientMenu(false);
    setDraft("");
    abandonChatRequest(undefined, scopeKey);
    if (nextVersionId) setVersionId(nextVersionId);
  }

  // Done on the New page creates the Chat at once. A new Team chat stays
  // empty until the student sends the first message.
  async function createPicked() {
    const separator = pick.indexOf(":");
    const kind = pick.slice(0, separator);
    const id = pick.slice(separator + 1);
    if (!id || creating || busy || teamBusy) return;
    start("");
    setVersionId("");
    teamSendSequence.current += 1;
    setTeamLastEventId(0);
    // A later New, history click or account switch takes a newer attempt, so
    // a late create response can never replace what is on screen by then.
    const scopeAtCreate = scopeKey;
    const attemptId = createChatRequestAttempt(scopeAtCreate);
    if (attemptId === null) return;
    // Leaving Chatform must not let a late create navigate back to it.
    const stillCurrent = () =>
      mounted.current &&
      isChatRequestScopeActive(scopeAtCreate) &&
      isChatRequestAttemptCurrent(attemptId, scopeAtCreate);
    setCreating(true);
    try {
      if (kind === "agent") {
        const session = await api.createConversation(id);
        if (!stillCurrent()) return;
        remember(session, true);
        setSelected(session);
        setVersionId(session.agent.version_id);
      } else {
        const team_version_id =
          teamChoices.find((team) => team.id === id)?.current_version_id ??
          mayaChoices.find((team) => team.id === id)?.team_version_id;
        const session = await api.createTeamConversation(
          team_version_id
            ? { kind: "team", team_id: id, team_version_id }
            : { kind: "team", team_id: id },
        );
        if (!stillCurrent()) return;
        rememberTeam(session, true);
        setSelectedTeam(session);
        selectedTeamIdRef.current = session.id;
      }
      closeNewEntry(true);
    } catch (cause) {
      if (stillCurrent()) setError(cause);
    } finally {
      if (mounted.current && isChatRequestScopeActive(scopeAtCreate))
        setCreating(false);
    }
  }

  async function openHistory(session: ChatSession) {
    if (!scopeKey || loadedScope !== scopeKey || busy) return;
    const openAttempt = createChatRequestAttempt(scopeKey);
    if (openAttempt === null) return;
    const openSequence = ++historyOpenSequence.current;
    const openUiRevision = ++uiRevision.current;
    const openSendSequence = ++sendSequence.current;
    const requestAtOpen = getChatRequest(scopeKey);
    const attemptAtOpen = requestAtOpen?.attemptId ?? null;
    const stillCurrent = () =>
      historyOpenSequence.current === openSequence &&
      uiRevision.current === openUiRevision &&
      sendSequence.current === openSendSequence &&
      isChatRequestScopeActive(scopeKey) &&
      isChatRequestAttemptCurrent(openAttempt, scopeKey) &&
      (getChatRequest(scopeKey)?.attemptId ?? null) === attemptAtOpen;

    setHistoryRefreshTarget(session);
    setBusy(true);
    try {
      const refreshed = await api.conversation(session.id);
      if (!stillCurrent()) return;
      remember(refreshed);
      setSelected(refreshed);
      setSelectedTeam(null);
      setVersionId(refreshed.agent.version_id);
      setDraft("");
      setError(null);
      setHistoryRefreshTarget(null);
      if (newChatRoute) closeNewEntry(true);

      const currentRequest = getChatRequest(scopeKey);
      if (currentRequest?.sessionId === refreshed.id) {
        const requestTurn = refreshed.turns.find(
          (turn) => turn.id === currentRequest.requestId,
        );
        if (requestTurn?.state === "ready") {
          settleChatRequest(
            currentRequest.requestId,
            refreshed,
            scopeKey,
            currentRequest.attemptId,
          );
        } else if (requestTurn?.state === "acceptance_unknown") {
          setDraft(currentRequest.message);
          setError(unknownChatOutcomeError());
          markChatRequestUncertain(
            currentRequest.requestId,
            scopeKey,
            currentRequest.attemptId,
          );
        } else if (requestTurn?.state === "failed") {
          const code = requestTurn.safe_error_code ?? "chat_failed";
          setError(new PlatformApiError(503, code, { code, message: code }));
          settleChatRequest(
            currentRequest.requestId,
            refreshed,
            scopeKey,
            currentRequest.attemptId,
          );
        } else if (requestTurn?.state === "pending") {
          observeChatRequestOnTurn(
            currentRequest.requestId,
            currentRequest.requestId,
            scopeKey,
            currentRequest.attemptId,
          );
        } else {
          const otherPending = refreshed.turns.find(
            (turn) => turn.state === "pending",
          );
          if (otherPending) {
            observeChatRequestOnTurn(
              currentRequest.requestId,
              otherPending.id,
              scopeKey,
              currentRequest.attemptId,
            );
          } else {
            retryChatRequestAtRevision(
              currentRequest.requestId,
              refreshed.revision,
              scopeKey,
              currentRequest.attemptId,
            );
          }
        }
        return;
      }

      if (currentRequest) {
        abandonChatRequest(
          currentRequest.requestId,
          scopeKey,
          currentRequest.attemptId,
        );
      }
      const pendingTurn = refreshed.turns.find(
        (turn) => turn.state === "pending",
      );
      if (pendingTurn) {
        const observed = adoptPendingChatRequest(
          {
            sessionId: refreshed.id,
            versionId: refreshed.agent.version_id,
            message: pendingTurn.user_text,
            requestId: pendingTurn.id,
            revision: refreshed.revision,
          },
          scopeKey,
        );
        if (observed) {
          setRequestState(observed);
          setBusy(true);
          return;
        }
      }
      const lastTurn = refreshed.turns.at(-1);
      if (lastTurn?.state === "acceptance_unknown") {
        const unknown = adoptUncertainChatRequest(
          {
            sessionId: refreshed.id,
            versionId: refreshed.agent.version_id,
            message: lastTurn.user_text,
            requestId: lastTurn.id,
            revision: Math.max(0, refreshed.revision - 1),
          },
          scopeKey,
        );
        if (unknown) {
          setRequestState(unknown);
          setDraft(unknown.message);
          setError(unknownChatOutcomeError());
          setBusy(false);
          setPendingMessage("");
          return;
        }
      }
      setRequestState(null);
      setBusy(false);
    } catch {
      if (!stillCurrent()) return;
      setError(
        new PlatformApiError(503, "chat_history_refresh_failed", {
          code: "chat_history_refresh_failed",
          message: "chat_history_refresh_failed",
        }),
      );
    } finally {
      if (stillCurrent()) {
        const pending = getChatRequest(scopeKey);
        setBusy(pending?.promise != null || pending?.status === "observing");
      }
    }
  }

  async function openTeamHistory(session: TeamChatSession) {
    if (!scopeKey || loadedScope !== scopeKey || busy || teamBusy) return;
    const sequence = ++teamSendSequence.current;
    const scopeAtOpen = scopeKey;
    setTeamBusy(true);
    setTeamStreamDropped(false);
    setTeamError(null);
    try {
      const refreshed = await api.conversationSession(session.id);
      if (
        sequence !== teamSendSequence.current ||
        !isChatRequestScopeActive(scopeAtOpen) ||
        !isTeamSession(refreshed)
      ) {
        return;
      }
      setSelected(null);
      setSelectedTeam(refreshed);
      rememberTeam(refreshed, true);
      setTeamDraft("");
      setTeamLastEventId(0);
      setTeamRecipientMenu(false);
      if (newChatRoute) closeNewEntry(true);
      const lastTurn = refreshed.turns.at(-1);
      if (lastTurn?.state === "acceptance_unknown") {
        setTeamError(unknownChatOutcomeError());
      }
    } catch (cause) {
      if (
        sequence === teamSendSequence.current &&
        isChatRequestScopeActive(scopeAtOpen)
      ) {
        setTeamError(cause);
      }
    } finally {
      if (
        sequence === teamSendSequence.current &&
        isChatRequestScopeActive(scopeAtOpen)
      ) {
        setTeamBusy(false);
      }
    }
  }

  async function resumePausedTeam() {
    const turn = selectedTeam?.turns.at(-1);
    if (
      !selectedTeam ||
      !turn ||
      turn.state !== "paused" ||
      teamBusy ||
      !isChatRequestScopeActive(scopeKey)
    )
      return;
    const sequence = ++teamSendSequence.current;
    setTeamBusy(true);
    setTeamStreamDropped(false);
    setTeamError(null);
    try {
      const refreshed = await api.controlConversationTurn(
        selectedTeam.id,
        turn.id,
        "resume",
      );
      if (
        sequence !== teamSendSequence.current ||
        !isChatRequestScopeActive(scopeKey) ||
        !isTeamSession(refreshed)
      ) {
        return;
      }
      rememberTeam(refreshed);
      setSelectedTeam(refreshed);
    } catch (cause) {
      if (
        sequence === teamSendSequence.current &&
        isChatRequestScopeActive(scopeKey)
      ) {
        setTeamError(cause);
      }
    } finally {
      if (
        sequence === teamSendSequence.current &&
        isChatRequestScopeActive(scopeKey)
      ) {
        setTeamBusy(false);
      }
    }
  }

  async function checkTeamStatus() {
    if (!selectedTeam || teamBusy || !isChatRequestScopeActive(scopeKey))
      return;
    const sequence = ++teamSendSequence.current;
    const conversationId = selectedTeam.id;
    setTeamBusy(true);
    setTeamStreamDropped(false);
    try {
      const refreshed = await api.conversationSession(conversationId);
      if (
        sequence !== teamSendSequence.current ||
        !isChatRequestScopeActive(scopeKey) ||
        !isTeamSession(refreshed) ||
        selectedTeam.id !== conversationId
      ) {
        return;
      }
      rememberTeam(refreshed);
      setSelectedTeam(refreshed);
      const lastTurn = refreshed.turns.at(-1);
      const pending = teamPendingRequest.current;
      if (
        lastTurn?.state === "pending" &&
        pending?.conversationId === conversationId
      ) {
        const resumed = await api.streamTeamConversation(
          conversationId,
          pending.body,
          {
            afterEventId: teamLastEventId,
            onEvent: (event) => {
              const eventSequence = Number(event.id);
              if (Number.isInteger(eventSequence) && eventSequence > 0) {
                setTeamLastEventId(eventSequence);
              }
            },
          },
        );
        if (
          sequence === teamSendSequence.current &&
          isChatRequestScopeActive(scopeKey) &&
          isTeamSession(resumed)
        ) {
          rememberTeam(resumed);
          setSelectedTeam(resumed);
          const latest = resumed.turns.at(-1);
          if (latest?.state === "pending") {
            setTeamError(new ChatRequestPendingError());
          } else {
            teamPendingRequest.current = null;
            setTeamError(
              latest?.state === "acceptance_unknown"
                ? unknownChatOutcomeError()
                : null,
            );
          }
        }
        return;
      }
      if (lastTurn && lastTurn.state !== "pending") {
        teamPendingRequest.current = null;
      }
      setTeamError(
        lastTurn?.state === "acceptance_unknown"
          ? unknownChatOutcomeError()
          : null,
      );
    } catch (cause) {
      if (
        sequence === teamSendSequence.current &&
        isChatRequestScopeActive(scopeKey) &&
        selectedTeam.id === conversationId
      ) {
        setTeamError(cause);
      }
    } finally {
      if (sequence === teamSendSequence.current) setTeamBusy(false);
    }
  }

  async function sendTeam(
    event?: FormEvent,
    preset?: {
      session: TeamChatSession;
      requestId: string;
      expectedRevision: number;
      message: string;
    },
  ) {
    event?.preventDefault();
    const session = preset?.session ?? selectedTeam;
    const message = preset?.message ?? teamDraft.trim();
    // Bug (2026-10-13): while the server picked the follow-ups the student
    // could already type, and the answer landed before the follow-up showed.
    const serverWorking =
      !preset &&
      (session?.assessment_stage === "preparing" ||
        session?.assessment_stage === "scoring" ||
        (session?.assessment_stage === "summarizing" &&
          session.can_send === false));
    if (
      !session ||
      !message ||
      teamBusy ||
      serverWorking ||
      session.read_only ||
      !session.can_send ||
      !isChatRequestScopeActive(scopeKey)
    ) {
      return;
    }
    const routing: TeamRouting = routingForMention(session, message);
    if (routing.mode === "selected" && !routing.participant_ids.length) {
      setTeamError(
        new PlatformApiError(400, "team_no_recipient", {
          code: "team_no_recipient",
          message: "team_no_recipient",
        }),
      );
      return;
    }
    const sequence = ++teamSendSequence.current;
    const requestId = preset?.requestId ?? newRequestId();
    const scopeAtSend = scopeKey;
    const sentSessionId = session.id;
    const request = {
      request_id: requestId,
      expected_revision: preset?.expectedRevision ?? session.revision,
      message,
      routing,
    };
    teamPendingRequest.current = {
      conversationId: session.id,
      body: request,
    };
    // Like a single-Agent Chat, the message shows at once with its loading
    // state; streamed member results fill this same turn by its request id.
    setSelectedTeam((current) =>
      current?.id === sentSessionId &&
      !current.turns.some((turn) => turn.id === requestId)
        ? {
            ...current,
            turns: [
              ...current.turns,
              {
                id: requestId,
                user_text: message,
                state: "pending",
                routing,
                member_results: [],
              } as unknown as TeamChatTurn,
            ],
          }
        : current,
    );
    setTeamDraft("");
    setTeamBusy(true);
    setTeamStreamDropped(false);
    setTeamError(null);
    setTeamLastEventId(0);
    const sendStillOwned = () =>
      sequence === teamSendSequence.current &&
      isChatRequestScopeActive(scopeAtSend) &&
      (Boolean(preset) || selectedTeamIdRef.current === sentSessionId);
    try {
      const streamHooks: NonNullable<
        Parameters<PlatformApi["streamTeamConversation"]>[2]
      > = {
        onEvent: (event) => {
          if (
            sequence !== teamSendSequence.current ||
            !isChatRequestScopeActive(scopeAtSend) ||
            (!preset && selectedTeamIdRef.current !== sentSessionId)
          ) {
            return;
          }
          const eventSequence = Number(event.id);
          if (Number.isInteger(eventSequence) && eventSequence > 0) {
            setTeamLastEventId(eventSequence);
          }
          if (
            event.event === "member_result" &&
            event.request_id === requestId &&
            event.result &&
            typeof event.result === "object"
          ) {
            const resultPayload = event.result as TeamMemberResult;
            setSelectedTeam((current) =>
              current?.id === sentSessionId
                ? {
                    ...current,
                    turns: upsertTeamResult(
                      current.turns,
                      requestId,
                      resultPayload,
                    ),
                  }
                : current,
            );
          }
        },
      };
      // A busy refusal stored nothing, so the same request (id, revision) is
      // sent again on its own while the student waits, at the busy pace
      // (5-10 s, or the server's Retry-After), instead of handing the text
      // back. Load tests (2026-10-19): students left waiting on a refusal
      // gave up or hammered Send; a class must still finish under overload.
      const busyRetryUntil = Date.now() + TEAM_BUSY_RETRY_LIMIT_MS;
      let busyAttempt = 0;
      let result: TeamChatSession;
      const sendStarted = performance.now();
      for (;;) {
        try {
          result = await api.streamTeamConversation(
            session.id,
            request,
            streamHooks,
          );
          break;
        } catch (cause) {
          if (
            !isAutoRetriedBusyRefusal(cause) ||
            !sendStillOwned() ||
            Date.now() >= busyRetryUntil
          ) {
            throw cause;
          }
          notePollError(cause);
          await new Promise((resolve) =>
            window.setTimeout(resolve, nextPollDelay(5000, busyAttempt)),
          );
          busyAttempt += 1;
          if (!sendStillOwned()) throw cause;
        }
      }
      if (
        sequence !== teamSendSequence.current ||
        !isChatRequestScopeActive(scopeAtSend) ||
        !isTeamSession(result) ||
        result.id !== sentSessionId ||
        (!preset && selectedTeamIdRef.current !== sentSessionId)
      ) {
        return;
      }
      if (result.assessment_stage) {
        recordClientMetric(
          "assessment_submit",
          performance.now() - sendStarted,
        );
      }
      rememberTeam(result);
      setSelectedTeam(result);
      const savedTurn = result.turns.find((turn) => turn.id === requestId);
      if (savedTurn?.state === "pending") {
        setTeamError(new ChatRequestPendingError());
      } else {
        setTeamDraft("");
        teamPendingRequest.current = null;
        setTeamError(
          savedTurn?.state === "acceptance_unknown"
            ? unknownChatOutcomeError()
            : null,
        );
      }
    } catch (cause) {
      if (
        sequence !== teamSendSequence.current ||
        !isChatRequestScopeActive(scopeAtSend) ||
        (!preset && selectedTeamIdRef.current !== sentSessionId)
      ) {
        return;
      }
      try {
        const refreshed = await api.conversationSession(sentSessionId);
        if (
          sequence === teamSendSequence.current &&
          isChatRequestScopeActive(scopeAtSend) &&
          isTeamSession(refreshed)
        ) {
          rememberTeam(refreshed);
          setSelectedTeam(refreshed);
          announceAssessmentCompleted(refreshed);
          const turn = refreshed.turns.find((item) => item.id === requestId);
          // The stream broke but the server finished the turn (or moved on
          // to the summary): it went through, so no error and no draft.
          if (turn && teamSendSettled(refreshed, requestId)) {
            setTeamDraft("");
            teamPendingRequest.current = null;
            setTeamError(null);
            setTeamStreamDropped(false);
            return;
          }
          // Still running on the server: wait like a busy turn (polling
          // picks it up), not a red "could not complete".
          if (turn?.state === "pending") {
            setTeamDraft("");
            setTeamError(null);
            setTeamStreamDropped(true);
            return;
          }
          // Nothing was saved, or the turn failed (e.g. server busy): give
          // the message back so the student can resend without retyping.
          if (!turn || turn.state === "failed") {
            setTeamDraft((current) => current || message);
          }
          setTeamError(
            turn?.state === "acceptance_unknown"
              ? unknownChatOutcomeError()
              : turn?.safe_error_code
                ? new PlatformApiError(503, turn.safe_error_code, {
                    code: turn.safe_error_code,
                    message: turn.safe_error_code,
                  })
                : cause,
          );
        }
      } catch {
        if (sequence === teamSendSequence.current) {
          setTeamDraft(message);
          setTeamError(cause);
        }
      }
    } finally {
      if (
        sequence === teamSendSequence.current &&
        isChatRequestScopeActive(scopeAtSend)
      ) {
        setTeamBusy(false);
      }
    }
  }

  // A name and a pin only arrange the owner's history: they never change a
  // Chat's turns or revision, so they stay open while a reply is pending.
  async function arrangeChat(
    session: ChatSession | TeamChatSession,
    changes: { title?: string | null; pinned?: boolean },
  ) {
    const arrangeScope = scopeKey;
    if (!arrangeScope || arranging) return;
    setArranging(session.id);
    try {
      const updated = await api.updateConversation(session.id, changes);
      if (!isChatRequestScopeActive(arrangeScope)) return;
      const arrangement = {
        title: updated.title ?? null,
        pinned_at: updated.pinned_at ?? null,
      };
      const apply = <T extends { id: string }>(item: T): T =>
        item.id === session.id ? { ...item, ...arrangement } : item;
      setSessions((current) => current.map(apply));
      setTeamSessions((current) => current.map(apply));
      setSelected((current) => (current ? apply(current) : current));
      setSelectedTeam((current) => (current ? apply(current) : current));
    } catch (cause) {
      if (isChatRequestScopeActive(arrangeScope)) setError(cause);
    } finally {
      if (mounted.current && isChatRequestScopeActive(arrangeScope))
        setArranging(null);
    }
  }

  function commitRename() {
    const current = renaming;
    if (!current) return;
    setRenaming(null);
    const value = current.value.trim();
    // An untouched field keeps the automatic name rather than freezing it.
    if (value === current.initial) return;
    void arrangeChat(current.session, { title: value || null });
  }

  async function removeChat(session: ChatSession | TeamChatSession) {
    if (busy || teamBusy) return;
    if (!window.confirm(t("deleteChatConfirm"))) return;
    const removeUiRevision = ++uiRevision.current;
    const removeSendSequence = ++sendSequence.current;
    const removeScope = scopeKey;
    setError(null);
    try {
      await api.deleteConversation(session.id);
      if (
        !removeScope ||
        !isChatRequestScopeActive(removeScope) ||
        uiRevision.current !== removeUiRevision ||
        sendSequence.current !== removeSendSequence
      ) {
        return;
      }
      setSessions((current) =>
        current.filter((item) => item.id !== session.id),
      );
      setTeamSessions((current) =>
        current.filter((item) => item.id !== session.id),
      );
      if (selected?.id === session.id) {
        setSelected(null);
        setDraft("");
        abandonChatRequest(undefined, removeScope);
      }
      if (selectedTeam?.id === session.id) {
        setSelectedTeam(null);
        setTeamDraft("");
        teamPendingRequest.current = null;
      }
    } catch (cause) {
      if (
        removeScope &&
        isChatRequestScopeActive(removeScope) &&
        uiRevision.current === removeUiRevision &&
        sendSequence.current === removeSendSequence
      ) {
        setError(cause);
      }
    }
  }

  async function send(
    event?: FormEvent,
    preset?: {
      session: AgentChatSession;
      requestId: string;
      expectedRevision: number;
      message: string;
    },
  ) {
    event?.preventDefault();
    const message = preset?.message ?? draft.trim();
    if (
      !message ||
      busy ||
      (!preset && !selected && !versionId) ||
      !scopeKey ||
      loadedScope !== scopeKey ||
      historyRefreshTarget ||
      getChatRequest(scopeKey)?.promise
    ) {
      return;
    }
    const sendAttempt = ++sendSequence.current;
    const attemptId = createChatRequestAttempt(scopeKey);
    if (attemptId === null) return;
    const interactionAtSend = uiRevision.current;
    let confirmedUnknownOutcome = false;
    const ownsSend = () =>
      sendSequence.current === sendAttempt &&
      uiRevision.current === interactionAtSend &&
      isChatRequestScopeActive(scopeKey) &&
      isChatRequestAttemptCurrent(attemptId, scopeKey);
    setBusy(true);
    setPendingMessage(message);
    setDraft("");
    setError(null);
    try {
      const session =
        preset?.session ??
        selected ??
        (await api.createConversation(versionId));
      if (!ownsSend()) return;
      if (!selected || preset) remember(session, true);
      if (!selected && !preset && newChatRoute) closeNewEntry(true);
      if (
        preset &&
        (preset.session.read_only === true || preset.session.can_send === false)
      ) {
        throw new PlatformApiError(403, "chat_read_only", {
          code: "chat_read_only",
          message: "chat_read_only",
        });
      }
      const pending = getChatRequest(scopeKey);
      const reuse =
        pending &&
        pending.status === "uncertain" &&
        pending.message === message &&
        (pending.sessionId === session.id || pending.sessionId === null)
          ? pending
          : null;
      const requestId = preset?.requestId ?? reuse?.requestId ?? newRequestId();
      const revision =
        preset?.expectedRevision ?? reuse?.revision ?? session.revision;
      const promise = api
        .streamConversation(
          session.id,
          {
            request_id: requestId,
            message,
            expected_revision: revision,
          },
          {
            onTextDone: (refreshed) => {
              if (!ownsSend()) return;
              settleChatRequest(requestId, refreshed, scopeKey, attemptId);
              setPendingMessage("");
              setBusy(false);
            },
            onPending: (refreshed, pendingTurnId) => {
              if (!ownsSend()) return;
              remember(refreshed);
              observeChatRequestOnTurn(
                requestId,
                pendingTurnId,
                scopeKey,
                attemptId,
              );
            },
            onTerminalError: (refreshed, terminalError) => {
              if (!ownsSend()) return;
              if (refreshed) remember(refreshed);
              const requestTurn = refreshed?.turns.find(
                (turn) => turn.id === requestId,
              );
              const pendingTurn =
                (requestTurn?.state === "pending" ? requestTurn : undefined) ??
                refreshed?.turns.find((turn) => turn.state === "pending");
              if (pendingTurn) {
                observeChatRequestOnTurn(
                  requestId,
                  String(pendingTurn.id),
                  scopeKey,
                  attemptId,
                );
                return;
              }
              if (requestTurn?.state === "acceptance_unknown") {
                confirmedUnknownOutcome = true;
                setError(unknownChatOutcomeError());
                markChatRequestUncertain(requestId, scopeKey, attemptId);
              } else {
                settleChatRequest(requestId, refreshed, scopeKey, attemptId);
              }
            },
            onUncertain: (refreshed) => {
              if (!ownsSend()) return;
              if (refreshed) remember(refreshed);
              markChatRequestUncertain(requestId, scopeKey, attemptId);
            },
          },
        )
        .then((result) => result.session);
      beginChatRequest({
        sessionId: session.id,
        versionId: session.agent.version_id,
        message,
        requestId,
        revision,
        scopeKey,
        attemptId,
        promise,
      });
      const result = await promise;
      if (ownsSend()) {
        remember(result);
        settleChatRequest(requestId, result, scopeKey, attemptId);
      }
    } catch (cause) {
      if (!(cause instanceof ChatRequestPendingError) && ownsSend()) {
        // Nothing was saved for a refused send, so there is no outcome to
        // check later and no request to resume: the next Send is a new one.
        if (isRefusedSend(cause)) abandonChatRequest(undefined, scopeKey);
        setError(confirmedUnknownOutcome ? unknownChatOutcomeError() : cause);
        setDraft(message);
      }
    } finally {
      if (ownsSend()) {
        const pending = getChatRequest(scopeKey);
        const inFlight = pending?.promise != null;
        const observing = pending?.status === "observing";
        setPendingMessage(
          inFlight && pending?.status === "in_flight" ? pending.message : "",
        );
        setBusy(inFlight || observing);
      }
    }
  }

  async function checkUncertainRequestStatus() {
    const request = scopeKey ? getChatRequest(scopeKey) : null;
    if (
      !scopeKey ||
      loadedScope !== scopeKey ||
      request?.status !== "uncertain" ||
      !request.sessionId ||
      busy
    ) {
      return;
    }
    const checkUiRevision = uiRevision.current;
    const checkSendSequence = sendSequence.current;
    const stillCurrent = () =>
      isChatRequestScopeActive(scopeKey) &&
      uiRevision.current === checkUiRevision &&
      sendSequence.current === checkSendSequence &&
      getChatRequest(scopeKey)?.attemptId === request.attemptId;
    setError(null);
    try {
      const session = await api.conversation(request.sessionId);
      if (!stillCurrent()) return;
      remember(session);
      const turn = session.turns.find((item) => item.id === request.requestId);
      if (turn?.state === "ready") {
        if (draft.trim() === request.message) setDraft("");
        settleChatRequest(
          request.requestId,
          session,
          scopeKey,
          request.attemptId,
        );
      } else if (turn?.state === "pending") {
        observeChatRequestOnTurn(
          request.requestId,
          request.requestId,
          scopeKey,
          request.attemptId,
        );
      } else if (
        turn?.state === "failed" ||
        turn?.state === "acceptance_unknown"
      ) {
        if (turn.state === "acceptance_unknown") {
          setError(unknownChatOutcomeError());
          markChatRequestUncertain(
            request.requestId,
            scopeKey,
            request.attemptId,
          );
        } else {
          const code = turn.safe_error_code ?? "chat_failed";
          setError(new PlatformApiError(503, code, { code, message: code }));
          settleChatRequest(
            request.requestId,
            session,
            scopeKey,
            request.attemptId,
          );
        }
      } else if (session.turns.some((item) => item.state === "pending")) {
        const pendingTurn = session.turns.find(
          (item) => item.state === "pending",
        );
        if (pendingTurn) {
          observeChatRequestOnTurn(
            request.requestId,
            String(pendingTurn.id),
            scopeKey,
            request.attemptId,
          );
        }
      } else {
        retryChatRequestAtRevision(
          request.requestId,
          session.revision,
          scopeKey,
          request.attemptId,
        );
      }
    } catch (cause) {
      if (stillCurrent()) setError(cause);
    }
  }

  async function dispatchMemoryEntry(entry: MemoryEntryResult, retry = false) {
    if (!isChatRequestScopeActive(scopeKey)) return;
    const session = entry.session;
    const key = `${scopeKey}:${entry.action_id}`;
    const dispatchKey = `maya:brainform-memory:${key}`;
    const hasStarted = (() => {
      try {
        return window.sessionStorage.getItem(dispatchKey) === "sent";
      } catch {
        return false;
      }
    })();

    if (isTeamSession(session)) {
      setSelected(null);
      setSelectedTeam(session);
      rememberTeam(session, true);
      const savedTurn = session.turns.find(
        (turn) => turn.id === entry.request_id,
      );
      if (savedTurn) {
        setMemoryRetryEntry(null);
        if (savedTurn.state === "acceptance_unknown") {
          setTeamError(unknownChatOutcomeError());
        } else if (savedTurn.state === "pending") {
          setTeamError(new ChatRequestPendingError());
        } else {
          setTeamError(null);
        }
        return;
      }
      if (session.turns.some((turn) => turn.state === "pending")) {
        setMemoryRetryEntry(entry);
        setTeamError(new ChatRequestPendingError());
        return;
      }
      if (session.read_only || !session.can_send) {
        setMemoryRetryEntry(null);
        setTeamError(
          new PlatformApiError(403, "chat_read_only", {
            code: "chat_read_only",
            message: "chat_read_only",
          }),
        );
        return;
      }
      if (hasStarted && !retry) {
        setMemoryRetryEntry(entry);
        return;
      }
      if (teamPendingRequest.current?.body.request_id === entry.request_id)
        return;
      try {
        window.sessionStorage.setItem(dispatchKey, "sent");
      } catch {
        // The server request_id remains the durable deduplication key.
      }
      setMemoryRetryEntry(entry);
      setPendingMessage(entry.message);
      try {
        await sendTeam(undefined, {
          session,
          requestId: entry.request_id,
          expectedRevision: session.revision,
          message: entry.message,
        });
      } finally {
        setPendingMessage("");
      }
      try {
        const refreshed = await api.conversationSession(session.id);
        if (!isChatRequestScopeActive(scopeKey) || !isTeamSession(refreshed))
          return;
        rememberTeam(refreshed);
        setSelectedTeam(refreshed);
        const current = refreshed.turns.some(
          (turn) => turn.id === entry.request_id,
        );
        setMemoryRetryEntry(current ? null : { ...entry, session: refreshed });
      } catch {
        // Keep the same action and request identity available for a deliberate retry.
      }
      return;
    }

    if (!isAgentSession(session)) return;
    setSelectedTeam(null);
    setSelected(session);
    remember(session, true);
    setVersionId(session.agent.version_id);
    const savedTurn = session.turns.find(
      (turn) => turn.id === entry.request_id,
    );
    if (savedTurn) {
      setMemoryRetryEntry(null);
      if (savedTurn.state === "pending") {
        const current = getChatRequest(scopeKey);
        if (!current || current.requestId === savedTurn.id) {
          const observed = adoptPendingChatRequest(
            {
              sessionId: session.id,
              versionId: session.agent.version_id,
              message: savedTurn.user_text,
              requestId: savedTurn.id,
              revision: Math.max(0, session.revision - 1),
            },
            scopeKey,
          );
          setRequestState(observed);
          setBusy(true);
        } else {
          setError(new ChatRequestPendingError());
        }
      } else if (savedTurn.state === "acceptance_unknown") {
        setError(unknownChatOutcomeError());
        const observed = adoptUncertainChatRequest(
          {
            sessionId: session.id,
            versionId: session.agent.version_id,
            message: savedTurn.user_text,
            requestId: savedTurn.id,
            revision: Math.max(0, session.revision - 1),
          },
          scopeKey,
        );
        setRequestState(observed);
      } else if (savedTurn.state === "failed") {
        const code = savedTurn.safe_error_code ?? "chat_failed";
        setError(new PlatformApiError(503, code, { code, message: code }));
      }
      return;
    }
    if (session.turns.some((turn) => turn.state === "pending")) {
      const pendingTurn = session.turns.find(
        (turn) => turn.state === "pending",
      );
      if (pendingTurn) {
        const current = getChatRequest(scopeKey);
        if (!current || current.requestId === pendingTurn.id) {
          const observed = adoptPendingChatRequest(
            {
              sessionId: session.id,
              versionId: session.agent.version_id,
              message: pendingTurn.user_text,
              requestId: pendingTurn.id,
              revision: Math.max(0, session.revision - 1),
            },
            scopeKey,
          );
          setRequestState(observed);
          setBusy(true);
        }
      }
      setMemoryRetryEntry(entry);
      return;
    }
    if (
      session.read_only === true ||
      session.can_send === false ||
      session.agent.available === false
    ) {
      setMemoryRetryEntry(null);
      setError(
        new PlatformApiError(403, "chat_read_only", {
          code: "chat_read_only",
          message: "chat_read_only",
        }),
      );
      return;
    }
    if (hasStarted && !retry) {
      setMemoryRetryEntry(entry);
      return;
    }
    const current = getChatRequest(scopeKey);
    if (current?.requestId === entry.request_id && current.promise) return;
    if (current?.promise) {
      setMemoryRetryEntry(entry);
      return;
    }
    try {
      window.sessionStorage.setItem(dispatchKey, "sent");
    } catch {
      // The request_id still deduplicates the server-side message stage.
    }
    setMemoryRetryEntry(entry);
    await send(undefined, {
      session,
      requestId: entry.request_id,
      expectedRevision: session.revision,
      message: entry.message,
    });
    try {
      const refreshed = await api.conversationSession(session.id);
      if (!isChatRequestScopeActive(scopeKey) || !isAgentSession(refreshed))
        return;
      remember(refreshed);
      setSelected(refreshed);
      const currentTurn = refreshed.turns.some(
        (turn) => turn.id === entry.request_id,
      );
      setMemoryRetryEntry(
        currentTurn ? null : { ...entry, session: refreshed },
      );
    } catch {
      // Keep the same action and request identity available for a deliberate retry.
    }
  }

  useEffect(() => {
    memoryDispatch.current = dispatchMemoryEntry;
    // This ref intentionally tracks the latest committed render; dispatch also
    // closes over the current send/session helpers, which are render-scoped.
  });

  useEffect(() => {
    if (loadedScope !== scopeKey || !isChatRequestScopeActive(scopeKey)) return;
    if (parsedMemoryRoute.kind === "none" || invalidMemoryRoute) return;
    const marker = `${scopeKey}:${parsedMemoryRoute.value.actionId}`;
    if (memoryActionHandled.current === marker) return;
    memoryActionHandled.current = marker;
    const route = parsedMemoryRoute.value;
    setMemoryLoading(true);
    setError(null);
    void api
      .memoryEntry({
        action_id: route.actionId,
        course_id: route.courseId,
        source: route.source,
      })
      .then(async (entry) => {
        if (
          !isChatRequestScopeActive(scopeKey) ||
          entry.action_id !== route.actionId ||
          entry.conversation_id !== entry.session.id
        ) {
          return;
        }
        const sessionCourseId = isTeamSession(entry.session)
          ? entry.session.team.course_id
          : entry.session.agent.course_id;
        if (sessionCourseId !== route.courseId) {
          setError(
            new PlatformApiError(400, "memory_entry_invalid", {
              code: "memory_entry_invalid",
              message: t("brainformMemoryInvalid"),
            }),
          );
          return;
        }
        await memoryDispatch.current(entry);
      })
      .catch((cause) => {
        if (isChatRequestScopeActive(scopeKey)) setError(cause);
      })
      .finally(() => {
        if (isChatRequestScopeActive(scopeKey)) setMemoryLoading(false);
      });
  }, [
    api,
    courseId,
    invalidMemoryRoute,
    loadedScope,
    parsedMemoryRoute,
    scopeKey,
    t,
  ]);

  async function retryMemoryQuery() {
    if (
      !memoryRetryEntry ||
      memoryRetryBusy ||
      !isChatRequestScopeActive(scopeKey)
    )
      return;
    const entry = memoryRetryEntry;
    setMemoryRetryBusy(true);
    try {
      const session = await api.conversationSession(entry.conversation_id);
      if (
        !isChatRequestScopeActive(scopeKey) ||
        session.id !== entry.conversation_id
      )
        return;
      await memoryDispatch.current({ ...entry, session }, true);
    } catch (cause) {
      if (isChatRequestScopeActive(scopeKey)) setError(cause);
    } finally {
      if (isChatRequestScopeActive(scopeKey)) setMemoryRetryBusy(false);
    }
  }

  const character =
    selected?.agent ?? agents.find((agent) => agent.version_id === versionId);
  const agentCanSend =
    selected?.read_only !== true &&
    selected?.can_send !== false &&
    character?.available !== false;
  const teamMode = Boolean(selectedTeam);
  // After the last answer the Scorer marks the test; the Chat waits for it.
  const teamScoring =
    selectedTeam?.assessment_stage === "scoring" ||
    (teamStreamDropped && selectedTeam?.turns.at(-1)?.state === "pending");
  const sendHint = teamMode
    ? sendRefusalHint(teamError, teamScoring)
    : sendRefusalHint(error);
  const activeSession = selectedTeam ?? selected;
  const teamIds = new Set(teamChoices.map((team) => team.id));
  const teamOptions: ChatTargetTeam[] = [
    ...teamChoices,
    ...mayaChoices
      .filter((team) => !teamIds.has(team.id))
      .map((team) => ({
        id: team.id,
        display_name: team.display_name,
        visibility: "public" as const,
      })),
  ];
  const chatTitle = selectedTeam?.team.name ?? character?.name ?? "";
  const chatKind = teamMode ? "Team" : "Agent";
  const hasTarget = Boolean(selected || selectedTeam || versionId);
  // Inside an open Chat, errors sit under the latest message, not above the page.
  const showConversation = hasTarget && !newChatRoute;
  const deletedMember = selectedTeam?.team.members.find(
    (member) => member.deleted,
  );
  // A running turn, including the server's own scoring and summary, blocks
  // sending only for now; it is not a reason the Chat cannot continue.
  const teamWorking =
    selectedTeam?.turns.at(-1)?.state === "pending" ||
    selectedTeam?.assessment_stage === "preparing" ||
    selectedTeam?.assessment_stage === "scoring" ||
    (selectedTeam?.assessment_stage === "summarizing" &&
      selectedTeam.can_send === false);
  const shownTeamTurns = selectedTeam
    ? studentEndFlowTurns(selectedTeam.turns)
    : [];
  // Name the real reason when no member can be reached: that is not a
  // runtime limit (bug 2026-10-18 showed the runtime text for it).
  const teamUnavailableText =
    selectedTeam &&
    selectedTeam.team.members.length > 0 &&
    selectedTeam.team.members.every((member) => !member.available)
      ? t("teamChatMembersUnavailable")
      : t("teamChatUnavailable");
  // Why this Chat cannot continue, shown once under its latest message.
  const closedNotice = selectedTeam
    ? selectedTeam.team.deleted
      ? t("chatTeamDeleted")
      : deletedMember
        ? t("chatTeamMemberDeleted", { name: deletedMember.name })
        : selectedTeam.read_only
          ? t("teamChatReadOnly")
          : !selectedTeam.can_send && !teamWorking
            ? teamUnavailableText
            : null
    : selected?.agent.deleted
      ? t("chatAgentDeleted")
      : character?.available === false
        ? readOnlyHelp
        : null;
  // Done creates a Chat before its first message, so every saved Chat is
  // listed; it is named by its first message, else by whom it is with.
  const historyItems = [
    ...sessions.map((session) => ({
      kind: "agent" as const,
      session,
      name: session.agent.name,
    })),
    ...teamSessions.map((session) => ({
      kind: "team" as const,
      session,
      name: session.team.name,
    })),
  ]
    .map((item) => ({
      ...item,
      label:
        item.session.title ||
        item.session.turns.find((turn) => turn.user_text)?.user_text ||
        item.name,
    }))
    // Pinned Chats lead, the latest pin first; the rest go newest first.
    .sort(
      (left, right) =>
        Number(Boolean(right.session.pinned_at)) -
          Number(Boolean(left.session.pinned_at)) ||
        (right.session.pinned_at ?? "").localeCompare(
          left.session.pinned_at ?? "",
        ) ||
        right.session.created_at.localeCompare(left.session.created_at),
    );

  const mentionMembers: {
    key: string;
    id: string | null;
    name: string;
    available: boolean;
  }[] = selectedTeam
    ? selectedTeam.team.members.map((member) => ({
        key: member.id,
        id: member.id,
        name: member.name,
        available: member.available,
      }))
    : [];
  const canMention = Boolean(
    selectedTeam && selectedTeam.can_send && !selectedTeam.read_only,
  );

  function insertMention(label: string) {
    const { next, caret } = applyMentionInsert(teamDraft, label);
    insertedMention.current = insertedMentionAt(teamDraft, label);
    flushSync(() => {
      setTeamDraft(next);
      setTeamRecipientMenu(false);
    });
    placeMentionCaret(messageRef.current, caret);
  }

  function submitMessage(event?: FormEvent) {
    if (selectedTeam) void sendTeam(event);
    else void send(event);
  }

  if (!scopeKey || loadedScope !== scopeKey || loading) {
    return (
      <>
        <WorkspaceAction name="new" disabled />
        <LoadingCard />
      </>
    );
  }

  return (
    <>
      <PageIntro title="Chatform" />
      <WorkspaceAction
        name="new"
        disabled={busy || teamBusy || newChatRoute}
        onClick={openNewEntry}
      />
      {newChatRoute ? (
        <>
          <PageAction
            name="back"
            disabled={creating}
            onClick={() => closeNewEntry()}
          />
          <PageAction
            name="done"
            disabled={!pick || creating || busy || teamBusy}
            onClick={() => void createPicked()}
          />
        </>
      ) : null}
      {/* Owner decision (2026-10-13): opening Memory shows no status line
          and no "continue" button; the Chat itself shows what happened. */}
      {invalidMemoryRoute ? (
        <DismissibleAlert className={styles.memoryStatus}>
          {t("brainformMemoryInvalid")}
        </DismissibleAlert>
      ) : null}
      {error && !showConversation ? (
        <ErrorNotice
          error={error}
          onRetry={
            historyRefreshTarget
              ? () => void openHistory(historyRefreshTarget)
              : undefined
          }
        />
      ) : null}
      {requestState?.status === "uncertain" && requestState.sessionId ? (
        <button
          className="inline-button"
          type="button"
          onClick={() => void checkUncertainRequestStatus()}
        >
          {t("chatCheckStatus")}
        </button>
      ) : null}
      {newChatRoute ? (
        <ChatTargetPicker
          teams={teamOptions}
          agents={agents}
          value={pick}
          disabled={creating}
          onPick={setPick}
        />
      ) : (
        <div className={styles.layout}>
          <aside className={styles.sidebar}>
            <div className={styles.historyHead}>
              <h2>{t("chatHistory")}</h2>
            </div>
            <div className={styles.history} aria-label="History">
              {historyItems.length === 0 ? (
                <p className={styles.historyEmpty}>{t("chatHistoryEmpty")}</p>
              ) : null}
              {historyItems.map(({ kind, session, name, label }) => (
                <div className={styles.historyRow} key={session.id}>
                  {renaming?.session.id === session.id ? (
                    <input
                      className={styles.historyRename}
                      aria-label={t("renameChat")}
                      value={renaming.value}
                      maxLength={80}
                      autoFocus
                      onFocus={(event) => event.currentTarget.select()}
                      onChange={(event) => {
                        const value = event.currentTarget.value;
                        setRenaming((current) =>
                          current ? { ...current, value } : current,
                        );
                      }}
                      onKeyDown={(event) => {
                        if (event.nativeEvent.isComposing) return;
                        if (event.key === "Enter") {
                          event.preventDefault();
                          commitRename();
                        } else if (event.key === "Escape") {
                          event.preventDefault();
                          setRenaming(null);
                        }
                      }}
                      onBlur={commitRename}
                    />
                  ) : (
                    <button
                      type="button"
                      className={styles.historySelect}
                      // Not `disabled`: the second click of a double-click
                      // lands while the first one is opening the Chat.
                      aria-disabled={busy || teamBusy || undefined}
                      aria-current={
                        (kind === "agent" ? selected?.id : selectedTeam?.id) ===
                        session.id
                          ? "page"
                          : undefined
                      }
                      data-ui-guide="chat.history"
                      data-ui-guide-text={name}
                      onClick={() => {
                        if (busy || teamBusy) return;
                        if (kind === "agent") void openHistory(session);
                        else void openTeamHistory(session);
                      }}
                      onDoubleClick={() =>
                        setRenaming({ session, initial: label, value: label })
                      }
                      onKeyDown={(event) => {
                        if (event.key !== "F2") return;
                        event.preventDefault();
                        setRenaming({ session, initial: label, value: label });
                      }}
                    >
                      <span>{label}</span>
                    </button>
                  )}
                  <span className={styles.historyMeta}>
                    <small className={styles.historyDate}>
                      {new Date(session.created_at).toLocaleDateString()}
                    </small>
                    <button
                      type="button"
                      className={styles.historyPin}
                      disabled={arranging === session.id}
                      aria-pressed={Boolean(session.pinned_at)}
                      aria-label={
                        session.pinned_at ? t("unpinChat") : t("pinChat")
                      }
                      data-ui-guide="chat.pin"
                      onClick={(event) => {
                        event.stopPropagation();
                        void arrangeChat(session, {
                          pinned: !session.pinned_at,
                        });
                      }}
                    >
                      <IconPin filled={Boolean(session.pinned_at)} />
                    </button>
                    <button
                      type="button"
                      className={styles.historyDelete}
                      disabled={
                        busy ||
                        teamBusy ||
                        ("read_only" in session && session.read_only === true)
                      }
                      aria-label={t("deleteChat")}
                      data-ui-guide="chat.delete"
                      onClick={(event) => {
                        event.stopPropagation();
                        void removeChat(session);
                      }}
                    >
                      <IconClose />
                    </button>
                  </span>
                </div>
              ))}
            </div>
          </aside>
          <section
            className={styles.conversation}
            data-blank={!activeSession && !pendingMessage ? "true" : undefined}
          >
            {!hasTarget ? (
              // A blank pane read as "still loading" (2026-10-20 audit):
              // say what to do instead.
              <p className={styles.blankHint}>{t("chatPickOrNew")}</p>
            ) : (
              <>
                <header className={styles.chatHeader}>
                  <div className={styles.chatTitle}>
                    <h2>{chatTitle || t("chatNewTitle")}</h2>
                    <span className={styles.kindChip}>{chatKind}</span>
                  </div>
                </header>
                <div
                  className={styles.messages}
                  role="log"
                  aria-live="polite"
                  aria-relevant="additions text"
                >
                  {selected?.turns.map((turn) => (
                    <div key={turn.id} className={styles.exchange}>
                      {turn.user_text ? (
                        <div className={styles.userMessage}>
                          {turn.user_text}
                        </div>
                      ) : null}
                      <div className={styles.reply}>
                        {turn.assistant_text ? (
                          <ReportMarkdown>{turn.assistant_text}</ReportMarkdown>
                        ) : (
                          <span className={styles.pending} role="status">
                            {turn.state === "pending" ? (
                              <>
                                <span className="spinner" aria-hidden="true" />
                                {t("loading")}
                              </>
                            ) : turn.state === "acceptance_unknown" ? (
                              t("errorChatAcceptanceUnknown")
                            ) : (
                              localizeError(
                                { code: turn.safe_error_code },
                                locale,
                              )
                            )}
                          </span>
                        )}
                        {turn.sources.length ? (
                          <details>
                            <summary>Check RAG · {turn.sources.length}</summary>
                            {turn.sources.map((source) => (
                              <div
                                className={styles.source}
                                key={source.chunk_id}
                              >
                                <strong>{source.filename}</strong>
                                <p>{source.excerpt}</p>
                              </div>
                            ))}
                          </details>
                        ) : null}
                      </div>
                    </div>
                  ))}
                  {shownTeamTurns.map((turn) => (
                    <div key={turn.id} className={styles.exchange}>
                      {turn.user_text ? (
                        <div className={styles.userMessage}>
                          {turn.user_text}
                        </div>
                      ) : null}
                      {/* Turn-level Loading only until the first member slot
                          appears; after that each agent shows its own spinner. */}
                      {turn.state === "pending" &&
                      visibleTeamMemberResults(turn.member_results).length ===
                        0 ? (
                        <p className={styles.pending} role="status">
                          <span className="spinner" aria-hidden="true" />
                          {t("loading")}
                        </p>
                      ) : null}
                      {turn.state === "acceptance_unknown" ? (
                        <DismissibleAlert
                          className={styles.teamWarning}
                          role="status"
                        >
                          {t("errorChatAcceptanceUnknown")}
                        </DismissibleAlert>
                      ) : null}
                      {visibleTeamMemberResults(turn.member_results).some(
                        (item) =>
                          item.state === "failed" ||
                          item.state === "acceptance_unknown",
                      ) ? (
                        <DismissibleAlert
                          className={styles.teamWarning}
                          role="status"
                        >
                          {t("teamPartialResult")}
                        </DismissibleAlert>
                      ) : null}
                      <div className={styles.teamResults}>
                        {sortTeamMemberResults(
                          visibleTeamMemberResults(turn.member_results),
                          selectedTeam?.team.members ?? [],
                        ).map((result) => {
                          if (!selectedTeam) return null;
                          const participant = selectedTeam.team.members.find(
                            (member) => member.id === result.participant_id,
                          );
                          const summarizerTurnId = [...shownTeamTurns]
                            .reverse()
                            .find((item) =>
                              item.member_results.some((card) =>
                                (card.assistant_text ?? "").includes(
                                  "正在总结答案",
                                ),
                              ),
                            )?.id;
                          const formalSummarizerCard =
                            Boolean(summarizerTurnId) &&
                            turn.id === summarizerTurnId &&
                            (result.assistant_text ?? "").includes(
                              "正在总结答案",
                            ) &&
                            selectedTeam.assessment_stage !== "preparing";
                          const isSummarizerTurn =
                            !summarizerTurnId &&
                            !participant?.is_leader &&
                            !turn.user_text &&
                            (selectedTeam.assessment_stage === "summarizing" ||
                              selectedTeam.assessment_stage === "completed" ||
                              selectedTeam.assessment_stage === "scoring");
                          return (
                            <article
                              className={styles.teamResult}
                              key={result.id}
                            >
                              <h3>
                                {result.speaker_name}
                                {participant?.is_leader
                                  ? ` · ${t("leader")}`
                                  : ""}
                              </h3>
                              {result.assistant_text ? (
                                result.assistant_text.trim() ===
                                "正在总结答案" ? (
                                  <p
                                    role="status"
                                    data-team-progress="summarizing"
                                  >
                                    {result.assistant_text}
                                  </p>
                                ) : (
                                  <ReportMarkdown>
                                    {result.assistant_text}
                                  </ReportMarkdown>
                                )
                              ) : result.state === "pending" ||
                                result.state === "running" ? (
                                <p className={styles.pending} role="status">
                                  <span
                                    className="spinner"
                                    aria-hidden="true"
                                  />
                                  {t("loading")}
                                </p>
                              ) : result.state === "acceptance_unknown" ? (
                                <DismissibleAlert
                                  className={styles.teamWarning}
                                  role="status"
                                >
                                  {t("errorChatAcceptanceUnknown")}
                                </DismissibleAlert>
                              ) : (
                                <DismissibleAlert
                                  className={styles.teamWarning}
                                  role="status"
                                >
                                  {teamFailureText(
                                    result.safe_error_code,
                                    "teamMemberFailure",
                                  )}
                                </DismissibleAlert>
                              )}
                              {/* Formal progress hangs under the Summarizer line.
                                  Until that card exists, the executor card or
                                  the fallback below carries it. */}
                              {(formalSummarizerCard ||
                                (isSummarizerTurn &&
                                  turn.id ===
                                    shownTeamTurns[shownTeamTurns.length - 1]
                                      ?.id)) &&
                              selectedTeam.assessment_stage &&
                              selectedTeam.assessment_stage !== "preparing" ? (
                                <AssessmentProgress
                                  stage={selectedTeam.assessment_stage}
                                />
                              ) : null}
                            </article>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                  {pendingMessage ? (
                    <div className={styles.exchange}>
                      <div className={styles.userMessage}>{pendingMessage}</div>
                      <div className={styles.pending} role="status">
                        <span className="spinner" aria-hidden="true" />
                        {t("loading")}
                      </div>
                    </div>
                  ) : null}
                  {error && !sendRefusalHint(error) ? (
                    <ErrorNotice
                      inline
                      error={error}
                      onRetry={
                        historyRefreshTarget
                          ? () => void openHistory(historyRefreshTarget)
                          : undefined
                      }
                    />
                  ) : null}
                  {closedNotice &&
                  closedNoticeDismissed !== activeSession?.id ? (
                    <Notice
                      inline
                      id="chat-readonly-help"
                      tone="warning"
                      onClose={() =>
                        setClosedNoticeDismissed(activeSession?.id ?? null)
                      }
                    >
                      {closedNotice}
                    </Notice>
                  ) : null}
                  {selectedTeam && teamError && !sendRefusalHint(teamError) ? (
                    <Notice
                      inline
                      tone="error"
                      onClose={() => setTeamError(null)}
                      action={
                        teamError instanceof PlatformApiError &&
                        teamError.code ===
                          "assessment_resume_choice_required" ? (
                          <span>
                            {["继续", "重新做"].map((choice) => (
                              <button
                                key={choice}
                                type="button"
                                className="inline-button"
                                disabled={teamBusy}
                                onClick={() => {
                                  setTeamError(null);
                                  setTeamDraft(choice);
                                }}
                              >
                                {choice}
                              </button>
                            ))}
                          </span>
                        ) : teamError instanceof PlatformApiError &&
                          teamError.code ===
                            "assessment_resume_original_conversation" &&
                          typeof teamError.details?.conversation_id ===
                            "string" ? (
                          <button
                            type="button"
                            className="inline-button"
                            disabled={teamBusy}
                            onClick={() =>
                              void openTeamHistory({
                                id: (teamError as PlatformApiError).details
                                  ?.conversation_id,
                              } as TeamChatSession)
                            }
                          >
                            打开上次的作答
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="inline-button"
                            disabled={teamBusy}
                            onClick={() => void checkTeamStatus()}
                          >
                            {t("teamCheckStatus")}
                          </button>
                        )
                      }
                    >
                      {teamErrorText(teamError)}
                    </Notice>
                  ) : null}
                  {/* Scoring with no summarizer or executor card yet still needs a bar. */}
                  {selectedTeam?.assessment_stage &&
                  selectedTeam.assessment_stage !== "preparing" &&
                  !shownTeamTurns.some((turn) =>
                    turn.member_results.some((result) =>
                      (result.assistant_text ?? "").includes("正在总结答案"),
                    ),
                  ) &&
                  !shownTeamTurns.some(
                    (turn) =>
                      !turn.user_text &&
                      turn.member_results.some((result) => {
                        const member = selectedTeam.team.members.find(
                          (item) => item.id === result.participant_id,
                        );
                        return member && !member.is_leader;
                      }),
                  ) ? (
                    <AssessmentProgress stage={selectedTeam.assessment_stage} />
                  ) : null}
                  {selected &&
                  isAgentSession(selected) &&
                  selected.knowledge_generation ? (
                    <KnowledgeGenerationProgress
                      status={selected.knowledge_generation}
                    />
                  ) : null}
                  <div ref={endRef} />
                </div>
                {selectedTeam ? (
                  <div className={styles.teamComposerTools}>
                    {teamError ? null : selectedTeam.turns.at(-1)?.state ===
                      "paused" ? (
                      <button
                        type="button"
                        className="inline-button"
                        disabled={teamBusy}
                        onClick={() => void resumePausedTeam()}
                      >
                        {t("teamResume")}
                      </button>
                    ) : null}
                  </div>
                ) : null}
                {teamScoring ? (
                  <p className={styles.scoringNotice} role="status">
                    {t("chatScoringNotice")}
                  </p>
                ) : null}
                <form
                  className={styles.composer}
                  onSubmit={(event) => submitMessage(event)}
                >
                  {canMention && teamRecipientMenu ? (
                    <div
                      ref={teamRecipientMenuRef}
                      className={styles.recipientMenu}
                      role="menu"
                      aria-label={t("teamRecipients")}
                    >
                      {mentionMembers.map((member) => (
                        <button
                          key={member.key}
                          type="button"
                          role="menuitem"
                          disabled={teamBusy || !member.available}
                          onClick={() => insertMention(member.name)}
                        >
                          {member.name}
                        </button>
                      ))}
                    </div>
                  ) : null}
                  <textarea
                    ref={messageRef}
                    id="chat-message"
                    aria-label="Message"
                    placeholder={t("chatMessagePlaceholder")}
                    aria-describedby={
                      !teamMode && character?.available === false
                        ? "chat-readonly-help"
                        : undefined
                    }
                    value={teamMode ? teamDraft : draft}
                    rows={1}
                    disabled={
                      selectedTeam
                        ? teamBusy ||
                          !selectedTeam.can_send ||
                          selectedTeam.read_only ||
                          teamWorking
                        : busy || !agentCanSend
                    }
                    onChange={(event) => {
                      if (teamMode) setTeamDraft(event.target.value);
                      else {
                        uiRevision.current += 1;
                        setDraft(event.target.value);
                      }
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Escape") {
                        setTeamRecipientMenu(false);
                        return;
                      }
                      if (
                        teamMode &&
                        event.key === "Backspace" &&
                        !event.nativeEvent.isComposing
                      ) {
                        const el = event.currentTarget;
                        const collapsed =
                          el.selectionStart === el.selectionEnd
                            ? collapseMentionOnBackspace(
                                teamDraft,
                                el.selectionStart,
                                insertedMention.current,
                              )
                            : null;
                        insertedMention.current = null;
                        if (collapsed) {
                          event.preventDefault();
                          flushSync(() => {
                            setTeamDraft(collapsed.next);
                            if (canMention) setTeamRecipientMenu(true);
                          });
                          placeMentionCaret(el, collapsed.caret);
                          return;
                        }
                      }
                      if (
                        canMention &&
                        event.key === "@" &&
                        !event.nativeEvent.isComposing
                      ) {
                        setTeamRecipientMenu(true);
                      }
                      // Enter never sends: pinyin input confirms a candidate
                      // with Enter, and Safari reports that keydown as no
                      // longer composing. Only the Send button submits.
                    }}
                  />
                  {selectedTeam && !selectedTeam.read_only ? (
                    <ChatAttachments
                      key={selectedTeam.id}
                      conversationId={selectedTeam.id}
                      disabled={teamBusy || teamWorking}
                    />
                  ) : !selectedTeam &&
                    selected &&
                    isAgentSession(selected) &&
                    agentCanSend ? (
                    // Same "+" for a one-to-one Agent Chat: the files belong
                    // to this Chat and its owner only (server-enforced).
                    <ChatAttachments
                      key={selected.id}
                      conversationId={selected.id}
                      disabled={busy}
                    />
                  ) : null}
                  <div className={styles.composerBar}>
                    {sendHint ? (
                      <p
                        id="chat-send-hint"
                        className={styles.sendHint}
                        role="status"
                      >
                        {t(sendHint)}
                      </p>
                    ) : null}
                    <button
                      type="submit"
                      className={styles.sendButton}
                      aria-describedby={
                        sendHint
                          ? "chat-send-hint"
                          : !teamMode && character?.available === false
                            ? "chat-readonly-help"
                            : undefined
                      }
                      aria-label={
                        selectedTeam?.read_only
                          ? t("teamChatReadOnly")
                          : selectedTeam &&
                              !selectedTeam.can_send &&
                              !teamWorking
                            ? teamUnavailableText
                            : !teamMode && character?.available === false
                              ? "Read-only"
                              : "Send"
                      }
                      data-ui-guide={
                        selectedTeam?.read_only ||
                        (selectedTeam !== null &&
                          !selectedTeam.can_send &&
                          !teamWorking) ||
                        (!teamMode && !agentCanSend)
                          ? "chat.readOnly"
                          : "chat.send"
                      }
                      data-ui-guide-text={
                        selectedTeam?.read_only
                          ? t("teamChatReadOnly")
                          : selectedTeam &&
                              !selectedTeam.can_send &&
                              !teamWorking
                            ? teamUnavailableText
                            : !teamMode && !agentCanSend
                              ? readOnlyHelp
                              : undefined
                      }
                      disabled={
                        busy ||
                        teamBusy ||
                        historyRefreshTarget !== null ||
                        !(teamMode ? teamDraft.trim() : draft.trim()) ||
                        (selectedTeam
                          ? !selectedTeam.can_send ||
                            selectedTeam.read_only ||
                            teamWorking
                          : !agentCanSend ||
                            !versionId ||
                            Boolean(
                              selected?.turns.some(
                                (turn) => turn.state === "pending",
                              ),
                            ))
                      }
                    >
                      <svg
                        viewBox="0 0 24 24"
                        width="18"
                        height="18"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                      >
                        <path d="M12 19V5m-7 7 7-7 7 7" />
                      </svg>
                    </button>
                  </div>
                </form>
              </>
            )}
          </section>
        </div>
      )}
    </>
  );
}
