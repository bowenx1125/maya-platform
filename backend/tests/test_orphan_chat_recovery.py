"""Chats left busy by a process that died are freed; live ones are never touched."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.core.chat_turn_locks import ChatTurnLocks, chat_turn_locks, turn_is_held
from app.core.db import build_engine
from app.modules.demo_baseline.service import BASELINE_VERSION_ID, ensure_demo_baseline
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.chat import claim_chat_send
from app.modules.workspace.chat_stream import stream_events
from app.modules.workspace.models import Conversation, ConversationTurn
from app.modules.workspace.orphan_chats import OrphanChatSweeper
from app.modules.workspace.schemas import TeamRouting
from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_mayaform_team_turns import _chat


def _held_elsewhere(database: Any, turn_id: str) -> bool:
    with database.session_factory() as db:
        held = turn_is_held(db.connection(), turn_id)
        db.rollback()
    return held


def _single_claim(client: TestClient, database: Any, settings: Any) -> tuple[str, str]:
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        turn, is_new = claim_chat_send(
            db,
            conversation,
            request_id=str(uuid4()),
            expected_revision=0,
            message="A reply whose process died",
            settings=settings,
        )
        assert is_new
        return created["id"], turn.id


def _busy(database: Any, conversation_id: str) -> str | None:
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        assert row is not None
        return row.active_request_id


def test_a_held_turn_reads_as_held_until_its_holder_releases_or_dies(database: Any) -> None:
    other_process = build_engine(str(database.engine.url.render_as_string(hide_password=False)))
    holder = ChatTurnLocks(other_process)
    turn_id = str(uuid4())
    try:
        assert not _held_elsewhere(database, turn_id)
        holder.hold(turn_id)
        holder.hold(turn_id)  # nested: one release must not free it
        assert _held_elsewhere(database, turn_id)
        holder.release(turn_id)
        assert _held_elsewhere(database, turn_id)
        holder.release(turn_id)
        assert not _held_elsewhere(database, turn_id)
        holder.hold(turn_id)
        assert _held_elsewhere(database, turn_id)
        # A process that dies closes its connection, and its locks go with it.
        holder.close()
        assert not _held_elsewhere(database, turn_id)
    finally:
        holder.close()
        other_process.dispose()


def test_an_unheld_single_chat_is_freed_on_the_second_sweep(
    app_bundle: Any, client: TestClient
) -> None:
    _app, database, settings = app_bundle
    conversation_id, turn_id = _single_claim(client, database, settings)
    sweeper = OrphanChatSweeper(database)
    # One sighting can be a runner that has not taken its lock yet.
    assert sweeper.sweep() == 0
    assert _busy(database, conversation_id) == turn_id
    assert sweeper.sweep() == 1
    assert _busy(database, conversation_id) is None
    with database.session() as db:
        turn = db.get(ConversationTurn, turn_id)
        assert turn is not None
        assert turn.state in {"failed", "acceptance_unknown"}
        assert turn.safe_error_code == "chat_interrupted"
    assert sweeper.sweep() == 0


def test_a_chat_held_by_a_live_process_is_never_freed(app_bundle: Any, client: TestClient) -> None:
    _app, database, settings = app_bundle
    conversation_id, turn_id = _single_claim(client, database, settings)
    other_process = build_engine(str(database.engine.url.render_as_string(hide_password=False)))
    holder = ChatTurnLocks(other_process)
    try:
        holder.hold(turn_id)
        sweeper = OrphanChatSweeper(database)
        for _ in range(3):
            assert sweeper.sweep() == 0
        assert _busy(database, conversation_id) == turn_id
        holder.close()  # the peer died mid-reply
        assert sweeper.sweep() == 0
        assert sweeper.sweep() == 1
        assert _busy(database, conversation_id) is None
    finally:
        holder.close()
        other_process.dispose()


def test_a_claim_that_moved_on_between_sweeps_is_not_freed(
    app_bundle: Any, client: TestClient
) -> None:
    _app, database, settings = app_bundle
    conversation_id, turn_id = _single_claim(client, database, settings)
    sweeper = OrphanChatSweeper(database)
    assert sweeper.sweep() == 0
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        assert row is not None
        row.revision += 1  # e.g. the runner paused and a new send claimed it
    assert sweeper.sweep() == 0
    assert _busy(database, conversation_id) == turn_id
    assert sweeper.sweep() == 1


def test_an_unheld_team_turn_is_freed_and_left_resumable(
    client: TestClient, database: Any, app_bundle: Any
) -> None:
    session, _csrf, actor_id = _chat(client, database)
    with database.session() as db:
        claim = runtime.claim_team_turn(
            db,
            app_bundle[2],
            conversation_id=session["id"],
            actor_id=actor_id,
            request_id=str(uuid4()),
            expected_revision=session["revision"],
            message="The replica running this died",
            routing=TeamRouting(mode="all"),
        )
    sweeper = OrphanChatSweeper(database)
    assert sweeper.sweep() == 0
    assert sweeper.sweep() == 1
    assert _busy(database, session["id"]) is None
    with database.session() as db:
        turn = db.get(ConversationTurn, claim.turn_id)
        assert turn is not None and turn.state == "paused"


def test_team_and_single_runners_hold_their_turn_while_running(
    app_bundle: Any, client: TestClient, database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, _csrf, actor_id = _chat(client, database)
    with database.session() as db:
        claim = runtime.claim_team_turn(
            db,
            app_bundle[2],
            conversation_id=session["id"],
            actor_id=actor_id,
            request_id=str(uuid4()),
            expected_revision=session["revision"],
            message="Held while it runs",
            routing=TeamRouting(mode="all"),
        )
    seen: list[bool] = []
    monkeypatch.setattr(
        runtime,
        "_execute_team_turn_body",
        lambda _factory, running: seen.append(_held_elsewhere(database, running.turn_id)),
    )
    runtime.execute_team_turn(database.session_factory, claim)
    assert seen == [True]
    assert not _held_elsewhere(database, claim.turn_id)
    assert chat_turn_locks(database.engine).held() == ()


@pytest.mark.asyncio
async def test_a_single_chat_stream_holds_its_turn_until_it_ends(
    app_bundle: Any, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _app, database, settings = app_bundle
    conversation_id, turn_id = _single_claim(client, database, settings)
    seen: list[bool] = []

    def reply(*args: Any, **_kwargs: Any) -> tuple[str, list[Any], None]:
        seen.append(_held_elsewhere(database, turn_id))
        return "A reply", [], None

    monkeypatch.setattr("app.modules.workspace.chat_stream._reply_segment", reply)
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        assert row is not None
        revision = row.revision
    events = [
        event
        async for event in stream_events(
            database,
            settings,
            conversation_id=conversation_id,
            created=True,
            message="A reply whose process died",
            request_id=turn_id,
            claim_revision=revision,
        )
    ]
    assert seen == [True]
    assert any(b"event: text_done" in event for event in events)
    assert not _held_elsewhere(database, turn_id)
