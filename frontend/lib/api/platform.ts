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
export type KnowledgeDocumentMutation =
  components["schemas"]["KnowledgeDocumentMutation"];
export type RagPreview = components["schemas"]["RagPreview"];
export type TestChatResponse = components["schemas"]["TestChatResponse"];
export type KnowledgeSnapshot = components["schemas"]["KnowledgeSnapshot"];
export type PublishedAgentSummary =
  components["schemas"]["PublishedAgentSummary"];
export type ErrorPayload = components["schemas"]["Error"];
export type DemoIdentity =
  operations["listDemoIdentities"]["responses"][200]["content"]["application/json"][number];

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
  private csrfToken?: string;

  constructor(options: PlatformApiOptions = {}) {
    this.csrfToken = options.csrfToken;
    this.client = createPlatformClient({
      baseUrl: options.baseUrl ?? "/api/v1",
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

  async archiveAgent(
    agentId: string,
    options: IdempotentMutationOptions = {},
  ): Promise<AgentSummary> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.POST("/agents/{agent_id}/archive", {
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

  async unarchiveAgent(
    agentId: string,
    options: IdempotentMutationOptions = {},
  ): Promise<AgentSummary> {
    return commitMutation(options.idempotency, async (key) => {
      const result = await this.client.POST("/agents/{agent_id}/unarchive", {
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
    options: IdempotentMutationOptions = {},
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
          body: { expected_revision: expectedRevision },
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
          body: form as unknown as never,
        },
      );
      return unwrap(result);
    });
  }

  async document(documentId: string): Promise<KnowledgeDocument> {
    return unwrap(
      await this.client.GET("/knowledge-documents/{document_id}", {
        params: { path: { document_id: documentId } },
      }),
    );
  }

  async downloadKnowledge(documentId: string): Promise<string> {
    return unwrap(
      await this.client.GET("/knowledge-documents/{document_id}/download", {
        params: { path: { document_id: documentId } },
      }),
    );
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
      return unwrap(result);
    });
  }

  async publishedAgents(courseId: string): Promise<PublishedAgentSummary[]> {
    return unwrap(
      await this.client.GET("/courses/{course_id}/published-agents", {
        params: { path: { course_id: courseId } },
      }),
    );
  }

  async snapshot(snapshotId: string): Promise<KnowledgeSnapshot> {
    return unwrap(
      await this.client.GET("/knowledge-snapshots/{snapshot_id}", {
        params: { path: { snapshot_id: snapshotId } },
      }),
    );
  }

  async downloadSnapshot(snapshotId: string): Promise<string> {
    return unwrap(
      await this.client.GET("/knowledge-snapshots/{snapshot_id}/download", {
        params: { path: { snapshot_id: snapshotId } },
      }),
    );
  }

  async downloadSnapshotDocument(
    snapshotId: string,
    snapshotDocumentId: string,
  ): Promise<string> {
    return unwrap(
      await this.client.GET(
        "/knowledge-snapshots/{snapshot_id}/documents/{snapshot_document_id}/download",
        {
          params: {
            path: {
              snapshot_id: snapshotId,
              snapshot_document_id: snapshotDocumentId,
            },
          },
        },
      ),
    );
  }
}
