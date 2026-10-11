"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

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
import { AcademyMascots } from "./academy/mascots";
import { AccountSettings } from "./account-settings";
import { HomeGuide } from "./home-guide";
import { OnboardingTour } from "./onboarding-tour";
import { useLocale, useT } from "./locale";
import { AgentWorkbench } from "./agent-workspace";
import { useSession } from "./session-provider";
import { UserAvatar } from "./user-avatar";
import { TeamEntryFlow } from "./chats/team-entry-flow";
import { VoiceLibrary } from "./voice/voice-library";
import {
  ModuleCard,
  ModuleGrid,
  ModulePlus,
  ModuleTiles,
  VersionTile,
} from "./studyform-layout";
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

async function loadGroups(
  api: PlatformApi,
  groupIds: string[],
): Promise<GroupOverview[]> {
  return Promise.all(
    groupIds.map(async (groupId) => {
      const [group, agents, knowledge, voices] = await Promise.all([
        api.group(groupId),
        api.agents(groupId, true),
        api.knowledge(groupId),
        api.voiceProfiles(groupId),
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
    pending: agent.status === "archived",
  };
}

export function StudentDashboard() {
  const t = useT();
  const { locale } = useLocale();
  const { api, user } = useSession();
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
        loadGroups(api, groupIds),
        courseId && typeof api.publishedAgents === "function"
          ? api.publishedAgents(courseId)
          : Promise.resolve([]),
      ]);
      setGroups(overviews);
      setPublished(nextPublished);
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [api, courseId, groupIdsKey, hasUser]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading) return <LoadingCard />;
  if (error) return <ErrorNotice error={error} onRetry={() => void load()} />;

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
          <div className="agent-tile-grid">
            {published.map((item) => (
              <VersionTile
                key={item.agent.id}
                name={item.agent.name}
                href={`/student/agents/${item.agent.id}`}
                label={item.current_version.version_label}
                pending={false}
                deleteLabel={t("deleteAgent")}
              />
            ))}
          </div>
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
            <HomeGuide steps={guide} />
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
                    <small>{roleLabel(member.role, locale)}</small>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      <AccountSettings onSaved={() => void load()} />
      {user ? <OnboardingTour userId={user.id} /> : null}
    </div>
  );
}

export function GroupWorkspace({
  groupId,
  initialVoiceCreate = false,
  focusVoices = false,
  initialMode,
  initialTeamId,
}: {
  groupId: string;
  initialVoiceCreate?: boolean;
  focusVoices?: boolean;
  initialMode?: string;
  initialTeamId?: string;
}) {
  const { identityGeneration, user } = useSession();
  const scope = `${user?.id ?? "anonymous"}:${groupId}:${identityGeneration}:${initialMode ?? ""}:${initialTeamId ?? ""}`;
  return (
    <GroupWorkspaceSession
      key={scope}
      groupId={groupId}
      initialVoiceCreate={initialVoiceCreate}
      focusVoices={focusVoices}
      initialMode={initialMode}
      initialTeamId={initialTeamId}
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
  scope,
}: {
  groupId: string;
  initialVoiceCreate: boolean;
  focusVoices: boolean;
  initialMode?: string;
  initialTeamId?: string;
  scope: string;
}) {
  const t = useT();
  const { api, user } = useSession();
  const [group, setGroup] = useState<GroupDetail | null>(null);
  const [items, setItems] = useState<AgentListItem[]>([]);
  const [courseAgents, setCourseAgents] = useState<PublishedAgentSummary[]>([]);
  const [chatAgents, setChatAgents] = useState<ChatAgent[]>([]);
  const [teams, setTeams] = useState<TeamSummaryDto[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [retryDelete, setRetryDelete] = useState<string | null>(null);
  const mutations = useIdempotencyStore();
  const teacherIdentity = Boolean(
    group &&
    user?.courses.some(
      (membership) =>
        membership.course_id === group.course_id &&
        membership.role === "teacher",
    ),
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextGroup = await api.group(groupId);
      const [nextAgents, nextTeams, nextChatAgents] = await Promise.all([
        api.agents(groupId, true),
        typeof api.teams === "function"
          ? api.teams(nextGroup.course_id)
          : Promise.resolve([]),
        typeof api.chatAgents === "function"
          ? api.chatAgents(nextGroup.course_id)
          : Promise.resolve([]),
      ]);
      const versions = await Promise.all(
        nextAgents.map((agent) => api.versions(agent.id)),
      );
      const listedIds = new Set(nextAgents.map((agent) => agent.id));
      const nextCourseAgents =
        typeof api.publishedAgents === "function"
          ? await api.publishedAgents(nextGroup.course_id)
          : [];
      setGroup(nextGroup);
      setCourseAgents(
        nextCourseAgents.filter((item) => !listedIds.has(item.agent.id)),
      );
      setTeams(Array.isArray(nextTeams) ? nextTeams : []);
      setChatAgents(Array.isArray(nextChatAgents) ? nextChatAgents : []);
      setItems(
        nextAgents.map((agent, index) => ({
          agent,
          versions: versions[index] ?? [],
        })),
      );
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [api, groupId]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

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
        error={error ?? new Error(t("groupNotFound"))}
        onRetry={() => void load()}
      />
    );

  const teamForm =
    !teacherIdentity &&
    (initialMode === "team-new" || initialMode === "team-edit");
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
      <ModuleGrid>
        <ModuleCard
          title={t("agents")}
          labelledBy="studyform-agents"
          empty={
            items.length || courseAgents.length ? undefined : t("noAgents")
          }
          action={
            teacherIdentity ? null : (
              <ModulePlus
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
                  canDelete={!teacherIdentity}
                />
              ))}
              {courseAgents.map((item) => (
                <VersionTile
                  key={item.agent.id}
                  name={item.agent.name}
                  href={`/student/agents/${item.agent.id}`}
                  label={item.current_version.version_label}
                  pending={false}
                  deleteLabel={t("deleteAgent")}
                />
              ))}
            </ModuleTiles>
          ) : courseAgents.length ? (
            <ModuleTiles>
              {courseAgents.map((item) => (
                <VersionTile
                  key={item.agent.id}
                  name={item.agent.name}
                  href={`/student/agents/${item.agent.id}`}
                  label={item.current_version.version_label}
                  pending={false}
                  deleteLabel={t("deleteAgent")}
                />
              ))}
            </ModuleTiles>
          ) : undefined}
        </ModuleCard>
        {teacherIdentity ? null : (
          <ModuleCard
            title={t("chatTargetTeams")}
            labelledBy="studyform-teams"
            empty={teams.length ? undefined : t("teamNoneYet")}
            action={
              <ModulePlus
                href={`/student/groups/${groupId}?mode=team-new`}
                label={t("newAgent")}
              />
            }
          >
            {teams.length ? (
              <ModuleTiles>
                {teams.map((team) => (
                  <VersionTile
                    key={team.id}
                    name={team.display_name}
                    href={`/student/groups/${groupId}?mode=team-edit&team_id=${encodeURIComponent(team.id)}`}
                    label={t("teamVersionLabel", {
                      seq: team.current_version_seq,
                    })}
                    pending={false}
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
        )}
        <VoiceLibrary
          id="studyform-voices"
          key={`${scope}:voices:${initialVoiceCreate ? "new" : "list"}:${teacherIdentity ? "listen" : "own"}`}
          groupId={groupId}
          listenOnly={teacherIdentity}
          embedded
          initialCreate={teacherIdentity ? false : initialVoiceCreate}
        />
      </ModuleGrid>
    </>
  );
}

function GroupAgentRow({
  agent,
  versions,
  deleting,
  canDelete = true,
  onDelete,
}: {
  agent: AgentSummary;
  versions: AgentVersion[];
  deleting: boolean;
  canDelete?: boolean;
  onDelete: () => void;
}) {
  const t = useT();
  const bubble = versionBubble(agent, versions);
  return (
    <VersionTile
      name={agent.name}
      href={`/student/agents/${agent.id}`}
      label={bubble.label}
      pending={bubble.pending}
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
