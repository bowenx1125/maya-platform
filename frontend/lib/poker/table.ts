import { freshDeck, shuffle, type Card } from "./cards";
import { bestHand, compareHands, handName, type HandValue } from "./hand";

export type Player = {
  id: string;
  name: string;
  avatar?: string | null;
  human: boolean;
};

export type Seat = Player & {
  stack: number;
  hole: Card[];
  /** Chips put in on the current street. */
  bet: number;
  /** Chips put in over the whole hand; pots are built from this. */
  contributed: number;
  folded: boolean;
  allIn: boolean;
  /** Has acted since the last full raise on this street. */
  acted: boolean;
  sittingOut: boolean;
  lastAction: string | null;
};

export type Street =
  "waiting" | "preflop" | "flop" | "turn" | "river" | "complete";

export type Payout = { seatId: string; amount: number; hand: string | null };

export type TableState = {
  seats: Seat[];
  deck: Card[];
  board: Card[];
  button: number;
  toAct: number | null;
  street: Street;
  currentBet: number;
  /** Smallest raise increment allowed now: the last full raise, at least the big blind. */
  minRaise: number;
  smallBlind: number;
  bigBlind: number;
  handNumber: number;
  payouts: Payout[];
  /** True once the hand reached a showdown, so live hole cards are shown. */
  showdown: boolean;
};

export type Action =
  | { type: "fold" }
  | { type: "check" }
  | { type: "call" }
  | { type: "raise"; to: number };

export type LegalActions = {
  canCheck: boolean;
  toCall: number;
  canRaise: boolean;
  minRaiseTo: number;
  maxRaiseTo: number;
};

export function createTable(
  players: readonly Player[],
  { stack = 1000, smallBlind = 10, bigBlind = 20 } = {},
): TableState {
  return {
    seats: players.map((player) => ({
      ...player,
      stack,
      hole: [],
      bet: 0,
      contributed: 0,
      folded: false,
      allIn: false,
      acted: false,
      sittingOut: false,
      lastAction: null,
    })),
    deck: [],
    board: [],
    button: -1,
    toAct: null,
    street: "waiting",
    currentBet: 0,
    minRaise: bigBlind,
    smallBlind,
    bigBlind,
    handNumber: 0,
    payouts: [],
    showdown: false,
  };
}

const inHand = (seat: Seat) => !seat.sittingOut && !seat.folded;
const canAct = (seat: Seat) => inHand(seat) && !seat.allIn;

function clone(state: TableState): TableState {
  return {
    ...state,
    seats: state.seats.map((seat) => ({ ...seat, hole: [...seat.hole] })),
    deck: [...state.deck],
    board: [...state.board],
    payouts: [...state.payouts],
  };
}

/** The next seat after `from`, going round the table, that passes `test`. */
function nextSeat(
  state: TableState,
  from: number,
  test: (seat: Seat) => boolean,
): number {
  const count = state.seats.length;
  for (let step = 1; step <= count; step += 1) {
    const index = (((from + step) % count) + count) % count;
    if (test(state.seats[index])) return index;
  }
  return -1;
}

function put(seat: Seat, amount: number) {
  const chips = Math.min(amount, seat.stack);
  seat.stack -= chips;
  seat.bet += chips;
  seat.contributed += chips;
  if (seat.stack === 0) seat.allIn = true;
}

function draw(state: TableState): Card {
  const card = state.deck.shift();
  if (!card) throw new Error("The deck ran out.");
  return card;
}

/** Deal a new hand. `deck` is for tests; play shuffles a fresh one. */
export function startHand(
  previous: TableState,
  deck: Card[] = shuffle(freshDeck()),
): TableState {
  if (previous.street !== "waiting" && previous.street !== "complete")
    throw new Error("A hand is already being played.");
  const state = clone(previous);
  for (const seat of state.seats) {
    Object.assign(seat, {
      hole: [],
      bet: 0,
      contributed: 0,
      folded: false,
      allIn: false,
      acted: false,
      lastAction: null,
      sittingOut: seat.stack <= 0,
    });
  }
  const live = state.seats.filter((seat) => !seat.sittingOut);
  if (live.length < 2) throw new Error("A hand needs two players with chips.");

  state.deck = [...deck];
  state.board = [];
  state.payouts = [];
  state.showdown = false;
  state.handNumber += 1;
  state.street = "preflop";
  state.button = nextSeat(state, state.button, (seat) => !seat.sittingOut);
  // Heads-up the button is the small blind and acts first before the flop.
  const smallBlind =
    live.length === 2
      ? state.button
      : nextSeat(state, state.button, (seat) => !seat.sittingOut);
  const bigBlind = nextSeat(state, smallBlind, (seat) => !seat.sittingOut);
  put(state.seats[smallBlind], state.smallBlind);
  put(state.seats[bigBlind], state.bigBlind);

  for (let round = 0; round < 2; round += 1) {
    let index = state.button;
    for (let dealt = 0; dealt < live.length; dealt += 1) {
      index = nextSeat(state, index, (seat) => !seat.sittingOut);
      state.seats[index].hole.push(draw(state));
    }
  }

  state.currentBet = state.bigBlind;
  state.minRaise = state.bigBlind;
  return advance(state, bigBlind);
}

export function legalActions(state: TableState): LegalActions {
  if (state.toAct === null) throw new Error("Nobody is to act.");
  const seat = state.seats[state.toAct];
  const toCall = Math.min(state.currentBet - seat.bet, seat.stack);
  const maxRaiseTo = seat.bet + seat.stack;
  return {
    canCheck: toCall === 0,
    toCall,
    canRaise: maxRaiseTo > state.currentBet,
    minRaiseTo: Math.min(state.currentBet + state.minRaise, maxRaiseTo),
    maxRaiseTo,
  };
}

export function act(previous: TableState, action: Action): TableState {
  const legal = legalActions(previous);
  const state = clone(previous);
  const index = state.toAct as number;
  const seat = state.seats[index];

  switch (action.type) {
    case "fold":
      seat.folded = true;
      seat.lastAction = "Fold";
      break;
    case "check":
      if (!legal.canCheck) throw new Error("There is a bet to call.");
      seat.lastAction = "Check";
      break;
    case "call":
      if (legal.toCall === 0) throw new Error("Nothing to call; check.");
      put(seat, legal.toCall);
      seat.lastAction = seat.allIn ? "All in" : `Call ${legal.toCall}`;
      break;
    case "raise": {
      const to = action.to;
      if (!legal.canRaise || !Number.isInteger(to))
        throw new Error("No raise is possible.");
      // Below the minimum is only allowed as an all-in for less.
      if (
        to > legal.maxRaiseTo ||
        (to < legal.minRaiseTo && to !== legal.maxRaiseTo)
      )
        throw new Error("That raise is not allowed.");
      const raisedBy = to - state.currentBet;
      const opening = state.currentBet === 0;
      put(seat, to - seat.bet);
      if (raisedBy >= state.minRaise) {
        // A full raise reopens the betting for everyone still able to act.
        state.minRaise = raisedBy;
        for (const other of state.seats)
          if (other !== seat) other.acted = false;
      } else {
        // An all-in for less only obliges those now behind to answer it.
        for (const other of state.seats)
          if (other !== seat && other.bet < to) other.acted = false;
      }
      state.currentBet = to;
      seat.lastAction = seat.allIn
        ? "All in"
        : `${opening ? "Bet" : "Raise"} ${to}`;
      break;
    }
  }
  seat.acted = true;
  return advance(state, index);
}

/** Move to the next player, the next street, or the end of the hand. */
function advance(state: TableState, from: number): TableState {
  if (state.seats.filter(inHand).length === 1) return finish(state);

  const actors = state.seats.filter(canAct);
  const highest = Math.max(
    ...state.seats.filter(inHand).map((seat) => seat.bet),
  );
  const roundDone =
    actors.length === 0 ||
    actors.every((seat) => seat.acted && seat.bet === state.currentBet) ||
    (actors.length === 1 && actors[0].bet >= highest);

  if (!roundDone) {
    state.toAct = nextSeat(
      state,
      from,
      (seat) => canAct(seat) && (!seat.acted || seat.bet < state.currentBet),
    );
    return state;
  }

  for (const seat of state.seats) {
    seat.bet = 0;
    seat.acted = false;
  }
  state.currentBet = 0;
  state.minRaise = state.bigBlind;

  // Deal the next street; when at most one player can still bet, run the
  // board out to the river without stopping.
  for (;;) {
    if (state.street === "river") return finish(state);
    const next = { preflop: "flop", flop: "turn", turn: "river" } as const;
    const street = next[state.street as keyof typeof next];
    state.street = street;
    const count = street === "flop" ? 3 : 1;
    for (let card = 0; card < count; card += 1) state.board.push(draw(state));
    if (state.seats.filter(canAct).length >= 2) {
      state.toAct = nextSeat(state, state.button, canAct);
      return state;
    }
  }
}

/** Build the pots from what everyone put in and pay each to its best hand. */
function finish(state: TableState): TableState {
  // A bet nobody matched was never contested: it goes straight back, so the
  // pots and the winners shown are only what was actually won.
  const [top, second = 0] = state.seats
    .map((seat) => seat.contributed)
    .sort((a, b) => b - a);
  const leader = state.seats.find((seat) => seat.contributed === top);
  if (leader && top > second) {
    leader.contributed -= top - second;
    leader.stack += top - second;
  }

  const contenders = state.seats.filter(inHand);
  const showdown = contenders.length > 1;
  const values = new Map<string, HandValue>();
  if (showdown)
    for (const seat of contenders)
      values.set(seat.id, bestHand([...seat.hole, ...state.board]));
  const valueOf = (seat: Seat) => {
    const value = values.get(seat.id);
    if (!value) throw new Error("A contender has no hand.");
    return value;
  };

  const won = new Map<string, number>();
  const levels = [
    ...new Set(
      state.seats.map((seat) => seat.contributed).filter((n) => n > 0),
    ),
  ].sort((a, b) => a - b);
  let floor = 0;
  for (const level of levels) {
    const amount = state.seats.reduce(
      (sum, seat) =>
        sum + Math.max(0, Math.min(seat.contributed, level) - floor),
      0,
    );
    const eligible = contenders.filter((seat) => seat.contributed >= level);
    // Every layer left after the refund has someone still in the hand; if
    // that ever fails, the chips go back to who put them in, never nowhere.
    let winners = eligible.length
      ? eligible
      : state.seats.filter((seat) => seat.contributed >= level);
    if (showdown && eligible.length > 1) {
      const best = winners.reduce((leading, seat) =>
        compareHands(valueOf(seat), valueOf(leading)) > 0 ? seat : leading,
      );
      winners = winners.filter(
        (seat) => compareHands(valueOf(seat), valueOf(best)) === 0,
      );
    }
    // Odd chips go one at a time to the winners nearest the button's left.
    const ordered = [...winners].sort(
      (a, b) => distanceFromButton(state, a) - distanceFromButton(state, b),
    );
    const share = Math.floor(amount / ordered.length);
    let odd = amount - share * ordered.length;
    for (const seat of ordered) {
      const extra = odd > 0 ? 1 : 0;
      odd -= extra;
      won.set(seat.id, (won.get(seat.id) ?? 0) + share + extra);
    }
    floor = level;
  }

  for (const seat of state.seats) {
    seat.stack += won.get(seat.id) ?? 0;
    seat.bet = 0;
  }
  state.payouts = [...won.entries()].map(([seatId, amount]) => {
    const value = values.get(seatId);
    return { seatId, amount, hand: showdown && value ? handName(value) : null };
  });
  state.showdown = showdown;
  state.street = "complete";
  state.toAct = null;
  state.currentBet = 0;
  return state;
}

function distanceFromButton(state: TableState, seat: Seat): number {
  const count = state.seats.length;
  const index = state.seats.indexOf(seat);
  return (index - state.button - 1 + count) % count;
}

/** Top a seat up between hands ("add chips"). */
export function addChips(
  previous: TableState,
  seatId: string,
  amount: number,
): TableState {
  if (previous.street !== "waiting" && previous.street !== "complete")
    throw new Error("Chips can only be added between hands.");
  if (!Number.isInteger(amount) || amount <= 0)
    throw new Error("Add a positive whole number of chips.");
  const state = clone(previous);
  const seat = state.seats.find((candidate) => candidate.id === seatId);
  if (!seat) throw new Error("No such seat.");
  seat.stack += amount;
  seat.sittingOut = false;
  return state;
}

export function pot(state: TableState): number {
  return state.seats.reduce((sum, seat) => sum + seat.contributed, 0);
}

export function describeHand(
  seat: Seat,
  board: readonly Card[],
): string | null {
  const cards = [...seat.hole, ...board];
  return cards.length >= 5 ? handName(bestHand(cards)) : null;
}
