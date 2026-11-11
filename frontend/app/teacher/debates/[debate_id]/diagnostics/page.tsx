"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { AppShell } from "../../../../../components/app-shell";
import { DebateDiagnosticsView } from "../../../../../components/debate/diagnostics";
import { PageAction } from "../../../../../components/page-action";
import {
  RouteGuard,
  useSession,
} from "../../../../../components/session-provider";
import { ErrorNotice, LoadingCard } from "../../../../../components/ui";
import {
  fetchDebateDiagnostics,
  type DebateDiagnostics,
} from "../../../../../lib/api/debate-diagnostics";

export default function TeacherDebateDiagnosticsPage() {
  const params = useParams<{ debate_id: string | string[] }>();
  const rawDebateId = params?.debate_id;
  const debateId = Array.isArray(rawDebateId) ? rawDebateId[0] : rawDebateId;
  const { api } = useSession();
  const [diagnostics, setDiagnostics] = useState<DebateDiagnostics | null>(
    null,
  );
  const [topic, setTopic] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const request = useRef(0);

  const load = useCallback(async () => {
    if (!debateId) return;
    const current = ++request.current;
    setError(null);
    setLoading(true);
    try {
      const [next, detail] = await Promise.all([
        fetchDebateDiagnostics(debateId),
        api.debate(debateId),
      ]);
      if (current !== request.current) return;
      setDiagnostics(next);
      setTopic(detail.topic);
    } catch (cause) {
      if (current === request.current) setError(cause);
    } finally {
      if (current === request.current) setLoading(false);
    }
  }, [api, debateId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => {
      request.current += 1;
      window.clearTimeout(timer);
    };
  }, [load]);

  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <PageAction
          name="back"
          href={
            debateId
              ? `/teacher/debates/${encodeURIComponent(debateId)}/control`
              : "/teacher/debates"
          }
        />
        {loading && !diagnostics ? <LoadingCard /> : null}
        {!loading && error && !diagnostics ? (
          <ErrorNotice
            inline
            notFound="debateNotFound"
            error={error}
            onRetry={() => void load()}
          />
        ) : null}
        {diagnostics ? (
          <DebateDiagnosticsView topic={topic} diagnostics={diagnostics} />
        ) : null}
      </AppShell>
    </RouteGuard>
  );
}
