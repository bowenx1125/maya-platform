import { describe, expect, it } from "vitest";

import { decide } from "../lib/poker/bot";
import { freshDeck, shuffle, type Card, type Suit } from "../lib/poker/cards";
import {
  bestHand,
  compareHands,
  evaluateFive,
  handName,
} from "../lib/poker/hand";
import {
  act,
  addChips,
  createTable,
  legalActions,
  startHand,
  type Player,
  type TableState,
} from "../lib/poker/table";

const RANKS: Record<string, number> = { A: 14, K: 13, Q: 12, J: 11, T: 10 };
function card(text: string): Card {
  const rank = RANKS[text[0]] ?? Number(text[0]);
  return { rank, suit: text[1] as Suit };
}
const cards = (text: string) => text.split(" ").map(card);
const name = (text: string) => handName(bestHand(cards(text)));

/** A deck that deals `holes` in deal order, then `board`, then the rest. */
function deck(holes: string[], board: string): Card[] {
  const firsts = holes.map((hole) => card(hole.split(" ")[0]));
  const seconds = holes.map((hole) => card(hole.split(" ")[1]));
  const top = [...firsts, ...seconds, ...cards(board)];
  const used = new Set(top.map((c) => `${c.rank}${c.suit}`));
  return [
    ...top,
    ...freshDeck().filter((c) => !used.has(`${c.rank}${c.suit}`)),
  ];
}

const players = (count: number): Player[] =>
  Array.from({ length: count }, (_, index) => ({
    id: `p${index}`,
    name: `P${index}`,
    human: false,
  }));

/** Chips at the table; between hands every chip is in someone's stack. */
const chips = (state: TableState) =>
  state.seats.reduce((sum, seat) => sum + seat.stack, 0);

describe("hands", () => {
  it("names every category, royal flush included", () => {
    expect(name("As Ks Qs Js Ts 2d 3c")).toBe("Royal Flush");
    expect(name("9h 8h 7h 6h 5h Ad Ac")).toBe("Straight Flush");
    expect(name("9h 9d 9s 9c 2h 3d 4c")).toBe("Four of a Kind");
    expect(name("9h 9d 9s 2c 2h 3d 4c")).toBe("Full House");
    expect(name("Ah 9h 7h 4h 2h 3d Kc")).toBe("Flush");
    expect(name("Ah 2d 3s 4c 5h 9d Kc")).toBe("Straight");
    expect(name("9h 9d 9s 2c 5h 3d Kc")).toBe("Three of a Kind");
    expect(name("9h 9d 5s 5c 2h 3d Kc")).toBe("Two Pair");
    expect(name("9h 9d 5s 4c 2h Td Kc")).toBe("Pair");
    expect(name("Ah Jd 5s 4c 2h 8d Kc")).toBe("High Card");
  });

  it("ranks the wheel below a six-high straight and breaks ties on kickers", () => {
    const wheel = evaluateFive(cards("Ah 2d 3s 4c 5h"));
    const sixHigh = evaluateFive(cards("2d 3s 4c 5h 6d"));
    expect(compareHands(wheel, sixHigh)).toBeLessThan(0);
    const kingKicker = evaluateFive(cards("9h 9d Ks 4c 2h"));
    const queenKicker = evaluateFive(cards("9s 9c Qs 4d 2d"));
    expect(compareHands(kingKicker, queenKicker)).toBeGreaterThan(0);
    expect(
      compareHands(
        evaluateFive(cards("9h 9d Ks 4c 2h")),
        evaluateFive(cards("9s 9c Kd 4d 2s")),
      ),
    ).toBe(0);
  });

  it("finds the best five of seven", () => {
    expect(bestHand(cards("Ah 9h 7h 4h 2h 3d 5c")).category).toBe(5);
  });
});

describe("table", () => {
  it("makes the button the small blind heads-up and gives the big blind its option", () => {
    let state = startHand(
      createTable(players(2)),
      deck(["2c 7d", "9s 9h"], "Ks 8h 4d 3c Jh"),
    );
    expect(state.button).toBe(0);
    expect(state.seats[0].bet).toBe(10);
    expect(state.seats[1].bet).toBe(20);
    expect(state.toAct).toBe(0);
    state = act(state, { type: "call" });
    expect(state.street).toBe("preflop");
    expect(state.toAct).toBe(1);
    expect(legalActions(state).canCheck).toBe(true);
    state = act(state, { type: "check" });
    expect(state.street).toBe("flop");
    expect(state.board).toHaveLength(3);
    // After the flop the big blind, not the button, speaks first.
    expect(state.toAct).toBe(1);
  });

  it("gives the blinds to the last player standing without a showdown", () => {
    // Three players: button 0, small blind 1, big blind 2; 0 acts first.
    let state = startHand(createTable(players(3)));
    state = act(state, { type: "fold" });
    state = act(state, { type: "fold" });
    expect(state.street).toBe("complete");
    expect(state.showdown).toBe(false);
    // The big blind's last 10 was never called, so the pot won is 20.
    expect(state.payouts).toEqual([{ seatId: "p2", amount: 20, hand: null }]);
    expect(state.seats.map((seat) => seat.stack)).toEqual([1000, 990, 1010]);
  });

  it("plays to a showdown and pays the best hand", () => {
    // Deal order is 1, 2, 0 (left of the button).
    let state = startHand(
      createTable(players(3)),
      deck(["Ks Kd", "2c 7d", "As Ad"], "Kh 8h 4d 3c Jh"),
    );
    state = act(state, { type: "call" });
    state = act(state, { type: "call" });
    state = act(state, { type: "check" });
    for (const street of ["flop", "turn", "river"]) {
      expect(state.street).toBe(street);
      for (let turn = 0; turn < 3; turn += 1)
        state = act(state, { type: "check" });
    }
    expect(state.showdown).toBe(true);
    expect(state.payouts).toEqual([
      { seatId: "p1", amount: 60, hand: "Three of a Kind" },
    ]);
    expect(chips(state)).toBe(3000);
  });

  it("splits a tied pot and gives the odd chip left of the button", () => {
    const table = createTable(players(3), {
      stack: 1000,
      smallBlind: 5,
      bigBlind: 10,
    });
    let state = startHand(
      table,
      deck(["2c 7d", "3d 4h", "5s 6s"], "Ah Kh Qh Jc Tc"),
    );
    state = act(state, { type: "call" }); // button
    state = act(state, { type: "fold" }); // small blind gives up 5
    state = act(state, { type: "check" }); // big blind
    for (let turn = 0; turn < 6; turn += 1)
      state = act(state, { type: "check" });
    // Both live hands play the board's straight; the 25-chip pot splits 13/12.
    const paid = Object.fromEntries(
      state.payouts.map((p) => [p.seatId, p.amount]),
    );
    expect(paid.p2 + paid.p0).toBe(25);
    expect(paid.p2).toBe(13);
    expect(chips(state)).toBe(3000);
  });

  it("builds side pots when stacks differ and everyone is all in", () => {
    let state = createTable(players(3));
    state = {
      ...state,
      seats: state.seats.map((seat, i) => ({
        ...seat,
        stack: [300, 100, 200][i],
      })),
    };
    // Seat 1 (shortest) holds the best hand, seat 2 the next, seat 0 the worst.
    state = startHand(
      state,
      deck(["As Ad", "Ks Kd", "2c 7h"], "9c 8d 4s 3h Jc"),
    );
    state = act(state, { type: "raise", to: 300 });
    state = act(state, { type: "call" });
    state = act(state, { type: "call" });
    expect(state.street).toBe("complete");
    expect(state.board).toHaveLength(5);
    const paid = Object.fromEntries(
      state.payouts.map((p) => [p.seatId, p.amount]),
    );
    // Main pot 300 to seat 1; side pot 200 (seats 0 and 2) to seat 2; seat 0's
    // last 100 was never called and comes back.
    expect(paid).toEqual({ p1: 300, p2: 200 });
    expect(state.seats.map((seat) => seat.stack)).toEqual([100, 300, 200]);
  });

  it("refuses a raise below the minimum unless it is all in", () => {
    const state = startHand(createTable(players(2)));
    expect(() => act(state, { type: "raise", to: 30 })).toThrow();
    expect(() => act(state, { type: "raise", to: 2000 })).toThrow();
    expect(act(state, { type: "raise", to: 40 }).currentBet).toBe(40);
    expect(act(state, { type: "raise", to: 1000 }).seats[0].allIn).toBe(true);
  });

  it("returns an uncalled bet instead of counting it as won", () => {
    let state = startHand(createTable(players(2)));
    state = act(state, { type: "call" });
    state = act(state, { type: "check" });
    state = act(state, { type: "raise", to: 100 });
    state = act(state, { type: "fold" });
    expect(state.payouts).toEqual([{ seatId: "p1", amount: 40, hand: null }]);
    expect(state.seats.map((seat) => seat.stack)).toEqual([980, 1020]);
  });

  it("adds chips only between hands", () => {
    const table = createTable(players(2));
    expect(addChips(table, "p0", 500).seats[0].stack).toBe(1500);
    expect(() => addChips(startHand(table), "p0", 500)).toThrow();
    expect(() => addChips(table, "p0", -5)).toThrow();
  });

  it("lets computer players finish hundreds of hands without losing a chip", () => {
    let seed = 7;
    const random = () => {
      seed = (seed * 16807) % 2147483647;
      return seed / 2147483647;
    };
    let state = createTable(players(4));
    for (let hand = 0; hand < 300; hand += 1) {
      for (const seat of state.seats)
        if (seat.stack === 0) state = addChips(state, seat.id, 1000);
      const before = chips(state);
      state = startHand(
        state,
        shuffle(freshDeck(), (n) => Math.floor(random() * n)),
      );
      let guard = 0;
      while (state.toAct !== null) {
        state = act(state, decide(state, random));
        guard += 1;
        expect(guard).toBeLessThan(200);
      }
      expect(state.street).toBe("complete");
      expect(chips(state)).toBe(before);
    }
  });
});
