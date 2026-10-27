"use client";

import { safeTeamsReturn } from "../lib/team-return";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  isAmbiguousMutationFailure,
  type AgentSummary,
  type PublishedAgentSummary,
  type AgentVersion,
  type ChatAgent,
  type ConversationSession,
  type GroupDetail,
  type PlatformApi,
  type TeamSummaryDto,
} from "../lib/api";
import { useIdempotencyStore } from "../lib/idempotency";
import { roleLabel } from "../lib/i18n";
import {
  cachedCall,
  forgetRequestCache,
  invalidateRequestCache,
  isBusyResponse,
  peekRequestCache,
  rememberRequestCache,
  requestCacheGeneration,
  requestCacheIdentity,
} from "../lib/request-cache";
import { fetchVoiceList, voiceListIdentity } from "../lib/voice-list-cache";
import { AccountSettings } from "./account-settings";
import { HomeGuide } from "./home-guide";
import { HomeAgentRow } from "./home/agent-row";
import {
  HOME_CARD_CLASS,
  HOME_CARD_TITLE,
  HOME_CLASS,
  HOME_TAPE_TITLE,
  HomeHero,
} from "./home/home-hero";
import { useT } from "../lib/i18n";
import { AgentWorkbench } from "./agent-workspace";
import { useSession } from "./session-provider";
import { UserAvatar } from "./user-avatar";
import { TeamEntryFlow } from "./chats/team-entry-flow";
import { assessmentAttemptsRead } from "./knowledge/assessment-record";
import { ModuleTiles, VersionTile } from "./studyform-layout";
import { AgentsEmpty, type AgentRename } from "./ui/agent-card";
import { AgentsPage } from "./agents-page";
import { PageAction } from "./page-action";
import { TeamsPage } from "./teams-page";
import { GuidePortrait } from "./ui/guide-dialog";
import { EmptyCard, ErrorNotice, LoadingCard, SectionCard } from "./ui";

type GroupOverview = {
  group: GroupDetail;
  agentCount: number;
  knowledgeCount: number;
  voiceCount: number;
};

type AgentListItem = {
  agent: AgentSummary;
  versions: AgentVersion[];
};

type StudyformGroupSnapshot = {
  group: GroupDetail;
  items: AgentListItem[];
  courseAgents: PublishedAgentSummary[];
  chatAgents: ChatAgent[];
  teams: TeamSummaryDto[];
};

async function loadGroups(
  api: PlatformApi,
  groupIds: string[],
  voiceIdentity: string | null,
): Promise<GroupOverview[]> {
  return Promise.all(
    groupIds.map(async (groupId) => {
      // Through the shared cache with Studyform's own keys: opening a group
      // from here reuses these reads instead of asking again.
      const identity = voiceIdentity;
      const [group, agents, knowledge, voices] = await Promise.all([
        cachedCall(api, identity, "group", [groupId], () => api.group(groupId)),
        cachedCall(api, identity, "agents", [groupId, true], () =>
          api.agents(groupId, true),
        ),
        cachedCall(api, identity, "knowledge", [groupId], () =>
          api.knowledge(groupId),
        ),
        // Also warms the Studyform voice list for this group.
        fetchVoiceList(api, voiceIdentity, "group", groupId, { reuse: true }),
      ]);
      return {
        group,
        agentCount: agents.length,
        knowledgeCount: knowledge.length,
        voiceCount: voices.length,
      };
    }),
  );
}

function versionBubble(agent: AgentSummary, versions: AgentVersion[]) {
  const published =
    versions.find(
      (version) => version.id === agent.current_published_version_id,
    ) ?? versions.find((version) => version.state === "published");
  const draft =
    versions.find((version) => version.id === agent.current_draft_version_id) ??
    versions.find((version) => version.state === "draft");
  const label = published?.version_label ?? draft?.version_label ?? "V1.0";
  return {
    label,
    materialTheme: (published ?? draft)?.avatar_config?.material_theme,
    pending: agent.status === "archived",
  };
}

/**
 * Chats in the current course only: the conversations list spans every course
 * the student is in. Agent chats carry agent.course_id, team chats
 * team.course_id; with no current course nothing counts.
 */
export function courseChatCount(
  chats: readonly ConversationSession[],
  courseId: string | undefined,
) {
  if (!courseId) return 0;
  return chats.filter((chat) =>
    "team" in chat && chat.team
      ? chat.team.course_id === courseId
      : "agent" in chat && chat.agent
        ? chat.agent.course_id === courseId
        : false,
  ).length;
}

export function StudentDashboard() {
  const t = useT();
  const { api, identityGeneration, user } = useSession();
  const voiceIdentity = voiceListIdentity(user?.id, identityGeneration);
  const [groups, setGroups] = useState<GroupOverview[]>([]);
  const [published, setPublished] = useState<PublishedAgentSummary[]>([]);
  const [chatCount, setChatCount] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const hasUser = Boolean(user);
  const groupIdsKey = user?.groups
    .map((membership) => membership.group_id)
    .join(",");
  const courseId = user?.courses[0]?.course_id;

  const load = useCallback(async () => {
    if (!hasUser) return;
    setError(null);
    try {
      const groupIds = groupIdsKey ? groupIdsKey.split(",") : [];
      const [overviews, nextPublished, chats] = await Promise.all([
        loadGroups(api, groupIds, voiceIdentity),
        courseId && typeof api.publishedAgents === "function"
          ? cachedCall(api, voiceIdentity, "publishedAgents", [courseId], () =>
              api.publishedAgents(courseId),
            )
          : Promise.resolve([]),
        // "Start the Chat" is done once the student has a chat in this
        // course (the list spans all courses, so it is filtered below). Only the guide uses it,
        // so a failed read leaves the step undone rather than the page.
        typeof api.conversations === "function"
          ? api.conversations().catch(() => [])
          : Promise.resolve([]),
      ]);
      setGroups(overviews);
      setPublished(nextPublished);
      setChatCount(courseChatCount(chats, courseId));
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [api, courseId, groupIdsKey, hasUser, voiceIdentity]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading) return <LoadingCard />;
  if (error)
    return <ErrorNotice inline error={error} onRetry={() => void load()} />;

  const name = user?.display_name ?? "";
  const primary = groups[0];
  const guide = primary
    ? [
        {
          label: t("studentGuideAgent"),
          complete: primary.agentCount > 0,
          href: `/student/agents?group_id=${encodeURIComponent(primary.group.id)}`,
        },
        {
          label: t("studentGuideKnowledge"),
          complete: primary.knowledgeCount > 0,
          href: "/student/knowledge",
        },
        {
          label: t("studentGuideVoice"),
          complete: primary.voiceCount > 0,
          href: `/student/voices?group_id=${encodeURIComponent(primary.group.id)}&mode=new`,
        },
        {
          label: t("studentGuideChat"),
          complete: chatCount > 0,
          href: "/student/chat",
        },
      ]
    : [];

  return (
    <div className={HOME_CLASS}>
      <HomeHero name={name} />
      {published.length ? (
        <section
          className="home-panel grid min-w-0 gap-[26px] max-[767px]:gap-[23px]"
          aria-labelledby="student-agents-title"
        >
          <h2 id="student-agents-title" className={HOME_TAPE_TITLE}>
            {t("agents")} · {published.length}
          </h2>
          <HomeAgentRow>
            {published.map((item, index) => (
              <VersionTile
                key={item.agent.id}
                index={index}
                id={item.agent.id}
                materialTheme={
                  item.current_version.avatar_config?.material_theme
                }
                name={item.agent.name}
                href={`/student/agents/${item.agent.id}`}
                label={item.current_version.version_label}
                pending={false}
                visibility={item.agent.visibility}
                deleteLabel={t("deleteAgent")}
              />
            ))}
          </HomeAgentRow>
        </section>
      ) : null}
      {groups.length === 0 ? (
        <EmptyCard title={t("noGroup")} />
      ) : (
        <div
          className="home-columns grid grid-cols-2 items-stretch gap-8 max-[880px]:grid-cols-1 max-[880px]:gap-10"
          id="student-groups"
        >
          <section
            className={`home-panel ${HOME_CARD_CLASS} shadow-[0_0_0_3px_#67E8F9,8px_8px_0_3px_#111]`}
            aria-labelledby="student-guide-title"
            data-tour="guide"
          >
            <h2 id="student-guide-title" className={HOME_CARD_TITLE}>
              {t("guide")}
            </h2>
            {/* The guide speaks from its gold portrait, as in the tour. */}
            <div className="flex items-start gap-5 max-[680px]:gap-3">
              <GuidePortrait className="size-24 max-[680px]:size-14" />
              <div className="min-w-0 flex-1">
                <HomeGuide steps={guide} />
              </div>
            </div>
          </section>
          {groups.map((overview, index) => (
            <section
              className={`home-panel ${HOME_CARD_CLASS} shadow-[0_0_0_3px_#FDBA74,8px_8px_0_3px_#111]`}
              key={overview.group.id}
              aria-labelledby={`group-${overview.group.id}`}
              data-tour={index === 0 ? "group" : undefined}
            >
              <h2
                id={`group-${overview.group.id}`}
                className={`${HOME_CARD_TITLE} bg-[#67E8F9]`}
              >
                {overview.group.name}
              </h2>
              <ul className="home-people-list m-0 grid list-none border-0 border-t-2 border-[#FFE14D] p-0">
                {(overview.group.members ?? []).map((member) => (
                  <li
                    className="home-person grid min-h-[52px] grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-0 border-b-2 border-dashed border-[#11111133] px-1.5 py-2.5 font-body last:border-b-0"
                    data-role={member.role}
                    key={member.user_id}
                  >
                    <UserAvatar
                      avatar={member.avatar}
                      name={member.display_name}
                      userId={member.user_id}
                      size="sm"
                    />
                    <strong className="min-w-0 truncate text-sm font-semibold">
                      {member.display_name}
                    </strong>
                    {/* roleLabel words, uppercased by CSS as the approved home mock draws them. */}
                    <small
                      className={
                        "rounded border-2 border-ink px-2 py-px font-body text-[11px] font-extrabold text-ink uppercase shadow-[2px_2px_0_#111] " +
                        (member.role === "leader"
                          ? "-rotate-3 bg-[#FF4D8D]"
                          : "rotate-3 bg-[#67E8F9]")
                      }
                    >
                      {roleLabel(member.role)}
                    </small>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      <AccountSettings onSaved={() => void load()} />
    </div>
  );
}

/** The Agents page; ?group_id picks the group, else the first membership. */
export function StudentAgentsPage({ groupId }: { groupId?: string }) {
  const { user } = useSession();
  const target = groupId ?? user?.groups?.[0]?.group_id;
  if (!target) return <LoadingCard />;
  return <GroupWorkspace key={target} groupId={target} view="agents" />;
}

/** Where a group's Teams page lives (sidebar Teams); list, create and edit. */
export function studentTeamsHref(
  groupId: string,
  mode?: "team-new" | "team-edit",
  teamId?: string,
) {
  const params = new URLSearchParams({ group_id: groupId });
  if (mode) params.set("mode", mode);
  if (teamId) params.set("team_id", teamId);
  return `/student/teams?${params.toString()}`;
}

/**
 * The Teams page; ?group_id picks the group, else the first membership.
 * ?mode=team-new / team-edit&team_id open the form; no mode (or the
 * mode=teams TeamEntryFlow leaves behind) is the list.
 */
export function StudentTeamsPage({
  groupId,
  mode,
  teamId,
}: {
  groupId?: string;
  mode?: string;
  teamId?: string;
}) {
  const { user } = useSession();
  const target = groupId ?? user?.groups?.[0]?.group_id;
  if (!target) return <LoadingCard />;
  return (
    <GroupWorkspace
      key={target}
      groupId={target}
      view="teams"
      initialMode={mode}
      initialTeamId={teamId}
    />
  );
}

export function GroupWorkspace({
  groupId,
  initialMode,
  initialTeamId,
  view,
}: {
  /** Split Studyform pages: Agents or Teams. */
  view: "agents" | "teams";
  groupId: string;
  initialMode?: string;
  initialTeamId?: string;
}) {
  const { identityGeneration, user } = useSession();
  const pageMode =
    initialMode === "team-new" || initialMode === "team-edit"
      ? initialMode
      : "";
  const scope = `${user?.id ?? "anonymous"}:${groupId}:${identityGeneration}:${pageMode}:${initialTeamId ?? ""}`;
  return (
    <GroupWorkspaceSession
      key={scope}
      groupId={groupId}
      initialMode={initialMode}
      initialTeamId={initialTeamId}
      scope={scope}
      view={view}
    />
  );
}

function GroupWorkspaceSession({
  view,
  groupId,
  initialMode,
  initialTeamId,
  scope,
}: {
  groupId: string;
  initialMode?: string;
  initialTeamId?: string;
  scope: string;
  view: "agents" | "teams";
}) {
  const t = useT();
  const { api, identityGeneration, user } = useSession();
  const cacheIdentity = requestCacheIdentity(user?.id, identityGeneration);
  const snapshotKey = `page:studyform-group:${groupId}`;
  // A return visit paints the last page this identity saw, then refreshes.
  const [snapshot] = useState(() =>
    peekRequestCache<StudyformGroupSnapshot>(api, cacheIdentity, snapshotKey),
  );
  const [group, setGroup] = useState<GroupDetail | null>(
    snapshot?.group ?? null,
  );
  const [items, setItems] = useState<AgentListItem[]>(snapshot?.items ?? []);
  const [courseAgents, setCourseAgents] = useState<PublishedAgentSummary[]>(
    snapshot?.courseAgents ?? [],
  );
  const [chatAgents, setChatAgents] = useState<ChatAgent[]>(
    snapshot?.chatAgents ?? [],
  );
  const [teams, setTeams] = useState<TeamSummaryDto[]>(snapshot?.teams ?? []);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(!snapshot);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [renameError, setRenameError] = useState<{
    agentId: string;
    error: unknown;
  } | null>(null);
  const renameField = useRef<HTMLInputElement | null>(null);
  const [retryDelete, setRetryDelete] = useState<string | null>(null);
  const mutations = useIdempotencyStore();
  const teacherCourseKey = (user?.courses ?? [])
    .filter((membership) => membership.role === "teacher")
    .map((membership) => membership.course_id)
    .join(",");
  const teacherCourseIds = useMemo(
    () => (teacherCourseKey ? teacherCourseKey.split(",") : []),
    [teacherCourseKey],
  );
  const teacherIdentity = Boolean(
    group &&
    user?.courses.some(
      (membership) =>
        membership.course_id === group.course_id &&
        membership.role === "teacher",
    ),
  );

  const load = useCallback(
    async (background = false) => {
      if (!background) {
        setLoading(true);
        setError(null);
      }
      // The Voices panel mounts only after this page loads; start its list
      // now so it is not a second wait after the first.
      const generation = requestCacheGeneration(api);
      const read = <T,>(
        name: string,
        args: unknown[],
        run: () => Promise<T>,
      ): Promise<T> => cachedCall(api, cacheIdentity, name, args, run);
      try {
        // Two round trips, not four: the group and its Agents together, then
        // the course reads (which need the group's course) beside each
        // Agent's versions.
        const groupRequest = read("group", [groupId], () => api.group(groupId));
        const agentsRequest = read("agents", [groupId, true], () =>
          api.agents(groupId, true),
        );
        if (
          !teacherCourseIds.length &&
          typeof api.courses === "function" &&
          typeof api.knowledge === "function"
        ) {
          // Warm caches used by Agents / Teams tiles.
          // this page loads; warm the same cached reads now so they do not
          // add round trips of their own (same endpoints, same cache keys).
          void read("courses", [], () => api.courses()).catch(() => undefined);
          void read("knowledge", [groupId], () => api.knowledge(groupId)).catch(
            () => undefined,
          );
        }
        if (
          !teacherCourseIds.length &&
          typeof api.myAssessmentAttempts === "function"
        ) {
          // Record's own attempts, warmed beside the group read (Record joins
          // it through the cache instead of asking after the page paints).
          void groupRequest
            .then((nextGroup) =>
              assessmentAttemptsRead(
                api,
                cacheIdentity,
                "own",
                nextGroup.course_id,
              ),
            )
            .catch(() => undefined);
        }
        const courseRequest = groupRequest.then((nextGroup) =>
          Promise.all([
            typeof api.teams === "function"
              ? // A teacher looking round the group asks for this group's
                // Teams, its members' private ones included.
                (() => {
                  const teamGroup = teacherCourseIds.includes(
                    nextGroup.course_id,
                  )
                    ? groupId
                    : undefined;
                  return read("teams", [nextGroup.course_id, teamGroup], () =>
                    api.teams(nextGroup.course_id, teamGroup),
                  );
                })()
              : Promise.resolve([]),
            typeof api.chatAgents === "function"
              ? read("chatAgents", [nextGroup.course_id], () =>
                  api.chatAgents(nextGroup.course_id),
                )
              : Promise.resolve([]),
            typeof api.publishedAgents === "function"
              ? read("publishedAgents", [nextGroup.course_id], () =>
                  api.publishedAgents(nextGroup.course_id),
                )
              : Promise.resolve([]),
          ]),
        );
        const versionsRequest = agentsRequest.then((nextAgents) =>
          Promise.all(
            nextAgents.map((agent) =>
              read("versions", [agent.id], () => api.versions(agent.id)),
            ),
          ),
        );
        const settled = await Promise.allSettled([
          groupRequest,
          agentsRequest,
          courseRequest,
          versionsRequest,
        ]);
        // The group's own answer decides first, as when it was read alone.
        const failed = settled.find((result) => result.status === "rejected");
        if (failed) throw (failed as PromiseRejectedResult).reason;
        const nextGroup = await groupRequest;
        const nextAgents = await agentsRequest;
        const [nextTeams, nextChatAgents, nextPublished] = await courseRequest;
        const versions = await versionsRequest;
        const listedIds = new Set(nextAgents.map((agent) => agent.id));
        const next: StudyformGroupSnapshot = {
          group: nextGroup,
          courseAgents: nextPublished.filter(
            (item) => !listedIds.has(item.agent.id),
          ),
          teams: Array.isArray(nextTeams) ? nextTeams : [],
          chatAgents: Array.isArray(nextChatAgents) ? nextChatAgents : [],
          items: nextAgents.map((agent, index) => ({
            agent,
            versions: versions[index] ?? [],
          })),
        };
        setGroup(next.group);
        setCourseAgents(next.courseAgents);
        setTeams(next.teams);
        setChatAgents(next.chatAgents);
        setItems(next.items);
        rememberRequestCache(api, cacheIdentity, snapshotKey, next, generation);
      } catch (cause) {
        // Busy server during a quiet refresh: keep the page we are showing.
        if (background && isBusyResponse(cause)) return;
        forgetRequestCache(api, cacheIdentity, snapshotKey);
        if (background) {
          // A refusal now (left the group, signed out) must not leave the
          // old page on screen.
          setGroup(null);
          setItems([]);
          setCourseAgents([]);
          setTeams([]);
          setChatAgents([]);
        }
        setError(cause);
      } finally {
        setLoading(false);
      }
    },
    [api, cacheIdentity, groupId, snapshotKey, teacherCourseIds],
  );
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load(Boolean(snapshot));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load, snapshot]);

  if (loading) return <LoadingCard />;
  async function deleteAgent(agentId: string, retry = false) {
    if (deleting || (!retry && !window.confirm(t("deleteAgentConfirm"))))
      return;
    const intent = `agent-delete:${agentId}`;
    const handle = mutations.handleFor(intent);
    setDeleting(agentId);
    setError(null);
    setRetryDelete(null);
    try {
      await api.deleteAgent(agentId, { idempotency: handle });
      mutations.finish(intent, handle);
      invalidateRequestCache(api);
      setItems((current) =>
        current.filter((item) => item.agent.id !== agentId),
      );
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) setRetryDelete(agentId);
      else mutations.abandon(intent, handle);
      setError(cause);
    } finally {
      setDeleting(null);
    }
  }

  async function renameAgent(agentId: string, name: string) {
    const current = items.find((item) => item.agent.id === agentId);
    if (!current) return false;
    setRenameError(null);
    try {
      const saved = await api.updateAgentMetadata(agentId, {
        name,
        expected_metadata_revision: current.agent.metadata_revision,
      });
      invalidateRequestCache(api);
      setItems((list) =>
        list.map((item) =>
          item.agent.id === agentId
            ? {
                ...item,
                agent: {
                  ...item.agent,
                  name: saved.name,
                  metadata_revision: saved.metadata_revision,
                },
              }
            : item,
        ),
      );
      return true;
    } catch (cause) {
      setRenameError({ agentId, error: cause });
      return false;
    }
  }

  async function deleteOwnedTeam(teamId: string) {
    if (
      deleting ||
      teacherIdentity ||
      typeof api.deleteTeam !== "function" ||
      !window.confirm(t("deletePrivateTeamConfirm"))
    )
      return;
    setDeleting(teamId);
    setError(null);
    try {
      await api.deleteTeam(teamId);
      invalidateRequestCache(api);
      setTeams((current) => current.filter((team) => team.id !== teamId));
    } catch (cause) {
      setError(cause);
    } finally {
      setDeleting(null);
    }
  }

  if (!group)
    return (
      <ErrorNotice
        inline
        notFound="groupNotFound"
        error={error ?? new Error(t("groupNotFound"))}
        onRetry={() => void load()}
      />
    );

  // A teacher looking round the group opens its Teams read-only; only the
  // group's students start new ones.
  // The course's shared Agents sit beside the group's own for its students;
  // a teacher looking round the group sees the group's work alone.
  const sharedAgents = teacherIdentity ? [] : courseAgents;
  const teamForm =
    view === "teams" &&
    (initialMode === "team-edit" ||
      (!teacherIdentity && initialMode === "team-new"));
  if (teamForm)
    return (
      <>
        <TeamEntryFlow
          key={scope}
          api={api}
          courseId={group.course_id}
          agents={chatAgents}
          variant="team"
          groupId={groupId}
          standalone
          backHref={studentTeamsHref(groupId)}
          agentCreateHref={
            teacherIdentity
              ? undefined
              : `/student/groups/${groupId}/agents/new`
          }
          initialRouteMode={
            initialMode === "team-new" ? "team-new" : "team-edit"
          }
          initialTeamId={initialTeamId}
        />
      </>
    );

  const agentNotices = (
    <>
      {error ? (
        <ErrorNotice
          error={error}
          onRetry={
            retryDelete ? () => void deleteAgent(retryDelete, true) : undefined
          }
        />
      ) : null}
      {renameError ? (
        <ErrorNotice
          id={`agent-rename-error-${renameError.agentId}`}
          error={renameError.error}
          onClosed={() => {
            const field = renameField.current;
            setRenameError(null);
            field?.focus();
          }}
        />
      ) : null}
    </>
  );
  if (view === "agents")
    return (
      <>
        {agentNotices}
        <AgentsPage
          title={t("agents")}
          action={
            // With no Agents yet, New sits inside the empty card instead.
            teacherIdentity || !(items.length || sharedAgents.length) ? null : (
              <PageAction
                name="new"
                placement="page"
                href={`/student/groups/${groupId}/agents/new`}
                className="bg-[#FF4D8D]"
              />
            )
          }
        >
          {items.length ? (
            <ModuleTiles variant="list">
              {items.map(({ agent, versions }, index) => (
                <GroupAgentRow
                  variant="list"
                  index={index}
                  agent={agent}
                  key={agent.id}
                  versions={versions}
                  deleting={deleting !== null}
                  onDelete={() => void deleteAgent(agent.id)}
                  // Creator; for a public Agent also groupmates and course
                  // teachers (the API answers 404 for everyone else).
                  canDelete={
                    agent.can_delete ??
                    (!teacherIdentity && agent.can_edit === true)
                  }
                  rename={
                    !teacherIdentity && agent.can_edit
                      ? {
                          fieldLabel: t("agentName"),
                          onRename: (name) => renameAgent(agent.id, name),
                          errorId: `agent-rename-error-${agent.id}`,
                          invalid: renameError?.agentId === agent.id,
                          bindInput: (input) => {
                            if (renameError?.agentId === agent.id)
                              renameField.current = input;
                          },
                        }
                      : undefined
                  }
                />
              ))}
              {sharedAgents.map((item, index) => (
                <VersionTile
                  variant="list"
                  index={items.length + index}
                  key={item.agent.id}
                  id={item.agent.id}
                  editedBy={item.agent.last_edited_by_name}
                  materialTheme={
                    item.current_version.avatar_config?.material_theme
                  }
                  name={item.agent.name}
                  href={`/student/agents/${item.agent.id}`}
                  label={item.current_version.version_label}
                  pending={false}
                  visibility={item.agent.visibility}
                  deleteLabel={t("deleteAgent")}
                />
              ))}
            </ModuleTiles>
          ) : sharedAgents.length ? (
            <ModuleTiles variant="list">
              {sharedAgents.map((item, index) => (
                <VersionTile
                  variant="list"
                  index={index}
                  key={item.agent.id}
                  name={item.agent.name}
                  href={`/student/agents/${item.agent.id}`}
                  label={item.current_version.version_label}
                  pending={false}
                  visibility={item.agent.visibility}
                  deleteLabel={t("deleteAgent")}
                />
              ))}
            </ModuleTiles>
          ) : teacherIdentity ? undefined : (
            <AgentsEmpty
              title={t("noAgents")}
              newHref={`/student/groups/${groupId}/agents/new`}
              newLabel={t("newAgent")}
            />
          )}
        </AgentsPage>
      </>
    );

  // /student/teams (where Team Back / Done return): the Teams page.
  if (view === "teams")
    return (
      <TeamsPage
        deleting={deleting !== null}
        newHref={
          teacherIdentity ? undefined : studentTeamsHref(groupId, "team-new")
        }
        teams={teams.map((team) => ({
          team,
          href: studentTeamsHref(groupId, "team-edit", team.id),
          onDelete: team.can_edit
            ? () => void deleteOwnedTeam(team.id)
            : undefined,
        }))}
      />
    );

  return <LoadingCard />;
}

function GroupAgentRow({
  agent,
  versions,
  deleting,
  canDelete = true,
  onDelete,
  rename,
  variant,
  index,
}: {
  variant?: "list";
  /** List position: picks the card tone as the mocks cycle it. */
  index?: number;
  agent: AgentSummary;
  versions: AgentVersion[];
  deleting: boolean;
  canDelete?: boolean;
  onDelete: () => void;
  rename?: AgentRename;
}) {
  const t = useT();
  const bubble = versionBubble(agent, versions);
  return (
    <VersionTile
      id={agent.id}
      rename={rename}
      editedBy={agent.last_edited_by_name}
      materialTheme={bubble.materialTheme}
      name={agent.name}
      href={`/student/agents/${agent.id}`}
      label={bubble.label}
      pending={bubble.pending}
      visibility={agent.visibility}
      deleting={deleting}
      deleteLabel={t("deleteAgent")}
      onDelete={canDelete ? onDelete : undefined}
      variant={variant}
      index={index}
    />
  );
}

export function CreateAgentForm({
  groupId,
  courseId,
  returnHref,
}: {
  groupId?: string;
  courseId?: string;
  /** ?return= from Create/Edit Team; Back and Done go there instead. */
  returnHref?: string;
}) {
  const { identityGeneration, user } = useSession();
  const actorScopeKey = `${user?.id ?? "anonymous"}:${courseId ?? groupId ?? "none"}:${identityGeneration}`;
  return (
    <CreateAgentFormSession
      key={actorScopeKey}
      actorScopeKey={actorScopeKey}
      courseId={courseId}
      groupId={groupId}
      returnHref={safeTeamsReturn(returnHref)}
    />
  );
}

function CreateAgentFormSession({
  groupId,
  courseId,
  actorScopeKey,
  returnHref,
}: {
  groupId?: string;
  courseId?: string;
  returnHref?: string;
  actorScopeKey: string;
}) {
  const { api } = useSession();
  const mutationStore = useIdempotencyStore();
  const mutationIntent = `create-agent:${actorScopeKey}`;

  function abandonCreateIntent() {
    mutationStore.abandon(mutationIntent);
  }

  async function createAgent(name: string, visibility: "private" | "public") {
    const handle = mutationStore.handleFor(mutationIntent);
    try {
      const created = groupId
        ? await api.createAgent(
            groupId,
            name.trim(),
            "",
            { idempotency: handle },
            visibility,
          )
        : await api.createWorkspaceAgent(
            courseId ?? "",
            name.trim(),
            "",
            { idempotency: handle },
            visibility,
          );
      mutationStore.finish(mutationIntent, handle);
      return created;
    } catch (cause) {
      if (!isAmbiguousMutationFailure(cause))
        mutationStore.abandon(mutationIntent, handle);
      throw cause;
    }
  }

  return (
    <AgentWorkbench
      publishOnDone
      backHref={
        returnHref ??
        (groupId ? `/student/agents?group_id=${groupId}` : "/teacher/agents")
      }
      unsavedCreate={{
        groupId,
        courseId,
        create: createAgent,
        onIdentityEdit: abandonCreateIntent,
      }}
    />
  );
}
