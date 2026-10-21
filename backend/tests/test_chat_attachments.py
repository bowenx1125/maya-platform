"""Chatform attachments: owner- and conversation-scoped, read by Team members.

Single-Agent Chats use the same routes; see test_agent_chat_attachments_reports.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from app.core.db import Database
from app.modules.workspace import attachments
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.models import ConversationAttachment
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login, post_message
from tests.test_mayaform_team_conversations import _create, _headers, _team

CHAT_LOG = "2026-10-01 20:01 她: 今天好累\n2026-10-01 20:03 我: 早点休息\n".encode()


def _team_chat(client: TestClient, database: Database) -> tuple[dict[str, Any], str]:
    team, _versions, csrf = _team(client, database)
    return _create(client, csrf, {"kind": "team", "team_id": team["id"]}), csrf


def _upload(
    client: TestClient,
    csrf: str,
    conversation_id: str,
    name: str = "chat.txt",
    content: bytes = CHAT_LOG,
) -> Any:
    return client.post(
        f"/api/v1/conversations/{conversation_id}/attachments",
        headers=_headers(csrf),
        files={"file": (name, content, "application/octet-stream")},
    )


def _send(client: TestClient, csrf: str, session: dict[str, Any], message: str) -> Any:
    current = client.get(f"/api/v1/conversations/{session['id']}").json()
    return post_message(
        client,
        f"/api/v1/conversations/{session['id']}/messages",
        headers=_headers(csrf),
        json={
            "request_id": str(uuid4()),
            "expected_revision": current["revision"],
            "message": message,
            "routing": {"mode": "all", "participant_ids": []},
        },
    )


def test_members_read_the_owners_attachment_only_in_that_chat(
    client: TestClient, database: Database, app_bundle: Any, monkeypatch: Any
) -> None:
    session, csrf = _team_chat(client, database)
    uploaded = _upload(client, csrf, session["id"])
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["filename"] == "chat.txt"
    assert body["media_type"] == "text/plain"
    assert body["size_bytes"] == len(CHAT_LOG)
    listed = client.get(f"/api/v1/conversations/{session['id']}/attachments")
    assert [item["id"] for item in listed.json()] == [body["id"]]

    histories: dict[str, list[tuple[dict[str, str], ...]]] = {}
    original = runtime.invoke_mock_member

    def record(request: Any) -> Any:
        histories.setdefault(request.conversation_id, []).append(request.history)
        return original(request)

    monkeypatch.setattr(runtime, "invoke_mock_member", record)
    assert _send(client, csrf, session, "帮我分析一下").status_code == 200
    assert len(histories[session["id"]]) == 2
    for history in histories[session["id"]]:
        assert history[-1]["role"] == "user"
        assert "<chat_attachments>" in history[-1]["content"]
        assert "今天好累" in history[-1]["content"]
        assert '"chat.txt"' in history[-1]["content"]

    # The owner's other Chat with the same Team never sees it.
    team_id = session["team"]["id"]
    other = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={"entry": {"kind": "team", "team_id": team_id}},
    ).json()
    assert other["id"] != session["id"]
    assert client.get(f"/api/v1/conversations/{other['id']}/attachments").json() == []
    assert _send(client, csrf, other, "你好").status_code == 200
    assert all(
        "<chat_attachments>" not in item["content"]
        for history in histories[other["id"]]
        for item in history
    )
    wrong_scope = client.delete(
        f"/api/v1/conversations/{other['id']}/attachments/{body['id']}",
        headers=_headers(csrf),
    )
    assert wrong_scope.status_code == 404

    _app, _database, settings = app_bundle
    with database.session() as db:
        row = db.get(ConversationAttachment, body["id"])
        assert row is not None
        stored = settings.resolved_data_root / row.relative_path
    assert stored.read_bytes() == CHAT_LOG
    deleted = client.delete(
        f"/api/v1/conversations/{session['id']}/attachments/{body['id']}",
        headers=_headers(csrf),
    )
    assert deleted.status_code == 204
    assert not stored.exists()
    assert client.get(f"/api/v1/conversations/{session['id']}/attachments").json() == []


def test_another_user_cannot_list_upload_or_delete(client: TestClient, database: Database) -> None:
    session, csrf = _team_chat(client, database)
    attachment_id = _upload(client, csrf, session["id"]).json()["id"]
    _user, other_csrf = login(client, "kaikai")
    base = f"/api/v1/conversations/{session['id']}/attachments"
    assert client.get(base).status_code == 404
    assert _upload(client, other_csrf, session["id"]).status_code == 404
    assert client.delete(f"{base}/{attachment_id}", headers=_headers(other_csrf)).status_code == 404
    with database.session() as db:
        rows = db.scalars(select(ConversationAttachment)).all()
        assert [row.id for row in rows] == [attachment_id]


@pytest.mark.parametrize(
    ("name", "content", "status", "code"),
    [
        ("chat.exe", b"MZ", 422, "chat_attachment_type_unsupported"),
        ("photo.png", b"\x89PNG", 422, "chat_attachment_type_unsupported"),
        ("chat.txt", b"", 422, "chat_attachment_empty"),
        ("chat.json", b"{not json", 422, "chat_attachment_invalid"),
        ("chat.txt", b"\xff\xfa\xfb\x00\x81", 422, "chat_attachment_encoding_unsupported"),
        (
            "chat.txt",
            b"a" * (attachments.MAX_ATTACHMENT_BYTES + 1),
            422,
            "chat_attachment_too_large",
        ),
    ],
    ids=["executable", "image", "empty", "invalid-json", "invalid-encoding", "oversized"],
)
def test_refused_files_store_nothing(
    client: TestClient, database: Database, name: str, content: bytes, status: int, code: str
) -> None:
    session, csrf = _team_chat(client, database)
    response = _upload(client, csrf, session["id"], name, content)
    assert response.status_code == status, response.text
    assert response.json()["code"] == code
    with database.session() as db:
        assert db.scalars(select(ConversationAttachment)).all() == []


def test_text_formats_decode_to_readable_text() -> None:
    assert attachments.extract_attachment_text("a.txt", "你好".encode("gb18030")) == (
        "text/plain",
        "你好",
    )
    assert attachments.extract_attachment_text("a.TXT", "\ufeff你好".encode())[1] == "你好"
    assert attachments.extract_attachment_text("a.csv", "你好".encode("utf-16"))[1] == "你好"
    media, text = attachments.extract_attachment_text(
        "wechat.html",
        b"<html><head><style>p{}</style><script>x()</script></head>"
        b"<body><div>20:01 \xe5\xa5\xb9</div><p>hi &amp; bye</p></body></html>",
    )
    assert media == "text/html"
    assert text == "20:01 她\n\nhi & bye"


def test_count_and_text_limits(client: TestClient, database: Database, monkeypatch: Any) -> None:
    session, csrf = _team_chat(client, database)
    for index in range(attachments.MAX_ATTACHMENTS_PER_CONVERSATION):
        assert _upload(client, csrf, session["id"], f"c{index}.md").status_code == 200
    sixth = _upload(client, csrf, session["id"], "c6.md")
    assert sixth.status_code == 409
    assert sixth.json()["code"] == "chat_attachment_limit"

    other, _ = _team_chat(client, database)
    _user, csrf = login(client, "maya")
    monkeypatch.setattr(attachments, "MAX_ATTACHMENT_TEXT_CHARS", len(CHAT_LOG.decode()) + 3)
    assert _upload(client, csrf, other["id"]).status_code == 200
    too_long = _upload(client, csrf, other["id"])
    assert too_long.status_code == 422
    assert too_long.json()["code"] == "chat_attachment_text_too_long"


def test_a_file_attached_during_a_turn_waits_for_the_next_turn(
    client: TestClient, database: Database
) -> None:
    session, csrf = _team_chat(client, database)
    attachment_id = _upload(client, csrf, session["id"]).json()["id"]
    with database.session() as db:
        row = db.get(ConversationAttachment, attachment_id)
        assert row is not None
        created = row.created_at
        assert attachments.attachment_history(db, session["id"], created) == ()
        later = created + timedelta(microseconds=1)
        assert len(attachments.attachment_history(db, session["id"], later)) == 1
        assert attachments.attachment_history(db, str(uuid4()), datetime.now(UTC)) == ()


def test_deleting_the_chat_removes_its_files(
    client: TestClient, database: Database, app_bundle: Any
) -> None:
    session, csrf = _team_chat(client, database)
    attachment_id = _upload(client, csrf, session["id"]).json()["id"]
    _app, _database, settings = app_bundle
    with database.session() as db:
        row = db.get(ConversationAttachment, attachment_id)
        assert row is not None
        stored = settings.resolved_data_root / row.relative_path
    assert stored.exists()
    response = client.delete(f"/api/v1/conversations/{session['id']}", headers=_headers(csrf))
    assert response.status_code == 204
    assert not stored.exists()
    with database.session() as db:
        assert db.get(ConversationAttachment, attachment_id) is None
