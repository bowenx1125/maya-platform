"""Public Agno execution bridge; Maya's dispatch port owns every external call."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agno.agent import Agent
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.team import Team, TeamMode

Dispatch = Callable[
    [str, str, Sequence[Message], list[dict[str, Any]] | None, Any, RunContext | None],
    ModelResponse,
]


class TeamDispatchError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.safe_error_code = code
        super().__init__(code)


def _require_completed(output: RunOutput | TeamRunOutput) -> None:
    if output.status != RunStatus.completed:
        code = output.content
        if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
            code = "team_dispatch_failed"
        raise TeamDispatchError(code)


@dataclass(frozen=True)
class MemberSpec:
    participant_id: str
    name: str
    system_message: str
    is_leader: bool = False


class _TeamModel(Model):
    def __init__(self, member_id: str, model_key: str, dispatch: Dispatch) -> None:
        super().__init__(
            id=model_key,
            name="Maya Team member",
            provider="maya",
            retries=0,
            retry_with_guidance=False,
            retry_with_guidance_limit=0,
            cache_response=False,
        )
        self._member_id = member_id
        self._dispatch = dispatch
        self.invocation_id = str(uuid4())
        self._run_context: RunContext | None = None

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        del args
        messages = kwargs.get("messages")
        if not isinstance(messages, (list, tuple)) or not all(
            isinstance(item, Message) for item in messages
        ):
            raise TeamDispatchError("team_messages_invalid")
        run_context = kwargs.get("run_context")
        if isinstance(run_context, RunContext):
            self._run_context = run_context
            self.invocation_id = run_context.run_id
        try:
            return self._dispatch(
                self._member_id,
                self.invocation_id,
                messages,
                kwargs.get("tools"),
                kwargs.get("tool_choice"),
                self._run_context,
            )
        except Exception as exc:
            code = getattr(exc, "safe_error_code", getattr(exc, "code", "team_dispatch_failed"))
            if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
                code = "team_dispatch_failed"
            # SDK errors are observable in RunOutput/logging. Transport bodies
            # and credentials must stay behind the dispatch port.
            raise TeamDispatchError(code) from None

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise TeamDispatchError("team_provider_stream_unsupported")

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        if False:
            yield ModelResponse()
        raise TeamDispatchError("team_provider_stream_unsupported")

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        raise TeamDispatchError("team_response_invalid")

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        raise TeamDispatchError("team_provider_stream_unsupported")


def _agent(
    spec: MemberSpec,
    *,
    model_key: str,
    dispatch: Dispatch,
    additional_input: list[Message],
    actor_id: str,
    tools: Sequence[Any] = (),
) -> Agent:
    model = _TeamModel(spec.participant_id, model_key, dispatch)

    def begin_invocation(run_context: RunContext) -> None:
        model.invocation_id = run_context.run_id

    return Agent(
        id=spec.participant_id,
        name=spec.name,
        user_id=actor_id,
        model=model,
        tools=list(tools),
        pre_hooks=[begin_invocation],
        system_message=spec.system_message,
        build_context=False,
        build_user_context=False,
        additional_input=list(additional_input),
        retries=0,
        fallback_config=None,
        fallback_models=None,
        tool_call_limit=None,
        telemetry=False,
        debug_mode=False,
        cache_callables=False,
        cache_session=False,
        db=None,
        add_history_to_context=False,
        read_chat_history=False,
        read_tool_call_history=False,
        search_past_sessions=False,
        enable_agentic_memory=False,
        update_memory_on_run=False,
        add_memories_to_context=False,
        enable_session_summaries=False,
        add_session_summary_to_context=False,
        add_session_state_to_context=False,
        add_dependencies_to_context=False,
        add_knowledge_to_context=False,
        add_learnings_to_context=False,
        resolve_in_context=False,
        store_history_messages=False,
        store_media=False,
        store_tool_messages=False,
        store_events=False,
        output_schema=None,
        parser_model=None,
        output_model=None,
    )


def run_selected_agent(
    spec: MemberSpec,
    *,
    model_key: str,
    dispatch: Dispatch,
    actor_id: str,
    conversation_id: str,
    turn_id: str,
    history: Sequence[Message],
    message: str,
    tools: Sequence[Any] = (),
) -> RunOutput:
    agent = _agent(
        spec,
        model_key=model_key,
        dispatch=dispatch,
        additional_input=list(history),
        actor_id=actor_id,
        tools=tools,
    )
    output = agent.run(
        Message(role="user", content=message),
        stream=False,
        run_context=RunContext(
            run_id=turn_id, session_id=conversation_id, user_id=actor_id, session_state={}
        ),
    )
    _require_completed(output)
    return output


def run_coordinate_team(
    specs: Sequence[MemberSpec],
    *,
    model_key: str,
    dispatch: Dispatch,
    actor_id: str,
    conversation_id: str,
    turn_id: str,
    history: Sequence[Message],
    message: str,
    participant_tools: Mapping[str, Sequence[Any]] | None = None,
) -> TeamRunOutput:
    leaders = [spec for spec in specs if spec.is_leader]
    if len(leaders) != 1 or len({spec.participant_id for spec in specs}) != len(specs):
        raise TeamDispatchError("team_members_invalid")
    leader = leaders[0]
    tools_by_participant = participant_tools or {}
    current = Message(role="user", content=message)
    members: list[Agent | Team] = [
        _agent(
            spec,
            model_key=model_key,
            dispatch=dispatch,
            additional_input=[*history, current],
            actor_id=actor_id,
            tools=tools_by_participant.get(spec.participant_id, ()),
        )
        for spec in specs
        if not spec.is_leader
    ]
    team = Team(
        id=leader.participant_id,
        name=leader.name,
        user_id=actor_id,
        model=_TeamModel(leader.participant_id, model_key, dispatch),
        tools=list(tools_by_participant.get(leader.participant_id, ())),
        system_message=leader.system_message,
        members=members,
        mode=TeamMode.coordinate,
        additional_input=list(history),
        retries=0,
        fallback_config=None,
        fallback_models=None,
        tool_call_limit=None,
        telemetry=False,
        debug_mode=False,
        cache_callables=False,
        cache_session=False,
        db=None,
        stream_member_events=False,
        add_history_to_context=False,
        add_team_history_to_members=False,
        share_member_interactions=False,
        read_chat_history=False,
        search_past_sessions=False,
        enable_agentic_memory=False,
        update_memory_on_run=False,
        add_memories_to_context=False,
        enable_session_summaries=False,
        add_session_summary_to_context=False,
        add_session_state_to_context=False,
        add_dependencies_to_context=False,
        add_knowledge_to_context=False,
        add_learnings_to_context=False,
        resolve_in_context=False,
        store_history_messages=False,
        store_media=False,
        store_tool_messages=False,
        store_events=False,
        store_member_responses=False,
        output_schema=None,
        output_model=None,
    )
    output = team.run(
        current,
        stream=False,
        run_context=RunContext(
            run_id=turn_id, session_id=conversation_id, user_id=actor_id, session_state={}
        ),
    )
    _require_completed(output)
    return output
