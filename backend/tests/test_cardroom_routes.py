import json
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.models import Course
from app.modules.cardroom.models import CardRoom
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login


class Player:
    def __init__(self, client: TestClient, username: str) -> None:
        self.client = client
        payload, self.csrf = login(client, username)
        self.id: str = payload["user"]["id"]

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        headers = {"Origin": "http://testserver", "X-CSRF-Token": self.csrf}
        return self.client.post(f"/api/v1{path}", json=body, headers=headers)

    def delete(self, path: str) -> Any:
        headers = {"Origin": "http://testserver", "X-CSRF-Token": self.csrf}
        return self.client.delete(f"/api/v1{path}", headers=headers)

    def get(self, path: str) -> Any:
        return self.client.get(f"/api/v1{path}")


@pytest.fixture
def players(app_bundle: tuple[FastAPI, Database, Any]) -> Iterator[Callable[[str], Player]]:
    app = app_bundle[0]
    with ExitStack() as stack:

        def sign_in(username: str) -> Player:
            return Player(stack.enter_context(TestClient(app)), username)

        yield sign_in


def _edit(database: Database, code: str, change: Callable[[dict[str, Any]], None]) -> None:
    """Move a room's clock by hand, as if time had passed."""

    with database.session() as db:
        room = db.scalar(
            select(CardRoom).where(CardRoom.code == code, CardRoom.closed_at.is_(None))
        )
        assert room is not None
        state = json.loads(room.state_json)
        change(state)
        room.state_json = json.dumps(state)


def _past(seconds: int = 1) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


def _table(players: Callable[[str], Player], *names: str) -> tuple[list[Player], str]:
    seated = [players(name) for name in names]
    created = seated[0].post("/card-rooms")
    assert created.status_code == 201, created.text
    code = created.json()["code"]
    for player in seated[1:]:
        assert player.post(f"/card-rooms/{code}/seat").status_code == 200
    return seated, code


def test_a_room_is_opened_joined_by_code_and_dealt_by_the_host(
    players: Callable[[str], Player],
) -> None:
    (maya, bowen, jade), code = _table(players, "maya", "bowen", "jade")
    assert len(code) == 4 and code.isdigit()
    # Opening again brings the host back to the room they already have.
    assert maya.post("/card-rooms").json()["code"] == code

    waiting = bowen.get(f"/card-rooms/{code}").json()
    assert waiting["status"] == "waiting"
    assert [seat["host"] for seat in waiting["seats"]] == [True, False, False]
    assert waiting["you"] == 1

    refused = bowen.post(f"/card-rooms/{code}/start")
    assert refused.status_code == 403
    started = maya.post(f"/card-rooms/{code}/start")
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "playing"
    assert started.json()["street"] == "preflop"
    assert started.json()["pot"] == 30
    assert maya.post(f"/card-rooms/{code}/start").json()["code"] == "card_room_started"

    # Everyone sees their own two cards and only the count of anyone else's.
    for index, player in enumerate((maya, bowen, jade)):
        view = player.get(f"/card-rooms/{code}").json()
        assert "deck" not in json.dumps(view)
        for seat_index, seat in enumerate(view["seats"]):
            assert seat["hole_count"] == 2
            assert len(seat["hole"]) == (2 if seat_index == index else 0)


def test_only_the_player_to_act_moves_and_only_on_the_table_they_saw(
    players: Callable[[str], Player],
) -> None:
    seated, code = _table(players, "maya", "bowen")
    view = seated[0].post(f"/card-rooms/{code}/start").json()
    turn = seated[view["to_act"]]
    other = seated[1 - view["to_act"]]
    assert view["legal"] is None or turn is seated[0]

    waiting = other.post(
        f"/card-rooms/{code}/actions", {"type": "call", "expected_revision": view["revision"]}
    )
    assert waiting.json()["code"] == "card_room_not_your_turn"
    stale = turn.post(
        f"/card-rooms/{code}/actions", {"type": "call", "expected_revision": view["revision"] - 1}
    )
    assert stale.json()["code"] == "stale_revision"
    illegal = turn.post(
        f"/card-rooms/{code}/actions", {"type": "check", "expected_revision": view["revision"]}
    )
    assert illegal.json()["code"] == "card_room_illegal_action"

    own = turn.get(f"/card-rooms/{code}").json()
    assert own["legal"]["to_call"] == 10
    called = turn.post(
        f"/card-rooms/{code}/actions", {"type": "call", "expected_revision": own["revision"]}
    )
    assert called.status_code == 200, called.text
    assert called.json()["revision"] == own["revision"] + 1
    assert called.json()["to_act"] == seated.index(other)


def test_the_clock_checks_or_folds_and_two_misses_take_you_off_the_table(
    players: Callable[[str], Player], database: Database
) -> None:
    seated, code = _table(players, "maya", "bowen", "jade")
    view = seated[0].post(f"/card-rooms/{code}/start").json()
    late = view["to_act"]

    def expire(state: dict[str, Any]) -> None:
        state["deadline"] = _past()

    _edit(database, code, expire)
    after = seated[1].get(f"/card-rooms/{code}").json()
    assert after["seats"][late]["folded"] is True
    assert after["seats"][late]["last_action"] == "Fold"
    assert after["to_act"] != late
    # A move made on the table from before the clock ran out is refused.
    refused = seated[late].post(
        f"/card-rooms/{code}/actions", {"type": "call", "expected_revision": view["revision"]}
    )
    assert refused.json()["code"] == "stale_revision"

    # Let everyone's clock run out until the hand is over, then deal the next.
    for _ in range(6):
        current = seated[0].get(f"/card-rooms/{code}").json()
        if current["street"] == "complete":
            break
        _edit(database, code, expire)
    finished = seated[0].get(f"/card-rooms/{code}").json()
    assert finished["street"] == "complete"
    assert finished["next_hand_at"] is not None

    def deal(state: dict[str, Any]) -> None:
        state["next_hand_at"] = _past()

    _edit(database, code, deal)
    second = seated[0].get(f"/card-rooms/{code}").json()
    assert second["hand_number"] == 2
    assert second["street"] == "preflop"


def test_two_missed_turns_in_a_row_remove_a_player_between_hands(
    players: Callable[[str], Player], database: Database
) -> None:
    seated, code = _table(players, "maya", "bowen", "jade")
    view = seated[0].post(f"/card-rooms/{code}/start").json()
    late = seated[view["to_act"]].id

    def missed_twice(state: dict[str, Any]) -> None:
        state["missed"][late] = 1
        state["deadline"] = _past()

    _edit(database, code, missed_twice)
    after = seated[0].get(f"/card-rooms/{code}").json()
    gone = next(seat for seat in after["seats"] if seat["user_id"] == late)
    assert gone["leaving"] is True

    # Finish the hand by the clock and deal again: the late player is gone.
    for _ in range(8):
        current = seated[0].get(f"/card-rooms/{code}").json()
        if current["hand_number"] == 2:
            break

        def tick(state: dict[str, Any]) -> None:
            state["deadline"] = _past() if state["deadline"] else None
            state["next_hand_at"] = _past() if state["next_hand_at"] else None

        _edit(database, code, tick)
    second = seated[0].get(f"/card-rooms/{code}").json()
    assert second["hand_number"] == 2
    assert late not in {seat["user_id"] for seat in second["seats"]}


def test_leaving_moves_the_host_and_the_last_one_out_closes_the_room(
    players: Callable[[str], Player],
) -> None:
    (maya, bowen), code = _table(players, "maya", "bowen")
    assert maya.delete(f"/card-rooms/{code}/seat").status_code == 204
    view = bowen.get(f"/card-rooms/{code}").json()
    assert [seat["user_id"] for seat in view["seats"]] == [bowen.id]
    assert view["seats"][0]["host"] is True
    assert bowen.delete(f"/card-rooms/{code}/seat").status_code == 204
    assert bowen.get(f"/card-rooms/{code}").status_code == 404
    assert maya.post(f"/card-rooms/{code}/seat").status_code == 404


def test_leaving_mid_hand_folds_and_the_seat_goes_after_the_hand(
    players: Callable[[str], Player],
) -> None:
    seated, code = _table(players, "maya", "bowen", "jade")
    view = seated[0].post(f"/card-rooms/{code}/start").json()
    leaver = seated[view["to_act"]]
    assert leaver.delete(f"/card-rooms/{code}/seat").status_code == 204
    after = seated[0].get(f"/card-rooms/{code}").json()
    seat = next(seat for seat in after["seats"] if seat["user_id"] == leaver.id)
    assert seat["folded"] is True
    assert seat["leaving"] is True


def test_another_courses_room_does_not_exist(
    players: Callable[[str], Player], database: Database
) -> None:
    (maya,), code = _table(players, "maya")
    with database.session() as db:
        other = str(uuid4())
        db.add(Course(id=other, code="other-course", name="Other", created_at=datetime.now(UTC)))
        db.flush()
        room = db.scalar(select(CardRoom).where(CardRoom.code == code))
        assert room is not None
        room.course_id = other
    bowen = players("bowen")
    assert bowen.get(f"/card-rooms/{code}").status_code == 404
    assert bowen.post(f"/card-rooms/{code}/seat").status_code == 404
    assert bowen.get("/card-rooms/12345").status_code == 400


def test_chips_are_topped_up_only_when_you_have_none(
    players: Callable[[str], Player], database: Database
) -> None:
    (maya, bowen), code = _table(players, "maya", "bowen")
    assert bowen.post(f"/card-rooms/{code}/rebuy").json()["code"] == "card_room_rebuy_not_allowed"

    def broke(state: dict[str, Any]) -> None:
        for seat in state["table"]["seats"]:
            if seat["id"] == bowen.id:
                seat["stack"] = 0

    _edit(database, code, broke)
    assert maya.post(f"/card-rooms/{code}/start").json()["code"] == "card_room_needs_players"
    topped = bowen.post(f"/card-rooms/{code}/rebuy")
    assert topped.status_code == 200, topped.text
    assert topped.json()["seats"][1]["stack"] == 4000
    assert maya.post(f"/card-rooms/{code}/start").status_code == 200
