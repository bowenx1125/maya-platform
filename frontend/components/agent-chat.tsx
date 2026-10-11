"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import {
  ChatRequestPendingError,
  PlatformApiError,
  type PlatformApi,
  type ChatAgent,
  type ChatSession,
  type AgentChatSession,
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
  ChatTargetPicker,
  type ChatTargetTeam,
} from "./chats/chat-target-picker";
import { useLocale, useT } from "./locale";
import { localizeError } from "../lib/i18n";
import { uiGuideText } from "../lib/ui-guide-copy";
import { IconClose } from "./quiet-icons";
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

function mentionLabel(text: string): string | null {
  const visible = text.replace(/```[\s\S]*?```/g, " ");
  const labels = [...visible.matchAll(/@([^\s@]+)/g)].map((match) => match[1]);
  return labels.at(-1) ?? null;
}

function routingForMention(
  session: TeamChatSession,
  message: string,
): TeamRouting {
  const leaderId = session.team.members.find((member) => member.is_leader)?.id;
  const leader: TeamRouting = leaderId
    ? { mode: "selected", participant_ids: [leaderId] }
    : { mode: "auto", participant_ids: [] };
  const label = mentionLabel(message);
  if (!label) return leader;
  if (label === "All") return { mode: "all", participant_ids: [] };
  const member = session.team.members.find(
    (item) => item.name === label && item.available !== false,
  );
  return member ? { mode: "selected", participant_ids: [member.id] } : leader;
}

function isAgentSession(
  session: ConversationSession,
): session is AgentChatSession {
  return session.entry_kind === undefined || session.entry_kind === "agent";
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
      role={role}
    />
  );
}

function AgentChatScope({
  api,
  courseId,
  actorId,
  scopeKey,
  role,
}: {
  api: PlatformApi;
  courseId: string;
  actorId: string;
  scopeKey: string;
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
  const messageRef = useRef<HTMLTextAreaElement>(null);
  const [teamBusy, setTeamBusy] = useState(false);
  const [teamError, setTeamError] = useState<unknown>(null);
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
    void Promise.all([api.chatAgents(courseId), historyRequest])
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
    courseId,
    invalidMemoryRoute,
    newChatRoute,
    parsedMemoryRoute,
    scopeKey,
  ]);

  const loadTeamChoices = useCallback(async () => {
    const [teams, mayaTeams] = await Promise.all([
      typeof api.teams === "function"
        ? api.teams(courseId).catch(() => [])
        : Promise.resolve([]),
      typeof api.mayaTeams === "function"
        ? api.mayaTeams(courseId).catch(() => [])
        : Promise.resolve([]),
    ]);
    if (!isChatRequestScopeActive(scopeKey)) return;
    setTeamChoices(teams);
    setMayaChoices(mayaTeams);
  }, [api, courseId, scopeKey]);

  useEffect(() => {
    if (loadedScope !== scopeKey) return;
    const timer = window.setTimeout(() => void loadTeamChoices(), 0);
    return () => window.clearTimeout(timer);
  }, [loadTeamChoices, loadedScope, newChatRoute, scopeKey]);

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
      if (active) timer = setTimeout(() => void poll(), 1500);
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
      } catch {
        // Idle refresh is opportunistic; opening the history remains the
        // explicit path that reports a failed conversation read.
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

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [selected?.id, selected?.turns.length, busy, pendingMessage]);

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

  // Done on the New page creates the Chat at once. A Team whose published
  // recipe is complete arrives with the Leader's opening already saved.
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
    if (
      !session ||
      !message ||
      teamBusy ||
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
    setTeamBusy(true);
    setTeamError(null);
    setTeamLastEventId(0);
    try {
      const result = await api.streamTeamConversation(session.id, request, {
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
      });
      if (
        sequence !== teamSendSequence.current ||
        !isChatRequestScopeActive(scopeAtSend) ||
        !isTeamSession(result) ||
        result.id !== sentSessionId ||
        (!preset && selectedTeamIdRef.current !== sentSessionId)
      ) {
        return;
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
          const turn = refreshed.turns.find((item) => item.id === requestId);
          setTeamError(
            turn?.state === "pending"
              ? new ChatRequestPendingError()
              : turn?.state === "acceptance_unknown"
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
        if (sequence === teamSendSequence.current) setTeamError(cause);
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
  // Why this Chat cannot continue, shown once under its latest message.
  const closedNotice = selectedTeam
    ? selectedTeam.team.deleted
      ? t("chatTeamDeleted")
      : deletedMember
        ? t("chatTeamMemberDeleted", { name: deletedMember.name })
        : selectedTeam.read_only
          ? t("teamChatReadOnly")
          : !selectedTeam.can_send
            ? t("teamChatUnavailable")
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
  ].sort((left, right) =>
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
    const draft = teamDraft;
    const at = draft.lastIndexOf("@");
    const next =
      at >= 0
        ? `${draft.slice(0, at)}@${label}${draft.slice(at + 1).replace(/^[^\s@]*/, "")}`
        : `${draft}@${label}`;
    setTeamDraft(next);
    setTeamRecipientMenu(false);
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
      {memoryLoading ? (
        <p className={styles.memoryStatus} role="status">
          {t("brainformMemoryLoading")}
        </p>
      ) : null}
      {invalidMemoryRoute ? (
        <p className={styles.memoryStatus} role="alert">
          {t("brainformMemoryInvalid")}
        </p>
      ) : null}
      {memoryRetryEntry &&
      !memoryRetryEntry.session.turns.some(
        (turn) => turn.id === memoryRetryEntry.request_id,
      ) ? (
        <button
          type="button"
          className="inline-button"
          disabled={
            memoryRetryBusy ||
            busy ||
            teamBusy ||
            selectedTeam?.turns.at(-1)?.state === "pending"
          }
          onClick={() => void retryMemoryQuery()}
        >
          {t("brainformMemoryRetry")}
        </button>
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
              {historyItems.map(({ kind, session, name }) => (
                <div className={styles.historyRow} key={session.id}>
                  <button
                    type="button"
                    className={styles.historySelect}
                    disabled={busy || teamBusy}
                    aria-current={
                      (kind === "agent" ? selected?.id : selectedTeam?.id) ===
                      session.id
                        ? "page"
                        : undefined
                    }
                    data-ui-guide="chat.history"
                    data-ui-guide-text={name}
                    onClick={() => {
                      if (kind === "agent") void openHistory(session);
                      else void openTeamHistory(session);
                    }}
                  >
                    <span>
                      {session.turns.find((turn) => turn.user_text)
                        ?.user_text || name}
                    </span>
                  </button>
                  <span className={styles.historyMeta}>
                    <small className={styles.historyDate}>
                      {new Date(session.created_at).toLocaleDateString()}
                    </small>
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
            {!hasTarget ? null : (
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
                  {selectedTeam?.turns.map((turn) => (
                    <div key={turn.id} className={styles.exchange}>
                      {turn.user_text ? (
                        <div className={styles.userMessage}>
                          {turn.user_text}
                        </div>
                      ) : null}
                      {turn.state === "pending" ? (
                        <p className={styles.pending} role="status">
                          <span className="spinner" aria-hidden="true" />
                          {t("loading")}
                        </p>
                      ) : null}
                      {turn.state === "acceptance_unknown" ? (
                        <p className={styles.teamWarning} role="status">
                          {t("errorChatAcceptanceUnknown")}
                        </p>
                      ) : null}
                      {turn.state === "partial" ||
                      turn.member_results.some(
                        (item) =>
                          item.state === "failed" ||
                          item.state === "acceptance_unknown",
                      ) ? (
                        <p className={styles.teamWarning} role="status">
                          {t("teamPartialResult")}
                        </p>
                      ) : null}
                      <div className={styles.teamResults}>
                        {[...turn.member_results]
                          .sort((left, right) => left.ordinal - right.ordinal)
                          .map((result) => {
                            const participant = selectedTeam.team.members.find(
                              (member) => member.id === result.participant_id,
                            );
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
                                  <ReportMarkdown>
                                    {result.assistant_text}
                                  </ReportMarkdown>
                                ) : result.state === "pending" ||
                                  result.state === "running" ? (
                                  turn.state === "pending" ? (
                                    <p className={styles.pending} role="status">
                                      <span
                                        className="spinner"
                                        aria-hidden="true"
                                      />
                                      {t("loading")}
                                    </p>
                                  ) : null
                                ) : result.state === "acceptance_unknown" ? (
                                  <p
                                    className={styles.teamWarning}
                                    role="status"
                                  >
                                    {t("errorChatAcceptanceUnknown")}
                                  </p>
                                ) : (
                                  <p
                                    className={styles.teamWarning}
                                    role="status"
                                  >
                                    {teamFailureText(
                                      result.safe_error_code,
                                      "teamMemberFailure",
                                    )}
                                  </p>
                                )}
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
                  {error ? (
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
                  {selectedTeam && teamError ? (
                    <Notice
                      inline
                      tone="error"
                      onClose={() => setTeamError(null)}
                      action={
                        <button
                          type="button"
                          className="inline-button"
                          disabled={teamBusy}
                          onClick={() => void checkTeamStatus()}
                        >
                          {t("teamCheckStatus")}
                        </button>
                      }
                    >
                      {teamErrorText(teamError)}
                    </Notice>
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
                    ) : selectedTeam.turns.at(-1)?.state === "pending" ? (
                      <button
                        type="button"
                        className="inline-button"
                        disabled={teamBusy}
                        onClick={() => void checkTeamStatus()}
                      >
                        {t("teamCheckStatus")}
                      </button>
                    ) : null}
                  </div>
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
                      <button
                        type="button"
                        role="menuitem"
                        disabled={teamBusy}
                        onClick={() => insertMention(t("teamAllMembers"))}
                      >
                        {t("teamAllMembers")}
                      </button>
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
                          selectedTeam.turns.at(-1)?.state === "pending"
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
                        canMention &&
                        event.key === "@" &&
                        !event.nativeEvent.isComposing
                      ) {
                        setTeamRecipientMenu(true);
                      }
                      if (
                        event.key === "Enter" &&
                        !event.shiftKey &&
                        !event.nativeEvent.isComposing
                      ) {
                        event.preventDefault();
                        submitMessage();
                      }
                    }}
                  />
                  <div className={styles.composerBar}>
                    <button
                      type="submit"
                      className={styles.sendButton}
                      aria-describedby={
                        !teamMode && character?.available === false
                          ? "chat-readonly-help"
                          : undefined
                      }
                      aria-label={
                        selectedTeam?.read_only
                          ? t("teamChatReadOnly")
                          : selectedTeam && !selectedTeam.can_send
                            ? t("teamChatUnavailable")
                            : !teamMode && character?.available === false
                              ? "Read-only"
                              : "Send"
                      }
                      data-ui-guide={
                        selectedTeam?.read_only ||
                        (selectedTeam !== null && !selectedTeam.can_send) ||
                        (!teamMode && !agentCanSend)
                          ? "chat.readOnly"
                          : "chat.send"
                      }
                      data-ui-guide-text={
                        selectedTeam?.read_only
                          ? t("teamChatReadOnly")
                          : selectedTeam && !selectedTeam.can_send
                            ? t("teamChatUnavailable")
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
                            selectedTeam.turns.at(-1)?.state === "pending"
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
