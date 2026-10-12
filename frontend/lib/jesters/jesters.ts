import type { Card } from "../poker/cards";
import type { HandKind } from "./score";

export type ScoreContext = {
  kind: HandKind;
  played: readonly Card[];
  scoring: readonly Card[];
  /** Hands left in the round, counting the one being played. */
  handsLeft: number;
  discardsLeft: number;
  jesterCount: number;
  /** Hands played earlier this run. */
  handsPlayed: number;
};

export type Effect = { chips?: number; mult?: number; times?: number };

export type JesterId =
  | "hypatia"
  | "laozi"
  | "plato"
  | "archimedes"
  | "socrates"
  | "sunzi"
  | "euclid"
  | "ibnSina"
  | "heraclitus"
  | "zhuangzi"
  | "pythagoras"
  | "confucius"
  | "aristotle"
  | "diogenes";

export type Jester = {
  id: JesterId;
  name: string;
  text: string;
  cost: number;
  /** Fires once for each scoring card, in order. */
  onCard?: (card: Card, context: ScoreContext) => Effect | null;
  /** Fires once per hand, after the cards. */
  onHand?: (context: ScoreContext) => Effect | null;
  /** Money for each card thrown away. */
  onDiscard?: (count: number) => number;
};

const PRIMES = new Set([2, 3, 5, 7]);
const isFace = (card: Card) => card.rank >= 11 && card.rank <= 13;

// The scholars Mayaform's classroom already knows, each with a habit that
// fits them. Effects are original to this game.
export const JESTERS: Record<JesterId, Jester> = {
  hypatia: {
    id: "hypatia",
    name: "Hypatia",
    text: "+3 Mult for each 2, 3, 5 or 7 scored",
    cost: 5,
    onCard: (card) => (PRIMES.has(card.rank) ? { mult: 3 } : null),
  },
  laozi: {
    id: "laozi",
    name: "Laozi",
    text: "+40 Chips if no face card is played",
    cost: 5,
    onHand: ({ played }) => (played.some(isFace) ? null : { chips: 40 }),
  },
  plato: {
    id: "plato",
    name: "Plato",
    text: "+10 Mult for a Flush",
    cost: 6,
    onHand: ({ kind }) =>
      kind === "flush" || kind === "straightFlush" ? { mult: 10 } : null,
  },
  archimedes: {
    id: "archimedes",
    name: "Archimedes",
    text: "+60 Chips for a Straight",
    cost: 6,
    onHand: ({ kind }) =>
      kind === "straight" || kind === "straightFlush" ? { chips: 60 } : null,
  },
  socrates: {
    id: "socrates",
    name: "Socrates",
    text: "+15 Chips for each discard left",
    cost: 4,
    onHand: ({ discardsLeft }) =>
      discardsLeft > 0 ? { chips: 15 * discardsLeft } : null,
  },
  sunzi: {
    id: "sunzi",
    name: "Sun Tzu",
    text: "+12 Mult when 3 or fewer cards are played",
    cost: 6,
    onHand: ({ played }) => (played.length <= 3 ? { mult: 12 } : null),
  },
  euclid: {
    id: "euclid",
    name: "Euclid",
    text: "+4 Mult for each even card scored",
    cost: 5,
    onCard: (card) =>
      card.rank <= 10 && card.rank % 2 === 0 ? { mult: 4 } : null,
  },
  ibnSina: {
    id: "ibnSina",
    name: "Ibn Sina",
    text: "Aces score +25 Chips",
    cost: 4,
    onCard: (card) => (card.rank === 14 ? { chips: 25 } : null),
  },
  heraclitus: {
    id: "heraclitus",
    name: "Heraclitus",
    text: "+1 Mult for every hand played this run",
    cost: 7,
    onHand: ({ handsPlayed }) =>
      handsPlayed > 0 ? { mult: handsPlayed } : null,
  },
  zhuangzi: {
    id: "zhuangzi",
    name: "Zhuangzi",
    text: "x2 Mult on the last hand of a round",
    cost: 7,
    onHand: ({ handsLeft }) => (handsLeft === 1 ? { times: 2 } : null),
  },
  pythagoras: {
    id: "pythagoras",
    name: "Pythagoras",
    text: "x3 Mult for Three of a Kind",
    cost: 7,
    onHand: ({ kind }) => (kind === "trips" ? { times: 3 } : null),
  },
  confucius: {
    id: "confucius",
    name: "Confucius",
    text: "+8 Mult if the hand holds a Pair",
    cost: 5,
    onHand: ({ kind }) =>
      kind === "pair" || kind === "twoPair" || kind === "fullHouse"
        ? { mult: 8 }
        : null,
  },
  aristotle: {
    id: "aristotle",
    name: "Aristotle",
    text: "+2 Mult for each Jester you hold",
    cost: 5,
    onHand: ({ jesterCount }) => ({ mult: 2 * jesterCount }),
  },
  diogenes: {
    id: "diogenes",
    name: "Diogenes",
    text: "Earn $1 for each card discarded",
    cost: 4,
    onDiscard: (count) => count,
  },
};

export const JESTER_IDS = Object.keys(JESTERS) as JesterId[];
