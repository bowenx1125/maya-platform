"""Bind real Agno FunctionCall identities to transactional Maya Tool handlers."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from typing import Any

from agno.tools.function import Function, FunctionCall
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import PlatformError, conflict
from app.modules.auth.service import AuthContext
from app.modules.workspace.models import (
    Conversation,
    ConversationTurn,
    TeamProviderCall,
    TeamTurnResult,
)

from .models import RuntimeModelCallStage
from .registry import ToolCallIdentity, ToolSpec, execute_tool, exposed_tools

SessionFactory = Callable[[], Session]


def _call_identity(
    db: Session,
    *,
    conversation_id: str,
    turn_id: str,
    participant_id: str,
    call: FunctionCall,
    conversation_revision: int,
    claim_token: str | None,
) -> ToolCallIdentity:
    if not call.call_id:
        raise conflict("tool_call_unverified", "The model did not supply a Tool call identity.")
    stages: list[TeamProviderCall | RuntimeModelCallStage] = list(
        db.scalars(
            select(TeamProviderCall)
            .join(TeamTurnResult, TeamTurnResult.id == TeamProviderCall.result_id)
            .where(
                TeamTurnResult.conversation_id == conversation_id,
                TeamTurnResult.turn_id == turn_id,
                TeamTurnResult.participant_id == participant_id,
                TeamProviderCall.accepted_response_json.is_not(None),
            )
            .order_by(TeamTurnResult.ordinal.desc(), TeamProviderCall.ordinal.desc())
        )
    )
    stages.extend(
        db.scalars(
            select(RuntimeModelCallStage)
            .where(
                RuntimeModelCallStage.conversation_id == conversation_id,
                RuntimeModelCallStage.turn_id == turn_id,
                RuntimeModelCallStage.executor_agent_version_id == participant_id,
                RuntimeModelCallStage.accepted_response_json.is_not(None),
            )
            .order_by(RuntimeModelCallStage.ordinal.desc())
        )
    )
    for stage in stages:
        try:
            body = json.loads(stage.accepted_response_json or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(body, dict):
            continue
        choices = body.get("choices")
        message = (
            choices[0].get("message")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict)
            else body
        )
        if not isinstance(message, dict):
            continue
        calls = message.get("tool_calls")
        for candidate in calls if isinstance(calls, list) else []:
            if isinstance(candidate, dict) and candidate.get("id") == call.call_id:
                return ToolCallIdentity(
                    conversation_id,
                    turn_id,
                    participant_id,
                    stage.id if isinstance(stage, TeamProviderCall) else stage.operation_id,
                    call.call_id,
                    conversation_revision,
                    claim_token,
                )
    raise conflict("tool_call_unverified", "This Tool call has no saved accepted model result.")


def bind_runtime_functions(
    factory: SessionFactory,
    actor: AuthContext,
    *,
    conversation_id: str,
    participant_id: str,
    turn_id: str,
    registry: Mapping[str, ToolSpec],
) -> list[Function]:
    with factory() as db:
        specs = exposed_tools(db, actor, conversation_id, registry)
        conversation = db.get(Conversation, conversation_id)
        turn = db.get(ConversationTurn, turn_id)
        if conversation is None or turn is None or turn.conversation_id != conversation.id:
            raise conflict("tool_run_inactive", "Continue through the current run.")
        conversation_revision = conversation.revision
        claim_token = turn.claim_token
    return [
        _bind_one(
            factory,
            actor,
            conversation_id,
            participant_id,
            turn_id,
            spec,
            registry,
            conversation_revision,
            claim_token,
        )
        for spec in specs
    ]


def _bind_one(
    factory: SessionFactory,
    actor: AuthContext,
    conversation_id: str,
    participant_id: str,
    turn_id: str,
    spec: ToolSpec,
    registry: Mapping[str, ToolSpec],
    conversation_revision: int,
    claim_token: str | None,
) -> Function:
    current_call: ContextVar[FunctionCall | None] = ContextVar(
        f"maya_tool_{spec.name}", default=None
    )

    def capture(fc: FunctionCall) -> None:
        current_call.set(fc)

    def invoke(arguments: dict[str, Any]) -> dict[str, Any]:
        call = current_call.get()
        if call is None:
            return {
                "ok": False,
                "code": "tool_call_unverified",
                "message": "Use this Tool through the current authorized run.",
            }
        try:
            with factory() as db:
                if db.get_bind().dialect.name == "sqlite":
                    db.execute(text("BEGIN IMMEDIATE"))
                identity = _call_identity(
                    db,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    participant_id=participant_id,
                    call=call,
                    conversation_revision=conversation_revision,
                    claim_token=claim_token,
                )
                result = execute_tool(db, actor, identity, spec.name, arguments, registry)
                db.commit()
                return result
        except PlatformError as exc:
            return {"ok": False, "code": exc.code, "message": exc.message}
        finally:
            current_call.set(None)

    function = Function.from_callable(invoke, name=spec.name)
    payload_schema = spec.payload_model.model_json_schema()
    definitions = payload_schema.pop("$defs", None)
    function.parameters = {
        "type": "object",
        "properties": {"arguments": payload_schema},
        "required": ["arguments"],
        "additionalProperties": False,
    }
    if definitions is not None:
        function.parameters["$defs"] = definitions
    function.description = spec.description
    function.pre_hook = capture
    function.cache_results = False
    function.stop_after_tool_call = spec.stop_after_tool_call
    return function
