"use client";

import { useState } from "react";

import type { Player } from "../../lib/poker/table";
import { CardTable } from "./card-table";
import { JestersTable } from "./jesters-table";
import { PixelText } from "./pixel-text";
import { PlayingCard } from "./playing-card";
import styles from "./card-table.module.css";

/** The room behind the door: pick a table, or leave. */
export function CardRoom({
  players,
  onLeave,
}: {
  players: Player[];
  onLeave: () => void;
}) {
  const [table, setTable] = useState<"menu" | "holdem" | "jesters">("menu");
  if (table === "holdem")
    return <CardTable players={players} onLeave={() => setTable("menu")} />;
  if (table === "jesters")
    return <JestersTable onLeave={() => setTable("menu")} />;
  return (
    <div className={styles.menu}>
      <PixelText className={styles.menuTitle} text="The card room" scale={5} />
      <div className={styles.menuChoices}>
        <button
          type="button"
          className={`${styles.button} ${styles.blue} ${styles.menuChoice}`}
          onClick={() => setTable("holdem")}
        >
          <span className={styles.menuFan} aria-hidden="true">
            <PlayingCard card={{ rank: 14, suit: "s" }} order={0} />
            <PlayingCard card={{ rank: 13, suit: "h" }} order={1} />
            <PlayingCard faceDown order={2} />
          </span>
          <PixelText text="Hold'em" scale={4} />
        </button>
        <button
          type="button"
          className={`${styles.button} ${styles.red} ${styles.menuChoice}`}
          onClick={() => setTable("jesters")}
        >
          <span className={styles.menuFan} aria-hidden="true">
            <PlayingCard card={{ rank: 12, suit: "d" }} order={3} />
            <PlayingCard card={{ rank: 7, suit: "c" }} order={4} />
            <PlayingCard card={{ rank: 2, suit: "h" }} order={5} />
          </span>
          <PixelText text="Jesters" scale={4} />
        </button>
      </div>
      <button
        type="button"
        className={`${styles.button} ${styles.grey}`}
        onClick={onLeave}
      >
        <PixelText text="Leave" scale={3} />
      </button>
    </div>
  );
}
