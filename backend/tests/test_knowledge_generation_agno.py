"""Focused no-network tests for the bounded Knowledge Agno adapter."""

from __future__ import annotations

import hashlib
import json
import socket
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

import pytest
from agno.agent import Agent
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run.base import RunStatus
from app.modules.knowledge_sets.generation_provider import (
    KnowledgeGenerationInvokeError,
    _KnowledgeGenerationModel,
    run_knowledge_generation_agent,
)


@pytest.fixture(autouse=True)
def socket_block(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    attempts: list[object] = []

    def deny(*args: Any, **kwargs: Any) -> None:
        del kwargs
        attempts.append(args[1] if len(args) > 1 else None)
        raise AssertionError("Agno Knowledge tests must not open a socket")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    yield
    assert attempts == []


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def test_agent_hands_exact_final_messages_to_one_dispatch_and_hashes_exact_bytes() -> None:
    system = "Build only the requested learning assets."
    user = '{"lesson":"Ω and full source text","note":"keep every line"}'
    captured: list[tuple[tuple[str, str], ...]] = []
    wire: list[bytes] = []
    request_hashes: list[str] = []

    def dispatch(messages: tuple[Message, ...] | Any) -> ModelResponse:
        observed = tuple((message.role, message.content) for message in messages)
        captured.append(observed)
        body = {
            "model": "maya-fake-model",
            "messages": [{"role": role, "content": content} for role, content in observed],
            "enable_thinking": False,
            "stream": False,
        }
        exact_bytes = _canonical_json_bytes(body)
        wire.append(exact_bytes)
        request_hashes.append(hashlib.sha256(exact_bytes).hexdigest())
        return ModelResponse(role="assistant", content='{"assets":[]}')

    output = run_knowledge_generation_agent(
        system_message=system,
        user_message=user,
        model_key="maya-fake-model",
        dispatch_once=dispatch,
    )

    assert output.status == RunStatus.completed
    assert output.content == '{"assets":[]}'
    assert captured == [(("system", system), ("user", user))]
    assert len(wire) == len(request_hashes) == 1
    assert hashlib.sha256(wire[0]).hexdigest() == request_hashes[0]
    assert json.loads(wire[0]) == {
        "model": "maya-fake-model",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "enable_thinking": False,
        "stream": False,
    }


def test_fresh_agent_and_model_disable_implicit_sdk_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_run = Agent.run
    captured_agents: list[Agent] = []

    def record_agent(agent: Agent, *args: Any, **kwargs: Any) -> Any:
        captured_agents.append(agent)
        return original_run(agent, *args, **kwargs)

    monkeypatch.setattr(Agent, "run", record_agent)
    output = run_knowledge_generation_agent(
        system_message="system",
        user_message="user",
        model_key="fake-model",
        dispatch_once=lambda _: ModelResponse(role="assistant", content="done"),
    )

    assert output.status == RunStatus.completed
    assert len(captured_agents) == 1
    agent = captured_agents[0]
    model = agent.model
    assert model is not None
    assert agent.tools == []
    assert agent.retries == 0
    assert agent.fallback_config is None and agent.fallback_models is None
    assert agent.telemetry is False
    assert agent.cache_callables is False and agent.cache_session is False
    assert agent.db is None and agent.tool_call_limit is None
    assert agent.add_history_to_context is False
    assert agent.read_chat_history is False and agent.read_tool_call_history is False
    assert agent.search_past_sessions is False
    assert agent.enable_agentic_memory is False and agent.update_memory_on_run is False
    assert agent.enable_session_summaries is False
    assert agent.add_knowledge_to_context is False and agent.add_learnings_to_context is False
    assert agent.search_knowledge is False and agent.update_knowledge is False
    assert agent.add_search_knowledge_instructions is False
    assert agent.send_media_to_model is False
    assert agent.store_history_messages is False and agent.store_tool_messages is False
    assert agent.store_media is False and agent.store_events is False
    assert model.retries == 0
    assert model.retry_with_guidance is False and model.retry_with_guidance_limit == 0
    assert model.cache_response is False
    assert not hasattr(model, "max_tokens")


def test_ordinary_authorization_and_api_key_terms_in_lesson_are_not_blocked() -> None:
    lesson = "Explain Authorization headers and why an API key must remain private."
    dispatched: list[tuple[str, str]] = []

    def dispatch(messages: tuple[Message, ...] | Any) -> ModelResponse:
        dispatched.extend((message.role, message.content) for message in messages)
        return ModelResponse(role="assistant", content="lesson assets")

    result = run_knowledge_generation_agent(
        system_message="Generate teaching assets.",
        user_message=lesson,
        model_key="fake-model",
        dispatch_once=dispatch,
    )

    assert result.status == RunStatus.completed
    assert ("user", lesson) in dispatched


def test_second_invoke_fails_closed_before_a_second_dispatch() -> None:
    calls: list[int] = []

    def dispatch(_: tuple[Message, ...]) -> ModelResponse:
        calls.append(1)
        return ModelResponse(role="assistant", content="ok")

    model = _KnowledgeGenerationModel("fake-model", dispatch)
    messages = [Message(role="system", content="system"), Message(role="user", content="user")]

    assert model.invoke(messages=messages, tools=None).content == "ok"
    with pytest.raises(KnowledgeGenerationInvokeError) as raised:
        model.invoke(messages=messages, tools=None)

    assert raised.value.safe_error_code == "knowledge_invocation_already_bound"
    assert calls == [1]


def test_concurrent_invoke_fails_closed_before_a_second_dispatch() -> None:
    entered = Event()
    release = Event()
    calls: list[int] = []

    def dispatch(_: tuple[Message, ...]) -> ModelResponse:
        calls.append(1)
        entered.set()
        assert release.wait(timeout=2)
        return ModelResponse(role="assistant", content="ok")

    model = _KnowledgeGenerationModel("fake-model", dispatch)
    messages = [Message(role="system", content="system"), Message(role="user", content="user")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(model.invoke, messages=messages, tools=None)
        assert entered.wait(timeout=2)
        with pytest.raises(KnowledgeGenerationInvokeError) as raised:
            model.invoke(messages=messages, tools=None)
        release.set()
        assert first.result(timeout=2).content == "ok"

    assert raised.value.safe_error_code == "knowledge_invocation_already_bound"
    assert calls == [1]


def test_dispatch_exception_does_not_leak_provider_body_or_credential(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinel = "Bearer synthetic-secret raw-provider-body"

    def dispatch(_: tuple[Message, ...]) -> ModelResponse:
        raise RuntimeError(sentinel)

    with pytest.raises(KnowledgeGenerationInvokeError) as raised:
        run_knowledge_generation_agent(
            system_message="system",
            user_message="user",
            model_key="fake-model",
            dispatch_once=dispatch,
        )

    assert raised.value.safe_error_code == "knowledge_generation_run_failed"
    assert sentinel not in str(raised.value)
    assert sentinel not in caplog.text


def test_unsafe_model_response_and_run_error_are_not_reported_as_success() -> None:
    calls: list[int] = []

    def tool_response(_: tuple[Message, ...]) -> ModelResponse:
        calls.append(1)
        return ModelResponse(
            role="assistant",
            content="unsafe",
            tool_calls=[
                {
                    "id": "synthetic-call",
                    "type": "function",
                    "function": {"name": "write", "arguments": "{}"},
                }
            ],
        )

    with pytest.raises(KnowledgeGenerationInvokeError):
        run_knowledge_generation_agent(
            system_message="system",
            user_message="user",
            model_key="fake-model",
            dispatch_once=tool_response,
        )
    assert calls == [1]

    def failed(_: tuple[Message, ...]) -> ModelResponse:
        raise KnowledgeGenerationInvokeError("safe_operation_error")

    with pytest.raises(KnowledgeGenerationInvokeError):
        run_knowledge_generation_agent(
            system_message="system",
            user_message="user",
            model_key="fake-model",
            dispatch_once=failed,
        )
