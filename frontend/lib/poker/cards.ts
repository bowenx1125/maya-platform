export type Suit = "s" | "h" | "d" | "c";
/** Rank 2–14, ace high. */
export type Card = { rank: number; suit: Suit };

export const SUITS: readonly Suit[] = ["s", "h", "d", "c"];

export function freshDeck(): Card[] {
  return SUITS.flatMap((suit) =>
    Array.from({ length: 13 }, (_, index) => ({ rank: index + 2, suit })),
  );
}

/**
 * A uniform integer in [0, bound). Rejection sampling keeps the deal unbiased:
 * a plain modulo of a 32-bit value favours the low cards by a hair.
 */
export function randomIndex(bound: number): number {
  const limit = Math.floor(0x1_0000_0000 / bound) * bound;
  const buffer = new Uint32Array(1);
  for (;;) {
    crypto.getRandomValues(buffer);
    if (buffer[0] < limit) return buffer[0] % bound;
  }
}

export function shuffle<T>(items: readonly T[], random = randomIndex): T[] {
  const result = [...items];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const other = random(index + 1);
    [result[index], result[other]] = [result[other], result[index]];
  }
  return result;
}

export function rankLabel(rank: number): string {
  return { 14: "A", 13: "K", 12: "Q", 11: "J" }[rank] ?? String(rank);
}

export function isRed(suit: Suit): boolean {
  return suit === "h" || suit === "d";
}
