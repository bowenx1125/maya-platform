"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  type AgentDetail,
  type AgentVersion,
  type Course,
  type Group,
  type GroupDetail,
  type KnowledgeSnapshot,
  type PublishedAgentSummary,
} from "../lib/api";
import { useT } from "./locale";
import { useSession } from "./session-provider";
import { AvatarPreview } from "./avatar";
import { DemoCompositionBadge } from "./demo-composition";
import { ReportMarkdown } from "./report/report-markdown";
import detailStyles from "./teacher-agent-detail.module.css";
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
} from "./ui";

export function TeacherDashboard() {
  const t = useT();
  const { api, user } = useSession();
  const [course, setCourse] = useState<Course | null>(null);
  const [published, setPublished] = useState<PublishedAgentSummary[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const teacherMembership = user?.courses.find(
        (item) => item.role === "teacher",
      );
      const [courses, nextPublished, nextGroups] = await Promise.all([
        api.courses(),
        teacherMembership
          ? api.publishedAgents(teacherMembership.course_id)
          : Promise.resolve([]),
        teacherMembership
          ? api.groups(teacherMembership.course_id)
          : Promise.resolve([]),
      ]);
      setCourse(
        courses.find((item) => item.id === teacherMembership?.course_id) ??
          courses[0] ??
          null,
      );
      setPublished(nextPublished);
      setGroups(nextGroups);
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [api, user]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading) return <LoadingCard />;
  if (error) return <ErrorNotice error={error} onRetry={() => void load()} />;
  return (
    <div className="teacher-home-layout">
      <PageIntro
        eyebrow={t("teacherCourse")}
        title={
          course?.name === "Maya Cultural Exchange Demo"
            ? t("appName")
            : (course?.name ?? t("appName"))
        }
      />
      {/* What is real and what is Mock, under the course it describes rather
          than above the title, so the page opens on its own heading. */}
      <DemoCompositionBadge />
      {published.length === 0 ? (
        <EmptyCard title={t("noPublishedAgents")} />
      ) : (
        <SectionCard
          title={`${t("publishedWork")} ${published.length} ${t("currentAgents")}`}
          className="published-section"
        >
          <div className="published-grid">
            {published.map((item) => (
              <PublishedAgentCard
                groupName={
                  groups.find((group) => group.id === item.agent.group_id)
                    ?.name ?? null
                }
                item={item}
                key={item.agent.id}
              />
            ))}
          </div>
        </SectionCard>
      )}
    </div>
  );
}

function PublishedAgentCard({
  item,
  groupName,
}: {
  item: PublishedAgentSummary;
  groupName: string | null;
}) {
  const version = item.current_version;
  // A newer draft that has not been published yet. Derived from the Agent's
  // own pointers rather than a status word, so it stays true for any version
  // label and any number of releases.
  const hasUnpublishedWork =
    Boolean(item.agent.current_draft_version_id) &&
    item.agent.current_draft_version_id !==
      item.agent.current_published_version_id;
  return (
    <Link className="published-card" href={`/teacher/agents/${item.agent.id}`}>
      <div className="published-card-top">
        <h2>{item.agent.name}</h2>
        <span className="published-card-group" title={groupName ?? undefined}>
          {groupName}
        </span>
      </div>
      <div className="published-card-meta">
        <span
          className="agent-pill"
          data-pending={hasUnpublishedWork ? "true" : "false"}
        >
          {version.version_label}
        </span>
        <p title={item.agent.description ?? undefined}>
          {item.agent.description}
        </p>
      </div>
    </Link>
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
  const { api } = useSession();
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [group, setGroup] = useState<GroupDetail | null>(null);
  const [versions, setVersions] = useState<AgentVersion[]>([]);
  const [snapshot, setSnapshot] = useState<KnowledgeSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setSnapshot(null);
    try {
      const nextAgent = await api.agent(agentId);
      const [nextVersions, nextGroup] = await Promise.all([
        api.versions(agentId),
        typeof api.group === "function"
          ? api.group(nextAgent.group_id)
          : Promise.resolve(null),
      ]);
      setAgent(nextAgent);
      setGroup(nextGroup);
      setVersions(nextVersions.filter((version) => version.state !== "draft"));
      const selectedSnapshotId =
        snapshotId ||
        nextVersions.find(
          (version) => version.id === nextAgent.current_published_version_id,
        )?.knowledge_snapshot_id ||
        null;
      if (selectedSnapshotId)
        setSnapshot(await api.snapshot(selectedSnapshotId));
      else setSnapshot(null);
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [agentId, api, snapshotId]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading) return <LoadingCard />;
  if (error || !agent)
    return (
      <ErrorNotice
        error={error ?? new Error(t("publishedAgentNotFound"))}
        onRetry={() => void load()}
      />
    );
  const currentAgent = agent;
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
      <PageIntro
        eyebrow="Agent"
        title={agent.name}
        action={
          <Link className="secondary-action" href="/teacher">
            {t("debateBack")}
          </Link>
        }
      />
      {agent.status === "archived" ? (
        <span className="status-badge status-warn">{t("archivedAgent")}</span>
      ) : null}
      <div className={detailStyles.overview}>
        <TeacherPersona key={selectedVersion?.id} version={selectedVersion} />
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
      <SectionCard title="RAG" className={detailStyles.card}>
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
                <span className="agent-pill">{version.version_label}</span>
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

function TeacherPersona({ version }: { version?: AgentVersion }) {
  return (
    <SectionCard
      title="Persona"
      className={`${detailStyles.card} ${detailStyles.personaCard}`}
      action={
        version ? (
          <span className="agent-pill">{version.version_label}</span>
        ) : null
      }
    >
      {version?.agent_md ? (
        <ReportMarkdown className={detailStyles.persona} label="Persona">
          {version.agent_md}
        </ReportMarkdown>
      ) : (
        <p className={detailStyles.empty}>No Persona</p>
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
          <small>{document.char_count.toLocaleString()} characters</small>
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
            className={detailStyles.action}
            type="button"
            disabled={busy}
            onClick={() => void read(true)}
          >
            Download
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
