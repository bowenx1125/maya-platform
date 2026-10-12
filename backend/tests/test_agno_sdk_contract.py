"""Synthetic W0 probes for the pinned Agno extension surface."""

from __future__ import annotations

import asyncio
import inspect
import json
import socket
from collections.abc import Callable, Iterable, Iterator
from importlib.metadata import version
from typing import Any

import pytest
from agno.agent import Agent
from agno.exceptions import ModelProviderError, RetryableModelProviderError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.team import Team, TeamMode
from agno.tools import Toolkit


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    attempts: list[tuple[str, Any]] = []

    def deny_network(*args: Any, **kwargs: Any) -> None:
        address = args[1] if len(args) > 1 else kwargs.get("address")
        attempts.append(("socket", address))
        raise OSError("W0 SDK probes must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    yield
    assert attempts == [], "Agno attempted network I/O during a synthetic W0 probe"


class ScriptedModel(Model):
    """A no-network Model implementation that exercises Agno's public run path."""

    def __init__(
        self,
        responses: Iterable[ModelResponse | BaseException]
        | Callable[[dict[str, Any], int], ModelResponse | BaseException],
        *,
        model_id: str = "w0-fake-model",
        retries: int = 0,
        retry_with_guidance: bool = False,
        retry_with_guidance_limit: int = 0,
    ) -> None:
        super().__init__(
            id=model_id,
            retries=retries,
            retry_with_guidance=retry_with_guidance,
            retry_with_guidance_limit=retry_with_guidance_limit,
        )
        self._responses = iter(responses) if not callable(responses) else responses
        self.requests: list[dict[str, Any]] = []

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        messages = kwargs["messages"]
        request = {
            "messages": tuple((message.role, message.content) for message in messages),
            "messages_named": tuple(
                (message.role, message.content, message.name) for message in messages
            ),
            "tools": list(kwargs.get("tools") or []),
        }
        self.requests.append(request)
        if callable(self._responses):
            response = self._responses(kwargs, len(self.requests))
        else:
            response = next(self._responses)
        if isinstance(response, BaseException):
            raise response
        return response

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("The W0 probes must not stream")

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("The W0 probes must not stream")

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        raise AssertionError("Fake Model responses are already normalized")

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        raise AssertionError("The W0 probes must not parse provider deltas")


def tool_call(name: str, arguments: dict[str, Any], call_id: str = "call-1") -> ModelResponse:
    return ModelResponse(
        role="assistant",
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    )


def explicit_agent(model: Model, tools: Any) -> Agent:
    return Agent(
        name="W0 probe",
        model=model,
        tools=tools,
        fallback_config=None,
        fallback_models=None,
        tool_call_limit=None,
        retries=0,
        telemetry=False,
        cache_callables=False,
        add_history_to_context=False,
        read_chat_history=False,
        search_past_sessions=False,
        enable_agentic_memory=False,
        enable_session_summaries=False,
        store_history_messages=False,
    )


class ContextToolkit(Toolkit):
    def __init__(self, value: str) -> None:
        self.value = value
        self.seen: list[tuple[str, str, str | None]] = []
        super().__init__(name="context_probe", tools=[self.read_value], cache_results=False)

    def read_value(self, key: str, run_context: RunContext) -> str:
        """Read a request-bound value.

        Args:
            key: A harmless lookup label.
        """
        self.seen.append((key, run_context.run_id, run_context.user_id))
        return self.value


def contains_ordered_messages(
    actual: tuple[tuple[str, Any], ...], expected: tuple[tuple[str, Any], ...]
) -> bool:
    return any(actual[start : start + len(expected)] == expected for start in range(len(actual)))


def test_pinned_sdk_version_and_runtime_defaults_are_explicitly_visible() -> None:
    assert version("agno") == "3.0.11"

    agent = inspect.signature(Agent.__init__).parameters
    team = inspect.signature(Team.__init__).parameters
    model = inspect.signature(Model.__init__).parameters
    assert agent["retries"].default == 0
    assert agent["fallback_config"].default is None
    assert agent["fallback_models"].default is None
    assert agent["tool_call_limit"].default is None
    assert agent["telemetry"].default is True
    assert agent["cache_callables"].default is True
    assert agent["add_history_to_context"].default is False
    assert agent["num_history_runs"].default is None
    assert team["retries"].default == 0
    assert team["fallback_config"].default is None
    assert team["fallback_models"].default is None
    assert team["tool_call_limit"].default is None
    assert team["telemetry"].default is True
    assert team["cache_callables"].default is True
    assert team["stream_member_events"].default is True
    assert team["add_team_history_to_members"].default is False
    assert team["num_team_history_runs"].default == 3
    assert team["max_iterations"].default == 10
    assert model["retries"].default == 0
    assert model["retry_with_guidance"].default is True
    assert model["retry_with_guidance_limit"].default == 1
    assert "max_tokens" not in agent and "max_tokens" not in team and "max_tokens" not in model


def test_public_agent_tool_call_hides_run_context_and_keeps_full_message_input() -> None:
    model = ScriptedModel(
        [
            tool_call("read_value", {"key": "concept"}),
            ModelResponse(role="assistant", content="answer"),
        ]
    )
    toolkit = ContextToolkit(value="authorized evidence")
    agent = explicit_agent(model, [toolkit])
    history = [
        Message(role="user" if index % 2 == 0 else "assistant", content=f"message-{index}")
        for index in range(14)
    ]
    expected_messages = tuple((message.role, message.content) for message in history)
    context = RunContext(
        run_id="request-1",
        session_id="conversation-1",
        user_id="student-1",
        dependencies={"scope": "course-1"},
    )

    output = agent.run(history, run_context=context)

    assert output.content == "answer"
    assert len(model.requests) == 2
    sent_tools = model.requests[0]["tools"]
    schema = next(
        item["function"] for item in sent_tools if item["function"]["name"] == "read_value"
    )
    assert set(schema["parameters"]["properties"]) == {"key"}
    assert "run_context" not in schema["parameters"]["properties"]
    assert contains_ordered_messages(model.requests[0]["messages"], expected_messages)
    assert ("tool", "authorized evidence") in model.requests[1]["messages"]
    assert toolkit.seen == [("concept", "request-1", "student-1")]
    assert toolkit.cache_results is False
    assert agent.cache_callables is False
    assert agent.tool_call_limit is None
    assert agent.fallback_config is None and agent.fallback_models is None


def test_agent_runs_more_than_ten_tool_steps_without_a_default_cap() -> None:
    tool_steps = 11
    responses: list[ModelResponse] = [
        tool_call("step", {"number": index}, call_id=f"step-{index}") for index in range(tool_steps)
    ]
    responses.append(ModelResponse(role="assistant", content="finished"))

    class StepToolkit(Toolkit):
        def __init__(self) -> None:
            self.completed: list[int] = []
            super().__init__(name="steps", tools=[self.step], cache_results=False)

        def step(self, number: int) -> str:
            """Record one synthetic progress step.

            Args:
                number: The distinct step number.
            """
            self.completed.append(number)
            return f"step-{number}-done"

    model = ScriptedModel(responses)
    toolkit = StepToolkit()
    agent = explicit_agent(model, [toolkit])

    output = agent.run("continue while making progress")

    assert output.content == "finished"
    assert toolkit.completed == list(range(tool_steps))
    assert len(model.requests) == tool_steps + 1
    assert agent.tool_call_limit is None


def test_callable_tool_factory_isolated_per_run_when_cache_is_off() -> None:
    model = ScriptedModel(
        [
            tool_call("read_value", {"key": "same-user"}, "first"),
            ModelResponse(role="assistant", content="first done"),
            tool_call("read_value", {"key": "same-user"}, "second"),
            ModelResponse(role="assistant", content="second done"),
        ]
    )
    toolkits: list[ContextToolkit] = []
    factory_calls: list[tuple[str, str | None]] = []

    def factory(run_context: RunContext) -> list[Toolkit]:
        factory_calls.append((run_context.run_id, run_context.user_id))
        toolkit = ContextToolkit(value=f"for-{run_context.run_id}")
        toolkits.append(toolkit)
        return [toolkit]

    agent = explicit_agent(model, factory)
    first_context = RunContext(run_id="run-first", session_id="same-session", user_id="same-user")
    second_context = RunContext(run_id="run-second", session_id="same-session", user_id="same-user")

    assert agent.run("first", run_context=first_context).content == "first done"
    assert agent.run("second", run_context=second_context).content == "second done"

    assert factory_calls == [("run-first", "same-user"), ("run-second", "same-user")]
    assert len(toolkits) == 2 and toolkits[0] is not toolkits[1]
    assert toolkits[0].seen == [("same-user", "run-first", "same-user")]
    assert toolkits[1].seen == [("same-user", "run-second", "same-user")]
    assert all(toolkit.cache_results is False for toolkit in toolkits)


def test_team_direct_message_list_drops_assistant_turns() -> None:
    leader_model = ScriptedModel([ModelResponse(role="assistant", content="answer")])
    member = Agent(
        id="member",
        name="Member",
        model=ScriptedModel([ModelResponse(role="assistant", content="unused")]),
        telemetry=False,
        cache_callables=False,
        retries=0,
    )
    team = Team(
        name="W0 direct input counterexample",
        model=leader_model,
        members=[member],
        mode=TeamMode.coordinate,
        telemetry=False,
        cache_callables=False,
        add_history_to_context=False,
        add_team_history_to_members=False,
    )
    direct_messages = [
        Message(role="user", content="previous question"),
        Message(role="assistant", content="previous answer"),
        Message(role="user", content="current question"),
    ]

    output = team.run(direct_messages)

    assert output.content == "answer"
    assert ("user", "previous question\ncurrent question") in leader_model.requests[0]["messages"]
    assert not any(
        content == "previous answer" for _, content in leader_model.requests[0]["messages"]
    )


@pytest.mark.parametrize("async_mode", [False, True])
def test_team_additional_input_preserves_history_through_member_delegation(
    async_mode: bool,
) -> None:
    history = [
        Message(
            role=role,
            name=f"speaker-{index}" if role == "assistant" else None,
            content=f"history-{index}-{role}-" + "完整课堂原文🙂" * 3000,
        )
        for index in range(12)
        for role in ("user", "assistant")
    ]
    current = Message(role="user", content="CURRENT_USER_EXACT")
    member1_model = ScriptedModel(
        [ModelResponse(role="assistant", content="MEMBER1_VISIBLE_ANSWER")]
    )
    member2_model = ScriptedModel(
        [ModelResponse(role="assistant", content="MEMBER2_VISIBLE_ANSWER")]
    )
    member1 = Agent(
        id="member1",
        name="Member 1",
        model=member1_model,
        system_message="MEMBER1_PRIVATE_CONFIG_ONLY",
        telemetry=False,
        cache_callables=False,
        retries=0,
        additional_input=[*history, current],
        add_history_to_context=False,
        resolve_in_context=False,
    )
    member2 = Agent(
        id="member2",
        name="Member 2",
        model=member2_model,
        telemetry=False,
        cache_callables=False,
        retries=0,
        additional_input=[*history, current],
        add_history_to_context=False,
        resolve_in_context=False,
    )
    leader_model = ScriptedModel(
        [
            tool_call(
                "delegate_task_to_member",
                {"member_id": member_id, "task": f"task for {member_id}"},
                f"delegate-{member_id}",
            )
            for member_id in ("member1", "member2")
        ]
        + [ModelResponse(role="assistant", content="combined answer")]
    )
    team = Team(
        name="W0 history and delegation probe",
        model=leader_model,
        members=[member1, member2],
        mode=TeamMode.coordinate,
        additional_input=history,
        fallback_config=None,
        fallback_models=None,
        tool_call_limit=None,
        retries=0,
        telemetry=False,
        cache_callables=False,
        stream_member_events=False,
        add_history_to_context=False,
        add_team_history_to_members=False,
        num_team_history_runs=0,
        share_member_interactions=False,
        resolve_in_context=False,
        add_dependencies_to_context=False,
        add_session_state_to_context=False,
        enable_agentic_memory=False,
        update_memory_on_run=False,
        enable_session_summaries=False,
        add_memories_to_context=False,
        add_session_summary_to_context=False,
        learning=False,
        add_learnings_to_context=False,
        offload_tool_results=False,
        compress_tool_results=False,
    )

    output = asyncio.run(team.arun(current)) if async_mode else team.run(current)

    expected = tuple(
        (message.role, message.content, message.name) for message in [*history, current]
    )

    def assert_history_prefix(requests: list[dict[str, Any]]) -> None:
        assert requests
        for request in requests:
            actual = tuple(
                message for message in request["messages_named"] if message[0] != "system"
            )
            assert actual[: len(expected)] == expected

    assert output.content == "combined answer"
    assert len(leader_model.requests) == 3
    assert_history_prefix(leader_model.requests)
    assert_history_prefix(member1_model.requests)
    assert_history_prefix(member2_model.requests)
    assert "MEMBER1_PRIVATE_CONFIG_ONLY" not in str(leader_model.requests)
    assert "MEMBER1_PRIVATE_CONFIG_ONLY" not in str(member2_model.requests)
    assert "MEMBER1_VISIBLE_ANSWER" not in str(member2_model.requests)
    assert all(len(message.content or "") >= 20_000 for message in history)


def test_guidance_retry_defaults_are_disabled_with_zero_guidance_limit() -> None:
    default_model = ScriptedModel(
        [
            RetryableModelProviderError(
                original_error="invalid response", retry_guidance_message="retry guidance"
            ),
            ModelResponse(role="assistant", content="retried"),
        ],
        retry_with_guidance=True,
        retry_with_guidance_limit=1,
    )
    default_output = default_model.response(messages=[Message(role="user", content="x")])
    assert default_output.content == "retried"
    assert len(default_model.requests) == 2

    no_retry_model = ScriptedModel(
        [
            RetryableModelProviderError(
                original_error="invalid response", retry_guidance_message="retry guidance"
            ),
            ModelResponse(role="assistant", content="must not be reached"),
        ],
        retry_with_guidance=False,
        retry_with_guidance_limit=0,
    )
    with pytest.raises(ModelProviderError):
        no_retry_model.response(messages=[Message(role="user", content="x")])
    assert len(no_retry_model.requests) == 1
    assert inspect.signature(Model.__init__).parameters["retry_with_guidance_limit"].default == 1


def test_confirmation_pauses_before_side_effect_and_stop_tool_ends_the_run() -> None:
    class ActionToolkit(Toolkit):
        def __init__(self, *, confirmation: bool = False, stop: bool = False) -> None:
            self.called = False
            super().__init__(
                name="action_probe",
                tools=[self.perform],
                cache_results=False,
                requires_confirmation_tools=["perform"] if confirmation else None,
                stop_after_tool_call_tools=["perform"] if stop else None,
            )

        def perform(self, value: str) -> str:
            """Perform one synthetic action.

            Args:
                value: The action label.
            """
            self.called = True
            return f"performed-{value}"

    paused_model = ScriptedModel(
        [tool_call("perform", {"value": "confirm"}), ModelResponse(content="unexpected")]
    )
    confirm_toolkit = ActionToolkit(confirmation=True)
    paused = explicit_agent(paused_model, [confirm_toolkit]).run("request action")
    assert paused.status.value == "PAUSED"
    assert confirm_toolkit.called is False
    assert len(paused_model.requests) == 1
    assert (
        paused.requirements and paused.requirements[0].tool_execution.requires_confirmation is True
    )

    stop_model = ScriptedModel(
        [tool_call("perform", {"value": "stop"}), ModelResponse(content="unexpected")]
    )
    stop_toolkit = ActionToolkit(stop=True)
    stopped = explicit_agent(stop_model, [stop_toolkit]).run("stop after action")
    assert stop_toolkit.called is True
    assert stopped.status.value == "COMPLETED"
    assert stopped.content == "performed-stop"
    assert len(stop_model.requests) == 1


@pytest.mark.parametrize(("decision", "expected_effects"), [("confirm", 1), ("reject", 0)])
def test_serialized_confirmation_resumes_with_fresh_agent(
    decision: str, expected_effects: int
) -> None:
    preconditions: list[str] = []
    effects: list[str] = []

    class ReceiptToolkit(Toolkit):
        def __init__(self) -> None:
            super().__init__(
                name="receipt_probe",
                tools=[self.read_precondition, self.write_receipt],
                requires_confirmation_tools=["write_receipt"],
                cache_results=False,
            )

        def read_precondition(self) -> str:
            """Record that the synthetic precondition ran."""
            preconditions.append("read")
            return "ready"

        def write_receipt(self, value: str) -> str:
            """Write one synthetic receipt after confirmation.

            Args:
                value: The receipt value.
            """
            effects.append(value)
            return "receipt written"

    def fresh_agent(model: ScriptedModel) -> Agent:
        return Agent(
            id="serialized-confirmation-probe",
            name="W0 confirmation probe",
            model=model,
            tools=[ReceiptToolkit()],
            fallback_config=None,
            fallback_models=None,
            tool_call_limit=None,
            retries=0,
            telemetry=False,
            cache_callables=False,
            add_history_to_context=False,
            read_chat_history=False,
            search_past_sessions=False,
            enable_agentic_memory=False,
            enable_session_summaries=False,
            store_history_messages=False,
        )

    initial_model = ScriptedModel(
        [
            tool_call("read_precondition", {}, "precondition"),
            tool_call("write_receipt", {"value": "synthetic"}, "receipt"),
        ]
    )
    paused = fresh_agent(initial_model).run("create a synthetic receipt")
    assert paused.status.value == "PAUSED"
    assert len(paused.requirements or []) == 1
    assert preconditions == ["read"] and effects == []

    restored = RunOutput.from_dict(paused.to_dict())
    executions = {execution.tool_call_id: execution for execution in restored.tools or []}
    for requirement in restored.requirements or []:
        requirement.tool_execution = executions[requirement.tool_execution.tool_call_id]
        if decision == "confirm":
            requirement.confirm()
        else:
            requirement.reject("synthetic rejection")

    continuation_model = ScriptedModel([ModelResponse(role="assistant", content="completed")])
    resumed = fresh_agent(continuation_model).continue_run(run_response=restored)

    assert resumed.status.value == "COMPLETED"
    assert preconditions == ["read"]
    assert effects == (["synthetic"] if expected_effects else [])
    assert len(initial_model.requests) == 2
    assert len(continuation_model.requests) == 1
