"""What a Chat turn sent to the model, for the Details view under Check RAG.

Owner decision (2026-11-05): everything sent to the model is visible to the
person chatting. RAG excerpts already show in Check RAG; Details shows the
rest: system prompt, AGENT.md, Knowledge, attachments and Tools. It is read
from the stored request bytes of each model call, so it cannot drift from
what was actually sent. Server-run assessment scoring and summary calls keep
their Rubric and reference answers away from the student and are not shown.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Error, not_found
from app.modules.auth.dependencies import get_db, require_auth
from app.modules.auth.service import AuthContext
from app.modules.runtime_tools.models import RuntimeModelCallStage

from .models import (
    ConversationParticipant,
    ConversationTurn,
    TeamProviderCall,
    TeamTurnResult,
)
from .schemas import ModelInput, ModelInputCall, ModelInputTool, ModelInputToolMessage

router = APIRouter(tags=["Chat"])

_ATTACHMENTS_OPEN = "<chat_attachments>\n"
_EXECUTOR_CONTEXT = "<assessment_executor_private_context>"


def _between(text: str, start: str, end: str) -> str | None:
    head = text.find(start)
    if head < 0:
        return None
    tail = text.rfind(end)
    if tail < head + len(start):
        return None
    return text[head + len(start) : tail]


def _agent_parts(system: str) -> tuple[str | None, str | None]:
    """AGENT.md and Knowledge exactly as they appear inside the system prompt."""

    # One-to-one Agent Chat: rules, a newline, then one JSON object.
    rules, _, tail = system.partition("\n")
    if rules and tail.startswith("{"):
        try:
            context = json.loads(tail)
        except json.JSONDecodeError:
            context = None
        if isinstance(context, dict) and isinstance(context.get("agent_markdown"), str):
            knowledge = context.get("canonical_knowledge")
            return context["agent_markdown"], (
                json.dumps(knowledge, ensure_ascii=False, indent=2) if knowledge else None
            )
    # Team member: tagged blocks.
    agent_md = _between(system, "<agent_instructions>\n", "\n</agent_instructions>")
    knowledge = _between(system, "<authorized_knowledge>\n", "\n</authorized_knowledge>")
    if knowledge is not None and knowledge.strip() in {"", "{}", "[]"}:
        knowledge = None
    return agent_md, knowledge


def _text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _call(speaker_name: str, request_json: str) -> ModelInputCall | None:
    try:
        body = json.loads(request_json)
    except json.JSONDecodeError:
        return None
    messages = body.get("messages") if isinstance(body, dict) else None
    if not isinstance(messages, list) or not messages or not isinstance(messages[0], dict):
        return None
    system = messages[0].get("content")
    if messages[0].get("role") != "system" or not isinstance(system, str):
        return None
    if _EXECUTOR_CONTEXT in system:
        return None
    agent_md, knowledge = _agent_parts(system)
    attachments: str | None = None
    tool_messages: list[ModelInputToolMessage] = []
    for message in messages[1:]:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if message.get("role") == "user" and isinstance(content, str):
            if content.startswith(_ATTACHMENTS_OPEN):
                attachments = content
        elif message.get("role") == "assistant" and isinstance(message.get("tool_calls"), list):
            for item in message["tool_calls"]:
                function = item.get("function") if isinstance(item, dict) else None
                if isinstance(function, dict):
                    tool_messages.append(
                        ModelInputToolMessage(
                            role="tool_call",
                            name=_text(function.get("name")),
                            content=_text(function.get("arguments", "")),
                        )
                    )
        elif message.get("role") == "tool":
            name = message.get("name")
            tool_messages.append(
                ModelInputToolMessage(
                    role="tool_result",
                    name=name if isinstance(name, str) else None,
                    content=_text(content),
                )
            )
    tools: list[ModelInputTool] = []
    for tool in body.get("tools") or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            continue
        tools.append(
            ModelInputTool(
                name=_text(function.get("name", "")),
                description=_text(function.get("description", "")),
                parameters=json.dumps(function.get("parameters", {}), ensure_ascii=False, indent=2),
            )
        )
    return ModelInputCall(
        speaker_name=speaker_name,
        system_prompt=system,
        agent_md=agent_md,
        knowledge=knowledge,
        attachments=attachments,
        tools=tools,
        tool_messages=tool_messages,
    )


def _requests(
    db: Session, conversation: Any, turn: ConversationTurn, result_id: str | None
) -> list[tuple[str, str]]:
    if conversation.entry_kind == "agent":
        if result_id is not None:
            raise not_found()
        stages = db.scalars(
            select(RuntimeModelCallStage)
            .where(
                RuntimeModelCallStage.conversation_id == conversation.id,
                RuntimeModelCallStage.turn_id == turn.id,
            )
            .order_by(RuntimeModelCallStage.dispatch_ordinal, RuntimeModelCallStage.ordinal)
        )
        # A not-sent retry re-stages the same body under the next ordinal.
        latest: dict[int, str] = {}
        for stage in stages:
            latest[stage.dispatch_ordinal] = stage.request_json
        name = conversation.agent_name_snapshot
        return [(name, latest[key]) for key in sorted(latest)]
    statement = (
        select(TeamTurnResult, TeamProviderCall)
        .join(TeamProviderCall, TeamProviderCall.result_id == TeamTurnResult.id)
        .where(
            TeamTurnResult.conversation_id == conversation.id,
            TeamTurnResult.turn_id == turn.id,
        )
        .order_by(TeamTurnResult.ordinal, TeamProviderCall.ordinal)
    )
    if result_id is not None:
        statement = statement.where(TeamTurnResult.id == result_id)
    names = {
        participant.id: participant.display_name
        for participant in db.scalars(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation.id
            )
        )
    }
    requests: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for result, call in db.execute(statement).tuples():
        if (result.id, call.request_hash) in seen:
            continue
        seen.add((result.id, call.request_hash))
        requests.append((names.get(result.participant_id, ""), call.request_json))
    return requests


@router.get(
    "/conversations/{conversation_id}/turns/{turn_id}/model-input",
    response_model=ModelInput,
    operation_id="getChatTurnModelInput",
    responses={404: {"model": Error}},
)
def get_chat_turn_model_input(
    conversation_id: UUID,
    turn_id: UUID,
    result_id: str | None = Query(
        None,
        description="A Team member's reply in this turn. Omit for an Agent Chat or every member.",
        json_schema_extra={"format": "uuid"},
    ),
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> ModelInput:
    from .chat import owned_conversation

    conversation = owned_conversation(db, context, str(conversation_id))
    if result_id is not None:
        try:
            result_id = str(UUID(result_id))
        except ValueError:
            raise not_found() from None
    turn = db.get(ConversationTurn, str(turn_id))
    # A server-run assessment turn has no user message and carries the
    # Rubric; it is never shown, so it reads as absent.
    if turn is None or turn.conversation_id != conversation.id or turn.user_text == "":
        raise not_found()
    calls = [
        call
        for speaker_name, request_json in _requests(db, conversation, turn, result_id)
        if (call := _call(speaker_name, request_json)) is not None
    ]
    return ModelInput(calls=calls)
