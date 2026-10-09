"""No-progress cycle pausing is based on durable repeated Tool outcomes, not a total cap."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from agno.models.message import Message
from agno.models.response import ModelResponse
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.chat_team_provider import (
    has_repeated_no_progress_tool_cycle,
    stalled_refusal_code,
)
from fastapi.testclient import TestClient

from tests.test_mayaform_team_conversations import _headers
from tests.test_mayaform_team_turns import _chat


def _cycle(
    first_args: dict[str, Any],
    first_result: str,
    second_args: dict[str, Any],
    second_result: str,
) -> list[Message]:
    return [
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "read_memory", "arguments": json.dumps(first_args)},
                }
            ],
        ),
        Message(role="tool", tool_call_id="call-1", content=first_result),
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-2",
                    "type": "function",
                    "function": {"name": "read_memory", "arguments": json.dumps(second_args)},
                }
            ],
        ),
        Message(role="tool", tool_call_id="call-2", content=second_result),
    ]


def test_loop_fingerprint_requires_same_available_tool_arguments_and_result() -> None:
    tools = [
        {
            "type": "function",
            "function": {"name": "read_memory", "parameters": {"type": "object"}},
        }
    ]
    same = _cycle({"scope": "own"}, '{"count":1}', {"scope": "own"}, '{"count":1}')
    different_args = _cycle({"scope": "own"}, '{"count":1}', {"scope": "shared"}, '{"count":1}')
    different_result = _cycle({"scope": "own"}, '{"count":1}', {"scope": "own"}, '{"count":2}')
    assert has_repeated_no_progress_tool_cycle(same, tools) is True
    assert has_repeated_no_progress_tool_cycle(different_args, tools) is False
    assert has_repeated_no_progress_tool_cycle(different_result, tools) is False
    assert has_repeated_no_progress_tool_cycle(same, []) is False
    assert stalled_refusal_code(same, tools) == "agent_cannot"
    denied = _cycle(
        {"scope": "own"},
        '{"ok":false,"code":"tool_not_authorized"}',
        {"scope": "own"},
        '{"ok":false,"code":"tool_not_authorized"}',
    )
    assert stalled_refusal_code(denied, tools) == "agent_cannot_see"
    delegated = [
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "delegate_task_to_member",
                        "arguments": json.dumps({"member_id": "m", "task": "same"}),
                    },
                }
            ],
        ),
        Message(role="tool", tool_call_id="call-1", content='{"ok":true}'),
        Message(
            role="assistant",
            tool_calls=[
                {
                    "id": "call-2",
                    "type": "function",
                    "function": {
                        "name": "delegate_task_to_member",
                        "arguments": json.dumps({"member_id": "m", "task": "same"}),
                    },
                }
            ],
        ),
        Message(role="tool", tool_call_id="call-2", content='{"ok":true}'),
    ]
    delegate_tools = [
        {
            "type": "function",
            "function": {"name": "delegate_task_to_member", "parameters": {"type": "object"}},
        }
    ]
    assert has_repeated_no_progress_tool_cycle(delegated, delegate_tools) is True
    assert stalled_refusal_code(delegated, delegate_tools) is None


def test_coordinate_cycle_pauses_and_explicit_resume_continues_saved_run(
    client: TestClient, database: Any, monkeypatch: Any
) -> None:
    session, csrf, _actor = _chat(client, database)
    leader_id, member_id = [row["id"] for row in session["team"]["members"][:2]]
    leader_calls = 0

    def invoke(request: runtime.MemberRequest, messages: Any, _tools: Any) -> ModelResponse:
        nonlocal leader_calls
        if request.participant_id != leader_id:
            return ModelResponse(role="assistant", content="same member outcome")
        leader_calls += 1
        # The first turn executes two identical delegations, then the runtime
        # pauses before a third Provider/model request. Explicit resume is a new
        # invocation of the same durable turn and can now produce a conclusion.
        if leader_calls <= 3:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": f"repeated-{leader_calls}",
                        "type": "function",
                        "function": {
                            "name": "delegate_task_to_member",
                            "arguments": json.dumps(
                                {"member_id": member_id, "task": "same useful task"}
                            ),
                        },
                    }
                ],
            )
        return ModelResponse(role="assistant", content="resumed conclusion")

    monkeypatch.setattr(runtime, "invoke_mock_team_model", invoke)
    body = {
        "request_id": "",
        "expected_revision": session["revision"],
        "message": "Please complete the work.",
        "routing": {"mode": "auto", "participant_ids": []},
    }
    body["request_id"] = str(uuid4())
    messages_url = f"/api/v1/conversations/{session['id']}/messages"
    paused = client.post(messages_url, headers=_headers(csrf), json=body)
    assert paused.status_code == 200, paused.text
    turn = paused.json()["turns"][0]
    assert turn["state"] == "paused"
    assert turn["safe_error_code"] == "team_no_progress"
    assert leader_calls == 2

    resume_url = f"/api/v1/conversations/{session['id']}/turns/{turn['id']}:resume"
    resumed = client.post(resume_url, headers=_headers(csrf))
    assert resumed.status_code == 200, resumed.text
    final = resumed.json()["turns"][0]
    assert final["state"] == "ready"
    assert final["member_results"][0]["assistant_text"] == "resumed conclusion"
    assert len(final["member_results"]) == 3
