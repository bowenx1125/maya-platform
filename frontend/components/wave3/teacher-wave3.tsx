"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  CivilizationReport,
  DebateDetail,
  DebateTranscript,
  PlatformApi,
  ReportRevisionSummary,
  TeacherInteraction,
  TranslationBatch,
} from "../../lib/api";
import {
  apiErrorMessage,
  createIdempotencyHandle,
  type IdempotencyHandle,
} from "../../lib/api";
import { HistoryView, type HistoryReport } from "../history";
import { TeacherInteractionPanel } from "../interaction";
import { ReportPanel } from "../report";
import { TranslationPanel } from "../translation";

import styles from "./teacher-wave3.module.css";

type TeacherWave3Props = {
  api: PlatformApi;
  debateId: string;
  detail: DebateDetail;
};

function websocketUrl(debateId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/v1/debates/${encodeURIComponent(debateId)}/events`;
}

export function TeacherWave3({ api, debateId, detail }: TeacherWave3Props) {
  const [interaction, setInteraction] = useState<TeacherInteraction | null>(
    null,
  );
  const [transcript, setTranscript] = useState<DebateTranscript | null>(null);
  const [report, setReport] = useState<CivilizationReport | null>(null);
  const [revisions, setRevisions] = useState<ReportRevisionSummary[]>([]);
  const [batches, setBatches] = useState<TranslationBatch[]>([]);
  const [translationVisible, setTranslationVisible] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<
    "connecting" | "connected" | "disconnected"
  >("connecting");
  const [reconnectBusy, setReconnectBusy] = useState(false);
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  const openKey = useRef<IdempotencyHandle | null>(null);
  const closeKey = useRef<IdempotencyHandle | null>(null);
  const translationKey = useRef<IdempotencyHandle | null>(null);
  const refreshVersion = useRef(0);

  const participants = useMemo(
    () =>
      detail.participants.map((participant) => ({
        id: participant.id,
        slot: participant.slot,
        name: participant.agent_name,
      })),
    [detail.participants],
  );

  const downstreamAllowed =
    detail.status === "debate_finished" || detail.status === "completed";

  const load = useCallback(async () => {
    if (!downstreamAllowed) {
      setInteraction(null);
      setTranscript(null);
      setReport(null);
      setRevisions([]);
      setBatches([]);
      setLoading(false);
      return;
    }
    const version = refreshVersion.current + 1;
    refreshVersion.current = version;
    try {
      const [
        nextInteraction,
        nextTranscript,
        nextReport,
        nextRevisions,
        nextBatches,
      ] = await Promise.all([
        api.teacherInteraction(debateId),
        api.debateTranscript(debateId),
        api.getCurrentReport(debateId),
        api.listReportRevisions(debateId),
        api.listTranslationBatches(debateId),
      ]);
      if (refreshVersion.current !== version) return;
      setInteraction(nextInteraction);
      setTranscript(nextTranscript);
      setReport(nextReport);
      setRevisions(nextRevisions);
      setBatches(nextBatches);
      setError(null);
    } catch (cause) {
      if (refreshVersion.current === version) setError(apiErrorMessage(cause));
    } finally {
      if (refreshVersion.current === version) setLoading(false);
    }
  }, [api, debateId, downstreamAllowed]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (!downstreamAllowed) return;
    let disposed = false;
    let socket: WebSocket | null = null;
    const connect = () => {
      if (disposed) return;
      setConnection("connecting");
      socket = new WebSocket(websocketUrl(debateId));
      socket.onopen = () => {
        if (!disposed) {
          setConnection("connected");
          setReconnectBusy(false);
        }
      };
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(String(message.data)) as {
            event_type?: string;
          };
          if (
            event.event_type === "snapshot" ||
            event.event_type?.startsWith("interaction.") ||
            event.event_type?.startsWith("barrage_insight.") ||
            event.event_type?.startsWith("report.") ||
            event.event_type?.startsWith("translation.")
          ) {
            void load();
          }
        } catch {
          // The closed backend schema remains authoritative; malformed frames are ignored.
        }
      };
      socket.onclose = () => {
        if (!disposed) {
          setConnection("disconnected");
          setReconnectBusy(false);
        }
      };
      socket.onerror = () => {
        if (!disposed) setConnection("disconnected");
      };
    };
    connect();
    return () => {
      disposed = true;
      socket?.close();
    };
  }, [connectionAttempt, debateId, load, downstreamAllowed]);

  const reconnect = useCallback(() => {
    if (!downstreamAllowed || reconnectBusy || connection !== "disconnected")
      return;
    setReconnectBusy(true);
    // A manual retry reloads once; failures leave all already-rendered Wave 3
    // content intact and do not schedule another attempt.
    setConnectionAttempt((value) => value + 1);
    void load()
      .catch(() => undefined)
      .finally(() => {
        setReconnectBusy(false);
      });
  }, [connection, downstreamAllowed, load, reconnectBusy]);

  async function mutate(
    handleRef: { current: IdempotencyHandle | null },
    operation: (handle: IdempotencyHandle) => Promise<unknown>,
  ) {
    setBusy(true);
    setError(null);
    const handle = handleRef.current ?? createIdempotencyHandle();
    handleRef.current = handle;
    try {
      await operation(handle);
      handleRef.current = null;
      await load();
    } catch (cause) {
      setError(apiErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  const historyReport: HistoryReport | undefined = report
    ? {
        generation_status: report.generation_status,
        latest_attempt_status: report.latest_attempt_status,
        current_success_revision: report.current_success_revision ?? null,
        revisions,
      }
    : undefined;

  return (
    <div
      className={styles.root}
      data-wave3-loading={loading ? "true" : "false"}
      data-wave3-connection={downstreamAllowed ? connection : "disabled"}
    >
      {!downstreamAllowed ? (
        <p role="status">
          Partial or unfinished debates keep generated turns for audit, but
          classroom interaction, reports, history and replay are unavailable.
        </p>
      ) : (
        <>
          {connection === "disconnected" ? (
            <div role="status">
              <span>Wave 3 connection disconnected.</span>{" "}
              <button
                type="button"
                onClick={reconnect}
                disabled={reconnectBusy}
              >
                {reconnectBusy ? "Reconnecting…" : "Reconnect / 重新连接"}
              </button>
            </div>
          ) : null}
          {interaction ? (
            <TeacherInteractionPanel
              debateId={debateId}
              interaction={interaction}
              participants={participants}
              busy={busy}
              error={error}
              onOpen={() =>
                void mutate(openKey, (idempotency) =>
                  api.openInteraction(debateId, { idempotency }),
                )
              }
              onClose={() =>
                void mutate(closeKey, (idempotency) =>
                  api.closeInteraction(debateId, { idempotency }),
                )
              }
            />
          ) : null}

          <ReportPanel
            key={`${debateId}-${report?.latest_attempt_status ?? "none"}`}
            debateId={debateId}
            api={api}
            canRegenerate={interaction?.status === "finalized"}
          />

          <TranslationPanel
            batches={batches}
            busy={busy}
            error={error}
            translatedVisible={translationVisible}
            onToggleDisplay={() => setTranslationVisible((value) => !value)}
            onTranslate={() =>
              mutate(translationKey, (idempotency) =>
                api.translateCurrentPublishedContent(debateId, { idempotency }),
              ).then(() => setTranslationVisible(true))
            }
          />

          {transcript ? (
            <HistoryView
              topic={detail.topic}
              transcript={transcript}
              interaction={interaction ?? undefined}
              report={historyReport}
              showTranslated={translationVisible}
            />
          ) : null}
        </>
      )}
    </div>
  );
}

export default TeacherWave3;
