"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  isAmbiguousMutationFailure,
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

async function loadGroups(
  api: PlatformApi,
  groupIds: string[],
): Promise<GroupOverview[]> {
  return Promise.all(
    groupIds.map(async (groupId) => {
      const [group, agents, documents] = await Promise.all([
        api.group(groupId),
        api.agents(groupId),
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
        title={`${t("welcomeBack")}${user?.display_name ? `, ${user.display_name}` : ""}.`}
        description={t("studentHomeLede")}
        action={
          course ? (
            <div className="course-context">
              <span className="section-label">{t("currentCourse")}</span>
              <strong>{course.name}</strong>
              <span>{course.code}</span>
            </div>
          ) : null
        }
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
      <SectionCard
        title={t("teachingNote")}
        description={t("teachingNoteLede")}
      >
        <div className="teaching-note-grid">
          <div>
            <span className="feature-index">01</span>
            <h3>{t("promptTeaching")}</h3>
            <p>{t("promptTeachingLede")}</p>
          </div>
          <div>
            <span className="feature-index">02</span>
            <h3>{t("ragTeaching")}</h3>
            <p>{t("ragTeachingLede")}</p>
          </div>
          <div>
            <span className="feature-index">03</span>
            <h3>{t("releaseTeaching")}</h3>
            <p>{t("releaseTeachingLede")}</p>
          </div>
        </div>
      </SectionCard>
    </>
  );
}

function GroupOverviewCard({ overview }: { overview: GroupOverview }) {
  const t = useT();
  const { group, agents, documents } = overview;
  return (
    <SectionCard
      title={group.name}
      description={`${group.members?.length ?? 0} ${t("groupMembers")} · ${t("privateGroup")}`}
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
              <small>{agent.description || t("noDescription")}</small>
            </span>
            <StatusBadge status={agent.status} />
          </Link>
        ))}
        {agents.length === 0 ? (
          <p className="muted-copy">{t("createFirstAgent")}</p>
        ) : null}
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
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextGroup, nextAgents, nextDocuments] = await Promise.all([
        api.group(groupId),
        api.agents(groupId, showArchived),
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
  }, [api, groupId, showArchived]);
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
        description={t("groupLede")}
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
        <SectionCard
          title={t("agents")}
          description={t("agentsLede")}
          action={
            <label className="toggle-label">
              <input
                type="checkbox"
                checked={showArchived}
                onChange={(event) => setShowArchived(event.target.checked)}
              />{" "}
              {t("showArchived")}
            </label>
          }
        >
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
                <Link
                  className="agent-row"
                  href={`/student/agents/${agent.id}`}
                  key={agent.id}
                >
                  <div className="avatar-orb" aria-hidden="true">
                    {agent.name.slice(0, 1).toUpperCase()}
                  </div>
                  <div className="agent-row-copy">
                    <strong>{agent.name}</strong>
                    <span>{agent.description || t("defineIdentity")}</span>
                    <div className="chip-row">
                      <StatusBadge status={agent.status} />
                      {agent.current_draft_version_id ? (
                        <StatusBadge status="draft" />
                      ) : null}
                      {agent.current_published_version_id ? (
                        <StatusBadge status="published" />
                      ) : null}
                    </div>
                  </div>
                  <span className="row-arrow" aria-hidden="true">
                    →
                  </span>
                </Link>
              ))}
            </div>
          )}
        </SectionCard>
        <SectionCard
          title={t("knowledgeLibrary")}
          description={t("knowledgeLede")}
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
      <SectionCard title={t("members")} description={t("membersLede")}>
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
      <PageIntro
        eyebrow={t("newAgent")}
        title={t("newAgentTitle")}
        description={t("newAgentLede")}
      />
      <SectionCard
        title={t("agentIdentity")}
        description={t("agentIdentityLede")}
      >
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
              placeholder={t("agentNamePlaceholder")}
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
              placeholder={t("descriptionPlaceholder")}
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
