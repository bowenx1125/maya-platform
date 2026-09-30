"use client";

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
import { AcademyMascots } from "./academy/mascots";
import { AccountSettings } from "./account-settings";
import { useLocale, useT } from "./locale";
import { PageAction } from "./page-action";
import { IconClose } from "./quiet-icons";
import { useSession } from "./session-provider";
import { UserAvatar } from "./user-avatar";
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
} from "./ui";

type GroupOverview = {
  group: GroupDetail;
  agentCount: number;
  knowledgeCount: number;
  voiceCount: number;
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
    groupIds.map(async (groupId) => {
      const [group, agents, knowledge, voices] = await Promise.all([
        api.group(groupId),
        api.agents(groupId, true),
        api.knowledge(groupId),
        api.voiceProfiles(groupId),
      ]);
      return {
        group,
        agentCount: agents.length,
        knowledgeCount: knowledge.length,
        voiceCount: voices.length,
      };
    }),
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
  const label = published?.version_label ?? draft?.version_label ?? "V1.0";
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
  const hasUser = Boolean(user);
  const groupIdsKey = user?.groups
    .map((membership) => membership.group_id)
    .join(",");
  const courseId = user?.courses[0]?.course_id;

  const load = useCallback(async () => {
    if (!hasUser) return;
    setError(null);
    try {
      const groupIds = groupIdsKey ? groupIdsKey.split(",") : [];
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
  }, [api, courseId, groupIdsKey, hasUser]);

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
  const primary = groups[0];
  const guide = primary
    ? [
        {
          label: t("studentGuideGroup"),
          complete: true,
          href: `/student/groups/${primary.group.id}`,
        },
        {
          label: t("studentGuideAgent"),
          complete: primary.agentCount > 0,
          href: `/student/groups/${primary.group.id}/agents/new`,
        },
        {
          label: t("studentGuideKnowledge"),
          complete: primary.knowledgeCount > 0,
          href: `/student/groups/${primary.group.id}/knowledge`,
        },
        {
          label: t("studentGuideVoice"),
          complete: primary.voiceCount > 0,
          optional: true,
          href: `/student/groups/${primary.group.id}/voices`,
        },
      ]
    : [];

  return (
    <div className="mayaform-home">
      <section className="home-hero">
        <div className="home-hero-copy">
          {/* The course is the eyebrow rather than a sentence underneath: it
              is one of the four things this page has to answer, and naming it
              costs less than explaining it. */}
          <p className="home-hero-eyebrow">{courseName}</p>
          <h1>{t("homeWelcomeTitle", { name })}</h1>
        </div>
        <div className="home-hero-art">
          <AcademyMascots label={t("academyMascotsLabel")} />
        </div>
      </section>
      {groups.length === 0 ? (
        <EmptyCard title={t("noGroup")} />
      ) : (
        <div className="home-columns">
          <section className="home-panel" aria-labelledby="student-guide-title">
            <h2 id="student-guide-title">{t("guide")}</h2>
            <div className="home-guide-list">
              {guide.map((item, index) => (
                <Link
                  className="home-guide-row"
                  href={item.href}
                  key={item.label}
                >
                  <span
                    className="home-guide-marker"
                    data-complete={item.complete ? "true" : undefined}
                    aria-hidden="true"
                  >
                    {item.complete ? "✓" : index + 1}
                  </span>
                  <strong>{item.label}</strong>
                  {item.optional ? <small>{t("guideOptional")}</small> : null}
                  <span className="home-guide-state">
                    {item.complete ? t("guideDone") : t("guideNext")}
                  </span>
                  <span aria-hidden="true">→</span>
                </Link>
              ))}
            </div>
          </section>
          {groups.map((overview) => (
            <section
              className="home-panel"
              key={overview.group.id}
              aria-labelledby={`group-${overview.group.id}`}
            >
              <h2 id={`group-${overview.group.id}`}>{overview.group.name}</h2>
              <ul className="home-people-list">
                {(overview.group.members ?? []).map((member) => (
                  <li className="home-person" key={member.user_id}>
                    <UserAvatar
                      avatar={member.avatar}
                      name={member.display_name}
                      userId={member.user_id}
                      size="sm"
                    />
                    <strong>{member.display_name}</strong>
                    <small>{roleLabel(member.role, locale)}</small>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      <AccountSettings onSaved={() => void load()} />
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

  const newAgent = (
    <PageAction name="new" href={`/student/groups/${groupId}/agents/new`} />
  );

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
      <SectionCard
        title={`${t("agents")} · ${items.length}`}
        action={items.length > 0 ? newAgent : undefined}
      >
        {items.length === 0 ? (
          <EmptyCard title={t("noAgents")} action={newAgent} />
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
      <PageAction
        name="back"
        href={`/student/groups/${groupId}`}
        disabled={busy}
      />
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
          <div className="button-row">
            <PageAction name="done" form="create-agent-form" disabled={busy} />
          </div>
        </form>
      </SectionCard>
    </>
  );
}
