"""A late worker must not rewrite a turn that was already closed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import PlatformError
from app.modules.workspace.chat import (
    mark_abandoned_turn,
    record_chat_failure,
    repair_abandoned_chats,
    store_assistant_text,
)
from app.modules.workspace.models import Conversation, ConversationTurn
from fastapi.testclient import TestClient

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
