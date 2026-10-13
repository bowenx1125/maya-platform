"""Teacher tools reuse course-authorized aggregates and persisted reports."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.modules.auth.service import AuthContext
from app.modules.learning.models import (
    AssessmentCourseReport,
    AssessmentCourseReportRevision,
)
from app.modules.learning.reports import (
    create_assessment_course_report,
    list_authorized_assessment_activities,
    read_assessment_activity_aggregate,
    read_attempt_transcripts,
    read_student_answers,
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
    include_abandoned: bool = False


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
            include_abandoned=arguments.include_abandoned,
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
        "download_path": report_download_path(
            str(receipt.report.id), str(receipt.report.revision_id)
        ),
    }


def read_answers(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    payload: BaseModel,
    _event_id: str,
    _identity: ToolCallIdentity,
) -> dict[str, Any]:
    arguments = TranscriptArguments.model_validate(payload)
    return {
        "attempts": read_student_answers(
            db,
            actor,
            course_id=row.course_id,
            activity_id=str(arguments.activity_id),
            learner_ref=arguments.learner_ref,
            include_abandoned=arguments.include_abandoned,
        )
    }


def report_download_path(report_id: str, revision_id: str) -> str:
    return f"/api/v1/learning/reports/{report_id}/download?revision_id={revision_id}"


def list_reports(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    _payload: BaseModel,
    _event_id: str,
    _identity: ToolCallIdentity,
) -> dict[str, Any]:
    """This teacher's saved reports in the course, newest first.

    Owner request (2026-10-13): a teacher asking where an earlier report is gets
    its download link again; the server adds the links under the reply.
    """

    reports = db.scalars(
        select(AssessmentCourseReport)
        .where(
            AssessmentCourseReport.course_id == row.course_id,
            AssessmentCourseReport.owner_user_id == actor.user.id,
        )
        .order_by(AssessmentCourseReport.updated_at.desc(), AssessmentCourseReport.id)
        .limit(10)
    ).all()
    items: list[dict[str, Any]] = []
    for report in reports:
        revision = db.scalar(
            select(AssessmentCourseReportRevision).where(
                AssessmentCourseReportRevision.report_id == report.id,
                AssessmentCourseReportRevision.revision_seq == report.current_revision_seq,
            )
        )
        if revision is None:
            continue
        items.append(
            {
                "report_id": report.id,
                "activity_id": report.activity_id,
                "revision_id": revision.id,
                "saved_at": revision.created_at.isoformat(),
                "download_path": report_download_path(report.id, revision.id),
            }
        )
    return {"reports": items}


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
            "learner_ref from the statistics to read one student. Each item is one attempt, "
            "newest first: never combine messages from different attempts, and name the "
            "attempt you quote. Abandoned attempts are left out unless include_abandoned "
            "is true; their answers were discarded. Quote these messages when the teacher "
            "asks what a student answered; chat outside a test is not included.",
            TranscriptArguments,
            authorize_transcripts,
            read_transcripts,
            replay_read=read_transcripts,
        ),
        "read_student_answers": ToolSpec(
            "read_student_answers",
            "Teacher",
            "Read each formal attempt's answer sheet in an activity, newest first: every "
            "Question with the student's exact answers, points and feedback, and when the "
            "attempt started and ended. Use learner_ref from the statistics for one student. "
            "Use it whenever the teacher asks what a student answered. Do not retype the "
            "answers or dates in your reply: the server writes the exact sheets under it. "
            "Name which attempt you mean by its start time.",
            TranscriptArguments,
            authorize_transcripts,
            read_answers,
            replay_read=read_answers,
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
        "list_course_reports": ToolSpec(
            "list_course_reports",
            "Teacher",
            "List the reports you saved in the current course, newest first. Use it when "
            "the teacher asks for an earlier report or its link. Do not write a download "
            "link, path or token in your reply: the server adds the real links under it.",
            CourseArguments,
            authorize_course,
            list_reports,
            replay_read=list_reports,
        ),
    }
