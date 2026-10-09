import { freshDeck, randomIndex, shuffle, type Card } from "../poker/cards";
import {
  JESTERS,
  JESTER_IDS,
  type Effect,
  type JesterId,
  type ScoreContext,
} from "./jesters";
import { HANDS, cardChips, readHand, type HandKind } from "./score";

export const HAND_SIZE = 8;
export const MAX_JESTERS = 5;
export const HANDS_PER_ROUND = 4;
export const DISCARDS_PER_ROUND = 3;
export const REROLL_COST = 3;

/** Three sittings an ante, each a harder examination than the last. */
export const BLINDS = [
  { name: "Lecture", factor: 1, reward: 3 },
  { name: "Seminar", factor: 1.5, reward: 4 },
  { name: "Viva", factor: 2, reward: 5 },
] as const;
const ANTE_BASE = [300, 800, 2000, 5000, 11000, 20000, 35000, 50000];

export function targetFor(ante: number, blind: number): number {
  const base =
    ANTE_BASE[ante - 1] ??
    Math.round(
      ANTE_BASE[ANTE_BASE.length - 1] * 1.6 ** (ante - ANTE_BASE.length),
    );
  return Math.round((base * BLINDS[blind].factor) / 10) * 10;
}

export type ScoreEvent =
  | { type: "base"; chips: number; mult: number }
  | { type: "card"; card: number; chips: number }
  | {
      type: "jester";
      jester: number;
      card?: number;
      effect: Effect;
      chips: number;
      mult: number;
    };

export type ScoreResult = {
  kind: HandKind;
  played: Card[];
  scoring: Card[];
  chips: number;
  mult: number;
  total: number;
  /** Every step in order, with running chips and mult, for the reveal. */
  events: ScoreEvent[];
};

export type GameState = {
  deck: Card[];
  hand: Card[];
  ante: number;
  blind: number;
  target: number;
  roundScore: number;
  handsLeft: number;
  discardsLeft: number;
  money: number;
  jesters: JesterId[];
  shop: JesterId[];
  handsPlayed: number;
  phase: "play" | "shop" | "lost";
  earned: number;
  last: ScoreResult | null;
};

type Random = (bound: number) => number;

const sameCard = (a: Card, b: Card) => a.rank === b.rank && a.suit === b.suit;

function draw(deck: Card[], hand: Card[]) {
  const nextDeck = [...deck];
  const nextHand = [...hand];
  while (nextHand.length < HAND_SIZE && nextDeck.length) {
    const card = nextDeck.shift();
    if (card) nextHand.push(card);
  }
  return { deck: nextDeck, hand: nextHand };
}

function rollShop(owned: readonly JesterId[], random: Random): JesterId[] {
  const pool = JESTER_IDS.filter((id) => !owned.includes(id));
  return shuffle(pool, random).slice(0, 2);
}

function dealRound(state: GameState, random: Random): GameState {
  const { deck, hand } = draw(shuffle(freshDeck(), random), []);
  return {
    ...state,
    deck,
    hand,
    target: targetFor(state.ante, state.blind),
    roundScore: 0,
    handsLeft: HANDS_PER_ROUND,
    discardsLeft: DISCARDS_PER_ROUND,
    phase: "play",
    earned: 0,
    last: null,
  };
}

export function newGame(random: Random = randomIndex): GameState {
  return dealRound(
    {
      deck: [],
      hand: [],
      ante: 1,
      blind: 0,
      target: 0,
      roundScore: 0,
      handsLeft: 0,
      discardsLeft: 0,
      money: 4,
      jesters: [],
      shop: [],
      handsPlayed: 0,
      phase: "play",
      earned: 0,
      last: null,
    },
    random,
  );
}

function pick(state: GameState, indexes: readonly number[]): Card[] {
  const unique = new Set(indexes);
  if (
    unique.size !== indexes.length ||
    indexes.length < 1 ||
    indexes.length > 5 ||
    indexes.some((index) => !Number.isInteger(index) || !state.hand[index])
  )
    throw new Error("Choose one to five cards from your hand.");
  return indexes.map((index) => state.hand[index]);
}

/** Score a hand: base, then each scoring card with its jesters, then the hand's jesters. */
export function score(
  played: Card[],
  jesters: readonly JesterId[],
  context: Omit<ScoreContext, "kind" | "played" | "scoring" | "jesterCount">,
): ScoreResult {
  const { kind, scoring } = readHand(played);
  const full: ScoreContext = {
    ...context,
    kind,
    played,
    scoring,
    jesterCount: jesters.length,
  };
  let chips = HANDS[kind].chips;
  let mult = HANDS[kind].mult;
  const events: ScoreEvent[] = [{ type: "base", chips, mult }];
  const apply = (effect: Effect, jester: number, card?: number) => {
    chips += effect.chips ?? 0;
    mult += effect.mult ?? 0;
    mult *= effect.times ?? 1;
    events.push({ type: "jester", jester, card, effect, chips, mult });
  };
  scoring.forEach((card) => {
    const index = played.findIndex((candidate) => sameCard(candidate, card));
    chips += cardChips(card);
    events.push({ type: "card", card: index, chips });
    jesters.forEach((id, jester) => {
      const effect = JESTERS[id].onCard?.(card, full);
      if (effect) apply(effect, jester, index);
    });
  });
  jesters.forEach((id, jester) => {
    const effect = JESTERS[id].onHand?.(full);
    if (effect) apply(effect, jester);
  });
  return {
    kind,
    played,
    scoring,
    chips,
    mult,
    total: Math.floor(chips * mult),
    events,
  };
}

export function play(
  state: GameState,
  indexes: readonly number[],
  random: Random = randomIndex,
): GameState {
  if (state.phase !== "play" || state.handsLeft < 1)
    throw new Error("No hand can be played now.");
  const played = pick(state, indexes);
  const result = score(played, state.jesters, {
    handsLeft: state.handsLeft,
    discardsLeft: state.discardsLeft,
    handsPlayed: state.handsPlayed,
  });
  const kept = state.hand.filter((_, index) => !indexes.includes(index));
  const { deck, hand } = draw(state.deck, kept);
  const next: GameState = {
    ...state,
    deck,
    hand,
    roundScore: state.roundScore + result.total,
    handsLeft: state.handsLeft - 1,
    handsPlayed: state.handsPlayed + 1,
    last: result,
  };
  if (next.roundScore >= next.target) {
    // A cleared round pays its reward, a dollar per hand to spare, and a
    // dollar of interest per five held, capped at five.
    const earned =
      BLINDS[next.blind].reward +
      next.handsLeft +
      Math.min(5, Math.floor(next.money / 5));
    return {
      ...next,
      money: next.money + earned,
      earned,
      phase: "shop",
      shop: rollShop(next.jesters, random),
    };
  }
  return next.handsLeft === 0 ? { ...next, phase: "lost" } : next;
}

export function discard(
  state: GameState,
  indexes: readonly number[],
): GameState {
  if (state.phase !== "play" || state.discardsLeft < 1)
    throw new Error("No discards left.");
  pick(state, indexes);
  const kept = state.hand.filter((_, index) => !indexes.includes(index));
  const { deck, hand } = draw(state.deck, kept);
  const paid = state.jesters.reduce(
    (sum, id) => sum + (JESTERS[id].onDiscard?.(indexes.length) ?? 0),
    0,
  );
  return {
    ...state,
    deck,
    hand,
    discardsLeft: state.discardsLeft - 1,
    money: state.money + paid,
  };
}

export function buy(state: GameState, slot: number): GameState {
  const id = state.shop[slot];
  if (state.phase !== "shop" || !id) throw new Error("Nothing to buy there.");
  if (state.jesters.length >= MAX_JESTERS)
    throw new Error("No room for another Jester.");
  if (state.money < JESTERS[id].cost) throw new Error("Not enough money.");
  return {
    ...state,
    money: state.money - JESTERS[id].cost,
    jesters: [...state.jesters, id],
    shop: state.shop.filter((_, index) => index !== slot),
  };
}

export function sell(state: GameState, slot: number): GameState {
  const id = state.jesters[slot];
  if (state.phase !== "shop" || !id) throw new Error("Nothing to sell there.");
  return {
    ...state,
    money: state.money + Math.floor(JESTERS[id].cost / 2),
    jesters: state.jesters.filter((_, index) => index !== slot),
  };
}

export function reroll(
  state: GameState,
  random: Random = randomIndex,
): GameState {
  if (state.phase !== "shop" || state.money < REROLL_COST)
    throw new Error("Not enough money to reroll.");
  return {
    ...state,
    money: state.money - REROLL_COST,
    shop: rollShop(state.jesters, random),
  };
}

/** Leave the shop for the next sitting; after the Viva comes a harder ante. */
export function nextBlind(
  state: GameState,
  random: Random = randomIndex,
): GameState {
  if (state.phase !== "shop") throw new Error("Finish the round first.");
  const last = state.blind === BLINDS.length - 1;
  return dealRound(
    {
      ...state,
      ante: last ? state.ante + 1 : state.ante,
      blind: last ? 0 : state.blind + 1,
      shop: [],
    },
    random,
  );
}

/** What the selected cards would make, for the panel before playing. */
export function preview(state: GameState, indexes: readonly number[]) {
  if (indexes.length < 1 || indexes.length > 5) return null;
  const { kind } = readHand(indexes.map((index) => state.hand[index]));
  return { kind, ...HANDS[kind] };
}
