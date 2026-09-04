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
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
  StatusBadge,
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
    <>
      <PageIntro
        eyebrow={t("teacherCourse")}
        title={course?.name ?? t("publishedAgents")}
        action={
          <div className="course-context">
            <span className="section-label">{t("publishedWork")}</span>
            <strong>{published.length}</strong>
            <span>{t("currentAgents")}</span>
          </div>
        }
      />
      {published.length === 0 ? (
        <EmptyCard title={t("noPublishedAgents")} />
      ) : (
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
      )}
    </>
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
        <div className="avatar-orb" aria-hidden="true">
          {item.agent.name.slice(0, 1).toUpperCase()}
        </div>
        <div>
          <h2>{item.agent.name}</h2>
          <p>{item.agent.description}</p>
        </div>
        <span className="row-arrow" aria-hidden="true">
          →
        </span>
      </div>
      <div className="published-card-meta">
        {/* The version and the group that made it. Green means the published
            release is the newest work; amber means a newer draft exists that
            the class has not released yet. */}
        <span
          className="agent-pill"
          data-pending={hasUnpublishedWork ? "true" : "false"}
        >
          {version.version_label}
        </span>
        {groupName ? <span className="agent-pill">{groupName}</span> : null}
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
  const [snapshotText, setSnapshotText] = useState<string | null>(null);
  const [downloadedSnapshotId, setDownloadedSnapshotId] = useState<
    string | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setSnapshot(null);
    setSnapshotText(null);
    setDownloadedSnapshotId(null);
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

  async function downloadSnapshot() {
    if (!snapshot) return;
    setBusy(true);
    try {
      const downloaded = await api.downloadSnapshot(snapshot.id);
      setSnapshotText(downloaded.content);
      setDownloadedSnapshotId(snapshot.id);
      downloadText(downloaded.content, downloaded.filename);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  async function downloadDocument(snapshotDocumentId: string) {
    if (!snapshot) return;
    setBusy(true);
    try {
      const downloaded = await api.downloadSnapshotDocument(
        snapshot.id,
        snapshotDocumentId,
      );
      downloadText(downloaded.content, downloaded.filename);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageIntro
        eyebrow={t("publishedAgent")}
        title={agent.name}
        description={agent.description}
        action={
          <Link className="secondary-action" href="/teacher">
            {t("debateBack")}
          </Link>
        }
      />
      <div className="teacher-agent-context-grid">
        <SectionCard title={group?.name ?? t("producingGroup")}>
          {/* Who made this Agent, by name, in an order a reader can scan. */}
          {group?.members?.length ? (
            <ul className="teacher-group-members">
              {[...group.members]
                .sort((left, right) =>
                  left.display_name.localeCompare(right.display_name),
                )
                .map((member) => (
                  <li key={member.user_id}>{member.display_name}</li>
                ))}
            </ul>
          ) : group ? null : (
            // The group itself did not load; its id is all we can honestly say.
            <p className="teacher-context-value">{currentAgent.group_id}</p>
          )}
        </SectionCard>
        <SectionCard title={t("avatarPreview")}>
          {currentVersion ? (
            <AvatarPreview
              config={currentVersion.avatar_config}
              fallbackLabel={currentAgent.name}
            />
          ) : (
            <p className="muted-copy">{t("noCurrentPublished")}</p>
          )}
        </SectionCard>
        <SectionCard title={t("voiceBinding")}>
          {currentVersion ? (
            <div
              className="teacher-voice-state"
              data-effective-voice={
                currentVersion.voice_fallback_active
                  ? "platform-fallback"
                  : "custom-profile"
              }
            >
              <span
                className={`status-badge status-${currentVersion.voice_fallback_active ? "warn" : "good"}`}
              >
                <span aria-hidden="true" />
                {currentVersion.voice_fallback_active
                  ? t("platformVoiceFallback")
                  : t("customVoiceReady")}
              </span>
            </div>
          ) : (
            <p className="muted-copy">{t("noCurrentPublished")}</p>
          )}
        </SectionCard>
      </div>
      {agent.status === "archived" ? (
        <div className="notice notice-warning">
          <strong>{t("archivedAgent")}</strong>
          <span>{t("archivedLede")}</span>
        </div>
      ) : null}
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}
      <div className="teacher-detail-grid">
        <div>
          <SectionCard title={t("currentRelease")}>
            {currentVersion ? (
              <TeacherVersion
                version={currentVersion}
                selected={currentVersion.id === selectedVersionId}
              />
            ) : (
              <EmptyCard title={t("noCurrentPublished")} />
            )}
          </SectionCard>
          <SectionCard title={t("publishedHistory")}>
            {versions.length === 0 ? (
              <p className="muted-copy">{t("noPublishedHistory")}</p>
            ) : (
              <div className="version-list">
                {versions.map((version) => (
                  <TeacherVersion
                    version={version}
                    selected={version.id === selectedVersionId}
                    key={version.id}
                  />
                ))}
              </div>
            )}
          </SectionCard>
        </div>
        <aside>
          <SectionCard title={t("knowledgeSnapshot")}>
            {snapshot ? (
              <>
                <div className="snapshot-summary">
                  <div>
                    <span className="section-label">{t("snapshot")}</span>
                    <strong>{snapshot.id.slice(0, 8)}…</strong>
                  </div>
                  <div>
                    <span className="section-label">{t("content")}</span>
                    <strong>
                      {snapshot.total_char_count.toLocaleString()}{" "}
                      {t("characters")}
                    </strong>
                  </div>
                  <div>
                    <span className="section-label">{t("files")}</span>
                    <strong>{snapshot.documents.length}</strong>
                  </div>
                </div>
                <button
                  className="secondary-action"
                  type="button"
                  disabled={busy}
                  onClick={() => void downloadSnapshot()}
                >
                  {t("downloadRag")}
                </button>
                <div className="snapshot-files">
                  {snapshot.documents.map((document) => (
                    <div className="snapshot-file" key={document.id}>
                      <span>
                        <strong>{document.source_filename}</strong>
                        <small>
                          {t("order")} {document.order_index + 1} ·{" "}
                          {document.char_count.toLocaleString()}{" "}
                          {t("characters")}
                        </small>
                      </span>
                      <button
                        className="inline-button"
                        type="button"
                        disabled={busy}
                        onClick={() => void downloadDocument(document.id)}
                      >
                        {t("download")}
                      </button>
                    </div>
                  ))}
                </div>
                {canShowSnapshotText(snapshot.id, downloadedSnapshotId) &&
                snapshotText ? (
                  <pre className="snapshot-preview">{snapshotText}</pre>
                ) : null}
              </>
            ) : (
              <p className="muted-copy">{t("selectSnapshot")}</p>
            )}
          </SectionCard>
        </aside>
      </div>
    </>
  );
}

export function canShowSnapshotText(
  snapshotId: string | null | undefined,
  downloadedSnapshotId: string | null,
): boolean {
  return Boolean(snapshotId && downloadedSnapshotId === snapshotId);
}

function TeacherVersion({
  version,
  selected,
}: {
  version: AgentVersion;
  selected: boolean;
}) {
  const t = useT();
  const { api } = useSession();
  const [agentMdBusy, setAgentMdBusy] = useState(false);
  const [agentMdError, setAgentMdError] = useState<unknown>(null);

  async function downloadAgentMd() {
    setAgentMdBusy(true);
    setAgentMdError(null);
    try {
      const downloaded = await api.downloadAgentMd(version.id, "AGENT.md");
      downloadText(downloaded.content, downloaded.filename);
    } catch (cause) {
      setAgentMdError(cause);
    } finally {
      setAgentMdBusy(false);
    }
  }

  return (
    <div className="teacher-version">
      <div className="version-summary">
        <div>
          <div className="chip-row">
            <strong>{version.version_label}</strong>
            <StatusBadge status={version.state} />
          </div>
          <p>
            {t("immutable")} {t("revision")} {version.revision} ·{" "}
            {version.enabled_documents?.length ?? 0} {t("evidenceFiles")}
          </p>
        </div>
        {selected ? (
          <span className="current-version-indicator" aria-current="page">
            {t("viewingSnapshot")}
          </span>
        ) : (
          <Link
            className="text-link"
            href={`/teacher/agents/${version.agent_id}?snapshot=${version.knowledge_snapshot_id ?? ""}`}
          >
            {t("inspect")}
          </Link>
        )}
      </div>
      <details>
        <summary>{t("readAgentMd")}</summary>
        <pre className="read-only-markdown compact-readonly">
          {version.agent_md || t("noPrompt")}
        </pre>
        <button
          className="inline-button"
          type="button"
          disabled={agentMdBusy}
          onClick={() => void downloadAgentMd()}
        >
          {t("download")} AGENT.md
        </button>
        {agentMdError ? <ErrorNotice error={agentMdError} /> : null}
      </details>
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
