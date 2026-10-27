"use client";

import type { DebateSummary } from "../../lib/api";
import { statusLabel, useT } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { StatusBadge } from "../ui";
import { DEBATE_TAG, DEBATE_TAG_TONE } from "./debate-chrome";

/**
 * `pill` draws the Debates-list tag (final mockup F); without it the badge
 * keeps the shared status-badge look used elsewhere (Immerse stage).
 */
export function DebateStatus({
  debate,
  pill = false,
}: {
  debate: DebateSummary;
  pill?: boolean;
}) {
  const t = useT();
  const pillClass = (tone: keyof typeof DEBATE_TAG_TONE) =>
    cn(DEBATE_TAG, DEBATE_TAG_TONE[tone]);
  if (debate.stall && ["draft", "running"].includes(debate.status)) {
    const reason = t("debateStalledReason")
      .replace("{round}", String(debate.stall.round_no))
      .replace("{code}", debate.stall.safe_error_code);
    return (
      <span
        className={pill ? pillClass("stalled") : "status-badge status-bad"}
        data-prewarm="stalled"
        data-ui-guide="debate.stalled"
        data-ui-guide-text={reason}
        tabIndex={0}
      >
        <span aria-hidden="true" />
        {t("debateStalled")}
      </span>
    );
  }
  if (debate.status !== "draft")
    return pill ? (
      <span
        className={pillClass(
          debate.status === "running" ? "running" : "completed",
        )}
      >
        {statusLabel(debate.status)}
      </span>
    ) : (
      <StatusBadge status={debate.status} />
    );
  const prepared = debate.preview?.prepared_turns ?? debate.prepared_turns ?? 0;
  const expected = debate.preview?.expected_turns ?? debate.expected_turns ?? 0;
  const complete = expected > 0 && prepared >= expected;
  return (
    <span
      className={
        pill
          ? pillClass(complete ? "ready" : "thinking")
          : `status-badge ${complete ? "status-good" : "status-warn"}`
      }
      data-prewarm={complete ? "ready" : "thinking"}
    >
      <span aria-hidden="true" />
      {complete ? t("debatePrewarmReady") : `${prepared} / ${expected} turns`}
    </span>
  );
}
