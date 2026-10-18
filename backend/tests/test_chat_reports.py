"""Team Chat HTML reports: owner- and Chat-scoped, escaped, linked by the server."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.core.db import Database
from app.modules.runtime_tools.builtin import runtime_registry
from app.modules.workspace.chat_reports import (
    CHAT_REPORT_TOOL,
    ChatReportArguments,
    chat_report_download_path,
    is_chat_report_path,
)
from app.modules.workspace.models import ChatReport, Conversation
from app.modules.workspace.team_runtime import report_paths
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_chat_attachments import _team_chat
from tests.test_mayaform_team_conversations import _create, _headers

ARGUMENTS = {
    "title": "她爱我吗？<script>alert(1)</script>",
    "summary": "整体温暖，但回应速度不对称。",
    "metrics": [{"label": "对称性", "score": 6.5, "note": "她主动 38%"}],
    "sections": [
        {
            "heading": "关系温度",
            "body": "第一段。\n\n第二段 <b>不是标签</b>",
            "evidence": [
                {"quote": "今天好累 <img src=x onerror=alert(1)>", "when": "2026-10-01 20:01"}
            ],
        }
    ],
}


def _actor(user_id: str) -> Any:
    return SimpleNamespace(user=SimpleNamespace(id=user_id))


def _save(database: Database, conversation_id: str, event_id: str | None = None) -> dict[str, Any]:
    spec = runtime_registry()[CHAT_REPORT_TOOL]
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        assert row is not None
        payload = ChatReportArguments.model_validate(ARGUMENTS)
        actor = _actor(row.user_id)
        spec.authorize(db, actor, row, payload)
        result = spec.handler(db, actor, row, payload, event_id or str(uuid4()), None)  # type: ignore[arg-type]
        db.commit()
    return result


def test_the_tool_is_public_and_only_mounted_in_team_chats() -> None:
    spec = runtime_registry()[CHAT_REPORT_TOOL]
    assert spec.authorization_class == "Public"
    assert spec.entry_kinds == frozenset({"team", "maya_team"})
    assert "Do not write a download link" in spec.description


def test_owner_downloads_escaped_html_and_others_get_404(
    client: TestClient, database: Database
) -> None:
    session, csrf = _team_chat(client, database)
    event_id = str(uuid4())
    saved = _save(database, session["id"], event_id)
    assert saved["download_path"] == chat_report_download_path(session["id"], saved["report_id"])
    # A replayed Tool call returns the same report and stores no second one.
    assert _save(database, session["id"], event_id) == saved
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(ChatReport)) == 1

    response = client.get(saved["download_path"])
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    html = response.text
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<img" not in html and "&lt;img src=x" in html
    assert "<b>不是标签" not in html and "&lt;b&gt;不是标签" in html
    assert "<p>第一段。</p>" in html and "6.5/10" in html
    assert "2026-10-01 20:01" in html

    # Another Chat id with this report's id is not this report.
    other = _create(client, csrf, {"kind": "team", "team_id": session["team"]["id"]})
    wrong = chat_report_download_path(other["id"], saved["report_id"])
    assert client.get(wrong).status_code == 404

    login(client, "kaikai")
    assert client.get(saved["download_path"]).status_code == 404


def test_a_single_agent_chat_or_another_user_cannot_save(
    client: TestClient, database: Database
) -> None:
    session, _csrf = _team_chat(client, database)
    spec = runtime_registry()[CHAT_REPORT_TOOL]
    payload = ChatReportArguments.model_validate(ARGUMENTS)
    with database.session() as db:
        row = db.get(Conversation, session["id"])
        assert row is not None
        with pytest.raises(Exception) as stranger:
            spec.authorize(db, _actor(str(uuid4())), row, payload)
        assert getattr(stranger.value, "code", None) == "not_found"
        row.entry_kind = "agent"
        with pytest.raises(Exception) as single:
            spec.authorize(db, _actor(row.user_id), row, payload)
        assert getattr(single.value, "code", None) == "not_found"
        db.rollback()


def test_arguments_are_bounded_text() -> None:
    with pytest.raises(ValueError):
        ChatReportArguments.model_validate({**ARGUMENTS, "sections": []})
    with pytest.raises(ValueError):
        ChatReportArguments.model_validate({**ARGUMENTS, "metrics": [{"label": "x", "score": 11}]})
    with pytest.raises(ValueError):
        ChatReportArguments.model_validate({**ARGUMENTS, "html": "<p>"})


def test_only_real_report_paths_become_links() -> None:
    conversation, report = str(uuid4()), str(uuid4())
    path = chat_report_download_path(conversation, report)
    assert is_chat_report_path(path)
    for bad in (
        f"/api/v1/conversations/{conversation}/reports/x",
        f"/api/v1/conversations/{conversation}/attachments/{report}",
        f"https://evil.example/api/v1/conversations/{conversation}/reports/{report}",
        f"/api/v1/conversations/{conversation}/reports/{report}/../../x",
    ):
        assert not is_chat_report_path(bad)
    assert report_paths(
        [
            json.dumps({"ok": True, "result": {"download_path": path}}),
            json.dumps({"ok": True, "result": {"download_path": path}}),
            json.dumps({"ok": False, "result": {"download_path": path + "x"}}),
        ]
    ) == [path]


def test_deleting_the_chat_removes_its_reports(client: TestClient, database: Database) -> None:
    session, csrf = _team_chat(client, database)
    saved = _save(database, session["id"])
    response = client.delete(f"/api/v1/conversations/{session['id']}", headers=_headers(csrf))
    assert response.status_code == 204
    with database.session() as db:
        assert db.get(ChatReport, saved["report_id"]) is None
