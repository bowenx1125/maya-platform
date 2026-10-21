"""PR2: open chats follow the Agent's new version and keep history."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.models import Agent
from app.modules.workspace.models import Conversation
from fastapi.testclient import TestClient

from tests.conftest import login, post_message
from tests.test_agent_source_cascade import _agent_with_docs, _current, _h, _upload


def _send(client: TestClient, csrf: str, conversation_id: str, revision: int, text: str) -> Any:
    sent = post_message(
        client,
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_h(csrf),
        json={"request_id": str(uuid4()), "expected_revision": revision, "message": text},
    )
    assert sent.status_code == 200, sent.text
    return sent.json()


def test_chat_moves_to_the_new_version_with_full_history(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, _settings = app_bundle
    _owner, csrf = login(client, "bowen")
    doc = _upload(client, csrf, "pr2.md", b"# PR2\n\nPR2_CANARY", "pr2-upload-doc-0001")
    agent_id = _agent_with_docs(client, csrf, "Follow Chat", [doc])
    before, _ = _current(database, agent_id)
    opened = client.post("/api/v1/conversations", headers=_h(csrf), json={"version_id": before.id})
    assert opened.status_code == 200, opened.text
    conversation_id = opened.json()["id"]
    first = _send(client, csrf, conversation_id, 0, "first question")

    hidden = client.post(
        f"/api/v1/knowledge-documents/{doc}/hide", headers=_h(csrf, "pr2-hide-doc-00001")
    )
    assert hidden.status_code == 200, hidden.text
    after, _ = _current(database, agent_id)
    assert after.id != before.id
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        assert row is not None
        assert row.agent_version_id == after.id
        assert row.snapshot_id == after.knowledge_snapshot_id

    second = _send(client, csrf, conversation_id, first["revision"], "second question")
    texts = [turn["user_text"] for turn in second["turns"]]
    assert texts[-2:] == ["first question", "second question"]


def test_chat_of_a_deleted_agent_can_no_longer_continue(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, _settings = app_bundle
    _owner, csrf = login(client, "bowen")
    agent_id = _agent_with_docs(client, csrf, "Gone Chat", [])
    version, _ = _current(database, agent_id)
    opened = client.post("/api/v1/conversations", headers=_h(csrf), json={"version_id": version.id})
    assert opened.status_code == 200, opened.text
    conversation_id = opened.json()["id"]
    with database.session() as db:
        agent = db.get(Agent, agent_id)
        assert agent is not None
        from datetime import UTC, datetime

        agent.deleted_at = datetime.now(UTC)
        agent.status = "archived"
        db.commit()
    blocked = post_message(
        client,
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_h(csrf),
        json={"request_id": str(uuid4()), "expected_revision": 0, "message": "still there?"},
    )
    assert blocked.status_code in {403, 404, 409, 422}, blocked.text
