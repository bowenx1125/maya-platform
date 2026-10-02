import { describe, expect, it } from "vitest";

import type { Card, Suit } from "../lib/poker/cards";
import {
  buy,
  discard,
  nextBlind,
  newGame,
  play,
  reroll,
  score,
  sell,
  targetFor,
  type GameState,
} from "../lib/jesters/game";
import { readHand } from "../lib/jesters/score";

const RANKS: Record<string, number> = { A: 14, K: 13, Q: 12, J: 11, T: 10 };
const card = (text: string): Card => ({
  rank: RANKS[text[0]] ?? Number(text[0]),
  suit: text[1] as Suit,
});
const cards = (text: string) => text.split(" ").map(card);
const fixed = () => 0;

/** A game whose hand is exactly `text`, with nothing left to draw. */
function holding(text: string, patch: Partial<GameState> = {}): GameState {
  return { ...newGame(fixed), hand: cards(text), deck: [], ...patch };
}

describe("reading a played hand", () => {
  it("finds the hand and only the cards that score", () => {
    expect(readHand(cards("9h 9d"))).toMatchObject({ kind: "pair" });
    expect(readHand(cards("9h 9d Kc")).scoring).toEqual(cards("9h 9d"));
    expect(readHand(cards("Ah 2d 3s 4c 5h")).kind).toBe("straight");
    expect(readHand(cards("2h 7h 9h Jh Kh")).kind).toBe("flush");
    expect(readHand(cards("9h 9d 9s 2c 2h")).kind).toBe("fullHouse");
    expect(readHand(cards("Kh 2d 7s")).scoring).toEqual(cards("Kh"));
    // Four to a flush is not a flush.
    expect(readHand(cards("2h 7h 9h Jh")).kind).toBe("high");
  });
});

describe("scoring", () => {
  it("adds base, card chips and jesters in order, multiplying last where asked", () => {
    const plain = score(cards("9h 9d"), [], {
      handsLeft: 4,
      discardsLeft: 3,
      handsPlayed: 0,
    });
    // Pair 12 chips x 2, plus 9 + 9.
    expect(plain).toMatchObject({ chips: 30, mult: 2, total: 60 });

    const primes = score(cards("7h 7d"), ["hypatia"], {
      handsLeft: 4,
      discardsLeft: 3,
      handsPlayed: 0,
    });
    // Each scoring 7 adds +3 Mult.
    expect(primes).toMatchObject({ chips: 26, mult: 8, total: 208 });

    const lastHand = score(cards("9h 9d"), ["confucius", "zhuangzi"], {
      handsLeft: 1,
      discardsLeft: 0,
      handsPlayed: 3,
    });
    // (2 + 8) x 2: additions come before the multiplier in jester order.
    expect(lastHand).toMatchObject({ chips: 30, mult: 20, total: 600 });
    expect(lastHand.events.at(-1)).toMatchObject({ type: "jester", jester: 1 });
  });

  it("gives Laozi's chips only without face cards", () => {
    const context = { handsLeft: 4, discardsLeft: 3, handsPlayed: 0 };
    expect(score(cards("9h 9d"), ["laozi"], context).chips).toBe(70);
    expect(score(cards("Kh Kd"), ["laozi"], context).chips).toBe(32);
  });
});

describe("a run", () => {
  it("opens with a full hand and the first sitting's target", () => {
    const game = newGame();
    expect(game.hand).toHaveLength(8);
    expect(game.target).toBe(targetFor(1, 0));
    expect(game).toMatchObject({
      handsLeft: 4,
      discardsLeft: 3,
      money: 4,
      phase: "play",
    });
  });

  it("pays and opens the shop once the target is met", () => {
    const game = holding("Ah Ad As Ac Kh", { target: 100 });
    const after = play(game, [0, 1, 2, 3], fixed);
    expect(after.phase).toBe("shop");
    expect(after.roundScore).toBeGreaterThanOrEqual(100);
    // Lecture pays 3, plus one per hand to spare (3), no interest under $5.
    expect(after.earned).toBe(6);
    expect(after.money).toBe(10);
    expect(after.shop).toHaveLength(2);
  });

  it("ends the run when the last hand falls short", () => {
    const game = holding("2h 3d", { handsLeft: 1, target: 10_000 });
    expect(play(game, [0]).phase).toBe("lost");
  });

  it("refuses what the rules do not allow", () => {
    const game = holding("2h 3d 4s 5c 6h 7d");
    expect(() => play(game, [])).toThrow();
    expect(() => play(game, [0, 0])).toThrow();
    expect(() => play(game, [0, 1, 2, 3, 4, 5])).toThrow();
    expect(() => discard({ ...game, discardsLeft: 0 }, [0])).toThrow();
    expect(() => buy(game, 0)).toThrow();
  });

  it("pays Diogenes for discards", () => {
    const game = holding("2h 3d 4s", { jesters: ["diogenes"], money: 0 });
    const after = discard(game, [0, 1]);
    expect(after.money).toBe(2);
    expect(after.discardsLeft).toBe(2);
  });

  it("buys, sells and rerolls in the shop, and moves to the next ante after the Viva", () => {
    let game: GameState = {
      ...holding("2h"),
      phase: "shop",
      money: 20,
      shop: ["hypatia", "plato"],
    };
    game = buy(game, 0);
    expect(game.jesters).toEqual(["hypatia"]);
    expect(game.money).toBe(15);
    expect(() => buy({ ...game, money: 0 }, 0)).toThrow();
    game = sell(game, 0);
    expect(game.money).toBe(17);
    game = reroll(game, fixed);
    expect(game.money).toBe(14);
    expect(game.shop).toHaveLength(2);
    const viva = nextBlind({ ...game, blind: 2 }, fixed);
    expect(viva).toMatchObject({
      ante: 2,
      blind: 0,
      phase: "play",
      target: targetFor(2, 0),
    });
    expect(viva.hand).toHaveLength(8);
  });
});
