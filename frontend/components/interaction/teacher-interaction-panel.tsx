"use client";

import { useEffect, useRef, useState } from "react";

import { statusLabel } from "../../lib/i18n";
import { useLocale } from "../locale";
import { QrCode } from "./qr-code";
import type { TeacherInteractionPanelProps } from "./types";
import styles from "./interaction.module.css";

export function TeacherInteractionPanel({
  debateId,
  interaction,
  participants,
  busy = false,
  error = null,
  onOpen,
  onClose,
}: TeacherInteractionPanelProps) {
  const { locale, t } = useLocale();
  const participantById = new Map(
    participants.map((participant) => [participant.id, participant]),
  );
  const totalVotes = interaction.votes.reduce(
    (total, vote) => total + vote.count,
    0,
  );
  const title =
    interaction.status === "closed"
      ? t("interactionTitleClosed")
      : interaction.status === "open"
        ? t("interactionTitleOpen")
        : t("interactionTitleFinalized");

  return (
    <section
      className={styles.teacherPanel}
      data-debate-id={debateId}
      data-interaction-status={interaction.status}
    >
      <div className={styles.panelHeader}>
        <div>
          <span className={styles.eyebrow}>{t("interactionEyebrow")}</span>
          <h2>{title}</h2>
          <p>{t("interactionBoundary")}</p>
        </div>
        <span className={styles.status} data-status={interaction.status}>
          {statusLabel(interaction.status, locale)}
        </span>
      </div>

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}

      {interaction.status === "closed" ? (
        <div className={styles.actionRow}>
          <button
            className={styles.primaryButton}
            type="button"
            disabled={busy}
            onClick={onOpen}
          >
            {busy ? t("interactionOpening") : t("interactionOpen")}
          </button>
          <p className={styles.helper}>{t("interactionAvailability")}</p>
        </div>
      ) : null}

      {interaction.status === "open" ? (
        <div className={styles.openLayout}>
          <div className={styles.qrColumn}>
            {interaction.public_url ? (
              <QrCode
                value={interaction.public_url}
                label={t("interactionScan")}
              />
            ) : null}
            <button
              className={styles.secondaryButton}
              type="button"
              disabled={busy}
              onClick={onClose}
            >
              {busy ? t("interactionClosing") : t("interactionClose")}
            </button>
          </div>
          <BarrageFeed barrages={interaction.barrages} />
          <InteractionTotals
            votes={interaction.votes}
            totalVotes={totalVotes}
            participantById={participantById}
          />
        </div>
      ) : null}

      {interaction.status === "finalized" ? (
        <div className={styles.openLayout}>
          <InteractionTotals
            votes={interaction.votes}
            totalVotes={totalVotes}
            participantById={participantById}
          />
          <BarrageFeed barrages={interaction.barrages} />
        </div>
      ) : null}
    </section>
  );
}

function InteractionTotals({
  votes,
  totalVotes,
  participantById,
}: {
  votes: TeacherInteractionPanelProps["interaction"]["votes"];
  totalVotes: number;
  participantById: Map<string, { name: string; slot: string }>;
}) {
  const { t } = useLocale();
  return (
    <div className={styles.totals}>
      <div className={styles.sectionHeading}>
        <span>{t("interactionLiveVote")}</span>
        <strong>{totalVotes}</strong>
      </div>
      <div className={styles.voteList}>
        {votes.map((vote) => {
          const participant = participantById.get(vote.participant_id);
          return (
            <div className={styles.voteRow} key={vote.participant_id}>
              <div>
                <strong>
                  {participant?.slot ?? "?"} ·{" "}
                  {participant?.name ?? vote.participant_id}
                </strong>
                <span>{vote.percentage.toFixed(1)}%</span>
              </div>
              <div className={styles.voteTrack}>
                <span style={{ width: `${Math.min(100, vote.percentage)}%` }} />
              </div>
              <b>{vote.count}</b>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function BarrageFeed({
  barrages,
}: {
  barrages: TeacherInteractionPanelProps["interaction"]["barrages"];
}) {
  const { locale, t } = useLocale();
  const feedRef = useRef<HTMLDivElement>(null);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    const feed = feedRef.current;
    const reduceMotion =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!feed || barrages.length < 2 || reduceMotion) {
      return;
    }
    const timer = window.setInterval(() => {
      if (paused || feed.scrollHeight <= feed.clientHeight) return;
      const next = feed.scrollTop + 1;
      feed.scrollTop = next >= feed.scrollHeight - feed.clientHeight ? 0 : next;
    }, 80);
    return () => window.clearInterval(timer);
  }, [barrages.length, paused]);

  return (
    <div className={styles.barragePanel}>
      <div className={styles.sectionHeading}>
        <span>{t("interactionRawBarrages")}</span>
        <strong>{barrages.length}</strong>
      </div>
      <div
        ref={feedRef}
        className={styles.barrageFeed}
        aria-live="polite"
        aria-label={t("interactionRawBarrages")}
        tabIndex={0}
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
        onFocus={() => setPaused(true)}
        onBlur={() => setPaused(false)}
      >
        {barrages.length === 0 ? (
          <p className={styles.empty}>{t("interactionNoMessages")}</p>
        ) : (
          barrages.map((barrage) => (
            <article className={styles.barrage} key={barrage.id}>
              <div>
                <strong>{barrage.nickname}</strong>
                <time dateTime={barrage.submitted_at}>#{barrage.sequence}</time>
              </div>
              <p>{barrage.raw_text}</p>
            </article>
          ))
        )}
      </div>
    </div>
  );
}
