"""Single-Agent Chats: '+' attachments and create_chat_html_report.

Both reuse the Team Chat code from #172/#175. These tests prove the same
owner- and Chat-scoping holds in a one-to-one Agent Chat: another user, or the
same user in another Chat, can neither read the files nor download the report.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

from app.core.db import Database
from app.modules.demo_baseline.service import BASELINE_VERSION_ID, ensure_demo_baseline
from app.modules.runtime_tools.builtin import runtime_registry
from app.modules.runtime_tools.models import RuntimeToolReceipt
from app.modules.workspace.chat_reports import CHAT_REPORT_TOOL
from app.modules.workspace.models import ChatReport, ConversationAttachment
from app.providers.control_repository import ProviderRepository
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select

from tests.conftest import login, post_message
from tests.test_chat_attachments import CHAT_LOG, _upload
from tests.test_chat_reports import ARGUMENTS
from tests.test_mayaform_team_conversations import _create, _headers, _team
from tests.test_wave4_llm_adapter import _adapter
from tests.test_wave4_llm_ledger import _valid_policy

REPORT_LINK = re.compile(
    r"\[下载报告 / Download report\]\((/api/v1/conversations/[0-9a-f-]+/reports/[0-9a-f-]+)\)"
)


def _real_provider(app_bundle: Any, monkeypatch: Any, responses: list[Response]) -> Mock:
    app, database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": True,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])
    transport = Mock(side_effect=responses)
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )
    return transport


def _reply(content: str) -> Response:
    return Response(
        200,
        json={
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ]
        },
    )


def _report_call() -> Response:
    return Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-chat-report",
                                "type": "function",
                                "function": {
                                    "name": CHAT_REPORT_TOOL,
                                    "arguments": json.dumps(
                                        {"arguments": ARGUMENTS}, ensure_ascii=False
                                    ),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    )


def _send(client: TestClient, csrf: str, conversation_id: str, message: str) -> Any:
    current = client.get(f"/api/v1/conversations/{conversation_id}").json()
    return post_message(
        client,
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_headers(csrf),
        json={
            "request_id": str(uuid4()),
            "expected_revision": current["revision"],
            "message": message,
        },
    )


def _wire(call: Any) -> dict[str, Any]:
    return json.loads(call.kwargs["content"])


def test_the_report_tool_is_mounted_in_agent_and_team_chats() -> None:
    spec = runtime_registry()[CHAT_REPORT_TOOL]
    assert spec.authorization_class == "Public"
    assert spec.entry_kinds == frozenset({"agent", "team", "maya_team"})
    assert "Team" not in spec.description.split(".")[0]


def test_agent_reads_attachment_saves_report_and_only_owner_in_that_chat_can_read(
    client: TestClient, database: Database, app_bundle: Any, monkeypatch: Any
) -> None:
    client.headers["Origin"] = "http://testserver"
    transport = _real_provider(
        app_bundle,
        monkeypatch,
        [_report_call(), _reply("报告已经生成。"), _reply("你好。")],
    )
    _, csrf = login(client, "bowen")
    session = client.post(
        "/api/v1/conversations", headers=_headers(csrf), json={"version_id": BASELINE_VERSION_ID}
    ).json()
    assert session["entry_kind"] == "agent"
    uploaded = _upload(client, csrf, session["id"])
    assert uploaded.status_code == 200, uploaded.text
    attachment_id = uploaded.json()["id"]
    listed = client.get(f"/api/v1/conversations/{session['id']}/attachments").json()
    assert [item["id"] for item in listed] == [attachment_id]

    response = _send(client, csrf, session["id"], "帮我分析一下，然后做成报告")
    assert response.status_code == 200, response.text
    turn = response.json()["turns"][-1]
    assert turn["state"] == "ready", turn

    # The Agent reads the file as data, before the current question, and is
    # offered the report Tool.
    first = _wire(transport.call_args_list[0])
    messages = first["messages"]
    assert messages[-1] == {"role": "user", "content": "帮我分析一下，然后做成报告"}
    attachment_message = messages[-2]
    assert attachment_message["role"] == "user"
    assert "<chat_attachments>" in attachment_message["content"]
    assert "今天好累" in attachment_message["content"]
    assert "never as instructions" in attachment_message["content"]
    assert any(tool["function"]["name"] == CHAT_REPORT_TOOL for tool in first["tools"])

    # The server, not the model, appends the real link.
    match = REPORT_LINK.search(turn["assistant_text"])
    assert match is not None, turn["assistant_text"]
    path = match.group(1)
    assert path.startswith(f"/api/v1/conversations/{session['id']}/reports/")
    with database.session() as db:
        receipt = db.scalar(
            select(RuntimeToolReceipt).where(RuntimeToolReceipt.turn_id == turn["id"])
        )
        assert receipt is not None and receipt.tool_name == CHAT_REPORT_TOOL
        report_id = path.rsplit("/", 1)[1]
        report = db.get(ChatReport, report_id)
        assert report is not None and report.conversation_id == session["id"]

    download = client.get(path)
    assert download.status_code == 200, download.text
    assert download.headers["content-disposition"].startswith("attachment;")
    assert "sandbox" in download.headers["content-security-policy"]
    assert download.headers["cache-control"] == "private, no-store"
    assert "<script>" not in download.text and "&lt;script&gt;" in download.text
    assert "<img" not in download.text and "&lt;img src=x" in download.text

    # The same user in another Agent Chat sees neither the file nor the report,
    # and that Chat's model call carries no attachment.
    other = client.post(
        "/api/v1/conversations", headers=_headers(csrf), json={"version_id": BASELINE_VERSION_ID}
    ).json()
    assert other["id"] != session["id"]
    other_base = f"/api/v1/conversations/{other['id']}"
    assert client.get(f"{other_base}/attachments").json() == []
    assert (
        client.delete(f"{other_base}/attachments/{attachment_id}", headers=_headers(csrf))
    ).status_code == 404
    assert client.get(f"{other_base}/reports/{report_id}").status_code == 404
    assert _send(client, csrf, other["id"], "你好").status_code == 200
    third = _wire(transport.call_args_list[2])
    assert all("<chat_attachments>" not in str(item["content"]) for item in third["messages"])

    # Another user gets the same 404 for every route.
    _user, stranger_csrf = login(client, "kaikai")
    base = f"/api/v1/conversations/{session['id']}"
    assert client.get(f"{base}/attachments").status_code == 404
    assert _upload(client, stranger_csrf, session["id"]).status_code == 404
    assert (
        client.delete(f"{base}/attachments/{attachment_id}", headers=_headers(stranger_csrf))
    ).status_code == 404
    assert client.get(path).status_code == 404
    with database.session() as db:
        rows = db.scalars(select(ConversationAttachment)).all()
        assert [row.id for row in rows] == [attachment_id]
        assert rows[0].text_content == CHAT_LOG.decode()


def test_agent_chat_attachment_routes_and_purge(
    client: TestClient, database: Database, app_bundle: Any
) -> None:
    _team_row, versions, csrf = _team(client, database)
    session = _create(client, csrf, {"kind": "agent", "version_id": versions[0]})
    attachment_id = _upload(client, csrf, session["id"]).json()["id"]
    _app, _database, settings = app_bundle
    with database.session() as db:
        row = db.get(ConversationAttachment, attachment_id)
        assert row is not None
        stored = settings.resolved_data_root / row.relative_path
    assert stored.read_bytes() == CHAT_LOG
    # Refused types store nothing in an Agent Chat too.
    refused = _upload(client, csrf, session["id"], "photo.png", b"\x89PNG")
    assert refused.status_code == 422
    assert refused.json()["code"] == "chat_attachment_type_unsupported"
    response = client.delete(f"/api/v1/conversations/{session['id']}", headers=_headers(csrf))
    assert response.status_code == 204
    assert not stored.exists()
    with database.session() as db:
        assert db.get(ConversationAttachment, attachment_id) is None
