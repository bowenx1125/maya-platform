import type { AvatarConfig } from "../../components/avatar/types";
import type { components, operations } from "./generated/schema";
import type { LoginQueueNotice } from "../login-queue";
import {
  createPlatformClient,
  type PlatformClientHandle,
} from "./generated/client";
import { t, tm } from "../i18n";
import { notePollResponse } from "../poll-pacing";
import { invalidateRequestCache } from "../request-cache";
import type { ClientMetric } from "../client-metrics";

export type AuthSession = components["schemas"]["AuthSession"];
export type LoginIdentityChoice = components["schemas"]["LoginIdentityChoice"];
export type LoginIdentityChoiceRequest =
  components["schemas"]["LoginIdentityChoiceRequest"];
export type LoginResult = AuthSession | LoginIdentityChoice;
export type CurrentUser = components["schemas"]["CurrentUser"];
export type Course = components["schemas"]["Course"];
export type CourseDetail = components["schemas"]["CourseDetail"];
export type Group = components["schemas"]["Group"];
export type GroupDetail = components["schemas"]["GroupDetail"];
export type GroupOverview = components["schemas"]["GroupOverview"];
export type OverviewResult = components["schemas"]["OverviewResult"];
export type OverviewEvent = components["schemas"]["OverviewEvent"];
export type CourseRoster = components["schemas"]["CourseRoster"];
export type RosterEntry = components["schemas"]["RosterEntry"];
export type UpdateCourseMemberRequest =
  components["schemas"]["UpdateCourseMemberRequest"];
export type PasswordResetResult = components["schemas"]["PasswordResetResult"];
export type RegistrationOptions = components["schemas"]["RegistrationOptions"];
export type RegisterRequest = components["schemas"]["RegisterRequest"];
export type AgentSummary = components["schemas"]["AgentSummary"];
export type AgentDetail = components["schemas"]["AgentDetail"];
export type AgentVersion = components["schemas"]["AgentVersion"];
export type KnowledgeDocument = components["schemas"]["KnowledgeDocument"];
export type AffectedAgent = components["schemas"]["AffectedAgent"];
export type KnowledgeSetSummary = components["schemas"]["KnowledgeSetSummary"];
export type KnowledgeSetDetail = components["schemas"]["KnowledgeSetDetail"];
export type KnowledgeGenerationStatus =
  components["schemas"]["KnowledgeGenerationStatus"];
export type KnowledgeGenerationChatProgress =
  components["schemas"]["KnowledgeGenerationChatProgress"];
export type KnowledgeSetSource = components["schemas"]["KnowledgeSetSourceDTO"];
export type KnowledgeSetRevocation =
  components["schemas"]["KnowledgeSetRevocation"];
export type CreateKnowledgeSetRequest =
  components["schemas"]["CreateKnowledgeSetRequest"];
export type UpdateKnowledgeSetRequest =
  components["schemas"]["UpdateKnowledgeSetRequest"];
export type DeleteKnowledgeSetRequest =
  components["schemas"]["DeleteKnowledgeSetRequest"];
export type ReplaceKnowledgeSetSourcesRequest =
  components["schemas"]["ReplaceKnowledgeSetSourcesRequest"];
export type KnowledgeAsset =
  | components["schemas"]["KnowledgeAssetFullDTO"]
  | components["schemas"]["KnowledgeAssetStudentDTO"];
export type KnowledgeAssetFull = components["schemas"]["KnowledgeAssetFullDTO"];
export type AssetContent =
  | components["schemas"]["ConceptContent"]
  | components["schemas"]["QuestionContent"]
  | components["schemas"]["NoteContent"];
export type AssetCitation = components["schemas"]["AssetCitation"];
export type KnowledgeAssetRequest =
  components["schemas"]["CreateKnowledgeAssetRequest"];
export type UpdateKnowledgeAssetRequest =
  components["schemas"]["UpdateKnowledgeAssetRequest"];
export type KnowledgeAssetVersions =
  | components["schemas"]["KnowledgeAssetVersionHistoryFull"]
  | components["schemas"]["KnowledgeAssetVersionHistoryStudent"];
export type KnowledgeGraph = components["schemas"]["KnowledgeGraph"];
export type AgentKnowledgeSets = components["schemas"]["AgentKnowledgeSets"];
export type ReplaceAgentKnowledgeSetsRequest =
  components["schemas"]["ReplaceAgentKnowledgeSetsRequest"];
export type KnowledgeDocumentMutation = {
  document: KnowledgeDocument;
  agent_version: AgentVersion | null;
};
export type RagPreview = components["schemas"]["RagPreview"];
export type PersonaPreviewSpec = {
  schema_version?: string;
  identity: {
    name: string;
    role: string;
    historical_or_cultural_context: string;
  };
  cultural_lens: readonly string[];
  core_values: readonly string[];
  initial_position: string;
  speaking_style: {
    tone: string;
    argument_pattern: string;
    concession_style: string;
    question_style: string;
  };
  /** Present only on the immutable seven-section V1 projection. */
  debate_strategy?: readonly string[];
  /** Present only on the immutable seven-section V1 projection. */
  boundaries?: readonly string[];
  source_agent_md_hash?: string;
  compiler_version?: string;
};
export type PersonaCompileResponse = {
  version_id: string;
  revision: number;
  compiled: boolean;
  raw_agent_md_hash: string;
  persona_spec: PersonaPreviewSpec | null;
  persona_spec_hash: string | null;
  compiler_version: "persona_template_v1" | "persona_template_v2";
  diagnostics: Array<{
    code?: string;
    message: string;
    line?: number | null;
    field?: string | null;
  }>;
  persona_confirmed: boolean;
};
export type ConfirmPersonaRequest = {
  expected_revision: number;
  raw_agent_md_hash: string;
  persona_spec_hash: string;
  compiler_version: "persona_template_v1" | "persona_template_v2";
};
export type ProviderDataCallReportManifestListResponse =
  components["schemas"]["ProviderDataCallReportManifestListResponseV1"];

export type KnowledgeSnapshot = components["schemas"]["KnowledgeSnapshot"];
export type BrainformKnowledge = {
  agent_id: string;
  canonical_set_id: string;
  source_agent_display_name: string;
  knowledge_display_name: string;
  generation_job_id: string | null;
  can_read: true;
  can_edit: boolean;
  version_seq: number | null;
  content_hash: string | null;
  generation_state:
    | "pending"
    | "running"
    | "blocked"
    | "completed"
    | "failed"
    | "interrupted"
    | null;
  safe_error_code: string | null;
};
export type KnowledgeMarkdown = {
  audience: "full" | "student";
  agent_id: string;
  canonical_set_id: string;
  source_agent_display_name: string;
  knowledge_display_name: string;
  version_seq: number;
  content_hash: string;
  markdown: string;
  projection_available: boolean;
  can_read: true;
  can_edit: boolean;
  created_at: string;
};
export type KnowledgeRegeneration = {
  action_id: string;
  agent_id: string;
  canonical_set_id: string;
  run_id: string;
  job_id: string;
  state: NonNullable<BrainformKnowledge["generation_state"]>;
};
export type AssessmentRuntimeResult = {
  disposition: "recorded" | "transitioned" | "read" | "redirected";
  response_key:
    | "assessment.started"
    | "assessment.answer_recorded"
    | "assessment.answer_recorded_restricted_request"
    | "assessment.paused"
    | "assessment.resumed"
    | "assessment.completed"
    | "assessment.abandoned"
    | "assessment.abandoned_and_restarted"
    | "assessment.progress"
    | "assessment.answers"
    | "assessment.results_pending"
    | "assessment.restart_requires_choice"
    | "assessment.redirect";
  context: {
    attempt: {
      id: string;
      activity_id: string;
      conversation_id: string;
      chat_visibility: "private" | "public";
      status: "in_progress" | "paused" | "completed" | "abandoned";
      revision: number;
    };
    progress: {
      attempt_id: string;
      status: "in_progress" | "paused" | "completed" | "abandoned";
      question_count: number;
      presented_count: number;
      resolved_count: number;
      answered_count: number;
      skipped_count: number;
      current_ordinal: number | null;
      current_question_version_id: string | null;
    };
    current_question: {
      ordinal: number;
      question_version_id: string;
      prompt: string;
    } | null;
    canonical_conversation_id: string;
    redirect_to_original_conversation: boolean;
  };
  answers: Array<{
    question_ordinal: number;
    question_version_id: string | null;
    answer_text: string;
    created_at: string;
  }>;
  guidance?: string | null;
};
export type AssessmentLifecycleAction = "pause" | "resume" | "abandon" | "redo";
export type MemoryEntrySource =
  | { kind: "conversation"; id: string }
  | { kind: "agent"; agent_id: string }
  | { kind: "team"; team_id: string }
  | { kind: "maya_team"; team_id: string };
export type MemoryEntryResult = {
  action_id: string;
  conversation_id: string;
  request_id: string;
  message: string;
  session: ConversationSession;
};
export type PublishedAgentSummary =
  components["schemas"]["PublishedAgentSummary"];
export type DebateSummary = components["schemas"]["DebateSummary"];
export type DebateDetail = Omit<
  components["schemas"]["DebateDetail"],
  "participants"
> & {
  participants: DebateParticipant[];
};
export type DebateCleanupRequest =
  components["schemas"]["DebateCleanupRequest"];
export type DebateCleanupResult = components["schemas"]["DebateCleanupResult"];
export type RegenerateTurnAudioRequest =
  components["schemas"]["RegenerateTurnAudioRequest"];
export type RegenerateTurnAudioResult =
  components["schemas"]["RegenerateTurnAudioResult"];

export type QuizChoice = { id: string; label: string };
export type QuizItemType = "single" | "multiple" | "short_text" | "long_text";
export type QuizGradingStatus = "complete" | "pending" | "mixed";

/** Student-facing quiz item — `answer` / `rubric` must never appear. */
export type QuizItemStudent = {
  id: string;
  type: QuizItemType;
  required: boolean;
  prompt: string;
  choices: QuizChoice[];
  points: number;
};

/** Types mirror backend/app/modules/quiz/schemas.py (student projections). */
export type StudentQuizDto = {
  show_results: boolean;
  id: string;
  course_id: string;
  group_id: string | null;
  title: string;
  status: "published";
  schema_version: number;
  content_revision: number;
  settings: {
    shuffle_questions: boolean;
    shuffle_choices: boolean;
    allow_skip: boolean;
    time_limit_sec: number | null;
  };
  locale: string;
  items: QuizItemStudent[];
  taking_open?: boolean;
  taking_epoch?: number;
  published_at: string | null;
};

export type QuizSummary = {
  show_results: boolean;
  id: string;
  course_id: string;
  group_id: string | null;
  title: string;
  status: "draft" | "published";
  schema_version: number;
  content_revision: number;
  attempt_count: number;
  /** Teacher opened taking; missing/false => students cannot Start. */
  taking_open?: boolean;
  /** Current taking round; increments each closed→open. */
  taking_epoch?: number;
  exemption_count?: number;
  exemption_deadline_latest?: string | null;
  exempt_until?: string | null;
  can_take_now?: boolean;
  scheduled_start_at?: string | null;
  scheduled_end_at?: string | null;
  created_by_user_id: string;
  published_at: string | null;
  created_at: string;
  updated_at: string;
};

export type QuizAttemptDto = {
  show_results: boolean;
  id: string;
  quiz_id: string;
  course_id: string;
  actor_user_id: string;
  content_revision: number;
  status: "submitted";
  grading_status: QuizGradingStatus | null;
  score_objective: number | null;
  score_max_objective: number | null;
  answers: Array<Record<string, unknown>>;
  taking_epoch?: number;
  submitted_at: string;
};

/** Unified Record row for Quiz and legacy chat attempts. */
export type RecordAttemptDto = {
  show_results: boolean;
  source: "quiz" | "chat";
  attempt_id: string;
  user_id: string;
  student_name: string;
  title: string;
  status: string;
  submitted_at: string | null;
  score_objective: number | null;
  score_max_objective: number | null;
  grading_status: QuizGradingStatus | null;
  /** Optional AI score aggregate; tolerate absence until BE ships it. */
  score_ai?: number | null;
  quiz_id: string | null;
  conversation_id: string | null;
  points_awarded: number | null;
  points_total: number | null;
  phase: string | null;
  team_name: string | null;
  taking_epoch?: number | null;
  content_revision?: number | null;
};

export type SubmitQuizAttemptRequest = {
  answers: Array<{
    item_id: string;
    choice_ids?: string[];
    text?: string;
  }>;
};

/**
 * Defense in depth: the student GET must not carry answer/rubric at any
 * item (contract freeze); the mapper strips them even if a server ever
 * leaked the teacher projection.
 */
export function sanitizeStudentQuiz(raw: unknown): StudentQuizDto {
  const quiz = raw as StudentQuizDto;
  const items = (quiz.items ?? []).map((item) => {
    const safe = {
      ...item,
    } as QuizItemStudent & {
      answer?: unknown;
      rubric?: unknown;
      grading?: unknown;
    };
    delete safe.answer;
    delete safe.rubric;
    delete safe.grading;
    return safe as QuizItemStudent;
  });
  return { ...quiz, items };
}

/**
 * Browser-safe Real-Core Demo status. These handwritten DTOs intentionally
 * stay outside the frozen generated client: the endpoint exposes only
 * presentation labels and component modes, never provider configuration.
 */
export type DemoComponentKey = "embedding" | "llm" | "tts" | "voice" | "report";
export type DemoComponent = {
  key: DemoComponentKey;
  /** Real, but under a policy derived locally rather than reviewed. */
  policy_unreviewed?: boolean;
  label: string;
  mode: "real" | "mock";
};
export type DemoComposition = {
  components: DemoComponent[];
};
export type ChatAgent = components["schemas"]["ChatAgent"];
export type ChatSession = Omit<
  components["schemas"]["ChatSession"],
  "turns"
> & {
  turns: ChatTurn[];
};
export type AgentChatSession = ChatSession & {
  entry_kind?: "agent";
  chat_visibility?: "private" | "public";
  origin?: "single_agent";
  read_only?: boolean;
  can_send?: boolean;
};
export type ConversationSession = AgentChatSession | TeamChatSession;
export type ChatAttachment = components["schemas"]["ChatAttachment"];
export type ModelInput = components["schemas"]["ModelInput"];
export type ModelInputCall = components["schemas"]["ModelInputCall"];
export type TeamChatEntry =
  | { kind: "team"; team_id: string; team_version_id?: string | null }
  | { kind: "maya_team"; team_id: string };
export type TeamRouting = {
  mode: "auto" | "selected" | "all";
  participant_ids: string[];
};
export type TeamChatParticipant = {
  id: string;
  name: string;
  avatar_config: components["schemas"]["AvatarConfig"];
  position: number;
  is_leader: boolean;
  available: boolean;
  deleted?: boolean;
};
export type TeamMemberResult = {
  id: string;
  participant_id: string;
  speaker_name: string;
  ordinal: number;
  state: "pending" | "running" | "ready" | "failed" | "acceptance_unknown";
  assistant_text: string | null;
  sources: ChatTurn["sources"];
  safe_error_code: string | null;
};
export type TeamChatTurn = Omit<ChatTurn, "assistant_text" | "state"> & {
  assistant_text: null;
  state:
    | "pending"
    | "ready"
    | "partial"
    | "failed"
    | "acceptance_unknown"
    | "paused";
  routing: TeamRouting;
  member_results: TeamMemberResult[];
  assessment_result?: AssessmentRuntimeResult | null;
};
export type TeamChatSession = {
  entry_kind: "team" | "maya_team";
  chat_visibility: "private" | "public";
  origin: "custom_team" | "published_course_team";
  read_only: boolean;
  can_send: boolean;
  id: string;
  team: {
    id: string;
    version_id: string;
    course_id: string;
    name: string;
    members: TeamChatParticipant[];
    available: boolean;
    deleted?: boolean;
  };
  revision: number;
  turns: TeamChatTurn[];
  created_at: string;
  title?: string | null;
  pinned_at?: string | null;
  assessment_stage?:
    "preparing" | "scoring" | "summarizing" | "completed" | null;
};
export type TeamVisibility =
  components["schemas"]["CreateTeamRequest"]["visibility"];
export type TeamMemberInput = components["schemas"]["TeamMemberInput"];
export type TeamWriteRequest = components["schemas"]["CreateTeamRequest"];
export type TeamUpdateRequest = components["schemas"]["SaveTeamVersionRequest"];
export type TeamSummaryDto = components["schemas"]["TeamSummary"];
export type TeamDetailDto = components["schemas"]["TeamDetail"];
export type MayaTeamDirectoryDto =
  components["schemas"]["MayaTeamDirectoryEntry"];

export type ChatStreamResult = {
  session: ChatSession;
};

export type ChatStreamHooks = {
  /**
   * The reply so far, while the model is still writing it. Unsaved: a Tool
   * round starts the text over, and text_done's saved reply replaces it.
   */
  onDraft?: (text: string) => void;
  /** Fired when text_done is parsed, before the stream closes. */
  onTextDone?: (session: ChatSession) => void;
  /** Fired while the request's persisted turn is still pending. */
  onPending?: (session: ChatSession, pendingTurnId: string) => void;
  /** Fired for a confirmed failed/unknown turn or safe preclaim rejection. */
  onTerminalError?: (
    session: ChatSession | null,
    error: PlatformApiError,
  ) => void;
  /** Fired when the response is ambiguous and no persisted turn is visible yet. */
  onUncertain?: (session: ChatSession | null, error: PlatformApiError) => void;
};
export type ChatTurn = Omit<components["schemas"]["ChatTurn"], "state"> & {
  state:
    | "pending"
    | "ready"
    | "partial"
    | "failed"
    | "acceptance_unknown"
    | "paused";
  assessment_result?: AssessmentRuntimeResult | null;
};

// The root layout starts GET /auth/me while the scripts are still loading.
// Its answer serves the first session read only; anything but a signed-in
// answer falls through to the ordinary request, which reports the real error.
async function takeEarlySession(): Promise<AuthSession | null> {
  if (typeof window === "undefined") return null;
  const holder = window as unknown as {
    __mayaEarlySession?: Promise<Response | null>;
  };
  const pending = holder.__mayaEarlySession;
  if (!pending) return null;
  delete holder.__mayaEarlySession;
  try {
    const response = await pending;
    if (!response || !response.ok) return null;
    return (await response.json()) as AuthSession;
  } catch {
    return null;
  }
}

export class ChatRequestPendingError extends Error {
  constructor() {
    super("The Chat request is still pending.");
    this.name = "ChatRequestPendingError";
  }
}
export type ProviderSettings = components["schemas"]["ProviderSettings"];
export type LiveSummary = components["schemas"]["LiveSummary"];
export type LiveSnapshot = components["schemas"]["LiveSnapshot"];
export type CardRoom = components["schemas"]["CardRoomView"];
export type CardRoomAction = components["schemas"]["CardAction"];
export type DemoBaseline = {
  agent_id: string;
  version_id: string;
  snapshot_id: string;
  group_id: string;
  system_baseline: true;
  immutable: true;
  usable: boolean;
};
export type DemoRuntimeStatus = {
  baseline: DemoBaseline;
  composition: DemoComposition;
  dirty_agents: number;
  dirty_debates: number;
  dirty_interactions: number;
};
export type RoundUnitCaps = [number, number, number, number];
export type DebateCardTeacherReason = Exclude<
  NonNullable<
    components["schemas"]["DebateParticipant"]["card_teacher_reason"]
  >,
  null
>;
export type RoundUnitCapDefaultsInput = {
  courseId: string;
  language: "zh" | "en";
  participants: number;
  rate: number;
};
export type RoundUnitCapDefaults = Omit<
  components["schemas"]["DebateRoundUnitCapDefaults"],
  "round_unit_caps"
> & {
  round_unit_caps: RoundUnitCaps;
};
export type DebateDraftRequest = Omit<
  operations["createDebate"]["requestBody"]["content"]["application/json"],
  "target_minutes" | "round_unit_caps"
> & {
  round_unit_caps: RoundUnitCaps;
};
export type DebateLLMDefaults = components["schemas"]["DebateLLMDefaults"];
export type DebateRulesetDefaults =
  components["schemas"]["DebateRulesetDefaults"];
export type DebateDraftUpdateRequest =
  operations["updateDebateDraft"]["requestBody"]["content"]["application/json"];
export type AdvancePlaybackRequest =
  operations["advanceDebatePlayback"]["requestBody"]["content"]["application/json"];
export type PrefetchNextAudioRequest =
  operations["prefetchNextDebateAudio"]["requestBody"]["content"]["application/json"];
export type PrefetchedNextAudio =
  operations["prefetchNextDebateAudio"]["responses"]["200"]["content"]["application/json"];
export type PlaybackControlRequest =
  operations["pauseDebate"]["requestBody"]["content"]["application/json"];
export type FinishDebateRequest =
  operations["finishDebate"]["requestBody"]["content"]["application/json"];
export type RetryPreparationRequest =
  operations["retryDebatePreparation"]["requestBody"]["content"]["application/json"];
export type DebateParticipant = components["schemas"]["DebateParticipant"];
export type DebateTurn = components["schemas"]["DebateTurn"];
export type DebatePlaybackState = components["schemas"]["PlaybackState"];
export type DebateTranscript = components["schemas"]["Transcript"];
export type TeacherInteraction = components["schemas"]["TeacherInteraction"];
export type CivilizationReport = components["schemas"]["Report"];
export type ReportRevision = components["schemas"]["ReportRevision"];
export type ReportRevisionSummary =
  components["schemas"]["ReportRevisionSummary"];
export type AvatarTemplate = components["schemas"]["AvatarTemplate"];
export type VoiceProfile = components["schemas"]["VoiceProfile"];
export type PlaybackResource =
  components["schemas"]["VoicePreviewPlaybackResource"];
export type DebatePlaybackResource =
  components["schemas"]["DebatePlaybackResource"];
export type ErrorPayload = components["schemas"]["Error"];
export type DemoIdentity =
  operations["listDemoIdentities"]["responses"][200]["content"]["application/json"][number];

export type MarkdownDownload = {
  content: string;
  filename: string;
};

export type PlatformApiOptions = {
  baseUrl?: string;
  csrfToken?: string;
};

/**
 * A send the server refused before saving anything: the admission queue was
 * full, the 180 s wait ran out, or a backstop gate refused it. The text is
 * the student's to send again; nothing retries it automatically.
 */
export const SEND_REFUSED_BUSY_CODES: ReadonlySet<string> = new Set([
  "adaptive_admission_busy",
  "write_pressure",
  "llm_admission_busy",
]);

/** The conversation's previous message is still being answered. */
export const CHAT_BUSY_CODE = "chat_busy";

export function isRefusedSend(error: unknown): boolean {
  return (
    error instanceof PlatformApiError &&
    (error.code === CHAT_BUSY_CODE ||
      (error.code !== undefined && SEND_REFUSED_BUSY_CODES.has(error.code)))
  );
}

/**
 * Busy refusals and the server's poll-after hint slow every poller for a
 * while (lib/poll-pacing.ts). Test doubles may hand back partial responses.
 */
function notePollHints(response: unknown): void {
  const candidate = response as Partial<Response> | null | undefined;
  if (
    !candidate ||
    typeof candidate.status !== "number" ||
    !candidate.headers ||
    typeof candidate.headers.get !== "function"
  )
    return;
  notePollResponse(candidate as Response);
}

export class PlatformApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly details?: Record<string, unknown>;
  readonly requestId?: string;

  constructor(
    status: number,
    message: string,
    payload?: Partial<ErrorPayload>,
  ) {
    super(message);
    this.name = "PlatformApiError";
    this.status = status;
    this.code = payload?.code;
    this.details = payload?.details;
    this.requestId = payload?.request_id;
  }
}

/**
 * Holds one key for the lifetime of a logical mutation. A caller may retry an
 * ambiguous network/server response with the same key; only completion or an
 * explicit abandonment permits the next attempt to obtain a new key.
 */
export class IdempotencyHandle {
  private activeKey: string | undefined;

  constructor(key?: string) {
    this.activeKey = key ?? newIdempotencyKey();
  }

  get key(): string {
    if (!this.activeKey) this.activeKey = newIdempotencyKey();
    return this.activeKey;
  }

  retry(): string {
    return this.key;
  }

  complete(): void {
    this.activeKey = undefined;
  }

  abandon(): void {
    this.activeKey = undefined;
  }
}

export function createIdempotencyHandle(): IdempotencyHandle {
  return new IdempotencyHandle();
}

type ClientResult<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

export function readErrorPayload(
  error: unknown,
): Partial<ErrorPayload> | undefined {
  if (!error || typeof error !== "object") return undefined;
  const candidate = error as Partial<ErrorPayload>;
  return typeof candidate.message === "string" ? candidate : undefined;
}

export class SseBlockError extends Error {
  constructor() {
    super("chat_stream_invalid");
    this.name = "SseBlockError";
  }
}

export type SseEvent = { event: string; id?: string; [key: string]: unknown };

/** Parse one SSE block. Empty blocks are skipped. Invalid JSON throws. */
export function parseSseBlock(block: string): SseEvent | null {
  let event = "message";
  let id: string | undefined;
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("id:")) id = line.slice(3).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }
  if (!data.length) return null;
  let payload: unknown;
  try {
    payload = JSON.parse(data.join("\n"));
  } catch {
    throw new SseBlockError();
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new SseBlockError();
  }
  return {
    event,
    ...(id ? { id } : {}),
    ...(payload as Record<string, unknown>),
  };
}

export async function readSseEvents(
  response: Response,
  onEvent: (event: SseEvent) => void | Promise<void>,
): Promise<void> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const release = () => {
    try {
      reader.releaseLock();
    } catch {
      // cancel() already released the lock.
    }
  };
  const emit = async (final: boolean) => {
    let splitAt = buffer.indexOf("\n\n");
    while (splitAt >= 0) {
      const block = buffer.slice(0, splitAt);
      buffer = buffer.slice(splitAt + 2);
      const parsed = parseSseBlock(block);
      if (parsed) await onEvent(parsed);
      splitAt = buffer.indexOf("\n\n");
    }
    if (final && buffer.trim()) {
      const parsed = parseSseBlock(buffer);
      if (parsed) await onEvent(parsed);
      buffer = "";
    }
  };
  try {
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) {
        buffer += decoder.decode();
        await emit(true);
        break;
      }
      buffer += decoder.decode(chunk.value, { stream: true });
      await emit(false);
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    throw error;
  } finally {
    release();
  }
}

function readLoginQueue(error: unknown): LoginQueueNotice | null {
  if (
    !(error instanceof PlatformApiError) ||
    error.code !== "auth_login_queued"
  ) {
    return null;
  }
  const details = error.details ?? {};
  const count = (value: unknown, fallback: number, min = 0) =>
    typeof value === "number" && Number.isSafeInteger(value) && value >= min
      ? value
      : fallback;
  const position = count(details.position, 0);
  const retryAfterSeconds = count(details.retry_after_seconds, 2, 1);
  const ticket =
    typeof details.ticket === "string" ? details.ticket : undefined;
  const ticketExpiresInSeconds =
    typeof details.ticket_expires_in_seconds === "number" &&
    Number.isSafeInteger(details.ticket_expires_in_seconds) &&
    details.ticket_expires_in_seconds > 0
      ? details.ticket_expires_in_seconds
      : undefined;
  return {
    ticket,
    position,
    retryAfterSeconds,
    queueLength: count(details.queue_length, position + 1, 1),
    estimatedWaitSeconds: count(
      details.estimated_wait_seconds,
      (position + 1) * retryAfterSeconds,
      1,
    ),
    ticketExpiresInSeconds,
  };
}

function isNetworkFailure(error: unknown): boolean {
  return error instanceof TypeError;
}

function waitForQueue(
  milliseconds: number,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, milliseconds);
    const abort = () => {
      clearTimeout(timer);
      reject(new DOMException("The sign-in wait was cancelled.", "AbortError"));
    };
    if (signal?.aborted) {
      abort();
      return;
    }
    signal?.addEventListener("abort", abort, { once: true });
  });
}

function isReadMethod(method: string | undefined): boolean {
  const upper = (method ?? "GET").toUpperCase();
  return upper === "GET" || upper === "HEAD";
}

async function unwrap<T>(result: ClientResult<T>): Promise<T> {
  if (result.data !== undefined) return result.data;
  if (result.response.ok) return undefined as T;
  const payload = readErrorPayload(result.error);
  throw new PlatformApiError(
    result.response.status,
    payload?.message ?? tm("httpError", { status: result.response.status }),
    payload,
  );
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `maya-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function safeDownloadFilename(value: string, fallback: string): string {
  if (
    !value ||
    value === "." ||
    value === ".." ||
    value.includes("/") ||
    value.includes("\\") ||
    [...value].some((character) => {
      const code = character.charCodeAt(0);
      return code < 32 || code === 127;
    })
  ) {
    return fallback;
  }
  return value;
}

export function responseDownloadFilename(
  response: Response,
  fallback: string,
): string {
  const header = response.headers.get("Content-Disposition");
  if (!header) return fallback;
  const encoded = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header)?.[1];
  if (encoded) {
    try {
      return safeDownloadFilename(decodeURIComponent(encoded), fallback);
    } catch {
      return fallback;
    }
  }
  const plain = /filename\s*=\s*(?:"([^"]+)"|([^;]+))/i.exec(header);
  return safeDownloadFilename(
    (plain?.[1] ?? plain?.[2] ?? "").trim(),
    fallback,
  );
}

export function isConflict(error: unknown): error is PlatformApiError {
  return (
    error instanceof PlatformApiError &&
    error.status === 409 &&
    (error.code === "stale_revision" || error.code === "stale_base_version")
  );
}

export function isAmbiguousMutationFailure(error: unknown): boolean {
  if (!(error instanceof PlatformApiError)) return true;
  return (
    error.status === 408 ||
    error.status === 425 ||
    error.status === 429 ||
    error.status >= 500
  );
}

export type IdempotentMutationOptions = {
  idempotency?: IdempotencyHandle;
};

export type PublishAgentVersionOptions = IdempotentMutationOptions & {
  acceptance_run_id?: string;
  call_no?: 1;
  generation?: { source_document_ids: string[] };
};

async function commitMutation<T>(
  handle: IdempotencyHandle | undefined,
  operation: (key: string) => Promise<T>,
): Promise<T> {
  const key = handle?.key ?? newIdempotencyKey();
  try {
    const result = await operation(key);
    handle?.complete();
    return result;
  } catch (error) {
    if (handle && !isAmbiguousMutationFailure(error)) handle.abandon();
    throw error;
  }
}

export function apiErrorMessage(
  error: unknown,
  fallback = t("requestFallback"),
): string {
  if (error instanceof PlatformApiError) return error.message;
  if (error instanceof Error) return error.message;
  return fallback;
}

/**
 * Provider-neutral business API. All pages use this boundary instead of
 * importing openapi-fetch or assembling DTO-like request objects themselves.
 */
export class PlatformApi {
  private readonly client: PlatformClientHandle;
  private readonly baseUrl: string;
  private csrfToken?: string;

  constructor(options: PlatformApiOptions = {}) {
    this.csrfToken = options.csrfToken;
    this.baseUrl = options.baseUrl ?? "/api/v1";
    this.client = createPlatformClient({
      baseUrl: this.baseUrl,
      csrfToken: this.csrfToken,
    });
    // A change empties the shared page-load cache both when it is sent and
    // when it is answered, so no read from before the change is shown after.
    this.client.use({
      onRequest: ({ request }) => {
        if (!isReadMethod(request.method)) invalidateRequestCache(this);
      },
      onResponse: ({ request, response }) => {
        if (!isReadMethod(request.method)) invalidateRequestCache(this);
        notePollHints(response);
      },
    });
  }

  private async trackedFetch(
    input: string,
    init: RequestInit & { method: string },
  ): Promise<Response> {
    if (isReadMethod(init.method)) {
      const response = await fetch(input, init);
      notePollHints(response);
      return response;
    }
    invalidateRequestCache(this);
    try {
      const response = await fetch(input, init);
      notePollHints(response);
      return response;
    } finally {
      invalidateRequestCache(this);
    }
  }

  private async readWithTimeout<T>(
    read: (signal: AbortSignal) => Promise<T>,
  ): Promise<T> {
    // These list reads feed automatic refreshes. Abort the underlying fetch
    // (including its body), so a stalled read cannot retain a cache slot forever.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 60_000);
    try {
      return await read(controller.signal);
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * Sampled browser timings. Sent outside the typed client so the shared
   * page-load cache is not emptied, as it is after every other POST.
   */
  async reportClientMetrics(metrics: ClientMetric[]): Promise<void> {
    const separator = this.baseUrl.endsWith("/") ? "" : "/";
    await fetch(`${this.baseUrl}${separator}client-metrics`, {
      method: "POST",
      credentials: "include",
      keepalive: true,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": this.csrfToken ?? "",
      },
      body: JSON.stringify({ metrics }),
    });
  }

  setCsrfToken(token: string | undefined): void {
    this.csrfToken = token;
    this.client.setCsrfToken(token);
  }

  getCsrfToken(): string | undefined {
    return this.csrfToken;
  }

  private async multipart<T>(
    path: string,
    file: File,
    fields: Record<string, string>,
    idempotencyKey: string,
  ): Promise<T> {
    const form = new FormData();
    form.append("file", file);
    for (const [name, value] of Object.entries(fields)) {
      form.append(name, value);
    }
    const separator = this.baseUrl.endsWith("/") ? "" : "/";
    const response = await this.trackedFetch(
      `${this.baseUrl}${separator}${path.replace(/^\/+/, "")}`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Idempotency-Key": idempotencyKey,
          "X-CSRF-Token": this.csrfToken ?? "",
        },
        body: form,
      },
    );
    const raw = await response.text();
    let payload: unknown;
    try {
      payload = raw ? JSON.parse(raw) : undefined;
    } catch {
      payload = undefined;
    }
    if (!response.ok) {
      const errorPayload = readErrorPayload(payload);
      throw new PlatformApiError(
        response.status,
        errorPayload?.message ?? tm("httpError", { status: response.status }),
        errorPayload,
      );
    }
    return payload as T;
  }

  private async postJson<T>(
    path: string,
    body: unknown,
    keepalive = false,
  ): Promise<T> {
    const separator = this.baseUrl.endsWith("/") ? "" : "/";
    const response = await this.trackedFetch(
      `${this.baseUrl}${separator}${path.replace(/^\/+/, "")}`,
      {
        method: "POST",
        credentials: "include",
        keepalive,
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": this.csrfToken ?? "",
        },
        body: JSON.stringify(body),
      },
    );
    const raw = await response.text();
    let payload: unknown;
    try {
      payload = raw ? JSON.parse(raw) : undefined;
    } catch {
      payload = undefined;
    }
    if (!response.ok) {
      const errorPayload = readErrorPayload(payload);
      throw new PlatformApiError(
        response.status,
        errorPayload?.message ?? tm("httpError", { status: response.status }),
        errorPayload,
      );
    }
    return payload as T;
  }

  private async getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
    const separator = this.baseUrl.endsWith("/") ? "" : "/";
    const response = await this.trackedFetch(
      `${this.baseUrl}${separator}${path.replace(/^\/+/, "")}`,
      {
        method: "GET",
        credentials: "include",
        signal,
        headers: {
          "X-CSRF-Token": this.csrfToken ?? "",
        },
      },
    );
    const raw = await response.text();
    let payload: unknown;
    try {
      payload = raw ? JSON.parse(raw) : undefined;
    } catch {
      payload = undefined;
    }
    if (!response.ok) {
      const errorPayload = readErrorPayload(payload);
      throw new PlatformApiError(
        response.status,
        errorPayload?.message ?? tm("httpError", { status: response.status }),
        errorPayload,
      );
    }
    return payload as T;
  }

  private async mutateJson<T>(
    method: "POST" | "PUT",
    path: string,
    body: unknown,
    idempotencyKey: string,
  ): Promise<T> {
    const separator = this.baseUrl.endsWith("/") ? "" : "/";
    const response = await this.trackedFetch(
      `${this.baseUrl}${separator}${path.replace(/^\/+/, "")}`,
      {
        method,
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
          "X-CSRF-Token": this.csrfToken ?? "",
        },
        body: JSON.stringify(body),
      },
    );
    const raw = await response.text();
    let payload: unknown;
    try {
      payload = raw ? JSON.parse(raw) : undefined;
    } catch {
      payload = undefined;
    }
    if (!response.ok) {
      const errorPayload = readErrorPayload(payload);
      throw new PlatformApiError(
        response.status,
        errorPayload?.message ?? tm("httpError", { status: response.status }),
        errorPayload,
      );
    }
    return payload as T;
  }

  private async deleteJson(path: string): Promise<void> {
    const separator = this.baseUrl.endsWith("/") ? "" : "/";
    const response = await this.trackedFetch(
      `${this.baseUrl}${separator}${path.replace(/^\/+/, "")}`,
      {
        method: "DELETE",
        credentials: "include",
        headers: {
          "X-CSRF-Token": this.csrfToken ?? "",
        },
      },
    );
    if (!response.ok) {
      const raw = await response.text();
      let payload: unknown;
      try {
        payload = raw ? JSON.parse(raw) : undefined;
      } catch {
        payload = undefined;
      }
      const errorPayload = readErrorPayload(payload);
      throw new PlatformApiError(
        response.status,
        errorPayload?.message ?? tm("httpError", { status: response.status }),
        errorPayload,
      );
    }
  }

  async login(
    username: string,
    password: string,
    options?: {
      onQueued?: (notice: LoginQueueNotice) => void;
      signal?: AbortSignal;
      /** A ticket kept from an earlier attempt, e.g. before a page refresh. */
      ticket?: string;
      /** Upper bound for riding out a network drop while holding a ticket. */
      reconnectWindowMs?: number;
      /** Optional research-use consent; never required for access. */
      researchConsent?: boolean;
    },
  ): Promise<LoginResult> {
    let ticket: string | undefined = options?.ticket;
    let last: LoginQueueNotice | null = null;
    let offlineSince: number | null = null;
    const reconnectWindow = options?.reconnectWindowMs ?? 90_000;
    for (;;) {
      if (options?.signal?.aborted) {
        throw new DOMException("The sign-in wait was cancelled.", "AbortError");
      }
      let result;
      try {
        result = await this.client.POST("/auth/login", {
          body: {
            username,
            password,
            research_consent: options?.researchConsent === true,
          },
          headers: ticket ? { "X-Auth-Admission-Ticket": ticket } : {},
        });
        offlineSince = null;
      } catch (cause) {
        // A brief network drop must not cost the place in line: keep the
        // ticket and retry until the connection returns or the window ends.
        if (!ticket || !isNetworkFailure(cause)) throw cause;
        offlineSince ??= Date.now();
        if (Date.now() - offlineSince > reconnectWindow) throw cause;
        const retry = last?.retryAfterSeconds ?? 2;
        options?.onQueued?.({
          ...(last ?? {
            position: 0,
            retryAfterSeconds: retry,
            queueLength: 1,
            estimatedWaitSeconds: retry,
          }),
          ticket,
          reconnecting: true,
        });
        await waitForQueue(Math.max(retry, 2) * 1000, options?.signal);
        continue;
      }
      try {
        const session = await unwrap<LoginResult>(result);
        if ("choice_token" in session) return session;
        this.setCsrfToken(session.csrf_token);
        return session;
      } catch (cause) {
        const queued = readLoginQueue(cause);
        if (!queued) throw cause;
        ticket = queued.ticket ?? ticket;
        last = { ...queued, ticket };
        options?.onQueued?.(last);
        await waitForQueue(queued.retryAfterSeconds * 1000, options?.signal);
      }
    }
  }

  async chooseLoginIdentity(
    body: LoginIdentityChoiceRequest,
  ): Promise<AuthSession> {
    const session = await unwrap<AuthSession>(
      await this.client.POST("/auth/identity-choice", { body }),
    );
    this.setCsrfToken(session.csrf_token);
    return session;
  }

  async me(): Promise<AuthSession> {
    const early = await takeEarlySession();
    if (early) {
      this.setCsrfToken(early.csrf_token);
      return early;
    }
    const result = await this.client.GET("/auth/me");
    const session = await unwrap<AuthSession>(result);
    this.setCsrfToken(session.csrf_token);
    return session;
  }

  async updateCurrentUser(
    changes: components["schemas"]["UpdateCurrentUserRequest"],
  ): Promise<AuthSession> {
    const session = await unwrap<AuthSession>(
      await this.client.PATCH("/auth/me", {
        params: { header: { "X-CSRF-Token": this.csrfToken ?? "" } },
        body: changes,
      }),
    );
    this.setCsrfToken(session.csrf_token);
    return session;
  }

  async changePassword(
    currentPassword: string,
    newPassword: string,
  ): Promise<void> {
    await unwrap<void>(
      await this.client.POST("/auth/password", {
        params: { header: { "X-CSRF-Token": this.csrfToken ?? "" } },
        body: {
          current_password: currentPassword,
          new_password: newPassword,
        },
      }),
    );
  }

  async registrationOptions(): Promise<RegistrationOptions> {
    return unwrap(await this.client.GET("/auth/registration-options"));
  }

  async register(body: RegisterRequest): Promise<AuthSession> {
    const session = await unwrap<AuthSession>(
      await this.client.POST("/auth/register", { body }),
    );
    this.setCsrfToken(session.csrf_token);
    return session;
  }

  async logout(): Promise<void> {
    const result = await this.client.POST("/auth/logout", {
      params: { header: { "X-CSRF-Token": this.csrfToken ?? "" } },
    });
    await unwrap<void>(result);
    this.setCsrfToken(undefined);
  }

  async demoIdentities(): Promise<
    operations["listDemoIdentities"]["responses"][200]["content"]["application/json"]
  > {
    const result = await this.client.GET("/auth/demo-identities");
    return unwrap(result);
  }

  /** Select an identity from the anonymous Demo catalog. */
  async quickLogin(userId: string): Promise<AuthSession> {
    const result = await this.client.POST("/auth/quick-login", {
      body: { user_id: userId },
    });
    const session = await unwrap<AuthSession>(result);
    this.setCsrfToken(session.csrf_token);
    return session;
  }

  async switchDemoIdentity(userId: string): Promise<AuthSession> {
    const result = await this.client.POST("/auth/switch", {
      params: { header: { "X-CSRF-Token": this.csrfToken ?? "" } },
      body: { user_id: userId },
    });
    const session = await unwrap<AuthSession>(result);
    this.setCsrfToken(session.csrf_token);
    return session;
  }

  async courses(): Promise<Course[]> {
    return this.readWithTimeout(async (signal) =>
      unwrap(await this.client.GET("/courses", { signal })),
    );
  }

  async createClass(name: string): Promise<Course> {
    return unwrap(
      await this.client.POST("/courses", {
        params: { header: { "X-CSRF-Token": this.csrfToken ?? "" } },
        body: { name },
      }),
    );
  }

  chatAgents(courseId: string): Promise<ChatAgent[]> {
    return this.readWithTimeout((signal) =>
      this.getJson(`courses/${courseId}/chat-agents`, signal),
    );
  }

  conversations(entryKind?: "agent" | "team"): Promise<ConversationSession[]> {
    const query = entryKind
      ? `?entry_kind=${encodeURIComponent(entryKind)}`
      : "";
    return this.getJson(`conversations${query}`);
  }

  conversationSessions(
    entryKind?: "agent" | "team",
  ): Promise<ConversationSession[]> {
    return this.conversations(entryKind);
  }

  /** The course's Teams, or with `groupId` one group's (an entered teacher's view). */
  teams(courseId: string, groupId?: string): Promise<TeamSummaryDto[]> {
    const scope = groupId ? `?group_id=${encodeURIComponent(groupId)}` : "";
    return this.getJson(
      `courses/${encodeURIComponent(courseId)}/teams${scope}`,
    );
  }

  mayaTeams(courseId: string): Promise<MayaTeamDirectoryDto[]> {
    return this.getJson(`courses/${encodeURIComponent(courseId)}/maya-teams`);
  }

  team(teamId: string): Promise<TeamDetailDto> {
    return this.getJson(`teams/${encodeURIComponent(teamId)}`);
  }

  createTeam(
    courseId: string,
    body: TeamWriteRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<TeamDetailDto> {
    return commitMutation(options.idempotency, (key) =>
      this.mutateJson(
        "POST",
        `courses/${encodeURIComponent(courseId)}/teams`,
        body,
        key,
      ),
    );
  }

  updateTeam(
    teamId: string,
    body: TeamUpdateRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<TeamDetailDto> {
    return commitMutation(options.idempotency, (key) =>
      this.mutateJson("PUT", `teams/${encodeURIComponent(teamId)}`, body, key),
    );
  }

  deleteTeam(
    teamId: string,
    options: IdempotentMutationOptions = {},
  ): Promise<void> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.DELETE("/teams/{team_id}", {
        params: {
          path: { team_id: teamId },
          header: {
            "Idempotency-Key": key,
            "X-CSRF-Token": this.csrfToken ?? "",
          },
        },
      });
      return unwrap<void>(result);
    });
  }

  createConversation(versionId: string): Promise<ChatSession> {
    return this.postJson("conversations", {
      entry: { kind: "agent", version_id: versionId },
    });
  }

  createTeamConversation(entry: TeamChatEntry): Promise<TeamChatSession> {
    return this.postJson("conversations", { entry });
  }

  conversation(id: string): Promise<ChatSession> {
    return this.getJson(`conversations/${id}`);
  }

  conversationSession(id: string): Promise<ConversationSession> {
    return this.getJson(`conversations/${encodeURIComponent(id)}`);
  }

  memoryEntry(body: {
    action_id: string;
    course_id: string;
    source: MemoryEntrySource;
  }): Promise<MemoryEntryResult> {
    return this.postJson("conversations/memory-entry", body);
  }

  controlConversationTurn(
    conversationId: string,
    turnId: string,
    action: "pause" | "resume",
  ): Promise<ConversationSession> {
    return this.postJson(
      `conversations/${encodeURIComponent(conversationId)}/turns/${encodeURIComponent(turnId)}:${action}`,
      undefined,
    );
  }

  async streamTeamConversation(
    id: string,
    body: {
      request_id: string;
      expected_revision: number;
      message: string;
      routing: TeamRouting;
    },
    options: {
      afterEventId?: number;
      onEvent?: (event: SseEvent) => void;
    } = {},
  ): Promise<TeamChatSession> {
    const separator = this.baseUrl.endsWith("/") ? "" : "/";
    const response = await this.trackedFetch(
      `${this.baseUrl}${separator}conversations/${encodeURIComponent(id)}/messages:stream`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          Accept: "text/event-stream",
          "Content-Type": "application/json",
          "X-CSRF-Token": this.csrfToken ?? "",
          ...(options.afterEventId
            ? { "Last-Event-ID": String(options.afterEventId) }
            : {}),
        },
        body: JSON.stringify(body),
      },
    );
    if (!response.ok) {
      const raw = await response.text();
      let payload: unknown;
      try {
        payload = raw ? JSON.parse(raw) : undefined;
      } catch {
        payload = undefined;
      }
      const errorPayload = readErrorPayload(payload);
      throw new PlatformApiError(
        response.status,
        errorPayload?.message ?? tm("httpError", { status: response.status }),
        errorPayload,
      );
    }
    await readSseEvents(response, (event) => options.onEvent?.(event));
    const session = await this.conversationSession(id);
    if (session.entry_kind !== "team" && session.entry_kind !== "maya_team") {
      throw new PlatformApiError(502, "chat_response_invalid", {
        code: "chat_response_invalid",
        message: "chat_response_invalid",
      });
    }
    return session as TeamChatSession;
  }

  private async recoverChatResponse(
    id: string,
    requestId: string,
    hooks: ChatStreamHooks | undefined,
    failure: PlatformApiError,
  ): Promise<ChatSession> {
    // The server refused this send before saving it. Watching another
    // pending turn or marking the outcome uncertain would swallow the
    // student's text; hand the refusal straight back instead.
    if (isRefusedSend(failure)) throw failure;
    let refreshed: ChatSession | null = null;
    try {
      refreshed = await this.conversation(id);
    } catch {
      // The response classification below keeps an unobserved request ID intact.
    }
    const turn = refreshed?.turns.find((item) => item.id === requestId);
    if (turn?.state === "ready" && refreshed) {
      hooks?.onTextDone?.(refreshed);
      return refreshed;
    }
    if (
      turn &&
      (turn.state === "failed" || turn.state === "acceptance_unknown")
    ) {
      const code = turn.safe_error_code ?? failure.code ?? "chat_failed";
      const settledFailure = new PlatformApiError(failure.status, code, {
        code,
        message: code,
        request_id: failure.requestId,
      });
      hooks?.onTerminalError?.(refreshed, settledFailure);
      throw settledFailure;
    }
    const pendingTurn =
      (turn?.state === "pending" ? turn : undefined) ??
      refreshed?.turns.find((item) => item.state === "pending");
    if (pendingTurn && refreshed) {
      hooks?.onPending?.(refreshed, String(pendingTurn.id));
      throw new ChatRequestPendingError();
    }
    if (failure.status < 500) {
      hooks?.onTerminalError?.(refreshed, failure);
      throw failure;
    }
    const uncertain =
      failure.code === "chat_transport_uncertain"
        ? failure
        : new PlatformApiError(503, "chat_transport_uncertain", {
            code: "chat_transport_uncertain",
            message: "chat_transport_uncertain",
            request_id: failure.requestId,
          });
    hooks?.onUncertain?.(refreshed, uncertain);
    throw uncertain;
  }

  deleteConversation(id: string): Promise<void> {
    return this.deleteJson(`conversations/${id}`);
  }

  /** Files attached to one Team Chat. Only that Chat's owner reads them. */
  async conversationAttachments(id: string): Promise<ChatAttachment[]> {
    return unwrap(
      await this.client.GET("/conversations/{conversation_id}/attachments", {
        params: { path: { conversation_id: id } },
      }),
    );
  }

  /** What one Chat turn sent to the model (Details under Check RAG). */
  async chatTurnModelInput(
    conversationId: string,
    turnId: string,
    resultId?: string,
  ): Promise<ModelInput> {
    return unwrap(
      await this.client.GET(
        "/conversations/{conversation_id}/turns/{turn_id}/model-input",
        {
          params: {
            path: { conversation_id: conversationId, turn_id: turnId },
            query: resultId ? { result_id: resultId } : {},
          },
        },
      ),
    );
  }

  async uploadConversationAttachment(
    id: string,
    file: File,
  ): Promise<ChatAttachment> {
    const form = new FormData();
    form.append("file", file);
    return unwrap(
      await this.client.POST("/conversations/{conversation_id}/attachments", {
        params: {
          path: { conversation_id: id },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        // The real FormData keeps the browser's multipart boundary.
        body: form as unknown as never,
      }),
    );
  }

  deleteConversationAttachment(
    id: string,
    attachmentId: string,
  ): Promise<void> {
    return this.deleteJson(
      `conversations/${encodeURIComponent(id)}/attachments/${encodeURIComponent(attachmentId)}`,
    );
  }

  /** Rename or pin a Chat; a field left out keeps its value. */
  async updateConversation(
    id: string,
    changes: components["schemas"]["UpdateChat"],
  ): Promise<ConversationSession> {
    const session = await unwrap(
      await this.client.PATCH("/conversations/{conversation_id}", {
        params: {
          path: { conversation_id: id },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        body: changes,
      }),
    );
    // The same narrowed session shape every other Chat read returns.
    return session as unknown as ConversationSession;
  }

  /**
   * Stream one chat turn; this is the only way a Chat message is sent.
   * An error after text_done leaves the saved assistant text in place.
   */
  async streamConversation(
    id: string,
    body: {
      request_id: string;
      expected_revision: number;
      message: string;
    },
    hooks?: ChatStreamHooks,
  ): Promise<ChatStreamResult> {
    let sawText = false;
    let session: ChatSession | null = null;
    let draftCall: number | null = null;
    let draftText = "";
    const resultFor = (saved: ChatSession): ChatStreamResult => ({
      session: saved,
    });
    const separator = this.baseUrl.endsWith("/") ? "" : "/";
    let response: Response;
    try {
      response = await this.trackedFetch(
        `${this.baseUrl}${separator}conversations/${id}/messages:stream`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            Accept: "text/event-stream",
            "Content-Type": "application/json",
            "X-CSRF-Token": this.csrfToken ?? "",
          },
          body: JSON.stringify(body),
        },
      );
    } catch {
      const failure = new PlatformApiError(503, "chat_transport_uncertain", {
        code: "chat_transport_uncertain",
        message: "chat_transport_uncertain",
      });
      session = await this.recoverChatResponse(
        id,
        body.request_id,
        hooks,
        failure,
      );
      return resultFor(session);
    }
    if (!response.ok) {
      const raw = await response.text();
      let payload: unknown;
      try {
        payload = raw ? JSON.parse(raw) : undefined;
      } catch {
        payload = undefined;
      }
      const errorPayload = readErrorPayload(payload);
      const failure = new PlatformApiError(
        response.status,
        errorPayload?.message ?? tm("httpError", { status: response.status }),
        errorPayload,
      );
      session = await this.recoverChatResponse(
        id,
        body.request_id,
        hooks,
        failure,
      );
      return resultFor(session);
    }
    try {
      await readSseEvents(response, async (event) => {
        if (event.event === "draft") {
          if (sawText || typeof event.text !== "string") return;
          const call = typeof event.call === "number" ? event.call : 0;
          if (call !== draftCall) {
            draftCall = call;
            draftText = "";
          }
          draftText += event.text;
          hooks?.onDraft?.(draftText);
          return;
        }
        if (event.event === "error") {
          const code =
            typeof event.safe_error_code === "string"
              ? event.safe_error_code
              : "chat_failed";
          if (!sawText) {
            const failure = new PlatformApiError(502, code, {
              code,
              message: code,
            });
            session = await this.recoverChatResponse(
              id,
              body.request_id,
              hooks,
              failure,
            );
            sawText = true;
          }
          return;
        }
        if (event.event === "pending") {
          const failure = new PlatformApiError(
            503,
            "chat_transport_uncertain",
            {
              code: "chat_transport_uncertain",
              message: "chat_transport_uncertain",
            },
          );
          session = await this.recoverChatResponse(
            id,
            body.request_id,
            hooks,
            failure,
          );
          sawText = true;
          return;
        }
        if (event.event === "text_done") {
          sawText = true;
          session = await this.conversation(id);
          hooks?.onTextDone?.(session);
        }
      });
    } catch (error) {
      if (error instanceof ChatRequestPendingError) throw error;
      if (sawText && session) return resultFor(session);
      if (sawText) {
        const failure =
          error instanceof PlatformApiError
            ? error
            : new PlatformApiError(503, "chat_transport_uncertain", {
                code: "chat_transport_uncertain",
                message: "chat_transport_uncertain",
              });
        session = await this.recoverChatResponse(
          id,
          body.request_id,
          hooks,
          failure,
        );
        return resultFor(session);
      }
      if (error instanceof PlatformApiError) throw error;
      const failure =
        error instanceof SseBlockError
          ? new PlatformApiError(502, "chat_stream_invalid", {
              code: "chat_stream_invalid",
              message: "chat_stream_invalid",
            })
          : new PlatformApiError(503, "chat_transport_uncertain", {
              code: "chat_transport_uncertain",
              message: "chat_transport_uncertain",
            });
      session = await this.recoverChatResponse(
        id,
        body.request_id,
        hooks,
        failure,
      );
      return resultFor(session);
    }
    if (!sawText || session === null) {
      const failure = new PlatformApiError(502, "chat_failed", {
        code: "chat_failed",
        message: "chat_failed",
      });
      session = await this.recoverChatResponse(
        id,
        body.request_id,
        hooks,
        failure,
      );
    }
    return resultFor(session);
  }

  classroomLive(courseId: string): Promise<LiveSummary | null> {
    return this.getJson(`courses/${courseId}/live`);
  }

  liveSnapshot(debateId: string): Promise<LiveSnapshot> {
    return this.getJson(`live/${debateId}`);
  }

  updateClassroomLive(
    debateId: string,
    body: components["schemas"]["LiveHeartbeat"],
    keepalive = false,
  ): Promise<LiveSummary | null> {
    return this.postJson(`debates/${debateId}/live`, body, keepalive);
  }

  createCardRoom(): Promise<CardRoom> {
    return this.postJson("card-rooms", undefined);
  }

  cardRoom(code: string): Promise<CardRoom> {
    return this.getJson(`card-rooms/${encodeURIComponent(code)}`);
  }

  joinCardRoom(code: string): Promise<CardRoom> {
    return this.postJson(
      `card-rooms/${encodeURIComponent(code)}/seat`,
      undefined,
    );
  }

  leaveCardRoom(code: string): Promise<void> {
    return this.deleteJson(`card-rooms/${encodeURIComponent(code)}/seat`);
  }

  startCardRoom(code: string): Promise<CardRoom> {
    return this.postJson(
      `card-rooms/${encodeURIComponent(code)}/start`,
      undefined,
    );
  }

  actInCardRoom(code: string, body: CardRoomAction): Promise<CardRoom> {
    return this.postJson(
      `card-rooms/${encodeURIComponent(code)}/actions`,
      body,
    );
  }

  rebuyInCardRoom(code: string): Promise<CardRoom> {
    return this.postJson(
      `card-rooms/${encodeURIComponent(code)}/rebuy`,
      undefined,
    );
  }

  async course(courseId: string): Promise<CourseDetail> {
    return unwrap(
      await this.client.GET("/courses/{course_id}", {
        params: { path: { course_id: courseId } },
      }),
    );
  }

  async groups(courseId: string): Promise<Group[]> {
    return this.readWithTimeout(async (signal) =>
      unwrap(
        await this.client.GET("/courses/{course_id}/groups", {
          params: { path: { course_id: courseId } },
          signal,
        }),
      ),
    );
  }

  async group(groupId: string): Promise<GroupDetail> {
    return this.readWithTimeout(async (signal) =>
      unwrap(
        await this.client.GET("/groups/{group_id}", {
          params: { path: { group_id: groupId } },
          signal,
        }),
      ),
    );
  }

  /** Members, test results and recent work, for a course teacher. */
  async groupOverview(groupId: string): Promise<GroupOverview> {
    return unwrap(
      await this.client.GET("/groups/{group_id}/overview", {
        params: { path: { group_id: groupId } },
      }),
    );
  }

  /** Formal attempts in the course. Entering a group is not required. */
  async courseAssessmentAttempts(courseId: string): Promise<OverviewResult[]> {
    return unwrap(
      await this.client.GET(
        "/learning/courses/{course_id}/assessment-attempts",
        { params: { path: { course_id: courseId } } },
      ),
    );
  }

  /** The signed-in student's own formal attempts in the course. */
  async myAssessmentAttempts(courseId: string): Promise<OverviewResult[]> {
    return unwrap(
      await this.client.GET(
        "/learning/courses/{course_id}/my-assessment-attempts",
        { params: { path: { course_id: courseId } } },
      ),
    );
  }

  /** A course teacher deletes an attempt from Record; the server only hides it. */
  deleteCourseAssessmentAttempt(
    courseId: string,
    attemptId: string,
  ): Promise<void> {
    return this.deleteJson(
      `learning/courses/${courseId}/assessment-attempts/${attemptId}`,
    );
  }

  async courseRoster(courseId: string): Promise<CourseRoster> {
    return unwrap(
      await this.client.GET("/courses/{course_id}/roster", {
        params: { path: { course_id: courseId } },
      }),
    );
  }

  /** Permanently erase a student account, its work and grades. */
  async deleteCourseMember(courseId: string, userId: string): Promise<void> {
    await unwrap<void>(
      await this.client.DELETE("/courses/{course_id}/members/{user_id}", {
        params: {
          path: { course_id: courseId, user_id: userId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
      }),
    );
    invalidateRequestCache(this);
  }

  async updateCourseMember(
    courseId: string,
    userId: string,
    body: UpdateCourseMemberRequest,
  ): Promise<RosterEntry> {
    return unwrap(
      await this.client.PATCH("/courses/{course_id}/members/{user_id}", {
        params: {
          path: { course_id: courseId, user_id: userId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        body,
      }),
    );
  }

  async resetStudentPassword(
    courseId: string,
    userId: string,
    newPassword?: string,
  ): Promise<PasswordResetResult> {
    return unwrap(
      await this.client.POST("/auth/password-resets", {
        params: { header: { "X-CSRF-Token": this.csrfToken ?? "" } },
        body: {
          course_id: courseId,
          user_id: userId,
          ...(newPassword ? { new_password: newPassword } : {}),
        },
      }),
    );
  }

  async joinGroupAsTeacher(groupId: string): Promise<GroupDetail> {
    return unwrap(
      await this.client.POST("/groups/{group_id}/membership", {
        params: {
          path: { group_id: groupId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
      }),
    );
  }

  async leaveGroupAsTeacher(groupId: string): Promise<void> {
    await unwrap<void>(
      await this.client.DELETE("/groups/{group_id}/membership", {
        params: {
          path: { group_id: groupId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
      }),
    );
  }

  async agents(
    groupId: string,
    includeArchived = false,
  ): Promise<AgentSummary[]> {
    return unwrap(
      await this.client.GET("/groups/{group_id}/agents", {
        params: {
          path: { group_id: groupId },
          query: { include_archived: includeArchived },
        },
      }),
    );
  }

  async createAgent(
    groupId: string,
    name: string,
    description: string,
    options: IdempotentMutationOptions = {},
    visibility: "private" | "public" = "private",
    avatarConfig?: AvatarConfig,
  ): Promise<AgentDetail> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.POST("/groups/{group_id}/agents", {
        params: {
          path: { group_id: groupId },
          header: {
            "Idempotency-Key": key,
            "X-CSRF-Token": this.csrfToken ?? "",
          },
        },
        body: {
          name,
          description,
          visibility,
          ...(avatarConfig ? { avatar_config: avatarConfig } : {}),
        },
      });
      return unwrap(result);
    });
  }

  async workspaceAgents(courseId: string): Promise<AgentSummary[]> {
    return unwrap(
      await this.client.GET("/courses/{course_id}/workspace-agents", {
        params: { path: { course_id: courseId } },
      }),
    );
  }

  async createWorkspaceAgent(
    courseId: string,
    name: string,
    description: string,
    options: IdempotentMutationOptions = {},
    visibility: "private" | "public" = "private",
    avatarConfig?: AvatarConfig,
  ): Promise<AgentDetail> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.POST(
        "/courses/{course_id}/workspace-agents",
        {
          params: {
            path: { course_id: courseId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body: {
            name,
            description,
            visibility,
            ...(avatarConfig ? { avatar_config: avatarConfig } : {}),
          },
        },
      );
      return unwrap(result);
    });
  }

  async agent(agentId: string): Promise<AgentDetail> {
    return unwrap(
      await this.client.GET("/agents/{agent_id}", {
        params: { path: { agent_id: agentId } },
      }),
    );
  }

  async deleteAgent(
    agentId: string,
    options: IdempotentMutationOptions = {},
  ): Promise<void> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.DELETE("/agents/{agent_id}", {
        params: {
          path: { agent_id: agentId },
          header: {
            "Idempotency-Key": key,
            "X-CSRF-Token": this.csrfToken ?? "",
          },
        },
      });
      return unwrap<void>(result);
    });
  }

  /**
   * Rename an Agent and/or turn a private Agent public (CAS on its metadata
   * revision). The description is never sent, so the server leaves it alone.
   * The answer carries the name the server kept (it may add "-2" to avoid a
   * clash). Public is final: asking for Private again is 409.
   */
  async updateAgentMetadata(
    agentId: string,
    body: {
      name?: string;
      visibility?: "public";
      expected_metadata_revision: number;
    },
  ): Promise<AgentDetail> {
    return unwrap(
      await this.client.PATCH("/agents/{agent_id}", {
        params: {
          path: { agent_id: agentId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        body: body as components["schemas"]["UpdateAgentMetadataRequest"],
      }),
    );
  }

  async versions(agentId: string): Promise<AgentVersion[]> {
    return unwrap(
      await this.client.GET("/agents/{agent_id}/versions", {
        params: { path: { agent_id: agentId } },
      }),
    );
  }

  async nextVersion(
    agentId: string,
    options: IdempotentMutationOptions & {
      /** Published version the editor started from (409 stale_base_version). */
      expectedBaseVersionId?: string;
    } = {},
  ): Promise<AgentVersion> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.POST("/agents/{agent_id}/versions", {
        params: {
          path: { agent_id: agentId },
          ...(options.expectedBaseVersionId
            ? {
                query: {
                  expected_base_version_id: options.expectedBaseVersionId,
                },
              }
            : {}),
          header: {
            "Idempotency-Key": key,
            "X-CSRF-Token": this.csrfToken ?? "",
          },
        },
      });
      return unwrap(result);
    });
  }

  async version(versionId: string): Promise<AgentVersion> {
    return unwrap(
      await this.client.GET("/agent-versions/{version_id}", {
        params: { path: { version_id: versionId } },
      }),
    );
  }

  /** Download immutable published AGENT.md with the server-chosen filename. */
  async downloadAgentMd(
    versionId: string,
    fallbackFilename = "AGENT.md",
  ): Promise<MarkdownDownload> {
    const result = await this.client.GET(
      "/agent-versions/{version_id}/agent-md/download",
      {
        parseAs: "text",
        params: { path: { version_id: versionId } },
      },
    );
    return {
      content: await unwrap(result),
      filename: responseDownloadFilename(result.response, fallbackFilename),
    };
  }

  async saveAgentAvatar(
    versionId: string,
    body: components["schemas"]["SaveAvatarRequest"],
    idempotencyKey: string,
  ): Promise<AgentVersion> {
    return unwrap(
      await this.client.PUT("/agent-versions/{version_id}/avatar", {
        params: {
          path: { version_id: versionId },
          header: {
            "X-CSRF-Token": this.csrfToken ?? "",
            "Idempotency-Key": idempotencyKey,
          },
        },
        body,
      }),
    );
  }

  async updateDraft(
    versionId: string,
    body: components["schemas"]["UpdateAgentDraftRequest"],
  ): Promise<AgentVersion> {
    const result = await this.client.PATCH("/agent-versions/{version_id}", {
      params: {
        path: { version_id: versionId },
        header: { "X-CSRF-Token": this.csrfToken ?? "" },
      },
      body,
    });
    return unwrap(result);
  }

  async setDocuments(
    versionId: string,
    expectedRevision: number,
    documentIds: string[],
  ): Promise<AgentVersion> {
    const result = await this.client.PUT(
      "/agent-versions/{version_id}/knowledge-documents",
      {
        params: {
          path: { version_id: versionId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        body: {
          expected_revision: expectedRevision,
          document_ids: documentIds,
        },
      },
    );
    return unwrap(result);
  }

  async ragPreview(versionId: string): Promise<RagPreview> {
    const preview = await unwrap(
      await this.client.GET("/agent-versions/{version_id}/rag-preview", {
        params: { path: { version_id: versionId } },
      }),
    );
    return { ...preview, limit: null };
  }

  async uploadAgentMd(
    versionId: string,
    file: File,
    expectedRevision: number,
  ): Promise<AgentVersion> {
    const form = new FormData();
    form.append("file", file);
    form.append("expected_revision", String(expectedRevision));
    const result = await this.client.POST(
      "/agent-versions/{version_id}/agent-md/upload",
      {
        params: {
          path: { version_id: versionId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        body: form as unknown as never,
      },
    );
    return unwrap(result);
  }

  async publish(
    versionId: string,
    expectedRevision: number,
    options: PublishAgentVersionOptions = {},
  ): Promise<AgentVersion> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.POST(
        "/agent-versions/{version_id}/publish",
        {
          params: {
            path: { version_id: versionId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body: {
            expected_revision: expectedRevision,
            ...(options.acceptance_run_id
              ? {
                  acceptance_run_id: options.acceptance_run_id,
                  call_no: options.call_no ?? 1,
                }
              : {}),
            ...(options.generation ? { generation: options.generation } : {}),
          },
        },
      );
      return unwrap(result);
    });
  }

  async knowledge(groupId: string): Promise<KnowledgeDocument[]> {
    return this.readWithTimeout(async (signal) =>
      unwrap(
        await this.client.GET("/groups/{group_id}/knowledge-documents", {
          params: { path: { group_id: groupId } },
          signal,
        }),
      ),
    );
  }

  async knowledgeSets(courseId: string): Promise<KnowledgeSetSummary[]> {
    return unwrap(
      await this.client.GET("/courses/{course_id}/knowledge-sets", {
        params: { path: { course_id: courseId } },
      }),
    );
  }

  async knowledgeGenerationJob(
    jobId: string,
  ): Promise<KnowledgeGenerationStatus> {
    return unwrap(
      await this.client.GET("/knowledge-generation-jobs/{job_id}", {
        params: { path: { job_id: jobId } },
      }),
    );
  }

  async createKnowledgeSet(
    courseId: string,
    body: CreateKnowledgeSetRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<KnowledgeSetDetail> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.POST(
        "/courses/{course_id}/knowledge-sets",
        {
          params: {
            path: { course_id: courseId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body,
        },
      );
      return unwrap(result);
    });
  }

  async knowledgeSet(setId: string): Promise<KnowledgeSetDetail> {
    return unwrap(
      await this.client.GET("/knowledge-sets/{set_id}", {
        params: { path: { set_id: setId } },
      }),
    );
  }

  async brainformKnowledge(courseId: string): Promise<BrainformKnowledge[]> {
    return this.readWithTimeout((signal) =>
      this.getJson(
        `courses/${encodeURIComponent(courseId)}/brainform/knowledge`,
        signal,
      ),
    );
  }

  async knowledgeMarkdown(setId: string): Promise<KnowledgeMarkdown> {
    return this.getJson(`knowledge-sets/${encodeURIComponent(setId)}/markdown`);
  }

  async saveKnowledgeMarkdown(
    setId: string,
    body: { expected_version_seq: number; markdown: string },
    options: IdempotentMutationOptions = {},
  ): Promise<KnowledgeMarkdown> {
    return commitMutation(options.idempotency, (key) =>
      this.mutateJson(
        "PUT",
        `knowledge-sets/${encodeURIComponent(setId)}/markdown`,
        body,
        key,
      ),
    );
  }

  async updateKnowledgeSet(
    setId: string,
    body: UpdateKnowledgeSetRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<KnowledgeSetDetail> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.PATCH("/knowledge-sets/{set_id}", {
        params: {
          path: { set_id: setId },
          header: {
            "Idempotency-Key": key,
            "X-CSRF-Token": this.csrfToken ?? "",
          },
        },
        body,
      });
      return unwrap(result);
    });
  }

  async deleteKnowledgeSet(
    setId: string,
    body: DeleteKnowledgeSetRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<KnowledgeSetRevocation> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.DELETE("/knowledge-sets/{set_id}", {
        params: {
          path: { set_id: setId },
          header: {
            "Idempotency-Key": key,
            "X-CSRF-Token": this.csrfToken ?? "",
          },
        },
        body,
      });
      return unwrap(result);
    });
  }

  async agentKnowledgeSets(agentId: string): Promise<AgentKnowledgeSets> {
    return unwrap(
      await this.client.GET("/agents/{agent_id}/knowledge-sets", {
        params: { path: { agent_id: agentId } },
      }),
    );
  }

  async replaceAgentKnowledgeSets(
    agentId: string,
    body: ReplaceAgentKnowledgeSetsRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<AgentKnowledgeSets> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.PUT(
        "/agents/{agent_id}/knowledge-sets",
        {
          params: {
            path: { agent_id: agentId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body,
        },
      );
      return unwrap(result);
    });
  }

  async workspaceDocuments(courseId: string): Promise<KnowledgeDocument[]> {
    return this.readWithTimeout(async (signal) =>
      unwrap(
        await this.client.GET("/courses/{course_id}/workspace-documents", {
          params: { path: { course_id: courseId } },
          signal,
        }),
      ),
    );
  }

  async uploadWorkspaceKnowledge(
    courseId: string,
    versionId: string,
    file: File,
    expectedRevision: number,
    options: IdempotentMutationOptions = {},
  ): Promise<KnowledgeDocumentMutation> {
    return commitMutation(options.idempotency, async (key) => {
      const form = new FormData();
      form.append("file", file);
      form.append("target_agent_version_id", versionId);
      form.append("expected_revision", String(expectedRevision));
      // The server gives the file its Agent's Private or Public.
      const result = await this.client.POST(
        "/courses/{course_id}/workspace-documents",
        {
          params: {
            path: { course_id: courseId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body: form as unknown as never,
        },
      );
      const mutation = await unwrap(result);
      return {
        document: mutation.document,
        agent_version: mutation.agent_version ?? null,
      };
    });
  }

  /**
   * A RAG source added from Brainform's RAG +, in no Agent yet: a teacher's
   * course workspace or a student's group library. Public, so Brainform
   * lists it (a private source stays inside its Agent).
   */
  async uploadRagLibraryDocument(
    target: { courseId: string } | { groupId: string },
    file: File,
    options: IdempotentMutationOptions = {},
  ): Promise<KnowledgeDocument> {
    return commitMutation(options.idempotency, async (key) => {
      const form = new FormData();
      form.append("file", file);
      form.append("visibility", "public");
      const header = {
        "Idempotency-Key": key,
        "X-CSRF-Token": this.csrfToken ?? "",
      };
      const result =
        "courseId" in target
          ? await this.client.POST("/courses/{course_id}/workspace-documents", {
              params: { path: { course_id: target.courseId }, header },
              body: form as unknown as never,
            })
          : await this.client.POST("/groups/{group_id}/knowledge-documents", {
              params: { path: { group_id: target.groupId }, header },
              body: form as unknown as never,
            });
      return (await unwrap(result)).document;
    });
  }

  async uploadKnowledge(
    groupId: string,
    versionId: string,
    file: File,
    expectedRevision: number,
    options: IdempotentMutationOptions = {},
  ): Promise<KnowledgeDocumentMutation> {
    return commitMutation(options.idempotency, async (key) => {
      const form = new FormData();
      form.append("file", file);
      form.append("target_agent_version_id", versionId);
      form.append("expected_revision", String(expectedRevision));
      const result = await this.client.POST(
        "/groups/{group_id}/knowledge-documents",
        {
          params: {
            path: { group_id: groupId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          // openapi-fetch intentionally does not expose FormData as the
          // generated object-body type.  Passing the real FormData preserves
          // the browser multipart boundary and keeps this one cast inside the
          // platform adapter rather than leaking it to product components.
          body: form as unknown as never,
        },
      );
      const mutation = await unwrap(result);
      return {
        document: mutation.document,
        agent_version: mutation.agent_version ?? null,
      };
    });
  }

  async replaceKnowledgeDocument(
    documentId: string,
    file: File,
    expectedContentHash: string,
    expectedIndexRevision: number,
    options: IdempotentMutationOptions = {},
  ): Promise<KnowledgeDocument> {
    return commitMutation(options.idempotency, (key) => {
      return this.multipart<KnowledgeDocument>(
        `/knowledge-documents/${documentId}/replace`,
        file,
        {
          expected_content_hash: expectedContentHash,
          expected_index_revision: String(expectedIndexRevision),
        },
        key,
      );
    });
  }

  async renameKnowledgeDocument(
    documentId: string,
    body: { expected_filename: string; filename: string },
    options: IdempotentMutationOptions = {},
  ): Promise<KnowledgeDocument> {
    return commitMutation(options.idempotency, (key) =>
      this.mutateJson(
        "POST",
        `/knowledge-documents/${encodeURIComponent(documentId)}:rename`,
        body,
        key,
      ),
    );
  }

  async document(documentId: string): Promise<KnowledgeDocument> {
    return unwrap(
      await this.client.GET("/knowledge-documents/{document_id}", {
        params: { path: { document_id: documentId } },
      }),
    );
  }

  async downloadKnowledge(
    documentId: string,
    fallbackFilename = "download.md",
  ): Promise<MarkdownDownload> {
    const result = await this.client.GET(
      "/knowledge-documents/{document_id}/download",
      {
        parseAs: "text",
        params: { path: { document_id: documentId } },
      },
    );
    return {
      content: await unwrap(result),
      filename: responseDownloadFilename(result.response, fallbackFilename),
    };
  }

  async reindex(
    documentId: string,
    options: IdempotentMutationOptions = {},
  ): Promise<components["schemas"]["JobStatus"]> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.POST(
        "/knowledge-documents/{document_id}/reindex",
        {
          params: {
            path: { document_id: documentId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
        },
      );
      return unwrap(result);
    });
  }

  async hideKnowledge(
    documentId: string,
    options: IdempotentMutationOptions = {},
  ): Promise<KnowledgeDocument> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.POST(
        "/knowledge-documents/{document_id}/hide",
        {
          params: {
            path: { document_id: documentId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
        },
      );
      return (await unwrap(result)) as unknown as KnowledgeDocument;
    });
  }

  async knowledgeAffectedAgents(documentId: string): Promise<AffectedAgent[]> {
    return unwrap(
      await this.client.GET(
        "/knowledge-documents/{document_id}/affected-agents",
        { params: { path: { document_id: documentId } } },
      ),
    );
  }

  async voiceAffectedAgents(profileId: string): Promise<AffectedAgent[]> {
    return unwrap(
      await this.client.GET(
        "/voice-profiles/{voice_profile_id}/affected-agents",
        { params: { path: { voice_profile_id: profileId } } },
      ),
    );
  }

  async checkAgentDebateCard(
    versionId: string,
    agentMd: string,
  ): Promise<components["schemas"]["AgentCardResponse"]> {
    return this.postJson(`agent-versions/${versionId}/debate-card`, {
      agent_md: agentMd,
    });
  }

  async previewAgent(
    body: components["schemas"]["AgentPreviewRequest"],
  ): Promise<components["schemas"]["AgentPreviewResponse"]> {
    return this.postJson("agents/preview", body);
  }

  async avatarTemplates(): Promise<AvatarTemplate[]> {
    return unwrap(await this.client.GET("/avatar-templates"));
  }

  async voiceProfiles(groupId: string): Promise<VoiceProfile[]> {
    return unwrap(
      await this.client.GET("/groups/{group_id}/voice-profiles", {
        params: { path: { group_id: groupId } },
      }),
    );
  }

  async enrollVoice(
    groupId: string,
    file: File,
    consentCopyVersion?: string,
    options: IdempotentMutationOptions & { language?: "en" | "zh-CN" } = {},
  ): Promise<VoiceProfile> {
    return commitMutation(options.idempotency, async (key) => {
      const form = new FormData();
      form.append("file", file);
      form.append("consent_accepted", "true");
      if (options.language) form.append("language", options.language);
      if (consentCopyVersion)
        form.append("consent_copy_version", consentCopyVersion);
      const result = await this.client.POST(
        "/groups/{group_id}/voice-profiles",
        {
          params: {
            path: { group_id: groupId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body: form as unknown as never,
        },
      );
      return unwrap(result);
    });
  }

  async personalVoiceProfiles(courseId: string): Promise<VoiceProfile[]> {
    return unwrap(
      await this.client.GET("/courses/{course_id}/voice-profiles", {
        params: { path: { course_id: courseId } },
      }),
    );
  }

  async enrollPersonalVoice(
    courseId: string,
    file: File,
    consentCopyVersion?: string,
    options: IdempotentMutationOptions & { language?: "en" | "zh-CN" } = {},
  ): Promise<VoiceProfile> {
    return commitMutation(options.idempotency, async (key) => {
      const form = new FormData();
      form.append("file", file);
      form.append("consent_accepted", "true");
      if (options.language) form.append("language", options.language);
      if (consentCopyVersion)
        form.append("consent_copy_version", consentCopyVersion);
      const result = await this.client.POST(
        "/courses/{course_id}/voice-profiles",
        {
          params: {
            path: { course_id: courseId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body: form as unknown as never,
        },
      );
      return unwrap(result);
    });
  }

  async renameVoiceProfile(
    profileId: string,
    sourceFilename: string,
  ): Promise<VoiceProfile> {
    return unwrap(
      await this.client.PATCH("/voice-profiles/{voice_profile_id}", {
        params: {
          path: { voice_profile_id: profileId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        body: { source_filename: sourceFilename },
      }),
    );
  }

  async deleteVoiceProfile(
    profileId: string,
    options: IdempotentMutationOptions = {},
  ): Promise<VoiceProfile> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.DELETE(
        "/voice-profiles/{voice_profile_id}",
        {
          params: {
            path: { voice_profile_id: profileId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
        },
      );
      return unwrap(result);
    });
  }

  async createVoicePreview(
    profileId: string,
    instruction?: string | null,
  ): Promise<PlaybackResource> {
    return unwrap(
      await this.client.POST("/voice-profiles/{voice_profile_id}/preview", {
        params: {
          path: { voice_profile_id: profileId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        body:
          instruction && instruction.trim()
            ? { instruction: instruction.trim() }
            : {},
      }),
    );
  }

  async debateRulesetDefaults(
    courseId: string,
  ): Promise<DebateRulesetDefaults> {
    return unwrap(
      await this.client.GET("/courses/{course_id}/debate-ruleset", {
        params: { path: { course_id: courseId } },
      }),
    );
  }

  async debateLLMDefaults(courseId: string): Promise<DebateLLMDefaults> {
    return unwrap(
      await this.client.GET("/courses/{course_id}/debate-llm-defaults", {
        params: { path: { course_id: courseId } },
      }),
    );
  }

  async loadRoundUnitCapDefaults(
    input: RoundUnitCapDefaultsInput,
  ): Promise<RoundUnitCapDefaults> {
    const raw = await unwrap(
      await this.client.GET(
        "/courses/{course_id}/debate-round-unit-cap-defaults",
        {
          params: {
            path: { course_id: input.courseId },
            query: {
              language: input.language,
              participants: input.participants,
              rate: input.rate,
            },
          },
        },
      ),
    );
    const minimum = input.language === "zh" ? 40 : 25;
    const caps = raw.round_unit_caps;
    if (
      !Array.isArray(caps) ||
      caps.length !== 4 ||
      !caps.every(
        (value) =>
          typeof value === "number" &&
          Number.isInteger(value) &&
          value >= minimum &&
          value <= 2000,
      )
    ) {
      throw new PlatformApiError(502, "debate_round_unit_caps_invalid", {
        code: "debate_round_unit_caps_invalid",
      });
    }
    return { ...raw, round_unit_caps: caps as RoundUnitCaps };
  }

  async publishedAgents(courseId: string): Promise<PublishedAgentSummary[]> {
    return unwrap(
      await this.client.GET("/courses/{course_id}/published-agents", {
        params: { path: { course_id: courseId } },
      }),
    );
  }

  async debates(courseId: string): Promise<DebateSummary[]> {
    return unwrap(
      await this.client.GET("/courses/{course_id}/debates", {
        params: { path: { course_id: courseId } },
      }),
    );
  }

  async createDebate(
    courseId: string,
    body: DebateDraftRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<DebateDetail> {
    return commitMutation(options.idempotency, async (key) => {
      const {
        total_duration_seconds: _totalDuration,
        turn_duration_seconds: _turnDuration,
        ...requestBody
      } = body;
      const result = await this.client.POST("/courses/{course_id}/debates", {
        params: {
          path: { course_id: courseId },
          header: {
            "Idempotency-Key": key,
            "X-CSRF-Token": this.csrfToken ?? "",
          },
        },
        body: requestBody,
      });
      return unwrap(result);
    });
  }

  async debate(debateId: string): Promise<DebateDetail> {
    return unwrap(
      await this.client.GET("/debates/{debate_id}", {
        params: { path: { debate_id: debateId } },
      }),
    );
  }

  async startDebate(
    debateId: string,
    body: operations["startDebate"]["requestBody"]["content"]["application/json"],
    options: IdempotentMutationOptions = {},
  ): Promise<DebateDetail> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.POST("/debates/{debate_id}/start", {
        params: {
          path: { debate_id: debateId },
          header: {
            "Idempotency-Key": key,
            "X-CSRF-Token": this.csrfToken ?? "",
          },
        },
        body,
      });
      return unwrap(result);
    });
  }

  async retryDebatePreparation(
    debateId: string,
    body: RetryPreparationRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<DebatePlaybackState> {
    return commitMutation(options.idempotency, async (key) =>
      unwrap(
        await this.client.POST("/debates/{debate_id}/preparation/retry", {
          params: {
            path: { debate_id: debateId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body,
        }),
      ),
    );
  }

  async advanceDebatePlayback(
    debateId: string,
    body: AdvancePlaybackRequest,
  ): Promise<DebatePlaybackState> {
    return unwrap(
      await this.client.POST("/debates/{debate_id}/next", {
        params: {
          path: { debate_id: debateId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        body,
      }),
    );
  }

  async prefetchNextDebateAudio(
    debateId: string,
    body: PrefetchNextAudioRequest,
  ): Promise<PrefetchedNextAudio> {
    return unwrap(
      await this.client.POST("/debates/{debate_id}/next-audio", {
        params: {
          path: { debate_id: debateId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        body,
      }),
    );
  }

  async freezeFinalInput(debateId: string, expectedControlVersion: number) {
    return unwrap(
      await this.client.POST("/debates/{debate_id}/final-input", {
        params: {
          path: { debate_id: debateId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        body: { expected_control_version: expectedControlVersion },
      }),
    );
  }

  async pauseDebate(
    debateId: string,
    body: PlaybackControlRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<DebatePlaybackState> {
    return commitMutation(options.idempotency, async (key) =>
      unwrap(
        await this.client.POST("/debates/{debate_id}/pause", {
          params: {
            path: { debate_id: debateId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body,
        }),
      ),
    );
  }

  async resumeDebate(
    debateId: string,
    body: PlaybackControlRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<DebatePlaybackState> {
    return commitMutation(options.idempotency, async (key) =>
      unwrap(
        await this.client.POST("/debates/{debate_id}/resume", {
          params: {
            path: { debate_id: debateId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body,
        }),
      ),
    );
  }

  async finishDebate(
    debateId: string,
    body: FinishDebateRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<DebateDetail> {
    return commitMutation(options.idempotency, async (key) =>
      unwrap(
        await this.client.POST("/debates/{debate_id}/finish", {
          params: {
            path: { debate_id: debateId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body,
        }),
      ),
    );
  }

  async regenerateDebateTurnAudio(
    debateId: string,
    turnId: string,
    body: RegenerateTurnAudioRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<RegenerateTurnAudioResult> {
    const handle = options.idempotency;
    const key = handle?.key ?? newIdempotencyKey();
    try {
      const result = await unwrap(
        await this.client.POST(
          "/debates/{debate_id}/audio/{turn_id}/regenerate",
          {
            params: {
              path: { debate_id: debateId, turn_id: turnId },
              header: {
                "Idempotency-Key": key,
                "X-CSRF-Token": this.csrfToken ?? "",
              },
            },
            body,
          },
        ),
      );
      if (result.status !== "queued") handle?.complete();
      return result;
    } catch (error) {
      if (handle && !isAmbiguousMutationFailure(error)) handle.abandon();
      throw error;
    }
  }

  async deleteDebateVoice(
    debateId: string,
    body: DebateCleanupRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<DebateCleanupResult> {
    return commitMutation(options.idempotency, async (key) =>
      unwrap(
        await this.client.DELETE("/debates/{debate_id}/audio", {
          params: {
            path: { debate_id: debateId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body,
        }),
      ),
    );
  }

  async deleteDebateAll(
    debateId: string,
    body: DebateCleanupRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<DebateCleanupResult> {
    return commitMutation(options.idempotency, async (key) =>
      unwrap(
        await this.client.DELETE("/debates/{debate_id}", {
          params: {
            path: { debate_id: debateId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body,
        }),
      ),
    );
  }

  async remakeDebate(
    debateId: string,
    body: DebateCleanupRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<DebateCleanupResult> {
    return commitMutation(options.idempotency, async (key) =>
      unwrap(
        await this.client.POST("/debates/{debate_id}/remake", {
          params: {
            path: { debate_id: debateId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body,
        }),
      ),
    );
  }

  async rebirthDebate(
    debateId: string,
    body: DebateCleanupRequest,
    options: IdempotentMutationOptions = {},
  ): Promise<DebateCleanupResult> {
    return commitMutation(options.idempotency, async (key) =>
      unwrap(
        await this.client.POST("/debates/{debate_id}/rebirth", {
          params: {
            path: { debate_id: debateId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
          body,
        }),
      ),
    );
  }

  async replayDebate(
    debateId: string,
    expectedControlVersion: number,
  ): Promise<DebatePlaybackState> {
    return unwrap(
      await this.client.POST("/debates/{debate_id}/replay", {
        params: {
          path: { debate_id: debateId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        body: { expected_control_version: expectedControlVersion },
      }),
    );
  }

  async debateTranscript(debateId: string): Promise<DebateTranscript> {
    return unwrap(
      await this.client.GET("/debates/{debate_id}/transcript", {
        params: { path: { debate_id: debateId } },
      }),
    );
  }

  async teacherInteraction(debateId: string): Promise<TeacherInteraction> {
    return unwrap<TeacherInteraction>(
      (await this.client.GET("/debates/{debate_id}/interaction", {
        params: { path: { debate_id: debateId } },
      })) as unknown as ClientResult<TeacherInteraction>,
    );
  }

  async openInteraction(
    debateId: string,
    options: IdempotentMutationOptions = {},
  ): Promise<TeacherInteraction> {
    return commitMutation(options.idempotency, async (key) =>
      unwrap<TeacherInteraction>(
        (await this.client.POST("/debates/{debate_id}/interaction/open", {
          params: {
            path: { debate_id: debateId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
        })) as unknown as ClientResult<TeacherInteraction>,
      ),
    );
  }

  async closeInteraction(
    debateId: string,
    options: IdempotentMutationOptions = {},
  ): Promise<TeacherInteraction> {
    return commitMutation(options.idempotency, async (key) =>
      unwrap<TeacherInteraction>(
        (await this.client.POST("/debates/{debate_id}/interaction/close", {
          params: {
            path: { debate_id: debateId },
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
        })) as unknown as ClientResult<TeacherInteraction>,
      ),
    );
  }

  async getCurrentReport(debateId: string): Promise<CivilizationReport> {
    return unwrap<CivilizationReport>(
      (await this.client.GET("/debates/{debate_id}/report", {
        params: { path: { debate_id: debateId } },
      })) as unknown as ClientResult<CivilizationReport>,
    );
  }

  async regenerateReport(
    debateId: string,
    options: IdempotentMutationOptions & { initial?: boolean } = {},
  ): Promise<CivilizationReport> {
    return commitMutation(options.idempotency, async (key) =>
      unwrap<CivilizationReport>(
        (await this.client.POST("/debates/{debate_id}/report/generate", {
          params: {
            path: { debate_id: debateId },
            query: options.initial ? { initial: true } : undefined,
            header: {
              "Idempotency-Key": key,
              "X-CSRF-Token": this.csrfToken ?? "",
            },
          },
        })) as unknown as ClientResult<CivilizationReport>,
      ),
    );
  }

  async listReportRevisions(
    debateId: string,
  ): Promise<ReportRevisionSummary[]> {
    return unwrap(
      await this.client.GET("/debates/{debate_id}/report/revisions", {
        params: { path: { debate_id: debateId } },
      }),
    );
  }

  async getReportRevision(
    debateId: string,
    revisionId: string,
  ): Promise<ReportRevision> {
    return unwrap<ReportRevision>(
      (await this.client.GET(
        "/debates/{debate_id}/report/revisions/{revision_id}",
        {
          params: {
            path: { debate_id: debateId, revision_id: revisionId },
          },
        },
      )) as unknown as ClientResult<ReportRevision>,
    );
  }

  async downloadCurrentReport(
    debateId: string,
    language: "en" = "en",
  ): Promise<MarkdownDownload> {
    const result = await this.client.GET(
      "/debates/{debate_id}/report/download",
      {
        parseAs: "text",
        params: { path: { debate_id: debateId }, query: { language } },
      },
    );
    return {
      content: await unwrap(result),
      filename: responseDownloadFilename(result.response, "maya-report.md"),
    };
  }

  // Classroom Quiz student ops (hand-written; quiz paths are not in the
  // frozen OpenAPI schema).

  /** Published quizzes only for a student; the server enforces the filter. */
  listCourseQuizzes(courseId: string): Promise<QuizSummary[]> {
    return this.getJson(`courses/${encodeURIComponent(courseId)}/quizzes`);
  }

  /** The student projection of one quiz; the mapper also strips answer keys. */
  async getStudentQuiz(
    courseId: string,
    quizId: string,
  ): Promise<StudentQuizDto> {
    return sanitizeStudentQuiz(
      await this.getJson(
        `courses/${encodeURIComponent(courseId)}/quizzes/${encodeURIComponent(quizId)}`,
      ),
    );
  }

  /** One-shot submission; zero LLM, and the client never retries it. */
  submitCourseQuizAttempt(
    courseId: string,
    quizId: string,
    body: SubmitQuizAttemptRequest,
  ): Promise<QuizAttemptDto> {
    return this.postJson(
      `courses/${encodeURIComponent(courseId)}/quizzes/${encodeURIComponent(quizId)}/attempts`,
      body,
    );
  }

  /** The signed-in student's own Record rows (quiz + legacy chat). */
  listMyRecordAttempts(courseId: string): Promise<RecordAttemptDto[]> {
    return this.getJson(
      `courses/${encodeURIComponent(courseId)}/my-record-attempts`,
    );
  }

  async snapshot(snapshotId: string): Promise<KnowledgeSnapshot> {
    return unwrap(
      await this.client.GET("/knowledge-snapshots/{snapshot_id}", {
        params: { path: { snapshot_id: snapshotId } },
      }),
    );
  }

  async downloadSnapshot(
    snapshotId: string,
    fallbackFilename = "RAG.md",
  ): Promise<MarkdownDownload> {
    const result = await this.client.GET(
      "/knowledge-snapshots/{snapshot_id}/download",
      {
        parseAs: "text",
        params: { path: { snapshot_id: snapshotId } },
      },
    );
    return {
      content: await unwrap(result),
      filename: responseDownloadFilename(result.response, fallbackFilename),
    };
  }

  async downloadSnapshotDocument(
    snapshotId: string,
    snapshotDocumentId: string,
    fallbackFilename = "source.md",
  ): Promise<MarkdownDownload> {
    const result = await this.client.GET(
      "/knowledge-snapshots/{snapshot_id}/documents/{snapshot_document_id}/download",
      {
        parseAs: "text",
        params: {
          path: {
            snapshot_id: snapshotId,
            snapshot_document_id: snapshotDocumentId,
          },
        },
      },
    );
    return {
      content: await unwrap(result),
      filename: responseDownloadFilename(result.response, fallbackFilename),
    };
  }
}
