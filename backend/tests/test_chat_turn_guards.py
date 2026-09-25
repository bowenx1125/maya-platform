"""A late worker must not rewrite a turn that was already closed."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import PlatformError
from app.modules.workspace import chat as chat_module
from app.modules.workspace.chat import (
    _fail_open_turn,
    mark_abandoned_turn,
    record_chat_failure,
    repair_abandoned_chats,
    store_assistant_text,
)
from app.modules.workspace.models import Conversation, ConversationTurn
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests import test_chat_cancel
from tests.test_chat_cancel import _claim, _conversation, _plant, _send  # noqa: F401

# Register the reused fixture locally so test parameters can request it
# without importing a name that every test signature then shadows.
voice_app = test_chat_cancel.voice_app


def test_record_failure_after_repair_leaves_turn_and_allows_send(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    client, database, settings = voice_app
    csrf, conversation_id = _conversation(client, database, settings)
    request_id = _claim(database, settings, conversation_id, "Interrupted by a restart")
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        assert turn is not None
        turn.created_at = datetime.now(UTC) - timedelta(minutes=10)
    repair_abandoned_chats(database, conversation_id=conversation_id, only_stale=True)
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        row = session.get(Conversation, conversation_id)
        assert turn is not None and row is not None
        assert turn.state == "failed"
        assert turn.safe_error_code == "chat_interrupted"
        assert row.active_request_id is None
    _plant(database, scope_id=conversation_id, request_id=request_id, state="accepted")
    with database.session() as session:
        code = record_chat_failure(session, conversation_id, request_id, RuntimeError("late"))
        session.commit()
    assert code == "chat_failed"
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        assert turn is not None
        assert turn.state == "failed"
        assert turn.safe_error_code == "chat_interrupted"
    sent = _send(client, csrf, conversation_id, "next")
    assert sent["revision"] == 2
    with database.session() as session:
        row = session.get(Conversation, conversation_id)
        assert row is not None
        assert row.active_request_id is None


def test_store_text_after_cancel_keeps_cancelled(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    _client, database, settings = voice_app
    _csrf, conversation_id = _conversation(_client, database, settings)
    request_id = _claim(database, settings, conversation_id, "Cancelled mid-stream")
    mark_abandoned_turn(
        database, conversation_id=conversation_id, request_id=request_id, code="chat_cancelled"
    )
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        assert turn is not None
        assert turn.state == "failed"
        assert turn.safe_error_code == "chat_cancelled"
        with pytest.raises(PlatformError) as exc_info:
            store_assistant_text(session, request_id, "late reply", [], None)
        assert exc_info.value.code == "chat_turn_closed"
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        assert turn is not None
        assert turn.state == "failed"
        assert turn.safe_error_code == "chat_cancelled"
        assert turn.assistant_text is None


def test_store_text_on_pending_turn_marks_ready(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    _client, database, settings = voice_app
    _csrf, conversation_id = _conversation(_client, database, settings)
    request_id = _claim(database, settings, conversation_id, "Happy path")
    with database.session() as session:
        revision, stored = store_assistant_text(session, request_id, "full reply", [], None)
        assert stored == []
        row = session.get(Conversation, conversation_id)
        assert row is not None
        assert revision == row.revision
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        assert turn is not None
        assert turn.state == "ready"
        assert turn.assistant_text == "full reply"
        assert turn.sources_json == "[]"


def _insert_turn(
    session: object,
    conversation_id: str,
    position: int,
    state: str,
    safe_error_code: str | None = None,
) -> str:
    turn_id = str(uuid4())
    session.add(  # type: ignore[attr-defined]
        ConversationTurn(
            id=turn_id,
            conversation_id=conversation_id,
            position=position,
            user_text=f"turn {position}",
            assistant_text=None,
            sources_json="[]",
            mode="mock",
            state=state,
            safe_error_code=safe_error_code,
            created_at=datetime.now(UTC),
        )
    )
    return turn_id


def test_mark_abandoned_turn_leaves_ready_turn(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    _client, database, settings = voice_app
    _csrf, conversation_id = _conversation(_client, database, settings)
    request_id = _claim(database, settings, conversation_id, "Finished in time")
    with database.session() as session:
        store_assistant_text(session, request_id, "full reply", [], None)
    mark_abandoned_turn(
        database, conversation_id=conversation_id, request_id=request_id, code="chat_cancelled"
    )
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        row = session.get(Conversation, conversation_id)
        assert turn is not None and row is not None
        assert turn.state == "ready"
        assert turn.safe_error_code is None
        assert turn.assistant_text == "full reply"
        assert row.active_request_id is None


def test_mark_abandoned_turn_leaves_cancelled_turn(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    _client, database, settings = voice_app
    _csrf, conversation_id = _conversation(_client, database, settings)
    request_id = _claim(database, settings, conversation_id, "Cancelled first")
    mark_abandoned_turn(
        database, conversation_id=conversation_id, request_id=request_id, code="chat_cancelled"
    )
    mark_abandoned_turn(
        database, conversation_id=conversation_id, request_id=request_id, code="chat_interrupted"
    )
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        assert turn is not None
        assert turn.state == "failed"
        assert turn.safe_error_code == "chat_cancelled"


def test_fail_open_turn_only_rewrites_pending(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    _client, database, settings = voice_app
    _csrf, conversation_id = _conversation(_client, database, settings)
    with database.session() as session:
        ready_id = _insert_turn(session, conversation_id, 0, "ready")
        cancelled_id = _insert_turn(
            session, conversation_id, 1, "failed", safe_error_code="chat_cancelled"
        )
        pending_id = _insert_turn(session, conversation_id, 2, "pending")
        legacy_id = _insert_turn(
            session, conversation_id, 3, "acceptance_unknown", safe_error_code="chat_interrupted"
        )
        unknown_id = _insert_turn(
            session, conversation_id, 4, "acceptance_unknown", safe_error_code="acceptance_unknown"
        )
        # autoflush is off: the rows must exist in the database before the
        # conditional updates can match them.
        session.flush()
        results = [
            _fail_open_turn(session, ready_id, "chat_interrupted"),
            _fail_open_turn(session, cancelled_id, "chat_interrupted"),
            _fail_open_turn(session, pending_id, "chat_interrupted"),
            _fail_open_turn(session, legacy_id, "chat_interrupted"),
            _fail_open_turn(session, unknown_id, "chat_interrupted"),
        ]
    assert results == [False, False, True, True, False]
    with database.session() as session:
        ready = session.get(ConversationTurn, ready_id)
        cancelled = session.get(ConversationTurn, cancelled_id)
        pending = session.get(ConversationTurn, pending_id)
        legacy = session.get(ConversationTurn, legacy_id)
        unknown = session.get(ConversationTurn, unknown_id)
        assert ready is not None and ready.state == "ready"
        assert cancelled is not None and cancelled.state == "failed"
        assert cancelled.safe_error_code == "chat_cancelled"
        assert pending is not None and pending.state == "failed"
        assert pending.safe_error_code == "chat_interrupted"
        assert legacy is not None and legacy.state == "failed"
        assert legacy.safe_error_code == "chat_interrupted"
        assert unknown is not None and unknown.state == "acceptance_unknown"
        assert unknown.safe_error_code == "acceptance_unknown"


def test_repair_skips_ready_and_cancelled_turns(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    _client, database, settings = voice_app
    _csrf, conversation_id = _conversation(_client, database, settings)
    with database.session() as session:
        session.add(
            ConversationTurn(
                id=str(uuid4()),
                conversation_id=conversation_id,
                position=0,
                user_text="old ready",
                assistant_text="kept reply",
                sources_json="[]",
                mode="mock",
                state="ready",
                created_at=datetime.now(UTC) - timedelta(minutes=10),
            )
        )
        session.add(
            ConversationTurn(
                id=str(uuid4()),
                conversation_id=conversation_id,
                position=1,
                user_text="old cancelled",
                assistant_text=None,
                sources_json="[]",
                mode="mock",
                state="failed",
                safe_error_code="chat_cancelled",
                created_at=datetime.now(UTC) - timedelta(minutes=10),
            )
        )
    repair_abandoned_chats(database, conversation_id=conversation_id, only_stale=False)
    with database.session() as session:
        turns = list(
            session.scalars(
                select(ConversationTurn)
                .where(ConversationTurn.conversation_id == conversation_id)
                .order_by(ConversationTurn.position)
            )
        )
        assert [turn.state for turn in turns] == ["ready", "failed"]
        assert turns[0].assistant_text == "kept reply"
        assert turns[1].safe_error_code == "chat_cancelled"


def _plant_stale_locked_turn(database: Database, conversation_id: str) -> tuple[str, str]:
    """Insert a stale pending turn holding its conversation's lock."""

    turn_id = str(uuid4())
    new_lock_id = str(uuid4())
    with database.session() as session:
        row = session.get(Conversation, conversation_id)
        assert row is not None
        row.active_request_id = turn_id
        session.add(
            ConversationTurn(
                id=turn_id,
                conversation_id=conversation_id,
                position=0,
                user_text="stale lock",
                assistant_text=None,
                sources_json="[]",
                mode="real",
                state="pending",
                created_at=datetime.now(UTC) - timedelta(minutes=10),
            )
        )
    return turn_id, new_lock_id


def _steal_lock_after_fail(
    original: Callable[..., bool], conversation_id: str, new_lock_id: str
) -> Callable[..., bool]:
    """Wrap _fail_open_turn so a rival request takes the lock mid-repair."""

    def wrapper(db: Session, turn_id: str, code: str) -> bool:
        changed = original(db, turn_id, code)
        if changed:
            # An outside writer does not touch this session's identity map.
            db.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(active_request_id=new_lock_id)
                .execution_options(synchronize_session=False)
            )
        return changed

    return wrapper


@pytest.mark.parametrize("only_stale", [True, False])
def test_repair_does_not_clear_a_lock_taken_during_repair(
    voice_app: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
    only_stale: bool,
) -> None:
    _client, database, settings = voice_app
    _csrf, conversation_id = _conversation(_client, database, settings)
    turn_id, new_lock_id = _plant_stale_locked_turn(database, conversation_id)
    monkeypatch.setattr(
        chat_module,
        "_fail_open_turn",
        _steal_lock_after_fail(chat_module._fail_open_turn, conversation_id, new_lock_id),
    )
    repair_abandoned_chats(database, conversation_id=conversation_id, only_stale=only_stale)
    with database.session() as session:
        turn = session.get(ConversationTurn, turn_id)
        row = session.get(Conversation, conversation_id)
        assert turn is not None and row is not None
        assert turn.state == "failed"
        assert turn.safe_error_code == "chat_interrupted"
        assert row.active_request_id == new_lock_id


def test_repair_clears_the_observed_stale_lock(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    _client, database, settings = voice_app
    _csrf, conversation_id = _conversation(_client, database, settings)
    turn_id, _new_lock_id = _plant_stale_locked_turn(database, conversation_id)
    repair_abandoned_chats(database, conversation_id=conversation_id, only_stale=True)
    with database.session() as session:
        turn = session.get(ConversationTurn, turn_id)
        row = session.get(Conversation, conversation_id)
        assert turn is not None and row is not None
        assert turn.state == "failed"
        assert turn.safe_error_code == "chat_interrupted"
        assert row.active_request_id is None


def test_repair_abandoned_chats_is_at_most_80_lines() -> None:
    lines, _start = inspect.getsourcelines(chat_module.repair_abandoned_chats)
    body = lines[1:]
    assert len(body) <= 80
