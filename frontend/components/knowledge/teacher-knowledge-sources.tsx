"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { AgentSummary, KnowledgeDocument } from "../../lib/api";
import { useT } from "../locale";
import { useSession } from "../session-provider";
import { EmptyCard, ErrorNotice, LoadingCard, SectionCard } from "../ui";
import { KnowledgeLibrary } from "./knowledge-library";
import styles from "./teacher-knowledge-sources.module.css";

export function TeacherKnowledgeSources({
  courseId,
  groups,
}: {
  courseId: string | null;
  groups: Array<{ id: string; name: string }>;
}) {
  return (
    <TeacherKnowledgeSourcesForCourse
      key={courseId ?? "no-course"}
      courseId={courseId}
      groups={groups}
    />
  );
}

function TeacherKnowledgeSourcesForCourse({
  courseId,
  groups,
}: {
  courseId: string | null;
  groups: Array<{ id: string; name: string }>;
}) {
  const t = useT();
  const { api } = useSession();
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const groupId = groups.some((group) => group.id === selectedGroupId)
    ? selectedGroupId
    : (groups[0]?.id ?? "");
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [loadedCourseId, setLoadedCourseId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!courseId) return;
    let active = true;
    void Promise.all([
      api.workspaceDocuments(courseId),
      api.workspaceAgents(courseId),
    ])
      .then(([nextDocuments, nextAgents]) => {
        if (!active) return;
        setDocuments(
          nextDocuments.filter(
            (document) =>
              document.ownership_scope === "personal" &&
              document.workspace_state === "active",
          ),
        );
        setAgents(nextAgents);
        setLoadedCourseId(courseId);
      })
      .catch((cause) => {
        if (active) {
          setError(cause);
          setLoadedCourseId(courseId);
        }
      });
    return () => {
      active = false;
    };
  }, [api, courseId]);

  const visibleDocuments = courseId ? documents : [];
  const visibleAgents = courseId ? agents : [];
  const visibleLoading = Boolean(courseId && loadedCourseId !== courseId);
  const visibleError = courseId ? error : null;

  return (
    <div className="teacher-home-layout">
      <SectionCard
        title={t("originalCourseSources")}
        description={t("personalRawSourceLede")}
        action={
          <Link className="primary-action" href="/teacher">
            {t("openAgents")}
          </Link>
        }
      >
        {visibleError ? <ErrorNotice error={visibleError} /> : null}
        {visibleLoading ? (
          <LoadingCard />
        ) : visibleDocuments.length === 0 ? (
          <EmptyCard title={t("originalCourseSources")}>
            {t("noResults")}
          </EmptyCard>
        ) : (
          <ul className="document-list">
            {visibleDocuments.map((document) => (
              <li className="document-row" key={document.id}>
                <div className="document-main">
                  <strong>{document.source_filename}</strong>
                  <span>
                    {document.char_count} characters · {document.index_status}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
        {visibleAgents.length ? (
          <div className="button-row">
            {visibleAgents.map((agent) => (
              <Link
                className="secondary-action"
                href={`/teacher/agents/${encodeURIComponent(agent.id)}`}
                key={agent.id}
              >
                {agent.name}
              </Link>
            ))}
          </div>
        ) : null}
      </SectionCard>

      <SectionCard
        title={t("groupRawSources")}
        description={t("originalSourcesIntro")}
        action={
          groups.length ? (
            <label className={styles.groupChoice}>
              <span>{t("group")}</span>
              <select
                aria-label={t("group")}
                value={groupId}
                onChange={(event) => setSelectedGroupId(event.target.value)}
              >
                {groups.map((group) => (
                  <option key={group.id} value={group.id}>
                    {group.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null
        }
      >
        {groupId ? (
          <KnowledgeLibrary groupId={groupId} key={groupId} />
        ) : (
          <EmptyCard title={t("groupRawSources")}>
            {t("noJoinedGroup")}
          </EmptyCard>
        )}
      </SectionCard>
    </div>
  );
}
