"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  type AgentDetail,
  type AgentVersion,
  type Course,
  type KnowledgeSnapshot,
  type PublishedAgentSummary,
} from "../lib/api";
import { useT } from "./locale";
import { useSession } from "./session-provider";
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const teacherMembership = user?.courses.find(
        (item) => item.role === "teacher",
      );
      const [courses, nextPublished] = await Promise.all([
        api.courses(),
        teacherMembership
          ? api.publishedAgents(teacherMembership.course_id)
          : Promise.resolve([]),
      ]);
      setCourse(
        courses.find((item) => item.id === teacherMembership?.course_id) ??
          courses[0] ??
          null,
      );
      setPublished(nextPublished);
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
        description={t("teacherCourseLede")}
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
            <PublishedAgentCard item={item} key={item.agent.id} />
          ))}
        </div>
      )}
      <SectionCard
        title={t("teacherBoundary")}
        description={t("teacherBoundaryLede")}
      >
        <div className="teaching-note-grid">
          <div>
            <span className="feature-index">01</span>
            <h3>{t("currentRelease")}</h3>
            <p>{t("currentReleaseTeacher")}</p>
          </div>
          <div>
            <span className="feature-index">02</span>
            <h3>{t("history")}</h3>
            <p>{t("historyTeacher")}</p>
          </div>
          <div>
            <span className="feature-index">03</span>
            <h3>{t("snapshot")}</h3>
            <p>{t("snapshotTeacher")}</p>
          </div>
        </div>
      </SectionCard>
    </>
  );
}

function PublishedAgentCard({ item }: { item: PublishedAgentSummary }) {
  const t = useT();
  const version = item.current_version;
  return (
    <Link className="published-card" href={`/teacher/agents/${item.agent.id}`}>
      <div className="published-card-top">
        <div className="avatar-orb" aria-hidden="true">
          {item.agent.name.slice(0, 1).toUpperCase()}
        </div>
        <div>
          <div className="chip-row">
            <StatusBadge status={item.agent.status} />
            <StatusBadge status={version.state} />
          </div>
          <h2>{item.agent.name}</h2>
          <p>{item.agent.description || t("noDescriptionProvided")}</p>
        </div>
        <span className="row-arrow" aria-hidden="true">
          →
        </span>
      </div>
      <div className="published-card-meta">
        <span>{version.version_label}</span>
        <span>
          {version.enabled_documents?.length ?? 0} {t("evidenceFiles")}
        </span>
        <span>
          {version.voice_fallback_active
            ? t("platformVoiceFallback")
            : t("customVoiceReady")}
        </span>
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
      const nextVersions = await api.versions(agentId);
      setAgent(nextAgent);
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
      const text = await api.downloadSnapshot(snapshot.id);
      setSnapshotText(text);
      setDownloadedSnapshotId(snapshot.id);
      downloadText(
        text,
        `${currentAgent.name}-${snapshot.id.slice(0, 8)}-RAG.md`,
      );
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }
  async function downloadDocument(
    snapshotDocumentId: string,
    filename: string,
  ) {
    if (!snapshot) return;
    setBusy(true);
    try {
      const text = await api.downloadSnapshotDocument(
        snapshot.id,
        snapshotDocumentId,
      );
      downloadText(text, filename);
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
        description={t("teacherReadOnly")}
        action={
          <Link className="secondary-action" href="/teacher">
            {t("backPublished")}
          </Link>
        }
      />
      {agent.status === "archived" ? (
        <div className="notice notice-warning">
          <strong>{t("archivedAgent")}</strong>
          <span>{t("archivedLede")}</span>
        </div>
      ) : null}
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}
      <div className="teacher-detail-grid">
        <div>
          <SectionCard
            title={t("currentRelease")}
            description={t("currentPointerLede")}
          >
            {currentVersion ? (
              <TeacherVersion
                version={currentVersion}
                selected={currentVersion.id === selectedVersionId}
              />
            ) : (
              <EmptyCard title={t("noCurrentPublished")} />
            )}
          </SectionCard>
          <SectionCard
            title={t("publishedHistory")}
            description={t("publishedHistoryLede")}
          >
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
          <SectionCard
            title={t("knowledgeSnapshot")}
            description={t("snapshotOnlyPublish")}
          >
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
                        onClick={() =>
                          void downloadDocument(
                            document.id,
                            document.source_filename,
                          )
                        }
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
          <SectionCard title={t("whyMatters")}>
            <p className="teaching-copy">{t("whyMattersCopy")}</p>
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
