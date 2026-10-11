"""Texas Hold'em rules for an online card room, dealt by the server.

The same rules as the browser's practice table (frontend/lib/poker), held
here so that no player's browser ever sees the deck or another player's
cards before a showdown. State is plain data so it can be stored as JSON.
"""

from __future__ import annotations

import copy
import secrets
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from itertools import combinations
from typing import Any, Literal

Suit = Literal["s", "h", "d", "c"]
Street = Literal["waiting", "preflop", "flop", "turn", "river", "complete"]
ActionType = Literal["fold", "check", "call", "raise"]

SUITS: tuple[Suit, ...] = ("s", "h", "d", "c")
NAMES = (
    "High Card",
    "Pair",
    "Two Pair",
    "Three of a Kind",
    "Straight",
    "Flush",
    "Full House",
    "Four of a Kind",
    "Straight Flush",
)


class RuleError(ValueError):
    """An action the rules do not allow; never applied, never guessed at."""


@dataclass(frozen=True)
class Card:
    rank: int
    suit: Suit


@dataclass
class Seat:
    id: str
    name: str
    avatar: str | None = None
    stack: int = 0
    hole: list[Card] = field(default_factory=list)
    bet: int = 0
    contributed: int = 0
    folded: bool = False
    all_in: bool = False
    acted: bool = False
    sitting_out: bool = False
    last_action: str | None = None


@dataclass
class Payout:
    seat_id: str
    amount: int
    hand: str | None


@dataclass
class Table:
    seats: list[Seat]
    small_blind: int
    big_blind: int
    deck: list[Card] = field(default_factory=list)
    board: list[Card] = field(default_factory=list)
    button: int = -1
    to_act: int | None = None
    street: Street = "waiting"
    current_bet: int = 0
    min_raise: int = 0
    hand_number: int = 0
    payouts: list[Payout] = field(default_factory=list)
    showdown: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Table:
        def cards(items: list[dict[str, Any]]) -> list[Card]:
            return [Card(item["rank"], item["suit"]) for item in items]

        return cls(
            seats=[Seat(**{**seat, "hole": cards(seat["hole"])}) for seat in data["seats"]],
            small_blind=data["small_blind"],
            big_blind=data["big_blind"],
            deck=cards(data["deck"]),
            board=cards(data["board"]),
            button=data["button"],
            to_act=data["to_act"],
            street=data["street"],
            current_bet=data["current_bet"],
            min_raise=data["min_raise"],
            hand_number=data["hand_number"],
            payouts=[Payout(**payout) for payout in data["payouts"]],
            showdown=data["showdown"],
        )


@dataclass(frozen=True)
class Legal:
    can_check: bool
    to_call: int
    can_raise: bool
    min_raise_to: int
    max_raise_to: int


def fresh_deck() -> list[Card]:
    return [Card(rank, suit) for suit in SUITS for rank in range(2, 15)]


def shuffled_deck() -> list[Card]:
    deck = fresh_deck()
    # secrets.randbelow is unbiased and not predictable from earlier deals.
    for index in range(len(deck) - 1, 0, -1):
        other = secrets.randbelow(index + 1)
        deck[index], deck[other] = deck[other], deck[index]
    return deck


# --- hands -----------------------------------------------------------------


def evaluate_five(cards: Sequence[Card]) -> tuple[int, tuple[int, ...]]:
    """Category 0 (high card) to 8 (straight flush), then tie-break ranks."""

    if len(cards) != 5:
        raise RuleError("A hand is exactly five cards.")
    ranks = sorted((card.rank for card in cards), reverse=True)
    flush = len({card.suit for card in cards}) == 1
    distinct = sorted(set(ranks), reverse=True)
    straight = 0
    if len(distinct) == 5:
        if distinct[0] - distinct[4] == 4:
            straight = distinct[0]
        elif distinct == [14, 5, 4, 3, 2]:
            straight = 5
    counts: dict[int, int] = {}
    for rank in ranks:
        counts[rank] = counts.get(rank, 0) + 1
    groups = sorted(counts.items(), key=lambda item: (item[1], item[0]), reverse=True)
    by_group = tuple(rank for rank, _ in groups)

    if flush and straight:
        return 8, (straight,)
    if groups[0][1] == 4:
        return 7, by_group
    if groups[0][1] == 3 and groups[1][1] == 2:
        return 6, by_group
    if flush:
        return 5, tuple(ranks)
    if straight:
        return 4, (straight,)
    if groups[0][1] == 3:
        return 3, by_group
    if groups[0][1] == 2 and groups[1][1] == 2:
        return 2, by_group
    if groups[0][1] == 2:
        return 1, by_group
    return 0, tuple(ranks)


def best_hand(cards: Sequence[Card]) -> tuple[int, tuple[int, ...]]:
    if not 5 <= len(cards) <= 7:
        raise RuleError("Best hand needs five to seven cards.")
    return max(evaluate_five(five) for five in combinations(cards, 5))


def hand_name(value: tuple[int, tuple[int, ...]]) -> str:
    category, ranks = value
    return "Royal Flush" if category == 8 and ranks[0] == 14 else NAMES[category]


# --- the table ---------------------------------------------------------------


def create_table(
    players: Sequence[tuple[str, str, str | None]],
    *,
    stack: int,
    small_blind: int,
    big_blind: int,
) -> Table:
    return Table(
        seats=[
            Seat(id=pid, name=name, avatar=avatar, stack=stack) for pid, name, avatar in players
        ],
        small_blind=small_blind,
        big_blind=big_blind,
        min_raise=big_blind,
    )


def _in_hand(seat: Seat) -> bool:
    return not seat.sitting_out and not seat.folded


def _can_act(seat: Seat) -> bool:
    return _in_hand(seat) and not seat.all_in


def _next_seat(table: Table, start: int, test: Callable[[Seat], bool]) -> int:
    count = len(table.seats)
    for step in range(1, count + 1):
        index = (start + step) % count
        if test(table.seats[index]):
            return index
    return -1


def _put(seat: Seat, amount: int) -> None:
    chips = min(amount, seat.stack)
    seat.stack -= chips
    seat.bet += chips
    seat.contributed += chips
    if seat.stack == 0:
        seat.all_in = True


def _draw(table: Table) -> Card:
    if not table.deck:
        raise RuleError("The deck ran out.")
    return table.deck.pop(0)


def start_hand(previous: Table, deck: list[Card] | None = None) -> Table:
    """Deal a new hand. ``deck`` is for tests; play shuffles a fresh one."""

    if previous.street not in ("waiting", "complete"):
        raise RuleError("A hand is already being played.")
    table = copy.deepcopy(previous)
    for seat in table.seats:
        seat.hole = []
        seat.bet = 0
        seat.contributed = 0
        seat.folded = False
        seat.all_in = False
        seat.acted = False
        seat.last_action = None
        seat.sitting_out = seat.stack <= 0
    live = [seat for seat in table.seats if not seat.sitting_out]
    if len(live) < 2:
        raise RuleError("A hand needs two players with chips.")

    table.deck = list(deck) if deck is not None else shuffled_deck()
    table.board = []
    table.payouts = []
    table.showdown = False
    table.hand_number += 1
    table.street = "preflop"

    def seated(seat: Seat) -> bool:
        return not seat.sitting_out

    table.button = _next_seat(table, table.button, seated)
    # Heads-up the button is the small blind and acts first before the flop.
    small = table.button if len(live) == 2 else _next_seat(table, table.button, seated)
    big = _next_seat(table, small, seated)
    _put(table.seats[small], table.small_blind)
    _put(table.seats[big], table.big_blind)

    for _ in range(2):
        index = table.button
        for _ in live:
            index = _next_seat(table, index, seated)
            table.seats[index].hole.append(_draw(table))

    table.current_bet = table.big_blind
    table.min_raise = table.big_blind
    return _advance(table, big)


def legal_actions(table: Table) -> Legal:
    if table.to_act is None:
        raise RuleError("Nobody is to act.")
    seat = table.seats[table.to_act]
    to_call = min(table.current_bet - seat.bet, seat.stack)
    max_to = seat.bet + seat.stack
    return Legal(
        can_check=to_call == 0,
        to_call=to_call,
        can_raise=max_to > table.current_bet,
        min_raise_to=min(table.current_bet + table.min_raise, max_to),
        max_raise_to=max_to,
    )


def act(previous: Table, action: ActionType, to: int | None = None) -> Table:
    legal = legal_actions(previous)
    table = copy.deepcopy(previous)
    index = table.to_act
    assert index is not None
    seat = table.seats[index]

    if action == "fold":
        seat.folded = True
        seat.last_action = "Fold"
    elif action == "check":
        if not legal.can_check:
            raise RuleError("There is a bet to call.")
        seat.last_action = "Check"
    elif action == "call":
        if legal.to_call == 0:
            raise RuleError("Nothing to call; check.")
        _put(seat, legal.to_call)
        seat.last_action = "All in" if seat.all_in else f"Call {legal.to_call}"
    elif action == "raise":
        if not legal.can_raise or to is None:
            raise RuleError("No raise is possible.")
        # Below the minimum is only allowed as an all-in for less.
        if to > legal.max_raise_to or (to < legal.min_raise_to and to != legal.max_raise_to):
            raise RuleError("That raise is not allowed.")
        raised_by = to - table.current_bet
        opening = table.current_bet == 0
        _put(seat, to - seat.bet)
        if raised_by >= table.min_raise:
            # A full raise reopens the betting for everyone still able to act.
            table.min_raise = raised_by
            for other in table.seats:
                if other is not seat:
                    other.acted = False
        else:
            # An all-in for less only obliges those now behind to answer it.
            for other in table.seats:
                if other is not seat and other.bet < to:
                    other.acted = False
        table.current_bet = to
        seat.last_action = "All in" if seat.all_in else f"{'Bet' if opening else 'Raise'} {to}"
    else:
        raise RuleError("Unknown action.")
    seat.acted = True
    return _advance(table, index)


def _advance(table: Table, start: int) -> Table:
    """Move to the next player, the next street, or the end of the hand."""

    if sum(1 for seat in table.seats if _in_hand(seat)) == 1:
        return _finish(table)
    actors = [seat for seat in table.seats if _can_act(seat)]
    highest = max(seat.bet for seat in table.seats if _in_hand(seat))
    round_done = (
        not actors
        or all(seat.acted and seat.bet == table.current_bet for seat in actors)
        or (len(actors) == 1 and actors[0].bet >= highest)
    )
    if not round_done:
        table.to_act = _next_seat(
            table,
            start,
            lambda seat: _can_act(seat) and (not seat.acted or seat.bet < table.current_bet),
        )
        return table

    for seat in table.seats:
        seat.bet = 0
        seat.acted = False
    table.current_bet = 0
    table.min_raise = table.big_blind
    following: dict[str, Street] = {"preflop": "flop", "flop": "turn", "turn": "river"}
    # Deal the next street; when at most one player can still bet, run the
    # board out to the river without stopping.
    while True:
        if table.street == "river":
            return _finish(table)
        table.street = following[table.street]
        for _ in range(3 if table.street == "flop" else 1):
            table.board.append(_draw(table))
        if sum(1 for seat in table.seats if _can_act(seat)) >= 2:
            table.to_act = _next_seat(table, table.button, _can_act)
            return table


def _finish(table: Table) -> Table:
    """Build the pots from what everyone put in and pay each to its best hand."""

    # A bet nobody matched was never contested: it goes straight back, so the
    # pots and the winners shown are only what was actually won.
    ordered = sorted((seat.contributed for seat in table.seats), reverse=True)
    top, second = ordered[0], (ordered[1] if len(ordered) > 1 else 0)
    if top > second:
        leader = next(seat for seat in table.seats if seat.contributed == top)
        leader.contributed -= top - second
        leader.stack += top - second

    contenders = [seat for seat in table.seats if _in_hand(seat)]
    showdown = len(contenders) > 1
    values = (
        {seat.id: best_hand([*seat.hole, *table.board]) for seat in contenders} if showdown else {}
    )

    def distance(seat: Seat) -> int:
        count = len(table.seats)
        return (table.seats.index(seat) - table.button - 1) % count

    won: dict[str, int] = {}
    floor = 0
    for level in sorted({seat.contributed for seat in table.seats if seat.contributed > 0}):
        amount = sum(max(0, min(seat.contributed, level) - floor) for seat in table.seats)
        eligible = [seat for seat in contenders if seat.contributed >= level]
        # Every layer left after the refund has someone still in the hand; if
        # that ever fails, the chips go back to who put them in, never nowhere.
        winners = eligible or [seat for seat in table.seats if seat.contributed >= level]
        if showdown and len(eligible) > 1:
            best = max(values[seat.id] for seat in winners)
            winners = [seat for seat in winners if values[seat.id] == best]
        # Odd chips go one at a time to the winners nearest the button's left.
        winners = sorted(winners, key=distance)
        share, odd = divmod(amount, len(winners))
        for position, seat in enumerate(winners):
            won[seat.id] = won.get(seat.id, 0) + share + (1 if position < odd else 0)
        floor = level

    for seat in table.seats:
        seat.stack += won.get(seat.id, 0)
        seat.bet = 0
    table.payouts = [
        Payout(
            seat_id=seat_id,
            amount=amount,
            hand=hand_name(values[seat_id]) if showdown and seat_id in values else None,
        )
        for seat_id, amount in won.items()
    ]
    table.showdown = showdown
    table.street = "complete"
    table.to_act = None
    table.current_bet = 0
    return table


def pot(table: Table) -> int:
    return sum(seat.contributed for seat in table.seats)
