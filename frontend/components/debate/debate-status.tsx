"use client";

import type { DebateSummary } from "../../lib/api";
import { useT } from "../locale";
import { StatusBadge } from "../ui";

export function DebateStatus({ debate }: { debate: DebateSummary }) {
  const t = useT();
  if (debate.stall && ["draft", "running"].includes(debate.status)) {
    return (
      <span
        className="status-badge status-bad"
        data-prewarm="stalled"
        title={t("debateStalledReason")
          .replace("{round}", String(debate.stall.round_no))
          .replace("{code}", debate.stall.safe_error_code)}
      >
        <span aria-hidden="true" />
        {t("debateStalled")}
      </span>
    );
  }
  if (debate.status !== "draft") return <StatusBadge status={debate.status} />;
  const prepared = debate.preview?.prepared_turns ?? debate.prepared_turns ?? 0;
  const expected = debate.preview?.expected_turns ?? debate.expected_turns ?? 0;
  const complete = expected > 0 && prepared >= expected;
  return (
    <span
      className={`status-badge ${complete ? "status-good" : "status-warn"}`}
      data-prewarm={complete ? "ready" : "thinking"}
    >
      <span aria-hidden="true" />
      {complete ? t("debatePrewarmReady") : `${prepared} / ${expected} turns`}
    </span>
  );
}
