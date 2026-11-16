"use client";

import { CountUp } from "./count-up";
import { HomeAgentRow } from "./home/agent-row";
import {
  HOME_CLASS,
  HOME_TAPE_TITLE,
  HomeHero,
  HomeStat,
} from "./home/home-hero";
import { AgentCard, AgentsEmpty, agentMascot } from "./ui/agent-card";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import {
  type AgentDetail,
  type AgentSummary,
  type AgentVersion,
  type ChatAgent,
  type Group,
  type GroupDetail,
  type TeamSummaryDto,
  type KnowledgeSnapshot,
  type PublishedAgentSummary,
} from "../lib/api";
import { useT } from "../lib/i18n";
import { useSession } from "./session-provider";
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
import { AccountSettings } from "./account-settings";
import { UserAvatar } from "./user-avatar";
import { AgentWorkbench } from "./agent-workspace";
import { CreateAgentForm } from "./student-workspace";
import { TeamEntryFlow } from "./chats/team-entry-flow";
import { ModuleTiles, VersionTile } from "./studyform-layout";
import { AgentsPage } from "./agents-page";
import { PageAction } from "./page-action";
import { TeamsPage } from "./teams-page";
import { ErrorNotice, LoadingCard } from "./ui";

export function TeacherDashboard() {
  const t = useT();
  const { api, identityGeneration, user } = useSession();
  const teacherMembership = user?.courses.find(
    (item) => item.role === "teacher",
  );
  const teacherCourseId = teacherMembership?.course_id;
  const workspaceScope = `${user?.id ?? "anonymous"}:${teacherCourseId ?? "none"}:${identityGeneration}`;
  const workspaceScopeRef = useRef(workspaceScope);
  useEffect(() => {
    workspaceScopeRef.current = workspaceScope;
  }, [workspaceScope]);
  const [published, setPublished] = useState<PublishedAgentSummary[]>([]);
  const [owned, setOwned] = useState<AgentSummary[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [students, setStudents] = useState<number | null>(null);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(async () => {
    const requestScope = workspaceScope;
    const courseId = teacherCourseId;
    setLoading(true);
    setError(null);
    setStudents(null);
    // The Students count reads the roster on its own, so the page does not
    // wait on it; it shows a dash until it lands.
    if (courseId && typeof api.courseRoster === "function") {
      api
        .courseRoster(courseId)
        .then((roster) => {
          if (workspaceScopeRef.current !== requestScope) return;
          setStudents(
            (roster.entries ?? []).filter(
              (entry) => entry.role === "student" && entry.status === "active",
            ).length,
          );
        })
        .catch((cause: unknown) => {
          if (workspaceScopeRef.current === requestScope) setError(cause);
        });
    }
    try {
      const [nextPublished, nextGroups, nextOwned] = await Promise.all([
        courseId ? api.publishedAgents(courseId) : Promise.resolve([]),
        courseId ? api.groups(courseId) : Promise.resolve([]),
        // The teacher's own agents (as on Studyform): GET
        // /courses/{C}/workspace-agents, minus the ones already published.
        courseId && typeof api.workspaceAgents === "function"
          ? api.workspaceAgents(courseId)
          : Promise.resolve([] as AgentSummary[]),
      ]);
      if (workspaceScopeRef.current !== requestScope) return;
      const publishedIds = new Set(nextPublished.map((item) => item.agent.id));
      setPublished(nextPublished);
      setOwned(nextOwned.filter((agent) => !publishedIds.has(agent.id)));
      setGroups(nextGroups);
    } catch (cause) {
      if (workspaceScopeRef.current === requestScope) setError(cause);
    } finally {
      if (workspaceScopeRef.current === requestScope) {
        setLoadedScope(requestScope);
        setLoading(false);
      }
    }
  }, [api, teacherCourseId, workspaceScope]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading || loadedScope !== workspaceScope) return <LoadingCard />;
  if (error && published.length === 0)
    return <ErrorNotice inline error={error} onRetry={() => void load()} />;
  const name = user?.display_name ?? "";
  return (
    <div className={HOME_CLASS}>
      <HomeHero name={name}>
        {/* A teacher opens this page to read the class: how many groups,
            how many students. The Agents count heads their row below. */}
        <div className="home-stats mt-7 flex flex-wrap gap-5 max-[767px]:gap-3">
          <HomeStat
            tone="lime"
            value={<CountUp value={groups.length} />}
            label={t("groups")}
          />
          <HomeStat
            tone="cyan"
            value={students === null ? "–" : <CountUp value={students} />}
            label={t("homeStudentsCount")}
          />
        </div>
      </HomeHero>
      {error ? <ErrorNotice error={error} /> : null}
      {/* An empty class is just the banner. The old light empty card was a
          leftover under Welcome; creating the first Agent stays on Agents. */}
      {published.length + owned.length > 0 ? (
        <section
          className="published-section grid min-w-0 gap-[26px] max-[767px]:gap-[23px]"
          aria-labelledby="teacher-agents-title"
        >
          <h2 id="teacher-agents-title" className={HOME_TAPE_TITLE}>
            {t("agents")} · {published.length + owned.length}
          </h2>
          <HomeAgentRow>
            {published.map((item, index) => (
              <PublishedAgentCard
                index={index}
                groupName={
                  groups.find((group) => group.id === item.agent.group_id)
                    ?.name ?? ""
                }
                item={item}
                key={item.agent.id}
              />
            ))}
            {owned.map((agent, index) => (
              <AgentCard
                key={agent.id}
                index={published.length + index}
                id={agent.id}
                name={agent.name}
                href={`/teacher/agents/${agent.id}`}
                // Same fallback as Studyform's tile: a draft reads V1.0.
                label="V1.0"
                pending={false}
                visibility={agent.visibility}
                visibilityLabel={t(
                  agent.visibility === "public"
                    ? agent.is_teacher_owned
                      ? "teacherOption"
                      : "publicOption"
                    : "privateOption",
                )}
                mascot={agentMascot(agent.id, undefined)}
                deleteLabel={t("deleteAgent")}
                caption={
                  groups.find((group) => group.id === agent.group_id)?.name ||
                  undefined
                }
              />
            ))}
          </HomeAgentRow>
        </section>
      ) : null}
      <AccountSettings onSaved={() => void load()} />
    </div>
  );
}

/** A published Agent on the teacher's home: who made it, in which group. */
function PublishedAgentCard({
  item,
  groupName,
  index,
}: {
  item: PublishedAgentSummary;
  groupName: string;
  index?: number;
}) {
  const t = useT();
  const hasUnpublishedWork =
    Boolean(item.agent.current_draft_version_id) &&
    item.agent.current_draft_version_id !==
      item.agent.current_published_version_id;
  return (
    <AgentCard
      index={index}
      id={item.agent.id}
      name={item.agent.name}
      href={`/teacher/agents/${item.agent.id}`}
      label={item.current_version.version_label}
      pending={hasUnpublishedWork}
      visibility={item.agent.visibility}
      visibilityLabel={t(
        item.agent.visibility === "public"
          ? item.agent.is_teacher_owned
            ? "teacherOption"
            : "publicOption"
          : "privateOption",
      )}
      mascot={agentMascot(
        item.agent.id,
        item.current_version.avatar_config?.material_theme,
      )}
      deleteLabel={t("deleteAgent")}
      caption={groupName || undefined}
    />
  );
}

type TeacherStudyformSnapshot = {
  personalAgents: PublishedAgentSummary[];
  ownedAgents: AgentSummary[];
  chatAgents: ChatAgent[];
  teams: TeamSummaryDto[];
  groups: Group[];
};

export function TeacherStudyformWorkspace({
  initialGroupId,
  initialMode,
  initialTeamId,
  view,
}: {
  /** Split Studyform pages: Agents or Teams. */
  view: "agents" | "teams";
  initialGroupId?: string;
  initialMode?: string;
  initialTeamId?: string;
}) {
  const t = useT();
  const { api, identityGeneration, user } = useSession();
  const teacherCourseId = user?.courses.find(
    (membership) => membership.role === "teacher",
  )?.course_id;
  const teamMode =
    view === "teams" &&
    (initialMode === "team-new" ||
      initialMode === "team-edit" ||
      initialMode === "maya-new" ||
      initialMode === "maya-edit");
  const pageMode = teamMode ? initialMode : "";
  const scope = `${user?.id ?? "anonymous"}:${teacherCourseId ?? "none"}:${initialGroupId ?? "all"}:${pageMode}:${initialTeamId ?? ""}:${identityGeneration}`;
  const cacheIdentity = requestCacheIdentity(user?.id, identityGeneration);
  const snapshotKey = `page:studyform-teacher:${teacherCourseId ?? "none"}`;
  // A return visit paints the last page this identity saw, then refreshes.
  const [snapshot] = useState(() =>
    teacherCourseId
      ? peekRequestCache<TeacherStudyformSnapshot>(
          api,
          cacheIdentity,
          snapshotKey,
        )
      : undefined,
  );
  const [personalAgents, setPersonalAgents] = useState<PublishedAgentSummary[]>(
    snapshot?.personalAgents ?? [],
  );
  const [ownedAgents, setOwnedAgents] = useState<AgentSummary[]>(
    snapshot?.ownedAgents ?? [],
  );
  const [chatAgents, setChatAgents] = useState<ChatAgent[]>(
    snapshot?.chatAgents ?? [],
  );
  const [teams, setTeams] = useState<TeamSummaryDto[]>(snapshot?.teams ?? []);
  const [groups, setGroups] = useState<Group[]>(snapshot?.groups ?? []);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [loadedScope, setLoadedScope] = useState<string | null>(
    snapshot ? scope : null,
  );
  const paintedScope = useRef<string | null>(snapshot ? scope : null);
  const loading = loadedScope !== scope;
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let active = true;
    const requestScope = scope;
    // Painted from a snapshot: refresh quietly instead of blanking.
    const background = paintedScope.current === requestScope;
    paintedScope.current = null;
    const timer = window.setTimeout(() => {
      if (!background) setError(null);
      if (!teacherCourseId) {
        setPersonalAgents([]);
        setOwnedAgents([]);
        setChatAgents([]);
        setTeams([]);
        setGroups([]);
        setLoadedScope(requestScope);
        return;
      }
      const generation = requestCacheGeneration(api);
      const courseId = teacherCourseId;
      const read = <T,>(
        name: string,
        run: () => Promise<T>,
        args: unknown[] = [courseId],
      ): Promise<T> => cachedCall(api, cacheIdentity, name, args, run);
      void Promise.all([
        typeof api.publishedAgents === "function"
          ? read("publishedAgents", () => api.publishedAgents(courseId))
          : Promise.resolve([]),
        read("chatAgents", () => api.chatAgents(courseId)),
        typeof api.teams === "function"
          ? read("teams", () => api.teams(courseId), [courseId, undefined])
          : Promise.resolve([]),
        typeof api.workspaceAgents === "function"
          ? read("workspaceAgents", () => api.workspaceAgents(courseId))
          : Promise.resolve([]),
        // Group names only label the cards; without them the cards still work.
        typeof api.groups === "function"
          ? read("groups", () => api.groups(courseId)).catch(() => [])
          : Promise.resolve([]),
      ])
        .then(
          ([
            nextPersonalAgents,
            nextChatAgents,
            nextTeams,
            nextOwned,
            nextGroups,
          ]) => {
            if (!active) return;
            const publishedIds = new Set(
              nextPersonalAgents.map((item) => item.agent.id),
            );
            const next: TeacherStudyformSnapshot = {
              personalAgents: nextPersonalAgents,
              ownedAgents: nextOwned.filter(
                (agent) => !publishedIds.has(agent.id),
              ),
              chatAgents: nextChatAgents,
              teams: nextTeams,
              groups: nextGroups,
            };
            setPersonalAgents(next.personalAgents);
            setOwnedAgents(next.ownedAgents);
            setChatAgents(next.chatAgents);
            setTeams(next.teams);
            setGroups(next.groups);
            setLoadedScope(requestScope);
            setError(null);
            rememberRequestCache(
              api,
              cacheIdentity,
              snapshotKey,
              next,
              generation,
            );
          },
        )
        .catch((cause) => {
          if (!active) return;
          // Busy server during a quiet refresh: keep the page on screen.
          if (background && isBusyResponse(cause)) return;
          forgetRequestCache(api, cacheIdentity, snapshotKey);
          if (background) {
            setPersonalAgents([]);
            setOwnedAgents([]);
            setChatAgents([]);
            setTeams([]);
          }
          setError(cause);
          setLoadedScope(requestScope);
        });
    }, 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [api, cacheIdentity, initialGroupId, scope, snapshotKey, teacherCourseId]);

  async function deletePersonalAgent(agentId: string) {
    if (deletingId || !window.confirm(t("deleteAgentConfirm"))) return;
    setDeletingId(agentId);
    setError(null);
    try {
      await api.deleteAgent(agentId);
      invalidateRequestCache(api);
      setPersonalAgents((current) =>
        current.filter((item) => item.agent.id !== agentId),
      );
      setOwnedAgents((current) =>
        current.filter((agent) => agent.id !== agentId),
      );
    } catch (cause) {
      setError(cause);
    } finally {
      setDeletingId(null);
    }
  }

  async function deleteOwnedTeam(teamId: string, confirmMessage: string) {
    if (deletingId || !window.confirm(confirmMessage)) return;
    setDeletingId(teamId);
    setError(null);
    try {
      await api.deleteTeam(teamId);
      invalidateRequestCache(api);
      setTeams((current) => current.filter((team) => team.id !== teamId));
    } catch (cause) {
      setError(cause);
    } finally {
      setDeletingId(null);
    }
  }

  if (loading || loadedScope !== scope) return <LoadingCard />;
  if (
    error &&
    !personalAgents.length &&
    !ownedAgents.length &&
    !chatAgents.length
  )
    return <ErrorNotice inline error={error} />;

  const teamForm = teamMode;
  if (teamForm)
    return (
      <>
        {teacherCourseId ? (
          <TeamEntryFlow
            key={scope}
            api={api}
            courseId={teacherCourseId ?? null}
            agents={chatAgents}
            variant="team"
            standalone
            backHref="/teacher/teams"
            agentCreateHref="/teacher/agents/new"
            initialRouteMode={
              initialMode === "team-new" || initialMode === "maya-new"
                ? "team-new"
                : "team-edit"
            }
            initialTeamId={initialTeamId}
          />
        ) : null}
      </>
    );

  if (view === "agents")
    return (
      <>
        {error ? <ErrorNotice error={error} /> : null}
        <AgentsPage
          title={t("agents")}
          action={
            // With no Agents yet, New sits inside the empty card instead.
            teacherCourseId && (personalAgents.length || ownedAgents.length) ? (
              <PageAction
                name="new"
                placement="page"
                href="/teacher/agents/new"
              />
            ) : null
          }
        >
          {personalAgents.length || ownedAgents.length ? (
            <ModuleTiles variant="list">
              {personalAgents.map((item, index) => (
                <VersionTile
                  variant="list"
                  index={index}
                  editedBy={item.agent.last_edited_by_name}
                  group={item.group_name}
                  key={item.agent.id}
                  name={item.agent.name}
                  href={`/teacher/agents/${item.agent.id}`}
                  label={item.current_version.version_label}
                  pending={false}
                  visibility={item.agent.visibility}
                  isTeacherOwned={item.agent.is_teacher_owned === true}
                  deleting={deletingId !== null}
                  deleteLabel={t("deleteAgent")}
                  onDelete={
                    (item.agent.can_delete ?? item.author?.user_id === user?.id)
                      ? () => void deletePersonalAgent(item.agent.id)
                      : undefined
                  }
                />
              ))}
              {ownedAgents.map((agent, index) => {
                // Same fallback as a student's own tile: a draft reads V1.0.
                const label =
                  chatAgents.find((item) => item.agent_id === agent.id)
                    ?.version_label ?? "V1.0";
                return (
                  <VersionTile
                    variant="list"
                    index={personalAgents.length + index}
                    editedBy={agent.last_edited_by_name}
                    group={
                      groups.find((group) => group.id === agent.group_id)?.name
                    }
                    key={agent.id}
                    name={agent.name}
                    href={`/teacher/agents/${agent.id}`}
                    label={label}
                    pending={false}
                    visibility={agent.visibility}
                    isTeacherOwned={agent.is_teacher_owned === true}
                    deleting={deletingId !== null}
                    deleteLabel={t("deleteAgent")}
                    onDelete={
                      agent.can_edit !== false
                        ? () => void deletePersonalAgent(agent.id)
                        : undefined
                    }
                  />
                );
              })}
            </ModuleTiles>
          ) : (
            <AgentsEmpty
              title={t("noPersonalAgents")}
              newHref={teacherCourseId ? "/teacher/agents/new" : undefined}
              newLabel={t("newAgent")}
            />
          )}
        </AgentsPage>
      </>
    );

  // /teacher/teams (where Team Back / Done return): the Teams page.
  if (view === "teams")
    return (
      <>
        {error ? <ErrorNotice error={error} /> : null}
        <TeamsPage
          deleting={deletingId !== null}
          newHref={teacherCourseId ? "/teacher/teams?mode=team-new" : undefined}
          teams={teams.map((team) => ({
            team,
            href: `/teacher/teams?mode=team-edit&team_id=${encodeURIComponent(team.id)}`,
            onDelete: team.can_edit
              ? () =>
                  void deleteOwnedTeam(team.id, t("deletePrivateTeamConfirm"))
              : undefined,
          }))}
        />
      </>
    );

  return <LoadingCard />;
}

export function TeacherPersonalAgentCreate({
  returnHref,
}: {
  /** ?return= from Create/Edit Team (Teams paths only). */
  returnHref?: string;
} = {}) {
  const t = useT();
  const { identityGeneration, user } = useSession();
  const teacherMembership = user?.courses.find(
    (item) => item.role === "teacher",
  );
  if (!user || !teacherMembership) {
    return <ErrorNotice inline error={new Error(t("courseNotFound"))} />;
  }
  const scopeKey = `${user.id}:${teacherMembership.course_id}:${identityGeneration}`;
  return (
    <CreateAgentForm
      key={scopeKey}
      courseId={teacherMembership.course_id}
      returnHref={returnHref}
    />
  );
}

export function TeacherAgentDetail({
  agentId,
  snapshotId,
  generationFlow = false,
  generationSetId,
}: {
  agentId: string;
  snapshotId?: string;
  generationFlow?: boolean;
  generationSetId?: string;
}) {
  const t = useT();
  const { api, identityGeneration, user } = useSession();
  const actorScope = `${user?.id ?? "anonymous"}:${agentId}:${identityGeneration}`;
  const loadScope = `${actorScope}:${generationSetId ?? "no-generation-set"}`;
  const loadScopeRef = useRef(loadScope);
  const actorScopeRef = useRef(actorScope);
  useLayoutEffect(() => {
    loadScopeRef.current = loadScope;
    actorScopeRef.current = actorScope;
  }, [actorScope, loadScope]);
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [group, setGroup] = useState<GroupDetail | null>(null);
  const [versions, setVersions] = useState<AgentVersion[]>([]);
  const [snapshot, setSnapshot] = useState<KnowledgeSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [verifiedGenerationSetId, setVerifiedGenerationSetId] = useState<
    string | null
  >(null);
  const load = useCallback(async () => {
    const requestScope = loadScope;
    setLoading(true);
    setError(null);
    setSnapshot(null);
    try {
      const nextAgent = await api.agent(agentId);
      if (
        actorScopeRef.current !== actorScope ||
        loadScopeRef.current !== requestScope
      )
        return;
      const [nextVersions, nextGroup] = await Promise.all([
        api.versions(agentId),
        nextAgent.group_id && typeof api.group === "function"
          ? api.group(nextAgent.group_id)
          : Promise.resolve(null),
      ]);
      if (
        actorScopeRef.current !== actorScope ||
        loadScopeRef.current !== requestScope
      )
        return;
      const generationSet = generationSetId
        ? await api.knowledgeSet(generationSetId)
        : null;
      if (
        actorScopeRef.current !== actorScope ||
        loadScopeRef.current !== requestScope
      )
        return;
      const verifiedGenerationSet =
        generationSet &&
        generationSet.id === generationSetId &&
        generationSet.course_id === nextAgent.course_id &&
        generationSet.can_edit &&
        generationSet.owner_user_id === user?.id &&
        generationSet.generated_by_agent_id === agentId
          ? generationSetId
          : null;
      setVerifiedGenerationSetId(verifiedGenerationSet);
      setAgent(nextAgent);
      setGroup(nextGroup);
      const visibleVersions =
        nextAgent.ownership_scope === "personal"
          ? nextVersions
          : nextVersions.filter((version) => version.state !== "draft");
      setVersions(visibleVersions);
      const selectedSnapshotId =
        snapshotId ||
        nextVersions.find(
          (version) => version.id === nextAgent.current_published_version_id,
        )?.knowledge_snapshot_id ||
        null;
      if (selectedSnapshotId) {
        const nextSnapshot = await api.snapshot(selectedSnapshotId);
        if (
          actorScopeRef.current !== actorScope ||
          loadScopeRef.current !== requestScope
        )
          return;
        setSnapshot(nextSnapshot);
      } else setSnapshot(null);
    } catch (cause) {
      if (
        actorScopeRef.current === actorScope &&
        loadScopeRef.current === requestScope
      )
        setError(cause);
    } finally {
      if (
        actorScopeRef.current === actorScope &&
        loadScopeRef.current === requestScope
      ) {
        setLoadedScope(requestScope);
        setLoading(false);
      }
    }
  }, [actorScope, agentId, api, generationSetId, loadScope, snapshotId, user]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading || loadedScope !== loadScope) return <LoadingCard />;
  if (error || !agent)
    return (
      <ErrorNotice
        inline
        notFound="publishedAgentNotFound"
        error={error ?? new Error(t("publishedAgentNotFound"))}
        onRetry={() => void load()}
      />
    );
  if (generationSetId && verifiedGenerationSetId !== generationSetId) {
    return (
      <ErrorNotice inline error={new Error(t("generatedSetAgentMismatch"))} />
    );
  }
  const currentAgent = agent;
  const editorVersion =
    versions.find(
      (version) => version.id === agent.current_published_version_id,
    ) ?? versions.find((version) => version.state === "draft");
  const editable =
    agent.can_edit === true ||
    (agent.can_edit == null && agent.ownership_scope === "personal");
  if (editable && !snapshotId && editorVersion) {
    const knowledgeHref = generationSetId
      ? `/teacher/knowledge?agent_id=${encodeURIComponent(agentId)}&set_id=${encodeURIComponent(generationSetId)}`
      : `/teacher/knowledge?agent_id=${encodeURIComponent(agentId)}`;
    return (
      <AgentWorkbench
        key={`${actorScope}:${editorVersion.id}`}
        actorScopeKey={actorScope}
        backHref="/teacher/agents"
        knowledgeHref={knowledgeHref}
        generationFlow={generationFlow}
        publishOnDone
        versionId={editorVersion.id}
      />
    );
  }
  const selectedVersion = snapshotId
    ? (versions.find(
        (version) => version.knowledge_snapshot_id === snapshotId,
      ) ?? editorVersion)
    : editorVersion;

  if (snapshotId && snapshot?.id !== snapshotId) return <LoadingCard />;
  if (!selectedVersion) {
    return (
      <ErrorNotice inline error={new Error(t("publishedAgentNotFound"))} />
    );
  }
  return <ErrorNotice inline error={new Error(t("publishedAgentNotFound"))} />;
}
