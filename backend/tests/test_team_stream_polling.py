"""A waiting Team stream polls cheaply and backs off while nothing changes.

Read breakdown (2026-10-18): every poll rebuilt the whole turn view (~35
queries) even when no event was new, 20 times a second per waiting student,
which outweighed the turn's own reads many times over. An empty poll now
returns at once, and the interval backs off from 50 ms to 500 ms while idle.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from uuid import uuid4

import pytest
from app.modules.workspace import chat_stream
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.schemas import TeamRouting
from fastapi.testclient import TestClient
from sqlalchemy import event

from tests.test_mayaform_team_turns import _chat


def _claim(database: Any, settings: Any, session: dict[str, Any], actor_id: str, ids: list[str]):
    with database.session() as db:
        return runtime.claim_team_turn(
            db,
            settings,
            conversation_id=session["id"],
            actor_id=actor_id,
            request_id=str(uuid4()),
            expected_revision=session["revision"],
            message="One user request",
            routing=TeamRouting(mode="selected", participant_ids=ids),
        )


def test_next_poll_delay_backs_off_while_idle_and_resets_on_an_event() -> None:
    delay = chat_stream.POLL_MIN_SECONDS
    seen = []
    for _ in range(6):
        delay = chat_stream.next_poll_delay(delay, False)
        seen.append(delay)
    assert seen == [0.1, 0.2, 0.4, 0.5, 0.5, 0.5]
    assert chat_stream.next_poll_delay(0.5, True) == chat_stream.POLL_MIN_SECONDS


def test_a_poll_with_nothing_new_skips_the_turn_view(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    session, _csrf, actor_id = _chat(client, database)
    ids = [member["id"] for member in session["team"]["members"]]
    claim = _claim(database, app_bundle[2], session, actor_id, ids[1:])
    first, state, active = runtime.poll_team_events(
        database.session_factory, session["id"], claim.turn_id, actor_id
    )
    assert [kind for _sequence, kind, _payload in first] == ["turn_started"]
    assert (state, active) == ("pending", True)
    last = first[-1][0]

    def unexpected(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("an empty poll must not rebuild the turn view")

    monkeypatch.setattr(runtime, "project_team_turn", unexpected)
    statements: list[str] = []

    def count(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    event.listen(database.engine, "after_cursor_execute", count)
    try:
        empty, state, active = runtime.poll_team_events(
            database.session_factory,
            session["id"],
            claim.turn_id,
            actor_id,
            after_sequence=last,
        )
    finally:
        event.remove(database.engine, "after_cursor_execute", count)
    assert empty == []
    assert (state, active) == ("pending", True)
    assert len(statements) <= 10, statements


@pytest.mark.asyncio
async def test_a_slow_member_is_polled_far_less_and_no_event_is_lost(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    session, _csrf, actor_id = _chat(client, database)
    ids = [member["id"] for member in session["team"]["members"]]
    release = threading.Event()

    def reply(request: runtime.MemberRequest) -> runtime.MemberReply:
        if request.participant_id == ids[2]:
            assert release.wait(5)
        return runtime.MemberReply(f"Reply from {request.participant_id[:8]}")

    polls = {"count": 0}
    real_poll = runtime.poll_team_events

    def counted_poll(*args: Any, **kwargs: Any) -> Any:
        polls["count"] += 1
        return real_poll(*args, **kwargs)

    monkeypatch.setattr(runtime, "invoke_mock_member", reply)
    monkeypatch.setattr(runtime, "poll_team_events", counted_poll)
    claim = _claim(database, app_bundle[2], session, actor_id, ids[1:])
    stream = chat_stream.stream_team_events(database, session["id"], actor_id, claim)

    async def collect() -> list[bytes]:
        return [chunk async for chunk in stream]

    collecting = asyncio.create_task(collect())
    await asyncio.sleep(1.5)  # the last member is still thinking
    idle_polls = polls["count"]
    release.set()
    chunks = await asyncio.wait_for(collecting, timeout=10)

    # 1.5 s at a fixed 50 ms was ~30 polls; backing off it is under a dozen.
    assert idle_polls <= 12, idle_polls
    body = b"".join(chunks)
    assert body.count(b"event: member_result") == 2
    assert body.count(b"event: turn_started") == 1
    assert body.rstrip().endswith(b"}") and b"event: turn_done" in body
