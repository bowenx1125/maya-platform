"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useLocale } from "../locale";
import { useSession } from "../session-provider";
import { ErrorNotice, LoadingCard, PageIntro } from "../ui";
import { statusLabel } from "../../lib/i18n";
import type { DebateSummary } from "../../lib/api";
import styles from "./beta-debate-list.module.css";

/** Mirrors the classic list's lookup; the shared surface stays untouched. */
function teacherCourseId(
  user: ReturnType<typeof useSession>["user"],
): string | null {
  return (
    user?.courses.find((membership) => membership.role === "teacher")
      ?.course_id ?? null
  );
}

const COPY = {
  en: {
    eyebrow: "Debates (beta)",
    title: "The 3D bench",
    unavailable: "No teacher course is available for this account.",
    empty: "No debates yet. Create one in Debates, then open it here.",
    open: "Open on the bench",
    classic: "Debates",
    classicHint: "Create, edit and report on debates in the classic surface.",
  },
  zh: {
    eyebrow: "Debates（beta）",
    title: "3D 讲席",
    unavailable: "当前账号没有可用的教师课程。",
    empty: "还没有辩论。先在 Debates 里创建，再回到这里打开。",
    open: "在讲席上打开",
    classic: "Debates",
    classicHint: "创建、编辑和生成报告仍在原来的 Debates 页面。",
  },
} as const;

export function BetaDebateList() {
  const { locale } = useLocale();
  const { api, user } = useSession();
  const copy = COPY[locale === "zh" ? "zh" : "en"];
  const [debates, setDebates] = useState<DebateSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const courseId = teacherCourseId(user);

  const load = useCallback(async () => {
    if (!courseId) {
      setError(new Error(copy.unavailable));
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setDebates(await api.debates(courseId));
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [api, copy.unavailable, courseId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return (
    <>
      <PageIntro eyebrow={copy.eyebrow} title={copy.title} />
      <p className={styles.hint}>
        {copy.classicHint} <Link href="/teacher/debates">{copy.classic}</Link>
      </p>

      {loading ? <LoadingCard /> : null}
      {!loading && error ? (
        <ErrorNotice error={error} onRetry={() => void load()} />
      ) : null}

      {!loading && !error ? (
        debates.length === 0 ? (
          <p className={styles.empty}>{copy.empty}</p>
        ) : (
          <ul className={styles.list}>
            {debates.map((debate) => (
              <li className={styles.row} key={debate.id}>
                <div className={styles.rowMain}>
                  <h2>{debate.topic}</h2>
                  <span className={styles.meta}>
                    <span className={styles.status} data-status={debate.status}>
                      {statusLabel(debate.status, locale)}
                    </span>
                    {debate.expected_turns > 0 ? (
                      <span className={styles.progress}>
                        {debate.prepared_turns}/{debate.expected_turns}
                      </span>
                    ) : null}
                  </span>
                </div>
                <Link
                  className="primary-action"
                  href={`/teacher/debates-beta/${debate.id}/control`}
                >
                  {copy.open}
                </Link>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </>
  );
}
