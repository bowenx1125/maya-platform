import { describe, expect, it } from "vitest";

import { freshDeck, type Card, type Suit } from "../lib/poker/cards";
import { act, createTable, startHand, type Player } from "../lib/poker/table";
import {
  closeHand,
  decision,
  summarize,
  type Decision,
  type HandRecord,
} from "../lib/poker/training";

const RANKS: Record<string, number> = { A: 14, K: 13, Q: 12, J: 11, T: 10 };
const card = (text: string): Card => ({
  rank: RANKS[text[0]] ?? Number(text[0]),
  suit: text[1] as Suit,
});
function deck(holes: string[], board: string): Card[] {
  const firsts = holes.map((hole) => card(hole.split(" ")[0]));
  const seconds = holes.map((hole) => card(hole.split(" ")[1]));
  const top = [...firsts, ...seconds, ...board.split(" ").map(card)];
  const used = new Set(top.map((c) => `${c.rank}${c.suit}`));
  return [
    ...top,
    ...freshDeck().filter((c) => !used.has(`${c.rank}${c.suit}`)),
  ];
}
const players: Player[] = [
  { id: "me", name: "Me", human: true },
  { id: "bot", name: "Bot", human: false },
];

const record = (patch: Partial<HandRecord>): HandRecord => ({
  hand: 1,
  hole: [],
  board: [],
  strength: 0.5,
  vpip: false,
  pfr: false,
  sawFlop: false,
  showdown: false,
  won: false,
  facedBets: 0,
  foldsToBets: 0,
  aggressive: 0,
  passive: 0,
  net: 0,
  ...patch,
});

describe("training records", () => {
  it("records a raised hand won at showdown, net of what went in", () => {
    // Heads-up the human is the button and small blind and acts first.
    let table = startHand(
      createTable(players, { stack: 4000, smallBlind: 10, bigBlind: 20 }),
      deck(["2c 7d", "As Ad"], "Kh 8h 4d 3c Jh"),
    );
    const choices: Decision[] = [];
    const take = (action: Parameters<typeof act>[1]) => {
      choices.push(decision(table, action));
      table = act(table, action);
    };
    take({ type: "raise", to: 60 });
    expect(choices[0]).toEqual({
      street: "preflop",
      toCall: 10,
      type: "raise",
    });
    table = act(table, { type: "call" });
    while (table.toAct !== null)
      if (table.seats[table.toAct].human) take({ type: "check" });
      else table = act(table, { type: "check" });
    const hand = closeHand(table, "me", 4000, choices);
    expect(hand).toMatchObject({
      vpip: true,
      pfr: true,
      sawFlop: true,
      showdown: true,
      won: true,
      net: 60,
    });
  });

  it("gives no advice before there are enough hands to read", () => {
    expect(summarize([record({ vpip: true })]).tips).toEqual([]);
  });

  it("names the costliest leak with its number", () => {
    const loose = Array.from({ length: 10 }, (_, hand) =>
      record({ hand, vpip: true, strength: 0.2, net: -100 }),
    );
    const summary = summarize(loose);
    expect(summary.vpip).toBe(1);
    expect(summary.net).toBe(-1000);
    expect(summary.tips[0]).toContain("You played 100% of hands");
    expect(summary.tips[0]).toContain("cost you 1000");
    expect(summary.worst?.net).toBe(-100);
    expect(summary.best).toBeNull();
  });

  it("spots folding to most bets", () => {
    const timid = Array.from({ length: 10 }, (_, hand) =>
      record({
        hand,
        vpip: hand < 3,
        pfr: hand < 3,
        facedBets: 1,
        foldsToBets: hand < 9 ? 1 : 0,
      }),
    );
    expect(summarize(timid).tips.join(" ")).toContain(
      "You folded to 90% of bets",
    );
  });
});
