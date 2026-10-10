"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  PlatformApiError,
  type CardRoom,
  type CardRoomAction,
} from "../../lib/api/platform";
import { bestHand, handName } from "../../lib/poker/hand";
import type { Action } from "../../lib/poker/table";
import { useSession } from "../session-provider";
import { PixelText } from "./pixel-text";
import { PlayingCard } from "./playing-card";
import { ActionBar, Felt, type SeatView } from "./table-parts";
import styles from "./card-table.module.css";

const POLL_MS = 1000;
// A hidden tab still keeps its seat, just checks in less often.
const HIDDEN_POLL_MS = 4000;
const SEATS = 6;

function explain(caught: unknown): string {
  if (caught instanceof PlatformApiError) {
    if (caught.code === "not_found") return "No open room has that code.";
    if (caught.code === "card_room_full") return "That table is full.";
    if (caught.code === "card_room_needs_players")
      return "A hand needs two players with chips.";
    return caught.message;
  }
  return "The table could not be reached. Try again.";
}

/** Open a room for your classmates, or sit down at theirs by its code. */
export function OnlineLobby({ onLeave }: { onLeave: () => void }) {
  const { api } = useSession();
  const [room, setRoom] = useState<CardRoom | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function enter(task: () => Promise<CardRoom>) {
    setBusy(true);
    setError(null);
    try {
      setRoom(await task());
    } catch (caught) {
      setError(explain(caught));
    } finally {
      setBusy(false);
    }
  }

  if (room)
    return (
      <OnlineTable
        initial={room}
        onLeave={() => {
          setRoom(null);
          setCode("");
        }}
      />
    );

  return (
    <div className={styles.menu}>
      <PixelText className={styles.menuTitle} text="Play online" scale={5} />
      <div className={styles.menuChoices}>
        <button
          type="button"
          className={`${styles.button} ${styles.green} ${styles.menuChoice}`}
          disabled={busy}
          onClick={() => void enter(() => api.createCardRoom())}
        >
          <span className={styles.menuFan} aria-hidden="true">
            <PlayingCard faceDown order={0} />
            <PlayingCard card={{ rank: 10, suit: "c" }} order={1} />
            <PlayingCard faceDown order={2} />
          </span>
          <PixelText text="New room" scale={4} />
        </button>
        <form
          className={`${styles.joinPanel} ${styles.menuChoice}`}
          onSubmit={(event) => {
            event.preventDefault();
            if (code.length === 4) void enter(() => api.joinCardRoom(code));
          }}
        >
          <PixelText text="Room code" scale={3} />
          <label className={styles.code}>
            <input
              className={styles.codeInput}
              aria-label="Room code"
              inputMode="numeric"
              autoComplete="off"
              pattern="[0-9]{4}"
              maxLength={4}
              value={code}
              onChange={(event) =>
                setCode(event.target.value.replace(/\D/g, "").slice(0, 4))
              }
            />
            <span className={styles.codeCells} aria-hidden="true">
              {Array.from({ length: 4 }, (_, index) => (
                <span
                  key={index}
                  className={styles.codeCell}
                  data-next={index === code.length ? "" : undefined}
                >
                  {code[index] ? (
                    <PixelText text={code[index]} scale={5} />
                  ) : null}
                </span>
              ))}
            </span>
          </label>
          <button
            type="submit"
            className={`${styles.button} ${styles.blue}`}
            disabled={busy || code.length !== 4}
          >
            <PixelText text="Sit down" scale={3} />
          </button>
        </form>
      </div>
      {error ? (
        <p className={styles.notice} role="alert">
          {error}
        </p>
      ) : null}
      <button
        type="button"
        className={`${styles.button} ${styles.grey}`}
        onClick={onLeave}
      >
        <PixelText text="Back" scale={3} />
      </button>
    </div>
  );
}

/** A table of classmates. Everyone polls; the server deals and keeps time. */
export function OnlineTable({
  initial,
  onLeave,
}: {
  initial: CardRoom;
  onLeave: () => void;
}) {
  const { api } = useSession();
  const code = initial.code;
  const [room, setRoom] = useState(initial);
  const [closed, setClosed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Time is kept on the server's clock, so a countdown here matches
  // everyone else's whatever this computer's clock says.
  const [now, setNow] = useState(() => Date.parse(initial.now));
  const skew = useRef(0);

  const receive = useCallback((next: CardRoom) => {
    skew.current = Date.parse(next.now) - Date.now();
    setNow(Date.parse(next.now));
    // A slow poll can come back after a newer move; keep the newer table.
    setRoom((current) => (next.revision >= current.revision ? next : current));
  }, []);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await api.cardRoom(code);
        if (!active) return;
        receive(next);
        setError(null);
      } catch (caught) {
        if (!active) return;
        if (caught instanceof PlatformApiError && caught.status === 404) {
          setClosed(true);
          return;
        }
        setError("Reconnecting...");
      }
      timer = window.setTimeout(
        poll,
        document.hidden ? HIDDEN_POLL_MS : POLL_MS,
      );
    };
    timer = window.setTimeout(poll, POLL_MS);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [api, code, receive]);

  // Countdowns tick between polls.
  useEffect(() => {
    skew.current = Date.parse(initial.now) - Date.now();
    const timer = window.setInterval(
      () => setNow(Date.now() + skew.current),
      250,
    );
    return () => window.clearInterval(timer);
  }, [initial.now]);

  async function run(task: () => Promise<CardRoom>) {
    setBusy(true);
    try {
      receive(await task());
      setError(null);
    } catch (caught) {
      // The table moved on under you; the next poll shows where it is now.
      if (!(
        caught instanceof PlatformApiError && caught.code === "stale_revision"
      ))
        setError(explain(caught));
    } finally {
      setBusy(false);
    }
  }

  async function leave() {
    setBusy(true);
    await api.leaveCardRoom(code).catch(() => undefined);
    onLeave();
  }

  if (closed)
    return (
      <div className={styles.menu}>
        <PixelText className={styles.menuTitle} text="Room closed" scale={5} />
        <button
          type="button"
          className={`${styles.button} ${styles.grey}`}
          onClick={onLeave}
        >
          <PixelText text="Back" scale={3} />
        </button>
      </div>
    );

  const secondsUntil = (moment: string | null | undefined) =>
    moment ? Math.max(0, Math.ceil((Date.parse(moment) - now) / 1000)) : null;
  const between = room.street === "waiting" || room.street === "complete";
  const started = room.status === "playing";
  const you = room.you ?? null;
  const mine = you === null ? null : room.seats[you];
  const isHost = mine?.host ?? false;
  const funded = room.seats.filter((seat) => seat.stack > 0).length;
  const turnLeft = secondsUntil(room.deadline);
  const nextIn = secondsUntil(room.next_hand_at);

  const winners = room.payouts.flatMap((payout) => {
    const seat = room.seats.find((seat) => seat.user_id === payout.user_id);
    return seat
      ? [
          {
            id: seat.user_id,
            name: seat.name,
            amount: payout.amount,
            hand: payout.hand ?? null,
          },
        ]
      : [];
  });
  // Your seat at the bottom of the rail, everyone else on round from it.
  const rail = room.seats.map(
    (_, index) => room.seats[((you ?? 0) + index) % room.seats.length],
  );
  const seats: SeatView[] = rail.map((seat) => {
    const index = room.seats.indexOf(seat);
    const turn = room.to_act === index;
    return {
      id: seat.user_id,
      name: seat.name,
      avatar: seat.avatar,
      stack: seat.stack,
      bet: seat.bet,
      out: seat.folded || seat.sitting_out || seat.leaving,
      lastAction: seat.last_action ?? null,
      cards: seat.hole.length
        ? seat.hole
        : Array.from({ length: seat.hole_count }, () => null),
      mine: index === you,
      dealer: room.button === index,
      turn,
      winner: between && winners.some((winner) => winner.id === seat.user_id),
      note:
        turn && turnLeft !== null
          ? String(turnLeft)
          : seat.leaving
            ? "Leaving"
            : !started && seat.host
              ? "Host"
              : undefined,
    };
  });
  const yourCards = mine ? [...mine.hole, ...room.board] : [];
  const yourHand =
    yourCards.length >= 5 && !between ? handName(bestHand(yourCards)) : null;

  function play(action: Action) {
    const body: CardRoomAction = {
      type: action.type,
      to: action.type === "raise" ? action.to : null,
      expected_revision: room.revision,
    };
    void run(() => api.actInCardRoom(code, body));
  }

  return (
    <div className={styles.layout}>
      <header className={styles.topbar}>
        <button
          type="button"
          className={`${styles.button} ${styles.grey}`}
          disabled={busy}
          onClick={() => void leave()}
        >
          <PixelText text="Leave" scale={2} />
        </button>
        <PixelText
          className={styles.title}
          text={
            room.hand_number
              ? `Room ${code} · Hand ${room.hand_number} · Blinds ${room.small_blind}/${room.big_blind}`
              : `Room ${code}`
          }
          scale={2}
        />
        <span className={styles.topActions}>
          {mine ? (
            <button
              type="button"
              className={`${styles.button} ${styles.green}`}
              disabled={busy || !between || mine.stack > 0}
              data-urgent={between && mine.stack === 0 ? "" : undefined}
              onClick={() => void run(() => api.rebuyInCardRoom(code))}
            >
              <PixelText text="Rebuy" scale={2} />
            </button>
          ) : null}
        </span>
      </header>

      <Felt
        handNumber={room.hand_number}
        board={room.board}
        pot={room.pot}
        winners={winners}
        between={between}
        seats={seats}
      >
        {started ? (
          funded < 2 ? (
            <PixelText
              className={styles.waiting}
              text="Waiting for players"
              scale={3}
            />
          ) : null
        ) : (
          <div className={styles.lobbyCenter}>
            <PixelText text="Room code" scale={2} />
            <PixelText className={styles.roomCode} text={code} scale={8} />
            <PixelText
              text={`${room.seats.length}/${SEATS} seated`}
              scale={2}
            />
          </div>
        )}
      </Felt>

      <footer className={styles.controls}>
        {error ? (
          <p className={styles.notice} role="alert">
            {error}
          </p>
        ) : null}
        {yourHand ? (
          <PixelText className={styles.handName} text={yourHand} scale={3} />
        ) : null}
        {room.legal ? (
          <ActionBar
            legal={{
              canCheck: room.legal.can_check,
              toCall: room.legal.to_call,
              canRaise: room.legal.can_raise,
              minRaiseTo: room.legal.min_raise_to,
              maxRaiseTo: room.legal.max_raise_to,
            }}
            currentBet={room.current_bet}
            bigBlind={room.big_blind}
            disabled={busy}
            onAct={play}
          />
        ) : !mine ? (
          <button
            type="button"
            className={`${styles.button} ${styles.blue} ${styles.deal}`}
            disabled={busy || room.seats.length >= SEATS}
            onClick={() => void run(() => api.joinCardRoom(code))}
          >
            <PixelText text="Sit down" scale={4} />
          </button>
        ) : !started ? (
          isHost ? (
            <button
              type="button"
              className={`${styles.button} ${styles.orange} ${styles.deal}`}
              disabled={busy || funded < 2}
              onClick={() => void run(() => api.startCardRoom(code))}
            >
              <PixelText text="Deal" scale={4} />
            </button>
          ) : (
            <PixelText
              className={styles.waiting}
              text="Waiting for the host"
              scale={3}
            />
          )
        ) : between && nextIn !== null ? (
          <PixelText
            className={styles.waiting}
            text={`Next hand in ${nextIn}`}
            scale={3}
          />
        ) : (
          <PixelText className={styles.waiting} text="..." scale={4} />
        )}
      </footer>
    </div>
  );
}
