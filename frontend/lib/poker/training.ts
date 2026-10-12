import { preflopStrength } from "./bot";
import type { Card } from "./cards";
import type { Action, Street, TableState } from "./table";

/** One of the player's own decisions, with what it cost to stay in. */
export type Decision = { street: Street; toCall: number; type: Action["type"] };

export type HandRecord = {
  hand: number;
  hole: Card[];
  board: Card[];
  /** Rough 0–1 strength of the two cards dealt, as the bots judge it. */
  strength: number;
  /** Put chips in before the flop by choice, not just by posting a blind. */
  vpip: boolean;
  /** Raised before the flop. */
  pfr: boolean;
  sawFlop: boolean;
  showdown: boolean;
  won: boolean;
  facedBets: number;
  foldsToBets: number;
  /** Bets and raises after the flop. */
  aggressive: number;
  /** Calls after the flop. */
  passive: number;
  net: number;
};

export type Summary = {
  hands: number;
  vpip: number;
  pfr: number;
  foldToBet: number | null;
  showdownWin: number | null;
  aggression: number | null;
  net: number;
  best: HandRecord | null;
  worst: HandRecord | null;
  tips: string[];
};

/** The human's decision as it was taken, before it changes the table. */
export function decision(state: TableState, action: Action): Decision {
  const seat = state.toAct === null ? null : state.seats[state.toAct];
  const toCall = seat ? Math.max(0, state.currentBet - seat.bet) : 0;
  return { street: state.street, toCall, type: action.type };
}

/** Close a finished hand from the player's decisions and the final table. */
export function closeHand(
  final: TableState,
  seatId: string,
  stackBefore: number,
  decisions: readonly Decision[],
): HandRecord {
  const seat = final.seats.find((candidate) => candidate.id === seatId);
  if (!seat || final.street !== "complete")
    throw new Error("Only a finished hand can be recorded.");
  const preflop = decisions.filter((choice) => choice.street === "preflop");
  const postflop = decisions.filter((choice) => choice.street !== "preflop");
  const foldedPreflop = preflop.some((choice) => choice.type === "fold");
  const faced = decisions.filter((choice) => choice.toCall > 0);
  return {
    hand: final.handNumber,
    hole: seat.hole,
    board: final.board,
    strength: seat.hole.length === 2 ? preflopStrength(seat.hole) : 0,
    vpip: preflop.some(
      (choice) => choice.type === "call" || choice.type === "raise",
    ),
    pfr: preflop.some((choice) => choice.type === "raise"),
    sawFlop: !foldedPreflop && final.board.length >= 3 && decisions.length > 0,
    showdown: final.showdown && !seat.folded,
    won: final.payouts.some((payout) => payout.seatId === seatId),
    facedBets: faced.length,
    foldsToBets: faced.filter((choice) => choice.type === "fold").length,
    aggressive: postflop.filter((choice) => choice.type === "raise").length,
    passive: postflop.filter((choice) => choice.type === "call").length,
    net: seat.stack - stackBefore,
  };
}

const share = (part: number, whole: number) => (whole ? part / whole : 0);
const percent = (value: number) => `${Math.round(value * 100)}%`;
/** Below this many hands a habit is noise, so no advice is drawn from it. */
const ENOUGH = 8;

export function summarize(records: readonly HandRecord[]): Summary {
  const hands = records.length;
  const vpip = share(records.filter((record) => record.vpip).length, hands);
  const pfr = share(records.filter((record) => record.pfr).length, hands);
  const faced = records.reduce((sum, record) => sum + record.facedBets, 0);
  const folded = records.reduce((sum, record) => sum + record.foldsToBets, 0);
  const showdowns = records.filter((record) => record.showdown);
  const aggressive = records.reduce(
    (sum, record) => sum + record.aggressive,
    0,
  );
  const passive = records.reduce((sum, record) => sum + record.passive, 0);
  const net = records.reduce((sum, record) => sum + record.net, 0);
  const byNet = [...records].sort((a, b) => b.net - a.net);
  const weak = records.filter((record) => record.vpip && record.strength < 0.4);
  const weakNet = weak.reduce((sum, record) => sum + record.net, 0);

  const summary: Summary = {
    hands,
    vpip,
    pfr,
    foldToBet: faced ? folded / faced : null,
    showdownWin: showdowns.length
      ? showdowns.filter((record) => record.won).length / showdowns.length
      : null,
    aggression: passive ? aggressive / passive : aggressive ? aggressive : null,
    net,
    best: byNet[0] && byNet[0].net > 0 ? byNet[0] : null,
    worst:
      byNet.at(-1) && (byNet.at(-1)?.net ?? 0) < 0
        ? (byNet.at(-1) ?? null)
        : null,
    tips: [],
  };

  // Each tip names the habit and the number behind it, most costly first.
  const tips: { weight: number; text: string }[] = [];
  if (hands >= ENOUGH && vpip > 0.45)
    tips.push({
      weight: 3 + Math.max(0, -weakNet) / 1000,
      text: `You played ${percent(vpip)} of hands. Fold weak starts${
        weakNet < 0 ? `: ${weak.length} of them cost you ${-weakNet}` : ""
      }.`,
    });
  if (hands >= ENOUGH && vpip < 0.15)
    tips.push({
      weight: 2,
      text: `You played only ${percent(vpip)} of hands. Defend your blinds and play suited, connected cards more often.`,
    });
  if (hands >= ENOUGH && vpip >= 0.15 && pfr / vpip < 0.35)
    tips.push({
      weight: 2.5,
      text: `You raised only ${percent(pfr)} of hands before the flop. Raise your strong starts instead of calling.`,
    });
  if (faced >= 5 && folded / faced > 0.65)
    tips.push({
      weight: 2,
      text: `You folded to ${percent(folded / faced)} of bets. Call more often with a pair or a strong draw.`,
    });
  if (showdowns.length >= 4 && (summary.showdownWin ?? 1) < 0.4)
    tips.push({
      weight: 2.8,
      text: `You won ${percent(summary.showdownWin ?? 0)} of showdowns. Stop calling to the river with weak pairs.`,
    });
  if (passive >= 4 && aggressive / passive < 0.5)
    tips.push({
      weight: 1.5,
      text: "After the flop you call far more than you bet. Bet your made hands.",
    });
  summary.tips = tips
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 3)
    .map((tip) => tip.text);
  if (!summary.tips.length && hands >= ENOUGH)
    summary.tips = [
      net >= 0
        ? "A disciplined session. Keep choosing your hands the same way."
        : "No single leak stands out. Play more hands to see a pattern.",
    ];
  return summary;
}
