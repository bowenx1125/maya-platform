"use client";

import { useEffect, useState, type CSSProperties } from "react";

import { decide } from "../../lib/poker/bot";
import {
  act,
  addChips,
  createTable,
  describeHand,
  legalActions,
  pot,
  startHand,
  type Action,
  type Player,
} from "../../lib/poker/table";
import { UserAvatar } from "../user-avatar";
import { PixelText } from "./pixel-text";
import { PlayingCard } from "./playing-card";
import styles from "./card-table.module.css";

const STACK = 1000;
const TOP_UP = 500;

/** Where each other seat sits on the rail, as an arc over the top, left to right. */
const SPREAD: Record<number, number> = { 1: 0, 2: 110, 3: 150, 4: 190, 5: 210 };
function seatPosition(index: number, others: number): CSSProperties {
  // The human is seat 0 at the bottom; the rest follow clockwise, which on
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

export function CardTable({
  players,
  onLeave,
}: {
  players: Player[];
  onLeave: () => void;
}) {
  const [table, setTable] = useState(() =>
    createTable(players, { stack: STACK, smallBlind: 10, bigBlind: 20 }),
  );
  const [raise, setRaise] = useState<number | null>(null);
  const human = table.seats.findIndex((seat) => seat.human);
  const humanSeat = table.seats[human];
  const humanTurn = table.toAct === human;
  const legal = humanTurn ? legalActions(table) : null;
  const raiseTo = legal
    ? Math.min(legal.maxRaiseTo, Math.max(legal.minRaiseTo, raise ?? 0))
    : 0;
  const between = table.street === "waiting" || table.street === "complete";

  // Computer players think for a moment, so a hand reads as people playing.
  useEffect(() => {
    if (table.toAct === null || table.seats[table.toAct].human) return;
    const timer = window.setTimeout(
      () =>
        setTable((current) =>
          current.toAct === null || current.seats[current.toAct].human
            ? current
            : act(current, decide(current)),
        ),
      650 + Math.random() * 500,
    );
    return () => window.clearTimeout(timer);
  }, [table]);

  function play(action: Action) {
    setTable((current) => act(current, action));
    setRaise(null);
  }

  function deal() {
    setTable((current) => {
      let next = current;
      // Busted computer players buy back in so the table never empties.
      for (const seat of next.seats)
        if (!seat.human && seat.stack === 0)
          next = addChips(next, seat.id, STACK);
      return startHand(next);
    });
    setRaise(null);
  }

  const winners = table.payouts
    .map((payout) => ({
      ...payout,
      seat: table.seats.find((seat) => seat.id === payout.seatId),
    }))
    .filter((payout) => payout.seat && !payout.seat.folded);
  const others = table.seats.length - 1;
  const humanHand = humanSeat ? describeHand(humanSeat, table.board) : null;
  const canDeal =
    between &&
    table.seats.filter((seat) => seat.human || seat.stack > 0).length >= 2 &&
    (humanSeat?.stack ?? 0) > 0;

  return (
    <div className={styles.layout}>
      <header className={styles.topbar}>
        <button
          type="button"
          className={`${styles.button} ${styles.grey}`}
          onClick={onLeave}
        >
          <PixelText text="Leave" scale={2} />
        </button>
        <PixelText
          className={styles.title}
          text={
            table.handNumber
              ? `Hand ${table.handNumber} · Blinds ${table.smallBlind}/${table.bigBlind}`
              : "Mayaform Hold'em"
          }
          scale={2}
        />
        <button
          type="button"
          className={`${styles.button} ${styles.green}`}
          disabled={!between}
          data-urgent={humanSeat && humanSeat.stack === 0 ? "" : undefined}
          onClick={() =>
            setTable((current) => addChips(current, humanSeat.id, TOP_UP))
          }
        >
          <PixelText text={`+${TOP_UP} chips`} scale={2} />
        </button>
      </header>

      <div className={styles.felt}>
        <div className={styles.center}>
          <div className={styles.board} aria-label="Board">
            {Array.from({ length: 5 }, (_, index) =>
              table.board[index] ? (
                <PlayingCard
                  key={`${table.handNumber}-${index}`}
                  card={table.board[index]}
                  order={index}
                />
              ) : (
                <span key={index} className={styles.slot} aria-hidden="true" />
              ),
            )}
          </div>
          {/* Under the board, not over it: at a showdown the board is the
            reason someone won. */}
          {table.street === "complete" && winners.length ? (
            <div className={styles.banner} role="status">
              {winners.map((winner) => (
                <div key={winner.seatId} className={styles.bannerLine}>
                  <PixelText
                    text={`${winner.seat?.name} wins ${winner.amount}`}
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
          ) : pot(table) > 0 ? (
            <PixelText
              className={styles.pot}
              text={`Pot ${pot(table)}`}
              scale={3}
            />
          ) : null}
        </div>

        {table.seats.map((seat, index) => {
          const reveal = seat.human || (table.showdown && !seat.folded);
          return (
            <div
              key={seat.id}
              className={styles.seat}
              style={seatPosition(index, others)}
              data-turn={table.toAct === index ? "" : undefined}
              data-folded={seat.folded || seat.sittingOut ? "" : undefined}
              data-winner={
                winners.some((w) => w.seatId === seat.id) ? "" : undefined
              }
            >
              <div className={styles.hole}>
                {seat.hole.map((card, order) => (
                  <PlayingCard
                    key={`${table.handNumber}-${order}-${reveal}`}
                    card={card}
                    faceDown={!reveal}
                    order={order + index * 2}
                    small={!seat.human}
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
                  {index === table.button && table.handNumber ? (
                    <span className={styles.dealer} aria-label="Dealer">
                      <PixelText text="D" scale={2} />
                    </span>
                  ) : null}
                </span>
                <span className={styles.who}>
                  <PixelText
                    className={styles.name}
                    text={seat.name}
                    scale={2}
                  />
                  <PixelText
                    className={styles.stack}
                    text={String(seat.stack)}
                    scale={2}
                  />
                </span>
              </div>
              {seat.lastAction && !between ? (
                <PixelText
                  key={`${table.handNumber}-${seat.lastAction}-${seat.bet}`}
                  className={styles.said}
                  text={seat.lastAction}
                  scale={2}
                />
              ) : null}
              {seat.bet > 0 ? <Chip amount={seat.bet} /> : null}
            </div>
          );
        })}
      </div>

      <footer className={styles.controls}>
        {humanHand && !between ? (
          <PixelText className={styles.handName} text={humanHand} scale={3} />
        ) : null}
        {legal ? (
          <div className={styles.actions}>
            <button
              type="button"
              className={`${styles.button} ${styles.red}`}
              onClick={() => play({ type: "fold" })}
            >
              <PixelText text="Fold" scale={3} />
            </button>
            <button
              type="button"
              className={`${styles.button} ${styles.blue}`}
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
                  disabled={raiseTo <= legal.minRaiseTo}
                  onClick={() => setRaise(raiseTo - table.bigBlind)}
                >
                  <PixelText text="-" scale={3} />
                </button>
                <button
                  type="button"
                  className={`${styles.button} ${styles.orange}`}
                  onClick={() => play({ type: "raise", to: raiseTo })}
                >
                  <PixelText
                    text={
                      raiseTo === legal.maxRaiseTo
                        ? "All in"
                        : `${table.currentBet ? "Raise" : "Bet"} ${raiseTo}`
                    }
                    scale={3}
                  />
                </button>
                <button
                  type="button"
                  className={`${styles.button} ${styles.small}`}
                  aria-label="More"
                  disabled={raiseTo >= legal.maxRaiseTo}
                  onClick={() => setRaise(raiseTo + table.bigBlind)}
                >
                  <PixelText text="+" scale={3} />
                </button>
                <button
                  type="button"
                  className={`${styles.button} ${styles.purple}`}
                  onClick={() => setRaise(legal.maxRaiseTo)}
                >
                  <PixelText text="Max" scale={2} />
                </button>
              </span>
            ) : null}
          </div>
        ) : between ? (
          <button
            type="button"
            className={`${styles.button} ${styles.orange} ${styles.deal}`}
            disabled={!canDeal}
            onClick={deal}
          >
            <PixelText
              text={table.handNumber ? "Next hand" : "Deal"}
              scale={4}
            />
          </button>
        ) : (
          <PixelText className={styles.waiting} text="..." scale={4} />
        )}
      </footer>
    </div>
  );
}
