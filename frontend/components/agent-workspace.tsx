"use client";

import { AgentHintBar } from "./agent-issue-list";
import {
  issueKey,
  readinessIssues,
  type AgentIssue,
} from "../lib/agent-readiness";
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
  PlatformApiError,
  type IdempotencyHandle,
  type AgentKnowledgeSets,
  type AgentDetail,
  type AgentVersion,
  type KnowledgeDocumentMutation,
  type AvatarTemplate,
  type KnowledgeDocument,
  type KnowledgeSetSummary,
  type KnowledgeSnapshot,
  type RagPreview,
  type VoiceProfile,
} from "../lib/api";
import {
  clearAgentDraftStash,
  loadAgentDraftStash,
  saveAgentDraftStash,
} from "../lib/agent-draft-stash";
import { groupLibraryOrClosed } from "../lib/group-library";
import { useIdempotencyStore } from "../lib/idempotency";
import { blockerLabel, statusLabel, type MessageKey } from "../lib/i18n";
import { useT } from "../lib/i18n";
import { cn } from "../lib/utils";
import { PRESS_MOTION } from "./ui/button";
import {
  AVATAR_TEMPLATE_DEFAULT_CONFIGS,
  AvatarEditor,
  AvatarPreview,
  avatarDefaultConfigForTemplate,
  type AvatarConfig,
} from "./avatar";
import { buildAgentTemplate } from "./agent-template";
import { PageAction } from "./page-action";
import { PageBanner } from "./page-banner";
import { ModuleUpload } from "./studyform-layout";
import { IconDownload, IconUpload } from "./quiet-icons";
import { VoiceLibrary } from "./voice/voice-library";
import {
  downloadText,
  KnowledgeCheckOverlay,
  KnowledgeRowActions,
  useKnowledgeCheck,
} from "./knowledge-check";
import { ReportMarkdown } from "./report/report-markdown";
import { useSession } from "./session-provider";
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  Notice,
  RetryPill,
  PageIntro,
  SectionCard,
  StatusBadge,
  StickerBadge,
} from "./ui";
import {
  AGENT_ICON_BUTTON,
  AGENT_NEW_BUTTON,
  AGENT_PAGE,
  agentCard,
} from "./agent-chrome";
import { celebrate } from "../lib/confetti";

/** Create/Edit (O2, option A) card contents, ported from fin.mjs WB/R2/CMP. */
const NAME_CARD = cn(
  agentCard("name"),
  "[&_.stack-form]:grid [&_.stack-form]:gap-6 [&_.stack-form_label]:grid [&_.stack-form_label]:gap-2",
  "[&_input[aria-label]]:box-border [&_input[aria-label]]:w-full [&_input[aria-label]]:rounded-[10px] [&_input[aria-label]]:border-[3px] [&_input[aria-label]]:border-[#111] [&_input[aria-label]]:bg-white [&_input[aria-label]]:px-3.5 [&_input[aria-label]]:py-2.5 [&_input[aria-label]]:font-body [&_input[aria-label]]:text-lg [&_input[aria-label]]:[line-height:normal] [&_input[aria-label]]:font-semibold",
  "[&_.visibility-toggle]:inline-flex [&_.visibility-toggle]:gap-0 [&_.visibility-toggle]:overflow-hidden [&_.visibility-toggle]:rounded-[10px] [&_.visibility-toggle]:border-[3px] [&_.visibility-toggle]:border-[#111] [&_.visibility-toggle]:bg-white [&_.visibility-toggle]:p-0 [&_.visibility-toggle]:shadow-[3px_3px_0_#111]",
  "[&_.visibility-toggle_button]:rounded-none [&_.visibility-toggle_button]:border-0 [&_.visibility-toggle_button]:bg-white [&_.visibility-toggle_button]:px-4 [&_.visibility-toggle_button]:py-1.5 [&_.visibility-toggle_button]:font-body [&_.visibility-toggle_button]:text-[13px] [&_.visibility-toggle_button]:font-extrabold [&_.visibility-toggle_button]:text-[#111] [&_.visibility-toggle_button]:shadow-none [&_.visibility-toggle_button+button]:border-l-[3px] [&_.visibility-toggle_button+button]:border-[#111] [&_.visibility-toggle_button[aria-pressed=true]]:bg-[#E5E7EB] [&_.visibility-toggle_button[aria-pressed=true]:last-child]:bg-[#22C55E]",
);
const MARKDOWN_CARD = cn(
  agentCard("markdown"),
  "[&_textarea.markdown-editor]:box-border [&_textarea.markdown-editor]:min-h-[240px] [&_textarea.markdown-editor]:w-full [&_textarea.markdown-editor]:rounded-[10px] [&_textarea.markdown-editor]:border-[3px] [&_textarea.markdown-editor]:border-[#111] [&_textarea.markdown-editor]:bg-white [&_textarea.markdown-editor]:font-mono [&_textarea.markdown-editor]:text-sm [&_textarea.markdown-editor]:leading-normal [&_textarea.markdown-editor]:font-medium",
  "[&_.editor-footer]:mt-2 [&_.editor-footer]:font-body [&_.editor-footer]:text-xs [&_.editor-footer]:[line-height:normal] [&_.editor-footer]:font-bold",
  "[&_.button-row]:flex [&_.button-row]:items-center [&_.button-row]:gap-1.5",
);
const BRAINFORM_ROWS =
  "[&_.brainform-source-group_h3]:font-display [&_.brainform-source-group_h3]:text-base [&_.brainform-source-group_h3]:font-extrabold [&_.brainform-source-group_h3]:tracking-normal [&_.brainform-source-group_h3]:text-[#111] " +
  "[&_.document-row]:mb-2 [&_.document-row]:rounded-[10px] [&_.document-row]:border-2 [&_.document-row]:border-[#111] [&_.document-row]:bg-white [&_.document-row]:shadow-[2px_2px_0_#111] " +
  "[&_.document-row_:is(span,strong,p)]:min-w-[6em] [&_.document-row_:is(span,strong,p)]:overflow-visible [&_.document-row_:is(span,strong,p)]:text-clip [&_.document-row_:is(span,strong,p)]:break-normal [&_.document-row_:is(span,strong,p)]:wrap-break-word [&_.document-row_:is(span,strong,p)]:whitespace-normal " +
  "[&_.row-actions]:flex [&_.row-actions]:items-center [&_.row-actions]:gap-1.5";
/** Filled Brainform: a hairline between the RAG and Knowledge groups, as in the mock. */
const BRAINFORM_SPLIT =
  "[&_.brainform-source-group+.brainform-source-group]:border-0 [&_.brainform-source-group+.brainform-source-group]:border-t [&_.brainform-source-group+.brainform-source-group]:border-solid [&_.brainform-source-group+.brainform-source-group]:border-[#E4E1D9]";
const BRAINFORM_COMPACT =
  "[&_.brainform-source-group]:m-0 [&_.brainform-source-group]:flex [&_.brainform-source-group]:items-baseline [&_.brainform-source-group]:gap-2.5 [&_.brainform-source-group]:border-0 [&_.brainform-source-group]:border-t-2 [&_.brainform-source-group]:border-dashed [&_.brainform-source-group]:border-[#1144] [&_.brainform-source-group]:px-0.5 [&_.brainform-source-group]:py-2 " +
  "[&_.brainform-source-group_h3]:m-0 [&_.brainform-source-group_h3]:min-w-[84px] [&_.brainform-source-group_h3]:text-sm [&_.brainform-source-group_h3]:leading-[1.5] " +
  "[&_.brainform-source-group_p]:m-0 [&_.brainform-source-group_p]:font-body [&_.brainform-source-group_p]:text-[13px] [&_.brainform-source-group_p]:[line-height:normal] [&_.brainform-source-group_p]:font-medium [&_.brainform-source-group_p]:text-[#1119]";
const AVATAR_CARD = cn(
  agentCard("avatar"),
  "[background:radial-gradient(ellipse_at_50%_46%,#FFE14D_0_20%,transparent_21%),repeating-conic-gradient(from_0deg_at_50%_32%,#FDBA74_0_9deg,#FFE7CC_9deg_18deg)]",
  "[&_[class*=canvasFrame]]:border-0 [&_[class*=canvasFrame]]:bg-none [&_[class*=canvasFrame]]:bg-transparent [&_canvas]:drop-shadow-[0_8px_0_#1113]",
  "[&_[class*=controlGrid]]:rounded-[12px] [&_[class*=controlGrid]]:border-[3px] [&_[class*=controlGrid]]:border-[#111] [&_[class*=controlGrid]]:bg-white [&_[class*=controlGrid]]:p-3 [&_[class*=controlGrid]]:shadow-[4px_4px_0_#111]",
  "[&_select]:h-10 [&_select]:rounded-[8px] [&_select]:border-2 [&_select]:border-[#111] [&_select]:bg-white",
  "[&_:is([class*=buttonRow],[class*=templateGrid])_button]:rounded-[10px] [&_:is([class*=buttonRow],[class*=templateGrid])_button]:border-2 [&_:is([class*=buttonRow],[class*=templateGrid])_button]:border-[#111] [&_:is([class*=buttonRow],[class*=templateGrid])_button]:bg-white [&_:is([class*=buttonRow],[class*=templateGrid])_button]:font-body [&_:is([class*=buttonRow],[class*=templateGrid])_button]:text-[13px] [&_:is([class*=buttonRow],[class*=templateGrid])_button]:font-bold [&_:is([class*=buttonRow],[class*=templateGrid])_button]:shadow-[0_6px_0_#111] [&_:is([class*=buttonRow],[class*=templateGrid])_button]:transition-[translate,box-shadow,background-color,color] [&_:is([class*=buttonRow],[class*=templateGrid])_button]:duration-150 [&_:is([class*=buttonRow],[class*=templateGrid])_button]:ease-[cubic-bezier(.2,.8,.2,1)] [&_:is([class*=buttonRow],[class*=templateGrid])_button]:hover:-translate-y-0.5 [&_:is([class*=buttonRow],[class*=templateGrid])_button]:active:translate-y-1.5 [&_:is([class*=buttonRow],[class*=templateGrid])_button]:active:shadow-none [&_:is([class*=buttonRow],[class*=templateGrid])_button]:active:duration-[80ms] [&_:is([class*=buttonRow],[class*=templateGrid])_button]:motion-reduce:transition-colors [&_:is([class*=buttonRow],[class*=templateGrid])_button]:motion-reduce:hover:translate-y-0 [&_:is([class*=buttonRow],[class*=templateGrid])_button]:motion-reduce:active:translate-y-0 [&_:is([class*=buttonRow],[class*=templateGrid])_button]:motion-reduce:active:shadow-[0_6px_0_#111]",
  "[&_:is([aria-pressed=true],[aria-checked=true])]:bg-[#A3E635]",
  "max-[767px]:[&_[class*=canvasFrame]]:max-h-[300px]",
);
const TEMPLATE_BUTTON = `inline-flex h-11 box-border cursor-pointer items-center rounded-[10px] border-2 border-[#111] bg-white px-3.5 py-0 font-body text-sm font-bold text-[#111] no-underline disabled:cursor-not-allowed disabled:opacity-50 ${PRESS_MOTION}`;

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
      router.replace(`/student/agents?group_id=${agent.group_id}`);
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) setRetryAction("delete");
      else mutationStore.abandon(intent, handle);
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingCard size="sm" />;
  if (!agent)
    return (
      <ErrorNotice
        inline
        notFound="agentNotFound"
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
    agent.can_edit === true &&
    !visible &&
    !agent.current_published_version_id &&
    versions.every(
      (version) => version.state === "draft" && !version.knowledge_snapshot_id,
    );
  const editorVersion = current ?? draft;
  const entryBack = agent.group_id
    ? `/student/agents?group_id=${agent.group_id}`
    : "/student";
  if (editorVersion && agent.can_edit === true) {
    return (
      <AgentWorkbench
        versionId={editorVersion.id}
        backHref={entryBack}
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
      <SectionCard action={actions}>
        <PageAction
          name="back"
          href={`/student/agents?group_id=${agent.group_id}`}
        />
        <EmptyCard title={t("noVersions")} />
      </SectionCard>
    </>
  );
}

// The editor offers the library Brainform lists, plus whatever this Agent
// already uses. A private file belongs only to the Agent it was uploaded into,
// and a Knowledge set whose Agent was deleted is no longer in the library.
function libraryDocuments(
  rows: KnowledgeDocument[],
  boundIds: string[],
): KnowledgeDocument[] {
  const bound = new Set(boundIds);
  return rows.filter(
    (document) => document.visibility !== "private" || bound.has(document.id),
  );
}

// A withdrawn library file may still sit on a published version's enabled set.
// Selection and Done only keep active ids; hidden rows stay visible and disabled.
function mergeBoundDocuments(
  library: KnowledgeDocument[],
  bound: KnowledgeDocument[],
): KnowledgeDocument[] {
  const byId = new Map(library.map((document) => [document.id, document]));
  for (const document of bound) {
    if (!byId.has(document.id)) byId.set(document.id, document);
  }
  return [...byId.values()];
}

function activeDocumentIds(documents: KnowledgeDocument[]): string[] {
  return documents
    .filter((document) => document.workspace_state === "active")
    .map((document) => document.id);
}

function librarySetIds(
  rows: { canonical_set_id: string }[] | null,
): Set<string> | null {
  return rows === null
    ? null
    : new Set(rows.map((row) => row.canonical_set_id));
}

function libraryKnowledgeSets(
  rows: KnowledgeSetSummary[],
  listed: Set<string> | null,
  boundIds: string[],
): KnowledgeSetSummary[] {
  if (listed === null) return rows;
  const bound = new Set(boundIds);
  return rows.filter((set) => listed.has(set.id) || bound.has(set.id));
}

function brainformSetIds(
  api: {
    brainformKnowledge?: (
      courseId: string,
    ) => Promise<{ canonical_set_id: string }[]>;
  },
  courseId: string,
): Promise<Set<string> | null> {
  // Without Brainform's list the editor keeps every readable set rather than
  // hiding real ones.
  if (typeof api.brainformKnowledge !== "function")
    return Promise.resolve(null);
  return api
    .brainformKnowledge(courseId)
    .then(librarySetIds)
    .catch(() => null);
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
  const { api, user } = useSession();
  const stashUserId = user?.id;
  // Read through a ref so the session arriving does not reload the editor.
  const stashUserIdRef = useRef(stashUserId);
  useLayoutEffect(() => {
    stashUserIdRef.current = stashUserId;
  }, [stashUserId]);
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
  // Private files this editor has already offered stay offered, so a file
  // unticked here can be ticked again after a reload of the same editor.
  const offeredDocumentIds = useRef<Set<string>>(new Set());
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
  const [avatarTemplatesError, setAvatarTemplatesError] =
    useState<unknown>(null);
  const [avatarTemplatesLoading, setAvatarTemplatesLoading] = useState(false);
  const avatarLoadSequence = useRef(0);
  const [avatarConfig, setAvatarConfig] = useState<AvatarConfig | null>(null);
  const [voiceProfileId, setVoiceProfileId] = useState<string | null>(null);
  const [voiceProfiles, setVoiceProfiles] = useState<VoiceProfile[]>([]);
  const [agentIssuesDismissed, setAgentIssuesDismissed] = useState(false);
  // After a line's Done the bar is pinned to what was on screen, minus the
  // line that now passes, so one check never moves the other lines.
  const [checkedIssues, setCheckedIssues] = useState<{
    agentId: string;
    issues: AgentIssue[];
  } | null>(null);
  const [checkingIssue, setCheckingIssue] = useState<string | null>(null);
  const stayAfterPublish = useRef(false);
  const [agentMd, setAgentMd] = useState("");
  const [draftName, setDraftName] = useState("");
  const [draftVisibility, setDraftVisibility] = useState<"private" | "public">(
    "private",
  );
  // An existing Agent's name typed on its Name card; null while unchanged.
  // Done saves it before publishing (AGENT.md no longer renames the Agent).
  const [renameDraft, setRenameDraft] = useState<string | null>(null);
  const [makingPublic, setMakingPublic] = useState(false);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingRequest, setSavingRequest] = useState<{ scope: string } | null>(
    null,
  );
  const [publishingRequest, setPublishingRequest] = useState<{
    scope: string;
  } | null>(null);
  const saving = savingRequest?.scope === workbenchScope;
  const publishing = publishingRequest?.scope === workbenchScope;
  const editingLocked = saving || publishing;
  // View/download in Brainform reads the server copy, as read-only mode does;
  // it never edits RAG and stays usable while editing is locked by publish.
  const knowledgeCheck = useKnowledgeCheck();
  const knowledgeCheckDisabled = saving || knowledgeCheck.busy;
  const [error, setError] = useState<unknown>(null);
  // Shown only after Done on create; empty name / AGENT.md stay quiet until then.
  const [submitHint, setSubmitHint] = useState("");
  const nameField = useRef<HTMLInputElement>(null);
  const nameMissing =
    submitHint !== "" && submitHint === t("agentNameRequired");
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
  // Files chosen on a published version wait for Done, which makes the next
  // draft; a published version itself can never take a new file.
  const [stagedRag, setStagedRag] = useState<
    { file: File; signature: string }[]
  >([]);
  const [pendingKnowledgeUpload, setPendingKnowledgeUpload] = useState<{
    file: File;
    signature: string;
  } | null>(null);
  const versionKey = versionId ?? "new";
  const uploadIntent = `${workbenchScope}:upload-knowledge:${versionKey}`;
  const knowledgeBindingIntent = `${workbenchScope}:knowledge-sets:${agent?.id ?? versionKey}`;
  const publishIntent = `${workbenchScope}:publish-agent-version:${versionKey}`;
  const createdAgentRef = useRef<AgentDetail | null>(null);
  const persistedVersionRef = useRef<AgentVersion | null>(null);
  const publishLock = useRef<{ scope: string } | null>(null);
  const unsavedGroupId = unsavedCreate?.groupId ?? null;
  const unsavedCourseId = unsavedCreate?.courseId ?? null;
  const creating = unsavedCreate !== undefined;

  function beginSaving() {
    const request = { scope: workbenchScope };
    setSavingRequest(request);
    return request;
  }

  function finishSaving(request: { scope: string }) {
    if (workbenchMounted.current) {
      setSavingRequest((current) => (current === request ? null : current));
    }
  }

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

  // The API marks transient OCR/worker import failures as retryable; capacity
  // and corruption answers are final and must not offer a Retry button.
  function isRetryableKnowledgeImport(cause: unknown): boolean {
    if (!(cause instanceof PlatformApiError)) return false;
    if (cause.details?.retryable === true) return true;
    return (
      cause.details?.retryable !== false &&
      (cause.code === "knowledge_import_ocr_unavailable" ||
        cause.code === "knowledge_import_ocr_failed" ||
        cause.code === "knowledge_import_ocr_timeout" ||
        cause.code === "knowledge_import_processing_failed")
    );
  }

  function abandonPublishIntent() {
    mutationStore.abandon(publishIntent);
    setRetryAction((current) => (current === "publish" ? null : current));
  }

  const loadAvatarTemplates = useCallback(async () => {
    const requestScope = workbenchScope;
    const sequence = ++avatarLoadSequence.current;
    setAvatarTemplatesLoading(true);
    setAvatarTemplatesError(null);
    try {
      const templates = await api.avatarTemplates();
      if (
        !isCurrentScope(requestScope) ||
        sequence !== avatarLoadSequence.current
      )
        return null;
      setAvatarTemplates(templates);
      return templates;
    } catch (cause) {
      if (
        isCurrentScope(requestScope) &&
        sequence === avatarLoadSequence.current
      ) {
        setAvatarTemplatesError(cause);
      }
      return null;
    } finally {
      if (
        isCurrentScope(requestScope) &&
        sequence === avatarLoadSequence.current
      ) {
        setAvatarTemplatesLoading(false);
      }
    }
  }, [api, workbenchScope]);

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
            nextKnowledgeSets,
            nextLibrarySetIds,
          ] = await Promise.all([
            unsavedGroupId
              ? api.knowledge(unsavedGroupId)
              : api.workspaceDocuments(courseId),
            loadAvatarTemplates(),
            api.knowledgeSets(courseId),
            brainformSetIds(api, courseId),
          ]);
          if (!isCurrentScope(requestScope)) return;
          const baselineAvatar =
            (nextAvatarTemplates ?? [])
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
          if (!keepLocal) offeredDocumentIds.current = new Set();
          const offered = libraryDocuments(nextDocuments, [
            ...offeredDocumentIds.current,
          ]);
          offered.forEach((document) => {
            if (document.workspace_state === "active") {
              offeredDocumentIds.current.add(document.id);
            }
          });
          setDocuments(offered);
          setKnowledgeSets(
            libraryKnowledgeSets(nextKnowledgeSets, nextLibrarySetIds, []),
          );
          setAgentKnowledge({
            agent_id: "",
            agent_metadata_revision: 0,
            sets: [],
          });
          setPreview(null);
          setKnowledgePreviewRefreshFailed(false);
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
        void loadAvatarTemplates();
        const [
          nextDocuments,
          nextPreview,
          nextKnowledgeSets,
          nextAgentKnowledge,
          nextLibrarySetIds,
        ] = await Promise.all([
          nextAgent.group_id
            ? groupLibraryOrClosed(api.knowledge(nextAgent.group_id))
            : api.workspaceDocuments(nextAgent.course_id),
          // Preview is draft-only. A published version is the editor baseline
          // until Done, and its preview request is a not-found.
          nextVersion.state === "draft"
            ? api.ragPreview(versionId)
            : Promise.resolve(null),
          api.knowledgeSets(nextAgent.course_id),
          api.agentKnowledgeSets(nextAgent.id),
          brainformSetIds(api, nextAgent.course_id),
        ]);
        if (!isCurrentScope(requestScope)) return;
        setVersion(nextVersion);
        setAgent(nextAgent);
        if (!keepLocal) offeredDocumentIds.current = new Set();
        const enabledDocuments = nextVersion.enabled_documents ?? [];
        const offered = libraryDocuments(
          mergeBoundDocuments(nextDocuments, enabledDocuments),
          [
            ...enabledDocuments.map((document) => document.id),
            ...offeredDocumentIds.current,
          ],
        );
        offered.forEach((document) => {
          if (document.workspace_state === "active") {
            offeredDocumentIds.current.add(document.id);
          }
        });
        setDocuments(offered);
        const boundSetIds = nextAgentKnowledge.sets.map((set) => set.id);
        setKnowledgeSets(
          libraryKnowledgeSets(
            Array.from(
              new Map(
                [...nextKnowledgeSets, ...nextAgentKnowledge.sets].map(
                  (set) => [set.id, set],
                ),
              ).values(),
            ),
            nextLibrarySetIds,
            boundSetIds,
          ),
        );
        setAgentKnowledge(nextAgentKnowledge);
        setPreview(nextPreview);
        setKnowledgePreviewRefreshFailed(false);
        if (!keepLocal) {
          setAgentMd(nextVersion.agent_md ?? "");
          setAvatarConfig(nextVersion.avatar_config);
          setVoiceProfileId(nextVersion.voice_profile_id ?? null);
          setSelectedDocumentIds(activeDocumentIds(enabledDocuments));
          setSelectedKnowledgeSetIds(
            nextAgentKnowledge.sets.map((set) => set.id),
          );
          setPendingKnowledgeSetIds(null);
          setConflict(false);
          // A Done that lost to another editor kept its edits in this
          // browser; put them straight back on top of the latest version.
          const stash = loadAgentDraftStash(
            stashUserIdRef.current,
            nextAgent.id,
          );
          if (stash) {
            const offeredIds = new Set(
              offered
                .filter((document) => document.workspace_state === "active")
                .map((document) => document.id),
            );
            setAgentMd(stash.agent_md);
            if (stash.avatar_config) setAvatarConfig(stash.avatar_config);
            setVoiceProfileId(stash.voice_profile_id);
            setSelectedDocumentIds(
              stash.document_ids.filter((id) => offeredIds.has(id)),
            );
            setNotice("localDraftRestoredNotice");
          }
        }
      } catch (cause) {
        if (isCurrentScope(requestScope)) setError(cause);
      } finally {
        if (isCurrentScope(requestScope)) setLoading(false);
      }
    },
    [
      api,
      creating,
      loadAvatarTemplates,
      unsavedCourseId,
      unsavedGroupId,
      versionId,
      workbenchScope,
    ],
  );
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const enabledCount = selectedDocumentIds.length;
  const sameIds = (left: string[], right: string[]) =>
    left.length === right.length &&
    [...left].sort().every((id, index) => id === [...right].sort()[index]);
  const localDirty = Boolean(
    version &&
    (stagedRag.length > 0 ||
      agentMd !== (version.agent_md ?? "") ||
      JSON.stringify(avatarConfig) !== JSON.stringify(version.avatar_config) ||
      voiceProfileId !== (version.voice_profile_id ?? null) ||
      !sameIds(
        selectedDocumentIds,
        activeDocumentIds(version.enabled_documents ?? []),
      ) ||
      (agentKnowledge !== null &&
        !sameIds(
          selectedKnowledgeSetIds,
          agentKnowledge.sets.map((set) => set.id),
        ))),
  );
  const blockers = version?.publish_blockers ?? [];

  if (loading) return <LoadingCard size="sm" />;
  // Keep the loaded workbench mounted for mutation errors so local AGENT.md,
  // avatar/voice edits, selected documents, and retry handles remain visible
  // and usable. A load error without the required records still uses the
  // standalone recovery view below.
  if (!version || !agent)
    return (
      <ErrorNotice
        inline
        notFound="agentNotFound"
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
  // A published version outside publishOnDone is only a hand-off: Done has
  // already sent the user to the agent overview (the read-only view is gone).
  if (version.state !== "draft" && !publishOnDone)
    return <LoadingCard size="sm" />;

  function stashLocalDraft() {
    if (!agent?.id) return;
    saveAgentDraftStash(stashUserId, agent.id, {
      agent_md: agentMd,
      avatar_config: avatarConfig ?? null,
      voice_profile_id: voiceProfileId,
      document_ids: selectedDocumentIds,
      base_version_id: version?.id ?? null,
    });
  }

  async function saveDraft() {
    const requestScope = workbenchScope;
    abandonUploadIntent();
    abandonPublishIntent();
    const savingRequest = beginSaving();
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
        if (isConflict(cause)) {
          stashLocalDraft();
          setConflict(true);
        }
        setError(cause);
      }
    } finally {
      finishSaving(savingRequest);
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
    const savingRequest = beginSaving();
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
      finishSaving(savingRequest);
    }
  }

  async function toggleDocument(documentId: string, enabled: boolean) {
    const target = documents.find((document) => document.id === documentId);
    if (target?.workspace_state === "hidden") return;
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
    const savingRequest = beginSaving();
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
      setSelectedDocumentIds(activeDocumentIds(next.enabled_documents ?? []));
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
      finishSaving(savingRequest);
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
    if (publishOnDone && currentVersion.state !== "draft") {
      setStagedRag((current) =>
        current.some((item) => item.signature === signature)
          ? current
          : [...current, { file, signature }],
      );
      setError(null);
      setKnowledgeUploadError(null);
      return;
    }
    // A Retry click during an in-flight upload must not double-submit.
    if (saving) return;
    if (pendingKnowledgeUpload?.signature !== signature) {
      mutationStore.abandon(uploadIntent);
    }
    abandonPublishIntent();
    setPendingKnowledgeUpload({ file, signature });
    const savingRequest = beginSaving();
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
      offeredDocumentIds.current.add(mutation.document.id);
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
      } else if (!mutationCompleted && isRetryableKnowledgeImport(cause)) {
        // A 422 import failure never mutated anything, so the handle is
        // abandoned and the retry gets a fresh key while reusing the file.
        mutationStore.abandon(uploadIntent, handle);
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
      finishSaving(savingRequest);
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
        offeredDocumentIds.current.add(mutation.document.id);
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
    const enabledIds = activeDocumentIds(saved.enabled_documents ?? []);
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

  /**
   * Private → Public, once, by the creator. Like copying the Agent to Public:
   * the server turns it and its RAG public in place (same Agent, so chats
   * carry on), then Done's publish makes the new public version.
   */
  async function makePublic() {
    if (!window.confirm(t("agentMakePublicConfirm"))) return;
    const requestScope = workbenchScope;
    setMakingPublic(true);
    setError(null);
    try {
      // A name typed on the card goes in the same request, so Done's
      // publish below has nothing left to rename.
      const typed = renameDraft?.trim();
      const made = await api.updateAgentMetadata(currentAgent.id, {
        visibility: "public",
        ...(typed && typed !== currentAgent.name ? { name: typed } : {}),
        expected_metadata_revision: currentAgent.metadata_revision,
      });
      if (!isCurrentScope(requestScope)) return;
      setAgent((current) => (current ? { ...current, ...made } : current));
      setRenameDraft(null);
      setDraftVisibility("public");
    } catch (cause) {
      if (isCurrentScope(requestScope)) setError(cause);
      return;
    } finally {
      if (workbenchMounted.current) setMakingPublic(false);
    }
    await publish(false, true);
  }

  async function publish(retry = false, nameSaved = false) {
    const requestScope = workbenchScope;
    if (publishLock.current?.scope === requestScope) return;
    if (unsavedCreate) {
      const validation = !draftName.trim()
        ? t("agentNameRequired")
        : !agentMd.trim()
          ? t("agentMdRequired")
          : "";
      if (validation) {
        setSubmitHint(validation);
        setError(null);
        return;
      }
      setSubmitHint("");
    } else if (renameDraft !== null && !renameDraft.trim()) {
      setSubmitHint(t("agentNameRequired"));
      setError(null);
      return;
    }
    const request = { scope: requestScope };
    publishLock.current = request;
    setPublishingRequest(request);
    try {
      await publishCurrent(retry, nameSaved);
    } catch (cause) {
      if (!isCurrentScope(requestScope)) return;
      if (isConflict(cause)) {
        stashLocalDraft();
        setConflict(true);
      }
      if (isAmbiguousMutationFailure(cause)) setRetryAction("publish");
      setError(cause);
    } finally {
      if (publishLock.current === request) publishLock.current = null;
      if (workbenchMounted.current) {
        setPublishingRequest((current) =>
          current === request ? null : current,
        );
      }
    }
  }

  async function publishCurrent(retry: boolean, nameSaved = false) {
    const requestScope = workbenchScope;
    if (generationFlow && selectedDocumentIds.length === 0) {
      setGenerationSourcePrompt(true);
      setError(null);
      return;
    }
    setGenerationSourcePrompt(false);
    if (unsavedCreate) {
      const savingRequest = beginSaving();
      setError(null);
      setNotice(null);
      try {
        const materialized = await writeUnsavedAgent();
        if (!materialized || !isCurrentScope(requestScope)) return;
        const saved = materialized.version;
        const activeAgent = materialized.agent;
        if ((saved.publish_blockers ?? []).length > 0) {
          setError(new Error(blockerLabel(saved.publish_blockers?.[0] ?? "")));
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
        clearAgentDraftStash(stashUserId, activeAgent.id);
        celebrate();
        setNotice("publishedNotice");
        router.replace(
          activeAgent.group_id
            ? `/student/agents?group_id=${activeAgent.group_id}`
            : "/teacher/agents",
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
        finishSaving(savingRequest);
      }
      return;
    }
    // A typed name is saved first, on its own: the Name card owns the name.
    if (
      !nameSaved &&
      renameDraft !== null &&
      renameDraft.trim() !== currentAgent.name
    ) {
      const renamed = await api.updateAgentMetadata(currentAgent.id, {
        name: renameDraft.trim(),
        expected_metadata_revision: currentAgent.metadata_revision,
      });
      if (!isCurrentScope(requestScope)) return;
      setAgent((current) => (current ? { ...current, ...renamed } : current));
      setRenameDraft(null);
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
        saved = await api.nextVersion(currentAgent.id, {
          idempotency: handle,
          // The published version this editor started from: if someone else
          // has published since, the server answers 409 stale_base_version.
          expectedBaseVersionId: saved.id,
        });
        mutationStore.finish(intent, handle);
        if (!isCurrentScope(requestScope)) return;
      } catch (cause) {
        if (!isCurrentScope(requestScope)) return;
        if (isConflict(cause)) {
          mutationStore.abandon(intent, handle);
          throw cause;
        }
        if (isAmbiguousMutationFailure(cause)) {
          setError(cause);
          setRetryAction("publish");
          return;
        }
        mutationStore.abandon(intent, handle);
        const versions = await api.versions(currentAgent.id);
        if (!isCurrentScope(requestScope)) return;
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
      if (!isCurrentScope(requestScope)) return;
      saved = written;
    }
    const uploadedIds: string[] = [];
    if (publishOnDone && saved && stagedRag.length > 0) {
      let draft: AgentVersion = saved;
      for (const item of stagedRag) {
        // Keyed by the file, so a retried Done replays the same upload.
        const intent = `agent-staged-rag:${currentAgent.id}:${item.signature}`;
        const handle = mutationStore.handleFor(intent);
        try {
          const mutation: KnowledgeDocumentMutation = currentAgent.group_id
            ? await api.uploadKnowledge(
                currentAgent.group_id,
                draft.id,
                item.file,
                draft.revision,
                { idempotency: handle },
              )
            : await api.uploadWorkspaceKnowledge(
                currentAgent.course_id,
                draft.id,
                item.file,
                draft.revision,
                { idempotency: handle },
              );
          mutationStore.finish(intent, handle);
          if (mutation.agent_version) draft = mutation.agent_version;
          uploadedIds.push(mutation.document.id);
        } catch (cause) {
          if (!isCurrentScope(requestScope)) return;
          if (isAmbiguousMutationFailure(cause)) setRetryAction("publish");
          else mutationStore.abandon(intent, handle);
          setError(cause);
          return;
        }
      }
      saved = draft;
    }
    if (publishOnDone && saved) {
      const documentIds = activeDocumentIds(saved.enabled_documents ?? []);
      const wanted = [
        ...selectedDocumentIds,
        ...uploadedIds.filter((id) => !selectedDocumentIds.includes(id)),
      ];
      if (!sameIds(wanted, documentIds)) {
        saved = await api.setDocuments(saved.id, saved.revision, wanted);
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
    const savingRequest = beginSaving();
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
      setStagedRag([]);
      setVersion(next);
      clearAgentDraftStash(stashUserId, currentAgent.id);
      if (generationFlow) {
        const receipt = next.knowledge_generation;
        if (!receipt) {
          setError(new Error(t("generationReceiptMissing")));
          return;
        }
        celebrate();
        router.replace(
          `/teacher/knowledge?agent_id=${encodeURIComponent(currentAgent.id)}&set_id=${encodeURIComponent(receipt.knowledge_set_id)}&job_id=${encodeURIComponent(receipt.job_id)}`,
        );
        return;
      }
      celebrate();
      setNotice("publishedNotice");
      if (stayAfterPublish.current) {
        // A hint line's Done publishes in place and reads the Agent again.
        const fresh = await api.agent(currentAgent.id);
        if (isCurrentScope(requestScope)) setAgent(fresh);
        return;
      }
      router.replace(
        publishOnDone
          ? (backHref ??
              (currentAgent.group_id
                ? `/student/agents?group_id=${currentAgent.group_id}`
                : "/teacher/agents"))
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
      finishSaving(savingRequest);
    }
  }

  // Before the first Done there is no Agent to upload into, so the file
  // waits here; it must still be listed or the author thinks it was dropped.
  const queuedCreateRag =
    creating && !agent?.id ? pendingKnowledgeUpload : null;

  // Read by the server from the current published version (agents/readiness.py),
  // the same rules a new Debate applies.
  const agentIssues =
    checkedIssues && checkedIssues.agentId === agent.id
      ? checkedIssues.issues
      : readinessIssues(agent);

  async function checkIssue(item: AgentIssue) {
    const key = issueKey(item);
    const shown = agentIssues;
    setCheckingIssue(key);
    // Like the sidebar Done, only edits are published; with none, the line
    // is simply checked again against what is already published.
    if (localDirty || retryAction === "publish") {
      stayAfterPublish.current = true;
      try {
        await publish(retryAction === "publish");
      } finally {
        stayAfterPublish.current = false;
      }
    }
    try {
      const fresh = await api.agent(item.agent_id);
      const stillThere = readinessIssues(fresh).some(
        (candidate) => issueKey(candidate) === key,
      );
      setCheckedIssues({
        agentId: item.agent_id,
        issues: stillThere
          ? shown
          : shown.filter((candidate) => issueKey(candidate) !== key),
      });
    } catch {
      // The line stays; the publish error, if any, is already shown.
    } finally {
      setCheckingIssue(null);
    }
  }

  const brainformEmpty =
    documents.length === 0 &&
    stagedRag.length === 0 &&
    !queuedCreateRag &&
    knowledgeSets.length === 0;
  const voicesEmpty = voiceProfiles.length === 0;
  const duoEmpty = brainformEmpty && voicesEmpty;

  return (
    <>
      <div className={AGENT_PAGE}>
        <PageBanner
          title={
            unsavedCreate
              ? draftName.trim()
                ? `${draftName.trim()} · ${version.version_label}`
                : t("newAgent")
              : `${agent.name} · ${version.version_label}`
          }
        >
          <PageAction
            name="back"
            placement="page"
            href={backHref ?? `/student/agents/${agent.id}`}
            disabled={editingLocked}
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
                    ? `/student/agents?group_id=${created.group_id}`
                    : "/teacher/agents");
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
            placement="page"
            disabled={
              editingLocked ||
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
        </PageBanner>
        {!unsavedCreate && !agentIssuesDismissed ? (
          <AgentHintBar
            title={t("agentIssuesTitle")}
            issues={agentIssues}
            onCheck={
              generationFlow ? undefined : (item) => void checkIssue(item)
            }
            checking={checkingIssue}
            onDismiss={() => setAgentIssuesDismissed(true)}
          />
        ) : null}
        {generationFlow ? (
          <Notice tone="info">{t("aiKnowledgeFlowIntro")}</Notice>
        ) : null}
        {conflict ? <DraftConflictNotice /> : null}
        {error &&
        !conflict &&
        error !== knowledgeUploadError &&
        !unsavedCreate ? (
          <>
            <ErrorNotice
              error={error}
              onRetry={
                retryAction === "uploadKnowledge" && pendingKnowledgeUpload
                  ? () => void uploadKnowledge(pendingKnowledgeUpload.file)
                  : retryAction === "bindKnowledge" && pendingKnowledgeSetIds
                    ? () =>
                        void saveKnowledgeSetSelection(pendingKnowledgeSetIds)
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
          <Notice
            tone="warning"
            title={t("aiKnowledgeSourcesRequired")}
            onClose={() => setGenerationSourcePrompt(false)}
          >
            {t("aiKnowledgeSourcesRequiredHelp")}
          </Notice>
        ) : null}
        {notice ? (
          <Notice
            tone="success"
            title={t("done")}
            onClose={() => setNotice(null)}
          >
            {t(notice)}
          </Notice>
        ) : null}
        <div className="grid gap-8">
          <div className="grid grid-cols-1 items-start gap-x-9 gap-y-11 min-[768px]:grid-cols-[minmax(0,400px)_minmax(0,1fr)]">
            <div className="col-span-full grid gap-4 empty:hidden">
              {unsavedCreate && submitHint ? (
                // The mascot tray says it; the field it is about is marked and
                // gets focus back once the notice is dismissed.
                <Notice
                  id="agent-submit-hint"
                  tone="error"
                  badge={nameMissing ? 1 : undefined}
                  onClose={() => {
                    const field = nameMissing ? nameField.current : null;
                    setSubmitHint("");
                    field?.focus();
                  }}
                >
                  {submitHint}
                </Notice>
              ) : null}
              {unsavedCreate &&
              error &&
              !conflict &&
              error !== knowledgeUploadError ? (
                <ErrorNotice
                  inline
                  error={error}
                  onRetry={
                    retryAction === "publish"
                      ? () => {
                          void publish(true);
                        }
                      : undefined
                  }
                />
              ) : null}
            </div>
            <div className="stage sticky top-5 grid gap-11 self-start max-[767px]:static max-[767px]:order-2">
              {avatarConfig ? (
                <SectionCard title={t("avatarDesign")} className={AVATAR_CARD}>
                  {avatarTemplatesError ? (
                    <ErrorNotice
                      inline
                      error={avatarTemplatesError}
                      onRetry={() => void loadAvatarTemplates()}
                    />
                  ) : null}
                  {avatarTemplatesLoading ? <LoadingCard size="sm" /> : null}
                  <AvatarEditor
                    templates={avatarTemplates}
                    value={avatarConfig}
                    onChange={setAvatarConfig}
                    fallbackLabel={agent.name}
                    disabled={
                      editingLocked ||
                      avatarTemplatesLoading ||
                      Boolean(avatarTemplatesError)
                    }
                  />
                </SectionCard>
              ) : null}
            </div>
            <div className="stats grid min-w-0 gap-11 max-[767px]:order-1">
              {unsavedCreate ? (
                <SectionCard title={t("agentName")} className={NAME_CARD}>
                  <form
                    id="create-agent-form"
                    className="stack-form wide-form quiet-create"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void publish();
                    }}
                  >
                    <label className="relative">
                      {nameMissing ? <StickerBadge n={1} /> : null}
                      <input
                        ref={nameField}
                        aria-label={t("agentName")}
                        aria-invalid={nameMissing || undefined}
                        aria-describedby={
                          nameMissing ? "agent-submit-hint" : undefined
                        }
                        className="aria-invalid:border-[3px]! aria-invalid:border-err! aria-invalid:bg-surface! aria-invalid:shadow-[0_0_0_3px_#FFE4E4,3px_3px_0_#EF4444]!"
                        value={draftName}
                        disabled={editingLocked}
                        maxLength={120}
                        onChange={(event) => {
                          setSubmitHint("");
                          unsavedCreate.onIdentityEdit?.();
                          setDraftName(event.target.value);
                        }}
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
                            disabled={editingLocked}
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
              ) : (
                <SectionCard title={t("agentName")} className={NAME_CARD}>
                  <form
                    className="stack-form wide-form quiet-create"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void publish();
                    }}
                  >
                    <label className="relative">
                      <input
                        aria-label={t("agentName")}
                        value={renameDraft ?? currentAgent.name}
                        disabled={editingLocked || makingPublic}
                        maxLength={120}
                        onChange={(event) => {
                          setSubmitHint("");
                          setRenameDraft(event.target.value);
                        }}
                      />
                    </label>
                    <div className="agent-identity">
                      {/* Private can become Public (the creator, once);
                          Public never goes back. */}
                      <div
                        className="visibility-toggle"
                        role="group"
                        aria-label={t("agentVisibility")}
                        data-ui-guide="agent.visibility"
                      >
                        <button
                          type="button"
                          aria-pressed={currentAgent.visibility === "private"}
                          disabled={currentAgent.visibility === "public"}
                          title={
                            currentAgent.visibility === "public"
                              ? t("agentPublicIsFinal")
                              : undefined
                          }
                        >
                          {t("privateOption")}
                        </button>
                        <button
                          type="button"
                          aria-pressed={currentAgent.visibility === "public"}
                          aria-busy={makingPublic || undefined}
                          disabled={
                            currentAgent.visibility === "private" &&
                            (currentAgent.is_creator !== true ||
                              editingLocked ||
                              makingPublic)
                          }
                          onClick={() => {
                            if (currentAgent.visibility === "private") {
                              void makePublic();
                            }
                          }}
                        >
                          {t("publicOption")}
                        </button>
                      </div>
                    </div>
                  </form>
                </SectionCard>
              )}
              <SectionCard
                title={t("agentMd")}
                guide="agent.markdown"
                className={MARKDOWN_CARD}
                action={
                  <div className="button-row">
                    <button
                      className={TEMPLATE_BUTTON}
                      type="button"
                      disabled={editingLocked}
                      onClick={() => {
                        abandonUploadIntent();
                        abandonPublishIntent();
                        setAgentMd(
                          buildAgentTemplate(draftName.trim() || agent.name),
                        );
                      }}
                    >
                      {t("insertOutline")}
                    </button>
                    <button
                      className={AGENT_ICON_BUTTON}
                      type="button"
                      disabled={editingLocked || !agentMd}
                      aria-label={`${t("download")} AGENT.md`}
                      data-ui-guide="agent.download"
                      onClick={() => downloadText(agentMd, "AGENT.md")}
                    >
                      <IconDownload />
                    </button>
                    <label
                      className={AGENT_ICON_BUTTON}
                      data-ui-guide="agent.uploadMarkdown"
                    >
                      <IconUpload />
                      <input
                        className="sr-only"
                        type="file"
                        accept=".md,text/markdown"
                        aria-label={t("uploadMd")}
                        disabled={editingLocked}
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
                  disabled={editingLocked}
                  onChange={(event) => {
                    setSubmitHint("");
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
              <div
                className={cn(
                  "duo grid min-w-0 gap-11",
                  duoEmpty && "grid-cols-2 gap-7 max-[767px]:grid-cols-1",
                )}
              >
                <SectionCard
                  title={t("brainform")}
                  guide="agent.brainform"
                  className={cn(
                    agentCard("brainform", brainformEmpty),
                    BRAINFORM_ROWS,
                    brainformEmpty ? BRAINFORM_COMPACT : BRAINFORM_SPLIT,
                    "[&_label[data-ui-guide='agent.uploadRag']]:shadow-[6px_6px_0_#111]",
                  )}
                  action={
                    // RAG is added only here, inside its Agent, and takes the
                    // Agent's Private or Public.
                    <ModuleUpload
                      className={AGENT_NEW_BUTTON}
                      label={t("uploadRag")}
                      caption={t("newAgent")}
                      accept=".md,.pdf,.docx,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                      disabled={editingLocked}
                      onFile={(file) => void uploadKnowledge(file)}
                    />
                  }
                >
                  {knowledgeCheck.error ? (
                    <ErrorNotice inline error={knowledgeCheck.error} />
                  ) : null}
                  <KnowledgeCheckOverlay
                    check={knowledgeCheck.check}
                    onClose={knowledgeCheck.closeCheck}
                  />
                  <div className="brainform-source-group">
                    <h3>{t("rag")}</h3>
                    {saving && pendingKnowledgeUpload ? (
                      <p
                        className="muted-copy"
                        role="status"
                        aria-live="polite"
                      >
                        <span className="spinner" aria-hidden="true" />
                        {t(
                          /\.(pdf|docx)$/i.test(
                            pendingKnowledgeUpload.file.name,
                          )
                            ? "knowledgeImportPending"
                            : "knowledgeUploadPending",
                        )}
                      </p>
                    ) : null}
                    {knowledgePreviewRefreshing ? (
                      <p
                        className="muted-copy"
                        role="status"
                        aria-live="polite"
                      >
                        <span className="spinner" aria-hidden="true" />
                        {t("knowledgePreviewRefreshing")}
                      </p>
                    ) : null}
                    {knowledgeUploadError && error === knowledgeUploadError ? (
                      <ErrorNotice
                        error={knowledgeUploadError}
                        onRetry={
                          retryAction === "uploadKnowledge" &&
                          pendingKnowledgeUpload
                            ? () =>
                                void uploadKnowledge(
                                  pendingKnowledgeUpload.file,
                                )
                            : undefined
                        }
                      />
                    ) : null}
                    {knowledgePreviewRefreshFailed ? (
                      <Notice
                        tone="warning"
                        title={t("knowledgePreviewRefreshFailed")}
                        onClose={() => setKnowledgePreviewRefreshFailed(false)}
                        action={
                          <RetryPill
                            disabled={
                              editingLocked || knowledgePreviewRefreshing
                            }
                            onClick={() => void refreshKnowledgePreview()}
                          >
                            {t("retry")}
                          </RetryPill>
                        }
                      />
                    ) : null}
                    {documents.length === 0 &&
                    stagedRag.length === 0 &&
                    !queuedCreateRag ? (
                      <p className="muted-copy">{t("noGroupMarkdown")}</p>
                    ) : (
                      <div className={RAG_STICKERS}>
                        {queuedCreateRag ? (
                          <div className={RAG_STICKER}>
                            <label className={RAG_STICKER_SELECT}>
                              <input
                                className="peer sr-only"
                                type="checkbox"
                                checked
                                disabled={editingLocked}
                                onChange={() => setPendingKnowledgeUpload(null)}
                              />
                              <RagStickerFace
                                filename={queuedCreateRag.file.name}
                              />
                            </label>
                          </div>
                        ) : null}
                        {stagedRag.map((item) => (
                          <div className={RAG_STICKER} key={item.signature}>
                            <label className={RAG_STICKER_SELECT}>
                              <input
                                className="peer sr-only"
                                type="checkbox"
                                checked
                                disabled={editingLocked}
                                onChange={() =>
                                  setStagedRag((current) =>
                                    current.filter(
                                      (staged) =>
                                        staged.signature !== item.signature,
                                    ),
                                  )
                                }
                              />
                              <RagStickerFace filename={item.file.name} />
                            </label>
                          </div>
                        ))}
                        {documents.map((document) => (
                          <div
                            className={cn(
                              RAG_STICKER,
                              document.workspace_state === "hidden" &&
                                "opacity-55",
                            )}
                            key={document.id}
                          >
                            <label className={RAG_STICKER_SELECT}>
                              <input
                                className="peer sr-only"
                                type="checkbox"
                                aria-label={document.source_filename}
                                aria-describedby={`rag-origin-${document.id}`}
                                checked={selectedDocumentIds.includes(
                                  document.id,
                                )}
                                disabled={
                                  editingLocked ||
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
                              <RagStickerFace
                                filename={document.source_filename}
                              >
                                <RagPickerOrigin document={document} />
                              </RagStickerFace>
                            </label>
                            <div className="relative z-[1] flex flex-wrap items-center gap-1.5">
                              {document.index_status === "ready" ? null : (
                                <StatusBadge
                                  status={document.index_status}
                                  tone={
                                    document.index_status === "failed"
                                      ? "bad"
                                      : "warn"
                                  }
                                />
                              )}
                              <KnowledgeRowActions
                                name={document.source_filename}
                                disabled={
                                  knowledgeCheckDisabled ||
                                  document.workspace_state === "hidden"
                                }
                                onView={() =>
                                  void knowledgeCheck.viewMarkdown(
                                    document.source_filename,
                                    loadDocumentMarkdown(api, document),
                                  )
                                }
                                onDownload={() =>
                                  void knowledgeCheck.downloadMarkdown(
                                    document.source_filename,
                                    loadDocumentMarkdown(api, document),
                                  )
                                }
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="brainform-source-group">
                    <h3>{t("brainformKnowledgeHeading")}</h3>
                    {knowledgeSets.length === 0 ? (
                      <p className="muted-copy">
                        {t("brainformKnowledgeEmpty")}
                      </p>
                    ) : (
                      <div className="document-list">
                        {knowledgeSets.map((set) => (
                          <div className="document-row" key={set.id}>
                            <label className="document-select">
                              <input
                                type="checkbox"
                                checked={selectedKnowledgeSetIds.includes(
                                  set.id,
                                )}
                                disabled={
                                  editingLocked ||
                                  knowledgeBindingSaving ||
                                  !set.can_edit
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
                            <div className="row-actions">
                              <KnowledgeRowActions
                                name={set.display_name}
                                disabled={knowledgeCheckDisabled}
                                onView={() =>
                                  void knowledgeCheck.viewMarkdown(
                                    set.display_name,
                                    loadSetMarkdown(api, set.id),
                                  )
                                }
                                onDownload={() =>
                                  void knowledgeCheck.downloadMarkdown(
                                    `${set.display_name}.md`,
                                    loadSetMarkdown(api, set.id),
                                  )
                                }
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </SectionCard>
                <VoiceLibrary
                  groupId={agent.group_id}
                  courseId={agent.group_id ? null : agent.course_id}
                  membershipGroupIds={
                    agent.group_id
                      ? []
                      : (user?.groups ?? []).map((group) => group.group_id)
                  }
                  embedded
                  selectedId={voiceProfileId}
                  disabled={editingLocked}
                  // A teacher's personal Agent picks from that teacher's own
                  // voices, as on main (owner decision 2026-10-12). None is a
                  // choice of its own, so the picker never toggles to empty.
                  onSelect={setVoiceProfileId}
                  onProfilesChange={setVoiceProfiles}
                />
              </div>
            </div>
          </div>
        </div>
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
    <Notice
      tone="warning"
      title={t("revisionConflict")}
      action={
        // A full reload re-reads the latest revision from the server (the
        // in-memory page cache and idempotency keys go with it), so the next
        // save carries the current expected_revision.
        <RetryPill onClick={() => window.location.reload()}>
          {t("refreshPage")}
        </RetryPill>
      }
    >
      {t("conflictDetail")}
    </Notice>
  );
}

type KnowledgeCheckApi = {
  downloadKnowledge(
    documentId: string,
    filename: string,
  ): Promise<{ content: string }>;
  knowledgeMarkdown(setId: string): Promise<{ markdown: string }>;
};

/** The server copy of a RAG file, the same text read-only Brainform shows. */
function loadDocumentMarkdown(
  api: KnowledgeCheckApi,
  document: { id: string; source_filename: string },
) {
  return async () => {
    const downloaded = await api.downloadKnowledge(
      document.id,
      document.source_filename,
    );
    return downloaded.content;
  };
}

/** The saved Markdown of a Knowledge Set, as read-only Brainform shows it. */
function loadSetMarkdown(api: KnowledgeCheckApi, setId: string) {
  return async () => {
    const document = await api.knowledgeMarkdown(setId);
    return document.markdown;
  };
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
        <ErrorNotice inline error={error} />
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
        <LoadingCard size="sm" label={t("loadingSnapshot")} />
      )}
    </SectionCard>
  );
}

/**
 * Who uploaded a RAG file and which Agents use it, so two files with the
 * same name (each Agent's own baseline.md) can be told apart.
 */
function RagPickerOrigin({ document }: { document: KnowledgeDocument }) {
  const t = useT();
  const owner = document.owner_username;
  const used = (document.used_by_agents ?? []).map((agent) => agent.name);
  const parts = [
    owner ? `@${owner}` : null,
    used.length
      ? t("ragPickerUsedBy", { names: used.join(", ") })
      : t("ragNoAgentsYet"),
  ].filter(Boolean);
  return (
    <small id={`rag-origin-${document.id}`} data-testid="rag-picker-origin">
      {parts.join(" · ")}
    </small>
  );
}

/*
 * Option A (2026-11-03), the Agent page's RAG picker: two columns of sticker
 * cards. The checkbox stays (visually hidden) inside the card's label, so the
 * whole card toggles it; a checked card turns lime, lifts and gets a pink
 * check stamp.
 */
const RAG_STICKERS =
  "grid grid-cols-[repeat(2,minmax(0,1fr))] gap-3 max-[560px]:grid-cols-[minmax(0,1fr)]";
const RAG_STICKER =
  "group/sticker relative grid content-start gap-2 rounded-[12px] border-[2.5px] border-[#111] bg-white p-2.5 shadow-[0_4px_0_#111] transition-[transform,box-shadow,background-color] duration-150 has-[input:checked]:-translate-y-[3px] has-[input:checked]:-rotate-1 has-[input:checked]:bg-[#A3E635] has-[input:checked]:shadow-[0_7px_0_#111] has-[input:focus-visible]:outline has-[input:focus-visible]:outline-[3px] has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-main motion-reduce:transition-none motion-reduce:has-[input:checked]:translate-y-0 motion-reduce:has-[input:checked]:rotate-0";
const RAG_STICKER_SELECT =
  "grid min-w-0 cursor-pointer gap-1.5 text-left has-[input:disabled]:cursor-not-allowed";

function RagStickerFace({
  filename,
  children,
}: {
  filename: string;
  children?: ReactNode;
}) {
  const extension = filename.includes(".")
    ? filename.split(".").pop()!.slice(0, 4).toUpperCase()
    : "FILE";
  return (
    <>
      <span
        aria-hidden="true"
        className="absolute -top-2.5 -right-2 hidden size-[30px] rotate-12 place-items-center rounded-full border-[2.5px] border-[#111] bg-[#FF4D8D] text-white shadow-[2px_2px_0_#111] peer-checked:grid"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="m5 12 4 4L19 6" />
        </svg>
      </span>
      <span
        aria-hidden="true"
        className="justify-self-start rounded-[5px] border-2 border-[#111] bg-[#FFE14D] px-1.5 text-[11px] leading-[1.4] font-extrabold"
      >
        {extension}
      </span>
      <strong className="text-sm leading-[1.3] font-extrabold wrap-anywhere text-ink">
        {filename}
      </strong>
      {children ? (
        <span className="text-xs leading-[1.35] font-semibold text-[#333] [&_small]:text-inherit">
          {children}
        </span>
      ) : null}
    </>
  );
}
