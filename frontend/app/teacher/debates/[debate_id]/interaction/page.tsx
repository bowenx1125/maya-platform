"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "../../../../../components/app-shell";
import { PageAction } from "../../../../../components/page-action";
import { TeacherWave3 } from "../../../../../components/wave3";
import {
  ErrorNotice,
  LoadingCard,
  PageIntro,
} from "../../../../../components/ui";
import {
  RouteGuard,
  useSession,
} from "../../../../../components/session-provider";
import type { DebateDetail } from "../../../../../lib/api";
import { useT } from "../../../../../lib/i18n";

export default function TeacherDebateInteractionPage() {
  const t = useT();
  const params = useParams<{ debate_id: string | string[] }>();
  const rawDebateId = params?.debate_id;
  const debateId = Array.isArray(rawDebateId) ? rawDebateId[0] : rawDebateId;
  const { api } = useSession();
  const [detail, setDetail] = useState<DebateDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    if (!debateId) {
      setError(new Error(t("debateMissingId")));
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      setDetail(await api.debate(debateId));
      setError(null);
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [api, debateId, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        {loading && !detail ? <LoadingCard /> : null}
        {!loading && error && !detail ? (
          <ErrorNotice
            inline
            notFound="debateNotFound"
            error={error}
            onRetry={() => void load()}
          />
        ) : null}
        {detail && debateId ? (
          <>
            <PageIntro title={t("wave3Title")} />
            <PageAction
              name="back"
              href={`/teacher/debates/${debateId}/control`}
            />
            {error ? (
              <ErrorNotice error={error} onRetry={() => void load()} />
            ) : null}
            <TeacherWave3 api={api} debateId={debateId} detail={detail} />
          </>
        ) : null}
      </AppShell>
    </RouteGuard>
  );
}
