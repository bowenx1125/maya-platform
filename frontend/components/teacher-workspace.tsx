"use client";

import { CountUp } from "./count-up";
import { HomeGuide } from "./home-guide";
import { PageAction } from "./page-action";

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
import { IconClose, IconDownload } from "./quiet-icons";
import { useSession } from "./session-provider";
import { AcademyMascots } from "./academy/mascots";
import { AccountSettings } from "./account-settings";
import { AvatarPreview } from "./avatar";
import { DemoCompositionBadge } from "./demo-composition";
import { ReportMarkdown } from "./report/report-markdown";
import { UserAvatar } from "./user-avatar";
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
  const [debateCount, setDebateCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const teacherCourseId = user?.courses.find(
    (item) => item.role === "teacher",
  )?.course_id;
  const load = useCallback(async () => {
    setError(null);
    try {
      const [courses, nextPublished, nextGroups, debates] = await Promise.all([
        api.courses(),
        teacherCourseId
          ? api.publishedAgents(teacherCourseId)
          : Promise.resolve([]),
        teacherCourseId ? api.groups(teacherCourseId) : Promise.resolve([]),
        teacherCourseId ? api.debates(teacherCourseId) : Promise.resolve([]),
      ]);
      setCourse(
        courses.find((item) => item.id === teacherCourseId) ??
          courses[0] ??
          null,
      );
      setPublished(nextPublished);
      setGroups(nextGroups);
      setDebateCount(debates.length);
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [api, teacherCourseId]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function deleteAgent(agentId: string) {
    if (deleting || !window.confirm(t("deleteAgentConfirm"))) return;
    setDeleting(agentId);
    setError(null);
    try {
      await api.deleteAgent(agentId);
      setPublished((current) =>
        current.filter((item) => item.agent.id !== agentId),
      );
    } catch (cause) {
      setError(cause);
    } finally {
      setDeleting(null);
    }
  }

  if (loading) return <LoadingCard />;
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
      href: "/teacher",
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
      <DemoCompositionBadge />
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
      <PageIntro title={agent.name} />
      <PageAction name="back" href="/teacher" />
      {agent.status === "archived" ? (
        <span className="status-badge status-warn">{t("archivedAgent")}</span>
      ) : null}
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
