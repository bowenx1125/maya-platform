"""Registered services expose actual saved records, never invented memory."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.modules.auth.service import AuthContext
from app.modules.learning.attempts import (
    apply_assessment_action,
    get_assessment_runtime_context,
    read_attempt_answers,
)
from app.modules.learning.schemas import (
    AssessmentClassification,
    AssessmentOwnerAnswerDTO,
    AssessmentStudentAction,
)
from app.modules.learning.service import read_learning_records
from app.modules.workspace.models import Conversation, ConversationTurn

from .knowledge import knowledge_tools
from .learning import learning_tools
from .registry import ToolCallIdentity, ToolSpec
from .teacher import teacher_tools


class EmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssessmentActionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: AssessmentClassification
    answer_span: str | None = None


def assessment_action(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    payload: BaseModel,
    _call_id: str,
    identity: ToolCallIdentity,
) -> dict[str, Any]:
    """Apply a semantic action to saved text, never model-selected actor or question IDs."""
    arguments = AssessmentActionArguments.model_validate(payload)
    result = apply_assessment_action(
        db,
        actor,
        row.id,
        identity=identity,
        action=AssessmentStudentAction(
            classification=arguments.classification,
            answer_span=arguments.answer_span,
        ),
    )
    if result is None:
        raise conflict(
            "assessment_not_configured", "This conversation has no active assessment action."
        )
    return result.model_dump(mode="json")


def authorize_own_conversation(
    _db: Session, actor: AuthContext, row: Conversation, _payload: BaseModel
) -> None:
    if row.user_id != actor.user.id or row.withdrawn_at is not None:
        raise not_found()


def _attempt_records(db: Session, actor: AuthContext, row: Conversation) -> dict[str, Any] | None:
    context = get_assessment_runtime_context(db, actor, row.id)
    if context is None:
        return None
    if context.redirect_to_original_conversation:
        raise conflict(
            "assessment_resume_original_conversation",
            "Continue this assessment in its original conversation.",
        )
    return {
        "source": "saved_assessment_attempt",
        "progress": context.progress.model_dump(mode="json"),
        "submitted_records": [
            AssessmentOwnerAnswerDTO(
                answer_text=answer.answer_text,
                created_at=answer.created_at,
            ).model_dump(mode="json")
            for answer in read_attempt_answers(db, actor, row.id)
        ],
    }


def read_session(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    _payload: BaseModel,
    _call_id: str,
    _identity: ToolCallIdentity,
) -> dict[str, Any]:
    attempt_records = _attempt_records(db, actor, row)
    return {
        "entry_kind": row.entry_kind,
        "assessment": attempt_records,
    }


def read_memory(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    _payload: BaseModel,
    _call_id: str,
    _identity: ToolCallIdentity,
) -> dict[str, Any]:
    attempt_records = _attempt_records(db, actor, row)
    if attempt_records is not None:
        return attempt_records
    turns = db.scalars(
        select(ConversationTurn)
        .where(
            ConversationTurn.conversation_id == row.id,
            ConversationTurn.state.in_(("ready", "partial")),
        )
        .order_by(ConversationTurn.position, ConversationTurn.id)
    ).all()
    records = read_learning_records(db, actor, row.id)
    return {
        "source": "saved_conversation",
        "has_saved_records": bool(turns or records),
        "turns": [
            {"user_text": turn.user_text, "assistant_text": turn.assistant_text} for turn in turns
        ],
        "learning_records": [record.model_dump(mode="json") for record in records],
    }


def runtime_registry() -> dict[str, ToolSpec]:
    from .agent_memory import agent_memory_tools

    return {
        **teacher_tools(),
        **knowledge_tools(),
        **learning_tools(),
        **agent_memory_tools(),
        "assessment_action": ToolSpec(
            "assessment_action",
            "Student",
            (
                "Apply the user's explicit assessment action. Classify the saved current message; "
                "for answers provide only its exact answer span. Never invent an answer. "
                "complete_request means the user ends the test now: unanswered Questions are "
                "saved as skipped and the attempt is submitted. abandon_request discards the "
                "attempt's answers. redo_request means explicit abandonment AND redo, never a "
                "plain restart request. Before this attempt is submitted, 再来一轮 or 再来一遍 "
                "is redo_request: abandon this round's answers for scoring and start a new "
                "scored round. After it is submitted, that phrase is start_request: open another "
                "scored round and keep every completed record and score. Never edit a saved "
                "answer from another attempt or from a question that is not current. "
                "Use progress_request for time left or progress, "
                "restricted_request for answers, hints or judgments, and off_topic for anything "
                "else, including how to format an answer. "
                "Only a configured assessment recipe is affected. Return the server's safe result."
            ),
            AssessmentActionArguments,
            authorize_own_conversation,
            assessment_action,
        ),
        "read_session": ToolSpec(
            "read_session",
            "Public",
            (
                "Read this user's actual session and assessment progress. "
                "This cannot change identity, privacy or permissions."
            ),
            EmptyArguments,
            authorize_own_conversation,
            read_session,
            replay_read=read_session,
        ),
        "read_memory": ToolSpec(
            "read_memory",
            "Public",
            (
                "Read this user's real saved conversation records. During an unfinished assessment "
                "return submitted original answers and progress without hints, scores or Rubric. "
                "If no records exist, say so."
            ),
            EmptyArguments,
            authorize_own_conversation,
            read_memory,
            replay_read=read_memory,
        ),
    }
