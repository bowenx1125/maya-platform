"use client";

import { CountUp } from "./count-up";
import { HomeGuide } from "./home-guide";
import { PageAction } from "./page-action";

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
import { useIdempotencyStore } from "../lib/idempotency";
import { useT } from "./locale";
import { IconClose, IconDownload } from "./quiet-icons";
import { useSession } from "./session-provider";
import { AcademyMascots } from "./academy/mascots";
import { AccountSettings } from "./account-settings";
import { AvatarPreview } from "./avatar";
import { ReportMarkdown } from "./report/report-markdown";
import { UserAvatar } from "./user-avatar";
import detailStyles from "./teacher-agent-detail.module.css";
import { AgentWorkbench } from "./agent-workspace";
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
  const [personalAgents, setPersonalAgents] = useState<AgentSummary[]>([]);
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
        setChatAgents([]);
        setTeams([]);
        setLoadedScope(requestScope);
        return;
      }
      void Promise.all([
        api.workspaceAgents(teacherCourseId),
        api.chatAgents(teacherCourseId),
        typeof api.teams === "function"
          ? api.teams(teacherCourseId)
          : Promise.resolve([]),
      ])
        .then(([nextPersonalAgents, nextChatAgents, nextTeams]) => {
          if (!active) return;
          setPersonalAgents(nextPersonalAgents);
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
  if (error && !personalAgents.length && !chatAgents.length)
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
          empty={personalAgents.length ? undefined : t("noPersonalAgents")}
          action={
            teacherCourseId ? (
              <ModulePlus href="/teacher/agents/new" label={t("newAgent")} />
            ) : null
          }
        >
          {personalAgents.length ? (
            <ModuleTiles>
              {personalAgents.map((agent) => {
                const pending = Boolean(
                  agent.current_draft_version_id &&
                  agent.current_draft_version_id !==
                    agent.current_published_version_id,
                );
                return (
                  <VersionTile
                    key={agent.id}
                    name={agent.name}
                    href={`/teacher/agents/${agent.id}`}
                    label={pending ? t("draft") : t("published")}
                    pending={pending}
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
  const mutationStore = useIdempotencyStore();
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [group, setGroup] = useState<GroupDetail | null>(null);
  const [versions, setVersions] = useState<AgentVersion[]>([]);
  const [snapshot, setSnapshot] = useState<KnowledgeSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const [editingVersionId, setEditingVersionId] = useState<string | null>(null);
  const [creatingDraft, setCreatingDraft] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [verifiedGenerationSetId, setVerifiedGenerationSetId] = useState<
    string | null
  >(null);
  const updateDraftAttempted = useRef<string | null>(null);
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
      setEditingVersionId(
        nextAgent.ownership_scope === "personal"
          ? (visibleVersions.find((version) => version.state === "draft")?.id ??
              null)
          : null,
      );
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

  const createPersonalVersion = useCallback(async () => {
    if (creatingDraft) return;
    const requestScope = loadScope;
    const intent = `teacher-next-version:${requestScope}`;
    const handle = mutationStore.handleFor(intent);
    setCreatingDraft(true);
    setError(null);
    try {
      const next = await api.nextVersion(agentId, { idempotency: handle });
      mutationStore.finish(intent, handle);
      if (
        actorScopeRef.current !== actorScope ||
        loadScopeRef.current !== requestScope
      )
        return;
      setVersions((current) => [...current, next]);
      setEditingVersionId(next.id);
    } catch (cause) {
      if (
        actorScopeRef.current !== actorScope ||
        loadScopeRef.current !== requestScope
      )
        return;
      setError(cause);
    } finally {
      if (
        actorScopeRef.current === actorScope &&
        loadScopeRef.current === requestScope
      )
        setCreatingDraft(false);
    }
  }, [actorScope, agentId, api, creatingDraft, loadScope, mutationStore]);

  useEffect(() => {
    if (
      !generationFlow ||
      !generationSetId ||
      verifiedGenerationSetId !== generationSetId ||
      loading ||
      loadedScope !== loadScope ||
      !agent ||
      agent.ownership_scope !== "personal" ||
      editingVersionId ||
      creatingDraft
    )
      return;
    const attemptKey = `${actorScope}:${generationSetId}`;
    if (updateDraftAttempted.current === attemptKey) return;
    updateDraftAttempted.current = attemptKey;
    void createPersonalVersion();
  }, [
    actorScope,
    agent,
    creatingDraft,
    editingVersionId,
    generationFlow,
    generationSetId,
    loadedScope,
    loadScope,
    loading,
    createPersonalVersion,
    verifiedGenerationSetId,
  ]);

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
  if (agent.ownership_scope === "personal" && editingVersionId) {
    const knowledgeHref = generationSetId
      ? `/teacher/knowledge?agent_id=${encodeURIComponent(agentId)}&set_id=${encodeURIComponent(generationSetId)}`
      : `/teacher/knowledge?agent_id=${encodeURIComponent(agentId)}`;
    return (
      <AgentWorkbench
        key={`${actorScope}:${editingVersionId}`}
        actorScopeKey={actorScope}
        backHref="/teacher"
        knowledgeHref={knowledgeHref}
        generationFlow={generationFlow}
        versionId={editingVersionId}
      />
    );
  }
  const currentVersion = versions.find(
    (version) => version.id === currentAgent.current_published_version_id,
  );
  const selectedSnapshotId = snapshotId ?? snapshot?.id ?? null;
  const selectedVersionId = selectedSnapshotId
    ? (versions.find(
        (version) => version.knowledge_snapshot_id === selectedSnapshotId,
      )?.id ?? null)
    : (currentAgent.current_published_version_id ?? null);

  const selectedVersion = selectedSnapshotId
    ? versions.find((version) => version.id === selectedVersionId)
    : currentVersion;

  if (snapshotId && snapshot?.id !== snapshotId) return <LoadingCard />;

  return (
    <div className={detailStyles.page}>
      <PageIntro title={agent.name} />
      <PageAction name="back" href="/teacher/studyform" />
      {agent.status === "archived" ? (
        <span className="status-badge status-warn">{t("archivedAgent")}</span>
      ) : null}
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}
      <div className={detailStyles.overview}>
        <TeacherAgentMarkdown
          key={selectedVersion?.id}
          version={selectedVersion}
        />
        <SectionCard
          title="Profile"
          className={`${detailStyles.card} ${detailStyles.profile}`}
        >
          {selectedVersion ? (
            <div className={detailStyles.avatar}>
              <AvatarPreview
                config={selectedVersion.avatar_config}
                fallbackLabel={currentAgent.name}
                framing="full-body"
                className={detailStyles.fullBody}
              />
            </div>
          ) : null}
          <div className={detailStyles.profileFacts}>
            {group ? (
              <div className={detailStyles.fact}>
                <strong>{group.name}</strong>
                {group.members?.length ? (
                  <p>
                    {[...group.members]
                      .sort((a, b) =>
                        a.display_name.localeCompare(b.display_name),
                      )
                      .map((member) => member.display_name)
                      .join(" · ")}
                  </p>
                ) : null}
              </div>
            ) : null}
            {selectedVersion ? (
              <div
                className={detailStyles.fact}
                data-effective-voice={
                  selectedVersion.voice_fallback_active
                    ? "platform-fallback"
                    : "custom-profile"
                }
              >
                <span
                  className={`status-badge status-${selectedVersion.voice_fallback_active ? "warn" : "good"}`}
                >
                  <span aria-hidden="true" />
                  {selectedVersion.voice_fallback_active
                    ? "Default voice"
                    : "Custom voice"}
                </span>
              </div>
            ) : null}
          </div>
        </SectionCard>
      </div>
      <SectionCard
        title="RAG"
        className={detailStyles.card}
        action={
          <div className={detailStyles.actions}>
            {group ? (
              <Link
                className="secondary-action"
                href={`/teacher/groups/${group.id}/knowledge`}
              >
                {t("knowledgeImportLink")}
              </Link>
            ) : null}
            {snapshot?.documents.length ? (
              <button
                className="icon-action"
                type="button"
                aria-label={`${t("download")} RAG`}
                data-ui-guide="agent.download"
                onClick={() => {
                  void (async () => {
                    for (const document of snapshot.documents) {
                      const result = await api.downloadSnapshotDocument(
                        snapshot.id,
                        document.id,
                      );
                      downloadText(result.content, result.filename);
                    }
                  })();
                }}
              >
                <IconDownload />
              </button>
            ) : null}
          </div>
        }
      >
        {snapshot?.documents.length ? (
          <div className={detailStyles.files}>
            {snapshot.documents.map((document) => (
              <RagFile
                key={`${snapshot.id}:${document.id}`}
                snapshotId={snapshot.id}
                document={document}
              />
            ))}
          </div>
        ) : (
          <p className={detailStyles.empty}>No files yet.</p>
        )}
      </SectionCard>
      {versions.length > 1 ? (
        <SectionCard title="Versions" className={detailStyles.card}>
          <div className={detailStyles.versions}>
            {versions.map((version) => (
              <Link
                key={version.id}
                className={detailStyles.version}
                aria-label={`${version.version_label} ${version.state === "published" ? "Published" : "Previous"}`}
                aria-current={
                  version.id === selectedVersionId ? "page" : undefined
                }
                href={`/teacher/agents/${version.agent_id}?snapshot=${version.knowledge_snapshot_id ?? ""}`}
              >
                <span
                  className="agent-pill"
                  data-pending={version.state === "draft" ? "true" : "false"}
                >
                  {version.version_label}
                </span>
                <span>
                  {version.state === "published" ? "Published" : "Previous"}
                </span>
              </Link>
            ))}
          </div>
        </SectionCard>
      ) : null}
    </div>
  );
}

function TeacherAgentMarkdown({ version }: { version?: AgentVersion }) {
  const t = useT();
  const { api } = useSession();
  const [busy, setBusy] = useState(false);
  return (
    <SectionCard
      title="AGENT.md"
      className={`${detailStyles.card} ${detailStyles.personaCard}`}
      action={
        version ? (
          <div className={detailStyles.actions}>
            <span
              className="agent-pill"
              data-pending={version.state === "draft" ? "true" : "false"}
            >
              {version.version_label}
            </span>
            <button
              className="icon-action"
              type="button"
              disabled={busy}
              aria-label={`${t("download")} AGENT.md`}
              data-ui-guide="agent.download"
              onClick={() => {
                void (async () => {
                  setBusy(true);
                  try {
                    const downloaded = await api.downloadAgentMd(version.id);
                    downloadText(downloaded.content, downloaded.filename);
                  } finally {
                    setBusy(false);
                  }
                })();
              }}
            >
              <IconDownload />
            </button>
          </div>
        ) : null
      }
    >
      {version?.agent_md ? (
        <ReportMarkdown className={detailStyles.persona} label="AGENT.md">
          {version.agent_md}
        </ReportMarkdown>
      ) : (
        <p className={detailStyles.empty}>—</p>
      )}
    </SectionCard>
  );
}

function RagFile({
  snapshotId,
  document,
}: {
  snapshotId: string;
  document: KnowledgeSnapshot["documents"][number];
}) {
  const t = useT();
  const { api } = useSession();
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function read(download = false) {
    if (busy) return;
    if (!download && content !== null) {
      setOpen(!open);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.downloadSnapshotDocument(
        snapshotId,
        document.id,
      );
      if (download) downloadText(result.content, result.filename);
      else {
        setContent(result.content);
        setOpen(true);
      }
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={detailStyles.file}>
      <div className={detailStyles.fileHeader}>
        <div className={detailStyles.fileIdentity}>
          <strong
            data-ui-guide="knowledge.filename"
            data-ui-guide-text={document.source_filename}
            tabIndex={0}
          >
            {document.source_filename}
          </strong>
          <small>
            {document.char_count.toLocaleString()} {t("characters")}
          </small>
        </div>
        <div className={detailStyles.fileActions}>
          <button
            className={detailStyles.action}
            type="button"
            aria-expanded={open}
            aria-controls={`rag-file-${document.id}`}
            disabled={busy}
            onClick={() => void read()}
          >
            Check
          </button>
          <button
            className="icon-action"
            type="button"
            disabled={busy}
            aria-label={t("download")}
            data-ui-guide="agent.download"
            onClick={() => void read(true)}
          >
            <IconDownload />
          </button>
        </div>
      </div>
      {open && content !== null ? (
        <div id={`rag-file-${document.id}`} className={detailStyles.fileBody}>
          <ReportMarkdown label={document.source_filename}>
            {content}
          </ReportMarkdown>
        </div>
      ) : null}
      {error ? <ErrorNotice error={error} onRetry={() => void read()} /> : null}
    </div>
  );
}

function downloadText(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
