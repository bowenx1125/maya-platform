"""The card room's server-side Hold'em rules, case for case with the browser's."""

from __future__ import annotations

import random

import pytest
from app.modules.cardroom.engine import (
    Card,
    RuleError,
    Table,
    act,
    best_hand,
    create_table,
    evaluate_five,
    fresh_deck,
    hand_name,
    legal_actions,
    start_hand,
)

RANKS = {"A": 14, "K": 13, "Q": 12, "J": 11, "T": 10}


def card(text: str) -> Card:
    return Card(RANKS.get(text[0]) or int(text[0]), text[1])  # type: ignore[arg-type]


def cards(text: str) -> list[Card]:
    return [card(item) for item in text.split()]


def deck(holes: list[str], board: str) -> list[Card]:
    """A deck that deals ``holes`` in deal order, then ``board``, then the rest."""

    top = [card(hole.split()[0]) for hole in holes]
    top += [card(hole.split()[1]) for hole in holes]
    top += cards(board)
    return top + [c for c in fresh_deck() if c not in top]


def table(count: int, stack: int = 1000, small: int = 10, big: int = 20) -> Table:
    return create_table(
        [(f"p{i}", f"P{i}", None) for i in range(count)],
        stack=stack,
        small_blind=small,
        big_blind=big,
    )


def stacks(state: Table) -> list[int]:
    return [seat.stack for seat in state.seats]


def name(text: str) -> str:
    return hand_name(best_hand(cards(text)))


def test_names_every_category() -> None:
    assert name("As Ks Qs Js Ts 2d 3c") == "Royal Flush"
    assert name("9h 8h 7h 6h 5h Ad Ac") == "Straight Flush"
    assert name("9h 9d 9s 9c 2h 3d 4c") == "Four of a Kind"
    assert name("9h 9d 9s 2c 2h 3d 4c") == "Full House"
    assert name("Ah 9h 7h 4h 2h 3d Kc") == "Flush"
    assert name("Ah 2d 3s 4c 5h 9d Kc") == "Straight"
    assert name("9h 9d 9s 2c 5h 3d Kc") == "Three of a Kind"
    assert name("9h 9d 5s 5c 2h 3d Kc") == "Two Pair"
    assert name("9h 9d 5s 4c 2h Td Kc") == "Pair"
    assert name("Ah Jd 5s 4c 2h 8d Kc") == "High Card"


def test_wheel_is_lowest_straight_and_kickers_break_ties() -> None:
    assert evaluate_five(cards("Ah 2d 3s 4c 5h")) < evaluate_five(cards("2d 3s 4c 5h 6d"))
    assert evaluate_five(cards("9h 9d Ks 4c 2h")) > evaluate_five(cards("9s 9c Qs 4d 2d"))
    assert evaluate_five(cards("9h 9d Ks 4c 2h")) == evaluate_five(cards("9s 9c Kd 4d 2s"))


def test_heads_up_button_posts_small_and_big_blind_gets_option() -> None:
    state = start_hand(table(2), deck(["2c 7d", "9s 9h"], "Ks 8h 4d 3c Jh"))
    assert state.button == 0
    assert [seat.bet for seat in state.seats] == [10, 20]
    assert state.to_act == 0
    state = act(state, "call")
    assert state.street == "preflop" and state.to_act == 1
    assert legal_actions(state).can_check
    state = act(state, "check")
    assert state.street == "flop" and len(state.board) == 3
    assert state.to_act == 1


def test_last_player_standing_takes_the_blinds_without_showdown() -> None:
    state = start_hand(table(3))
    state = act(state, "fold")
    state = act(state, "fold")
    assert state.street == "complete" and not state.showdown
    # The big blind's last 10 was never called, so the pot won is 20.
    assert [(p.seat_id, p.amount, p.hand) for p in state.payouts] == [("p2", 20, None)]
    assert stacks(state) == [1000, 990, 1010]


def test_showdown_pays_the_best_hand() -> None:
    state = start_hand(table(3), deck(["Ks Kd", "2c 7d", "As Ad"], "Kh 8h 4d 3c Jh"))
    state = act(state, "call")
    state = act(state, "call")
    state = act(state, "check")
    for street in ("flop", "turn", "river"):
        assert state.street == street
        for _ in range(3):
            state = act(state, "check")
    assert state.showdown
    assert [(p.seat_id, p.amount, p.hand) for p in state.payouts] == [("p1", 60, "Three of a Kind")]
    assert sum(stacks(state)) == 3000


def test_tie_splits_with_odd_chip_left_of_button() -> None:
    state = start_hand(
        table(3, small=5, big=10),
        deck(["2c 7d", "3d 4h", "5s 6s"], "Ah Kh Qh Jc Tc"),
    )
    state = act(state, "call")
    state = act(state, "fold")
    state = act(state, "check")
    for _ in range(6):
        state = act(state, "check")
    paid = {p.seat_id: p.amount for p in state.payouts}
    assert paid == {"p2": 13, "p0": 12}
    assert sum(stacks(state)) == 3000


def test_side_pots_when_stacks_differ() -> None:
    state = table(3)
    for seat, chips in zip(state.seats, [300, 100, 200], strict=True):
        seat.stack = chips
    state = start_hand(state, deck(["As Ad", "Ks Kd", "2c 7h"], "9c 8d 4s 3h Jc"))
    state = act(state, "raise", 300)
    state = act(state, "call")
    state = act(state, "call")
    assert state.street == "complete" and len(state.board) == 5
    assert {p.seat_id: p.amount for p in state.payouts} == {"p1": 300, "p2": 200}
    assert stacks(state) == [100, 300, 200]


def test_refuses_raises_outside_the_rules() -> None:
    state = start_hand(table(2))
    with pytest.raises(RuleError):
        act(state, "raise", 30)
    with pytest.raises(RuleError):
        act(state, "raise", 2000)
    with pytest.raises(RuleError):
        act(state, "check")
    assert act(state, "raise", 40).current_bet == 40
    assert act(state, "raise", 1000).seats[0].all_in


def test_uncalled_bet_comes_back_before_the_pot_is_paid() -> None:
    state = start_hand(table(2))
    state = act(state, "call")
    state = act(state, "check")
    state = act(state, "raise", 100)
    state = act(state, "fold")
    assert [(p.seat_id, p.amount) for p in state.payouts] == [("p1", 40)]
    assert stacks(state) == [980, 1020]


def test_round_trips_through_json_shaped_data() -> None:
    state = act(start_hand(table(3)), "call")
    assert Table.from_dict(state.to_dict()) == state


def test_hundreds_of_random_hands_never_create_or_lose_a_chip() -> None:
    rng = random.Random(7)
    state = table(4)
    for _ in range(300):
        for seat in state.seats:
            if seat.stack == 0:
                seat.stack = 1000
        before = sum(stacks(state))
        state = start_hand(state, rng.sample(fresh_deck(), 52))
        guard = 0
        while state.to_act is not None:
            legal = legal_actions(state)
            roll = rng.random()
            if legal.can_raise and roll < 0.2:
                state = act(state, "raise", rng.randint(legal.min_raise_to, legal.max_raise_to))
            elif roll < 0.35:
                state = act(state, "fold")
            else:
                state = act(state, "check" if legal.can_check else "call")
            guard += 1
            assert guard < 200
        assert state.street == "complete"
        assert sum(stacks(state)) == before
