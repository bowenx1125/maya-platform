import hashlib
import json
import logging
import re
import weakref
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.config import Settings, get_settings
from app.core.create_admission import create_admission_slot
from app.core.db import Database
from app.core.errors import Error, PlatformError, conflict, not_found
from app.core.message_timing import message_timing
from app.core.models import (
    Agent,
    AgentVersion,
    CourseMember,
    KnowledgeDocument,
    KnowledgeSnapshot,
    ProviderOperation,
    ProviderReservation,
    SnapshotDocument,
    StoredFile,
    User,
)
from app.core.sqlutil import begin_immediate
from app.core.write_guard import WriteSlot, reserve_write_slot, write_guard_slot
from app.modules.agents.schemas import AvatarConfig
from app.modules.auth.dependencies import (
    get_database,
    get_db,
    require_auth,
    require_authenticated_mutation,
)
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import (
    can_invoke_version,
    snapshot_sources_are_readable,
)
from app.modules.knowledge_sets.generation import get_generation_status
from app.modules.knowledge_sets.models import KnowledgeGenerationRun
from app.modules.knowledge_sets.schemas import KnowledgeGenerationChatProgress
from app.modules.learning.schemas import AssessmentRuntimeResult
from app.modules.runtime_tools.models import RuntimeToolReceipt
from app.providers.control_repository import ProviderSendingGuard

from .access import course_member
from .chat_provider import (
    assessment_reply_chinese,
    assessment_safe_reply_text,
    chat_messages,
    conversation_user_texts,
    real_reply,
    reply_language_from_projection,
    retrieve_sources,
)
from .chat_stream import accepts_event_stream, chat_audio_path, stream_events, stream_team_events
from .models import (
    ChatMemoryEntryAction,
    Conversation,
    ConversationTurn,
    TeamProviderCall,
    TeamTurnResult,
)
from .schemas import (
    AgentChatEntry,
    ChatAgent,
    ChatSession,
    ChatSource,
    ChatTurn,
    ConversationSession,
    CreateChat,
    MayaTeamChatEntry,
    MemoryAgentSource,
    MemoryConversationSource,
    MemoryEntryRequest,
    MemoryEntryResponse,
    MemoryMayaTeamSource,
    MemoryTeamSource,
    SavedTeamChatEntry,
    SendChat,
    StreamChat,
    UpdateChat,
)
from .team_conversation import (
    can_read_conversation,
    create_team_conversation,
    require_single_runtime,
    team_session_view,
)
from .team_runtime import (
    claim_team_turn,
    execute_team_turn,
    execute_team_turn_with_natural_assessment_resume,
    pause_team_turn,
    resume_team_turn,
)

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


def agent_view(
    version: AgentVersion,
    agent: Agent,
    course_id: str,
    *,
    name: str | None = None,
    available: bool = True,
) -> ChatAgent:
    return ChatAgent(
        agent_id=UUID(agent.id),
        version_id=UUID(version.id),
        course_id=UUID(course_id),
        name=name or agent.name,
        version_label=f"V1.{version.version_seq}",
        avatar_config=AvatarConfig.model_validate_json(version.avatar_config_json),
        visibility=cast(Literal["private", "public"], agent.visibility),
        available=available,
        deleted=agent.deleted_at is not None,
    )


def owned_conversation(db: Session, context: AuthContext, conversation_id: str) -> Conversation:
    row = db.get(Conversation, conversation_id)
    if row is None or row.user_id != context.user.id or row.withdrawn_at is not None:
        raise not_found()
    course_member(db, context, row.course_id)
    return row


def _require_canonical_assessment_conversation(
    db: Session, context: AuthContext, row: Conversation
) -> None:
    """Fence public re-entry before a Team turn or member dispatch is claimed."""
    if row.entry_kind == "agent":
        return
    from app.modules.learning.attempts import get_assessment_lifecycle_context

    assessment = get_assessment_lifecycle_context(db, context, row.id)
    if assessment is not None and assessment.redirect_to_original_conversation:
        raise conflict(
            "assessment_resume_original_conversation",
            "Continue this assessment in its original conversation.",
            {
                "response_key": "assessment.redirect",
                "conversation_id": str(assessment.canonical_conversation_id),
            },
        )


CHAT_BUSY_MESSAGE = "The previous message is still being answered. Send again in a moment."


def reject_if_chat_busy(db: Session, row: Conversation, request_id: str) -> None:
    """Answer chat_busy before queueing for admission, not after the wait.

    A resend of the same request (its turn exists) is not busy.
    """

    if (
        row.active_request_id is not None
        and row.active_request_id != request_id
        and db.get(ConversationTurn, request_id) is None
    ):
        raise conflict("chat_busy", CHAT_BUSY_MESSAGE)


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

    require_single_runtime(row)
    previous = db.get(ConversationTurn, request_id)
    if previous:
        if previous.conversation_id != row.id or previous.user_text != message:
            raise conflict("chat_request_changed", "This request has already been used.")
        return previous, False
    claimed = db.execute(
        update(Conversation)
        .where(
            Conversation.id == row.id,
            Conversation.withdrawn_at.is_(None),
            Conversation.revision == expected_revision,
            Conversation.active_request_id.is_(None),
        )
        .values(active_request_id=request_id, revision=Conversation.revision + 1)
    )
    if not isinstance(claimed, CursorResult) or claimed.rowcount != 1:
        raise conflict("chat_busy", CHAT_BUSY_MESSAGE)
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


def _apply_single_attempt_lifecycle_action(
    db: Session,
    row: Conversation,
    actor_context: AuthContext,
    turn: ConversationTurn,
    *,
    action: Literal["pause", "resume"],
    action_revision: int,
) -> None:
    """Synchronize any actor-owned recipe attempt in the turn-control transaction."""

    from app.modules.learning.attempts import apply_current_attempt_lifecycle_action
    from app.modules.learning.models import AssessmentAttempt

    active_attempt = db.scalar(
        select(AssessmentAttempt.id)
        .where(
            AssessmentAttempt.source_conversation_id == row.id,
            AssessmentAttempt.actor_user_id == actor_context.user.id,
            AssessmentAttempt.status.in_(("in_progress", "paused")),
        )
        .limit(1)
    )
    if active_attempt is None:
        return
    apply_current_attempt_lifecycle_action(
        db,
        actor_context,
        row.id,
        client_event_id=uuid5(UUID(turn.id), f"assessment:single-turn:{action}:{action_revision}"),
        action=action,
    )


def pause_chat_turn(
    db: Session,
    *,
    conversation_id: str,
    actor_context: AuthContext,
    turn_id: str,
    stopped: bool = False,
) -> ConversationTurn:
    """Fence a Single run by advancing the revision before marking it paused."""
    row = owned_conversation(db, actor_context, conversation_id)
    turn = db.get(ConversationTurn, turn_id)
    if (
        turn is None
        or turn.conversation_id != row.id
        or turn.assistant_text is not None
        or turn.state not in {"pending", "paused"}
    ):
        raise not_found()
    if turn.state == "paused":
        _apply_single_attempt_lifecycle_action(
            db,
            row,
            actor_context,
            turn,
            action="pause",
            action_revision=max(turn.position - 1, 0),
        )
        db.commit()
        return turn
    if row.active_request_id != turn.id:
        raise conflict("chat_turn_not_running", "This Chat turn cannot be paused now.")
    operations = list(
        db.scalars(
            select(ProviderOperation).where(
                ProviderOperation.scope_id == row.id,
                ProviderOperation.logical_item_id == turn.id,
                ProviderOperation.provider_operation == "llm_agent_chat",
            )
        )
    )
    if any(operation.state == "acceptance_unknown" for operation in operations):
        raise conflict(
            "chat_acceptance_unknown",
            "A Provider request may already have been accepted; send a new message to continue.",
        )
    if any(operation.state in {"prepared", "reserved", "sending"} for operation in operations):
        raise conflict(
            "chat_dispatch_in_progress",
            "Wait for the current Provider request to settle before pausing.",
        )
    expected_revision = row.revision
    _apply_single_attempt_lifecycle_action(
        db,
        row,
        actor_context,
        turn,
        action="pause",
        action_revision=expected_revision,
    )
    changed = db.execute(
        update(Conversation)
        .where(
            Conversation.id == row.id,
            Conversation.withdrawn_at.is_(None),
            Conversation.active_request_id == turn.id,
            Conversation.revision == expected_revision,
        )
        .values(active_request_id=None, revision=Conversation.revision + 1)
    )
    if not isinstance(changed, CursorResult) or changed.rowcount != 1:
        raise conflict("chat_request_stale", "This Chat turn is no longer active.")
    turn.state = "paused"
    turn.safe_error_code = "chat_output_stopped" if stopped else None
    db.commit()
    return turn


def resume_chat_turn(
    db: Session,
    *,
    conversation_id: str,
    actor_context: AuthContext,
    turn_id: str,
) -> tuple[ConversationTurn, int]:
    """Claim an existing Single turn with a new revision; accepted stages replay."""
    from app.modules.runtime_tools.models import RuntimeModelCallStage
    from app.providers.control_repository import ProviderRepository

    row = owned_conversation(db, actor_context, conversation_id)
    turn = db.get(ConversationTurn, turn_id)
    if (
        turn is None
        or turn.conversation_id != row.id
        or turn.state != "paused"
        or turn.assistant_text is not None
        or row.active_request_id is not None
    ):
        raise conflict("chat_turn_not_paused", "Resume the paused Chat turn before continuing.")
    operations = list(
        db.scalars(
            select(ProviderOperation)
            .where(
                ProviderOperation.scope_id == row.id,
                ProviderOperation.logical_item_id == turn.id,
                ProviderOperation.provider_operation == "llm_agent_chat",
            )
            .order_by(ProviderOperation.attempt_no)
        )
    )
    repository = ProviderRepository(db)
    unresolved = False
    failed_code: str | None = None
    for operation in operations:
        if operation.state == "sending":
            repository.mark_acceptance_unknown(
                operation.id, safe_error_code="recovered_acceptance_unknown"
            )
            unresolved = True
            continue
        if operation.state in {"prepared", "reserved"}:
            repository.mark_not_sent(operation.id, safe_error_code="recovered_not_sent")
            continue
        if operation.state == "acceptance_unknown":
            unresolved = True
            continue
        if operation.state == "not_sent":
            stage = db.get(RuntimeModelCallStage, operation.id)
            if (
                stage is None
                or hashlib.sha256(stage.request_json.encode("utf-8")).hexdigest()
                != stage.request_hash
            ):
                failed_code = "chat_request_stage_corrupt"
            continue
        if operation.state == "failed":
            failed_code = operation.safe_error_code or "chat_provider_not_sent"
            continue
        if operation.state not in {"accepted", "succeeded"}:
            failed_code = "chat_resume_unavailable"
            continue
        stage = db.get(RuntimeModelCallStage, operation.id)
        if (
            stage is None
            or stage.accepted_response_json is None
            or operation.request_hash != stage.request_hash
            or operation.staged_response_hash != stage.accepted_response_hash
            or hashlib.sha256(stage.request_json.encode("utf-8")).hexdigest() != stage.request_hash
            or hashlib.sha256(stage.accepted_response_json.encode("utf-8")).hexdigest()
            != stage.accepted_response_hash
        ):
            failed_code = "chat_response_unavailable"
            continue
    db.expire_all()
    turn = db.get(ConversationTurn, turn_id)
    current_row = db.get(Conversation, conversation_id)
    if turn is None or current_row is None:
        raise not_found()
    if unresolved:
        turn.state = "acceptance_unknown"
        turn.safe_error_code = "chat_acceptance_unknown"
        current_row.active_request_id = None
        db.commit()
        raise conflict(
            "chat_acceptance_unknown",
            "A previous Provider request may have been accepted; send a new message to continue.",
        )
    if failed_code is not None:
        turn.state = "failed"
        turn.safe_error_code = failed_code
        current_row.active_request_id = None
        db.commit()
        raise conflict(
            "chat_resume_unavailable",
            "This turn cannot be safely resumed; send a new message to continue.",
        )
    expected_revision = current_row.revision
    _apply_single_attempt_lifecycle_action(
        db,
        current_row,
        actor_context,
        turn,
        action="resume",
        action_revision=expected_revision,
    )
    next_revision = expected_revision + 1
    changed = db.execute(
        update(Conversation)
        .where(
            Conversation.id == current_row.id,
            Conversation.withdrawn_at.is_(None),
            Conversation.active_request_id.is_(None),
            Conversation.revision == expected_revision,
        )
        .values(active_request_id=turn.id, revision=next_revision)
    )
    if not isinstance(changed, CursorResult) or changed.rowcount != 1:
        raise conflict("chat_busy", "Refresh the conversation before resuming this turn.")
    turn.state = "pending"
    turn.safe_error_code = None
    db.commit()
    return turn, next_revision


def _current_chat_claim(conversation_id: str, request_id: str, claim_revision: int) -> Any:
    return (
        select(Conversation.id)
        .where(
            Conversation.id == conversation_id,
            Conversation.withdrawn_at.is_(None),
            Conversation.active_request_id == request_id,
            Conversation.revision == claim_revision,
        )
        .exists()
    )


def _chat_sending_guard(
    conversation_id: str,
    request_id: str,
    claim_revision: int,
    actor_user_id: str | None = None,
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
            select(
                conversations.c.id,
                conversations.c.user_id,
                conversations.c.course_id,
                conversations.c.agent_version_id,
                conversations.c.snapshot_id,
            )
            .select_from(conversations.join(turns, turns.c.conversation_id == conversations.c.id))
            .where(
                conversations.c.id == conversation_id,
                conversations.c.entry_kind == "agent",
                conversations.c.withdrawn_at.is_(None),
                conversations.c.active_request_id == request_id,
                conversations.c.revision == claim_revision,
                turns.c.id == request_id,
                turns.c.state == "pending",
                turns.c.assistant_text.is_(None),
            )
            .limit(1)
        )
        current_row = connection.execute(current).mappings().first()
        if current_row is None:
            return False
        if actor_user_id is None:
            return True
        if current_row["user_id"] != actor_user_id:
            return False
        try:
            with Session(
                bind=connection,
                autoflush=False,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as db:
                actor = db.get(User, actor_user_id)
                row = db.get(Conversation, conversation_id)
                version = (
                    db.get(AgentVersion, current_row["agent_version_id"])
                    if current_row["agent_version_id"] is not None
                    else None
                )
                agent = db.get(Agent, version.agent_id) if version is not None else None
                if (
                    actor is None
                    or actor.status != "active"
                    or db.get(CourseMember, (current_row["course_id"], actor_user_id)) is None
                    or row is None
                    or row.withdrawn_at is not None
                    or row.user_id != actor_user_id
                    or row.entry_kind != "agent"
                    or row.agent_version_id != current_row["agent_version_id"]
                    or row.snapshot_id != current_row["snapshot_id"]
                    or version is None
                    or agent is None
                    or version.agent_id != agent.id
                    or version.state not in {"published", "superseded"}
                    or version.knowledge_snapshot_id != row.snapshot_id
                    or agent.course_id != row.course_id
                    or agent.deleted_at is not None
                    or agent.status != "active"
                    or (
                        agent.owner_user_id != actor_user_id
                        and row.agent_authorization_epoch != agent.authorization_epoch
                    )
                    or not can_invoke_version(db, actor_user_id, version, agent)
                ):
                    return False
                if row.snapshot_id is None:
                    return True
                snapshot = db.get(KnowledgeSnapshot, row.snapshot_id)
                if snapshot is None or snapshot.agent_version_id != version.id:
                    return False
                if not snapshot_sources_are_readable(
                    db,
                    actor_user_id,
                    snapshot.id,
                    agent=agent,
                    allow_historical_epoch_for_owner=True,
                ):
                    return False
                source_rows = db.execute(
                    select(SnapshotDocument, KnowledgeDocument)
                    .join(
                        KnowledgeDocument,
                        KnowledgeDocument.id == SnapshotDocument.document_id,
                    )
                    .where(SnapshotDocument.snapshot_id == snapshot.id)
                ).all()
                for _snapshot_source, document in source_rows:
                    source_file = db.get(StoredFile, document.stored_file_id)
                    if (
                        document.workspace_state != "active"
                        or source_file is None
                        or source_file.state != "active"
                    ):
                        return False
                return True
        except Exception:
            return False

    return guard


def require_current_chat_claim(
    db: Session, conversation_id: str, request_id: str, claim_revision: int
) -> ConversationTurn:
    db.expire_all()
    turn = db.get(ConversationTurn, request_id)
    if (
        turn is None
        or turn.conversation_id != conversation_id
        or turn.state != "pending"
        or turn.assistant_text is not None
        or db.scalar(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.withdrawn_at.is_(None),
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


def _wake_assessment_finalizer(request: Request, conversation_id: str) -> None:
    """After a Team turn, finish a formal attempt whose last answer is in."""

    finalizer = getattr(request.app.state, "assessment_finalizer", None)
    wake = getattr(finalizer, "wake", None)
    if callable(wake):
        wake(conversation_id)


def _knowledge_generation_waker(request: Request) -> Callable[[str], None] | None:
    task_manager = getattr(request.app.state, "knowledge_generation_task_manager", None)
    wake = getattr(task_manager, "wake", None)
    return wake if callable(wake) else None


def generate_reply(
    db: Session,
    settings: Settings,
    row: Conversation,
    request_id: str,
    claim_revision: int,
    message: str,
    *,
    actor_context: AuthContext | None = None,
    allow_not_sent_retry: bool = False,
    generation_waker: Callable[[str], None] | None = None,
    write_slot: WriteSlot | None = None,
) -> tuple[str, list[ChatSource], str | None]:
    """Produce one full reply in memory.  This does not store assistant text.

    ``write_slot`` is the slot a send reserved before claiming its turn; a
    caller already holding one on this thread takes no second slot.
    """

    # Joins the request's collector when the HTTP handler already opened one
    # (then storing the reply is timed too); the stream path times this part.
    with (
        message_timing("chat", conversation_id=row.id, request_id=request_id),
        write_guard_slot(settings, reserved=write_slot),
    ):
        return _generate_reply_body(
            db,
            settings,
            row,
            request_id,
            claim_revision,
            message,
            actor_context=actor_context,
            allow_not_sent_retry=allow_not_sent_retry,
            generation_waker=generation_waker,
        )


def _generate_reply_body(
    db: Session,
    settings: Settings,
    row: Conversation,
    request_id: str,
    claim_revision: int,
    message: str,
    *,
    actor_context: AuthContext | None = None,
    allow_not_sent_retry: bool = False,
    generation_waker: Callable[[str], None] | None = None,
) -> tuple[str, list[ChatSource], str | None]:
    require_single_runtime(row)
    current_turn = require_current_chat_claim(db, row.id, request_id, claim_revision)
    if current_turn.user_text != message:
        raise conflict("chat_request_changed", "This request has already been used.")
    assessment_active = False
    if actor_context is not None:
        from app.modules.learning.attempts import get_assessment_runtime_context

        assessment_context = get_assessment_runtime_context(db, actor_context, row.id)
        assessment_active = assessment_context is not None
        if assessment_context is not None and assessment_context.redirect_to_original_conversation:
            raise conflict(
                "assessment_resume_original_conversation",
                "Continue this assessment in its original conversation.",
                {
                    "response_key": "assessment.redirect",
                    "conversation_id": str(assessment_context.canonical_conversation_id),
                },
            )
    version = db.get(AgentVersion, row.agent_version_id)
    agent = db.get(Agent, version.agent_id) if version else None
    if (
        version is None
        or agent is None
        or not _conversation_is_callable(db, row, version, agent, row.user_id)
    ):
        raise not_found()
    if current_turn.mode == "mock":
        if assessment_active:
            raise PlatformError(
                "assessment_action_required",
                "This activity needs an authorized assessment action.",
                409,
            )
        return f"Mock · {agent.name}\n\n{message}", [], None
    effective_settings = settings.model_copy(update={"llm_provider": "dashscope"})
    sending_guard = _chat_sending_guard(
        row.id,
        request_id,
        claim_revision,
        actor_user_id=str(actor_context.user.id) if actor_context is not None else None,
    )
    sources = retrieve_sources(
        db,
        effective_settings,
        version,
        course_id=row.course_id,
        scope_id=row.id,
        request_id=request_id,
        message=message,
        actor_user_id=str(actor_context.user.id) if actor_context is not None else None,
        turn_id=current_turn.id,
        claim_revision=claim_revision,
        sending_guard=sending_guard,
    )
    history = _saved_chat_history(db, row.id, current_turn.position)
    history.append({"role": "user", "content": message})
    require_current_chat_claim(db, row.id, request_id, claim_revision)
    canonical_knowledge: list[dict[str, Any]] = []
    if actor_context is not None:
        from app.modules.knowledge_sets.service import get_agent_runtime_knowledge

        canonical_knowledge = get_agent_runtime_knowledge(db, actor_context, agent.id)
    audience: Literal["student", "teacher"] = "student"
    if actor_context is not None:
        membership = db.get(CourseMember, (row.course_id, actor_context.user.id))
        if membership is not None and membership.role == "teacher":
            audience = "teacher"
    messages, persona_hash = chat_messages(
        version,
        history,
        sources,
        canonical_knowledge=canonical_knowledge,
        audience=audience,
    )
    reply, operation_id = real_reply(
        db,
        effective_settings,
        scope_id=row.id,
        request_id=request_id,
        course_id=row.course_id,
        messages=messages,
        persona_hash=persona_hash,
        version_id=version.id,
        group_id=agent.group_id,
        sending_guard=sending_guard,
        actor_context=actor_context,
        sources=sources,
        canonical_knowledge=canonical_knowledge,
        allow_not_sent_retry=allow_not_sent_retry,
        generation_waker=generation_waker,
        required_tool="assessment_action" if assessment_active else None,
    )
    assessment_result = _assessment_result_for_turn(db, row.id, request_id, row.user_id)
    if assessment_active and assessment_result is None:
        raise PlatformError(
            "assessment_action_required",
            "Continue the current assessment through its authorized action.",
            409,
        )
    if assessment_result is not None:
        from app.modules.knowledge_sets.service import knowledge_opening_for_question_version
        from app.modules.learning.attempts import awaits_follow_up_round

        question = assessment_result.context.current_question
        opening = ""
        if (
            assessment_result.response_key
            in {
                "assessment.started",
                "assessment.abandoned_and_restarted",
            }
            and question is not None
        ):
            opening = knowledge_opening_for_question_version(db, str(question.question_version_id))
        reply = assessment_safe_reply_text(
            assessment_result,
            conversation_user_texts(db, row.id),
            chinese=assessment_reply_chinese(db, row.id, conversation_user_texts(db, row.id)),
            follow_up_pending=awaits_follow_up_round(db, str(assessment_result.context.attempt.id)),
            prose=(
                reply
                if assessment_result.disposition == "read"
                and assessment_result.response_key == "assessment.progress"
                else None
            ),
            opening=opening,
        )
    return reply, sources, operation_id


def _assessment_result_for_turn(
    db: Session, conversation_id: str, turn_id: str, actor_user_id: str
) -> AssessmentRuntimeResult | None:
    values = db.scalars(
        select(RuntimeToolReceipt.result_json)
        .where(
            RuntimeToolReceipt.conversation_id == conversation_id,
            RuntimeToolReceipt.turn_id == turn_id,
            RuntimeToolReceipt.actor_user_id == actor_user_id,
            RuntimeToolReceipt.tool_name == "assessment_action",
        )
        .order_by(RuntimeToolReceipt.created_at.desc(), RuntimeToolReceipt.id.desc())
    )
    projection: AssessmentRuntimeResult | None = None
    for raw in values:
        try:
            receipt = json.loads(raw)
            if not isinstance(receipt, dict) or receipt.get("ok") is not True:
                continue
            value = receipt.get("result")
            if isinstance(value, dict):
                projection = AssessmentRuntimeResult.model_validate(
                    reply_language_from_projection(value)[0]
                )
                break
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    from app.modules.learning.attempts import (
        project_attempt_lifecycle_for_latest_turn,
        project_completed_assessment_for_boundary_call,
    )

    boundary_calls = db.execute(
        select(TeamProviderCall.id, RuntimeToolReceipt.tool_call_id)
        .join(TeamTurnResult, TeamTurnResult.id == TeamProviderCall.result_id)
        .join(
            RuntimeToolReceipt,
            RuntimeToolReceipt.model_operation_id == TeamProviderCall.operation_id,
        )
        .where(
            TeamTurnResult.turn_id == turn_id,
            RuntimeToolReceipt.conversation_id == conversation_id,
            RuntimeToolReceipt.turn_id == turn_id,
            RuntimeToolReceipt.actor_user_id == actor_user_id,
            RuntimeToolReceipt.tool_name == "update_learning_boundary",
        )
        .order_by(RuntimeToolReceipt.created_at.desc(), RuntimeToolReceipt.id.desc())
    )
    for model_call_id, tool_call_id in boundary_calls:
        completed = project_completed_assessment_for_boundary_call(
            db,
            actor_user_id,
            conversation_id,
            model_call_id=model_call_id,
            tool_call_id=tool_call_id,
        )
        if completed is not None:
            return completed
    return (
        project_attempt_lifecycle_for_latest_turn(
            db,
            actor_user_id,
            conversation_id,
            turn_id,
            previous=projection,
        )
        or projection
    )


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
    # Teacher report tools forbid inventing links; append the real ones here
    # for single-Agent Chat the same way Team Leader replies do.
    reply_with_reports = (
        reply
        + _agent_report_download_suffix(db, conversation_id, request_id)
        + _agent_answer_sheet_suffix(db, conversation_id, request_id)
    )
    write = db.execute(
        update(ConversationTurn)
        .where(
            ConversationTurn.id == request_id,
            ConversationTurn.conversation_id == conversation_id,
            ConversationTurn.state == "pending",
            ConversationTurn.assistant_text.is_(None),
            _current_chat_claim(conversation_id, request_id, claim_revision),
        )
        .values(
            assistant_text=reply_with_reports,
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
    if turn is None or turn.conversation_id != conversation_id or turn.state != "pending":
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


def _conversation_is_callable(
    db: Session,
    conversation: Conversation,
    version: AgentVersion,
    agent: Agent,
    actor_user_id: str,
) -> bool:
    if (
        conversation.withdrawn_at is not None
        or conversation.entry_kind != "agent"
        or conversation.user_id != actor_user_id
        or agent.deleted_at is not None
        or agent.status != "active"
        or version.knowledge_snapshot_id != conversation.snapshot_id
    ):
        return False
    is_owner = agent.owner_user_id == conversation.user_id
    if not is_owner and conversation.agent_authorization_epoch != agent.authorization_epoch:
        return False
    return can_invoke_version(db, actor_user_id, version, agent)


def _conversation_unavailable_error(agent: Agent | None) -> PlatformError:
    # Whoever chats with a deleted Agent learns that it was deleted; the Chat
    # itself already proves they could use it.
    if agent is not None and agent.deleted_at is not None:
        return conflict("agent_deleted", "This Agent has been deleted.")
    return conflict("agent_unavailable", "This Agent is no longer available to this chat.")


def _version_chat_allowed(
    db: Session, context: AuthContext, version: AgentVersion, agent: Agent
) -> bool:
    return can_invoke_version(db, context, version, agent)


def _version_chat_available(
    db: Session, context: AuthContext, version: AgentVersion, agent: Agent
) -> bool:
    return (
        agent.deleted_at is None
        and agent.status == "active"
        and version.state == "published"
        and _version_chat_allowed(db, context, version, agent)
    )


def _version_sources_usable(db: Session, version: AgentVersion) -> bool:
    """False when a published Agent still points at a withdrawn library file.

    The Chat/Team picker still lists the Agent, but marks it unavailable until
    its owner republishes with active RAG.
    """

    if version.knowledge_snapshot_id is None:
        return True
    rows = db.execute(
        select(KnowledgeDocument.workspace_state)
        .join(SnapshotDocument, SnapshotDocument.document_id == KnowledgeDocument.id)
        .where(SnapshotDocument.snapshot_id == version.knowledge_snapshot_id)
    ).all()
    return all(workspace_state == "active" for (workspace_state,) in rows)


def _agent_knowledge_generation_progress(
    db: Session,
    context: AuthContext,
    *,
    agent: Agent,
    turns: list[ConversationTurn],
    read_only: bool,
) -> KnowledgeGenerationChatProgress | None:
    """Latest generation for this Agent while the Teacher Chat should show a bar.

    Active runs always show. Terminal runs stay until the teacher sends a newer
    user message, matching Team assessment_stage completed retention.
    """

    if read_only or agent.owner_user_id != context.user.id:
        return None
    run = db.scalar(
        select(KnowledgeGenerationRun)
        .where(
            KnowledgeGenerationRun.agent_id == agent.id,
            KnowledgeGenerationRun.owner_user_id == context.user.id,
        )
        .order_by(
            KnowledgeGenerationRun.created_at.desc(),
            KnowledgeGenerationRun.id.desc(),
        )
        .limit(1)
    )
    if run is None:
        return None
    if run.state not in {"pending", "running"}:
        newer_user = any(turn.user_text and turn.created_at > run.updated_at for turn in turns)
        if newer_user:
            return None
    try:
        status = get_generation_status(db, context, run.job_id)
    except PlatformError:
        return None
    return KnowledgeGenerationChatProgress(
        run_id=status.run_id,
        job_id=status.job_id,
        knowledge_set_id=status.knowledge_set_id,
        state=status.state,
        safe_error_code=status.safe_error_code,
        accepted_item_count=status.accepted_item_count,
        materialized_item_count=status.materialized_item_count,
        failed_item_count=status.failed_item_count,
        created_at=status.created_at,
        updated_at=status.updated_at,
    )


def _agent_report_download_suffix(db: Session, conversation_id: str, turn_id: str) -> str:
    """Append server-authored report links; models must not invent download paths."""

    from app.modules.workspace.team_runtime import report_paths

    raw = db.scalars(
        select(RuntimeToolReceipt.result_json)
        .where(
            RuntimeToolReceipt.conversation_id == conversation_id,
            RuntimeToolReceipt.turn_id == turn_id,
            RuntimeToolReceipt.tool_name.in_(("create_course_report", "list_course_reports")),
        )
        .order_by(RuntimeToolReceipt.created_at, RuntimeToolReceipt.id)
    ).all()
    links = report_paths(raw)
    if not links:
        return ""
    return "\n\n" + "\n\n".join(f"[下载报告 / Download report]({path})" for path in links)


def _agent_answer_sheet_suffix(db: Session, conversation_id: str, turn_id: str) -> str:
    """Append the sheets this turn read. The model must not invent a table."""

    from app.modules.workspace.team_runtime import answer_sheet_markdown

    raw = db.scalars(
        select(RuntimeToolReceipt.result_json)
        .where(
            RuntimeToolReceipt.conversation_id == conversation_id,
            RuntimeToolReceipt.turn_id == turn_id,
            RuntimeToolReceipt.tool_name == "read_student_answers",
        )
        .order_by(RuntimeToolReceipt.created_at, RuntimeToolReceipt.id)
    ).all()
    return answer_sheet_markdown(raw)


def session_view(
    db: Session, conversation: Conversation, context: AuthContext, settings: Settings | None = None
) -> ConversationSession:
    if conversation.withdrawn_at is not None or not can_read_conversation(
        db, context.user.id, conversation
    ):
        raise not_found()
    read_only = conversation.user_id != context.user.id
    turns = db.scalars(
        select(ConversationTurn)
        .where(ConversationTurn.conversation_id == conversation.id)
        .order_by(ConversationTurn.position, ConversationTurn.id)
    ).all()
    visible_turns = [
        ChatTurn(
            id=UUID(turn.id),
            user_text=turn.user_text,
            assistant_text=turn.assistant_text,
            mode=cast(Literal["real", "mock"], turn.mode),
            state=cast(
                Literal["pending", "ready", "partial", "failed", "acceptance_unknown", "paused"],
                turn.state,
            ),
            # Public transcript access does not grant access to its raw RAG.
            sources=[] if read_only else json.loads(turn.sources_json),
            safe_error_code=turn.safe_error_code,
            assessment_result=(
                None
                if read_only
                else _assessment_result_for_turn(db, conversation.id, turn.id, conversation.user_id)
            ),
        )
        for turn in turns
    ]
    if conversation.entry_kind != "agent":
        view = team_session_view(
            db,
            conversation,
            context,
            visible_turns,
            runtime_available=settings is not None
            and settings.llm_provider in {"mock", "dashscope"},
        )
        if not read_only:
            from .team_runtime import revoked_assessment_action_target

            action_target = revoked_assessment_action_target(db, conversation, context)
            if action_target is not None:
                members = [
                    member.model_copy(update={"available": member.id == UUID(action_target.id)})
                    for member in view.team.members
                ]
                team = view.team.model_copy(update={"members": members, "available": True})
                view = view.model_copy(
                    update={
                        "team": team,
                        "can_send": (
                            settings is not None
                            and settings.llm_provider in {"mock", "dashscope"}
                            and conversation.withdrawn_at is None
                            and conversation.user_id == context.user.id
                            and conversation.active_request_id is None
                        ),
                    }
                )
        return view
    version = db.get(AgentVersion, conversation.agent_version_id)
    agent = db.get(Agent, version.agent_id) if version else None
    if version is None or agent is None:
        raise not_found()
    available = _conversation_is_callable(db, conversation, version, agent, conversation.user_id)
    return ChatSession(
        id=UUID(conversation.id),
        chat_visibility=cast(Literal["private", "public"], conversation.chat_visibility),
        read_only=read_only,
        can_send=not read_only and available,
        agent=agent_view(
            version,
            agent,
            conversation.course_id,
            name=conversation.agent_name_snapshot or agent.name,
            available=available,
        ),
        revision=conversation.revision,
        created_at=conversation.created_at,
        title=conversation.title,
        pinned_at=conversation.pinned_at,
        turns=visible_turns,
        knowledge_generation=_agent_knowledge_generation_progress(
            db, context, agent=agent, turns=list(turns), read_only=read_only
        ),
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
        .join(Agent, Agent.current_published_version_id == AgentVersion.id)
        .where(
            Agent.course_id == str(course_id),
            Agent.status == "active",
            Agent.deleted_at.is_(None),
            AgentVersion.state == "published",
            or_(
                Agent.owner_user_id == context.user.id,
                and_(
                    Agent.visibility == "public",
                    AgentVersion.published_visibility == "public",
                    Agent.authorization_epoch == AgentVersion.authorization_epoch,
                ),
            ),
        )
        .order_by(Agent.created_at.desc())
    ).all()
    return [
        agent_view(
            version,
            agent,
            str(course_id),
            available=_version_sources_usable(db, version),
        )
        for version, agent in rows
        if _version_chat_available(db, context, version, agent)
    ]


@router.get(
    "/conversations", response_model=list[ConversationSession], operation_id="listConversations"
)
def list_conversations(
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[ConversationSession]:
    rows = db.scalars(
        select(Conversation)
        .join(
            CourseMember,
            (
                (CourseMember.course_id == Conversation.course_id)
                & (CourseMember.user_id == Conversation.user_id)
            ),
        )
        .where(
            Conversation.withdrawn_at.is_(None),
            Conversation.user_id == context.user.id,
        )
        .order_by(
            # Pinned Chats come first, the latest pin on top.
            Conversation.pinned_at.is_(None),
            Conversation.pinned_at.desc(),
            select(func.max(ConversationTurn.created_at))
            .where(ConversationTurn.conversation_id == Conversation.id)
            .scalar_subquery()
            .desc(),
            Conversation.created_at.desc(),
            Conversation.id,
        )
    ).all()
    return [session_view(db, row, context, settings) for row in rows]


@router.post(
    "/conversations", response_model=ConversationSession, operation_id="createConversation"
)
def create_conversation(
    payload: CreateChat,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ConversationSession:
    with create_admission_slot():
        # Freeze one coherent Team definition while another request may save a new version.
        if db.get_bind().dialect.name == "sqlite":
            db.rollback()
            begin_immediate(db)
        if payload.entry is not None and not isinstance(payload.entry, AgentChatEntry):
            row = create_team_conversation(db, context, payload.entry)
            return session_view(db, row, context, settings)
        version_id = (
            payload.entry.version_id
            if isinstance(payload.entry, AgentChatEntry)
            else payload.version_id
        )
        version = db.get(AgentVersion, str(version_id))
        agent = db.get(Agent, version.agent_id) if version else None
        if (
            version is None
            or agent is None
            or agent.status != "active"
            or agent.deleted_at is not None
            or version.state != "published"
            or agent.current_published_version_id != version.id
            or not _version_chat_allowed(db, context, version, agent)
        ):
            raise not_found()
        course_member(db, context, agent.course_id)
        row = Conversation(
            id=str(uuid4()),
            user_id=context.user.id,
            course_id=agent.course_id,
            entry_kind="agent",
            chat_visibility="private",
            origin="single_agent",
            agent_version_id=version.id,
            snapshot_id=version.knowledge_snapshot_id,
            agent_name_snapshot=agent.name,
            agent_authorization_epoch=agent.authorization_epoch,
            revision=0,
            active_request_id=None,
            created_at=datetime.now(UTC),
        )
        db.add(row)
        db.flush()
        return session_view(db, row, context, settings)


_MEMORY_CHAT_MESSAGE = "你目前记得我们之前聊过什么？"


def _memory_source_identity(payload: MemoryEntryRequest) -> tuple[str, str]:
    source = payload.source
    if isinstance(source, MemoryConversationSource):
        return source.kind, str(source.id)
    if isinstance(source, MemoryAgentSource):
        return source.kind, str(source.agent_id)
    if isinstance(source, (MemoryTeamSource, MemoryMayaTeamSource)):
        return source.kind, str(source.team_id)
    raise not_found()


def _memory_conversation(
    db: Session,
    context: AuthContext,
    course_id: str,
    payload: MemoryEntryRequest,
    settings: Settings,
) -> Conversation:
    source = payload.source
    if isinstance(source, MemoryConversationSource):
        row = owned_conversation(db, context, str(source.id))
        if row.course_id != course_id:
            raise not_found()
        session_view(db, row, context, settings)
        return row

    if isinstance(source, MemoryAgentSource):
        agent = db.get(Agent, str(source.agent_id))
        version = (
            db.get(AgentVersion, agent.current_published_version_id)
            if agent is not None and agent.current_published_version_id is not None
            else None
        )
        if (
            agent is None
            or agent.course_id != course_id
            or agent.status != "active"
            or agent.deleted_at is not None
            or version is None
            or version.state != "published"
            or not _version_chat_available(db, context, version, agent)
        ):
            raise not_found()
        # Brainform Memory always opens a new chat. Account memory is not this transcript.
        row = Conversation(
            id=str(uuid4()),
            user_id=context.user.id,
            course_id=course_id,
            entry_kind="agent",
            chat_visibility="private",
            origin="single_agent",
            agent_version_id=version.id,
            snapshot_id=version.knowledge_snapshot_id,
            agent_name_snapshot=agent.name,
            agent_authorization_epoch=agent.authorization_epoch,
            revision=0,
            active_request_id=None,
            created_at=datetime.now(UTC),
        )
        db.add(row)
        db.flush()
        return row

    if isinstance(source, MemoryTeamSource):
        entry: SavedTeamChatEntry | MayaTeamChatEntry = SavedTeamChatEntry(
            kind="team", team_id=source.team_id
        )
    elif isinstance(source, MemoryMayaTeamSource):
        entry = MayaTeamChatEntry(kind="maya_team", team_id=source.team_id)
    else:
        raise not_found()

    # A Team Memory click opens a new chat even when an older Team chat or assessment exists.
    row = create_team_conversation(db, context, entry)
    if row.course_id != course_id:
        raise not_found()
    return row


@router.post(
    "/conversations/memory-entry",
    response_model=MemoryEntryResponse,
    operation_id="createMemoryEntryAction",
    responses={
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
def create_memory_entry_action(
    payload: MemoryEntryRequest,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MemoryEntryResponse:
    """Resolve one durable Brainform navigation intent; sending remains explicit Chat work."""
    course_id = str(payload.course_id)
    source_kind, source_id = _memory_source_identity(payload)
    if db.get_bind().dialect.name == "sqlite":
        db.rollback()
        begin_immediate(db)
    course_member(db, context, course_id)
    actor = db.get(User, context.user.id)
    if actor is None or actor.status != "active":
        raise not_found()
    action = db.get(ChatMemoryEntryAction, (context.user.id, str(payload.action_id)))
    if action is not None:
        if (
            action.course_id != course_id
            or action.source_kind != source_kind
            or action.source_id != source_id
        ):
            raise conflict(
                "memory_action_changed", "This Memory entry action has already been used."
            )
        row = owned_conversation(db, context, action.conversation_id)
        return MemoryEntryResponse(
            action_id=payload.action_id,
            conversation_id=UUID(row.id),
            request_id=UUID(action.request_id),
            message=action.message,
            session=session_view(db, row, context, settings),
        )

    row = _memory_conversation(db, context, course_id, payload, settings)
    # A new Memory chat does not resume an assessment window. The speaking Agent
    # chooses read_memory or read_agent_memory after the one-shot question.
    message = _MEMORY_CHAT_MESSAGE
    request_id = str(uuid4())
    db.add(
        ChatMemoryEntryAction(
            actor_user_id=context.user.id,
            action_id=str(payload.action_id),
            course_id=course_id,
            source_kind=source_kind,
            source_id=source_id,
            conversation_id=row.id,
            request_id=request_id,
            message=message,
            created_at=datetime.now(UTC),
        )
    )
    db.flush()
    db.commit()
    db.expire_all()
    row = owned_conversation(db, context, row.id)
    return MemoryEntryResponse(
        action_id=payload.action_id,
        conversation_id=UUID(row.id),
        request_id=UUID(request_id),
        message=message,
        session=session_view(db, row, context, settings),
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationSession,
    operation_id="getConversation",
)
def get_conversation(
    conversation_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ConversationSession:
    row = db.get(Conversation, str(conversation_id))
    if row is None:
        raise not_found()
    return session_view(db, row, context, settings)


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
    row = db.get(Conversation, str(conversation_id))
    if row is None or row.user_id != context.user.id:
        raise not_found()
    course_member(db, context, row.course_id)
    if row.withdrawn_at is None:
        from app.modules.learning.attempts import withdraw_conversation_attempts

        timestamp = datetime.now(UTC)
        db.execute(
            update(Conversation)
            .where(Conversation.id == row.id, Conversation.withdrawn_at.is_(None))
            .values(
                withdrawn_at=timestamp, active_request_id=None, revision=Conversation.revision + 1
            )
        )
        db.execute(
            update(ConversationTurn)
            .where(ConversationTurn.conversation_id == row.id, ConversationTurn.state == "pending")
            .values(state="failed", safe_error_code="chat_withdrawn")
        )
        withdraw_conversation_attempts(db, row.id)
        db.commit()
    return Response(status_code=204)


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationSession,
    operation_id="updateConversation",
)
def update_conversation(
    conversation_id: UUID,
    payload: UpdateChat,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ConversationSession:
    row = db.get(Conversation, str(conversation_id))
    if row is None or row.user_id != context.user.id or row.withdrawn_at is not None:
        raise not_found()
    course_member(db, context, row.course_id)
    # A name and a pin only arrange the owner's own history, so they stay
    # open on a Chat whose Agent was deleted and never touch its revision.
    values: dict[str, Any] = {}
    if "title" in payload.model_fields_set:
        values["title"] = (payload.title or "").strip() or None
    if payload.pinned is not None:
        values["pinned_at"] = (row.pinned_at or datetime.now(UTC)) if payload.pinned else None
    db.execute(update(Conversation).where(Conversation.id == row.id).values(**values))
    db.commit()
    db.refresh(row)
    return session_view(db, row, context, settings)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationSession,
    operation_id="sendConversationMessage",
    responses={503: {"model": Error}},
)
def send_message(
    conversation_id: UUID,
    payload: SendChat,
    request: Request,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    database: Database = Depends(get_database),
) -> ConversationSession:
    row = owned_conversation(db, context, str(conversation_id))
    with message_timing(
        "chat" if row.entry_kind == "agent" else "team",
        conversation_id=row.id,
        request_id=payload.request_id,
    ):
        if row.entry_kind != "agent":
            _require_canonical_assessment_conversation(db, context, row)
            db.commit()  # hold no pooled connection while queued
            with write_guard_slot(settings):
                claim = claim_team_turn(
                    db,
                    settings,
                    conversation_id=row.id,
                    actor_id=context.user.id,
                    request_id=str(payload.request_id),
                    expected_revision=payload.expected_revision,
                    message=payload.message,
                    routing=payload.routing,
                    actor_context=context,
                )
                execute_team_turn_with_natural_assessment_resume(database.session_factory, claim)
            _wake_assessment_finalizer(request, row.id)
            db.expire_all()
            return session_view(
                db, owned_conversation(db, context, str(conversation_id)), context, settings
            )
        if payload.routing is not None and payload.routing.mode != "auto":
            raise conflict("chat_routing_invalid", "Single Chats cannot select Team participants.")
        version = db.get(AgentVersion, row.agent_version_id)
        agent = db.get(Agent, version.agent_id) if version else None
        if (
            version is None
            or agent is None
            or not _conversation_is_callable(db, row, version, agent, context.user.id)
        ):
            raise _conversation_unavailable_error(agent)
        request_id = str(payload.request_id)
        message = payload.message.strip()
        if not message:
            raise PlatformError("chat_message_empty", "Enter a message.", 400)
        reject_if_chat_busy(db, row, request_id)
        # Admission comes before the claim: a busy server answers 503 with
        # nothing stored, and the student resends the text still in the box.
        # No pooled connection is held while waiting in the queue (nothing is
        # pending; commit only ends the read transaction, keeping the rows).
        db.commit()
        with write_guard_slot(settings):
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
                return session_view(db, row, context, settings)
            try:
                reply, sources, operation_id = generate_reply(
                    db,
                    settings,
                    row,
                    request_id,
                    claim_revision,
                    message,
                    actor_context=context,
                    generation_waker=_knowledge_generation_waker(request),
                )
                store_assistant_text(
                    db, row.id, request_id, claim_revision, reply, sources, operation_id
                )
            except Exception as exc:
                record_chat_failure(db, row.id, request_id, claim_revision, exc)
            release_chat_request(db, row.id, request_id, claim_revision)
            db.commit()
        db.expire_all()
        return session_view(
            db, owned_conversation(db, context, str(conversation_id)), context, settings
        )


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
    request: Request,
    accept: str = Header(..., alias="Accept"),
    last_event_id: int = Header(0, alias="Last-Event-ID", ge=0),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    row = owned_conversation(db, context, str(conversation_id))
    if row.entry_kind != "agent":
        _require_canonical_assessment_conversation(db, context, row)
        if not accepts_event_stream(accept):
            raise PlatformError("malformed_request", "Accept text/event-stream is required.", 400)
        actor_id = context.user.id
        actor_session_id_hash = context.session.id_hash
        owned_id = row.id
        # Admission before the claim; the worker thread adopts this slot.
        db.commit()  # hold no pooled connection while queued
        team_slot = reserve_write_slot(settings)
        try:
            claim = claim_team_turn(
                db,
                settings,
                conversation_id=owned_id,
                actor_id=actor_id,
                request_id=str(payload.request_id),
                expected_revision=payload.expected_revision,
                message=payload.message,
                routing=payload.routing,
                actor_context=context,
            )
        except BaseException:
            team_slot.release()
            raise
        # The claim rolls back this request Session before committing. Keep
        # only the authenticated identity keys available to the worker; its
        # current-session and resource checks always re-read durable state.
        set_committed_value(context.user, "id", actor_id)
        set_committed_value(context.session, "id_hash", actor_session_id_hash)
        db.close()
        team_stream = stream_team_events(
            database,
            owned_id,
            actor_id,
            claim,
            last_event_id,
            on_finished=lambda: _wake_assessment_finalizer(request, owned_id),
            write_slot=team_slot,
        )
        # A browser gone before the stream starts never runs the generator.
        weakref.finalize(team_stream, team_slot.release_if_unadopted)
        return StreamingResponse(
            team_stream,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
    if payload.routing is not None and payload.routing.mode != "auto":
        raise conflict("chat_routing_invalid", "Single Chats cannot select Team participants.")
    version = db.get(AgentVersion, row.agent_version_id)
    agent = db.get(Agent, version.agent_id) if version else None
    if (
        version is None
        or agent is None
        or not _conversation_is_callable(db, row, version, agent, context.user.id)
    ):
        raise _conversation_unavailable_error(agent)
    if not accepts_event_stream(accept):
        raise PlatformError("malformed_request", "Accept text/event-stream is required.", 400)
    request_id = str(payload.request_id)
    message = payload.message.strip()
    if not message:
        raise PlatformError("chat_message_empty", "Enter a message.", 400)
    reject_if_chat_busy(db, row, request_id)
    # Admission before the claim (503 with nothing stored); the reply thread
    # adopts this slot.
    db.commit()  # hold no pooled connection while queued
    slot = reserve_write_slot(settings)
    try:
        turn, created = claim_chat_send(
            db,
            row,
            request_id=request_id,
            expected_revision=payload.expected_revision,
            message=message,
            settings=settings,
        )
    except BaseException:
        slot.release()
        raise
    claim_revision = turn.position
    owned_id = row.id
    # Claim is committed.  Drop the request connection before the stream so
    # it is not held across the LLM call or TTS.
    db.close()
    reply_stream = stream_events(
        database,
        settings,
        conversation_id=owned_id,
        created=created,
        message=message,
        request_id=request_id,
        claim_revision=claim_revision,
        actor_context=context,
        generation_waker=_knowledge_generation_waker(request),
        write_slot=slot,
    )
    # A browser gone before the stream starts never runs the generator.
    weakref.finalize(reply_stream, slot.release_if_unadopted)
    return StreamingResponse(
        reply_stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/conversations/{conversation_id}/turns/{turn_id}:pause",
    response_model=ConversationSession,
    operation_id="pauseTeamConversationTurn",
    responses={409: {"model": Error}},
)
def pause_team_conversation_turn(
    conversation_id: UUID,
    turn_id: UUID,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ConversationSession:
    row = owned_conversation(db, context, str(conversation_id))
    if row.entry_kind == "agent":
        pause_chat_turn(
            db,
            conversation_id=row.id,
            actor_context=context,
            turn_id=str(turn_id),
        )
        db.expire_all()
        return session_view(db, owned_conversation(db, context, row.id), context, settings)
    pause_team_turn(
        db,
        conversation_id=row.id,
        actor_id=context.user.id,
        turn_id=str(turn_id),
        actor_context=context,
    )
    db.expire_all()
    return session_view(db, owned_conversation(db, context, row.id), context, settings)


@router.post(
    "/conversations/{conversation_id}/turns/{turn_id}:stop",
    response_model=ConversationSession,
    operation_id="stopTeamConversationTurnOutput",
    responses={409: {"model": Error}},
)
def stop_team_conversation_turn_output(
    conversation_id: UUID,
    turn_id: UUID,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ConversationSession:
    row = owned_conversation(db, context, str(conversation_id))
    if row.entry_kind == "agent":
        pause_chat_turn(
            db,
            conversation_id=row.id,
            actor_context=context,
            turn_id=str(turn_id),
            stopped=True,
        )
        db.expire_all()
        return session_view(db, owned_conversation(db, context, row.id), context, settings)
    pause_team_turn(
        db,
        conversation_id=row.id,
        actor_id=context.user.id,
        turn_id=str(turn_id),
        stopped=True,
        actor_context=context,
    )
    db.expire_all()
    return session_view(db, owned_conversation(db, context, row.id), context, settings)


@router.post(
    "/conversations/{conversation_id}/turns/{turn_id}:resume",
    response_model=ConversationSession,
    operation_id="resumeTeamConversationTurn",
    responses={409: {"model": Error}},
)
def resume_team_conversation_turn(
    conversation_id: UUID,
    turn_id: UUID,
    request: Request,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    database: Database = Depends(get_database),
) -> ConversationSession:
    row = owned_conversation(db, context, str(conversation_id))
    if row.entry_kind == "agent":
        _require_canonical_assessment_conversation(db, context, row)
        turn, claim_revision = resume_chat_turn(
            db,
            conversation_id=row.id,
            actor_context=context,
            turn_id=str(turn_id),
        )
        try:
            reply, sources, operation_id = generate_reply(
                db,
                settings,
                row,
                turn.id,
                claim_revision,
                turn.user_text,
                actor_context=context,
                allow_not_sent_retry=True,
                generation_waker=_knowledge_generation_waker(request),
            )
            store_assistant_text(
                db,
                row.id,
                turn.id,
                claim_revision,
                reply,
                sources,
                operation_id,
            )
        except Exception as exc:
            record_chat_failure(db, row.id, turn.id, claim_revision, exc)
        release_chat_request(db, row.id, turn.id, claim_revision)
        db.commit()
        db.expire_all()
        return session_view(db, owned_conversation(db, context, row.id), context, settings)
    _require_canonical_assessment_conversation(db, context, row)
    claim = resume_team_turn(
        db,
        settings,
        conversation_id=row.id,
        actor_id=context.user.id,
        turn_id=str(turn_id),
        actor_context=context,
    )
    execute_team_turn(database.session_factory, claim)
    _wake_assessment_finalizer(request, row.id)
    db.expire_all()
    return session_view(db, owned_conversation(db, context, row.id), context, settings)


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
