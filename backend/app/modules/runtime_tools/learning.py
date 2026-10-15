"""Typed learning Tools delegate target ACL and phase views to learning services."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.modules.auth.service import AuthContext
from app.modules.learning.execution import (
    authorize_assessment_edit,
    authorize_assessment_edit_replay,
    authorize_boundary_update,
    authorize_boundary_update_replay,
    read_authorized_assessment,
    read_authorized_boundary,
    read_own_formal_attempt,
    write_assessment_revision,
    write_formal_boundary,
)
from app.modules.learning.schemas import AssessmentEvaluationContent, BoundarySummaryContent
from app.modules.workspace.models import Conversation

from .registry import ToolCallIdentity, ToolSpec


class AttemptArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempt_id: UUID


class AssessmentArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assessment_id: UUID


class BoundaryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    boundary_id: UUID


class AssessmentEditArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: AssessmentEvaluationContent
    assessment_id: UUID | None = None
    follow_up_question_refs: list[str] = Field(default_factory=list)


def _summary_text(item: Any) -> str:
    if isinstance(item, str):
        return " ".join(item.split())
    if isinstance(item, dict):
        for key in ("text", "point", "name", "knowledge_point", "summary"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())
        for value in item.values():
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())
    return ""


def _summary_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = _summary_text(value)
        return [text] if text else []
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _summary_text(item))]


def _summary_content(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only the summary fields. Models often send them beside `content`."""

    content: dict[str, Any] = {}
    summary = raw.get("summary")
    if isinstance(summary, str):
        content["summary"] = summary.strip()
    for key in ("strengths", "areas_to_explore", "not_yet_verified"):
        if key in raw:
            content[key] = _summary_list(raw[key])
    next_step = raw.get("next_step")
    if isinstance(next_step, str) and next_step.strip():
        content["next_step"] = next_step.strip()
    return content


class BoundaryEditArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: BoundarySummaryContent

    @model_validator(mode="before")
    @classmethod
    def accept_flat_summary(cls, value: Any) -> Any:
        # The schema nests the summary under content. A model that was told the
        # field names puts them directly in arguments, and stop_after_tool_call
        # then ends the turn before a second try. Accept that shape.
        if not isinstance(value, dict):
            return value
        inner = value.get("arguments")
        if "content" not in value and isinstance(inner, dict):
            value = inner
        content = value.get("content")
        if isinstance(content, str) and content.strip():
            return {"content": {"summary": content.strip()}}
        if isinstance(content, dict):
            return {"content": _summary_content(content)}
        if isinstance(value.get("summary"), str):
            return {"content": _summary_content(value)}
        return value


def read_attempt(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    payload: BaseModel,
    _event_id: str,
    _identity: ToolCallIdentity,
) -> dict[str, Any]:
    arguments = AttemptArguments.model_validate(payload)
    return read_own_formal_attempt(db, actor, row.id, attempt_id=arguments.attempt_id)


def read_assessment(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    payload: BaseModel,
    _event_id: str,
    _identity: ToolCallIdentity,
) -> dict[str, Any]:
    arguments = AssessmentArguments.model_validate(payload)
    return read_authorized_assessment(db, actor, row.id, assessment_id=arguments.assessment_id)


def read_boundary(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    payload: BaseModel,
    _event_id: str,
    _identity: ToolCallIdentity,
) -> dict[str, Any]:
    arguments = BoundaryArguments.model_validate(payload)
    return read_authorized_boundary(db, actor, row.id, boundary_id=arguments.boundary_id)


def authorize_read_attempt(
    db: Session, actor: AuthContext, row: Conversation, payload: BaseModel
) -> None:
    arguments = AttemptArguments.model_validate(payload)
    read_own_formal_attempt(db, actor, row.id, attempt_id=arguments.attempt_id)


def authorize_read_assessment(
    db: Session, actor: AuthContext, row: Conversation, payload: BaseModel
) -> None:
    arguments = AssessmentArguments.model_validate(payload)
    read_authorized_assessment(db, actor, row.id, assessment_id=arguments.assessment_id)


def authorize_read_boundary(
    db: Session, actor: AuthContext, row: Conversation, payload: BaseModel
) -> None:
    arguments = BoundaryArguments.model_validate(payload)
    read_authorized_boundary(db, actor, row.id, boundary_id=arguments.boundary_id)


def _execution_only(
    _db: Session, _actor: AuthContext, _row: Conversation, _payload: BaseModel
) -> None:
    # Accepted invocation and resource-specific execution grants are checked by the hook.
    return None


def edit_assessment(
    db: Session,
    actor: AuthContext,
    _row: Conversation,
    payload: BaseModel,
    _event_id: str,
    identity: ToolCallIdentity,
) -> dict[str, bool]:
    arguments = AssessmentEditArguments.model_validate(payload)
    return write_assessment_revision(
        db,
        actor,
        identity,
        arguments.content.model_dump(mode="json"),
        assessment_id=arguments.assessment_id,
        follow_up_question_refs=arguments.follow_up_question_refs,
    )


def update_boundary(
    db: Session,
    actor: AuthContext,
    _row: Conversation,
    payload: BaseModel,
    _event_id: str,
    identity: ToolCallIdentity,
) -> dict[str, bool]:
    arguments = BoundaryEditArguments.model_validate(payload)
    return write_formal_boundary(db, actor, identity, arguments.content.model_dump(mode="json"))


def learning_tools() -> dict[str, ToolSpec]:
    return {
        "read_learning_attempt": ToolSpec(
            "read_learning_attempt",
            "Public",
            "Read your authorized target attempt from any own Chat. Unfinished attempts expose "
            "only submitted answers, presented questions and progress; no hints or scores.",
            AttemptArguments,
            authorize_read_attempt,
            read_attempt,
            replay_read=read_attempt,
        ),
        "read_assessment": ToolSpec(
            "read_assessment",
            "Public",
            "Read the authorized phase-safe view of your Assessment.",
            AssessmentArguments,
            authorize_read_assessment,
            read_assessment,
            replay_read=read_assessment,
        ),
        "read_learning_boundary": ToolSpec(
            "read_learning_boundary",
            "Public",
            "Read your Boundary only in its authorized phase-safe view.",
            BoundaryArguments,
            authorize_read_boundary,
            read_boundary,
            replay_read=read_boundary,
        ),
        "edit_assessment": ToolSpec(
            "edit_assessment",
            "Public",
            "Save an Assessment revision with explicit target edit permission. Formal results "
            "require this invocation's server-issued evaluator grant. "
            "follow_up_question_refs may list only refs offered in follow_up_candidates; "
            "leave it empty when none are offered. "
            "Owning an attempt, being a teacher or naming an evaluator does not grant editing.",
            AssessmentEditArguments,
            _execution_only,
            edit_assessment,
            authorize_execution=authorize_assessment_edit,
            authorize_replay=authorize_assessment_edit_replay,
        ),
        "update_learning_boundary": ToolSpec(
            "update_learning_boundary",
            "Public",
            "Save a Boundary revision linked to real saved evidence only under the current "
            "server-issued summarizer grant. This cannot edit Assessment or original answers.",
            BoundaryEditArguments,
            _execution_only,
            update_boundary,
            authorize_execution=authorize_boundary_update,
            authorize_replay=authorize_boundary_update_replay,
            stop_after_tool_call=True,
        ),
    }
