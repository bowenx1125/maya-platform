import json
import logging
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import Error, PlatformError, conflict, not_found
from app.core.models import (
    Agent,
    AgentVersion,
    CourseMember,
    Group,
    ProviderOperation,
    ProviderReservation,
)
from app.modules.agents.schemas import AvatarConfig
from app.modules.auth.dependencies import (
    get_database,
    get_db,
    require_auth,
    require_authenticated_mutation,
)
from app.modules.auth.service import AuthContext
from app.providers.control_repository import ProviderSendingGuard

from .access import course_member
from .chat_provider import chat_messages, real_reply, retrieve_sources
from .chat_stream import accepts_event_stream, chat_audio_path, stream_events
from .models import Conversation, ConversationTurn
from .schemas import ChatAgent, ChatSession, ChatSource, ChatTurn, CreateChat, SendChat, StreamChat

router = APIRouter(
    tags=["Chat"],
    responses={
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
logger = logging.getLogger("maya.workspace")


def agent_view(version: AgentVersion, agent: Agent, course_id: str) -> ChatAgent:
    return ChatAgent(
        agent_id=UUID(agent.id),
        version_id=UUID(version.id),
        course_id=UUID(course_id),
        name=agent.name,
        version_label=f"V1.{version.version_seq}",
        avatar_config=AvatarConfig.model_validate_json(version.avatar_config_json),
        available=agent.deleted_at is None,
    )


def owned_conversation(db: Session, context: AuthContext, conversation_id: str) -> Conversation:
    row = db.get(Conversation, conversation_id)
    if row is None or row.user_id != context.user.id:
        raise not_found()
    course_member(db, context, row.course_id)
    return row


def claim_chat_send(
    db: Session,
    row: Conversation,
    *,
    request_id: str,
    expected_revision: int,
    message: str,
    settings: Settings,
) -> tuple[ConversationTurn, bool]:
    """Claim one send the same way the JSON and SSE routes do.

    An existing turn is returned without a second claim.  A new turn is
    committed as pending before any provider call.
    """

    previous = db.get(ConversationTurn, request_id)
    if previous:
        if previous.conversation_id != row.id or previous.user_text != message:
            raise conflict("chat_request_changed", "This request has already been used.")
        return previous, False
    claimed = db.execute(
        update(Conversation)
        .where(
            Conversation.id == row.id,
            Conversation.revision == expected_revision,
            Conversation.active_request_id.is_(None),
        )
        .values(active_request_id=request_id, revision=Conversation.revision + 1)
    )
    if not isinstance(claimed, CursorResult) or claimed.rowcount != 1:
        raise conflict("chat_busy", "Refresh the conversation before sending another message.")
    turn = ConversationTurn(
        id=request_id,
        conversation_id=row.id,
        position=expected_revision + 1,
        user_text=message,
        assistant_text=None,
        sources_json="[]",
        mode="real" if settings.llm_provider == "dashscope" else "mock",
        state="pending",
        created_at=datetime.now(UTC),
    )
    db.add(turn)
    db.commit()
    return turn, True


def _current_chat_claim(conversation_id: str, request_id: str, claim_revision: int) -> Any:
    return (
        select(Conversation.id)
        .where(
            Conversation.id == conversation_id,
            Conversation.active_request_id == request_id,
            Conversation.revision == claim_revision,
        )
        .exists()
    )


def _chat_sending_guard(
    conversation_id: str, request_id: str, claim_revision: int
) -> ProviderSendingGuard:
    conversations = Conversation.__table__
    turns = ConversationTurn.__table__

    def guard(connection: Any, operation: Any) -> bool:
        if operation["scope_id"] != conversation_id:
            return False
        operation_matches = (
            operation["provider_operation"] == "llm_agent_chat"
            and operation["logical_item_id"] == request_id
        ) or (
            operation["provider_operation"] == "embedding_query"
            and operation["logical_item_id"] == f"chat:{request_id}"
        )
        if not operation_matches:
            return False
        current = (
            select(conversations.c.id)
            .select_from(conversations.join(turns, turns.c.conversation_id == conversations.c.id))
            .where(
                conversations.c.id == conversation_id,
                conversations.c.active_request_id == request_id,
                conversations.c.revision == claim_revision,
                turns.c.id == request_id,
                turns.c.position == claim_revision,
                turns.c.state == "pending",
                turns.c.assistant_text.is_(None),
            )
            .limit(1)
        )
        return connection.execute(current).first() is not None

    return guard


def require_current_chat_claim(
    db: Session, conversation_id: str, request_id: str, claim_revision: int
) -> ConversationTurn:
    db.expire_all()
    turn = db.get(ConversationTurn, request_id)
    if (
        turn is None
        or turn.conversation_id != conversation_id
        or turn.position != claim_revision
        or turn.state != "pending"
        or turn.assistant_text is not None
        or db.scalar(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.active_request_id == request_id,
                Conversation.revision == claim_revision,
            )
        )
        is None
    ):
        raise PlatformError("chat_request_stale", "This request is no longer active.", 409)
    return turn


def _saved_chat_history(
    db: Session, conversation_id: str, before_position: int
) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for saved in db.scalars(
        select(ConversationTurn)
        .where(
            ConversationTurn.conversation_id == conversation_id,
            ConversationTurn.position < before_position,
        )
        .order_by(ConversationTurn.position, ConversationTurn.id)
    ):
        history.append({"role": "user", "content": saved.user_text})
        if saved.state == "ready" and saved.assistant_text is not None:
            history.append({"role": "assistant", "content": saved.assistant_text})
        else:
            state = (
                saved.state
                if saved.state in {"pending", "failed", "acceptance_unknown"}
                else "failed"
            )
            history.append(
                {
                    "role": "system",
                    "content": (
                        f"Status for the preceding user request: {state}. "
                        "No assistant reply was saved for that request."
                    ),
                }
            )
    return history


def generate_reply(
    db: Session,
    settings: Settings,
    row: Conversation,
    request_id: str,
    claim_revision: int,
    message: str,
) -> tuple[str, list[ChatSource], str | None]:
    """Produce one full reply in memory.  This does not store assistant text."""

    current_turn = require_current_chat_claim(db, row.id, request_id, claim_revision)
    if current_turn.user_text != message:
        raise conflict("chat_request_changed", "This request has already been used.")
    version = db.get(AgentVersion, row.agent_version_id)
    agent = db.get(Agent, version.agent_id) if version else None
    if (
        version is None
        or agent is None
        or agent.deleted_at is not None
        or version.knowledge_snapshot_id != row.snapshot_id
    ):
        raise not_found()
    if settings.llm_provider == "mock":
        return f"Mock · {agent.name}\n\n{message}", [], None
    sending_guard = _chat_sending_guard(row.id, request_id, claim_revision)
    sources = retrieve_sources(
        db,
        settings,
        version,
        course_id=row.course_id,
        scope_id=row.id,
        request_id=request_id,
        message=message,
        sending_guard=sending_guard,
    )
    history = _saved_chat_history(db, row.id, current_turn.position)
    history.append({"role": "user", "content": message})
    require_current_chat_claim(db, row.id, request_id, claim_revision)
    messages, persona_hash = chat_messages(version, history, sources)
    reply, operation_id = real_reply(
        db,
        settings,
        scope_id=row.id,
        request_id=request_id,
        course_id=row.course_id,
        messages=messages,
        persona_hash=persona_hash,
        version_id=version.id,
        group_id=agent.group_id,
        sending_guard=sending_guard,
    )
    return reply, sources, operation_id


def store_assistant_text(
    db: Session,
    conversation_id: str,
    request_id: str,
    claim_revision: int,
    reply: str,
    sources: list[ChatSource],
    operation_id: str | None,
) -> tuple[int, list[dict[str, Any]]]:
    """Commit the full assistant text once.  Callers must not store prefixes."""

    stored_sources = [item.model_dump(mode="json") for item in sources]
    write = db.execute(
        update(ConversationTurn)
        .where(
            ConversationTurn.id == request_id,
            ConversationTurn.conversation_id == conversation_id,
            ConversationTurn.position == claim_revision,
            ConversationTurn.state == "pending",
            ConversationTurn.assistant_text.is_(None),
            _current_chat_claim(conversation_id, request_id, claim_revision),
        )
        .values(
            assistant_text=reply,
            sources_json=json.dumps(stored_sources, ensure_ascii=False),
            state="ready",
            safe_error_code=None,
        )
    )
    if not isinstance(write, CursorResult) or write.rowcount != 1:
        raise PlatformError("chat_request_stale", "This request is no longer active.", 409)
    if operation_id:
        db.execute(
            update(ProviderOperation)
            .where(ProviderOperation.id == operation_id, ProviderOperation.state == "accepted")
            .values(state="succeeded")
        )
        db.execute(
            update(ProviderReservation)
            .where(ProviderReservation.operation_id == operation_id)
            .values(state="succeeded")
        )
    db.commit()
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise not_found()
    return conversation.revision, stored_sources


def record_chat_failure(
    db: Session,
    conversation_id: str,
    request_id: str,
    claim_revision: int,
    exc: Exception,
) -> str:
    """Mark one claimed turn failed.  The caller commits the release."""

    db.rollback()
    turn = db.get(ConversationTurn, request_id)
    code = getattr(exc, "code", "chat_failed")
    if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
        code = "chat_failed"
    if (
        turn is None
        or turn.conversation_id != conversation_id
        or turn.position != claim_revision
        or turn.state != "pending"
    ):
        return turn.safe_error_code if turn and turn.safe_error_code else code
    uncertain = code == "chat_acceptance_unknown" or bool(
        db.scalar(
            select(ProviderOperation.id)
            .where(
                ProviderOperation.scope_id == conversation_id,
                or_(
                    and_(
                        ProviderOperation.provider_operation == "llm_agent_chat",
                        ProviderOperation.logical_item_id == request_id,
                    ),
                    and_(
                        ProviderOperation.provider_operation == "embedding_query",
                        ProviderOperation.logical_item_id == f"chat:{request_id}",
                    ),
                ),
                ProviderOperation.state.in_(("sending", "acceptance_unknown")),
            )
            .limit(1)
        )
    )
    write = db.execute(
        update(ConversationTurn)
        .where(
            ConversationTurn.id == request_id,
            ConversationTurn.conversation_id == conversation_id,
            ConversationTurn.position == claim_revision,
            ConversationTurn.state == "pending",
            _current_chat_claim(conversation_id, request_id, claim_revision),
        )
        .values(state="acceptance_unknown" if uncertain else "failed", safe_error_code=code)
    )
    if not isinstance(write, CursorResult) or write.rowcount != 1:
        db.expire_all()
        current_turn = db.get(ConversationTurn, request_id)
        return (
            current_turn.safe_error_code if current_turn and current_turn.safe_error_code else code
        )
    logger.warning(
        "Chat failed conversation_id=%s turn_id=%s code=%s", conversation_id, request_id, code
    )
    return code


def release_chat_request(
    db: Session, conversation_id: str, request_id: str, claim_revision: int
) -> None:
    db.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.active_request_id == request_id,
            Conversation.revision == claim_revision,
        )
        .values(active_request_id=None)
    )


def session_view(db: Session, conversation: Conversation) -> ChatSession:
    version = db.get(AgentVersion, conversation.agent_version_id)
    agent = db.get(Agent, version.agent_id) if version else None
    if version is None or agent is None:
        raise not_found()
    turns = db.scalars(
        select(ConversationTurn)
        .where(
            ConversationTurn.conversation_id == conversation.id,
        )
        .order_by(ConversationTurn.position, ConversationTurn.id)
    ).all()
    return ChatSession(
        id=UUID(conversation.id),
        agent=agent_view(version, agent, conversation.course_id),
        revision=conversation.revision,
        created_at=conversation.created_at,
        turns=[
            ChatTurn.model_validate(
                {
                    "id": turn.id,
                    "user_text": turn.user_text,
                    "assistant_text": turn.assistant_text,
                    "mode": turn.mode,
                    "state": turn.state,
                    "sources": json.loads(turn.sources_json),
                    "safe_error_code": turn.safe_error_code,
                }
            )
            for turn in turns
        ],
    )


@router.get(
    "/courses/{course_id}/chat-agents",
    response_model=list[ChatAgent],
    operation_id="listChatAgents",
)
def list_agents(
    course_id: UUID, context: AuthContext = Depends(require_auth), db: Session = Depends(get_db)
) -> list[ChatAgent]:
    course_member(db, context, str(course_id))
    rows = db.execute(
        select(AgentVersion, Agent)
        .join(
            Agent,
            Agent.current_published_version_id == AgentVersion.id,
        )
        .join(Group, Group.id == Agent.group_id)
        .where(
            Group.course_id == str(course_id),
            Agent.status == "active",
            Agent.deleted_at.is_(None),
            AgentVersion.state == "published",
            AgentVersion.knowledge_snapshot_id.is_not(None),
        )
        .order_by(Agent.created_at.desc())
    ).all()
    return [agent_view(version, agent, str(course_id)) for version, agent in rows]


@router.get("/conversations", response_model=list[ChatSession], operation_id="listConversations")
def list_conversations(
    context: AuthContext = Depends(require_auth), db: Session = Depends(get_db)
) -> list[ChatSession]:
    rows = db.scalars(
        select(Conversation)
        .join(
            CourseMember,
            (
                (CourseMember.course_id == Conversation.course_id)
                & (CourseMember.user_id == Conversation.user_id)
            ),
        )
        .where(Conversation.user_id == context.user.id)
        .order_by(
            select(func.max(ConversationTurn.created_at))
            .where(ConversationTurn.conversation_id == Conversation.id)
            .scalar_subquery()
            .desc(),
            Conversation.created_at.desc(),
            Conversation.id,
        )
    ).all()
    return [session_view(db, row) for row in rows]


@router.post("/conversations", response_model=ChatSession, operation_id="createConversation")
def create_conversation(
    payload: CreateChat,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> ChatSession:
    version = db.get(AgentVersion, str(payload.version_id))
    agent = db.get(Agent, version.agent_id) if version else None
    group = db.get(Group, agent.group_id) if agent else None
    if (
        version is None
        or agent is None
        or group is None
        or agent.status != "active"
        or agent.deleted_at is not None
        or version.state != "published"
        or agent.current_published_version_id != version.id
        or not version.knowledge_snapshot_id
    ):
        raise not_found()
    course_member(db, context, group.course_id)
    row = Conversation(
        id=str(uuid4()),
        user_id=context.user.id,
        course_id=group.course_id,
        agent_version_id=version.id,
        snapshot_id=version.knowledge_snapshot_id,
        revision=0,
        active_request_id=None,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return session_view(db, row)


@router.get(
    "/conversations/{conversation_id}", response_model=ChatSession, operation_id="getConversation"
)
def get_conversation(
    conversation_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> ChatSession:
    return session_view(db, owned_conversation(db, context, str(conversation_id)))


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    operation_id="deleteConversation",
    response_class=Response,
)
def delete_conversation(
    conversation_id: UUID,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> Response:
    row = owned_conversation(db, context, str(conversation_id))
    db.execute(delete(ConversationTurn).where(ConversationTurn.conversation_id == row.id))
    db.execute(delete(Conversation).where(Conversation.id == row.id))
    db.commit()
    return Response(status_code=204)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ChatSession,
    operation_id="sendConversationMessage",
    responses={503: {"model": Error}},
)
def send_message(
    conversation_id: UUID,
    payload: SendChat,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ChatSession:
    row = owned_conversation(db, context, str(conversation_id))
    version = db.get(AgentVersion, row.agent_version_id)
    agent = db.get(Agent, version.agent_id) if version else None
    if agent is None or agent.deleted_at is not None:
        raise conflict("agent_deleted", "This Agent was deleted. The conversation is read-only.")
    request_id = str(payload.request_id)
    message = payload.message.strip()
    if not message:
        raise PlatformError("chat_message_empty", "Enter a message.", 400)
    turn, created = claim_chat_send(
        db,
        row,
        request_id=request_id,
        expected_revision=payload.expected_revision,
        message=message,
        settings=settings,
    )
    claim_revision = turn.position
    if not created:
        return session_view(db, row)
    try:
        reply, sources, operation_id = generate_reply(
            db, settings, row, request_id, claim_revision, message
        )
        store_assistant_text(db, row.id, request_id, claim_revision, reply, sources, operation_id)
    except Exception as exc:
        record_chat_failure(db, row.id, request_id, claim_revision, exc)
    release_chat_request(db, row.id, request_id, claim_revision)
    db.commit()
    db.expire_all()
    return session_view(db, owned_conversation(db, context, str(conversation_id)))


@router.post(
    "/conversations/{conversation_id}/messages:stream",
    operation_id="streamConversationMessage",
    response_model=None,
    responses={
        200: {
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
            "description": "Successful Response",
        },
        400: {"model": Error},
        503: {"model": Error},
    },
)
def stream_message(
    conversation_id: UUID,
    payload: StreamChat,
    accept: str = Header(..., alias="Accept"),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    row = owned_conversation(db, context, str(conversation_id))
    version = db.get(AgentVersion, row.agent_version_id)
    agent = db.get(Agent, version.agent_id) if version else None
    if agent is None or agent.deleted_at is not None:
        raise conflict("agent_deleted", "This Agent was deleted. The conversation is read-only.")
    if not accepts_event_stream(accept):
        raise PlatformError("malformed_request", "Accept text/event-stream is required.", 400)
    request_id = str(payload.request_id)
    message = payload.message.strip()
    if not message:
        raise PlatformError("chat_message_empty", "Enter a message.", 400)
    turn, created = claim_chat_send(
        db,
        row,
        request_id=request_id,
        expected_revision=payload.expected_revision,
        message=message,
        settings=settings,
    )
    claim_revision = turn.position
    owned_id = row.id
    # Claim is committed.  Drop the request connection before the stream so
    # it is not held across the LLM call or TTS.
    db.close()
    return StreamingResponse(
        stream_events(
            database,
            settings,
            conversation_id=owned_id,
            created=created,
            message=message,
            request_id=request_id,
            claim_revision=claim_revision,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/conversations/{conversation_id}/audio/{request_id}",
    include_in_schema=False,
    name="conversationAudio",
)
def conversation_audio(
    conversation_id: UUID,
    request_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    row = owned_conversation(db, context, str(conversation_id))
    turn = db.get(ConversationTurn, str(request_id))
    if turn is None or turn.conversation_id != row.id:
        raise not_found()
    return FileResponse(
        chat_audio_path(settings, conversation_id, request_id),
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )
