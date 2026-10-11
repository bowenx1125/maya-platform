"use client";

import { useCallback, useEffect, useRef, useState } from "react";

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
  type TableState,
} from "../../lib/poker/table";
import {
  closeHand,
  decision,
  type Decision,
  type HandRecord,
} from "../../lib/poker/training";
import { PixelText } from "./pixel-text";
import { ActionBar, Felt } from "./table-parts";
import { TrainingSummary } from "./training-summary";
import styles from "./card-table.module.css";

// The same blinds and starting stack as an online room, so practice carries over.
const STACK = 4000;
const TOP_UP = 1000;

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
  const [records, setRecords] = useState<HandRecord[]>([]);
  const [ended, setEnded] = useState(false);
  const decisions = useRef<Decision[]>([]);
  const stackBefore = useRef(STACK);
  const closed = useRef(0);
  const human = table.seats.findIndex((seat) => seat.human);
  const humanSeat = table.seats[human];
  const humanTurn = table.toAct === human;
  const legal = humanTurn ? legalActions(table) : null;
  const between = table.street === "waiting" || table.street === "complete";

  const humanId = table.seats[human]?.id;
  // Every change goes through here, so a hand is written into the session's
  // record exactly once, at the moment it finishes.
  const apply = useCallback(
    (next: TableState) => {
      setTable(next);
      if (
        humanId &&
        next.street === "complete" &&
        next.handNumber !== closed.current
      ) {
        closed.current = next.handNumber;
        const record = closeHand(
          next,
          humanId,
          stackBefore.current,
          decisions.current,
        );
        setRecords((now) => [...now, record]);
      }
    },
    [humanId],
  );

  // Computer players think for a moment, so a hand reads as people playing.
  useEffect(() => {
    if (table.toAct === null || table.seats[table.toAct].human) return;
    const timer = window.setTimeout(
      () => apply(act(table, decide(table))),
      650 + Math.random() * 500,
    );
    return () => window.clearTimeout(timer);
  }, [apply, table]);

  function play(action: Action) {
    decisions.current.push(decision(table, action));
    apply(act(table, action));
  }

  function deal() {
    let next = table;
    // Busted computer players buy back in so the table never empties.
    for (const seat of next.seats)
      if (!seat.human && seat.stack === 0)
        next = addChips(next, seat.id, STACK);
    stackBefore.current = humanSeat?.stack ?? 0;
    decisions.current = [];
    apply(startHand(next));
  }

  function again() {
    setTable(
      createTable(players, { stack: STACK, smallBlind: 10, bigBlind: 20 }),
    );
    setRecords([]);
    setEnded(false);
    closed.current = 0;
  }

  if (ended)
    return (
      <TrainingSummary records={records} onAgain={again} onLeave={onLeave} />
    );

  const winners = table.payouts.flatMap((payout) => {
    const seat = table.seats.find((seat) => seat.id === payout.seatId);
    return seat && !seat.folded
      ? [
          {
            id: seat.id,
            name: seat.name,
            amount: payout.amount,
            hand: payout.hand,
          },
        ]
      : [];
  });
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
              : "Training"
          }
          scale={2}
        />
        <span className={styles.topActions}>
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
          <button
            type="button"
            className={`${styles.button} ${styles.purple}`}
            disabled={!between || records.length === 0}
            onClick={() => setEnded(true)}
          >
            <PixelText text="End" scale={2} />
          </button>
        </span>
      </header>

      <Felt
        handNumber={table.handNumber}
        board={table.board}
        pot={pot(table)}
        winners={winners}
        between={between}
        seats={table.seats.map((seat, index) => ({
          id: seat.id,
          name: seat.name,
          avatar: seat.avatar,
          stack: seat.stack,
          bet: seat.bet,
          out: seat.folded || seat.sittingOut,
          lastAction: seat.lastAction,
          // Computer players' cards stay face down until a showdown shows them.
          cards: seat.hole.map((card) =>
            seat.human || (table.showdown && !seat.folded) ? card : null,
          ),
          mine: seat.human,
          dealer: index === table.button && table.handNumber > 0,
          turn: table.toAct === index,
          winner: winners.some((winner) => winner.id === seat.id),
        }))}
      />

      <footer className={styles.controls}>
        {humanHand && !between ? (
          <PixelText className={styles.handName} text={humanHand} scale={3} />
        ) : null}
        {legal ? (
          <ActionBar
            legal={legal}
            currentBet={table.currentBet}
            bigBlind={table.bigBlind}
            onAct={play}
          />
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
