"""Details under Check RAG: what a Chat turn sent to the model.

Owner decision (2026-11-05): nothing reaches the model that the person
chatting cannot see. The view is read back from the stored request bytes,
so these tests compare it with the bytes the provider actually received.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.db import Database
from app.core.models import AgentVersion
from app.modules.demo_baseline.service import BASELINE_AGENT_MD, BASELINE_VERSION_ID
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.chat_reports import CHAT_REPORT_TOOL
from app.modules.workspace.model_input import _call
from app.modules.workspace.models import ConversationTurn, TeamTurnResult
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.test_agent_chat_attachments_reports import (
    _real_provider,
    _reply,
    _report_call,
    _send,
    _wire,
)
from tests.test_chat_attachments import _upload
from tests.test_mayaform_team_conversations import _headers
from tests.test_team_tool_argument_retries import _report_member_turn, _text_body


def _model_input(client: TestClient, conversation_id: str, turn_id: str, **query: str) -> Any:
    return client.get(
        f"/api/v1/conversations/{conversation_id}/turns/{turn_id}/model-input", params=query
    )


def test_agent_chat_details_match_the_sent_request(
    client: TestClient, database: Database, app_bundle: Any, monkeypatch: Any
) -> None:
    client.headers["Origin"] = "http://testserver"
    transport = _real_provider(app_bundle, monkeypatch, [_report_call(), _reply("报告已经生成。")])
    _, csrf = login(client, "bowen")
    session = client.post(
        "/api/v1/conversations", headers=_headers(csrf), json={"version_id": BASELINE_VERSION_ID}
    ).json()
    assert _upload(client, csrf, session["id"]).status_code == 200
    response = _send(client, csrf, session["id"], "帮我分析一下，然后做成报告")
    assert response.status_code == 200, response.text
    turn = response.json()["turns"][-1]
    assert turn["state"] == "ready", turn

    shown = _model_input(client, session["id"], turn["id"])
    assert shown.status_code == 200, shown.text
    calls = shown.json()["calls"]
    sent = [_wire(call) for call in transport.call_args_list]
    assert len(calls) == len(sent) == 2
    for call, body in zip(calls, sent, strict=True):
        assert call["system_prompt"] == body["messages"][0]["content"]
        assert call["agent_md"] == BASELINE_AGENT_MD
        assert {tool["name"] for tool in call["tools"]} == {
            tool["function"]["name"] for tool in body["tools"]
        }
        attachment = next(
            item["content"]
            for item in body["messages"]
            if str(item.get("content") or "").startswith("<chat_attachments>")
        )
        assert call["attachments"] == attachment
        assert call["speaker_name"]
    report_tool = next(tool for tool in calls[0]["tools"] if tool["name"] == CHAT_REPORT_TOOL)
    assert report_tool["description"].startswith("Save a downloadable HTML report")
    assert json.loads(report_tool["parameters"])["type"] == "object"
    assert calls[0]["tool_messages"] == []
    assert [item["role"] for item in calls[1]["tool_messages"]] == ["tool_call", "tool_result"]
    assert calls[1]["tool_messages"][0]["name"] == CHAT_REPORT_TOOL

    # Only the owner of this Chat can read it, and only for its own turns.
    login(client, "maya")
    assert _model_input(client, session["id"], turn["id"]).status_code == 404
    login(client, "bowen")
    assert _model_input(client, session["id"], turn["id"], result_id=turn["id"]).status_code == 404


def test_team_member_details_show_only_that_members_request(
    client: TestClient, database: Database, app_bundle: Any, monkeypatch: Any
) -> None:
    claim, _settings, conversation_id = _report_member_turn(client, database, app_bundle)
    sent: list[dict[str, Any]] = []

    class Response:
        status_code = 200

        def __init__(self, content: bytes) -> None:
            self.content = content

    class Transport:
        @staticmethod
        def timeout() -> float:
            return 30.0

        def post_bytes(self, _endpoint: str, *, content: bytes, **_kwargs: Any) -> Any:
            sent.append(json.loads(content))
            return Response(_text_body("我只说自己的模块。"))

    monkeypatch.setattr("app.modules.workspace.chat_team_provider.HttpxLLMTransport", Transport)
    runtime.execute_team_turn(database.session_factory, claim)

    with database.session() as db:
        [result] = db.scalars(select(TeamTurnResult).where(TeamTurnResult.turn_id == claim.turn_id))
        assert result.state == "ready", result.safe_error_code
        own_md = "# 报告官\n\n只说自己的模块。"
        other_md = "# 小爱鉴定师\n\n只说自己的模块。"
        assert db.scalar(select(AgentVersion).where(AgentVersion.agent_md == own_md)) is not None
    shown = _model_input(client, conversation_id, claim.turn_id, result_id=result.id)
    assert shown.status_code == 200, shown.text
    [call] = shown.json()["calls"]
    assert call["speaker_name"] == "报告官"
    assert call["system_prompt"] == sent[0]["messages"][0]["content"]
    assert call["agent_md"] == own_md
    assert other_md not in json.dumps(call, ensure_ascii=False)
    assert {tool["name"] for tool in call["tools"]} == {
        tool["function"]["name"] for tool in sent[0]["tools"]
    }

    # A server-run assessment turn has no user message and carries the
    # Rubric: it is never shown.
    with database.session() as db:
        turn = db.get(ConversationTurn, claim.turn_id)
        assert turn is not None
        turn.user_text = ""
        db.commit()
    assert _model_input(client, conversation_id, claim.turn_id).status_code == 404


def test_scoring_calls_are_never_shown() -> None:
    system = runtime._member_system(
        "# Scorer",
        "{}",
        assessment_purpose="assessment_evaluate",
        assessment_task_json='{"rubric": "secret"}',
        speaker_name="Scorer",
    )
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": "x"}]}
    assert _call("Scorer", json.dumps(body)) is None


def test_team_member_parts_are_read_from_the_tags() -> None:
    system = runtime._member_system(
        "# Ada\n\nI explain engines.",
        '{"knowledge_sets": [{"markdown": "Gears"}]}',
        speaker_name="Ada",
        assessment_capable=False,
    )
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": "x"}]}
    call = _call("Ada", json.dumps(body))
    assert call is not None
    assert call.agent_md == "# Ada\n\nI explain engines."
    assert call.knowledge == '{"knowledge_sets": [{"markdown": "Gears"}]}'
    assert call.attachments is None and call.tools == []
