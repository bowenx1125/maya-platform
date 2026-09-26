"use client";

import { WorkspaceAction } from "./workspace-actions";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import {
  PlatformApiError,
  isAmbiguousMutationFailure,
  isConflict,
  type IdempotencyHandle,
  type AgentDetail,
  type AgentVersion,
  type AvatarTemplate,
  type KnowledgeDocument,
  type KnowledgeSnapshot,
  type RagPreview,
  type VoiceProfile,
} from "../lib/api";
import { useIdempotencyStore } from "../lib/idempotency";
import { blockerLabel, statusLabel, type MessageKey } from "../lib/i18n";
import { useLocale, useT } from "./locale";
import { AvatarEditor, type AvatarConfig } from "./avatar";
import { buildAgentTemplate } from "./agent-template";
import { IconDownload } from "./quiet-icons";
import { ReportMarkdown } from "./report/report-markdown";
import { useSession } from "./session-provider";
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
  StatusBadge,
} from "./ui";

export function AgentOverview({ agentId }: { agentId: string }) {
  const t = useT();
  const { api } = useSession();
  const router = useRouter();
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [versions, setVersions] = useState<AgentVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [retryAction, setRetryAction] = useState<
    "delete" | "nextVersion" | null
  >(null);
  const mutationStore = useIdempotencyStore();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextAgent, nextVersions] = await Promise.all([
        api.agent(agentId),
        api.versions(agentId),
      ]);
      setAgent(nextAgent);
      setVersions(nextVersions);
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [agentId, api]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function createNextVersion() {
    const intent = "agent-next-version:" + agentId;
    const handle = mutationStore.handleFor(intent);
    setBusy(true);
    setError(null);
    setRetryAction(null);
    try {
      const next = await api.nextVersion(agentId, { idempotency: handle });
      mutationStore.finish(intent, handle);
      router.push("/student/agent-versions/" + next.id + "/edit");
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) setRetryAction("nextVersion");
      else mutationStore.abandon(intent, handle);
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function deleteAgent(retry = false) {
    if (!agent || (!retry && !window.confirm(t("deleteAgentConfirm")))) return;
    const intent = "agent-delete:" + agentId;
    const handle = mutationStore.handleFor(intent);
    setBusy(true);
    setError(null);
    setRetryAction(null);
    try {
      await api.deleteAgent(agentId, { idempotency: handle });
      mutationStore.finish(intent, handle);
      router.replace("/student/groups/" + agent.group_id);
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) setRetryAction("delete");
      else mutationStore.abandon(intent, handle);
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingCard />;
  if (!agent)
    return (
      <ErrorNotice
        error={error ?? new Error(t("agentNotFound"))}
        onRetry={() => void load()}
      />
    );
  const draft =
    versions.find((version) => version.id === agent.current_draft_version_id) ??
    versions.find((version) => version.state === "draft");
  const current =
    versions.find(
      (version) => version.id === agent.current_published_version_id,
    ) ?? versions.find((version) => version.state === "published");
  const visible = current ?? draft;
  const canDelete =
    !agent.current_published_version_id &&
    versions.every(
      (version) => version.state === "draft" && !version.knowledge_snapshot_id,
    );
  const actions = (
    <div className="button-row">
      {draft && !current ? (
        <Link
          className="secondary-action"
          href={"/student/agent-versions/" + draft.id + "/edit"}
        >
          {t("edit")}
        </Link>
      ) : null}
      {canDelete ? (
        <button
          className="text-link danger-button"
          type="button"
          disabled={busy}
          onClick={() => void deleteAgent()}
        >
          {t("deleteAgent")}
        </button>
      ) : null}
    </div>
  );
  return (
    <>
      {error ? (
        <ErrorNotice
          error={error}
          onRetry={
            retryAction === "delete"
              ? () => void deleteAgent(true)
              : retryAction === "nextVersion"
                ? () => void createNextVersion()
                : () => void load()
          }
        />
      ) : null}
      {current ? (
        <WorkspaceAction
          name="new"
          disabled={busy || agent.status === "archived"}
          href={
            draft ? "/student/agent-versions/" + draft.id + "/edit" : undefined
          }
          onClick={draft ? undefined : () => void createNextVersion()}
        />
      ) : null}
      {visible ? (
        <ReadOnlyVersion version={visible} agent={agent} actions={actions} />
      ) : (
        <SectionCard action={actions}>
          <WorkspaceAction
            name="back"
            href={`/student/groups/${agent.group_id}`}
          />
          <EmptyCard title={t("noVersions")} />
        </SectionCard>
      )}
    </>
  );
}

export function AgentWorkbench({ versionId }: { versionId: string }) {
  const t = useT();
  const router = useRouter();
  const { locale } = useLocale();
  const { api } = useSession();
  const [version, setVersion] = useState<AgentVersion | null>(null);
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [preview, setPreview] = useState<RagPreview | null>(null);
  const [avatarTemplates, setAvatarTemplates] = useState<AvatarTemplate[]>([]);
  const [voiceProfiles, setVoiceProfiles] = useState<VoiceProfile[]>([]);
  const [avatarConfig, setAvatarConfig] = useState<AvatarConfig | null>(null);
  const [voiceProfileId, setVoiceProfileId] = useState<string | null>(null);
  const [agentMd, setAgentMd] = useState("");
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState<MessageKey | null>(null);
  const mutationStore = useIdempotencyStore();
  const [retryAction, setRetryAction] = useState<
    "uploadKnowledge" | "publish" | null
  >(null);
  const [providerConfirmationRequired, setProviderConfirmationRequired] =
    useState(false);
  const [pendingKnowledgeUpload, setPendingKnowledgeUpload] = useState<{
    file: File;
    signature: string;
  } | null>(null);
  const uploadIntent = `upload-knowledge:${versionId}`;
  const publishIntent = `publish-agent-version:${versionId}`;

  function abandonUploadIntent() {
    mutationStore.abandon(uploadIntent);
    setPendingKnowledgeUpload(null);
    setRetryAction((current) =>
      current === "uploadKnowledge" ? null : current,
    );
  }

  function abandonPublishIntent() {
    mutationStore.abandon(publishIntent);
    setRetryAction((current) => (current === "publish" ? null : current));
  }

  const load = useCallback(
    async (keepLocal = false) => {
      setLoading(true);
      setError(null);
      try {
        const nextVersion = await api.version(versionId);
        const nextAgent = await api.agent(nextVersion.agent_id);
        const [
          nextDocuments,
          nextPreview,
          nextAvatarTemplates,
          nextVoiceProfiles,
        ] = await Promise.all([
          api.knowledge(nextAgent.group_id),
          api.ragPreview(versionId),
          api.avatarTemplates(),
          api.voiceProfiles(nextAgent.group_id),
        ]);
        setVersion(nextVersion);
        setAgent(nextAgent);
        setDocuments(nextDocuments);
        setPreview(nextPreview);
        setAvatarTemplates(nextAvatarTemplates);
        setVoiceProfiles(nextVoiceProfiles);
        if (!keepLocal) {
          setAgentMd(nextVersion.agent_md ?? "");
          setAvatarConfig(nextVersion.avatar_config);
          setVoiceProfileId(nextVersion.voice_profile_id ?? null);
          setSelectedDocumentIds(
            (nextVersion.enabled_documents ?? []).map(
              (document) => document.id,
            ),
          );
          setConflict(false);
        }
      } catch (cause) {
        setError(cause);
      } finally {
        setLoading(false);
      }
    },
    [api, versionId],
  );
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const enabledCount = selectedDocumentIds.length;
  const localDirty = Boolean(
    version &&
    (agentMd !== (version.agent_md ?? "") ||
      JSON.stringify(avatarConfig) !== JSON.stringify(version.avatar_config) ||
      voiceProfileId !== (version.voice_profile_id ?? null)),
  );
  const blockers = version?.publish_blockers ?? [];
  const blockerTitles: Record<string, string> = {
    agent_md_missing: "AGENT.md",
    agent_md_too_large: "AGENT.md",
    rag_missing: t("knowledge"),
    rag_over_limit: t("knowledge"),
    rag_index_pending: t("knowledge"),
    rag_index_failed: t("knowledge"),
    avatar_missing: t("avatarDesign"),
  };

  // The recovery action can be rendered while the previous request is still
  // represented by `error`; keep these bindings initialized for its callback.
  const currentVersion = version as AgentVersion;
  const currentAgent = agent as AgentDetail;
  if (loading) return <LoadingCard />;
  // Keep the loaded workbench mounted for mutation errors so local AGENT.md,
  // avatar/voice edits, selected documents, and retry handles remain visible
  // and usable. A load error without the required records still uses the
  // standalone recovery view below.
  if (!version || !agent)
    return (
      <ErrorNotice
        error={error ?? new Error(t("draftNotFound"))}
        onRetry={
          retryAction === "uploadKnowledge" && pendingKnowledgeUpload
            ? () => void uploadKnowledge(pendingKnowledgeUpload.file)
            : retryAction === "publish"
              ? () => void publish(true)
              : () => void load(Boolean(version && agent))
        }
      />
    );
  if (version.state !== "draft")
    return <ReadOnlyVersion version={version} agent={agent} />;

  async function saveDraft() {
    abandonUploadIntent();
    abandonPublishIntent();
    setSaving(true);
    setError(null);
    setProviderConfirmationRequired(false);
    setNotice(null);
    setConflict(false);
    try {
      const next = await api.updateDraft(currentVersion.id, {
        expected_revision: currentVersion.revision,
        agent_md: agentMd,
        ...(avatarConfig ? { avatar_config: avatarConfig } : {}),
        voice_profile_id: voiceProfileId,
      });
      setVersion(next);
      setAgentMd(next.agent_md ?? "");
      setAvatarConfig(next.avatar_config);
      setVoiceProfileId(next.voice_profile_id ?? null);
      setNotice("draftSavedNotice");
      return next;
    } catch (cause) {
      if (isConflict(cause)) setConflict(true);
      setError(cause);
    } finally {
      setSaving(false);
    }
  }

  async function uploadAgentMd(file: File) {
    abandonUploadIntent();
    abandonPublishIntent();
    setSaving(true);
    setError(null);
    setNotice(null);
    setConflict(false);
    try {
      const next = await api.uploadAgentMd(
        currentVersion.id,
        file,
        currentVersion.revision,
      );
      setVersion(next);
      setAgentMd(next.agent_md ?? "");
      setNotice("agentMdUploadedNotice");
    } catch (cause) {
      if (isConflict(cause)) setConflict(true);
      setError(cause);
    } finally {
      setSaving(false);
    }
  }

  async function toggleDocument(documentId: string, enabled: boolean) {
    abandonUploadIntent();
    abandonPublishIntent();
    const nextIds = enabled
      ? [...selectedDocumentIds, documentId]
      : selectedDocumentIds.filter((id) => id !== documentId);
    setSelectedDocumentIds(nextIds);
    setSaving(true);
    setError(null);
    setNotice(null);
    setConflict(false);
    try {
      const next = await api.setDocuments(
        currentVersion.id,
        currentVersion.revision,
        nextIds,
      );
      setVersion(next);
      setSelectedDocumentIds(
        (next.enabled_documents ?? []).map((document) => document.id),
      );
      setNotice("evidenceUpdatedNotice");
      const nextPreview = await api.ragPreview(currentVersion.id);
      setPreview(nextPreview);
    } catch (cause) {
      if (isConflict(cause)) {
        setConflict(true);
        setSelectedDocumentIds(selectedDocumentIds);
      }
      setError(cause);
    } finally {
      setSaving(false);
    }
  }

  async function uploadKnowledge(file: File) {
    const signature = `${file.name}:${file.size}:${file.lastModified}`;
    if (pendingKnowledgeUpload?.signature !== signature) {
      mutationStore.abandon(uploadIntent);
    }
    abandonPublishIntent();
    setPendingKnowledgeUpload({ file, signature });
    setSaving(true);
    setError(null);
    setNotice(null);
    setConflict(false);
    let mutationCompleted = false;
    const handle = mutationStore.handleFor(uploadIntent);
    try {
      const mutation = await api.uploadKnowledge(
        currentAgent.group_id,
        currentVersion.id,
        file,
        currentVersion.revision,
        { idempotency: handle },
      );
      mutationStore.finish(uploadIntent, handle);
      mutationCompleted = true;
      setPendingKnowledgeUpload((current) =>
        current?.signature === signature ? null : current,
      );
      setRetryAction(null);
      setVersion(mutation.agent_version);
      setDocuments((current) => [...current, mutation.document]);
      setSelectedDocumentIds((current) =>
        current.includes(mutation.document.id)
          ? current
          : [...current, mutation.document.id],
      );
      setNotice("markdownUploadedNotice");
      setPreview(await api.ragPreview(currentVersion.id));
    } catch (cause) {
      if (!mutationCompleted && isConflict(cause)) {
        mutationStore.abandon(uploadIntent, handle);
        setPendingKnowledgeUpload((current) =>
          current?.signature === signature ? null : current,
        );
        setRetryAction(null);
      } else if (!mutationCompleted && isAmbiguousMutationFailure(cause)) {
        setRetryAction("uploadKnowledge");
      } else if (!mutationCompleted) {
        mutationStore.abandon(uploadIntent, handle);
        setPendingKnowledgeUpload((current) =>
          current?.signature === signature ? null : current,
        );
        setRetryAction(null);
      }
      if (isConflict(cause)) setConflict(true);
      setError(cause);
    } finally {
      setSaving(false);
    }
  }

  async function publish(retry = false) {
    // The server only knows the last saved revision.  Never publish it while
    // the browser still holds newer AGENT/avatar/voice values.
    const saved = localDirty ? await saveDraft() : currentVersion;
    if (!saved || (saved.publish_blockers ?? []).length > 0) return;
    if (!retry) abandonUploadIntent();
    setSaving(true);
    setError(null);
    setProviderConfirmationRequired(false);
    setNotice(null);
    const handle = mutationStore.handleFor(publishIntent);
    try {
      const next = await api.publish(saved.id, saved.revision, {
        idempotency: handle,
      });
      mutationStore.finish(publishIntent, handle);
      setRetryAction(null);
      setVersion(next);
      setNotice("publishedNotice");
      router.replace(`/student/agents/${currentAgent.id}`);
    } catch (cause) {
      setProviderConfirmationRequired(
        cause instanceof PlatformApiError &&
          cause.code === "provider_confirmation_required",
      );
      if (isConflict(cause)) setConflict(true);
      if (isAmbiguousMutationFailure(cause)) {
        setRetryAction("publish");
      } else {
        mutationStore.abandon(publishIntent, handle);
        setRetryAction(null);
      }
      setError(cause);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageIntro title={`${agent.name} · ${version.version_label}`} />
      <WorkspaceAction
        name="back"
        href={`/student/agents/${agent.id}`}
        disabled={saving}
        onClick={(event) => {
          if (localDirty && !window.confirm(t("discardDraftConfirm")))
            event.preventDefault();
        }}
      />
      <WorkspaceAction
        name="done"
        disabled={saving || (!localDirty && blockers.length > 0)}
        onClick={() => void publish()}
      />
      <div className="workbench-meta">
        <StatusBadge status="draft" />
        {localDirty ? (
          <span className="dirty-label" role="status">
            {t("unsavedChanges")}
          </span>
        ) : null}
      </div>
      {conflict ? <DraftConflictNotice /> : null}
      {error && !conflict ? (
        <>
          <ErrorNotice
            error={error}
            onRetry={
              retryAction === "uploadKnowledge" && pendingKnowledgeUpload
                ? () => void uploadKnowledge(pendingKnowledgeUpload.file)
                : retryAction === "publish"
                  ? () => {
                      void publish(true);
                    }
                  : () => void load(true)
            }
          />
        </>
      ) : null}
      {providerConfirmationRequired ? (
        <div className="notice notice-warning" role="status">
          <strong>{t("providerConfirmationNeeded")}</strong>

          <Link
            className="text-link"
            href={`/teacher/provider-approvals/agent-versions/${currentVersion.id}`}
          >
            {t("openProviderDisclosure")}
          </Link>
        </div>
      ) : null}
      {notice ? (
        <div className="notice notice-success" role="status">
          <strong>{t("done")}</strong>
          <span>{t(notice)}</span>
        </div>
      ) : null}
      <div className="workbench-grid">
        <div className="workbench-main">
          <SectionCard
            title={t("agentMd")}
            guide="agent.markdown"
            action={
              <div className="button-row">
                <button
                  className="secondary-action"
                  type="button"
                  disabled={saving}
                  onClick={() => {
                    abandonUploadIntent();
                    abandonPublishIntent();
                    setAgentMd(buildAgentTemplate(agent.name, locale));
                  }}
                >
                  {t("insertOutline")}
                </button>
                <label className="secondary-action file-button">
                  {t("uploadMd")}
                  <input
                    type="file"
                    accept=".md,text/markdown"
                    disabled={saving}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) void uploadAgentMd(file);
                      event.currentTarget.value = "";
                    }}
                  />
                </label>
              </div>
            }
          >
            <textarea
              className="markdown-editor"
              aria-label={`${t("agentMd")} ${t("editor")}`}
              maxLength={12000}
              value={agentMd}
              disabled={saving}
              onChange={(event) => {
                abandonUploadIntent();
                abandonPublishIntent();
                setAgentMd(event.target.value);
              }}
            />
            <div className="editor-footer">
              <span>
                {agentMd.length.toLocaleString()} / 12,000 {t("characters")}
              </span>
            </div>
          </SectionCard>
          {avatarConfig ? (
            <SectionCard title={t("avatarDesign")}>
              <AvatarEditor
                templates={avatarTemplates}
                value={avatarConfig}
                onChange={setAvatarConfig}
                fallbackLabel={agent.name}
                disabled={saving}
              />
            </SectionCard>
          ) : null}
          <SectionCard
            title={t("voiceBinding")}
            guide="agent.voice"
            action={
              <Link
                className="text-link"
                href={`/student/groups/${agent.group_id}/voices`}
              >
                {t("manageVoices")}
              </Link>
            }
          >
            <div className="stack-form">
              <label>
                <span>{t("voiceBinding")}</span>
                <select
                  value={voiceProfileId ?? ""}
                  disabled={saving}
                  onChange={(event) =>
                    setVoiceProfileId(event.target.value || null)
                  }
                >
                  <option value="">{t("useFallbackVoice")}</option>
                  {voiceProfiles
                    .filter((profile) => profile.status === "ready")
                    .map((profile) => (
                      <option key={profile.id} value={profile.id}>
                        {profile.source_filename || t("customVoiceReady")}
                      </option>
                    ))}
                </select>
              </label>
            </div>
          </SectionCard>
          <SectionCard
            title={t("evidenceSet")}
            guide="agent.evidence"
            action={
              <label className="secondary-action file-button">
                {t("uploadMarkdown")}
                <input
                  type="file"
                  accept=".md,text/markdown"
                  disabled={saving}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) void uploadKnowledge(file);
                    event.currentTarget.value = "";
                  }}
                />
              </label>
            }
          >
            {documents.length === 0 ? (
              <p className="muted-copy">{t("noGroupMarkdown")}</p>
            ) : (
              <div className="document-list">
                {documents.map((document) => (
                  <label
                    className={`document-row ${document.workspace_state === "hidden" ? "is-hidden" : ""}`}
                    key={document.id}
                  >
                    <input
                      type="checkbox"
                      checked={selectedDocumentIds.includes(document.id)}
                      disabled={saving || document.workspace_state === "hidden"}
                      onChange={(event) =>
                        void toggleDocument(document.id, event.target.checked)
                      }
                    />
                    <span className="document-main">
                      <strong>{document.source_filename}</strong>
                      <small>
                        {document.char_count.toLocaleString()} {t("characters")}{" "}
                        ·{" "}
                        {document.workspace_state === "hidden"
                          ? t("hiddenWorkspace")
                          : t("groupMarkdown")}
                      </small>
                    </span>
                    <StatusBadge
                      status={document.index_status}
                      tone={
                        document.index_status === "ready"
                          ? "good"
                          : document.index_status === "failed"
                            ? "bad"
                            : "warn"
                      }
                    />
                  </label>
                ))}
              </div>
            )}
          </SectionCard>
        </div>
        <aside className="workbench-side">
          <SectionCard title={t("publishChecklist")} guide="agent.publish">
            <div className="checklist">
              {blockers.length === 0 ? (
                <div className="check-item check-good">
                  <span aria-hidden="true">✓</span>
                  <div>
                    <strong>{t("readyPublish")}</strong>
                  </div>
                </div>
              ) : (
                blockers.map((blocker) => (
                  <div className="check-item check-bad" key={blocker}>
                    <span aria-hidden="true">!</span>
                    <div>
                      <strong>
                        {blockerTitles[blocker] ??
                          blockerLabel(blocker, locale)}
                      </strong>
                    </div>
                  </div>
                ))
              )}
            </div>
          </SectionCard>
          <SectionCard title={t("ragPreview")} guide="agent.ragPreview">
            {preview ? (
              <>
                <div className="rag-metrics">
                  <div>
                    <strong>{preview.document_count}</strong>
                    <span>{t("files")}</span>
                  </div>
                  <div>
                    <strong>{preview.total_char_count.toLocaleString()}</strong>
                    <span>{t("characters")}</span>
                  </div>
                  <StatusBadge status={preview.index_status} />
                </div>
                <pre className="rag-preview">
                  {preview.combined_markdown || t("previewAfterIndex")}
                </pre>
              </>
            ) : (
              <LoadingCard label={t("preparingPreview")} />
            )}
          </SectionCard>
        </aside>
      </div>
    </>
  );
}

export function preserveDraftOnRetry(error: unknown): boolean {
  return isConflict(error);
}

export function DraftConflictNotice() {
  const t = useT();
  return (
    <div className="notice notice-warning" role="alert">
      <strong>{t("revisionConflict")}</strong>
      <span>{t("conflictDetail")}</span>
    </div>
  );
}

function ReadOnlyVersion({
  version,
  agent,
  actions,
}: {
  version: AgentVersion;
  agent: AgentDetail;
  actions?: ReactNode;
}) {
  const t = useT();
  const { locale } = useLocale();
  const { api } = useSession();
  const [agentMdBusy, setAgentMdBusy] = useState(false);
  const [agentMdError, setAgentMdError] = useState<unknown>(null);

  async function downloadAgentMd() {
    setAgentMdBusy(true);
    setAgentMdError(null);
    try {
      const downloaded = await api.downloadAgentMd(version.id);
      downloadText(downloaded.content, downloaded.filename);
    } catch (cause) {
      setAgentMdError(cause);
    } finally {
      setAgentMdBusy(false);
    }
  }

  async function downloadEvidence() {
    const documents = version.enabled_documents ?? [];
    if (documents.length === 0) return;
    setAgentMdBusy(true);
    setAgentMdError(null);
    try {
      for (const document of documents) {
        const downloaded = await api.downloadKnowledge(
          document.id,
          document.source_filename,
        );
        downloadText(downloaded.content, downloaded.filename);
      }
    } catch (cause) {
      setAgentMdError(cause);
    } finally {
      setAgentMdBusy(false);
    }
  }

  const downloadAction = (
    <button
      className="icon-action"
      type="button"
      disabled={agentMdBusy}
      aria-label={`${t("download")} AGENT.md`}
      data-ui-guide="agent.download"
      onClick={() => void downloadAgentMd()}
    >
      <IconDownload />
    </button>
  );

  return (
    <>
      <PageIntro title={`${agent.name} · ${version.version_label}`} />
      <WorkspaceAction name="back" href={`/student/groups/${agent.group_id}`} />
      <div className="workbench-grid">
        <div className="workbench-main">
          <SectionCard
            title={t("agentMd")}
            guide="agent.markdown"
            action={
              <>
                {actions}
                {downloadAction}
              </>
            }
          >
            <ReportMarkdown className="read-only-markdown rendered-persona">
              {version.agent_md || t("noPrompt")}
            </ReportMarkdown>
            {agentMdError ? <ErrorNotice error={agentMdError} /> : null}
          </SectionCard>
          <SectionCard
            title={t("enabledEvidence")}
            guide="agent.evidence"
            action={
              (version.enabled_documents ?? []).length > 0 ? (
                <button
                  className="icon-action"
                  type="button"
                  disabled={agentMdBusy}
                  aria-label={t("download")}
                  data-ui-guide="agent.download"
                  onClick={() => void downloadEvidence()}
                >
                  <IconDownload />
                </button>
              ) : null
            }
          >
            <div className="document-list">
              {(version.enabled_documents ?? []).map((document) => (
                <div className="document-row" key={document.id}>
                  <span className="document-main">
                    <strong>{document.source_filename}</strong>
                    <small>
                      {document.char_count.toLocaleString()} {t("characters")}
                    </small>
                  </span>
                  <StatusBadge status={document.index_status} />
                </div>
              ))}
              {(version.enabled_documents ?? []).length === 0 ? (
                <p className="muted-copy">{t("noEvidence")}</p>
              ) : null}
            </div>
          </SectionCard>
        </div>
        <aside className="workbench-side">
          <SectionCard title={t("releaseState")}>
            <div className="check-item check-good">
              <span aria-hidden="true">✓</span>
              <div>
                <strong>{statusLabel(version.state, locale)}</strong>
                <small>
                  {t("revision")} {version.revision}
                </small>
              </div>
            </div>
          </SectionCard>
          {version.knowledge_snapshot_id ? (
            <StudentSnapshot snapshotId={version.knowledge_snapshot_id} />
          ) : null}
        </aside>
      </div>
    </>
  );
}

export function StudentPublishedVersion({ versionId }: { versionId: string }) {
  const t = useT();
  const { api } = useSession();
  const [version, setVersion] = useState<AgentVersion | null>(null);
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextVersion = await api.version(versionId);
      const nextAgent = await api.agent(nextVersion.agent_id);
      setVersion(nextVersion);
      setAgent(nextAgent);
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [api, versionId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading) return <LoadingCard />;
  if (error || !version || !agent)
    return (
      <ErrorNotice
        error={error ?? new Error(t("publishedVersionNotFound"))}
        onRetry={() => void load()}
      />
    );
  return <ReadOnlyVersion version={version} agent={agent} />;
}

function StudentSnapshot({ snapshotId }: { snapshotId: string }) {
  const t = useT();
  const { api } = useSession();
  const [snapshot, setSnapshot] = useState<KnowledgeSnapshot | null>(null);
  const [snapshotText, setSnapshotText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setSnapshot(null);
      setSnapshotText(null);
      void api
        .snapshot(snapshotId)
        .then((next) => {
          if (!cancelled) {
            setSnapshot(next);
            setSnapshotText(null);
            setError(null);
          }
        })
        .catch((cause) => {
          if (!cancelled) setError(cause);
        });
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [api, snapshotId]);

  async function downloadSnapshot() {
    setBusy(true);
    setError(null);
    try {
      const downloaded = await api.downloadSnapshot(snapshotId);
      setSnapshotText(downloaded.content);
      downloadText(downloaded.content, downloaded.filename);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function downloadDocument(snapshotDocumentId: string) {
    setBusy(true);
    setError(null);
    try {
      const downloaded = await api.downloadSnapshotDocument(
        snapshotId,
        snapshotDocumentId,
      );
      downloadText(downloaded.content, downloaded.filename);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  if (error)
    return (
      <SectionCard title={t("knowledgeSnapshot")} guide="agent.snapshot">
        <ErrorNotice error={error} />
      </SectionCard>
    );
  return (
    <SectionCard
      title={t("knowledgeSnapshot")}
      guide="agent.snapshot"
      action={
        snapshot ? (
          <button
            className="icon-action"
            type="button"
            disabled={busy}
            aria-label={`${t("download")} RAG`}
            data-ui-guide="agent.download"
            onClick={() => void downloadSnapshot()}
          >
            <IconDownload />
          </button>
        ) : null
      }
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
                {snapshot.total_char_count.toLocaleString()} {t("characters")}
              </strong>
            </div>
            <div>
              <span className="section-label">{t("files")}</span>
              <strong>{snapshot.documents.length}</strong>
            </div>
          </div>
          <div className="snapshot-files">
            {snapshot.documents.map((document) => (
              <div className="snapshot-file" key={document.id}>
                <span>
                  <strong>{document.source_filename}</strong>
                  <small>
                    {document.char_count.toLocaleString()} {t("characters")}
                  </small>
                </span>
                <button
                  className="icon-action"
                  type="button"
                  disabled={busy}
                  aria-label={t("download")}
                  data-ui-guide="agent.download"
                  onClick={() => void downloadDocument(document.id)}
                >
                  <IconDownload />
                </button>
              </div>
            ))}
          </div>
          {snapshotText ? (
            <pre className="snapshot-preview">{snapshotText}</pre>
          ) : null}
        </>
      ) : (
        <LoadingCard label={t("loadingSnapshot")} />
      )}
    </SectionCard>
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
