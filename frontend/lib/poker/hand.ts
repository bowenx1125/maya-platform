import type { Card } from "./cards";

/** Category 0 (high card) to 8 (straight flush), then tie-break ranks. */
export type HandValue = { category: number; ranks: number[] };

const NAMES = [
  "High Card",
  "Pair",
  "Two Pair",
  "Three of a Kind",
  "Straight",
  "Flush",
  "Full House",
  "Four of a Kind",
  "Straight Flush",
];

export function handName(value: HandValue): string {
  return value.category === 8 && value.ranks[0] === 14
    ? "Royal Flush"
    : NAMES[value.category];
}

/** High card of the straight in five distinct ranks, or 0. A-2-3-4-5 is 5-high. */
function straightHigh(distinctDescending: number[]): number {
  if (distinctDescending.length !== 5) return 0;
  const [high, , , , low] = distinctDescending;
  if (high - low === 4) return high;
  if (distinctDescending.join() === "14,5,4,3,2") return 5;
  return 0;
}

export function evaluateFive(cards: readonly Card[]): HandValue {
  if (cards.length !== 5) throw new Error("A hand is exactly five cards.");
  const ranks = cards.map((card) => card.rank).sort((a, b) => b - a);
  const flush = cards.every((card) => card.suit === cards[0].suit);
  const straight = straightHigh([...new Set(ranks)]);
  const counts = new Map<number, number>();
  for (const rank of ranks) counts.set(rank, (counts.get(rank) ?? 0) + 1);
  // Bigger groups first, then higher ranks: exactly the tie-break order.
  const groups = [...counts.entries()].sort(
    (a, b) => b[1] - a[1] || b[0] - a[0],
  );
  const byGroup = groups.map(([rank]) => rank);

  if (flush && straight) return { category: 8, ranks: [straight] };
  if (groups[0][1] === 4) return { category: 7, ranks: byGroup };
  if (groups[0][1] === 3 && groups[1][1] === 2)
    return { category: 6, ranks: byGroup };
  if (flush) return { category: 5, ranks };
  if (straight) return { category: 4, ranks: [straight] };
  if (groups[0][1] === 3) return { category: 3, ranks: byGroup };
  if (groups[0][1] === 2 && groups[1][1] === 2)
    return { category: 2, ranks: byGroup };
  if (groups[0][1] === 2) return { category: 1, ranks: byGroup };
  return { category: 0, ranks };
}

export function compareHands(a: HandValue, b: HandValue): number {
  if (a.category !== b.category) return a.category - b.category;
  for (
    let index = 0;
    index < Math.max(a.ranks.length, b.ranks.length);
    index += 1
  ) {
    const difference = (a.ranks[index] ?? 0) - (b.ranks[index] ?? 0);
    if (difference !== 0) return difference;
  }
  return 0;
}

/** The best five of five to seven cards. */
export function bestHand(cards: readonly Card[]): HandValue {
  if (cards.length < 5 || cards.length > 7)
    throw new Error("Best hand needs five to seven cards.");
  const n = cards.length;
  let best: HandValue | null = null;
  for (let a = 0; a < n; a += 1)
    for (let b = a + 1; b < n; b += 1)
      for (let c = b + 1; c < n; c += 1)
        for (let d = c + 1; d < n; d += 1)
          for (let e = d + 1; e < n; e += 1) {
            const value = evaluateFive([
              cards[a],
              cards[b],
              cards[c],
              cards[d],
              cards[e],
            ]);
            if (!best || compareHands(value, best) > 0) best = value;
          }
  if (!best) throw new Error("Best hand needs five to seven cards.");
  return best;
}
