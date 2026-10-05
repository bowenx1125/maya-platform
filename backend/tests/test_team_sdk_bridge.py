"""No-network tests of Maya's public Agno Team bridge."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from agno.models.message import Message
from agno.models.response import ModelResponse
from app.modules.workspace.chat_team_sdk import (
    MemberSpec,
    TeamDispatchError,
    run_coordinate_team,
    run_selected_agent,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    attempts: list[object] = []

    def deny(*args: Any, **kwargs: Any) -> None:
        attempts.append(args)
        raise AssertionError("Synthetic Team bridge must not use network")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    yield
    assert not attempts


def test_coordinate_supports_twelve_effective_delegations_with_full_history() -> None:
    calls: list[tuple[str, list[tuple[str, Any, str | None]], Any]] = []
    leader_calls = 0
    history = [
        Message(role=role, content=f"{index}:{role}:" + "完整原文🙂" * 6000)
        for index in range(6)
        for role in ("user", "assistant")
    ]

    def dispatch(
        member: str,
        invocation_id: str,
        messages: Sequence[Message],
        tools: Any,
        choice: Any,
        run_context: Any,
    ) -> ModelResponse:
        del run_context
        nonlocal leader_calls
        calls.append((member, [(m.role, m.content, m.name) for m in messages], tools))
        if member != "leader":
            return ModelResponse(role="assistant", content=f"reply {len(calls)}")
        leader_calls += 1
        if leader_calls <= 12:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": f"delegate-{leader_calls}",
                        "type": "function",
                        "function": {
                            "name": "delegate_task_to_member",
                            "arguments": json.dumps(
                                {
                                    "member_id": "one" if leader_calls % 2 else "two",
                                    "task": f"distinct useful task {leader_calls}",
                                }
                            ),
                        },
                    }
                ],
            )
        return ModelResponse(role="assistant", content="leader final")

    output = run_coordinate_team(
        [
            MemberSpec("leader", "Leader", "LEADER_PRIVATE", True),
            MemberSpec("one", "One", "ONE_PRIVATE"),
            MemberSpec("two", "Two", "TWO_PRIVATE"),
        ],
        model_key="synthetic",
        dispatch=dispatch,
        actor_id="actual-student",
        conversation_id="conversation",
        turn_id="turn",
        history=history,
        message="CURRENT_EXACT",
    )

    assert output.content == "leader final"
    assert len(calls) == 25
    assert leader_calls == 13
    assert output.tools and all(not tool.tool_call_error for tool in output.tools)
    assert [member for member, _, _ in calls].count("one") == 6
    assert [member for member, _, _ in calls].count("two") == 6
    expected = [(m.role, m.content, m.name) for m in history]
    expected.append(("user", "CURRENT_EXACT", None))
    for member, messages, _ in calls:
        content = [item for item in messages if item[0] != "system"]
        assert content[: len(expected)] == expected
        for other in {"leader", "one", "two"} - {member}:
            assert f"{other.upper()}_PRIVATE" not in str(messages)


def test_selected_member_does_not_call_leader_or_retry_failed_dispatch() -> None:
    calls: list[str] = []

    def dispatch(*args: Any) -> ModelResponse:
        calls.append(args[0])
        raise RuntimeError("secret transport body")

    with pytest.raises(TeamDispatchError, match="^team_dispatch_failed$"):
        run_selected_agent(
            MemberSpec("selected", "Selected", "PRIVATE"),
            model_key="synthetic",
            dispatch=dispatch,
            actor_id="actual-student",
            conversation_id="conversation",
            turn_id="turn",
            history=[],
            message="current",
        )
    assert calls == ["selected"]
