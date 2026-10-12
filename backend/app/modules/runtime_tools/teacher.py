"""Teacher tools reuse course-authorized aggregates and persisted reports."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.modules.auth.service import AuthContext
from app.modules.learning.reports import (
    create_assessment_course_report,
    list_authorized_assessment_activities,
    read_assessment_activity_aggregate,
    read_attempt_transcripts,
)
from app.modules.workspace.models import Conversation

from .registry import ToolCallIdentity, ToolSpec


class ActivityArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: UUID


class TranscriptArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: UUID
    learner_ref: str | None = None


class CourseArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


def authorize_course(
    db: Session, actor: AuthContext, row: Conversation, _payload: BaseModel
) -> None:
    list_authorized_assessment_activities(db, actor, course_id=row.course_id)


def list_activities(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    _payload: BaseModel,
    _event_id: str,
    _identity: ToolCallIdentity,
) -> list[dict[str, Any]]:
    return [
        activity.model_dump(mode="json")
        for activity in list_authorized_assessment_activities(db, actor, course_id=row.course_id)
    ]


def authorize_activity(
    db: Session, actor: AuthContext, row: Conversation, payload: BaseModel
) -> None:
    arguments = ActivityArguments.model_validate(payload)
    if row.user_id != actor.user.id or row.withdrawn_at is not None:
        raise not_found()
    # Reuse the same publication, course, privacy and withdrawal projection as reports.
    read_assessment_activity_aggregate(
        db, actor, course_id=row.course_id, activity_id=str(arguments.activity_id)
    )


def authorize_transcripts(
    db: Session, actor: AuthContext, row: Conversation, payload: BaseModel
) -> None:
    arguments = TranscriptArguments.model_validate(payload)
    authorize_activity(db, actor, row, ActivityArguments(activity_id=arguments.activity_id))


def read_transcripts(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    payload: BaseModel,
    _event_id: str,
    _identity: ToolCallIdentity,
) -> dict[str, Any]:
    arguments = TranscriptArguments.model_validate(payload)
    return {
        "attempts": read_attempt_transcripts(
            db,
            actor,
            course_id=row.course_id,
            activity_id=str(arguments.activity_id),
            learner_ref=arguments.learner_ref,
        )
    }


def read_statistics(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    payload: BaseModel,
    _event_id: str,
    _identity: ToolCallIdentity,
) -> dict[str, Any]:
    arguments = ActivityArguments.model_validate(payload)
    return read_assessment_activity_aggregate(
        db, actor, course_id=row.course_id, activity_id=str(arguments.activity_id)
    ).model_dump(mode="json")


def create_report(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    payload: BaseModel,
    event_id: str,
    _identity: ToolCallIdentity,
) -> dict[str, Any]:
    arguments = ActivityArguments.model_validate(payload)
    receipt = create_assessment_course_report(
        db,
        actor,
        course_id=row.course_id,
        activity_id=str(arguments.activity_id),
        client_event_id=event_id,
    )
    return {
        "report_id": str(receipt.report.id),
        "revision_id": str(receipt.report.revision_id),
        "download_path": (
            f"/api/v1/learning/reports/{receipt.report.id}/download"
            f"?revision_id={receipt.report.revision_id}"
        ),
    }


def teacher_tools() -> dict[str, ToolSpec]:
    return {
        "list_course_assessments": ToolSpec(
            "list_course_assessments",
            "Teacher",
            "List authorized published assessment activities in the current course.",
            CourseArguments,
            authorize_course,
            list_activities,
            replay_read=list_activities,
        ),
        "read_course_statistics": ToolSpec(
            "read_course_statistics",
            "Teacher",
            "Read the current course's formal assessment aggregate, Public and Private "
            "attempts alike. Ordinary chats outside a test are excluded.",
            ActivityArguments,
            authorize_activity,
            read_statistics,
            replay_read=read_statistics,
        ),
        "read_student_test_transcripts": ToolSpec(
            "read_student_test_transcripts",
            "Teacher",
            "Read the raw messages of students' formal test attempts in an activity, from "
            "the start of each test to its end, Public and Private Chats alike. Use "
            "learner_ref from the statistics to read one student. Quote these messages "
            "when the teacher asks what a student answered; chat outside a test is not "
            "included.",
            TranscriptArguments,
            authorize_transcripts,
            read_transcripts,
            replay_read=read_transcripts,
        ),
        "create_course_report": ToolSpec(
            "create_course_report",
            "Teacher",
            "Save an evidence-linked report for an authorized activity in the current course. "
            "This does not grant assessment editing. "
            "Do not write a download link, path or token in your reply: the server adds "
            "the real download link under it.",
            ActivityArguments,
            authorize_activity,
            create_report,
        ),
    }
