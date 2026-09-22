"use client";

import { WorkspaceAction } from "./workspace-actions";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  isAmbiguousMutationFailure,
  type AgentSummary,
  type GroupDetail,
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
      <PageIntro title={t("appName")} />
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
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [retryDelete, setRetryDelete] = useState<string | null>(null);
  const mutations = useIdempotencyStore();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextGroup, nextAgents] = await Promise.all([
        api.group(groupId),
        // Archived rows are legacy data only; they remain discoverable for
        // explicit safe deletion and are not offered as archive actions.
        api.agents(groupId, true),
      ]);
      setGroup(nextGroup);
      setAgents(nextAgents);
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
  async function deleteAgent(agentId: string, retry = false) {
    if (deleting || (!retry && !window.confirm(t("deleteAgentConfirm"))))
      return;
    const intent = `agent-delete:${agentId}`;
    const handle = mutations.handleFor(intent);
    setDeleting(agentId);
    setError(null);
    setRetryDelete(null);
    try {
      await api.deleteAgent(agentId, { idempotency: handle });
      mutations.finish(intent, handle);
      setAgents((current) => current.filter((agent) => agent.id !== agentId));
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) setRetryDelete(agentId);
      else mutations.abandon(intent, handle);
      setError(cause);
    } finally {
      setDeleting(null);
    }
  }

  if (!group)
    return (
      <ErrorNotice
        error={error ?? new Error(t("groupNotFound"))}
        onRetry={() => void load()}
      />
    );

  return (
    <>
      <PageIntro title={t("groupWorkspace")} />
      {error ? (
        <ErrorNotice
          error={error}
          onRetry={
            retryDelete ? () => void deleteAgent(retryDelete, true) : undefined
          }
        />
      ) : null}
      <WorkspaceAction
        name="new"
        href={`/student/groups/${groupId}/agents/new`}
      />
      <SectionCard title={t("agents")}>
        {agents.length === 0 ? (
          <EmptyCard title={t("noAgents")} />
        ) : (
          <div className="agent-list">
            {agents.map((agent) => (
              <GroupAgentRow
                agent={agent}
                key={agent.id}
                deleting={deleting !== null}
                onDelete={() => void deleteAgent(agent.id)}
              />
            ))}
          </div>
        )}
      </SectionCard>
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
  deleting,
  onDelete,
}: {
  agent: AgentSummary;
  deleting: boolean;
  onDelete: () => void;
}) {
  const t = useT();
  const state =
    agent.status === "archived"
      ? "archived"
      : agent.current_draft_version_id
        ? "draft"
        : "published";
  return (
    <div className="agent-row" data-agent-row={agent.id}>
      <Link
        className="agent-row-name text-link"
        href={`/student/agents/${agent.id}`}
      >
        {agent.name}
      </Link>
      <StatusBadge status={state} />
      <button
        className="inline-button danger-button"
        type="button"
        disabled={deleting}
        onClick={onDelete}
      >
        {t("deleteAgent")}
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
    if (busy) return;
    void createAgent();
  }

  return (
    <>
      <PageIntro title={t("newAgent")} />
      <WorkspaceAction
        name="back"
        href={`/student/groups/${groupId}`}
        disabled={busy}
      />
      <WorkspaceAction name="done" form="create-agent-form" disabled={busy} />
      <SectionCard title={t("agentIdentity")}>
        <form
          id="create-agent-form"
          className="stack-form wide-form"
          onSubmit={submit}
          aria-busy={busy}
        >
          <label>
            <span>{t("agentName")}</span>
            <input
              value={name}
              disabled={busy}
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
              disabled={busy}
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
        </form>
      </SectionCard>
    </>
  );
}
