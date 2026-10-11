"use client";

import { useState, type CSSProperties, type ReactNode } from "react";

import type { Card } from "../../lib/poker/cards";
import type { Action, LegalActions } from "../../lib/poker/table";
import { UserAvatar } from "../user-avatar";
import { PixelText } from "./pixel-text";
import { PlayingCard } from "./playing-card";
import styles from "./card-table.module.css";

/** One seat as drawn: training and online tables both describe theirs this way. */
export type SeatView = {
  id: string;
  name: string;
  avatar?: string | null;
  stack: number;
  bet: number;
  /** Folded, sitting out, or on the way out. */
  out: boolean;
  lastAction: string | null;
  /** A card shown face up, or `null` for one dealt face down. */
  cards: readonly (Card | null)[];
  /** The viewer's own seat: bottom of the rail, full-size cards. */
  mine: boolean;
  dealer: boolean;
  turn: boolean;
  winner: boolean;
  /** A word on the seat's plate: the turn's seconds left, or who is hosting. */
  note?: string;
};

export type Winner = {
  id: string;
  name: string;
  amount: number;
  hand: string | null;
};

/** Where each other seat sits on the rail, as an arc over the top, left to right. */
const SPREAD: Record<number, number> = { 1: 0, 2: 110, 3: 150, 4: 190, 5: 210 };
function seatPosition(index: number, others: number): CSSProperties {
  // The viewer is seat 0 at the bottom; the rest follow clockwise, which on
  // screen runs up the left rail, over the top and down the right.
  const angle =
    index === 0
      ? 90
      : 270 -
        (SPREAD[others] ?? 210) / 2 +
        (others === 1
          ? 0
          : ((index - 1) * (SPREAD[others] ?? 210)) / (others - 1));
  const radians = (angle * Math.PI) / 180;
  return {
    left: `${50 + 47 * Math.cos(radians)}%`,
    top: `${50 + 46 * Math.sin(radians)}%`,
  };
}

function Chip({ amount }: { amount: number }) {
  return (
    <span className={styles.bet}>
      <span className={styles.chip} aria-hidden="true" />
      <PixelText text={String(amount)} scale={2} />
    </span>
  );
}

/** The felt: board and pot in the middle, the seats round the rail. */
export function Felt({
  handNumber,
  board,
  pot,
  winners,
  between,
  seats,
  children,
}: {
  handNumber: number;
  board: readonly Card[];
  pot: number;
  winners: readonly Winner[];
  between: boolean;
  /** In rail order, the viewer's seat first. */
  seats: readonly SeatView[];
  /** Shown in the middle when there is no pot or result to show. */
  children?: ReactNode;
}) {
  const others = seats.length - 1;
  return (
    <div className={styles.felt}>
      <div className={styles.center}>
        <div className={styles.board} aria-label="Board">
          {Array.from({ length: 5 }, (_, index) =>
            board[index] ? (
              <PlayingCard
                key={`${handNumber}-${index}`}
                card={board[index]}
                order={index}
              />
            ) : (
              <span key={index} className={styles.slot} aria-hidden="true" />
            ),
          )}
        </div>
        {/* Under the board, not over it: at a showdown the board is the
            reason someone won. */}
        {between && winners.length ? (
          <div className={styles.banner} role="status">
            {winners.map((winner) => (
              <div key={winner.id} className={styles.bannerLine}>
                <PixelText
                  text={`${winner.name} wins ${winner.amount}`}
                  scale={4}
                />
                {winner.hand ? (
                  <PixelText
                    className={styles.handName}
                    text={winner.hand}
                    scale={3}
                  />
                ) : null}
              </div>
            ))}
          </div>
        ) : pot > 0 ? (
          <PixelText className={styles.pot} text={`Pot ${pot}`} scale={3} />
        ) : (
          children
        )}
      </div>

      {seats.map((seat, index) => (
        <div
          key={seat.id}
          className={styles.seat}
          style={seatPosition(index, others)}
          data-turn={seat.turn ? "" : undefined}
          data-folded={seat.out ? "" : undefined}
          data-winner={seat.winner ? "" : undefined}
        >
          <div className={styles.hole}>
            {seat.cards.map((card, order) => (
              <PlayingCard
                key={`${handNumber}-${order}-${card ? "up" : "down"}`}
                card={card ?? undefined}
                faceDown={!card}
                order={order + index * 2}
                small={!seat.mine}
              />
            ))}
          </div>
          <div className={styles.plate}>
            <span className={styles.avatar}>
              <UserAvatar
                avatar={seat.avatar}
                name={seat.name}
                userId={seat.id}
                size="sm"
              />
              {seat.dealer ? (
                <span className={styles.dealer} aria-label="Dealer">
                  <PixelText text="D" scale={2} />
                </span>
              ) : null}
            </span>
            <span className={styles.who}>
              <PixelText className={styles.name} text={seat.name} scale={2} />
              <PixelText
                className={styles.stack}
                text={String(seat.stack)}
                scale={2}
              />
            </span>
            {seat.note ? (
              <PixelText className={styles.note} text={seat.note} scale={2} />
            ) : null}
          </div>
          {seat.lastAction && !between ? (
            <PixelText
              key={`${handNumber}-${seat.lastAction}-${seat.bet}`}
              className={styles.said}
              text={seat.lastAction}
              scale={2}
            />
          ) : null}
          {seat.bet > 0 ? <Chip amount={seat.bet} /> : null}
        </div>
      ))}
    </div>
  );
}

/** Fold, check or call, and a raise you size in big blinds. */
export function ActionBar({
  legal,
  currentBet,
  bigBlind,
  disabled = false,
  onAct,
}: {
  legal: LegalActions;
  currentBet: number;
  bigBlind: number;
  disabled?: boolean;
  onAct: (action: Action) => void;
}) {
  const [raise, setRaise] = useState<number | null>(null);
  const raiseTo = Math.min(
    legal.maxRaiseTo,
    Math.max(legal.minRaiseTo, raise ?? 0),
  );
  function play(action: Action) {
    setRaise(null);
    onAct(action);
  }
  return (
    <div className={styles.actions}>
      <button
        type="button"
        className={`${styles.button} ${styles.red}`}
        disabled={disabled}
        onClick={() => play({ type: "fold" })}
      >
        <PixelText text="Fold" scale={3} />
      </button>
      <button
        type="button"
        className={`${styles.button} ${styles.blue}`}
        disabled={disabled}
        onClick={() =>
          play(legal.canCheck ? { type: "check" } : { type: "call" })
        }
      >
        <PixelText
          text={legal.canCheck ? "Check" : `Call ${legal.toCall}`}
          scale={3}
        />
      </button>
      {legal.canRaise ? (
        <span className={styles.raise}>
          <button
            type="button"
            className={`${styles.button} ${styles.small}`}
            aria-label="Less"
            disabled={disabled || raiseTo <= legal.minRaiseTo}
            onClick={() => setRaise(raiseTo - bigBlind)}
          >
            <PixelText text="-" scale={3} />
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.orange}`}
            disabled={disabled}
            onClick={() => play({ type: "raise", to: raiseTo })}
          >
            <PixelText
              text={
                raiseTo === legal.maxRaiseTo
                  ? "All in"
                  : `${currentBet ? "Raise" : "Bet"} ${raiseTo}`
              }
              scale={3}
            />
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.small}`}
            aria-label="More"
            disabled={disabled || raiseTo >= legal.maxRaiseTo}
            onClick={() => setRaise(raiseTo + bigBlind)}
          >
            <PixelText text="+" scale={3} />
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.purple}`}
            disabled={disabled}
            onClick={() => setRaise(legal.maxRaiseTo)}
          >
            <PixelText text="Max" scale={2} />
          </button>
        </span>
      ) : null}
    </div>
  );
}
