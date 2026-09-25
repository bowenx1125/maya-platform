import json
import logging
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
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
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext

from .access import course_member
from .chat_provider import chat_messages, real_reply, retrieve_sources
from .models import Conversation, ConversationTurn
from .schemas import ChatAgent, ChatSession, ChatSource, ChatTurn, CreateChat, SendChat

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
    previous = db.get(ConversationTurn, request_id)
    if previous:
        if previous.conversation_id != row.id or previous.user_text != message:
            raise conflict("chat_request_changed", "This request has already been used.")
        return session_view(db, row)
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
            Conversation.revision == payload.expected_revision,
            Conversation.active_request_id.is_(None),
        )
        .values(active_request_id=request_id, revision=Conversation.revision + 1)
    )
    if not isinstance(claimed, CursorResult) or claimed.rowcount != 1:
        raise conflict("chat_busy", "Refresh the conversation before sending another message.")
    turn: ConversationTurn | None = ConversationTurn(
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
    operation_id: str | None = None
    sources: list[ChatSource] = []
    try:
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
            reply = f"Mock · {agent.name}\n\n{message}"
        else:
            sources = retrieve_sources(
                db,
                settings,
                version,
                course_id=row.course_id,
                scope_id=row.id,
                request_id=request_id,
                message=message,
            )
            history = []
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
        db.expire_all()
        turn = db.get(ConversationTurn, request_id)
        if turn is None:
            raise not_found()
        turn.assistant_text = reply
        turn.sources_json = json.dumps(
            [s.model_dump(mode="json") for s in sources], ensure_ascii=False
        )
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
    except Exception as exc:
        db.rollback()
        turn = db.get(ConversationTurn, request_id)
        if turn is None:
            raise not_found() from None
        # No exception text or supplier response is returned or logged.
        code = getattr(exc, "code", "chat_failed")
        if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
            code = "chat_failed"
        uncertain = "acceptance_unknown" in code or bool(
            db.scalar(
                select(ProviderOperation.id)
                .where(
                    ProviderOperation.scope_id == row.id,
                    ProviderOperation.state.in_(("sending", "accepted", "acceptance_unknown")),
                )
                .limit(1)
            )
        )
        turn.state = "acceptance_unknown" if uncertain else "failed"
        turn.safe_error_code = code
        logger.warning(
            "Chat failed conversation_id=%s turn_id=%s code=%s", row.id, request_id, code
        )
    db.execute(
        update(Conversation)
        .where(Conversation.id == row.id, Conversation.active_request_id == request_id)
        .values(active_request_id=None)
    )
    db.commit()
    db.expire_all()
    return session_view(db, owned_conversation(db, context, str(conversation_id)))
