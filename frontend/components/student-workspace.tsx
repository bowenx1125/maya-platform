"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  isAmbiguousMutationFailure,
  type AgentSummary,
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
};

async function loadGroups(
  api: PlatformApi,
  groupIds: string[],
): Promise<GroupOverview[]> {
  return Promise.all(
    groupIds.map(async (groupId) => {
      const [group, agents] = await Promise.all([
        api.group(groupId),
        // Keep legacy archived rows discoverable so an old, never-published
        // Agent still has an explicit hard-delete path after archive UI is
        // removed.  Historical rows remain visibly inactive and are rejected
        // by the server's history check.
        api.agents(groupId, true),
      ]);
      return { group, agents };
    }),
  );
}

export function StudentDashboard() {
  const t = useT();
  const { api, user } = useSession();
  const [groups, setGroups] = useState<GroupOverview[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    setError(null);
    try {
      const groupIds = user.groups.map((membership) => membership.group_id);
      const overviews = await loadGroups(api, groupIds);
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
      <PageIntro eyebrow={t("studentHome")} title={t("appName")} />
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
  const { group, agents } = overview;
  return (
    <SectionCard
      title={group.name}
      action={
        <Link className="text-link" href={`/student/groups/${group.id}`}>
          {t("openWorkspace")}
        </Link>
      }
    >
      <div className="compact-list">
        {agents.slice(0, 4).map((agent) => (
          <Link
            className="list-row"
            href={`/student/agents/${agent.id}`}
            key={agent.id}
          >
            <span>
              <strong>{agent.name}</strong>
            </span>
            <StatusBadge
              status={
                agent.status === "archived"
                  ? "archived"
                  : agent.current_draft_version_id
                    ? "draft"
                    : "published"
              }
            />
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
          </div>
        }
      />
      <div className="workspace-grid">
        <SectionCard title={t("agents")}>
          {agents.length === 0 ? (
            <EmptyCard title={t("noAgents")} />
          ) : (
            <div className="agent-list">
              {agents.map((agent) => (
                <GroupAgentRow agent={agent} key={agent.id} />
              ))}
            </div>
          )}
        </SectionCard>
        <SectionCard
          title={t("knowledgePage")}

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

function GroupAgentRow({ agent }: { agent: AgentSummary }) {
  const state =
    agent.status === "archived"
      ? "archived"
      : agent.current_draft_version_id
        ? "draft"
        : "published";
  return (
    <Link
      className="agent-row"
      href={`/student/agents/${agent.id}`}
      data-agent-row={agent.id}
    >
      <strong className="agent-row-name">{agent.name}</strong>
      <StatusBadge status={state} />
    </Link>
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
