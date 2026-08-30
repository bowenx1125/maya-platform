import type { DebateTranscript, DebateTurn } from "../../lib/api";
import type { EvidenceTraceRow } from "../evidence";

export type HistoryInteraction = {
  status: "closed" | "open" | "finalized";
  votes: {
    participant_id: string;
    count: number;
    percentage: number;
    participant_name?: string;
    slot?: string;
  }[];
  barrages: {
    id: string;
    nickname: string;
    raw_text: string;
    sequence: number;
    submitted_at: string;
  }[];
};

export type ReportRevisionSummary = {
  id: string;
  revision_no: number;
  status: "generating" | "ready" | "failed";
  word_count: number | null;
  safe_error_code: string | null;
  created_at: string;
};

export type ReportRevisionView = ReportRevisionSummary & {
  english_markdown: string | null;
  translated_markdown?: string | null;
};

export type HistoryReport = {
  generation_status: "not_started" | "generating" | "ready" | "failed";
  latest_attempt_status: "not_started" | "generating" | "ready" | "failed";
  current_success_revision: ReportRevisionView | null;
  revisions: ReportRevisionSummary[];
};

export type HistoryTranscript = Omit<DebateTranscript, "turns"> & {
  turns: (DebateTurn & {
    translated_text?: string | null;
    evidence_trace?: EvidenceTraceRow[] | null;
  })[];
};
