from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.modules.demo_baseline.service import BASELINE_VERSION_ID, ensure_demo_baseline
from app.modules.workspace.chat import _current_chat_claim
from app.modules.workspace.models import Conversation, ConversationTurn
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login


def test_chat_withdrawal_retains_history_fences_pending_and_replays_delete(
    app_bundle: Any, client: TestClient
) -> None:
    _app, database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    _session, csrf = login(client, "bowen")
    headers = {"X-CSRF-Token": csrf}
    client.headers["Origin"] = "http://testserver"
    created = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"version_id": BASELINE_VERSION_ID},
    )
    assert created.status_code == 200
    conversation_id = created.json()["id"]
    turn_id = str(uuid4())
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        assert row is not None
        row.active_request_id = turn_id
        row.revision = 1
        db.add(
            ConversationTurn(
                id=turn_id,
                conversation_id=conversation_id,
                position=1,
                user_text="An unfinished answer",
                assistant_text=None,
                sources_json="[]",
                mode="mock",
                state="pending",
                created_at=datetime.now(UTC),
            )
        )
    url = f"/api/v1/conversations/{conversation_id}"
    assert client.delete(url, headers=headers).status_code == 204
    assert client.delete(url, headers=headers).status_code == 404
    assert client.get(url).status_code == 404
    assert client.get("/api/v1/conversations").json() == []
    with database.session() as db:
        assert db.get(Conversation, conversation_id) is None
        assert db.get(ConversationTurn, turn_id) is None
        assert not db.scalar(select(_current_chat_claim(conversation_id, turn_id, 1)))
    _teacher_session, teacher_csrf = login(client, "maya")
    assert client.get(url).status_code == 404
    assert client.delete(url, headers={"X-CSRF-Token": teacher_csrf}).status_code == 404
