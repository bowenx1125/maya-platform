"use client";

import { WorkspaceAction } from "./workspace-actions";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  isAmbiguousMutationFailure,
  type AgentSummary,
  type AgentVersion,
  type Course,
  type GroupDetail,
  type PlatformApi,
} from "../lib/api";
import { useIdempotencyStore } from "../lib/idempotency";
import { roleLabel } from "../lib/i18n";
import { useLocale, useT } from "./locale";
import { IconClose } from "./quiet-icons";
import { useSession } from "./session-provider";
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
} from "./ui";

type GroupOverview = {
  group: GroupDetail;
};

type AgentListItem = {
  agent: AgentSummary;
  versions: AgentVersion[];
};

async function loadGroups(
  api: PlatformApi,
  groupIds: string[],
): Promise<GroupOverview[]> {
  return Promise.all(
    groupIds.map(async (groupId) => ({
      group: await api.group(groupId),
    })),
  );
}

function versionBubble(agent: AgentSummary, versions: AgentVersion[]) {
  const published =
    versions.find(
      (version) => version.id === agent.current_published_version_id,
    ) ?? versions.find((version) => version.state === "published");
  const draft =
    versions.find((version) => version.id === agent.current_draft_version_id) ??
    versions.find((version) => version.state === "draft");
  const hasUnpublishedWork =
    Boolean(agent.current_draft_version_id) &&
    agent.current_draft_version_id !== agent.current_published_version_id;
  const onlyDraft = !agent.current_published_version_id && Boolean(draft);
  const label =
    published?.version_label ?? draft?.version_label ?? "V1.0";
  return {
    label,
    pending: hasUnpublishedWork || onlyDraft || agent.status === "archived",
  };
}

export function StudentDashboard() {
  const t = useT();
  const { locale } = useLocale();
  const { api, user } = useSession();
  const [groups, setGroups] = useState<GroupOverview[]>([]);
  const [course, setCourse] = useState<Course | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    setError(null);
    try {
      const groupIds = user.groups.map((membership) => membership.group_id);
      const courseId = user.courses[0]?.course_id;
      const [overviews, courses] = await Promise.all([
        loadGroups(api, groupIds),
        courseId ? api.courses() : Promise.resolve([]),
      ]);
      setGroups(overviews);
      setCourse(
        courses.find((item) => item.id === courseId) ?? courses[0] ?? null,
      );
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

  const name = user?.display_name ?? "";
  const courseName = course?.name ?? t("course");

  return (
    <div className="mayaform-home">
      <section className="mayaform-home-welcome">
        <p className="mayaform-home-eyebrow">{t("appName")}</p>
        <h1>{t("homeWelcomeTitle", { name })}</h1>
        <div className="mayaform-home-rule" aria-hidden="true">
          <span />
          <i />
          <span />
        </div>
        <p className="mayaform-home-lede">
          {t("homeWelcomeCourse", { course: courseName })}
        </p>
        <ul className="mayaform-home-surfaces">
          <li>{t("homeSurfaceChats")}</li>
          <li>{t("homeSurfaceWorkspace")}</li>
          <li>{t("homeSurfaceKnowledge")}</li>
          <li>{t("homeSurfaceVoice")}</li>
          <li>{t("homeSurfaceLive")}</li>
        </ul>
        <p className="mayaform-home-privacy">{t("homePrivacyNote")}</p>
      </section>
      {groups.length === 0 ? (
        <EmptyCard title={t("noGroup")} />
      ) : (
        groups.map((overview) => (
          <section className="mayaform-home-members" key={overview.group.id}>
            <header>
              <h2>{overview.group.name}</h2>
              <p>{t("homeMembersIntro")}</p>
            </header>
            <div className="member-grid">
              {(overview.group.members ?? []).map((member) => (
                <div className="member-chip" key={member.user_id}>
                  <span className="avatar-mini">
                    {member.display_name.slice(0, 1).toUpperCase()}
                  </span>
                  <span>{member.display_name}</span>
                  <small>{roleLabel(member.role, locale)}</small>
                </div>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

export function GroupWorkspace({ groupId }: { groupId: string }) {
  const t = useT();
  const { api } = useSession();
  const [group, setGroup] = useState<GroupDetail | null>(null);
  const [items, setItems] = useState<AgentListItem[]>([]);
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
        api.agents(groupId, true),
      ]);
      const versions = await Promise.all(
        nextAgents.map((agent) => api.versions(agent.id)),
      );
      setGroup(nextGroup);
      setItems(
        nextAgents.map((agent, index) => ({
          agent,
          versions: versions[index] ?? [],
        })),
      );
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

  const createHref = `/student/groups/${groupId}/agents/new`;

  if (loading) {
    return (
      <>
        <WorkspaceAction name="new" href={createHref} disabled />
        <LoadingCard />
      </>
    );
  }
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
      setItems((current) =>
        current.filter((item) => item.agent.id !== agentId),
      );
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
      <>
        <WorkspaceAction name="new" href={createHref} disabled />
        <ErrorNotice
          error={error ?? new Error(t("groupNotFound"))}
          onRetry={() => void load()}
        />
      </>
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
      <WorkspaceAction name="new" href={createHref} />
      <SectionCard title={`${t("agents")} · ${items.length}`}>
        {items.length === 0 ? (
          <EmptyCard title={t("noAgents")} />
        ) : (
          <div className="agent-tile-grid">
            {items.map(({ agent, versions }) => (
              <GroupAgentTile
                agent={agent}
                groupName={group.name}
                key={agent.id}
                versions={versions}
                deleting={deleting !== null}
                onDelete={() => void deleteAgent(agent.id)}
              />
            ))}
          </div>
        )}
      </SectionCard>
    </>
  );
}

function GroupAgentTile({
  agent,
  groupName,
  versions,
  deleting,
  onDelete,
}: {
  agent: AgentSummary;
  groupName: string;
  versions: AgentVersion[];
  deleting: boolean;
  onDelete: () => void;
}) {
  const t = useT();
  const bubble = versionBubble(agent, versions);
  return (
    <div className="agent-tile" data-agent-row={agent.id}>
      <Link
        className="agent-tile-name text-link"
        href={`/student/agents/${agent.id}`}
      >
        {agent.name}
      </Link>
      <span className="agent-tile-group">{groupName}</span>
      <button
        type="button"
        className="agent-pill agent-pill-action"
        data-pending={bubble.pending ? "true" : "false"}
        disabled={deleting}
        aria-label={t("deleteAgent")}
        title={bubble.label}
        onClick={onDelete}
      >
        <span className="agent-pill-label">{bubble.label}</span>
        <span className="agent-pill-x" aria-hidden="true">
          <IconClose size={12} />
        </span>
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
