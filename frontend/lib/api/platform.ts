import type { components, operations } from "./generated/schema";
import {
  createPlatformClient,
  type PlatformClientHandle,
} from "./generated/client";
import { t, tm } from "../i18n";

export type AuthSession = components["schemas"]["AuthSession"];
export type CurrentUser = components["schemas"]["CurrentUser"];
export type Course = components["schemas"]["Course"];
export type CourseDetail = components["schemas"]["CourseDetail"];
export type Group = components["schemas"]["Group"];
export type GroupDetail = components["schemas"]["GroupDetail"];
export type AgentSummary = components["schemas"]["AgentSummary"];
export type AgentDetail = components["schemas"]["AgentDetail"];
export type AgentVersion = components["schemas"]["AgentVersion"];
export type KnowledgeDocument = components["schemas"]["KnowledgeDocument"];
export type KnowledgeDocumentMutation = {
  document: KnowledgeDocument;
  agent_version: AgentVersion | null;
};
export type RagPreview = components["schemas"]["RagPreview"];
export type TestChatResponse = components["schemas"]["TestChatResponse"];
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
  debate_strategy: readonly string[];
  boundaries: readonly string[];
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
  compiler_version: string;
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
  compiler_version: string;
};
export type ProviderDataCallDisclosureResponse =
  components["schemas"]["ProviderDataCallDisclosureResponseV1"];
export type ProviderDataCallConfirmationRequest =
  components["schemas"]["ProviderDataCallConfirmationRequestV1"];
export type ProviderDataCallManifestListResponse =
  components["schemas"]["ProviderDataCallManifestListResponseV1"];
export type ProviderDataCallPublicationManifestListResponse =
  components["schemas"]["ProviderDataCallPublicationManifestListResponseV1"];
export type ProviderDataCallReportManifestListResponse =
  components["schemas"]["ProviderDataCallReportManifestListResponseV1"];

/**
 * Teacher-only, debate-scoped approval status for LLM turns.
 *
 * This endpoint is intentionally kept as a handwritten DTO until the main
 * window freezes its operationId and regenerates the shared OpenAPI client.
 * Keep this type limited to the opaque identifiers and CAS/status values the
 * teacher page needs; provider details and request data never cross this
 * boundary.
 */
export type ProviderDataCallDebateManifestItem = {
  turn_id: string;
  manifest_hash: string;
  confirmation_revision: number;
  confirmed: boolean;
};
export type ProviderDataCallDebateManifestSummary =
  ProviderDataCallDebateManifestItem;
export type ProviderDataCallDebateManifestListResponse = {
  debate_id: string;
  items: ProviderDataCallDebateManifestSummary[];
};
export type ProviderDataCallDebateManifestSummaryV1 =
  ProviderDataCallDebateManifestSummary;
export type ProviderDataCallDebateManifestListResponseV1 =
  ProviderDataCallDebateManifestListResponse;
export type KnowledgeSnapshot = components["schemas"]["KnowledgeSnapshot"];
export type PublishedAgentSummary =
  components["schemas"]["PublishedAgentSummary"];
export type DebateSummary = components["schemas"]["DebateSummary"];
export type DebateDetail = components["schemas"]["DebateDetail"];

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
export type DebateDraftRequest =
  operations["createDebate"]["requestBody"]["content"]["application/json"];
export type ContinueRealReportRequest =
  operations["continueRealReport"]["requestBody"]["content"]["application/json"];
export type ContinueRealReportResponse =
  operations["continueRealReport"]["responses"][202]["content"]["application/json"];
export type DebateDraftUpdateRequest =
  operations["updateDebateDraft"]["requestBody"]["content"]["application/json"];
export type AdvancePlaybackRequest =
  operations["advanceDebatePlayback"]["requestBody"]["content"]["application/json"];
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
  private activeKey: string | undefined = newIdempotencyKey();

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

function readErrorPayload(error: unknown): Partial<ErrorPayload> | undefined {
  if (!error || typeof error !== "object") return undefined;
  const candidate = error as Partial<ErrorPayload>;
  return typeof candidate.message === "string" ? candidate : undefined;
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
    error.code === "stale_revision"
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
    const response = await fetch(
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

  private async postJson<T>(path: string, body: unknown): Promise<T> {
    const separator = this.baseUrl.endsWith("/") ? "" : "/";
    const response = await fetch(
      `${this.baseUrl}${separator}${path.replace(/^\/+/, "")}`,
      {
        method: "POST",
        credentials: "include",
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

  private async getJson<T>(path: string): Promise<T> {
    const separator = this.baseUrl.endsWith("/") ? "" : "/";
    const response = await fetch(
      `${this.baseUrl}${separator}${path.replace(/^\/+/, "")}`,
      {
        method: "GET",
        credentials: "include",
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

  async login(username: string, password: string): Promise<AuthSession> {
    const result = await this.client.POST("/auth/login", {
      body: { username, password },
    });
    const session = await unwrap<AuthSession>(result);
    this.setCsrfToken(session.csrf_token);
    return session;
  }

  async me(): Promise<AuthSession> {
    const result = await this.client.GET("/auth/me");
    const session = await unwrap<AuthSession>(result);
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
    return unwrap(await this.client.GET("/courses"));
  }

  /** Read the safe composition badge used by the authenticated Demo shell. */
  async demoStatus(): Promise<DemoRuntimeStatus> {
    return this.getJson<DemoRuntimeStatus>("demo/status");
  }

  async course(courseId: string): Promise<CourseDetail> {
    return unwrap(
      await this.client.GET("/courses/{course_id}", {
        params: { path: { course_id: courseId } },
      }),
    );
  }

  async groups(courseId: string): Promise<Group[]> {
    return unwrap(
      await this.client.GET("/courses/{course_id}/groups", {
        params: { path: { course_id: courseId } },
      }),
    );
  }

  async group(groupId: string): Promise<GroupDetail> {
    return unwrap(
      await this.client.GET("/groups/{group_id}", {
        params: { path: { group_id: groupId } },
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
        body: { name, description },
      });
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

  async updateAgentMetadata(
    agentId: string,
    body: components["schemas"]["UpdateAgentMetadataRequest"],
  ): Promise<AgentDetail> {
    return unwrap(
      await this.client.PATCH("/agents/{agent_id}", {
        params: {
          path: { agent_id: agentId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        body,
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

  async versions(agentId: string): Promise<AgentVersion[]> {
    return unwrap(
      await this.client.GET("/agents/{agent_id}/versions", {
        params: { path: { agent_id: agentId } },
      }),
    );
  }

  async nextVersion(
    agentId: string,
    options: IdempotentMutationOptions = {},
  ): Promise<AgentVersion> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.POST("/agents/{agent_id}/versions", {
        params: {
          path: { agent_id: agentId },
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

  async compilePersona(
    versionId: string,
    expectedRevision: number,
  ): Promise<PersonaCompileResponse> {
    return this.postJson<PersonaCompileResponse>(
      `agent-versions/${versionId}/persona/compile`,
      { expected_revision: expectedRevision },
    );
  }

  async confirmPersona(
    versionId: string,
    body: ConfirmPersonaRequest,
  ): Promise<AgentVersion> {
    return this.postJson<AgentVersion>(
      `agent-versions/${versionId}/persona/confirm`,
      body,
    );
  }

  async getProviderDataCallDisclosure(
    manifestHash: string,
  ): Promise<ProviderDataCallDisclosureResponse> {
    return unwrap(
      await this.client.GET("/provider/data-call/disclosure", {
        params: { query: { manifest_hash: manifestHash } },
      }),
    );
  }

  async confirmProviderDataCallDisclosure(
    body: ProviderDataCallConfirmationRequest,
  ): Promise<ProviderDataCallDisclosureResponse> {
    return this.postJson<ProviderDataCallDisclosureResponse>(
      "provider/data-call/disclosure/confirm",
      body,
    );
  }

  async listProviderDataCallManifests(
    scopeId: string,
  ): Promise<ProviderDataCallManifestListResponse> {
    return unwrap(
      await this.client.GET("/provider/data-call/pending", {
        params: { query: { scope_id: scopeId } },
      }),
    );
  }

  async listProviderDataCallDebateManifests(
    debateId: string,
  ): Promise<ProviderDataCallDebateManifestListResponse> {
    return this.getJson<ProviderDataCallDebateManifestListResponse>(
      `provider/data-call/pending/debates/${encodeURIComponent(debateId)}`,
    );
  }

  async listProviderDataCallPublicationManifests(
    agentVersionId: string,
  ): Promise<ProviderDataCallPublicationManifestListResponse> {
    return unwrap(
      await this.client.GET(
        "/provider/data-call/pending/agent-versions/{agent_version_id}",
        {
          params: { path: { agent_version_id: agentVersionId } },
        },
      ),
    );
  }

  async listProviderDataCallReportManifests(
    debateId: string,
  ): Promise<ProviderDataCallReportManifestListResponse> {
    return unwrap(
      await this.client.GET("/provider/data-call/pending/reports/{debate_id}", {
        params: { path: { debate_id: debateId } },
      }),
    );
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
    return unwrap(
      await this.client.GET("/agent-versions/{version_id}/rag-preview", {
        params: { path: { version_id: versionId } },
      }),
    );
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

  async testChat(
    versionId: string,
    message: string,
  ): Promise<TestChatResponse> {
    const result = await this.client.POST("/agent-versions/{version_id}/chat", {
      params: {
        path: { version_id: versionId },
        header: { "X-CSRF-Token": this.csrfToken ?? "" },
      },
      body: { message },
    });
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
          },
        },
      );
      return unwrap(result);
    });
  }

  async knowledge(groupId: string): Promise<KnowledgeDocument[]> {
    return unwrap(
      await this.client.GET("/groups/{group_id}/knowledge-documents", {
        params: { path: { group_id: groupId } },
      }),
    );
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

  async createLibraryKnowledge(
    groupId: string,
    file: File,
    options: IdempotentMutationOptions = {},
  ): Promise<KnowledgeDocumentMutation> {
    return commitMutation(options.idempotency, (key) =>
      this.multipart<KnowledgeDocumentMutation>(
        `/groups/${groupId}/knowledge-documents`,
        file,
        {},
        key,
      ),
    );
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

  async replaceKnowledge(
    documentId: string,
    file: File,
    expectedContentHash: string,
    expectedIndexRevision: number,
    options: IdempotentMutationOptions = {},
  ): Promise<KnowledgeDocument> {
    return this.replaceKnowledgeDocument(
      documentId,
      file,
      expectedContentHash,
      expectedIndexRevision,
      options,
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
    options: IdempotentMutationOptions = {},
  ): Promise<VoiceProfile> {
    return commitMutation(options.idempotency, async (key) => {
      const form = new FormData();
      form.append("file", file);
      form.append("consent_accepted", "true");
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

  async voiceProfile(profileId: string): Promise<VoiceProfile> {
    return unwrap(
      await this.client.GET("/voice-profiles/{voice_profile_id}", {
        params: { path: { voice_profile_id: profileId } },
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

  async createVoicePreview(profileId: string): Promise<PlaybackResource> {
    return unwrap(
      await this.client.POST("/voice-profiles/{voice_profile_id}/preview", {
        params: {
          path: { voice_profile_id: profileId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
      }),
    );
  }

  async confirmVoiceProfile(profileId: string): Promise<VoiceProfile> {
    return unwrap(
      await this.client.POST("/voice-profiles/{voice_profile_id}/confirm", {
        params: {
          path: { voice_profile_id: profileId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
      }),
    );
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

  async updateDebateDraft(
    debateId: string,
    body: DebateDraftUpdateRequest,
  ): Promise<DebateDetail> {
    const {
      total_duration_seconds: _totalDuration,
      turn_duration_seconds: _turnDuration,
      ...requestBody
    } = body;
    return unwrap(
      await this.client.PATCH("/debates/{debate_id}", {
        params: {
          path: { debate_id: debateId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        body: requestBody,
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

  /**
   * Recover one stuck classroom playback so its course is not blocked by it.
   *
   * The confirmation is a literal `true` in the body rather than a flag the
   * caller can forget: recovery is deliberate, and the server refuses anything
   * else.
   */
  async releaseDebate(debateId: string): Promise<DebatePlaybackState> {
    return unwrap(
      await this.client.POST("/debates/{debate_id}/release", {
        params: {
          path: { debate_id: debateId },
          header: { "X-CSRF-Token": this.csrfToken ?? "" },
        },
        body: { confirm_release: true },
      }),
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
    options: IdempotentMutationOptions = {},
  ): Promise<CivilizationReport> {
    return commitMutation(options.idempotency, async (key) =>
      unwrap<CivilizationReport>(
        (await this.client.POST("/debates/{debate_id}/report/generate", {
          params: {
            path: { debate_id: debateId },
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

  async continueRealReport(
    debateId: string,
    revisionId: string,
    body: ContinueRealReportRequest,
  ): Promise<ContinueRealReportResponse> {
    return unwrap(
      await this.client.POST(
        "/debates/{debate_id}/report/revisions/{revision_id}/continue",
        {
          params: {
            path: { debate_id: debateId, revision_id: revisionId },
            header: { "X-CSRF-Token": this.csrfToken ?? "" },
          },
          body,
        },
      ),
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
