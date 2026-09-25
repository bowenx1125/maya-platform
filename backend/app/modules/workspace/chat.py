import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import delete, func, select, update
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
from app.providers.control_repository import ProviderRepository

from .access import course_member
from .chat_provider import chat_messages, real_reply, retrieve_sources
from .chat_stream import (
    accepts_event_stream,
    chat_audio_path,
    language_supported,
    remove_chat_audio,
    stream_events,
    turn_audio,
)
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

# A live send holds the conversation lock. Past this age the request is gone
# or stuck, and keeping the turn pending would stop every later message.
CHAT_PENDING_TTL = timedelta(minutes=3)
_CHAT_OPERATION = "llm_agent_chat"
_OPEN_OPERATION_STATES = ("prepared", "reserved", "sending", "accepted")
_TERMINAL_OPERATION_STATES = frozenset(
    {"succeeded", "failed", "not_sent", "acceptance_unknown", "abandoned"}
)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _turn_is_live(turn: ConversationTurn, active_request_id: str | None, now: datetime) -> bool:
    return (
        turn.state == "pending"
        and active_request_id == turn.id
        and now - _aware(turn.created_at) <= CHAT_PENDING_TTL
    )


def _fail_open_turn(turn: ConversationTurn, code: str) -> None:
    """Move an unfinished turn to failed. A ready turn is left ready."""

    if turn.state == "pending":
        turn.state = "failed"
        turn.safe_error_code = code
        return
    # Startup used to label an interrupted real turn acceptance_unknown, which
    # claim_chat_send treats as a permanent block. That label is not a
    # provider outcome, so it becomes an ordinary failure.
    if turn.state == "acceptance_unknown" and turn.safe_error_code == "chat_interrupted":
        turn.state = "failed"
        turn.safe_error_code = "chat_interrupted"


def settle_chat_operation(
    database: Database, operation_id: str, *, turn_ready: bool, code: str
) -> None:
    """Close one chat operation without leaving it accepted.

    A supplier that never accepted the call is not_sent, which releases the
    reservation. An accepted call whose text was not stored stays charged and
    becomes failed. A call still marked sending keeps the charge as
    acceptance_unknown. A ready turn promotes accepted to succeeded.
    """

    repository = ProviderRepository(database)
    try:
        state = repository.operation(operation_id).state
    except Exception:
        logger.warning(
            "Chat operation missing operation_id=%s code=%s",
            operation_id,
            code,
        )
        return
    if state in _TERMINAL_OPERATION_STATES:
        return
    try:
        if turn_ready and state == "accepted":
            repository.mark_succeeded(operation_id)
        elif state in {"prepared", "reserved"}:
            repository.mark_not_sent(operation_id, safe_error_code=code)
        elif state == "sending":
            repository.mark_acceptance_unknown(operation_id, safe_error_code="acceptance_unknown")
        elif state == "accepted":
            repository.mark_failed(operation_id, safe_error_code=code)
        else:
            logger.warning(
                "Chat operation left open operation_id=%s state=%s code=%s",
                operation_id,
                state,
                code,
            )
    except Exception:
        logger.warning(
            "Chat operation settle failed operation_id=%s code=%s",
            operation_id,
            code,
        )


def _load_open_chat_operations(
    db: Session, *, conversation_id: str, request_id: str
) -> list[tuple[str, bool]]:
    turn = db.get(ConversationTurn, request_id)
    turn_ready = (
        turn is not None and turn.state == "ready" and turn.conversation_id == conversation_id
    )
    return [
        (operation_id, turn_ready)
        for operation_id in db.scalars(
            select(ProviderOperation.id).where(
                ProviderOperation.scope_id == conversation_id,
                ProviderOperation.provider_operation == _CHAT_OPERATION,
                ProviderOperation.logical_item_id == request_id,
                ProviderOperation.state.in_(_OPEN_OPERATION_STATES),
            )
        )
    ]


def mark_abandoned_turn(
    database: Database,
    *,
    conversation_id: str,
    request_id: str,
    code: str,
) -> None:
    """Fail one still-pending turn and drop its lock. Operations settle separately."""

    with database.session() as db:
        turn = db.get(ConversationTurn, request_id)
        changed = False
        if turn is not None and turn.conversation_id == conversation_id and turn.state != "ready":
            before = (turn.state, turn.safe_error_code)
            _fail_open_turn(turn, code)
            changed = (turn.state, turn.safe_error_code) != before
        release_chat_request(db, conversation_id, request_id)
    if changed:
        logger.warning(
            "Chat request closed conversation_id=%s turn_id=%s code=%s",
            conversation_id,
            request_id,
            code,
        )


def settle_abandoned_operations(
    database: Database,
    *,
    conversation_id: str,
    request_id: str,
    code: str,
) -> None:
    """Close this request's chat operation after its worker has finished."""

    with database.session() as db:
        pending_ops = _load_open_chat_operations(
            db, conversation_id=conversation_id, request_id=request_id
        )
    for operation_id, turn_ready in pending_ops:
        settle_chat_operation(database, operation_id, turn_ready=turn_ready, code=code)


def close_abandoned_chat(
    database: Database,
    *,
    conversation_id: str,
    request_id: str,
    code: str,
) -> None:
    """Fail one abandoned turn, drop its lock, and close its chat operation."""

    mark_abandoned_turn(database, conversation_id=conversation_id, request_id=request_id, code=code)
    settle_abandoned_operations(
        database, conversation_id=conversation_id, request_id=request_id, code=code
    )


def repair_abandoned_chats(
    database: Database, *, conversation_id: str | None = None, only_stale: bool = True
) -> None:
    """Fail turns no live request can still finish, then close their operations.

    Claim-time repair (`only_stale`) leaves a young locked pending turn alone.
    Startup repair does not: the new process has no in-flight stream.
    """

    now = datetime.now(UTC)
    pending_ops: list[tuple[str, str, str]] = []
    with database.session() as db:
        turn_query = select(ConversationTurn).where(
            ConversationTurn.state.in_(("pending", "acceptance_unknown"))
        )
        if conversation_id is not None:
            turn_query = turn_query.where(ConversationTurn.conversation_id == conversation_id)
        turns = list(db.scalars(turn_query))
        conversations = {
            row.id: row
            for row in db.scalars(
                select(Conversation).where(
                    Conversation.id.in_({turn.conversation_id for turn in turns} or {""})
                )
            )
        }
        if conversation_id is not None and conversation_id not in conversations:
            row = db.get(Conversation, conversation_id)
            if row is not None:
                conversations[row.id] = row
        request_ids: list[tuple[str, str]] = []
        for turn in turns:
            row = conversations.get(turn.conversation_id)
            active = row.active_request_id if row is not None else None
            if turn.state == "acceptance_unknown":
                if turn.safe_error_code != "chat_interrupted":
                    continue
            elif only_stale and _turn_is_live(turn, active, now):
                continue
            elif turn.state != "pending":
                continue
            _fail_open_turn(turn, "chat_interrupted")
            request_ids.append((turn.conversation_id, turn.id))
        for row in conversations.values():
            if row.active_request_id is None:
                continue
            if only_stale and any(
                turn.id == row.active_request_id and _turn_is_live(turn, row.active_request_id, now)
                for turn in turns
                if turn.conversation_id == row.id
            ):
                continue
            row.active_request_id = None
        if not only_stale:
            for row in db.scalars(
                select(Conversation).where(Conversation.active_request_id.is_not(None))
            ):
                row.active_request_id = None
        for scope_id, request_id in request_ids:
            for operation_id, _turn_ready in _load_open_chat_operations(
                db, conversation_id=scope_id, request_id=request_id
            ):
                pending_ops.append((operation_id, scope_id, request_id))
        # Operations left open with no pending turn (the turn was already
        # failed, or the text was stored) still must leave accepted/sending.
        op_query = select(ProviderOperation).where(
            ProviderOperation.provider_operation == _CHAT_OPERATION,
            ProviderOperation.state.in_(_OPEN_OPERATION_STATES),
        )
        if conversation_id is not None:
            op_query = op_query.where(ProviderOperation.scope_id == conversation_id)
        known = {operation_id for operation_id, _scope, _request in pending_ops}
        live_ids = {
            turn.id
            for turn in turns
            if turn.state == "pending"
            and _turn_is_live(
                turn,
                conversations[turn.conversation_id].active_request_id
                if turn.conversation_id in conversations
                else None,
                now,
            )
        }
        for operation in db.scalars(op_query):
            if operation.id in known or operation.logical_item_id in live_ids:
                continue
            pending_ops.append((operation.id, operation.scope_id, operation.logical_item_id))
    for operation_id, scope_id, request_id in pending_ops:
        with database.session() as db:
            saved = db.get(ConversationTurn, request_id)
            turn_ready = (
                saved is not None and saved.state == "ready" and saved.conversation_id == scope_id
            )
        settle_chat_operation(
            database, operation_id, turn_ready=turn_ready, code="chat_interrupted"
        )


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
    database: Database,
    request_id: str,
    expected_revision: int,
    message: str,
    settings: Settings,
) -> tuple[ConversationTurn, bool]:
    """Claim one send the same way the JSON and SSE routes do.

    An existing turn is returned without a second claim.  A new turn is
    committed as pending before any provider call.  A pending turn whose
    request is already gone is failed here so it cannot block this send.
    """

    conversation_id = row.id
    db.commit()
    repair_abandoned_chats(database, conversation_id=conversation_id, only_stale=True)
    db.expire_all()
    fresh = db.get(Conversation, conversation_id)
    if fresh is None:
        raise not_found()
    row = fresh
    previous = db.get(ConversationTurn, request_id)
    if previous:
        if previous.conversation_id != row.id or previous.user_text != message:
            raise conflict("chat_request_changed", "This request has already been used.")
        return previous, False
    if db.scalar(
        select(ConversationTurn.id)
        .where(
            ConversationTurn.conversation_id == row.id,
            ConversationTurn.state == "acceptance_unknown",
        )
        .limit(1)
    ):
        raise conflict("chat_acceptance_unknown", "This conversation cannot send more requests.")
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
        position=row.revision,
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


def generate_reply(
    db: Session,
    settings: Settings,
    row: Conversation,
    request_id: str,
    message: str,
    *,
    lang: str | None = None,
) -> tuple[str, list[ChatSource], str | None]:
    """Produce one full reply in memory.  This does not store assistant text."""

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
    sources = retrieve_sources(
        db,
        settings,
        version,
        course_id=row.course_id,
        scope_id=row.id,
        request_id=request_id,
        message=message,
    )
    history: list[dict[str, str]] = []
    for saved in db.scalars(
        select(ConversationTurn)
        .where(
            ConversationTurn.conversation_id == row.id,
            ConversationTurn.state == "ready",
        )
        .order_by(ConversationTurn.position)
    ):
        history.extend(
            [
                {"role": "user", "content": saved.user_text},
                {"role": "assistant", "content": saved.assistant_text or ""},
            ]
        )
    history.append({"role": "user", "content": message})
    messages, persona_hash = chat_messages(version, history, sources)
    if lang == "zh-CN":
        messages[0]["content"] += (
            "\nThe requested conversation language is zh-CN. Write the reply in Chinese."
        )
    elif lang == "en":
        messages[0]["content"] += (
            "\nThe requested conversation language is en. Write the reply in English."
        )
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
    )
    return reply, sources, operation_id


def store_assistant_text(
    db: Session,
    request_id: str,
    reply: str,
    sources: list[ChatSource],
    operation_id: str | None,
) -> tuple[int, list[dict[str, Any]]]:
    """Commit the full assistant text once.  Callers must not store prefixes."""

    db.expire_all()
    turn = db.get(ConversationTurn, request_id)
    if turn is None:
        raise not_found()
    if turn.assistant_text is not None:
        raise RuntimeError("assistant text is already stored")
    stored_sources = [item.model_dump(mode="json") for item in sources]
    turn.assistant_text = reply
    turn.sources_json = json.dumps(stored_sources, ensure_ascii=False)
    turn.state = "ready"
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
    conversation = db.get(Conversation, turn.conversation_id)
    if conversation is None:
        raise not_found()
    return conversation.revision, stored_sources


def record_chat_failure(db: Session, conversation_id: str, request_id: str, exc: Exception) -> str:
    """Mark one claimed turn failed.  The caller commits the release."""

    db.rollback()
    turn = db.get(ConversationTurn, request_id)
    if turn is None:
        raise not_found() from None
    code = getattr(exc, "code", "chat_failed")
    if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
        code = "chat_failed"
    uncertain = "acceptance_unknown" in code or bool(
        db.scalar(
            select(ProviderOperation.id)
            .where(
                ProviderOperation.scope_id == conversation_id,
                ProviderOperation.logical_item_id.in_((request_id, f"chat:{request_id}")),
                ProviderOperation.state.in_(("sending", "accepted", "acceptance_unknown")),
            )
            .limit(1)
        )
    )
    turn.state = "acceptance_unknown" if uncertain else "failed"
    turn.safe_error_code = code
    logger.warning(
        "Chat failed conversation_id=%s turn_id=%s code=%s", conversation_id, request_id, code
    )
    return code


def release_chat_request(db: Session, conversation_id: str, request_id: str) -> None:
    db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id, Conversation.active_request_id == request_id)
        .values(active_request_id=None)
    )


def session_view(db: Session, conversation: Conversation) -> ChatSession:
    version = db.get(AgentVersion, conversation.agent_version_id)
    agent = db.get(Agent, version.agent_id) if version else None
    if version is None or agent is None:
        raise not_found()
    raw_settings = db.info.get("maya_settings")
    settings = raw_settings if isinstance(raw_settings, Settings) else None

    def audio_fields(turn_id: str) -> dict[str, str | int | None]:
        if settings is None:
            return {"audio_url": None, "audio_duration_ms": None}
        audio_url, audio_duration_ms = turn_audio(settings, conversation.id, turn_id)
        return {"audio_url": audio_url, "audio_duration_ms": audio_duration_ms}

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
                    **audio_fields(turn.id),
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
    settings: Settings = Depends(get_settings),
) -> Response:
    row = owned_conversation(db, context, str(conversation_id))
    db.execute(delete(ConversationTurn).where(ConversationTurn.conversation_id == row.id))
    db.execute(delete(Conversation).where(Conversation.id == row.id))
    db.commit()
    remove_chat_audio(settings, row.id)
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
    database: Database = Depends(get_database),
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
    _turn, created = claim_chat_send(
        db,
        row,
        database=database,
        request_id=request_id,
        expected_revision=payload.expected_revision,
        message=message,
        settings=settings,
    )
    if not created:
        return session_view(db, row)
    try:
        reply, sources, operation_id = generate_reply(db, settings, row, request_id, message)
        store_assistant_text(db, request_id, reply, sources, operation_id)
    except Exception as exc:
        record_chat_failure(db, row.id, request_id, exc)
    release_chat_request(db, row.id, request_id)
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
    if not language_supported(payload.lang):
        raise PlatformError(
            "chat_language_unsupported",
            "This chat supports Chinese (zh-CN) and English only.",
            400,
        )
    request_id = str(payload.request_id)
    message = payload.message.strip()
    if not message:
        raise PlatformError("chat_message_empty", "Enter a message.", 400)
    _turn, created = claim_chat_send(
        db,
        row,
        database=database,
        request_id=request_id,
        expected_revision=payload.expected_revision,
        message=message,
        settings=settings,
    )
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
            lang=payload.lang,
            request_id=request_id,
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
