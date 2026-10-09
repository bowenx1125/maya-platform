import type { Card } from "./cards";
import { bestHand } from "./hand";
import { legalActions, pot, type Action, type TableState } from "./table";

const clamp = (value: number, low: number, high: number) =>
  Math.min(high, Math.max(low, value));

/** Rough 0–1 strength of two hole cards before the flop. */
export function preflopStrength([a, b]: readonly Card[]): number {
  if (a.rank === b.rank) return 0.5 + a.rank / 28;
  const high = Math.max(a.rank, b.rank);
  const low = Math.min(a.rank, b.rank);
  let score = (high + low / 2) / 21 - 0.15;
  if (a.suit === b.suit) score += 0.06;
  if (high - low === 1) score += 0.04;
  else if (high - low === 2) score += 0.02;
  return clamp(score, 0.05, 0.95);
}

const CATEGORY_STRENGTH = [0.15, 0.42, 0.62, 0.74, 0.8, 0.85, 0.92, 0.97, 0.99];

/** Rough 0–1 strength once there is a board, with credit for draws. */
export function postflopStrength(
  hole: readonly Card[],
  board: readonly Card[],
): number {
  const value = bestHand([...hole, ...board]);
  const holeRanks = hole.map((card) => card.rank);
  let score = CATEGORY_STRENGTH[value.category];
  if (value.category === 1) {
    // A pair that is only on the board belongs to everyone.
    score = holeRanks.includes(value.ranks[0])
      ? score + (value.ranks[0] - 8) * 0.015
      : 0.22;
  } else if (value.category === 2) {
    if (!holeRanks.some((rank) => value.ranks.slice(0, 2).includes(rank)))
      score = 0.25;
  } else if (value.category === 0) {
    score += (Math.max(...holeRanks) - 10) * 0.02;
  }
  if (board.length < 5) {
    const cards = [...hole, ...board];
    const suited = Math.max(
      ...["s", "h", "d", "c"].map(
        (suit) => cards.filter((card) => card.suit === suit).length,
      ),
    );
    if (suited === 4) score += 0.12;
    const ranks = new Set(cards.map((card) => card.rank));
    if (ranks.has(14)) ranks.add(1);
    for (let low = 1; low <= 10; low += 1) {
      let held = 0;
      for (let rank = low; rank < low + 5; rank += 1)
        if (ranks.has(rank)) held += 1;
      if (held === 4) {
        score += 0.07;
        break;
      }
    }
  }
  return clamp(score, 0.02, 0.99);
}

/** What a computer player does on its turn. `random` is for tests. */
export function decide(state: TableState, random = Math.random): Action {
  if (state.toAct === null) throw new Error("Nobody is to act.");
  const seat = state.seats[state.toAct];
  const legal = legalActions(state);
  const strength = state.board.length
    ? postflopStrength(seat.hole, state.board)
    : preflopStrength(seat.hole);
  // A little mood each turn, so the table cannot be read off a formula.
  const felt = strength + (random() - 0.5) * 0.2;
  const potSize = pot(state);
  const raiseTo = (fraction: number) => {
    const size = Math.max(state.minRaise, potSize * fraction);
    const rounded =
      Math.round((state.currentBet + size) / state.smallBlind) *
      state.smallBlind;
    return clamp(rounded, legal.minRaiseTo, legal.maxRaiseTo);
  };

  if (legal.canCheck) {
    if (legal.canRaise && felt > 0.62)
      return { type: "raise", to: raiseTo(felt > 0.85 ? 0.9 : 0.55) };
    if (legal.canRaise && random() < 0.07)
      return { type: "raise", to: raiseTo(0.4) };
    return { type: "check" };
  }

  const odds = legal.toCall / (potSize + legal.toCall);
  if (felt < odds + 0.1) return { type: "fold" };
  if (legal.canRaise && felt > 0.93 && random() < 0.25)
    return { type: "raise", to: legal.maxRaiseTo };
  if (legal.canRaise && felt > 0.8) return { type: "raise", to: raiseTo(0.75) };
  return { type: "call" };
}
