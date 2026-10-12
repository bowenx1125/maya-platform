import type { CSSProperties } from "react";

import { isRed, rankLabel, type Card } from "../../lib/poker/cards";
import { PixelText } from "./pixel-text";
import styles from "./card-table.module.css";

const SUIT_GLYPH = { s: "♠", h: "♥", d: "♦", c: "♣" } as const;
const SUIT_NAME = {
  s: "spades",
  h: "hearts",
  d: "diamonds",
  c: "clubs",
} as const;

/**
 * One card. `order` staggers the deal and gives each card its own drift, so a
 * row of them never bobs in step.
 */
export function PlayingCard({
  card,
  faceDown = false,
  order = 0,
  small = false,
}: {
  card?: Card;
  faceDown?: boolean;
  order?: number;
  small?: boolean;
}) {
  const style = {
    "--order": order,
    "--tilt": `${((order * 37) % 5) - 2}deg`,
  } as CSSProperties;
  const className = `${styles.card} ${small ? styles.cardSmall : ""}`;
  if (!card || faceDown)
    return (
      <span
        className={`${className} ${styles.cardBack}`}
        style={style}
        role="img"
        aria-label="Face-down card"
      />
    );
  return (
    <span
      // A new key per face makes a card that turns over mount again and flip.
      key={`${card.rank}${card.suit}`}
      className={`${className} ${isRed(card.suit) ? styles.suitRed : styles.suitBlack}`}
      style={style}
      role="img"
      aria-label={`${rankLabel(card.rank)} of ${SUIT_NAME[card.suit]}`}
    >
      <span className={styles.corner} aria-hidden="true">
        <PixelText text={rankLabel(card.rank)} scale={small ? 2 : 3} />
        <PixelText text={SUIT_GLYPH[card.suit]} scale={small ? 1 : 2} />
      </span>
      <span className={styles.pip} aria-hidden="true">
        <PixelText text={SUIT_GLYPH[card.suit]} scale={small ? 3 : 5} />
      </span>
    </span>
  );
}
