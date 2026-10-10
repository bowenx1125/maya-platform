"use client";

import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";

import {
  isAmbiguousMutationFailure,
  isConflict,
  type IdempotencyHandle,
  type AgentKnowledgeSets,
  type AgentDetail,
  type AgentVersion,
  type AvatarTemplate,
  type KnowledgeDocument,
  type KnowledgeSetSummary,
  type KnowledgeSnapshot,
  type RagPreview,
  type VoiceProfile,
} from "../lib/api";
import { useIdempotencyStore } from "../lib/idempotency";
import { blockerLabel, statusLabel, type MessageKey } from "../lib/i18n";
import { useLocale, useT } from "./locale";
import {
  AVATAR_TEMPLATE_DEFAULT_CONFIGS,
  AvatarEditor,
  avatarDefaultConfigForTemplate,
  type AvatarConfig,
} from "./avatar";
import { buildAgentTemplate } from "./agent-template";
import { PageAction } from "./page-action";
import { ModulePlus } from "./studyform-layout";
import { IconDownload, IconUpload } from "./quiet-icons";
import { VoiceLibrary } from "./voice/voice-library";
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
    !visible &&
    !agent.current_published_version_id &&
    versions.every(
      (version) => version.state === "draft" && !version.knowledge_snapshot_id,
    );
  const editorVersion = current ?? draft;
  if (agent.group_id && editorVersion) {
    return (
      <AgentWorkbench
        versionId={editorVersion.id}
        backHref={`/student/groups/${agent.group_id}`}
        publishOnDone
      />
    );
  }
  const actions = canDelete ? (
    <div className="button-row">
      <button
        className="text-link danger-button"
        type="button"
        disabled={busy}
        onClick={() => void deleteAgent()}
      >
        {t("deleteAgent")}
      </button>
    </div>
  ) : null;
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
      {visible ? (
        <ReadOnlyVersion
          version={visible}
          agent={agent}
          actions={actions}
          backHref={`/student/groups/${agent.group_id}`}
        />
      ) : (
        <SectionCard action={actions}>
          <PageAction name="back" href={`/student/groups/${agent.group_id}`} />
          <EmptyCard title={t("noVersions")} />
        </SectionCard>
      )}
    </>
  );
}

export function AgentWorkbench({
  versionId,
  backHref,
  actorScopeKey,
  generationFlow = false,
  publishOnDone = false,
  unsavedCreate,
}: {
  versionId?: string;
  backHref?: string;
  actorScopeKey?: string;
  knowledgeHref?: string;
  generationFlow?: boolean;
  // Edits stay in the browser until Done. New does not create a draft.
  publishOnDone?: boolean;
  // A new Agent stays in this form until Done, which creates and publishes it.
  unsavedCreate?: {
    groupId?: string;
    courseId?: string;
    create: (
      name: string,
      visibility: "private" | "public",
    ) => Promise<AgentDetail>;
    onIdentityEdit?: () => void;
  };
}) {
  const t = useT();
  const router = useRouter();
  const { locale } = useLocale();
  const { api, user } = useSession();
  const workbenchScope =
    actorScopeKey ??
    (versionId
      ? `agent-version:${versionId}`
      : `agent-create:${unsavedCreate?.groupId ?? unsavedCreate?.courseId ?? "course"}`);
  const workbenchScopeRef = useRef(workbenchScope);
  useLayoutEffect(() => {
    workbenchScopeRef.current = workbenchScope;
  }, [workbenchScope]);
  const workbenchMounted = useRef(true);
  useEffect(() => {
    workbenchMounted.current = true;
    return () => {
      workbenchMounted.current = false;
    };
  }, []);
  const isCurrentScope = (scope: string) =>
    workbenchMounted.current && workbenchScopeRef.current === scope;
  const [version, setVersion] = useState<AgentVersion | null>(null);
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [knowledgeSets, setKnowledgeSets] = useState<KnowledgeSetSummary[]>([]);
  const [agentKnowledge, setAgentKnowledge] =
    useState<AgentKnowledgeSets | null>(null);
  const [selectedKnowledgeSetIds, setSelectedKnowledgeSetIds] = useState<
    string[]
  >([]);
  const [knowledgeBindingSaving, setKnowledgeBindingSaving] = useState(false);
  const [pendingKnowledgeSetIds, setPendingKnowledgeSetIds] = useState<
    string[] | null
  >(null);
  const [, setPreview] = useState<RagPreview | null>(null);
  const [avatarTemplates, setAvatarTemplates] = useState<AvatarTemplate[]>([]);
  const [voiceProfiles, setVoiceProfiles] = useState<VoiceProfile[]>([]);
  const [avatarConfig, setAvatarConfig] = useState<AvatarConfig | null>(null);
  const [voiceProfileId, setVoiceProfileId] = useState<string | null>(null);
  const [agentMd, setAgentMd] = useState("");
  const [draftName, setDraftName] = useState("");
  const [draftVisibility, setDraftVisibility] = useState<"private" | "public">(
    "private",
  );
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [knowledgeUploadError, setKnowledgeUploadError] =
    useState<unknown>(null);
  const [knowledgePreviewRefreshFailed, setKnowledgePreviewRefreshFailed] =
    useState(false);
  const [knowledgePreviewRefreshing, setKnowledgePreviewRefreshing] =
    useState(false);
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState<MessageKey | null>(null);
  const mutationStore = useIdempotencyStore();
  const [retryAction, setRetryAction] = useState<
    "uploadKnowledge" | "bindKnowledge" | "publish" | null
  >(null);
  const [generationSourcePrompt, setGenerationSourcePrompt] = useState(false);
  const [pendingKnowledgeUpload, setPendingKnowledgeUpload] = useState<{
    file: File;
    signature: string;
  } | null>(null);
  const [visibilityBusyDocumentId, setVisibilityBusyDocumentId] = useState<
    string | null
  >(null);
  const versionKey = versionId ?? "new";
  const uploadIntent = `${workbenchScope}:upload-knowledge:${versionKey}`;
  const knowledgeBindingIntent = `${workbenchScope}:knowledge-sets:${agent?.id ?? versionKey}`;
  const publishIntent = `${workbenchScope}:publish-agent-version:${versionKey}`;
  const createdAgentRef = useRef<AgentDetail | null>(null);
  const persistedVersionRef = useRef<AgentVersion | null>(null);
  const publishLock = useRef(false);
  const unsavedGroupId = unsavedCreate?.groupId ?? null;
  const unsavedCourseId = unsavedCreate?.courseId ?? null;
  const creating = unsavedCreate !== undefined;

  async function refreshKnowledgePreview() {
    const requestScope = workbenchScope;
    setKnowledgePreviewRefreshing(true);
    try {
      const nextPreview = await api.ragPreview(currentVersion.id);
      if (!isCurrentScope(requestScope)) return;
      setPreview(nextPreview);
      setKnowledgePreviewRefreshFailed(false);
    } catch {
      if (isCurrentScope(requestScope)) setKnowledgePreviewRefreshFailed(true);
    } finally {
      if (isCurrentScope(requestScope)) setKnowledgePreviewRefreshing(false);
    }
  }

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
      const requestScope = workbenchScope;
      setLoading(true);
      setError(null);
      try {
        if (creating) {
          let courseId = unsavedCourseId;
          if (unsavedGroupId) {
            const group = await api.group(unsavedGroupId);
            if (!isCurrentScope(requestScope)) return;
            courseId = courseId ?? group.course_id;
          }
          if (!courseId) throw new Error("missing course");
          const [
            nextDocuments,
            nextAvatarTemplates,
            nextVoiceProfiles,
            nextKnowledgeSets,
          ] = await Promise.all([
            unsavedGroupId
              ? api.knowledge(unsavedGroupId)
              : api.workspaceDocuments(courseId),
            api.avatarTemplates(),
            unsavedGroupId
              ? api.voiceProfiles(unsavedGroupId)
              : Promise.resolve([]),
            api.knowledgeSets(courseId),
          ]);
          if (!isCurrentScope(requestScope)) return;
          const baselineAvatar =
            nextAvatarTemplates
              .map((template) => avatarDefaultConfigForTemplate(template))
              .find((config): config is AvatarConfig => config !== null) ??
            ({
              ...AVATAR_TEMPLATE_DEFAULT_CONFIGS["wave1-default-head"],
            } as AvatarConfig);
          setVersion({
            id: "",
            agent_id: "",
            version_label: "V1.0",
            state: "draft",
            revision: 0,
            agent_md: "",
            avatar_config: baselineAvatar,
            voice_profile_id: null,
            voice_fallback_active: true,
            persona_confirmed: false,
            enabled_documents: [],
            publish_blockers: [],
          } as unknown as AgentVersion);
          setAgent({
            id: "",
            name: "",
            description: "",
            group_id: unsavedGroupId,
            course_id: courseId,
            ownership_scope: unsavedGroupId ? "group" : "personal",
            visibility: "private",
            metadata_revision: 0,
            status: "active",
            current_draft_version_id: null,
            current_published_version_id: null,
            versions: [],
          } as unknown as AgentDetail);
          setDocuments(nextDocuments);
          setKnowledgeSets(nextKnowledgeSets);
          setAgentKnowledge({
            agent_id: "",
            agent_metadata_revision: 0,
            sets: [],
          });
          setPreview(null);
          setKnowledgePreviewRefreshFailed(false);
          setAvatarTemplates(nextAvatarTemplates);
          setVoiceProfiles(nextVoiceProfiles);
          if (!keepLocal) {
            setAgentMd("");
            setAvatarConfig(baselineAvatar);
            setVoiceProfileId(null);
            setSelectedDocumentIds([]);
            setSelectedKnowledgeSetIds([]);
            setPendingKnowledgeSetIds(null);
            setConflict(false);
          }
          return;
        }
        if (!versionId) throw new Error("missing version");
        const nextVersion = await api.version(versionId);
        if (!isCurrentScope(requestScope)) return;
        const nextAgent = await api.agent(nextVersion.agent_id);
        if (!isCurrentScope(requestScope)) return;
        const [
          nextDocuments,
          nextPreview,
          nextAvatarTemplates,
          nextVoiceProfiles,
          nextKnowledgeSets,
          nextAgentKnowledge,
        ] = await Promise.all([
          nextAgent.group_id
            ? api.knowledge(nextAgent.group_id)
            : api.workspaceDocuments(nextAgent.course_id),
          // Preview is draft-only. A published version is the editor baseline
          // until Done, and its preview request is a not-found.
          nextVersion.state === "draft"
            ? api.ragPreview(versionId)
            : Promise.resolve(null),
          api.avatarTemplates(),
          nextAgent.group_id
            ? api.voiceProfiles(nextAgent.group_id)
            : Promise.resolve([]),
          api.knowledgeSets(nextAgent.course_id),
          api.agentKnowledgeSets(nextAgent.id),
        ]);
        if (!isCurrentScope(requestScope)) return;
        setVersion(nextVersion);
        setAgent(nextAgent);
        setDocuments(nextDocuments);
        setKnowledgeSets(
          Array.from(
            new Map(
              [...nextKnowledgeSets, ...nextAgentKnowledge.sets].map((set) => [
                set.id,
                set,
              ]),
            ).values(),
          ),
        );
        setAgentKnowledge(nextAgentKnowledge);
        setPreview(nextPreview);
        setKnowledgePreviewRefreshFailed(false);
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
          setSelectedKnowledgeSetIds(
            nextAgentKnowledge.sets.map((set) => set.id),
          );
          setPendingKnowledgeSetIds(null);
          setConflict(false);
        }
      } catch (cause) {
        if (isCurrentScope(requestScope)) setError(cause);
      } finally {
        if (isCurrentScope(requestScope)) setLoading(false);
      }
    },
    [api, creating, unsavedCourseId, unsavedGroupId, versionId, workbenchScope],
  );
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const voiceGroupId = agent?.group_id;
  useEffect(() => {
    if (!voiceGroupId) return;
    const groupId = voiceGroupId;
    let active = true;
    let refreshing = false;
    async function refreshVoices() {
      if (document.visibilityState === "hidden" || refreshing) return;
      refreshing = true;
      try {
        const next = await api.voiceProfiles(groupId);
        if (active) setVoiceProfiles(next);
      } catch (cause) {
        if (active) setError(cause);
      } finally {
        refreshing = false;
      }
    }
    window.addEventListener("focus", refreshVoices);
    document.addEventListener("visibilitychange", refreshVoices);
    return () => {
      active = false;
      window.removeEventListener("focus", refreshVoices);
      document.removeEventListener("visibilitychange", refreshVoices);
    };
  }, [api, voiceGroupId]);

  const enabledCount = selectedDocumentIds.length;
  const sameIds = (left: string[], right: string[]) =>
    left.length === right.length &&
    [...left].sort().every((id, index) => id === [...right].sort()[index]);
  const localDirty = Boolean(
    version &&
    (agentMd !== (version.agent_md ?? "") ||
      JSON.stringify(avatarConfig) !== JSON.stringify(version.avatar_config) ||
      voiceProfileId !== (version.voice_profile_id ?? null) ||
      !sameIds(
        selectedDocumentIds,
        (version.enabled_documents ?? []).map((document) => document.id),
      ) ||
      (agentKnowledge !== null &&
        !sameIds(
          selectedKnowledgeSetIds,
          agentKnowledge.sets.map((set) => set.id),
        ))),
  );
  const blockers = version?.publish_blockers ?? [];

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
  const currentVersion = version;
  const currentAgent = agent;
  if (version.state !== "draft" && !publishOnDone)
    return (
      <ReadOnlyVersion version={version} agent={agent} backHref={backHref} />
    );

  async function saveDraft() {
    const requestScope = workbenchScope;
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
        ...(voiceProfileId !== (currentVersion.voice_profile_id ?? null)
          ? { voice_profile_id: voiceProfileId }
          : {}),
      });
      if (!isCurrentScope(requestScope)) return;
      const nextAgent = await api.agent(next.agent_id);
      if (!isCurrentScope(requestScope)) return;
      setVersion(next);
      setAgent(nextAgent);
      setAgentMd(next.agent_md ?? "");
      setAvatarConfig(next.avatar_config);
      setVoiceProfileId(next.voice_profile_id ?? null);
      setNotice("draftSavedNotice");
      return next;
    } catch (cause) {
      if (isCurrentScope(requestScope)) {
        if (isConflict(cause)) setConflict(true);
        setError(cause);
      }
    } finally {
      if (isCurrentScope(requestScope)) setSaving(false);
    }
  }

  async function uploadAgentMd(file: File) {
    if (publishOnDone) {
      setAgentMd(await file.text());
      return;
    }
    const requestScope = workbenchScope;
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
      if (!isCurrentScope(requestScope)) return;
      const nextAgent = await api.agent(next.agent_id);
      if (!isCurrentScope(requestScope)) return;
      setVersion(next);
      setAgent(nextAgent);
      setAgentMd(next.agent_md ?? "");
      setNotice("agentMdUploadedNotice");
    } catch (cause) {
      if (isCurrentScope(requestScope)) {
        if (isConflict(cause)) setConflict(true);
        setError(cause);
      }
    } finally {
      if (isCurrentScope(requestScope)) setSaving(false);
    }
  }

  async function toggleDocument(documentId: string, enabled: boolean) {
    if (publishOnDone) {
      setSelectedDocumentIds((current) =>
        enabled
          ? current.includes(documentId)
            ? current
            : [...current, documentId]
          : current.filter((id) => id !== documentId),
      );
      return;
    }
    const requestScope = workbenchScope;
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
      if (!isCurrentScope(requestScope)) return;
      setVersion(next);
      setSelectedDocumentIds(
        (next.enabled_documents ?? []).map((document) => document.id),
      );
      setNotice("evidenceUpdatedNotice");
      const nextPreview = await api.ragPreview(currentVersion.id);
      if (isCurrentScope(requestScope)) setPreview(nextPreview);
    } catch (cause) {
      if (isCurrentScope(requestScope)) {
        if (isConflict(cause)) {
          setConflict(true);
          setSelectedDocumentIds(selectedDocumentIds);
        }
        setError(cause);
      }
    } finally {
      if (isCurrentScope(requestScope)) setSaving(false);
    }
  }

  async function saveKnowledgeSetSelection(nextSetIds: string[]) {
    if (publishOnDone) {
      setSelectedKnowledgeSetIds(nextSetIds);
      return;
    }
    const requestScope = workbenchScope;
    if (!agentKnowledge || knowledgeBindingSaving) return;
    setSelectedKnowledgeSetIds(nextSetIds);
    setPendingKnowledgeSetIds(nextSetIds);
    setKnowledgeBindingSaving(true);
    setError(null);
    setNotice(null);
    const handle = mutationStore.handleFor(knowledgeBindingIntent);
    try {
      const next = await api.replaceAgentKnowledgeSets(
        agentKnowledge.agent_id,
        {
          expected_agent_metadata_revision:
            agentKnowledge.agent_metadata_revision,
          set_ids: nextSetIds,
        },
        { idempotency: handle },
      );
      if (!isCurrentScope(requestScope)) return;
      mutationStore.finish(knowledgeBindingIntent, handle);
      setAgentKnowledge(next);
      setAgent((current) =>
        current
          ? { ...current, metadata_revision: next.agent_metadata_revision }
          : current,
      );
      setSelectedKnowledgeSetIds(next.sets.map((set) => set.id));
      setPendingKnowledgeSetIds(null);
      setRetryAction(null);
      setNotice("knowledgeBindingsUpdated");
    } catch (cause) {
      if (!isCurrentScope(requestScope)) return;
      if (isAmbiguousMutationFailure(cause)) {
        setRetryAction("bindKnowledge");
      } else {
        mutationStore.abandon(knowledgeBindingIntent, handle);
        setRetryAction(null);
        setPendingKnowledgeSetIds(null);
        setSelectedKnowledgeSetIds(agentKnowledge.sets.map((set) => set.id));
      }
      setError(cause);
    } finally {
      if (isCurrentScope(requestScope)) setKnowledgeBindingSaving(false);
    }
  }

  async function uploadKnowledge(file: File) {
    const requestScope = workbenchScope;
    const signature = `${file.name}:${file.size}:${file.lastModified}`;
    if (unsavedCreate && !createdAgentRef.current?.id) {
      setPendingKnowledgeUpload({ file, signature });
      setError(null);
      setKnowledgeUploadError(null);
      return;
    }
    if (pendingKnowledgeUpload?.signature !== signature) {
      mutationStore.abandon(uploadIntent);
    }
    abandonPublishIntent();
    setPendingKnowledgeUpload({ file, signature });
    setSaving(true);
    setError(null);
    setKnowledgeUploadError(null);
    setKnowledgePreviewRefreshFailed(false);
    setNotice(null);
    setConflict(false);
    let mutationCompleted = false;
    const handle = mutationStore.handleFor(uploadIntent);
    try {
      const mutation = currentAgent.group_id
        ? await api.uploadKnowledge(
            currentAgent.group_id,
            currentVersion.id,
            file,
            currentVersion.revision,
            { idempotency: handle },
          )
        : await api.uploadWorkspaceKnowledge(
            currentAgent.course_id,
            currentVersion.id,
            file,
            currentVersion.revision,
            { idempotency: handle },
          );
      mutationStore.finish(uploadIntent, handle);
      mutationCompleted = true;
      if (!isCurrentScope(requestScope)) return;
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
      setNotice(
        /\.(pdf|docx)$/i.test(file.name)
          ? "knowledgeEvidenceImported"
          : "markdownUploadedNotice",
      );
      await refreshKnowledgePreview();
    } catch (cause) {
      if (!isCurrentScope(requestScope)) return;
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
      setKnowledgeUploadError(cause);
    } finally {
      if (isCurrentScope(requestScope)) setSaving(false);
    }
  }

  async function updateSourceVisibility(document: KnowledgeDocument) {
    if (visibilityBusyDocumentId) return;
    const requestScope = workbenchScope;
    setVisibilityBusyDocumentId(document.id);
    setError(null);
    try {
      const updated = await api.updateKnowledgeVisibility(document.id, {
        expected_authorization_epoch: document.authorization_epoch,
        visibility: document.visibility === "private" ? "public" : "private",
      });
      if (!isCurrentScope(requestScope)) return;
      setDocuments((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setNotice("sourceSharingUpdatedNotice");
      const nextPreview = await api.ragPreview(currentVersion.id);
      if (isCurrentScope(requestScope)) setPreview(nextPreview);
    } catch (cause) {
      if (isCurrentScope(requestScope)) setError(cause);
    } finally {
      if (isCurrentScope(requestScope)) setVisibilityBusyDocumentId(null);
    }
  }

  async function writeUnsavedAgent(): Promise<{
    agent: AgentDetail;
    version: AgentVersion;
  } | null> {
    const requestScope = workbenchScope;
    const create = unsavedCreate?.create;
    if (!create) {
      setError(new Error(t("draftNotFound")));
      return null;
    }
    let created = createdAgentRef.current;
    if (!created) {
      try {
        created = await create(draftName.trim(), draftVisibility);
        if (!isCurrentScope(requestScope)) return null;
        createdAgentRef.current = created;
        setAgent(created);
      } catch (cause) {
        if (!isCurrentScope(requestScope)) return null;
        if (isAmbiguousMutationFailure(cause)) setRetryAction("publish");
        setError(cause);
        return null;
      }
    }
    const draftId =
      created.current_draft_version_id ??
      created.versions?.find((item) => item.state === "draft")?.id;
    if (!draftId) {
      setError(new Error(t("draftNotFound")));
      return null;
    }
    let saved = persistedVersionRef.current;
    if (!saved || localDirty) {
      try {
        saved = await api.updateDraft(draftId, {
          expected_revision: saved?.revision ?? 0,
          agent_md: agentMd,
          ...(avatarConfig ? { avatar_config: avatarConfig } : {}),
          ...(voiceProfileId !== (saved?.voice_profile_id ?? null)
            ? { voice_profile_id: voiceProfileId }
            : {}),
        });
        if (!isCurrentScope(requestScope)) return null;
        persistedVersionRef.current = saved;
        setVersion(saved);
      } catch (cause) {
        if (!isCurrentScope(requestScope)) return null;
        if (isConflict(cause)) setConflict(true);
        if (isAmbiguousMutationFailure(cause)) setRetryAction("publish");
        setError(cause);
        return null;
      }
    }
    if (!saved) return null;
    if (pendingKnowledgeUpload) {
      const handle = mutationStore.handleFor(uploadIntent);
      try {
        const mutation = created.group_id
          ? await api.uploadKnowledge(
              created.group_id,
              saved.id,
              pendingKnowledgeUpload.file,
              saved.revision,
              { idempotency: handle },
            )
          : await api.uploadWorkspaceKnowledge(
              created.course_id,
              saved.id,
              pendingKnowledgeUpload.file,
              saved.revision,
              { idempotency: handle },
            );
        mutationStore.finish(uploadIntent, handle);
        if (!isCurrentScope(requestScope)) return null;
        if (!mutation.agent_version) {
          setError(new Error(t("draftNotFound")));
          return null;
        }
        saved = mutation.agent_version;
        persistedVersionRef.current = saved;
        setVersion(saved);
        setPendingKnowledgeUpload(null);
        setDocuments((current) =>
          current.some((item) => item.id === mutation.document.id)
            ? current
            : [...current, mutation.document],
        );
      } catch (cause) {
        if (!isCurrentScope(requestScope)) return null;
        if (isAmbiguousMutationFailure(cause)) setRetryAction("publish");
        else mutationStore.abandon(uploadIntent, handle);
        setError(cause);
        setKnowledgeUploadError(cause);
        return null;
      }
    }
    const enabledIds = (saved.enabled_documents ?? []).map(
      (document) => document.id,
    );
    if (!sameIds(selectedDocumentIds, enabledIds)) {
      try {
        saved = await api.setDocuments(
          saved.id,
          saved.revision,
          selectedDocumentIds,
        );
        if (!isCurrentScope(requestScope)) return null;
        persistedVersionRef.current = saved;
        setVersion(saved);
      } catch (cause) {
        if (!isCurrentScope(requestScope)) return null;
        if (isConflict(cause)) setConflict(true);
        if (isAmbiguousMutationFailure(cause)) setRetryAction("publish");
        setError(cause);
        return null;
      }
    }
    const boundIds = agentKnowledge?.sets.map((set) => set.id) ?? [];
    if (agentKnowledge && !sameIds(selectedKnowledgeSetIds, boundIds)) {
      const handle = mutationStore.handleFor(knowledgeBindingIntent);
      try {
        const next = await api.replaceAgentKnowledgeSets(
          created.id,
          {
            expected_agent_metadata_revision:
              agentKnowledge.agent_metadata_revision,
            set_ids: selectedKnowledgeSetIds,
          },
          { idempotency: handle },
        );
        if (!isCurrentScope(requestScope)) return null;
        mutationStore.finish(knowledgeBindingIntent, handle);
        setAgentKnowledge(next);
        created = {
          ...created,
          metadata_revision: next.agent_metadata_revision,
        };
        createdAgentRef.current = created;
        setAgent(created);
      } catch (cause) {
        if (!isCurrentScope(requestScope)) return null;
        if (isAmbiguousMutationFailure(cause)) setRetryAction("publish");
        else mutationStore.abandon(knowledgeBindingIntent, handle);
        setError(cause);
        return null;
      }
    }
    return { agent: created, version: saved };
  }

  async function publish(retry = false) {
    const requestScope = workbenchScope;
    if (generationFlow && selectedDocumentIds.length === 0) {
      setGenerationSourcePrompt(true);
      setError(null);
      return;
    }
    setGenerationSourcePrompt(false);
    if (unsavedCreate) {
      if (publishLock.current) return;
      if (!draftName.trim() || !agentMd.trim()) return;
      publishLock.current = true;
      setSaving(true);
      setError(null);
      setNotice(null);
      try {
        const materialized = await writeUnsavedAgent();
        if (!materialized || !isCurrentScope(requestScope)) return;
        const saved = materialized.version;
        const activeAgent = materialized.agent;
        if ((saved.publish_blockers ?? []).length > 0) {
          setError(
            new Error(blockerLabel(saved.publish_blockers?.[0] ?? "", locale)),
          );
          return;
        }
        const handle = mutationStore.handleFor(publishIntent);
        const next = await api.publish(saved.id, saved.revision, {
          idempotency: handle,
        });
        mutationStore.finish(publishIntent, handle);
        if (!isCurrentScope(requestScope)) return;
        createdAgentRef.current = {
          ...activeAgent,
          current_published_version_id: next.id,
          current_draft_version_id: null,
        };
        setRetryAction(null);
        setVersion(next);
        setNotice("publishedNotice");
        router.replace(
          activeAgent.group_id
            ? `/student/groups/${activeAgent.group_id}`
            : "/teacher/studyform",
        );
      } catch (cause) {
        if (!isCurrentScope(requestScope)) return;
        if (isConflict(cause)) setConflict(true);
        if (isAmbiguousMutationFailure(cause)) setRetryAction("publish");
        else {
          mutationStore.abandon(publishIntent);
          setRetryAction(null);
        }
        setError(cause);
      } finally {
        publishLock.current = false;
        if (isCurrentScope(requestScope)) setSaving(false);
      }
      return;
    }
    // The server only knows the last saved revision.  Never publish it while
    // the browser still holds newer AGENT/avatar/voice values.
    let saved =
      localDirty && !(publishOnDone && currentVersion.state !== "draft")
        ? await saveDraft()
        : currentVersion;
    if (publishOnDone && saved && saved.state !== "draft") {
      const intent = `agent-next-version:${currentAgent.id}`;
      const handle = mutationStore.handleFor(intent);
      try {
        saved = await api.nextVersion(currentAgent.id, { idempotency: handle });
        mutationStore.finish(intent, handle);
      } catch (cause) {
        if (isAmbiguousMutationFailure(cause)) {
          setError(cause);
          setRetryAction("publish");
          return;
        }
        mutationStore.abandon(intent, handle);
        const versions = await api.versions(currentAgent.id);
        const existing = versions.find((item) => item.state === "draft");
        if (!existing) {
          setError(cause);
          return;
        }
        saved = existing;
      }
      if (!saved) return;
      const written = await api.updateDraft(saved.id, {
        expected_revision: saved.revision,
        agent_md: agentMd,
        ...(avatarConfig ? { avatar_config: avatarConfig } : {}),
        ...(voiceProfileId !== (saved.voice_profile_id ?? null)
          ? { voice_profile_id: voiceProfileId }
          : {}),
      });
      saved = written;
    }
    if (publishOnDone && saved) {
      const documentIds = (saved.enabled_documents ?? []).map(
        (document) => document.id,
      );
      if (!sameIds(selectedDocumentIds, documentIds)) {
        saved = await api.setDocuments(
          saved.id,
          saved.revision,
          selectedDocumentIds,
        );
      }
      if (
        agentKnowledge &&
        !sameIds(
          selectedKnowledgeSetIds,
          agentKnowledge.sets.map((set) => set.id),
        )
      ) {
        await api.replaceAgentKnowledgeSets(
          currentAgent.id,
          {
            expected_agent_metadata_revision:
              agentKnowledge.agent_metadata_revision,
            set_ids: selectedKnowledgeSetIds,
          },
          { idempotency: mutationStore.handleFor(knowledgeBindingIntent) },
        );
      }
    }
    if (
      !isCurrentScope(requestScope) ||
      !saved ||
      (saved.publish_blockers ?? []).length > 0
    )
      return;
    if (!retry) abandonUploadIntent();
    setSaving(true);
    setError(null);
    setNotice(null);
    const handle = mutationStore.handleFor(publishIntent);
    try {
      const next = await api.publish(saved.id, saved.revision, {
        idempotency: handle,
        ...(generationFlow
          ? { generation: { source_document_ids: selectedDocumentIds } }
          : {}),
      });
      mutationStore.finish(publishIntent, handle);
      if (!isCurrentScope(requestScope)) return;
      setRetryAction(null);
      setVersion(next);
      if (generationFlow) {
        const receipt = next.knowledge_generation;
        if (!receipt) {
          setError(new Error(t("generationReceiptMissing")));
          return;
        }
        router.replace(
          `/teacher/knowledge?agent_id=${encodeURIComponent(currentAgent.id)}&set_id=${encodeURIComponent(receipt.knowledge_set_id)}&job_id=${encodeURIComponent(receipt.job_id)}`,
        );
        return;
      }
      setNotice("publishedNotice");
      router.replace(
        publishOnDone
          ? (backHref ??
              (currentAgent.group_id
                ? `/student/groups/${currentAgent.group_id}`
                : "/teacher/studyform"))
          : currentAgent.ownership_scope === "personal"
            ? `/teacher/agents/${currentAgent.id}`
            : `/student/agents/${currentAgent.id}`,
      );
    } catch (cause) {
      if (!isCurrentScope(requestScope)) return;
      if (isConflict(cause)) setConflict(true);
      if (isAmbiguousMutationFailure(cause)) {
        setRetryAction("publish");
      } else {
        mutationStore.abandon(publishIntent, handle);
        setRetryAction(null);
      }
      setError(cause);
    } finally {
      if (isCurrentScope(requestScope)) setSaving(false);
    }
  }

  return (
    <>
      <PageIntro
        title={
          unsavedCreate
            ? draftName.trim()
              ? `${draftName.trim()} · ${version.version_label}`
              : t("newAgent")
            : `${agent.name} · ${version.version_label}`
        }
      />
      {generationFlow ? (
        <p className="notice notice-info" role="status">
          {t("aiKnowledgeFlowIntro")}
        </p>
      ) : null}
      {conflict ? <DraftConflictNotice /> : null}
      {error && !conflict && error !== knowledgeUploadError ? (
        <>
          <ErrorNotice
            error={error}
            onRetry={
              retryAction === "uploadKnowledge" && pendingKnowledgeUpload
                ? () => void uploadKnowledge(pendingKnowledgeUpload.file)
                : retryAction === "bindKnowledge" && pendingKnowledgeSetIds
                  ? () => void saveKnowledgeSetSelection(pendingKnowledgeSetIds)
                  : retryAction === "publish"
                    ? () => {
                        void publish(true);
                      }
                    : () => void load(true)
            }
          />
        </>
      ) : null}
      {generationSourcePrompt ? (
        <div className="notice notice-warning" role="alert">
          <strong>{t("aiKnowledgeSourcesRequired")}</strong>
          <span>{t("aiKnowledgeSourcesRequiredHelp")}</span>
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
          {unsavedCreate ? (
            <SectionCard title={t("agentIdentity")}>
              <form
                id="create-agent-form"
                className="stack-form wide-form quiet-create"
                onSubmit={(event) => {
                  event.preventDefault();
                  void publish();
                }}
              >
                <label>
                  <span>{t("agentName")}</span>
                  <input
                    aria-label={t("agentName")}
                    value={draftName}
                    disabled={saving}
                    maxLength={120}
                    onChange={(event) => {
                      unsavedCreate.onIdentityEdit?.();
                      setDraftName(event.target.value);
                    }}
                    required
                  />
                </label>
                <div className="agent-identity">
                  <div
                    className="visibility-toggle"
                    role="group"
                    aria-label={t("agentVisibility")}
                    data-ui-guide="agent.visibility"
                  >
                    {(["private", "public"] as const).map((option) => (
                      <button
                        key={option}
                        type="button"
                        aria-pressed={draftVisibility === option}
                        disabled={saving}
                        onClick={() => {
                          unsavedCreate.onIdentityEdit?.();
                          setDraftVisibility(option);
                        }}
                      >
                        {t(
                          option === "private"
                            ? "privateOption"
                            : "publicOption",
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              </form>
            </SectionCard>
          ) : null}
          <SectionCard
            title={t("agentMd")}
            guide="agent.markdown"
            action={
              <div className="button-row">
                <button
                  className="text-link"
                  type="button"
                  disabled={saving}
                  onClick={() => {
                    abandonUploadIntent();
                    abandonPublishIntent();
                    setAgentMd(
                      buildAgentTemplate(
                        draftName.trim() || agent.name,
                        locale,
                      ),
                    );
                  }}
                >
                  {t("insertOutline")}
                </button>
                <button
                  className="icon-action"
                  type="button"
                  disabled={saving || !agentMd}
                  aria-label={`${t("download")} AGENT.md`}
                  data-ui-guide="agent.download"
                  onClick={() => downloadText(agentMd, "AGENT.md")}
                >
                  <IconDownload />
                </button>
                <label
                  className="icon-action"
                  data-ui-guide="agent.uploadMarkdown"
                >
                  <IconUpload />
                  <input
                    className="sr-only"
                    type="file"
                    accept=".md,text/markdown"
                    aria-label={t("uploadMd")}
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
                {agentMd.length.toLocaleString()} {t("characters")}
              </span>
            </div>
          </SectionCard>
          <div className="agent-editor-media">
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
            <div>
              {voiceProfileId &&
              !voiceProfiles.some(
                (profile) =>
                  profile.id === voiceProfileId && profile.status === "ready",
              ) ? (
                <button
                  className="text-link"
                  type="button"
                  aria-pressed="true"
                  disabled={saving}
                  onClick={() => setVoiceProfileId(null)}
                >
                  {t("currentVoiceBinding")}
                </button>
              ) : null}
              <VoiceLibrary
                groupId={agent.group_id}
                membershipGroupIds={
                  agent.group_id
                    ? []
                    : (user?.groups ?? []).map((group) => group.group_id)
                }
                embedded
                selectedId={voiceProfileId}
                onSelect={(profileId) =>
                  setVoiceProfileId((current) =>
                    current === profileId ? null : profileId,
                  )
                }
              />
            </div>
          </div>
        </div>
        <aside className="workbench-side">
          <SectionCard
            title={t("brainform")}
            guide="agent.brainform"
            action={
              <ModulePlus
                href={
                  agent.group_id && agent.ownership_scope !== "personal"
                    ? `/student/knowledge?group_id=${encodeURIComponent(agent.group_id)}&mode=rag-new`
                    : "/teacher/knowledge?mode=rag-new"
                }
                label={t("newAgent")}
              />
            }
          >
            <div className="brainform-source-group">
              <h3>{t("rag")}</h3>
              {saving && pendingKnowledgeUpload ? (
                <p className="muted-copy" role="status" aria-live="polite">
                  <span className="spinner" aria-hidden="true" />
                  {t(
                    /\.(pdf|docx)$/i.test(pendingKnowledgeUpload.file.name)
                      ? "knowledgeImportPending"
                      : "knowledgeUploadPending",
                  )}
                </p>
              ) : null}
              {knowledgePreviewRefreshing ? (
                <p className="muted-copy" role="status" aria-live="polite">
                  <span className="spinner" aria-hidden="true" />
                  {t("knowledgePreviewRefreshing")}
                </p>
              ) : null}
              {knowledgeUploadError && error === knowledgeUploadError ? (
                <ErrorNotice
                  error={knowledgeUploadError}
                  onRetry={
                    retryAction === "uploadKnowledge" && pendingKnowledgeUpload
                      ? () => void uploadKnowledge(pendingKnowledgeUpload.file)
                      : undefined
                  }
                />
              ) : null}
              {knowledgePreviewRefreshFailed ? (
                <div className="notice notice-warning" role="alert">
                  <strong>{t("knowledgePreviewRefreshFailed")}</strong>
                  <button
                    className="inline-button"
                    type="button"
                    disabled={saving || knowledgePreviewRefreshing}
                    onClick={() => void refreshKnowledgePreview()}
                  >
                    {t("retry")}
                  </button>
                </div>
              ) : null}
              {documents.length === 0 ? (
                <p className="muted-copy">{t("noGroupMarkdown")}</p>
              ) : (
                <div className="document-list">
                  {documents.map((document) => (
                    <div
                      className={`document-row ${document.workspace_state === "hidden" ? "is-hidden" : ""}`}
                      key={document.id}
                    >
                      <label className="document-select">
                        <input
                          type="checkbox"
                          checked={selectedDocumentIds.includes(document.id)}
                          disabled={
                            saving ||
                            knowledgePreviewRefreshing ||
                            document.workspace_state === "hidden"
                          }
                          onChange={(event) =>
                            void toggleDocument(
                              document.id,
                              event.target.checked,
                            )
                          }
                        />
                        <span className="document-main">
                          <strong>{document.source_filename}</strong>
                          <small>
                            {document.char_count.toLocaleString()}{" "}
                            {t("characters")} ·{" "}
                            {document.workspace_state === "hidden"
                              ? t("hiddenWorkspace")
                              : document.visibility === "public"
                                ? t("publicVisibility")
                                : t("privateVisibility")}
                          </small>
                        </span>
                      </label>
                      <div className="row-actions">
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
                        {document.can_manage_visibility ? (
                          <button
                            className="inline-button"
                            type="button"
                            disabled={
                              saving || visibilityBusyDocumentId !== null
                            }
                            aria-label={`${document.visibility === "private" ? t("shareSource") : t("makeSourcePrivate")}: ${document.source_filename}`}
                            onClick={() =>
                              void updateSourceVisibility(document)
                            }
                          >
                            {visibilityBusyDocumentId === document.id
                              ? t("working")
                              : document.visibility === "private"
                                ? t("shareSource")
                                : t("makeSourcePrivate")}
                          </button>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="brainform-source-group">
              <h3>{t("brainformKnowledgeHeading")}</h3>
              {knowledgeSets.length === 0 ? (
                <p className="muted-copy">{t("brainformKnowledgeEmpty")}</p>
              ) : (
                <div className="document-list">
                  {knowledgeSets.map((set) => (
                    <div className="document-row" key={set.id}>
                      <label className="document-select">
                        <input
                          type="checkbox"
                          checked={selectedKnowledgeSetIds.includes(set.id)}
                          disabled={
                            saving || knowledgeBindingSaving || !set.can_edit
                          }
                          onChange={(event) => {
                            const nextIds = event.target.checked
                              ? [...selectedKnowledgeSetIds, set.id]
                              : selectedKnowledgeSetIds.filter(
                                  (id) => id !== set.id,
                                );
                            void saveKnowledgeSetSelection(nextIds);
                          }}
                        />
                        <span className="document-main">
                          <strong>{set.display_name}</strong>
                        </span>
                      </label>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </SectionCard>
        </aside>
      </div>
      <div className="button-row">
        <PageAction
          name="back"
          href={backHref ?? `/student/agents/${agent.id}`}
          disabled={saving}
          onClick={(event) => {
            if (localDirty && !window.confirm(t("discardDraftConfirm"))) {
              event.preventDefault();
              return;
            }
            const created = createdAgentRef.current;
            if (
              unsavedCreate &&
              created?.id &&
              !created.current_published_version_id
            ) {
              event.preventDefault();
              const href =
                backHref ??
                (created.group_id
                  ? `/student/groups/${created.group_id}`
                  : "/teacher/studyform");
              void (async () => {
                try {
                  await api.deleteAgent(created.id);
                  router.push(href);
                } catch (cause) {
                  setError(cause);
                }
              })();
            }
          }}
        />
        <PageAction
          name="done"
          disabled={
            saving ||
            (Boolean(unsavedCreate) &&
              (!draftName.trim() || !agentMd.trim()) &&
              retryAction !== "publish") ||
            (publishOnDone &&
              !unsavedCreate &&
              !generationFlow &&
              !localDirty &&
              retryAction !== "publish") ||
            (!publishOnDone &&
              !unsavedCreate &&
              !localDirty &&
              blockers.length > 0)
          }
          onClick={() => void publish()}
        />
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
  backHref,
}: {
  version: AgentVersion;
  agent: AgentDetail;
  actions?: ReactNode;
  backHref?: string;
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
      <PageAction
        name="back"
        href={backHref ?? `/student/groups/${agent.group_id}`}
      />
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
