"use client";

import { agentLastEditedTitle } from "../lib/agent-tooltip";
import { CountUp } from "./count-up";
import { HomeGuide } from "./home-guide";

import Link from "next/link";
import { FitTitle } from "./fit-title";
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
  type Course,
  type Group,
  type GroupDetail,
  type TeamSummaryDto,
  type KnowledgeSnapshot,
  type PublishedAgentSummary,
} from "../lib/api";
import { prefetchVoiceList } from "../lib/voice-list-cache";
import { useT } from "./locale";
import { IconClose } from "./quiet-icons";
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
import { AcademyMascots } from "./academy/mascots";
import { AccountSettings } from "./account-settings";
import { UserAvatar } from "./user-avatar";
import { AgentReadOnly, AgentWorkbench } from "./agent-workspace";
import { CreateAgentForm } from "./student-workspace";
import { TeamEntryFlow } from "./chats/team-entry-flow";
import { BrainformWorkspace } from "./knowledge/brainform-workspace";
import {
  ModuleCard,
  ModuleGrid,
  ModulePlus,
  ModuleTiles,
  VersionTile,
  teamVersionLabel,
} from "./studyform-layout";
import { VoiceLibrary } from "./voice/voice-library";
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
} from "./ui";

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
  const [course, setCourse] = useState<Course | null>(null);
  const [published, setPublished] = useState<PublishedAgentSummary[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const [debateCount, setDebateCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const load = useCallback(async () => {
    const requestScope = workspaceScope;
    setLoading(true);
    setError(null);
    try {
      const courses = await api.courses();
      if (workspaceScopeRef.current !== requestScope) return;
      const courseId = teacherCourseId;
      const [nextPublished, nextGroups, debates] = await Promise.all([
        courseId ? api.publishedAgents(courseId) : Promise.resolve([]),
        courseId ? api.groups(courseId) : Promise.resolve([]),
        courseId ? api.debates(courseId) : Promise.resolve([]),
      ]);
      if (workspaceScopeRef.current !== requestScope) return;
      setCourse(
        courses.find((item) => item.id === courseId) ?? courses[0] ?? null,
      );
      setPublished(nextPublished);
      setGroups(nextGroups);
      setDebateCount(debates.length);
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

  async function deleteAgent(agentId: string) {
    if (deleting || !window.confirm(t("deleteAgentConfirm"))) return;
    const requestScope = workspaceScope;
    setDeleting(agentId);
    setError(null);
    try {
      await api.deleteAgent(agentId);
      if (workspaceScopeRef.current !== requestScope) return;
      setPublished((current) =>
        current.filter((item) => item.agent.id !== agentId),
      );
    } catch (cause) {
      if (workspaceScopeRef.current === requestScope) setError(cause);
    } finally {
      if (workspaceScopeRef.current === requestScope) setDeleting(null);
    }
  }

  if (loading || loadedScope !== workspaceScope) return <LoadingCard />;
  if (error && published.length === 0)
    return <ErrorNotice inline error={error} onRetry={() => void load()} />;
  const name = user?.display_name ?? "";
  const guide = [
    {
      label: t("teacherGuideCourse"),
      complete: Boolean(course),
      href: "/teacher/roster",
    },
    {
      label: t("teacherGuideGroups"),
      complete: groups.length > 0,
      href: "/teacher/roster",
    },
    {
      label: t("teacherGuideAgents"),
      complete: published.length > 0,
      href: "/teacher/studyform",
    },
    {
      label: t("teacherGuideDebate"),
      complete: debateCount > 0,
      href: "/teacher/debates/new",
    },
  ];
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
      {/* A teacher opens this page to read the class, not their own progress,
          so the counts come before the guide. A student has one group and
          needs no such summary, which is what keeps the two homes apart. */}
      <div className="home-stats">
        <div className="home-stat">
          <b>
            <CountUp value={groups.length} />
          </b>
          <span>{t("groups")}</span>
        </div>
        <div className="home-stat">
          <b>
            <CountUp value={published.length} />
          </b>
          <span>{t("agents")}</span>
        </div>
        <div className="home-stat">
          <b>
            <CountUp value={debateCount} />
          </b>
          {/* `debates` is the nav's own word for the section ("Classroom"),
              which reads wrong over a number; `debateList` is the plural
              noun. */}
          <span>{t("debateList")}</span>
        </div>
      </div>
      <section className="home-panel" aria-labelledby="teacher-guide-title">
        <h2 id="teacher-guide-title">{t("guide")}</h2>
        <HomeGuide steps={guide} />
      </section>
      {error ? <ErrorNotice error={error} /> : null}
      {published.length === 0 ? (
        <EmptyCard title={t("noPublishedAgents")} />
      ) : (
        <SectionCard
          title={`${t("agents")} · ${published.length}`}
          className="published-section"
        >
          <div className="agent-tile-grid">
            {published.map((item) => (
              <PublishedAgentTile
                groupName={
                  groups.find((group) => group.id === item.agent.group_id)
                    ?.name ?? ""
                }
                item={item}
                key={item.agent.id}
                deleting={deleting !== null}
                onDelete={
                  // Only the publisher may delete; other viewers see the
                  // version pill without the × (the API rejects them).
                  item.author?.user_id === user?.id
                    ? () => void deleteAgent(item.agent.id)
                    : undefined
                }
              />
            ))}
          </div>
        </SectionCard>
      )}
      <AccountSettings onSaved={() => void load()} />
    </div>
  );
}

type TeacherStudyformSnapshot = {
  personalAgents: PublishedAgentSummary[];
  ownedAgents: AgentSummary[];
  chatAgents: ChatAgent[];
  teams: TeamSummaryDto[];
};

export function TeacherStudyformWorkspace({
  initialGroupId,
  initialMode,
  initialTeamId,
  initialDocumentId,
}: {
  initialGroupId?: string;
  initialMode?: string;
  initialTeamId?: string;
  /** A RAG file a ?mode=rag-view / rag-edit link opens. */
  initialDocumentId?: string;
}) {
  const t = useT();
  const { api, identityGeneration, user } = useSession();
  const teacherCourseId = user?.courses.find(
    (membership) => membership.role === "teacher",
  )?.course_id;
  // Owner request (2026-10-20): the teacher's Brainform cards (RAG,
  // Knowledge, Record) joined Studyform. Only Team modes swap the page; any
  // other mode belongs to the embedded cards and must not reload Studyform.
  const teamMode =
    initialMode === "team-new" ||
    initialMode === "team-edit" ||
    initialMode === "maya-new" ||
    initialMode === "maya-edit";
  const pageMode = teamMode ? initialMode : "";
  const brainformMode = teamMode ? undefined : initialMode;
  const [brainformPane, setBrainformPane] = useState(false);
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
        setLoadedScope(requestScope);
        return;
      }
      // The Voices panel mounts only after this page loads; start its list
      // now so it is not a second wait after the first.
      prefetchVoiceList(api, cacheIdentity, "personal", teacherCourseId);
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
      ])
        .then(([nextPersonalAgents, nextChatAgents, nextTeams, nextOwned]) => {
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
          };
          setPersonalAgents(next.personalAgents);
          setOwnedAgents(next.ownedAgents);
          setChatAgents(next.chatAgents);
          setTeams(next.teams);
          setLoadedScope(requestScope);
          setError(null);
          rememberRequestCache(
            api,
            cacheIdentity,
            snapshotKey,
            next,
            generation,
          );
        })
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
        <PageIntro title={t("studyform")} />
        {teacherCourseId ? (
          <TeamEntryFlow
            key={scope}
            api={api}
            courseId={teacherCourseId ?? null}
            agents={chatAgents}
            variant="team"
            standalone
            backHref="/teacher/studyform"
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

  return (
    <>
      <PageIntro title={t("studyform")} />
      {error ? <ErrorNotice error={error} /> : null}
      <ModuleGrid variant="teacherStudyform" paneOpen={brainformPane}>
        <ModuleCard
          title={t("agents")}
          labelledBy="studyform-agents"
          empty={
            personalAgents.length || ownedAgents.length
              ? undefined
              : t("noPersonalAgents")
          }
          action={
            teacherCourseId ? (
              <ModulePlus href="/teacher/agents/new" label={t("newAgent")} />
            ) : null
          }
        >
          {personalAgents.length || ownedAgents.length ? (
            <ModuleTiles>
              {personalAgents.map((item) => (
                <VersionTile
                  key={item.agent.id}
                  name={item.agent.name}
                  href={`/teacher/agents/${item.agent.id}`}
                  title={agentLastEditedTitle(
                    t,
                    item.agent,
                    item.current_version.version_label,
                  )}
                  label={item.current_version.version_label}
                  pending={false}
                  visibility={item.agent.visibility}
                  deleting={deletingId !== null}
                  deleteLabel={t("deleteAgent")}
                  onDelete={
                    item.author?.user_id === user?.id
                      ? () => void deletePersonalAgent(item.agent.id)
                      : undefined
                  }
                />
              ))}
              {ownedAgents.map((agent) => {
                // Same fallback as a student's own tile: a draft reads V1.0.
                const label =
                  chatAgents.find((item) => item.agent_id === agent.id)
                    ?.version_label ?? "V1.0";
                return (
                  <VersionTile
                    key={agent.id}
                    name={agent.name}
                    href={`/teacher/agents/${agent.id}`}
                    title={agentLastEditedTitle(t, agent, label)}
                    label={label}
                    pending={false}
                    visibility={agent.visibility}
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
          ) : undefined}
        </ModuleCard>
        <ModuleCard
          title={t("chatTargetTeams")}
          labelledBy="studyform-teams"
          empty={teams.length ? undefined : t("teamNoneYet")}
          action={
            teacherCourseId ? (
              <ModulePlus
                href="/teacher/studyform?mode=team-new"
                label={t("newAgent")}
              />
            ) : null
          }
        >
          {teams.length ? (
            <ModuleTiles>
              {teams.map((team) => (
                <VersionTile
                  key={team.id}
                  name={team.display_name}
                  href={`/teacher/studyform?mode=team-edit&team_id=${encodeURIComponent(team.id)}`}
                  label={teamVersionLabel(team.current_version_seq)}
                  pending={false}
                  visibility={team.visibility}
                  deleting={deletingId !== null}
                  deleteLabel={t("deleteAgent")}
                  onDelete={
                    team.can_edit
                      ? () =>
                          void deleteOwnedTeam(
                            team.id,
                            t("deletePrivateTeamConfirm"),
                          )
                      : undefined
                  }
                />
              ))}
            </ModuleTiles>
          ) : undefined}
        </ModuleCard>
        <VoiceLibrary
          id="studyform-voices"
          key={`${scope}:voices`}
          groupId={null}
          courseId={teacherCourseId ?? null}
          moduleCard
        />
        {teacherCourseId ? (
          <BrainformWorkspace
            role="teacher"
            embedded
            initialCourseId={teacherCourseId}
            initialMode={brainformMode}
            initialDocumentId={initialDocumentId}
            onPaneChange={setBrainformPane}
          />
        ) : null}
      </ModuleGrid>
    </>
  );
}

export function TeacherPersonalAgentCreate() {
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
    <CreateAgentForm key={scopeKey} courseId={teacherMembership.course_id} />
  );
}

function PublishedAgentTile({
  item,
  groupName,
  deleting,
  onDelete,
}: {
  item: PublishedAgentSummary;
  groupName: string;
  deleting: boolean;
  onDelete?: () => void;
}) {
  const t = useT();
  const version = item.current_version;
  const hasUnpublishedWork =
    Boolean(item.agent.current_draft_version_id) &&
    item.agent.current_draft_version_id !==
      item.agent.current_published_version_id;
  return (
    <div className="agent-tile" data-agent-row={item.agent.id}>
      <Link
        className="agent-tile-name text-link"
        href={`/teacher/agents/${item.agent.id}`}
        title={agentLastEditedTitle(t, item.agent)}
      >
        <FitTitle text={item.agent.name} />
      </Link>
      {groupName ? <span className="agent-tile-group">{groupName}</span> : null}
      {item.author ? (
        <span className="agent-tile-author">
          <UserAvatar
            avatar={item.author.avatar}
            name={item.author.display_name}
            userId={item.author.user_id}
            size="sm"
          />
          <span>{item.author.display_name}</span>
        </span>
      ) : null}
      {onDelete ? (
        <button
          type="button"
          className="agent-pill agent-pill-action"
          data-pending={hasUnpublishedWork ? "true" : "false"}
          disabled={deleting}
          aria-label={t("deleteAgent")}
          onClick={onDelete}
        >
          <span className="agent-pill-label">{version.version_label}</span>
          <span className="agent-pill-x" aria-hidden="true">
            <IconClose size={12} />
          </span>
        </button>
      ) : (
        <span
          className="agent-pill"
          data-pending={hasUnpublishedWork ? "true" : "false"}
        >
          <span className="agent-pill-label">{version.version_label}</span>
        </span>
      )}
    </div>
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
        backHref="/teacher/studyform"
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
  return (
    <AgentReadOnly
      agent={currentAgent}
      version={selectedVersion}
      backHref="/teacher/studyform"
    />
  );
}
