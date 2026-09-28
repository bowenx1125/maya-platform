"use client";

import { WorkspaceAction } from "./workspace-actions";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  type AgentDetail,
  type AgentSummary,
  type AgentVersion,
  type Course,
  type Group,
  type GroupDetail,
  type KnowledgeSnapshot,
  type PublishedAgentSummary,
} from "../lib/api";
import { useIdempotencyStore } from "../lib/idempotency";
import { useT } from "./locale";
import { IconClose, IconDownload } from "./quiet-icons";
import { useSession } from "./session-provider";
import { AvatarPreview } from "./avatar";
import { DemoCompositionBadge } from "./demo-composition";
import { ReportMarkdown } from "./report/report-markdown";
import detailStyles from "./teacher-agent-detail.module.css";
import { AgentWorkbench } from "./agent-workspace";
import { CreateAgentForm } from "./student-workspace";
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
  const [personalAgents, setPersonalAgents] = useState<AgentSummary[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
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
      const [nextPublished, nextGroups, nextPersonalAgents] = await Promise.all(
        [
          courseId ? api.publishedAgents(courseId) : Promise.resolve([]),
          courseId ? api.groups(courseId) : Promise.resolve([]),
          courseId && typeof api.workspaceAgents === "function"
            ? api.workspaceAgents(courseId)
            : Promise.resolve([]),
        ],
      );
      if (workspaceScopeRef.current !== requestScope) return;
      setCourse(
        courses.find((item) => item.id === courseId) ?? courses[0] ?? null,
      );
      setPublished(nextPublished);
      setGroups(nextGroups);
      setPersonalAgents(nextPersonalAgents);
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
  if (error && published.length === 0 && personalAgents.length === 0)
    return <ErrorNotice error={error} onRetry={() => void load()} />;
  return (
    <div className="teacher-home-layout">
      <PageIntro
        title={
          course?.name === "Maya Cultural Exchange Demo"
            ? t("appName")
            : (course?.name ?? t("appName"))
        }
      />
      <DemoCompositionBadge />
      {error ? <ErrorNotice error={error} /> : null}
      <SectionCard
        title={`${t("personalAgents")} · ${personalAgents.length}`}
        description={t("personalWorkspaceLede")}
        className="published-section"
        action={
          course ? (
            <Link className="primary-action" href="/teacher/agents/new">
              {t("newAgent")}
            </Link>
          ) : null
        }
      >
        {personalAgents.length === 0 ? (
          <EmptyCard
            title={t("noPersonalAgents")}
            action={
              course ? (
                <Link className="text-link" href="/teacher/agents/new">
                  {t("openPersonalWorkspace")}
                </Link>
              ) : null
            }
          />
        ) : (
          <div className="agent-tile-grid">
            {personalAgents.map((agent) => (
              <PersonalAgentTile agent={agent} key={agent.id} />
            ))}
          </div>
        )}
      </SectionCard>
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
    </div>
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

function PersonalAgentTile({ agent }: { agent: AgentSummary }) {
  const t = useT();
  return (
    <div className="agent-tile" data-agent-row={agent.id}>
      <Link
        className="agent-tile-name text-link"
        href={`/teacher/agents/${agent.id}`}
      >
        {agent.name}
      </Link>
      <span className="agent-tile-group">
        {agent.current_draft_version_id ? t("draft") : t("published")}
      </span>
      <span className="agent-pill-label">
        {agent.visibility === "private"
          ? t("privateVisibility")
          : t("personalPublicVisibility")}
      </span>
    </div>
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
      <button
        type="button"
        className="agent-pill agent-pill-action"
        data-pending={hasUnpublishedWork ? "true" : "false"}
        disabled={deleting}
        aria-label={t("deleteAgent")}
        title={version.version_label}
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
}: {
  agentId: string;
  snapshotId?: string;
}) {
  const t = useT();
  const { api, identityGeneration, user } = useSession();
  const actorScope = `${user?.id ?? "anonymous"}:${agentId}:${identityGeneration}`;
  const actorScopeRef = useRef(actorScope);
  useEffect(() => {
    actorScopeRef.current = actorScope;
  }, [actorScope]);
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
  const load = useCallback(async () => {
    const requestScope = actorScope;
    setLoading(true);
    setError(null);
    setSnapshot(null);
    try {
      const nextAgent = await api.agent(agentId);
      if (actorScopeRef.current !== requestScope) return;
      const [nextVersions, nextGroup] = await Promise.all([
        api.versions(agentId),
        nextAgent.group_id && typeof api.group === "function"
          ? api.group(nextAgent.group_id)
          : Promise.resolve(null),
      ]);
      if (actorScopeRef.current !== requestScope) return;
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
        if (actorScopeRef.current !== requestScope) return;
        setSnapshot(nextSnapshot);
      } else setSnapshot(null);
    } catch (cause) {
      if (actorScopeRef.current === requestScope) setError(cause);
    } finally {
      if (actorScopeRef.current === requestScope) {
        setLoadedScope(requestScope);
        setLoading(false);
      }
    }
  }, [actorScope, agentId, api, snapshotId]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading || loadedScope !== actorScope) return <LoadingCard />;
  if (error || !agent)
    return (
      <ErrorNotice
        error={error ?? new Error(t("publishedAgentNotFound"))}
        onRetry={() => void load()}
      />
    );
  const currentAgent = agent;
  async function createPersonalVersion() {
    if (creatingDraft) return;
    const requestScope = actorScope;
    const intent = `teacher-next-version:${requestScope}`;
    const handle = mutationStore.handleFor(intent);
    setCreatingDraft(true);
    setError(null);
    try {
      const next = await api.nextVersion(agentId, { idempotency: handle });
      mutationStore.finish(intent, handle);
      if (actorScopeRef.current !== requestScope) return;
      setVersions((current) => [...current, next]);
      setEditingVersionId(next.id);
    } catch (cause) {
      if (actorScopeRef.current !== requestScope) return;
      setError(cause);
    } finally {
      if (actorScopeRef.current === requestScope) setCreatingDraft(false);
    }
  }
  if (agent.ownership_scope === "personal" && editingVersionId) {
    return (
      <AgentWorkbench
        key={`${actorScope}:${editingVersionId}`}
        actorScopeKey={actorScope}
        backHref="/teacher"
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
      <WorkspaceAction name="back" href="/teacher" />
      {agent.status === "archived" ? (
        <span className="status-badge status-warn">{t("archivedAgent")}</span>
      ) : null}
      {agent.ownership_scope === "personal" &&
      agent.current_published_version_id ? (
        <button
          className="primary-action"
          type="button"
          disabled={creatingDraft}
          onClick={() => void createPersonalVersion()}
        >
          {creatingDraft ? t("creating") : t("createNewVersion")}
        </button>
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
          snapshot?.documents.length ? (
            <button
              className="icon-action"
              type="button"
              aria-label={`${t("download")} RAG`}
              title={t("download")}
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
          ) : null
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
          <p className={detailStyles.empty}>No files</p>
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
              title={t("download")}
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
          <strong title={document.source_filename}>
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
            title={t("download")}
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
