"use client";

import { useEffect, useState, type CSSProperties, type ReactNode } from "react";

import {
  BLINDS,
  MAX_JESTERS,
  REROLL_COST,
  buy,
  discard,
  nextBlind,
  newGame,
  play,
  preview,
  reroll,
  sell,
  type GameState,
  type ScoreResult,
} from "../../lib/jesters/game";
import { JESTERS, type Effect, type JesterId } from "../../lib/jesters/jesters";
import { HANDS } from "../../lib/jesters/score";
import { usePrefersReducedMotion } from "../academy/motion";
import { PixelText } from "./pixel-text";
import { PlayingCard } from "./playing-card";
import styles from "./card-table.module.css";

const STEP_MS = 280;
// The sign-in's four pigments, so the jesters belong to the same cast.
const PIGMENTS = ["#8f7bb5", "#c2704f", "#6f9b7d", "#d8a94b"];

type Reveal = {
  result: ScoreResult;
  after: GameState;
  played: number[];
  step: number;
};

function JesterCard({
  id,
  index,
  active,
  children,
}: {
  id: JesterId;
  index: number;
  active?: boolean;
  children?: ReactNode;
}) {
  const jester = JESTERS[id];
  return (
    <div
      className={styles.jester}
      data-active={active ? "" : undefined}
      style={
        { "--pigment": PIGMENTS[index % PIGMENTS.length] } as CSSProperties
      }
      title={jester.text}
    >
      <span className={styles.jesterBand} aria-hidden="true" />
      <PixelText className={styles.jesterName} text={jester.name} scale={2} />
      <span className={styles.jesterText}>{jester.text}</span>
      {children}
    </div>
  );
}

function effectLabel(effect: Effect): string {
  if (effect.times) return `×${effect.times}`;
  if (effect.mult) return `+${effect.mult} Mult`;
  return `+${effect.chips ?? 0}`;
}

function Tally({ chips, mult }: { chips: number; mult: number }) {
  return (
    <div className={styles.tally}>
      <span className={styles.chipsBox}>
        <PixelText text={String(chips)} scale={3} />
      </span>
      <PixelText className={styles.times} text="×" scale={3} />
      <span className={styles.multBox}>
        <PixelText text={String(mult)} scale={3} />
      </span>
    </div>
  );
}

export function JestersTable({ onLeave }: { onLeave: () => void }) {
  const reduced = usePrefersReducedMotion();
  const [game, setGame] = useState(() => newGame());
  const [selected, setSelected] = useState<number[]>([]);
  const [bySuit, setBySuit] = useState(false);
  const [reveal, setReveal] = useState<Reveal | null>(null);

  // The score is counted out one step at a time, then the new state lands.
  useEffect(() => {
    if (!reveal) return;
    const done = reveal.step >= reveal.result.events.length;
    const timer = window.setTimeout(
      () => {
        if (done) {
          setGame(reveal.after);
          setReveal(null);
        } else {
          setReveal(
            (current) => current && { ...current, step: current.step + 1 },
          );
        }
      },
      reduced ? 0 : done ? 900 : STEP_MS,
    );
    return () => window.clearTimeout(timer);
  }, [reveal, reduced]);

  const shownEvents = reveal ? reveal.result.events.slice(0, reveal.step) : [];
  const current = shownEvents.at(-1);
  let chips = 0;
  let mult = 0;
  for (const event of shownEvents) {
    chips = event.chips;
    if (event.type !== "card") mult = event.mult;
  }
  const guess = reveal ? null : preview(game, selected);
  const handName = reveal ? HANDS[reveal.result.kind].name : guess?.name;
  const order = game.hand
    .map((card, index) => ({ card, index }))
    .filter(({ index }) => !reveal?.played.includes(index))
    .sort((a, b) =>
      bySuit
        ? a.card.suit.localeCompare(b.card.suit) || b.card.rank - a.card.rank
        : b.card.rank - a.card.rank || a.card.suit.localeCompare(b.card.suit),
    );
  const busy = reveal !== null;

  function toggle(index: number) {
    setSelected((now) =>
      now.includes(index)
        ? now.filter((value) => value !== index)
        : now.length < 5
          ? [...now, index]
          : now,
    );
  }

  function playHand() {
    const after = play(game, selected);
    if (!after.last) return;
    setReveal({ result: after.last, after, played: selected, step: 0 });
    setSelected([]);
  }

  return (
    <div className={styles.jesters}>
      <aside className={styles.jSide}>
        <button
          type="button"
          className={`${styles.button} ${styles.grey}`}
          onClick={onLeave}
        >
          <PixelText text="Leave" scale={2} />
        </button>
        <div className={styles.jBlind}>
          <PixelText text={BLINDS[game.blind].name} scale={3} />
          <span className={styles.jLabel}>Score at least</span>
          <PixelText
            className={styles.jTarget}
            text={String(game.target)}
            scale={3}
          />
        </div>
        <div className={styles.jPanel}>
          <span className={styles.jLabel}>Round score</span>
          <PixelText
            text={String(
              game.roundScore +
                (reveal && reveal.step >= reveal.result.events.length
                  ? reveal.result.total
                  : 0),
            )}
            scale={4}
          />
        </div>
        <div className={styles.jPanel}>
          <PixelText
            className={styles.jHand}
            text={handName ?? " "}
            scale={2}
          />
          <Tally
            chips={reveal ? chips : (guess?.chips ?? 0)}
            mult={reveal ? mult : (guess?.mult ?? 0)}
          />
        </div>
        <div className={styles.jCounters}>
          <div>
            <span className={styles.jLabel}>Hands</span>
            <PixelText
              className={styles.jBlue}
              text={String(game.handsLeft)}
              scale={3}
            />
          </div>
          <div>
            <span className={styles.jLabel}>Discards</span>
            <PixelText
              className={styles.jRed}
              text={String(game.discardsLeft)}
              scale={3}
            />
          </div>
          <div>
            <span className={styles.jLabel}>Money</span>
            <PixelText
              className={styles.jGold}
              text={`$${game.money}`}
              scale={3}
            />
          </div>
          <div>
            <span className={styles.jLabel}>Ante</span>
            <PixelText text={String(game.ante)} scale={3} />
          </div>
        </div>
      </aside>

      <section className={styles.jMain}>
        <div className={styles.jesterRow} aria-label="Jesters">
          {game.jesters.map((id, index) => (
            <JesterCard
              key={id}
              id={id}
              index={index}
              active={current?.type === "jester" && current.jester === index}
            >
              {current?.type === "jester" && current.jester === index ? (
                <PixelText
                  key={reveal?.step}
                  className={styles.jPop}
                  text={effectLabel(current.effect)}
                  scale={2}
                />
              ) : null}
              {game.phase === "shop" ? (
                <button
                  type="button"
                  className={`${styles.button} ${styles.small} ${styles.grey}`}
                  onClick={() => setGame((now) => sell(now, index))}
                >
                  <PixelText
                    text={`Sell $${Math.floor(JESTERS[id].cost / 2)}`}
                    scale={2}
                  />
                </button>
              ) : null}
            </JesterCard>
          ))}
          {Array.from(
            { length: MAX_JESTERS - game.jesters.length },
            (_, index) => (
              <span
                key={index}
                className={styles.jesterSlot}
                aria-hidden="true"
              />
            ),
          )}
        </div>

        <div className={styles.jStage}>
          {reveal ? (
            <div className={styles.jPlayed}>
              {reveal.result.played.map((card, index) => (
                <span
                  key={`${card.rank}${card.suit}`}
                  className={styles.jPlayedCard}
                  data-scoring={
                    reveal.result.scoring.includes(card) ? "" : undefined
                  }
                  data-active={
                    current && "card" in current && current.card === index
                      ? ""
                      : undefined
                  }
                >
                  <PlayingCard card={card} order={index} />
                  {current?.type === "card" && current.card === index ? (
                    <PixelText
                      className={styles.jPop}
                      text={`+${current.chips - (shownEvents.at(-2)?.chips ?? 0)}`}
                      scale={3}
                    />
                  ) : null}
                </span>
              ))}
            </div>
          ) : game.phase === "shop" ? (
            <div className={styles.jShop}>
              <PixelText
                className={styles.jGold}
                text={`Cleared · +$${game.earned}`}
                scale={4}
              />
              <div className={styles.jOffers}>
                {game.shop.map((id, slot) => (
                  <JesterCard
                    key={id}
                    id={id}
                    index={slot + game.jesters.length}
                  >
                    <button
                      type="button"
                      className={`${styles.button} ${styles.small} ${styles.green}`}
                      disabled={
                        game.money < JESTERS[id].cost ||
                        game.jesters.length >= MAX_JESTERS
                      }
                      onClick={() => setGame((now) => buy(now, slot))}
                    >
                      <PixelText text={`Buy $${JESTERS[id].cost}`} scale={2} />
                    </button>
                  </JesterCard>
                ))}
              </div>
              <div className={styles.actions}>
                <button
                  type="button"
                  className={`${styles.button} ${styles.purple}`}
                  disabled={game.money < REROLL_COST}
                  onClick={() => setGame((now) => reroll(now))}
                >
                  <PixelText text={`Reroll $${REROLL_COST}`} scale={3} />
                </button>
                <button
                  type="button"
                  className={`${styles.button} ${styles.orange}`}
                  onClick={() => {
                    setGame((now) => nextBlind(now));
                    setSelected([]);
                  }}
                >
                  <PixelText text="Next" scale={3} />
                </button>
              </div>
            </div>
          ) : game.phase === "lost" ? (
            <div className={styles.jShop} role="status">
              <PixelText className={styles.jRed} text="Run over" scale={5} />
              <PixelText
                text={`Ante ${game.ante} · ${BLINDS[game.blind].name}`}
                scale={3}
              />
              <button
                type="button"
                className={`${styles.button} ${styles.orange} ${styles.deal}`}
                onClick={() => {
                  setGame(newGame());
                  setSelected([]);
                }}
              >
                <PixelText text="Again" scale={4} />
              </button>
            </div>
          ) : null}
        </div>

        {game.phase === "play" || reveal ? (
          <>
            <div className={styles.jHandRow} aria-label="Your hand">
              {order.map(({ card, index }, position) => (
                <button
                  key={`${card.rank}${card.suit}`}
                  type="button"
                  className={styles.jHandCard}
                  aria-pressed={selected.includes(index)}
                  disabled={busy}
                  onClick={() => toggle(index)}
                >
                  <PlayingCard card={card} order={position} />
                </button>
              ))}
            </div>
            <div className={styles.actions}>
              <button
                type="button"
                className={`${styles.button} ${styles.blue}`}
                disabled={busy || selected.length === 0}
                onClick={playHand}
              >
                <PixelText text="Play" scale={3} />
              </button>
              <button
                type="button"
                className={`${styles.button} ${styles.grey}`}
                disabled={busy}
                onClick={() => setBySuit((now) => !now)}
              >
                <PixelText text="Sort" scale={3} />
              </button>
              <button
                type="button"
                className={`${styles.button} ${styles.red}`}
                disabled={
                  busy || selected.length === 0 || game.discardsLeft === 0
                }
                onClick={() => {
                  setGame((now) => discard(now, selected));
                  setSelected([]);
                }}
              >
                <PixelText text="Discard" scale={3} />
              </button>
            </div>
          </>
        ) : null}
      </section>
    </div>
  );
}
