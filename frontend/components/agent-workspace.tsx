"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { FormEvent, MouseEvent, ReactNode } from "react";

import {
  PlatformApiError,
  isAmbiguousMutationFailure,
  isConflict,
  type IdempotencyHandle,
  type PlatformApi,
  type AgentDetail,
  type AgentVersion,
  type AvatarTemplate,
  type KnowledgeDocument,
  type KnowledgeSnapshot,
  type RagPreview,
  type TestChatResponse,
  type VoiceProfile,
} from "../lib/api";
import { useIdempotencyStore } from "../lib/idempotency";
import {
  AGENT_OUTLINE,
  blockerLabel,
  statusLabel,
  type MessageKey,
} from "../lib/i18n";
import { useLocale, useT } from "./locale";
import { AvatarEditor, type AvatarConfig } from "./avatar";
import {
  PersonaPreview,
  type PersonaPreviewDiagnostic,
  type PersonaPreviewSpec,
} from "./persona";
import { useSession } from "./session-provider";
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
  StatusBadge,
} from "./ui";

type AgentDetailWithMetadata = AgentDetail & {
  metadata_revision?: number;
};

type PersonaVersionFields = {
  persona_spec_json?: unknown;
  persona_spec?: unknown;
  previous_persona_spec_json?: unknown;
  persona_diagnostics?: readonly PersonaPreviewDiagnostic[];
  persona_diagnostics_json?: unknown;
  persona_confirmation_revision?: number | null;
  student_confirmed_at?: string | null;
};

type AgentMetadataApi = PlatformApi & {
  updateAgentMetadata: (
    agentId: string,
    body: {
      expected_metadata_revision: number;
      description: string | null;
    },
  ) => Promise<AgentDetail>;
  deleteAgent: (
    agentId: string,
    options?: { idempotency?: IdempotencyHandle },
  ) => Promise<unknown>;
};

function isMetadataRevisionConflict(error: unknown): boolean {
  return (
    error instanceof PlatformApiError &&
    error.status === 409 &&
    error.code === "stale_metadata_revision"
  );
}

export function AgentOverview({ agentId }: { agentId: string }) {
  const t = useT();
  const { api } = useSession();
  const router = useRouter();
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [versions, setVersions] = useState<AgentVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const [editingDescription, setEditingDescription] = useState(false);
  const [descriptionSaving, setDescriptionSaving] = useState(false);
  const [metadataConflict, setMetadataConflict] = useState(false);
  const mutationStore = useIdempotencyStore();
  const [retryAction, setRetryAction] = useState<
    "delete" | "nextVersion" | null
  >(null);
  const deleteIntent = `agent-delete:${agentId}`;
  const nextVersionIntent = `agent-next-version:${agentId}`;
  const metadataApi = api as AgentMetadataApi;
  // Recovery callbacks can render while an action error is present, before
  // the normal loaded-view narrowing below.
  const currentAgent = agent as AgentDetail;

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
      setDescriptionDraft(nextAgent.description ?? "");
      setEditingDescription(false);
      setMetadataConflict(false);
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [agentId, api]);
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
        error={error ?? new Error(t("agentNotFound"))}
        onRetry={
          retryAction === "delete"
            ? () => void deleteAgent(true)
            : retryAction === "nextVersion"
              ? () => void createNextVersion()
              : () => void load()
        }
      />
    );

  const draft =
    versions.find((version) => version.state === "draft") ??
    versions.find((version) => version.id === agent.current_draft_version_id);
  const current =
    versions.find(
      (version) => version.id === agent.current_published_version_id,
    ) ?? versions.find((version) => version.state === "published");
  const descriptionDirty =
    descriptionDraft !== (currentAgent.description ?? "");
  const canHardDelete =
    !currentAgent.current_published_version_id &&
    versions.every(
      (version) =>
        version.state === "draft" && version.knowledge_snapshot_id == null,
    );

  function abandonDeleteIntent() {
    mutationStore.abandon(deleteIntent);
  }

  async function deleteAgent(retry = false) {
    if (
      !retry &&
      descriptionDirty &&
      !window.confirm(t("discardDescriptionConfirm"))
    )
      return;
    if (!retry && !window.confirm(t("deleteAgentConfirm"))) return;
    if (!retry) {
      abandonDeleteIntent();
      mutationStore.abandon(nextVersionIntent);
    }
    setBusy(true);
    setError(null);
    setRetryAction(null);
    setMetadataConflict(false);
    const handle = mutationStore.handleFor(deleteIntent);
    try {
      await metadataApi.deleteAgent(currentAgent.id, { idempotency: handle });
      mutationStore.finish(deleteIntent, handle);
      router.replace(`/student/groups/${currentAgent.group_id}`);
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) {
        setRetryAction("delete");
      } else {
        mutationStore.abandon(deleteIntent, handle);
      }
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function createNextVersion() {
    abandonDeleteIntent();
    const handle = mutationStore.handleFor(nextVersionIntent);
    setBusy(true);
    setError(null);
    setRetryAction(null);
    try {
      const next = await api.nextVersion(currentAgent.id, {
        idempotency: handle,
      });
      mutationStore.finish(nextVersionIntent, handle);
      router.push(`/student/agent-versions/${next.id}/edit`);
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) {
        setRetryAction("nextVersion");
      } else {
        mutationStore.abandon(nextVersionIntent, handle);
      }
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function saveDescription() {
    if (!descriptionDirty) {
      setEditingDescription(false);
      return;
    }
    setDescriptionSaving(true);
    setError(null);
    setRetryAction(null);
    setMetadataConflict(false);
    const localDraft = descriptionDraft;
    try {
      const next = await metadataApi.updateAgentMetadata(currentAgent.id, {
        expected_metadata_revision:
          (currentAgent as AgentDetailWithMetadata).metadata_revision ?? 0,
        description: descriptionDraft,
      });
      setAgent(next);
      setDescriptionDraft(next.description ?? "");
      setEditingDescription(false);
    } catch (cause) {
      if (isMetadataRevisionConflict(cause)) {
        try {
          const authoritative = await metadataApi.agent(currentAgent.id);
          setAgent(authoritative);
          setDescriptionDraft(localDraft);
          setEditingDescription(true);
          setMetadataConflict(true);
          setError(null);
        } catch (refreshError) {
          setError(refreshError);
        }
      } else {
        setError(cause);
      }
    } finally {
      setDescriptionSaving(false);
    }
  }

  function cancelDescription() {
    setDescriptionDraft(currentAgent.description ?? "");
    setEditingDescription(false);
    setMetadataConflict(false);
    setError(null);
  }

  function returnToGroup(event: MouseEvent<HTMLAnchorElement>) {
    if (descriptionDirty && !window.confirm(t("discardDescriptionConfirm"))) {
      event.preventDefault();
    }
  }

  return (
    <>
      <PageIntro
        eyebrow={t("agentWorkspace")}
        title={agent.name}
        description={agent.description}
        action={
          <div className="button-row">
            <Link
              className="secondary-action"
              href={`/student/groups/${agent.group_id}`}
              onClick={returnToGroup}
            >
              {t("returnWorkspace")}
            </Link>
            {canHardDelete ? (
              <button
                className="secondary-action"
                type="button"
                disabled={busy || descriptionSaving}
                onClick={() => void deleteAgent()}
              >
                {t("deleteAgent")}
              </button>
            ) : null}
            {draft ? (
              <Link
                className="primary-action"
                href={`/student/agent-versions/${draft.id}/edit`}
              >
                {t("continueDraft")}
              </Link>
            ) : current ? (
              <button
                className="primary-action"
                type="button"
                disabled={busy || agent.status === "archived"}
                onClick={() => void createNextVersion()}
              >
                {t("createNextVersion")}
              </button>
            ) : null}
          </div>
        }
      />
      {error ? (
        <ErrorNotice
          error={error}
          onRetry={
            isMetadataRevisionConflict(error)
              ? undefined
              : retryAction === "delete"
                ? () => void deleteAgent(true)
                : retryAction === "nextVersion"
                  ? () => void createNextVersion()
                  : () => void load()
          }
        />
      ) : null}
      {metadataConflict ? (
        <div className="notice notice-warning" role="alert">
          {t("metadataConflict")}
        </div>
      ) : null}
      <SectionCard title={t("description")}>
        {editingDescription ? (
          <div className="stack-form">
            <label>
              <span>{t("shortDescription")}</span>
              <textarea
                aria-label={t("description")}
                value={descriptionDraft}
                rows={4}
                disabled={descriptionSaving}
                onChange={(event) => setDescriptionDraft(event.target.value)}
              />
            </label>
            <div className="button-row">
              <button
                className="primary-action"
                type="button"
                disabled={descriptionSaving || !descriptionDirty}
                onClick={() => void saveDescription()}
              >
                {descriptionSaving ? t("saving") : t("saveDescription")}
              </button>
              <button
                className="secondary-action"
                type="button"
                disabled={descriptionSaving}
                onClick={cancelDescription}
              >
                {t("cancel")}
              </button>
            </div>
          </div>
        ) : (
          <button
            className="secondary-action description-edit-trigger"
            type="button"
            aria-label={t("editDescription")}
            onClick={() => setEditingDescription(true)}
          >
            <span>{agent.description}</span>
            <span aria-hidden="true">✎</span>
          </button>
        )}
      </SectionCard>
      <div className="workspace-grid">
        <SectionCard
          title={t("currentRelease")}
          description={t("currentReleaseLede")}
        >
          {current ? (
            <VersionSummary version={current} current />
          ) : (
            <EmptyCard
              title={t("noPublishedYet")}
              action={
                draft ? (
                  <Link
                    className="secondary-action"
                    href={`/student/agent-versions/${draft.id}/edit`}
                  >
                    {t("openV10")}
                  </Link>
                ) : null
              }
            />
          )}
        </SectionCard>
        <SectionCard
          title={t("draftStatus")}
          description={t("draftStatusLede")}
        >
          {draft ? (
            <VersionSummary
              version={draft}
              action={
                <Link
                  className="text-link"
                  href={`/student/agent-versions/${draft.id}/edit`}
                >
                  {t("openWorkbench")}
                </Link>
              }
            />
          ) : (
            <p className="muted-copy">{t("noEditableDraft")}</p>
          )}
        </SectionCard>
      </div>
      <SectionCard
        title={t("versionHistory")}
        description={t("versionHistoryLede")}
      >
        {versions.length === 0 ? (
          <p className="muted-copy">{t("noVersions")}</p>
        ) : (
          <div className="version-list">
            {versions
              .slice()
              .sort((a, b) =>
                b.version_label.localeCompare(a.version_label, undefined, {
                  numeric: true,
                }),
              )
              .map((version) => (
                <VersionSummary
                  key={version.id}
                  version={version}
                  current={version.id === current?.id}
                />
              ))}
          </div>
        )}
      </SectionCard>
    </>
  );
}

function VersionSummary({
  version,
  current = false,
  action,
}: {
  version: AgentVersion;
  current?: boolean;
  action?: ReactNode;
}) {
  const t = useT();
  return (
    <div className="version-summary">
      <div>
        <div className="chip-row">
          <strong>{version.version_label}</strong>
          <StatusBadge status={version.state} />
          {current ? (
            <span className="current-label">{t("current")}</span>
          ) : null}
        </div>
        <p>
          {version.enabled_documents?.length ?? 0} {t("enabledFiles")} ·{" "}
          {t("revision")} {version.revision}
        </p>
      </div>
      {action ??
        (version.state !== "draft" ? (
          <Link
            className="text-link"
            href={`/student/agent-versions/${version.id}`}
          >
            {t("inspectRelease")}
          </Link>
        ) : null)}
    </div>
  );
}

export function AgentWorkbench({ versionId }: { versionId: string }) {
  const t = useT();
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
  const [chatMessage, setChatMessage] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatResult, setChatResult] = useState<TestChatResponse | null>(null);
  const mutationStore = useIdempotencyStore();
  const [retryAction, setRetryAction] = useState<
    "uploadKnowledge" | "publish" | null
  >(null);
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
  const blockerCopy: Record<string, Parameters<typeof t>[0]> = {
    agent_md_missing: "blockAgentMdMissing",
    agent_md_too_large: "blockAgentMdLarge",
    rag_missing: "blockRagMissing",
    rag_over_limit: "blockRagOverLimit",
    rag_index_pending: "blockRagPending",
    rag_index_failed: "blockRagFailed",
    avatar_missing: "blockAvatarMissing",
  };

  // The recovery action can be rendered while the previous request is still
  // represented by `error`; keep these bindings initialized for its callback.
  const currentVersion = version as AgentVersion;
  const currentAgent = agent as AgentDetail;
  const personaVersion = (currentVersion ?? {}) as AgentVersion &
    PersonaVersionFields;
  const structuredPersona =
    localDirty || !version
      ? null
      : parsePersonaSpec(
          personaVersion.persona_spec_json ?? personaVersion.persona_spec,
        );
  const previousPersona = version
    ? parsePersonaSpec(personaVersion.previous_persona_spec_json)
    : null;
  const personaConfirmed = Boolean(
    !localDirty &&
    personaVersion.persona_confirmation_revision != null &&
    personaVersion.student_confirmed_at,
  );

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

  async function askAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!chatMessage.trim()) return;
    setChatBusy(true);
    setError(null);
    try {
      setChatResult(await api.testChat(currentVersion.id, chatMessage.trim()));
    } catch (cause) {
      setError(cause);
    } finally {
      setChatBusy(false);
    }
  }

  async function publish(retry = false) {
    // The server only knows the last saved revision.  Never publish it while
    // the browser still holds newer AGENT/avatar/voice values.
    if (localDirty) return;
    if (blockers.length > 0) return;
    if (!retry) abandonUploadIntent();
    setSaving(true);
    setError(null);
    setNotice(null);
    const handle = mutationStore.handleFor(publishIntent);
    try {
      const next = await api.publish(
        currentVersion.id,
        currentVersion.revision,
        { idempotency: handle },
      );
      mutationStore.finish(publishIntent, handle);
      setRetryAction(null);
      setVersion(next);
      setNotice("publishedNotice");
    } catch (cause) {
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
      <PageIntro
        eyebrow={t("agentWorkbench")}
        title={`${agent.name} · ${version.version_label}`}
        description={t("workbenchLede")}
        action={
          <div className="button-row">
            <Link
              className="secondary-action"
              href={`/student/agents/${agent.id}`}
            >
              {t("backToAgent")}
            </Link>
            <button
              className="primary-action"
              type="button"
              disabled={saving || blockers.length > 0 || localDirty}
              title={localDirty ? t("saveBeforePublish") : undefined}
              onClick={() => void publish()}
            >
              {saving ? t("working") : t("publish")}
            </button>
          </div>
        }
      />
      <div className="workbench-meta">
        <StatusBadge status="draft" />
        <span>
          {t("revision")} {version.revision}
        </span>
        <span>
          {enabledCount} {t("enabledFileCount")}
        </span>
        {localDirty ? (
          <span className="dirty-label" role="status">
            {t("unsavedChanges")}
          </span>
        ) : null}
      </div>
      {localDirty ? (
        <div className="notice notice-warning" role="status" aria-live="polite">
          <strong>{t("unsavedChanges")}</strong>
          <span>{t("saveBeforePublish")}</span>
        </div>
      ) : null}
      {conflict ? (
        <DraftConflictNotice onRefresh={() => void load(true)} />
      ) : null}
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
            description={t("agentMdLede")}
            action={
              <div className="button-row">
                <button
                  className="secondary-action"
                  type="button"
                  onClick={() => {
                    abandonUploadIntent();
                    abandonPublishIntent();
                    setAgentMd(AGENT_OUTLINE);
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
              onChange={(event) => {
                abandonUploadIntent();
                abandonPublishIntent();
                setAgentMd(event.target.value);
              }}
              placeholder={t("writePrompt")}
            />
            <div className="editor-footer">
              <span>
                {agentMd.length.toLocaleString()} / 12,000 {t("characters")}
              </span>
              <button
                className="primary-action compact-action"
                type="button"
                disabled={saving || !localDirty}
                onClick={() => void saveDraft()}
              >
                {saving ? t("saving") : t("save")}
              </button>
            </div>
          </SectionCard>
          <PersonaPreview
            rawAgentMd={agentMd}
            spec={structuredPersona}
            previousSpec={previousPersona}
            diagnostics={
              personaVersion.persona_diagnostics ??
              parsePersonaDiagnostics(personaVersion.persona_diagnostics_json)
            }
            confirmed={personaConfirmed}
          />
          {avatarConfig ? (
            <SectionCard
              title={t("avatarDesign")}
              description={t("avatarDesignLede")}
            >
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
            description={t("voiceBindingLede")}
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
            <p className="muted-copy">
              {voiceProfileId
                ? t("customVoiceReady")
                : t("platformVoiceFallback")}
            </p>
          </SectionCard>
          <SectionCard
            title={t("evidenceSet")}
            description={t("evidenceSetLede")}
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
          <SectionCard
            title={t("testChat")}
            description={t("testChatLede")}
            className="chat-card"
          >
            <form className="chat-form" onSubmit={askAgent}>
              <textarea
                aria-label={t("testChatMessage")}
                value={chatMessage}
                onChange={(event) => setChatMessage(event.target.value)}
                placeholder={t("askEvidence")}
                rows={3}
              />
              <button
                className="primary-action"
                type="submit"
                disabled={chatBusy || !chatMessage.trim()}
              >
                {chatBusy ? t("retrieving") : t("testDraft")}
              </button>
            </form>
            {chatResult ? (
              <ChatResult result={chatResult} />
            ) : (
              <p className="muted-copy">{t("tryChat")}</p>
            )}
          </SectionCard>
        </div>
        <aside className="workbench-side">
          <SectionCard
            title={t("publishChecklist")}
            description={t("checklistLede")}
          >
            <div className="checklist">
              {blockers.length === 0 ? (
                <div className="check-item check-good">
                  <span aria-hidden="true">✓</span>
                  <div>
                    <strong>{t("readyPublish")}</strong>
                    <small>{t("allBlockersClear")}</small>
                  </div>
                </div>
              ) : (
                blockers.map((blocker) => (
                  <div className="check-item check-bad" key={blocker}>
                    <span aria-hidden="true">!</span>
                    <div>
                      <strong>{blockerLabel(blocker, locale)}</strong>
                      <small>
                        {blockerCopy[blocker]
                          ? t(blockerCopy[blocker])
                          : t("resolveBlocker")}
                      </small>
                    </div>
                  </div>
                ))
              )}
            </div>
          </SectionCard>
          <SectionCard
            title={t("ragPreview")}
            description={t("ragPreviewLede")}
          >
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
          <SectionCard title={t("whatTeaches")}>
            <p className="teaching-copy">
              <strong>{t("promptWord")}</strong> {t("whatTeachesPrompt")}{" "}
              <strong>{t("ragWord")}</strong> {t("whatTeachesRag")}{" "}
              <strong>{t("publishWord")}</strong> {t("whatTeachesPublish")}
            </p>
          </SectionCard>
        </aside>
      </div>
    </>
  );
}

export function preserveDraftOnRetry(error: unknown): boolean {
  return isConflict(error);
}

export function DraftConflictNotice({ onRefresh }: { onRefresh: () => void }) {
  const t = useT();
  return (
    <div className="notice notice-warning" role="alert">
      <strong>{t("revisionConflict")}</strong>
      <span>{t("conflictDetail")}</span>
      <button className="inline-button" type="button" onClick={onRefresh}>
        {t("refreshServer")}
      </button>
    </div>
  );
}

function groundingLabel(
  mode: TestChatResponse["grounding_mode"],
  t: ReturnType<typeof useT>,
): string {
  if (mode === "rag_grounded") return t("groundingRag");
  if (mode === "general_reasoning") return t("groundingGeneral");
  return t("groundingMixed");
}

function ChatResult({ result }: { result: TestChatResponse }) {
  const t = useT();
  const matched = result.retrieval_status === "matched";
  return (
    <div
      className={`chat-result ${matched ? "chat-matched" : "chat-no-match"}`}
    >
      <div className="chip-row">
        <StatusBadge
          status={result.retrieval_status}
          tone={matched ? "good" : "warn"}
        />
        <span>{groundingLabel(result.grounding_mode, t)}</span>
      </div>
      <p>{result.answer}</p>
      <div className="source-row">
        {matched ? (
          result.sources.map((source) => (
            <span
              className="source-chip"
              key={`${source.source_filename}-${source.chunk_id ?? "source"}`}
            >
              {source.source_filename}
            </span>
          ))
        ) : (
          <span className="muted-copy">{t("noSources")}</span>
        )}
      </div>
    </div>
  );
}

function ReadOnlyVersion({
  version,
  agent,
}: {
  version: AgentVersion;
  agent: AgentDetail;
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

  return (
    <>
      <PageIntro
        eyebrow={t("publishedSnapshot")}
        title={`${agent.name} · ${version.version_label}`}
        description={t("publishedSnapshotLede")}
        action={
          <Link
            className="secondary-action"
            href={`/student/agents/${agent.id}`}
          >
            {t("backToAgent")}
          </Link>
        }
      />
      <div className="workbench-grid">
        <div className="workbench-main">
          <SectionCard title={t("agentMd")} description={t("readOnlyRelease")}>
            <pre className="read-only-markdown">
              {version.agent_md || t("noPrompt")}
            </pre>
            <button
              className="secondary-action"
              type="button"
              disabled={agentMdBusy}
              onClick={() => void downloadAgentMd()}
            >
              {t("download")} AGENT.md
            </button>
            {agentMdError ? <ErrorNotice error={agentMdError} /> : null}
          </SectionCard>
          <SectionCard title={t("enabledEvidence")}>
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
                  {t("revision")} {version.revision} {t("revisionImmutable")}
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
      <SectionCard title={t("knowledgeSnapshot")}>
        <ErrorNotice error={error} />
      </SectionCard>
    );
  return (
    <SectionCard title={t("knowledgeSnapshot")} description={t("snapshotLede")}>
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
                    {document.char_count.toLocaleString()} {t("characters")}
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

function parsePersonaSpec(value: unknown): PersonaPreviewSpec | null {
  const candidate =
    typeof value === "string"
      ? parseJson(value)
      : value && typeof value === "object"
        ? value
        : null;
  if (!candidate || typeof candidate !== "object") return null;
  const record = candidate as Record<string, unknown>;
  const identity = record.identity;
  const style = record.speaking_style;
  if (!isRecord(identity) || !isRecord(style)) return null;
  if (
    typeof identity.name !== "string" ||
    typeof identity.role !== "string" ||
    typeof identity.historical_or_cultural_context !== "string" ||
    typeof style.tone !== "string" ||
    typeof style.argument_pattern !== "string" ||
    typeof style.concession_style !== "string" ||
    typeof style.question_style !== "string" ||
    typeof record.initial_position !== "string" ||
    !isStringArray(record.cultural_lens) ||
    !isStringArray(record.core_values) ||
    !isStringArray(record.debate_strategy) ||
    !isStringArray(record.boundaries)
  )
    return null;
  return {
    schema_version:
      typeof record.schema_version === "string"
        ? record.schema_version
        : undefined,
    identity: {
      name: identity.name,
      role: identity.role,
      historical_or_cultural_context: identity.historical_or_cultural_context,
    },
    cultural_lens: record.cultural_lens,
    core_values: record.core_values,
    initial_position: record.initial_position,
    speaking_style: {
      tone: style.tone,
      argument_pattern: style.argument_pattern,
      concession_style: style.concession_style,
      question_style: style.question_style,
    },
    debate_strategy: record.debate_strategy,
    boundaries: record.boundaries,
    source_agent_md_hash:
      typeof record.source_agent_md_hash === "string"
        ? record.source_agent_md_hash
        : undefined,
    compiler_version:
      typeof record.compiler_version === "string"
        ? record.compiler_version
        : undefined,
  };
}

function parseJson(value: string): unknown {
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return null;
  }
}

function parsePersonaDiagnostics(value: unknown): PersonaPreviewDiagnostic[] {
  const candidate =
    typeof value === "string"
      ? parseJson(value)
      : Array.isArray(value)
        ? value
        : [];
  if (!Array.isArray(candidate)) return [];
  return candidate.filter(
    (item): item is PersonaPreviewDiagnostic =>
      isRecord(item) && typeof item.message === "string",
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function isStringArray(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
  );
}
