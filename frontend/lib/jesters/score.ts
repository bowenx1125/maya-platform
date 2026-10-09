import type { Card } from "../poker/cards";

export type HandKind =
  | "high"
  | "pair"
  | "twoPair"
  | "trips"
  | "straight"
  | "flush"
  | "fullHouse"
  | "quads"
  | "straightFlush";

/** Base chips and multiplier for each hand. Our own table, not another game's. */
export const HANDS: Record<
  HandKind,
  { name: string; chips: number; mult: number }
> = {
  high: { name: "High Card", chips: 6, mult: 1 },
  pair: { name: "Pair", chips: 12, mult: 2 },
  twoPair: { name: "Two Pair", chips: 22, mult: 2 },
  trips: { name: "Three of a Kind", chips: 32, mult: 3 },
  straight: { name: "Straight", chips: 36, mult: 4 },
  flush: { name: "Flush", chips: 40, mult: 4 },
  fullHouse: { name: "Full House", chips: 48, mult: 5 },
  quads: { name: "Four of a Kind", chips: 70, mult: 7 },
  straightFlush: { name: "Straight Flush", chips: 110, mult: 9 },
};

/** What a card adds when it scores: its pip value, faces 10, aces 11. */
export function cardChips(card: Card): number {
  if (card.rank === 14) return 11;
  return Math.min(card.rank, 10);
}

/**
 * The hand formed by one to five played cards, and which of them score.
 * Straights and flushes need all five; a pair needs only its two.
 */
export function readHand(played: readonly Card[]): {
  kind: HandKind;
  scoring: Card[];
} {
  if (played.length < 1 || played.length > 5)
    throw new Error("Play one to five cards.");
  const byRank = new Map<number, Card[]>();
  for (const card of played)
    byRank.set(card.rank, [...(byRank.get(card.rank) ?? []), card]);
  const groups = [...byRank.values()].sort(
    (a, b) => b.length - a.length || b[0].rank - a[0].rank,
  );
  const five = played.length === 5;
  const flush = five && played.every((card) => card.suit === played[0].suit);
  const distinct = [...new Set(played.map((card) => card.rank))].sort(
    (a, b) => b - a,
  );
  const straight =
    five &&
    distinct.length === 5 &&
    (distinct[0] - distinct[4] === 4 || distinct.join() === "14,5,4,3,2");

  if (flush && straight) return { kind: "straightFlush", scoring: [...played] };
  if (groups[0].length === 4) return { kind: "quads", scoring: groups[0] };
  if (groups[0].length === 3 && groups[1]?.length === 2)
    return { kind: "fullHouse", scoring: [...played] };
  if (flush) return { kind: "flush", scoring: [...played] };
  if (straight) return { kind: "straight", scoring: [...played] };
  if (groups[0].length === 3) return { kind: "trips", scoring: groups[0] };
  if (groups[0].length === 2 && groups[1]?.length === 2)
    return { kind: "twoPair", scoring: [...groups[0], ...groups[1]] };
  if (groups[0].length === 2) return { kind: "pair", scoring: groups[0] };
  const highest = [...played].sort((a, b) => b.rank - a.rank)[0];
  return { kind: "high", scoring: [highest] };
}
