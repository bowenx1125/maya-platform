"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  isAmbiguousMutationFailure,
  type AgentDetail,
  type AgentSummary,
  type Course,
  type GroupDetail,
  type KnowledgeDocument,
  type PlatformApi,
} from "../lib/api";
import { useIdempotencyStore } from "../lib/idempotency";
import { roleLabel } from "../lib/i18n";
import { useLocale, useT } from "./locale";
import { useSession } from "./session-provider";
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
  StatusBadge,
} from "./ui";

type GroupOverview = {
  group: GroupDetail;
  agents: AgentSummary[];
  documents: KnowledgeDocument[];
};

type AgentWithMetadata = AgentSummary & {
  metadata_revision?: number;
};

type AgentMetadataApi = PlatformApi & {
  updateAgentMetadata: (
    agentId: string,
    body: {
      expected_metadata_revision: number;
      description: string | null;
    },
  ) => Promise<AgentDetail>;
};

function isMetadataRevisionConflict(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const candidate = error as { status?: unknown; code?: unknown };
  return (
    candidate.status === 409 && candidate.code === "stale_metadata_revision"
  );
}

async function loadGroups(
  api: PlatformApi,
  groupIds: string[],
): Promise<GroupOverview[]> {
  return Promise.all(
    groupIds.map(async (groupId) => {
      const [group, agents, documents] = await Promise.all([
        api.group(groupId),
        // Keep legacy archived rows discoverable so an old, never-published
        // Agent still has an explicit hard-delete path after archive UI is
        // removed.  Historical rows remain visibly inactive and are rejected
        // by the server's history check.
        api.agents(groupId, true),
        api.knowledge(groupId),
      ]);
      return { group, agents, documents };
    }),
  );
}

export function StudentDashboard() {
  const t = useT();
  const { api, user } = useSession();
  const [course, setCourse] = useState<Course | null>(null);
  const [groups, setGroups] = useState<GroupOverview[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    setError(null);
    try {
      const studentCourse = user.courses.find(
        (membership) => membership.role === "student",
      );
      const groupIds = user.groups.map((membership) => membership.group_id);
      const [courses, overviews] = await Promise.all([
        api.courses(),
        loadGroups(api, groupIds),
      ]);
      setCourse(
        courses.find((item) => item.id === studentCourse?.course_id) ??
          courses[0] ??
          null,
      );
      setGroups(overviews);
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
        eyebrow={t("studentHome")}
        title={t("appName")}
        description={course?.name}
      />
      {groups.length === 0 ? (
        <EmptyCard title={t("noGroup")} />
      ) : (
        <div className="overview-grid">
          {groups.map((overview) => (
            <GroupOverviewCard key={overview.group.id} overview={overview} />
          ))}
        </div>
      )}
    </>
  );
}

function GroupOverviewCard({ overview }: { overview: GroupOverview }) {
  const t = useT();
  const { group, agents, documents } = overview;
  return (
    <SectionCard
      title={group.name}
      description={`${group.members?.length ?? 0} ${t("groupMembers")}`}
      action={
        <Link className="text-link" href={`/student/groups/${group.id}`}>
          {t("openWorkspace")}
        </Link>
      }
    >
      <div className="stat-row">
        <div>
          <strong>
            {agents.filter((agent) => agent.status === "active").length}
          </strong>
          <span>{t("activeAgents")}</span>
        </div>
        <div>
          <strong>
            {
              documents.filter(
                (document) => document.workspace_state === "active",
              ).length
            }
          </strong>
          <span>{t("markdownFiles")}</span>
        </div>
        <div>
          <strong>
            {
              agents.filter((agent) =>
                Boolean(agent.current_published_version_id),
              ).length
            }
          </strong>
          <span>{t("publishedCount")}</span>
        </div>
      </div>
      <div className="compact-list">
        {agents.slice(0, 4).map((agent) => (
          <Link
            className="list-row"
            href={`/student/agents/${agent.id}`}
            key={agent.id}
          >
            <span>
              <strong>{agent.name}</strong>
              <small>{agent.description}</small>
            </span>
            <StatusBadge status={agent.status} />
          </Link>
        ))}
      </div>
    </SectionCard>
  );
}

export function GroupWorkspace({ groupId }: { groupId: string }) {
  const t = useT();
  const { locale } = useLocale();
  const { api } = useSession();
  const [group, setGroup] = useState<GroupDetail | null>(null);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextGroup, nextAgents, nextDocuments] = await Promise.all([
        api.group(groupId),
        // Archived rows are legacy data only; they remain discoverable for
        // explicit safe deletion and are not offered as archive actions.
        api.agents(groupId, true),
        api.knowledge(groupId),
      ]);
      setGroup(nextGroup);
      setAgents(nextAgents);
      setDocuments(nextDocuments);
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [api, groupId]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading) return <LoadingCard />;
  if (error || !group)
    return (
      <ErrorNotice
        error={error ?? new Error(t("groupNotFound"))}
        onRetry={() => void load()}
      />
    );

  return (
    <>
      <PageIntro
        eyebrow={t("groupWorkspace")}
        title={group.name}

        action={
          <div className="button-row">
            <Link
              className="primary-action"
              href={`/student/groups/${groupId}/agents/new`}
            >
              {t("createAgent")}
            </Link>
            <Link
              className="secondary-action"
              href={`/student/groups/${groupId}/knowledge`}
            >
              {t("openKnowledge")}
            </Link>
          </div>
        }
      />
      <div className="workspace-grid">
        <SectionCard title={t("agents")}>
          {agents.length === 0 ? (
            <EmptyCard
              title={t("noAgents")}
              action={
                <Link
                  className="secondary-action"
                  href={`/student/groups/${groupId}/agents/new`}
                >
                  {t("createAgent")}
                </Link>
              }
            />
          ) : (
            <div className="agent-list">
              {agents.map((agent) => (
                <GroupAgentRow
                  agent={agent}
                  key={`${agent.id}:${(agent as AgentWithMetadata).metadata_revision ?? 0}:${agent.description ?? ""}`}
                  onUpdated={(updated) =>
                    setAgents((current) =>
                      current.map((item) =>
                        item.id === updated.id ? updated : item,
                      ),
                    )
                  }
                />
              ))}
            </div>
          )}
        </SectionCard>
        <SectionCard
          title={t("knowledgeLibrary")}

          action={
            <Link
              className="text-link"
              href={`/student/groups/${groupId}/knowledge`}
            >
              {t("manageFiles")}
            </Link>
          }
        >
          {documents.length === 0 ? (
            <p className="muted-copy">{t("noMarkdown")}</p>
          ) : (
            <div className="compact-list">
              {documents.slice(0, 6).map((document) => (
                <div className="list-row" key={document.id}>
                  <span>
                    <strong>{document.source_filename}</strong>
                    <small>
                      {document.char_count.toLocaleString()} {t("characters")}
                    </small>
                  </span>
                  <StatusBadge status={document.index_status} />
                </div>
              ))}
            </div>
          )}
        </SectionCard>
      </div>
      <SectionCard title={t("members")}>
        <div className="member-grid">
          {(group.members ?? []).map((member) => (
            <div className="member-chip" key={member.user_id}>
              <span className="avatar-mini">
                {member.display_name.slice(0, 1).toUpperCase()}
              </span>
              <span>{member.display_name}</span>
              <small>{roleLabel(member.role, locale)}</small>
            </div>
          ))}
        </div>
      </SectionCard>
    </>
  );
}

function GroupAgentRow({
  agent,
  onUpdated,
}: {
  agent: AgentSummary;
  onUpdated: (agent: AgentSummary) => void;
}) {
  const t = useT();
  const { api } = useSession();
  const metadataApi = api as AgentMetadataApi;
  const [currentAgent, setCurrentAgent] = useState<AgentWithMetadata>(
    agent as AgentWithMetadata,
  );
  const [descriptionDraft, setDescriptionDraft] = useState(
    agent.description ?? "",
  );
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const dirty = descriptionDraft !== (currentAgent.description ?? "");

  async function refreshAfterConflict(localDraft: string) {
    try {
      const authoritative = await metadataApi.agent(currentAgent.id);
      setCurrentAgent(authoritative as AgentWithMetadata);
      setDescriptionDraft(localDraft);
      setEditing(true);
      setConflict(true);
      setError(null);
    } catch (refreshError) {
      setError(refreshError);
    }
  }

  async function saveDescription() {
    if (!dirty) {
      setEditing(false);
      return;
    }
    const localDraft = descriptionDraft;
    setSaving(true);
    setError(null);
    try {
      const next = await metadataApi.updateAgentMetadata(currentAgent.id, {
        expected_metadata_revision: currentAgent.metadata_revision ?? 0,
        description: localDraft,
      });
      const nextAgent = next as AgentWithMetadata;
      setCurrentAgent(nextAgent);
      setDescriptionDraft(nextAgent.description ?? "");
      setEditing(false);
      setConflict(false);
      onUpdated(nextAgent);
    } catch (cause) {
      if (isMetadataRevisionConflict(cause)) {
        await refreshAfterConflict(localDraft);
      } else {
        setError(cause);
      }
    } finally {
      setSaving(false);
    }
  }

  function cancelDescription() {
    setDescriptionDraft(currentAgent.description ?? "");
    setEditing(false);
    setConflict(false);
    setError(null);
  }

  if (editing) {
    return (
      <div
        className="agent-row"
        data-agent-row={currentAgent.id}
        style={{ flexWrap: "wrap" }}
      >
        <div className="avatar-orb" aria-hidden="true">
          {currentAgent.name.slice(0, 1).toUpperCase()}
        </div>
        <div className="agent-row-copy">
          <Link
            href={`/student/agents/${currentAgent.id}`}
            className="text-link"
          >
            {currentAgent.name}
          </Link>
          <label>
            <span className="section-label">{t("description")}</span>
            <textarea
              aria-label={t("description")}
              rows={2}
              value={descriptionDraft}
              disabled={saving}
              onChange={(event) => setDescriptionDraft(event.target.value)}
            />
          </label>
          {conflict ? (
            <div className="notice notice-warning" role="alert">
              <strong>{t("metadataConflict")}</strong>
              <span aria-label={t("currentMetadata")}>
                {t("currentMetadata")}: {currentAgent.description}
              </span>
            </div>
          ) : null}
          {error ? <ErrorNotice error={error} /> : null}
          <div className="button-row">
            <button
              className="primary-action"
              type="button"
              disabled={saving || !dirty}
              onClick={() => void saveDescription()}
            >
              {saving ? t("saving") : t("saveDescription")}
            </button>
            <button
              className="secondary-action"
              type="button"
              disabled={saving}
              onClick={cancelDescription}
            >
              {t("cancel")}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="agent-row student-agent-entry"
      data-agent-row={currentAgent.id}
    >
      <Link
        href={`/student/agents/${currentAgent.id}`}
        className="agent-row-link"
      >
        <div className="avatar-orb" aria-hidden="true">
          {currentAgent.name.slice(0, 1).toUpperCase()}
        </div>
        <div className="agent-row-copy">
          <strong>{currentAgent.name}</strong>
          <div className="chip-row">
            <StatusBadge status={currentAgent.status} />
            {currentAgent.current_draft_version_id ? (
              <StatusBadge status="draft" />
            ) : null}
            {currentAgent.current_published_version_id ? (
              <StatusBadge status="published" />
            ) : null}
          </div>
        </div>
        <span className="row-arrow" aria-hidden="true">
          →
        </span>
      </Link>
      <button
        className="secondary-action description-edit-trigger"
        type="button"
        aria-label={t("editDescription")}
        onClick={() => {
          setDescriptionDraft(currentAgent.description ?? "");
          setEditing(true);
          setError(null);
        }}
      >
        <span>{currentAgent.description}</span>
        <span aria-hidden="true">✎</span>
      </button>
    </div>
  );
}

export function CreateAgentForm({ groupId }: { groupId: string }) {
  const t = useT();
  const { api } = useSession();
  const router = useRouter();
  const mutationStore = useIdempotencyStore();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [retryable, setRetryable] = useState(false);
  const mutationIntent = `create-agent:${groupId}`;

  function abandonCreateIntent() {
    mutationStore.abandon(mutationIntent);
    setRetryable(false);
  }

  async function createAgent() {
    setBusy(true);
    setError(null);
    const handle = mutationStore.handleFor(mutationIntent);
    try {
      const created = await api.createAgent(
        groupId,
        name.trim(),
        description.trim(),
        { idempotency: handle },
      );
      mutationStore.finish(mutationIntent, handle);
      setRetryable(false);
      const draftId =
        created.current_draft_version_id ??
        created.versions?.find((version) => version.state === "draft")?.id;
      router.push(
        draftId
          ? `/student/agent-versions/${draftId}/edit`
          : `/student/agents/${created.id}`,
      );
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) {
        setRetryable(true);
      } else {
        mutationStore.abandon(mutationIntent, handle);
        setRetryable(false);
      }
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void createAgent();
  }

  return (
    <>
      <PageIntro eyebrow={t("agents")} title={t("newAgent")} />
      <SectionCard title={t("agentIdentity")}>
        <form className="stack-form wide-form" onSubmit={submit}>
          <label>
            <span>{t("agentName")}</span>
            <input
              value={name}
              maxLength={120}
              onChange={(event) => {
                abandonCreateIntent();
                setName(event.target.value);
              }}
              required
            />
          </label>
          <label>
            <span>
              {t("shortDescription")} <small>{t("optional")}</small>
            </span>
            <textarea
              value={description}
              maxLength={500}
              onChange={(event) => {
                abandonCreateIntent();
                setDescription(event.target.value);
              }}
              rows={4}
            />
          </label>
          {error ? (
            <ErrorNotice
              error={error}
              onRetry={retryable ? () => void createAgent() : undefined}
            />
          ) : null}
          <div className="button-row">
            <Link
              className="secondary-action"
              href={`/student/groups/${groupId}`}
            >
              {t("cancel")}
            </Link>
            <button className="primary-action" type="submit" disabled={busy}>
              {busy ? t("creating") : t("createV10")}
            </button>
          </div>
        </form>
      </SectionCard>
    </>
  );
}
