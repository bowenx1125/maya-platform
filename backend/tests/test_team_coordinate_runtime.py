"""Persisted native coordinate runs with synthetic Provider callbacks."""

from __future__ import annotations

import json
from typing import Any

from agno.models.response import ModelResponse
from app.core.models import ProviderOperation
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.models import (
    Conversation,
    ConversationTurn,
    TeamChatEvent,
    TeamTurnResult,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.test_mayaform_team_conversations import _headers
from tests.test_mayaform_team_turns import _body, _chat


def test_coordinate_twelve_effective_delegations_keep_every_result_and_replay_no_calls(
    client: TestClient, database: Any, monkeypatch: Any
) -> None:
    session, csrf, actor_id = _chat(client, database)
    members = session["team"]["members"]
    leader_id = members[0]["id"]
    member_id = members[1]["id"]
    calls: list[runtime.MemberRequest] = []
    leader_calls = 0

    def invoke(request: runtime.MemberRequest, messages: Any, tools: Any) -> ModelResponse:
        nonlocal leader_calls
        calls.append(request)
        assert request.actor_id == actor_id
        if request.participant_id != leader_id:
            return ModelResponse(role="assistant", content=f"independent result {len(calls)}")
        leader_calls += 1
        if leader_calls <= 12:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": f"effective-{leader_calls}",
                        "type": "function",
                        "function": {
                            "name": "delegate_task_to_member",
                            "arguments": json.dumps(
                                {"member_id": member_id, "task": f"useful subtask {leader_calls}"}
                            ),
                        },
                    }
                ],
            )
        assert all(not m.tool_call_error for m in messages if m.role == "tool")
        return ModelResponse(role="assistant", content="coordinated final")

    monkeypatch.setattr(runtime, "invoke_mock_team_model", invoke)
    body = _body(session, "auto")
    url = f"/api/v1/conversations/{session['id']}/messages"
    response = client.post(url, headers=_headers(csrf), json=body)
    assert response.status_code == 200, response.text
    turn = next(item for item in response.json()["turns"] if item["user_text"])
    assert turn["state"] == "ready", turn
    assert len(calls) == 25 and leader_calls == 13
    results = turn["member_results"]
    assert len(results) == len({result["id"] for result in results}) == 13
    assert sum(result["participant_id"] == member_id for result in results) == 12
    assert results[0]["assistant_text"] == "coordinated final"
    assert len({result["assistant_text"] for result in results[1:]}) == 12
    assert client.post(url, headers=_headers(csrf), json=body).json() == response.json()
    assert len(calls) == 25
    with database.session() as db:
        # Without a complete published recipe the Team has no Leader opening.
        assert db.scalar(select(func.count()).select_from(ConversationTurn)) == 1
        assert db.scalar(select(func.count()).select_from(TeamTurnResult)) == 13
        assert db.scalar(select(func.count()).select_from(TeamChatEvent)) == 15
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0
        assert db.get(Conversation, session["id"]).active_request_id is None


def test_default_auto_sse_has_committed_member_results_and_owner_can_continue(
    client: TestClient, database: Any
) -> None:
    session, csrf, _actor = _chat(client, database)
    body = _body(session, "auto")
    url = f"/api/v1/conversations/{session['id']}/messages:stream"
    headers = {**_headers(csrf), "Accept": "text/event-stream"}
    response = client.post(url, headers=headers, json=body)
    assert response.status_code == 200
    assert response.text.count("event: member_result") == 3
    assert response.text.count("event: turn_done") == 1
    saved = client.get(f"/api/v1/conversations/{session['id']}").json()
    sent = next(item for item in saved["turns"] if item["user_text"])
    assert sent["state"] == "ready" and saved["can_send"] is True
    assert client.post(url, headers=headers, json=body).text == response.text
