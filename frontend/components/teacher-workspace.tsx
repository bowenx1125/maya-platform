"use client";

import { CountUp } from "./count-up";
import { HomeGuide } from "./home-guide";

import Link from "next/link";
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
import { useT } from "./locale";
import { IconClose } from "./quiet-icons";
import { useSession } from "./session-provider";
import { AcademyMascots } from "./academy/mascots";
import { AccountSettings } from "./account-settings";
import { UserAvatar } from "./user-avatar";
import { AgentReadOnly, AgentWorkbench } from "./agent-workspace";
import { CreateAgentForm } from "./student-workspace";
import { TeamEntryFlow } from "./chats/team-entry-flow";
import {
  ModuleCard,
  ModuleGrid,
  ModulePlus,
  ModuleTiles,
  VersionTile,
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
    return <ErrorNotice error={error} onRetry={() => void load()} />;
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
          <p className="home-hero-eyebrow">{course?.name ?? t("course")}</p>
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
                onDelete={() => void deleteAgent(item.agent.id)}
              />
            ))}
          </div>
        </SectionCard>
      )}
      <AccountSettings onSaved={() => void load()} />
    </div>
  );
}

export function TeacherStudyformWorkspace({
  initialGroupId,
  initialMode,
  initialTeamId,
}: {
  initialGroupId?: string;
  initialMode?: string;
  initialTeamId?: string;
}) {
  const t = useT();
  const { api, identityGeneration, user } = useSession();
  const teacherCourseId = user?.courses.find(
    (membership) => membership.role === "teacher",
  )?.course_id;
  const scope = `${user?.id ?? "anonymous"}:${teacherCourseId ?? "none"}:${initialGroupId ?? "all"}:${initialMode ?? ""}:${initialTeamId ?? ""}:${identityGeneration}`;
  const [personalAgents, setPersonalAgents] = useState<PublishedAgentSummary[]>(
    [],
  );
  const [ownedAgents, setOwnedAgents] = useState<AgentSummary[]>([]);
  const [chatAgents, setChatAgents] = useState<ChatAgent[]>([]);
  const [teams, setTeams] = useState<TeamSummaryDto[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const loading = loadedScope !== scope;
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let active = true;
    const requestScope = scope;
    const timer = window.setTimeout(() => {
      setError(null);
      if (!teacherCourseId) {
        setPersonalAgents([]);
        setOwnedAgents([]);
        setChatAgents([]);
        setTeams([]);
        setLoadedScope(requestScope);
        return;
      }
      void Promise.all([
        typeof api.publishedAgents === "function"
          ? api.publishedAgents(teacherCourseId)
          : Promise.resolve([]),
        api.chatAgents(teacherCourseId),
        typeof api.teams === "function"
          ? api.teams(teacherCourseId)
          : Promise.resolve([]),
        typeof api.workspaceAgents === "function"
          ? api.workspaceAgents(teacherCourseId)
          : Promise.resolve([]),
      ])
        .then(([nextPersonalAgents, nextChatAgents, nextTeams, nextOwned]) => {
          if (!active) return;
          const publishedIds = new Set(
            nextPersonalAgents.map((item) => item.agent.id),
          );
          setPersonalAgents(nextPersonalAgents);
          setOwnedAgents(
            nextOwned.filter((agent) => !publishedIds.has(agent.id)),
          );
          setChatAgents(nextChatAgents);
          setTeams(
            nextTeams.filter(
              (team) =>
                team.can_edit &&
                team.ownership_scope === "personal" &&
                team.group_id === null,
            ),
          );
          setLoadedScope(requestScope);
          setError(null);
        })
        .catch((cause) => {
          if (!active) return;
          setError(cause);
          setLoadedScope(requestScope);
        });
    }, 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [api, initialGroupId, scope, teacherCourseId]);

  async function deletePersonalAgent(agentId: string) {
    if (deletingId || !window.confirm(t("deleteAgentConfirm"))) return;
    setDeletingId(agentId);
    setError(null);
    try {
      await api.deleteAgent(agentId);
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
    return <ErrorNotice error={error} />;

  const mayaForm = initialMode === "maya-new" || initialMode === "maya-edit";
  const privateForm = initialMode === "team-new" || initialMode === "team-edit";
  if (mayaForm || privateForm)
    return (
      <>
        <PageIntro title={t("studyform")} />
        {teacherCourseId ? (
          <TeamEntryFlow
            key={scope}
            api={api}
            courseId={teacherCourseId}
            agents={chatAgents}
            variant={mayaForm ? "maya" : "team"}
            standalone
            backHref="/teacher/studyform"
            initialRouteMode={
              initialMode === "maya-new" || initialMode === "team-new"
                ? "team-new"
                : "team-edit"
            }
            initialTeamId={initialTeamId}
          />
        ) : null}
      </>
    );
  const privateTeams = teams.filter((team) => team.visibility === "private");
  const mayaTeams = teams.filter((team) => team.visibility === "public");

  return (
    <>
      <PageIntro title={t("studyform")} />
      {error ? <ErrorNotice error={error} /> : null}
      <ModuleGrid>
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
                  label={item.current_version.version_label}
                  pending={false}
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
                return (
                  <VersionTile
                    key={agent.id}
                    name={agent.name}
                    href={`/teacher/agents/${agent.id}`}
                    label=""
                    pending={false}
                    deleting={deletingId !== null}
                    deleteLabel={t("deleteAgent")}
                    onDelete={() => void deletePersonalAgent(agent.id)}
                  />
                );
              })}
            </ModuleTiles>
          ) : undefined}
        </ModuleCard>
        <ModuleCard
          title={t("chatTargetTeams")}
          labelledBy="studyform-teams"
          empty={privateTeams.length ? undefined : t("teamNoneYet")}
          action={
            teacherCourseId ? (
              <ModulePlus
                href="/teacher/studyform?mode=team-new"
                label={t("newAgent")}
              />
            ) : null
          }
        >
          {privateTeams.length ? (
            <ModuleTiles>
              {privateTeams.map((team) => (
                <VersionTile
                  key={team.id}
                  name={team.display_name}
                  href={`/teacher/studyform?mode=team-edit&team_id=${encodeURIComponent(team.id)}`}
                  label={t("teamVersionLabel", {
                    seq: team.current_version_seq,
                  })}
                  pending={false}
                  deleting={deletingId !== null}
                  deleteLabel={t("deleteAgent")}
                  onDelete={() =>
                    void deleteOwnedTeam(team.id, t("deletePrivateTeamConfirm"))
                  }
                />
              ))}
            </ModuleTiles>
          ) : undefined}
        </ModuleCard>
        <ModuleCard
          title={t("mayaTeam")}
          labelledBy="studyform-maya"
          empty={mayaTeams.length ? undefined : t("mayaTeamNoneYet")}
          action={
            teacherCourseId ? (
              <ModulePlus
                href="/teacher/studyform?mode=maya-new"
                label={t("newAgent")}
              />
            ) : null
          }
        >
          {mayaTeams.length ? (
            <ModuleTiles>
              {mayaTeams.map((team) => (
                <VersionTile
                  key={team.id}
                  name={team.display_name}
                  href={`/teacher/studyform?mode=maya-edit&team_id=${encodeURIComponent(team.id)}`}
                  label={t("teamVersionLabel", {
                    seq: team.current_version_seq,
                  })}
                  pending={false}
                  deleting={deletingId !== null}
                  deleteLabel={t("deleteAgent")}
                  onDelete={() =>
                    void deleteOwnedTeam(team.id, t("deleteTeamConfirm"))
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
          membershipGroupIds={(user?.groups ?? []).map(
            (group) => group.group_id,
          )}
          listenOnly
          embedded
        />
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
    return <ErrorNotice error={new Error(t("courseNotFound"))} />;
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
  onDelete: () => void;
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
      >
        {item.agent.name}
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
        error={error ?? new Error(t("publishedAgentNotFound"))}
        onRetry={() => void load()}
      />
    );
  if (generationSetId && verifiedGenerationSetId !== generationSetId) {
    return <ErrorNotice error={new Error(t("generatedSetAgentMismatch"))} />;
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
    return <ErrorNotice error={new Error(t("publishedAgentNotFound"))} />;
  }
  return (
    <AgentReadOnly
      agent={currentAgent}
      version={selectedVersion}
      backHref="/teacher/studyform"
    />
  );
}
