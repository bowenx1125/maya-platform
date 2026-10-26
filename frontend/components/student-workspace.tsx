"use client";

import { agentLastEditedTitle } from "../lib/agent-tooltip";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  isAmbiguousMutationFailure,
  type AgentSummary,
  type PublishedAgentSummary,
  type AgentVersion,
  type ChatAgent,
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
import {
  fetchVoiceList,
  prefetchVoiceList,
  voiceListIdentity,
} from "../lib/voice-list-cache";
import { AcademyMascots } from "./academy/mascots";
import { AccountSettings } from "./account-settings";
import { GroupOverview } from "./group-overview";
import { HomeGuide } from "./home-guide";
import { useT } from "../lib/i18n";
import { AgentWorkbench } from "./agent-workspace";
import { useSession } from "./session-provider";
import { UserAvatar } from "./user-avatar";
import { TeamEntryFlow } from "./chats/team-entry-flow";
import { VoiceLibrary } from "./voice/voice-library";
import { BrainformWorkspace } from "./knowledge/brainform-workspace";
import { assessmentAttemptsRead } from "./knowledge/assessment-record";
import {
  ModuleCard,
  ModuleGrid,
  ModulePlus,
  ModuleTiles,
  VersionTile,
  teamVersionLabel,
} from "./studyform-layout";
import {
  AGENT_GRID_CLASS,
  AgentsEmpty,
  NewButton,
  type AgentRename,
} from "./ui/agent-card";
import { GuidePortrait } from "./ui/guide-dialog";
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
} from "./ui";

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

export function StudentDashboard() {
  const t = useT();
  const { api, identityGeneration, user } = useSession();
  const voiceIdentity = voiceListIdentity(user?.id, identityGeneration);
  const [groups, setGroups] = useState<GroupOverview[]>([]);
  const [published, setPublished] = useState<PublishedAgentSummary[]>([]);
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
      const [overviews, nextPublished] = await Promise.all([
        loadGroups(api, groupIds, voiceIdentity),
        courseId && typeof api.publishedAgents === "function"
          ? cachedCall(api, voiceIdentity, "publishedAgents", [courseId], () =>
              api.publishedAgents(courseId),
            )
          : Promise.resolve([]),
      ]);
      setGroups(overviews);
      setPublished(nextPublished);
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
          label: t("studentGuideGroup"),
          complete: true,
          href: `/student/groups/${primary.group.id}`,
        },
        {
          label: t("studentGuideAgent"),
          complete: primary.agentCount > 0,
          href: `/student/groups/${primary.group.id}`,
        },
        {
          label: t("studentGuideKnowledge"),
          complete: primary.knowledgeCount > 0,
          href: "/student/knowledge",
        },
        {
          label: t("studentGuideVoice"),
          complete: primary.voiceCount > 0,
          optional: true,
          href: `/student/groups/${primary.group.id}/voices?mode=new`,
        },
      ]
    : [];

  return (
    <div className="mayaform-home">
      <section className="home-hero">
        <div className="home-hero-copy">
          <h1>{t("homeWelcomeTitle", { name })}</h1>
        </div>
        <div className="home-hero-art">
          <AcademyMascots label={t("academyMascotsLabel")} />
        </div>
      </section>
      {published.length ? (
        <section className="home-panel" aria-labelledby="student-agents-title">
          <h2 id="student-agents-title">
            {t("agents")} · {published.length}
          </h2>
          <ul className={AGENT_GRID_CLASS}>
            {published.map((item) => (
              <VersionTile
                key={item.agent.id}
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
          </ul>
        </section>
      ) : null}
      {groups.length === 0 ? (
        <EmptyCard title={t("noGroup")} />
      ) : (
        <div className="home-columns" id="student-groups">
          <section
            className="home-panel"
            aria-labelledby="student-guide-title"
            data-tour="guide"
          >
            <h2 id="student-guide-title">{t("guide")}</h2>
            {/* The guide speaks from its gold portrait, as in the tour. */}
            <div className="flex items-start gap-5 max-[680px]:gap-3">
              <GuidePortrait />
              <div className="min-w-0 flex-1">
                <HomeGuide steps={guide} />
              </div>
            </div>
          </section>
          {groups.map((overview, index) => (
            <section
              className="home-panel"
              key={overview.group.id}
              aria-labelledby={`group-${overview.group.id}`}
              data-tour={index === 0 ? "group" : undefined}
            >
              <h2 id={`group-${overview.group.id}`}>{overview.group.name}</h2>
              <ul className="home-people-list">
                {(overview.group.members ?? []).map((member) => (
                  <li
                    className="home-person"
                    data-role={member.role}
                    key={member.user_id}
                  >
                    <UserAvatar
                      avatar={member.avatar}
                      name={member.display_name}
                      userId={member.user_id}
                      size="sm"
                    />
                    <strong>{member.display_name}</strong>
                    <small>{roleLabel(member.role)}</small>
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

export function GroupWorkspace({
  groupId,
  initialVoiceCreate = false,
  focusVoices = false,
  initialMode,
  initialTeamId,
  initialDocumentId,
}: {
  groupId: string;
  initialVoiceCreate?: boolean;
  focusVoices?: boolean;
  initialMode?: string;
  initialTeamId?: string;
  /** A RAG file a ?mode=rag-view / rag-edit link opens. */
  initialDocumentId?: string;
}) {
  const { identityGeneration, user } = useSession();
  // Only Team modes swap the page; RAG modes open inside the embedded
  // Brainform cards and must not remount Studyform.
  const pageMode =
    initialMode === "team-new" || initialMode === "team-edit"
      ? initialMode
      : "";
  const scope = `${user?.id ?? "anonymous"}:${groupId}:${identityGeneration}:${pageMode}:${initialTeamId ?? ""}`;
  return (
    <GroupWorkspaceSession
      key={scope}
      groupId={groupId}
      initialVoiceCreate={initialVoiceCreate}
      focusVoices={focusVoices}
      initialMode={initialMode}
      initialTeamId={initialTeamId}
      initialDocumentId={initialDocumentId}
      scope={scope}
    />
  );
}

function GroupWorkspaceSession({
  groupId,
  initialVoiceCreate,
  focusVoices,
  initialMode,
  initialTeamId,
  initialDocumentId,
  scope,
}: {
  groupId: string;
  initialVoiceCreate: boolean;
  focusVoices: boolean;
  initialMode?: string;
  initialTeamId?: string;
  initialDocumentId?: string;
  scope: string;
}) {
  const t = useT();
  // Team modes swap the whole page; any other mode belongs to the embedded
  // RAG / Record cards, which open it as their own page.
  const brainformMode =
    initialMode === "team-new" || initialMode === "team-edit"
      ? undefined
      : initialMode;
  const [brainformPane, setBrainformPane] = useState(false);
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
      prefetchVoiceList(api, cacheIdentity, "group", groupId);
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
          // The RAG and Record cards (Brainform's, embedded) mount after
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

  useEffect(() => {
    if (loading || !(initialVoiceCreate || focusVoices)) return;
    document.getElementById("studyform-voices")?.scrollIntoView({
      block: "start",
    });
  }, [focusVoices, initialVoiceCreate, loading]);

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
    initialMode === "team-edit" ||
    (!teacherIdentity && initialMode === "team-new");
  if (teamForm)
    return (
      <>
        <PageIntro title={t("studyform")} />
        <TeamEntryFlow
          key={scope}
          api={api}
          courseId={group.course_id}
          agents={chatAgents}
          variant="team"
          groupId={groupId}
          standalone
          backHref={`/student/groups/${groupId}`}
          initialRouteMode={
            initialMode === "team-new" ? "team-new" : "team-edit"
          }
          initialTeamId={initialTeamId}
        />
      </>
    );

  return (
    <>
      <PageIntro title={t("studyform")} />
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
      <ModuleGrid
        variant={teacherIdentity ? undefined : "studyform"}
        paneOpen={brainformPane}
      >
        <ModuleCard
          title={t("agents")}
          labelledBy="studyform-agents"
          empty={
            items.length || sharedAgents.length || !teacherIdentity
              ? undefined
              : t("noAgents")
          }
          action={
            // With no Agents yet, New sits inside the empty card instead.
            teacherIdentity || !(items.length || sharedAgents.length) ? null : (
              <NewButton
                href={`/student/groups/${groupId}/agents/new`}
                label={t("newAgent")}
              />
            )
          }
        >
          {items.length ? (
            <ModuleTiles>
              {items.map(({ agent, versions }) => (
                <GroupAgentRow
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
              {sharedAgents.map((item) => (
                <VersionTile
                  key={item.agent.id}
                  id={item.agent.id}
                  editedBy={item.agent.last_edited_by_name}
                  materialTheme={
                    item.current_version.avatar_config?.material_theme
                  }
                  name={item.agent.name}
                  href={`/student/agents/${item.agent.id}`}
                  title={agentLastEditedTitle(
                    t,
                    item.agent,
                    item.current_version.version_label,
                  )}
                  label={item.current_version.version_label}
                  pending={false}
                  visibility={item.agent.visibility}
                  deleteLabel={t("deleteAgent")}
                />
              ))}
            </ModuleTiles>
          ) : sharedAgents.length ? (
            <ModuleTiles>
              {sharedAgents.map((item) => (
                <VersionTile
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
        </ModuleCard>
        <ModuleCard
          title={t("chatTargetTeams")}
          labelledBy="studyform-teams"
          empty={teams.length ? undefined : t("teamNoneYet")}
          action={
            teacherIdentity ? null : (
              <ModulePlus
                href={`/student/groups/${groupId}?mode=team-new`}
                label={t("newAgent")}
              />
            )
          }
        >
          {teams.length ? (
            <ModuleTiles>
              {teams.map((team) => (
                <VersionTile
                  key={team.id}
                  name={team.display_name}
                  href={`/student/groups/${groupId}?mode=team-edit&team_id=${encodeURIComponent(team.id)}`}
                  label={teamVersionLabel(team.current_version_seq)}
                  pending={false}
                  visibility={team.visibility}
                  deleting={deleting !== null}
                  deleteLabel={t("deleteAgent")}
                  onDelete={
                    team.can_edit
                      ? () => void deleteOwnedTeam(team.id)
                      : undefined
                  }
                />
              ))}
            </ModuleTiles>
          ) : undefined}
        </ModuleCard>
        <VoiceLibrary
          id="studyform-voices"
          key={`${scope}:voices:${initialVoiceCreate ? "new" : "list"}:${teacherIdentity ? "listen" : "own"}`}
          groupId={groupId}
          listenOnly={teacherIdentity}
          moduleCard
          initialCreate={teacherIdentity ? false : initialVoiceCreate}
        />
        {/* Owner request (2026-10-20): Brainform's RAG and Record cards
            moved here for students; same component, same API calls. */}
        {teacherIdentity ? null : (
          <BrainformWorkspace
            role="student"
            embedded
            initialGroupId={groupId}
            initialCourseId={group.course_id}
            initialMode={brainformMode}
            initialDocumentId={initialDocumentId}
            onPaneChange={setBrainformPane}
          />
        )}
      </ModuleGrid>
      {/* A visiting teacher also sees who is in the group, how their tests
          went and what happened lately. */}
      {teacherIdentity ? <GroupOverview groupId={groupId} /> : null}
    </>
  );
}

function GroupAgentRow({
  agent,
  versions,
  deleting,
  canDelete = true,
  onDelete,
  rename,
}: {
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
      title={agentLastEditedTitle(t, agent, bubble.label)}
      label={bubble.label}
      pending={bubble.pending}
      visibility={agent.visibility}
      deleting={deleting}
      deleteLabel={t("deleteAgent")}
      onDelete={canDelete ? onDelete : undefined}
    />
  );
}

export function CreateAgentForm({
  groupId,
  courseId,
}: {
  groupId?: string;
  courseId?: string;
}) {
  const { identityGeneration, user } = useSession();
  const actorScopeKey = `${user?.id ?? "anonymous"}:${courseId ?? groupId ?? "none"}:${identityGeneration}`;
  return (
    <CreateAgentFormSession
      key={actorScopeKey}
      actorScopeKey={actorScopeKey}
      courseId={courseId}
      groupId={groupId}
    />
  );
}

function CreateAgentFormSession({
  groupId,
  courseId,
  actorScopeKey,
}: {
  groupId?: string;
  courseId?: string;
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
      backHref={groupId ? `/student/groups/${groupId}` : "/teacher/studyform"}
      unsavedCreate={{
        groupId,
        courseId,
        create: createAgent,
        onIdentityEdit: abandonCreateIntent,
      }}
    />
  );
}
