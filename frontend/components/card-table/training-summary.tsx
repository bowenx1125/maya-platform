"use client";

import { summarize, type HandRecord } from "../../lib/poker/training";
import { PixelText } from "./pixel-text";
import { PlayingCard } from "./playing-card";
import styles from "./card-table.module.css";

const percent = (value: number | null) =>
  value === null ? "-" : `${Math.round(value * 100)}%`;

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.stat}>
      <PixelText text={value} scale={4} />
      <span className={styles.jLabel}>{label}</span>
    </div>
  );
}

function Notable({ label, record }: { label: string; record: HandRecord }) {
  return (
    <div className={styles.notable}>
      <span className={styles.jLabel}>{label}</span>
      <span className={styles.notableCards}>
        {record.hole.map((card, index) => (
          <PlayingCard key={index} card={card} order={index} small />
        ))}
      </span>
      <PixelText
        className={record.net > 0 ? styles.jGold : styles.jRed}
        text={`${record.net > 0 ? "+" : ""}${record.net}`}
        scale={3}
      />
    </div>
  );
}

/** The end of a practice session: how it went, and what to change next time. */
export function TrainingSummary({
  records,
  onAgain,
  onLeave,
}: {
  records: HandRecord[];
  onAgain: () => void;
  onLeave: () => void;
}) {
  const summary = summarize(records);
  return (
    <div className={styles.summary}>
      <PixelText className={styles.menuTitle} text="Session" scale={5} />
      <div className={styles.summaryGrid}>
        <Stat label="Hands" value={String(summary.hands)} />
        <Stat
          label="Net"
          value={`${summary.net > 0 ? "+" : ""}${summary.net}`}
        />
        <Stat label="Played" value={percent(summary.vpip)} />
        <Stat label="Raised" value={percent(summary.pfr)} />
        <Stat label="Folded to bets" value={percent(summary.foldToBet)} />
        <Stat label="Showdowns won" value={percent(summary.showdownWin)} />
      </div>
      {summary.best || summary.worst ? (
        <div className={styles.notables}>
          {summary.best ? <Notable label="Best" record={summary.best} /> : null}
          {summary.worst ? (
            <Notable label="Worst" record={summary.worst} />
          ) : null}
        </div>
      ) : null}
      {summary.tips.length ? (
        <ul className={styles.tips} aria-label="Tips">
          {summary.tips.map((tip) => (
            <li key={tip}>{tip}</li>
          ))}
        </ul>
      ) : null}
      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.button} ${styles.orange}`}
          onClick={onAgain}
        >
          <PixelText text="Again" scale={3} />
        </button>
        <button
          type="button"
          className={`${styles.button} ${styles.grey}`}
          onClick={onLeave}
        >
          <PixelText text="Leave" scale={3} />
        </button>
      </div>
    </div>
  );
}
