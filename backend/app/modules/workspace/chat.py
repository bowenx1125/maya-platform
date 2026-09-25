import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import ColumnElement, delete, exists, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, aliased

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


def _live_turn_exists(turn_id_expr: Any, cutoff: datetime) -> ColumnElement[bool]:
    """SQL predicate: that turn id is a pending, locked, in-TTL request.

    The database evaluates liveness inside the same UPDATE that fails a
    turn or clears a lock, so a claim committed after repair's SELECTs
    still counts as live even though repair never loaded its row.  The
    cutoff is a datetime so it binds in the same form claim_chat_send
    writes created_at, which keeps the SQLite string comparison exact.
    """

    turn = aliased(ConversationTurn)
    conversation = aliased(Conversation)
    return exists().where(
        turn.id == turn_id_expr,
        turn.state == "pending",
        turn.created_at > cutoff,
        exists().where(
            conversation.id == turn.conversation_id,
            conversation.active_request_id == turn.id,
        ),
    )


def _fail_open_turn(
    db: Session, turn_id: str, code: str, *, live_cutoff: datetime | None = None
) -> bool:
    """Fail one unfinished turn. A ready turn is left ready.

    The conditional update re-reads the state, so a turn that became ready
    after the caller loaded it is never rewritten.  Repair also passes a
    live cutoff so a pending turn the database still considers live is
    never failed, even if this session never loaded its row.
    """

    pending_conditions = [ConversationTurn.id == turn_id, ConversationTurn.state == "pending"]
    if live_cutoff is not None:
        pending_conditions.append(~_live_turn_exists(ConversationTurn.id, live_cutoff))
    failed = db.execute(
        update(ConversationTurn)
        .where(*pending_conditions)
        .values(state="failed", safe_error_code=code)
    )
    if isinstance(failed, CursorResult) and failed.rowcount == 1:
        return True
    # Startup used to label an interrupted real turn acceptance_unknown, which
    # claim_chat_send treats as a permanent block. That label is not a
    # provider outcome, so it becomes an ordinary failure.
    interrupted = db.execute(
        update(ConversationTurn)
        .where(
            ConversationTurn.id == turn_id,
            ConversationTurn.state == "acceptance_unknown",
            ConversationTurn.safe_error_code == "chat_interrupted",
        )
        .values(state="failed", safe_error_code="chat_interrupted")
    )
    return isinstance(interrupted, CursorResult) and interrupted.rowcount == 1


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
        changed = (
            turn is not None
            and turn.conversation_id == conversation_id
            and _fail_open_turn(db, request_id, code)
        )
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


def _load_repair_turns(db: Session, conversation_id: str | None) -> list[ConversationTurn]:
    turn_query = select(ConversationTurn).where(
        ConversationTurn.state.in_(("pending", "acceptance_unknown"))
    )
    if conversation_id is not None:
        turn_query = turn_query.where(ConversationTurn.conversation_id == conversation_id)
    return list(db.scalars(turn_query))


def _load_repair_locks(
    db: Session,
    conversation_id: str | None,
    only_stale: bool,
    turns: list[ConversationTurn],
) -> dict[str, str]:
    """Snapshot the locks observed right now.

    Startup repair also snapshots every other locked conversation, because it
    is allowed to clear locks its turns never mentioned.
    """

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
    observed_locks = {
        row.id: row.active_request_id for row in conversations.values() if row.active_request_id
    }
    if not only_stale:
        lock_query = select(Conversation.id, Conversation.active_request_id).where(
            Conversation.active_request_id.is_not(None)
        )
        if conversation_id is not None:
            lock_query = lock_query.where(Conversation.id == conversation_id)
        for lock_row in db.execute(lock_query):
            observed_locks[lock_row.id] = lock_row.active_request_id
    return observed_locks


def _load_repair_rows(
    db: Session, conversation_id: str | None, only_stale: bool
) -> tuple[list[ConversationTurn], dict[str, str]]:
    """Load unfinished turns, then snapshot the locks observed right now."""

    turns = _load_repair_turns(db, conversation_id)
    return turns, _load_repair_locks(db, conversation_id, only_stale, turns)


def _live_turn_ids(
    turns: list[ConversationTurn], observed_locks: dict[str, str], now: datetime
) -> set[str]:
    return {
        turn.id
        for turn in turns
        if turn.state == "pending"
        and _turn_is_live(turn, observed_locks.get(turn.conversation_id), now)
    }


def _fail_dead_turns(
    db: Session,
    turns: list[ConversationTurn],
    live_ids: set[str],
    *,
    only_stale: bool,
    cutoff: datetime,
) -> list[tuple[str, str]]:
    """Fail every loaded turn no live request can still finish."""
    request_ids: list[tuple[str, str]] = []
    for turn in turns:
        if turn.state == "acceptance_unknown":
            if turn.safe_error_code != "chat_interrupted":
                continue
        elif only_stale and turn.id in live_ids:
            continue
        elif turn.state != "pending":
            continue
        # The SQL guard inside the UPDATE is what makes the decision safe:
        # a claim committed after this session's SELECTs still counts as
        # live even though its row is missing from `turns`.
        if _fail_open_turn(
            db, turn.id, "chat_interrupted", live_cutoff=cutoff if only_stale else None
        ):
            request_ids.append((turn.conversation_id, turn.id))
    return request_ids


def _clear_lock(
    db: Session, conversation_id: str, observed: str, *, cutoff: datetime | None = None
) -> bool:
    """Clear one lock only if it still holds the value repair observed.

    Claim-time repair also re-checks liveness in the same UPDATE, so a
    lock claimed after repair's SELECTs is never cleared: the CAS alone
    matches the new value but the NOT-live guard rejects it.
    """

    conditions = [Conversation.id == conversation_id, Conversation.active_request_id == observed]
    if cutoff is not None:
        conditions.append(~_live_turn_exists(Conversation.active_request_id, cutoff))
    result = db.execute(update(Conversation).where(*conditions).values(active_request_id=None))
    return isinstance(result, CursorResult) and result.rowcount == 1


def _release_dead_locks(
    db: Session,
    observed_locks: dict[str, str],
    live_ids: set[str],
    *,
    only_stale: bool,
    cutoff: datetime,
) -> None:
    for conversation_id, observed in observed_locks.items():
        if only_stale and observed in live_ids:
            continue
        # Startup repair passes no cutoff: nothing is live after a restart.
        _clear_lock(db, conversation_id, observed, cutoff=cutoff if only_stale else None)


def _open_operations_to_settle(
    db: Session,
    *,
    conversation_id: str | None,
    request_ids: list[tuple[str, str]],
    live_ids: set[str],
    cutoff: datetime | None = None,
) -> list[tuple[str, str, str]]:
    """Collect open chat operations that repair must settle."""
    pending_ops = [
        (operation_id, scope_id, request_id)
        for scope_id, request_id in request_ids
        for operation_id, _turn_ready in _load_open_chat_operations(
            db, conversation_id=scope_id, request_id=request_id
        )
    ]
    # Operations left open with no pending turn (the turn was already
    # failed, or the text was stored) still must leave accepted/sending.
    # A live request's operation is excluded in SQL, so a claim committed
    # after this session's SELECTs is not settled even though its row was
    # never loaded.
    op_conditions = [
        ProviderOperation.provider_operation == _CHAT_OPERATION,
        ProviderOperation.state.in_(_OPEN_OPERATION_STATES),
    ]
    if conversation_id is not None:
        op_conditions.append(ProviderOperation.scope_id == conversation_id)
    if cutoff is not None:
        op_conditions.append(~_live_turn_exists(ProviderOperation.logical_item_id, cutoff))
    op_query = select(ProviderOperation).where(*op_conditions)
    known = {operation_id for operation_id, _scope, _request in pending_ops}
    for operation in db.scalars(op_query):
        if operation.id in known or operation.logical_item_id in live_ids:
            continue
        pending_ops.append((operation.id, operation.scope_id, operation.logical_item_id))
    return pending_ops


def repair_abandoned_chats(
    database: Database, *, conversation_id: str | None = None, only_stale: bool = True
) -> None:
    """Fail turns no live request can still finish, then close their operations.

    Claim-time repair (`only_stale`) leaves a young locked pending turn
    alone.  Startup repair does not: the new process has no in-flight
    stream.

    Liveness is checked inside each conditional UPDATE (`_live_turn_exists`
    with a cutoff), not only in the pre-filter, so a claim committed after
    this function's SELECTs keeps its lock, its pending turn and its open
    operation.  Locks are still cleared from the snapshot taken before any
    turn was failed.
    """

    now = datetime.now(UTC)
    cutoff = now - CHAT_PENDING_TTL
    with database.session() as db:
        turns, observed_locks = _load_repair_rows(db, conversation_id, only_stale)
        # Startup repair has no in-flight stream, so nothing counts as live.
        live_ids = _live_turn_ids(turns, observed_locks, now) if only_stale else set()
        request_ids = _fail_dead_turns(db, turns, live_ids, only_stale=only_stale, cutoff=cutoff)
        _release_dead_locks(db, observed_locks, live_ids, only_stale=only_stale, cutoff=cutoff)
        pending_ops = _open_operations_to_settle(
            db,
            conversation_id=conversation_id,
            request_ids=request_ids,
            live_ids=live_ids,
            cutoff=cutoff if only_stale else None,
        )
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
    result = db.execute(
        update(ConversationTurn)
        .where(
            ConversationTurn.id == request_id,
            ConversationTurn.state == "pending",
            ConversationTurn.assistant_text.is_(None),
        )
        .values(
            assistant_text=reply,
            sources_json=json.dumps(stored_sources, ensure_ascii=False),
            state="ready",
        )
    )
    if not isinstance(result, CursorResult) or result.rowcount != 1:
        # A closed turn is already terminal (cancelled, repaired or failed);
        # writing over it would flip a recorded outcome the user has seen.
        db.rollback()
        raise conflict("chat_turn_closed", "This reply was already closed.")
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
    result = db.execute(
        update(ConversationTurn)
        .where(ConversationTurn.id == request_id, ConversationTurn.state == "pending")
        .values(state="acceptance_unknown" if uncertain else "failed", safe_error_code=code)
    )
    closed_state = turn.state
    db.expire(turn)
    if isinstance(result, CursorResult) and result.rowcount == 1:
        logger.warning(
            "Chat failed conversation_id=%s turn_id=%s code=%s", conversation_id, request_id, code
        )
    else:
        logger.warning(
            "Chat turn already closed, leaving it conversation_id=%s turn_id=%s state=%s",
            conversation_id,
            request_id,
            closed_state,
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
            "description": (
                "Server-sent event stream: delta events {request_id, seq, text} with "
                "incremental reply text, then text_done {request_id, assistant_text, "
                "revision, sources} with the committed reply, then at most one of "
                "tts_ready {request_id, audio_url, voice_profile_id, content_type, "
                "audio_duration_ms} with the synthesized WAV audio or "
                "tts_speech_empty {request_id} when the reply had nothing to speak. "
                "An error {request_id, safe_error_code} event can end the stream at "
                "any point instead."
            ),
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
