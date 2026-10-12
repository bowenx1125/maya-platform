"""Account-scoped Agent notes. Assessment rows and Debate inputs stay elsewhere."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.core.models import Agent, AgentVersion
from app.modules.auth.service import AuthContext
from app.modules.workspace.models import (
    AgentAccountMemory,
    Conversation,
    ConversationParticipant,
    ConversationTurn,
)

from .registry import ToolCallIdentity, ToolSpec

_MEMORY_LIMIT = 50


class ReadAgentMemoryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WriteAgentMemoryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)
    memory_id: str | None = Field(default=None, min_length=36, max_length=36)
    member_names: list[str] = Field(default_factory=list, max_length=8)


def _speaking(db: Session, row: Conversation, identity: ToolCallIdentity) -> tuple[str, str, bool]:
    if row.entry_kind == "agent":
        version = db.get(AgentVersion, row.agent_version_id)
        agent = db.get(Agent, version.agent_id) if version is not None else None
        if agent is None:
            raise not_found()
        return agent.id, agent.name, False
    participant = db.get(ConversationParticipant, identity.participant_id)
    if participant is None or participant.conversation_id != row.id:
        raise not_found()
    return participant.agent_id, participant.display_name, bool(participant.is_leader)


def _current_turn(db: Session, row: Conversation, identity: ToolCallIdentity) -> ConversationTurn:
    turn = db.get(ConversationTurn, identity.turn_id)
    if turn is None or turn.conversation_id != row.id:
        raise not_found()
    return turn


def _span_in_user_message(
    db: Session, row: Conversation, identity: ToolCallIdentity, span: str, *, allow_earlier: bool
) -> str:
    """Return the current message after checking where the remembered span was said.

    Whether the user meant "keep this" is the model's reading of their words,
    however phrased. What the server guarantees is narrower: the note is the
    user's own words from this chat, never text the model made up.
    """

    current = _current_turn(db, row, identity).user_text
    if span in current:
        return current
    if not allow_earlier:
        raise conflict(
            "agent_memory_span_missing",
            "The memory text must be an exact part of the user's message.",
        )
    earlier = db.scalars(
        select(ConversationTurn)
        .where(
            ConversationTurn.conversation_id == row.id,
            ConversationTurn.id != identity.turn_id,
        )
        .order_by(ConversationTurn.position.desc(), ConversationTurn.id.desc())
    ).all()
    if any(span in turn.user_text for turn in earlier):
        return current
    raise conflict(
        "agent_memory_span_missing",
        "The memory text must be an exact part of the user's message.",
    )


def _participants(db: Session, row: Conversation) -> list[ConversationParticipant]:
    return list(
        db.scalars(
            select(ConversationParticipant)
            .where(ConversationParticipant.conversation_id == row.id)
            .order_by(ConversationParticipant.position, ConversationParticipant.id)
        )
    )


def _upsert(
    db: Session,
    *,
    owner_user_id: str,
    agent_id: str,
    course_id: str,
    body: str,
    memory_id: str | None,
) -> AgentAccountMemory:
    now = datetime.now(UTC)
    if memory_id is not None:
        current = db.get(AgentAccountMemory, memory_id)
        if (
            current is None
            or current.deleted_at is not None
            or current.owner_user_id != owner_user_id
            or current.agent_id != agent_id
        ):
            raise not_found()
        current.body = body
        current.updated_at = now
        return current
    existing = db.scalar(
        select(AgentAccountMemory).where(
            AgentAccountMemory.owner_user_id == owner_user_id,
            AgentAccountMemory.agent_id == agent_id,
            AgentAccountMemory.body == body,
            AgentAccountMemory.deleted_at.is_(None),
        )
    )
    if existing is not None:
        existing.updated_at = now
        return existing
    created = AgentAccountMemory(
        id=str(uuid4()),
        owner_user_id=owner_user_id,
        agent_id=agent_id,
        course_id=course_id,
        body=body,
        created_at=now,
        updated_at=now,
    )
    db.add(created)
    db.flush()
    return created


def _read_rows(db: Session, owner_user_id: str, agent_id: str) -> list[dict[str, str]]:
    rows = db.scalars(
        select(AgentAccountMemory)
        .where(
            AgentAccountMemory.owner_user_id == owner_user_id,
            AgentAccountMemory.agent_id == agent_id,
            AgentAccountMemory.deleted_at.is_(None),
        )
        .order_by(AgentAccountMemory.updated_at.desc(), AgentAccountMemory.id)
        .limit(_MEMORY_LIMIT)
    ).all()
    return [{"memory_id": row.id, "text": row.body} for row in rows]


def read_agent_memory(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    _payload: BaseModel,
    _call_id: str,
    identity: ToolCallIdentity,
) -> dict[str, Any]:
    agent_id, _, _ = _speaking(db, row, identity)
    return {"memories": _read_rows(db, actor.user.id, agent_id)}


def write_agent_memory(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    payload: BaseModel,
    _call_id: str,
    identity: ToolCallIdentity,
) -> dict[str, Any]:
    arguments = WriteAgentMemoryArguments.model_validate(payload)
    span = arguments.text.strip()
    if not span:
        raise conflict(
            "agent_memory_span_missing",
            "The memory text must be an exact part of the user's message.",
        )
    agent_id, _display_name, is_leader = _speaking(db, row, identity)
    names = [name.strip() for name in arguments.member_names if name.strip()]
    if names and (row.entry_kind == "agent" or not is_leader):
        raise conflict(
            "agent_memory_target_invalid",
            "Only the Leader can store a named member's memory.",
        )
    if arguments.memory_id and names:
        raise conflict(
            "agent_memory_target_invalid",
            "Update one speaking Agent note, or name members, not both.",
        )
    if arguments.memory_id is not None:
        user_text = _current_turn(db, row, identity).user_text
        if span not in user_text:
            raise conflict(
                "agent_memory_span_missing",
                "The memory text must be an exact part of the user's message.",
            )
    else:
        # A reply that only names members keeps the fact in an earlier message
        # of this same chat.
        user_text = _span_in_user_message(db, row, identity, span, allow_earlier=bool(names))
    targets: list[str]
    if names:
        participants = _participants(db, row)
        targets = []
        for name in names:
            if name not in user_text:
                raise conflict(
                    "agent_memory_name_unknown",
                    "Name only a member the current message names.",
                )
            matches = [item for item in participants if item.display_name == name]
            if not matches:
                raise conflict(
                    "agent_memory_name_unknown",
                    "Name only a member the current message names.",
                )
            if len(matches) > 1:
                raise conflict("agent_memory_name_ambiguous", "That member name is not unique.")
            targets.append(matches[0].agent_id)
    else:
        targets = [agent_id]
    saved = [
        _upsert(
            db,
            owner_user_id=actor.user.id,
            agent_id=target,
            course_id=row.course_id,
            body=span,
            memory_id=arguments.memory_id,
        )
        for target in targets
    ]
    return {
        "memories": [
            {"memory_id": item.id, "agent_id": item.agent_id, "text": item.body} for item in saved
        ]
    }


def agent_memory_tools() -> dict[str, ToolSpec]:
    from .builtin import authorize_own_conversation

    return {
        "read_agent_memory": ToolSpec(
            "read_agent_memory",
            "Public",
            (
                "Read only this signed-in account's saved notes for the Agent that is speaking. "
                "At most 50 notes, newest first. Never another account, another Agent, "
                "an assessment record, or a Debate. If none exist, say so."
            ),
            ReadAgentMemoryArguments,
            authorize_own_conversation,
            read_agent_memory,
            replay_read=read_agent_memory,
        ),
        "write_agent_memory": ToolSpec(
            "write_agent_memory",
            "Public",
            (
                "Store what the user wants this Agent to keep for later chats, however they say "
                "it, as one exact span of the user's own words in this chat. "
                "Pass memory_id only to update that note when the current message restates it. "
                "In a Team, if it is unclear which member should keep it, do not call this yet: "
                "ask who. After the user names members, the Leader may pass those member_names; "
                "the span may be in that earlier message. "
                "A single-Agent chat and an @ member write only the speaking Agent. "
                "Never store an assessment answer, score, Rubric, or another account's note. "
                "Debates do not receive these notes."
            ),
            WriteAgentMemoryArguments,
            authorize_own_conversation,
            write_agent_memory,
        ),
    }
