"""Persisted teacher reports over current Public formal assessment attempts."""

from __future__ import annotations

import re
from collections import defaultdict
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import PlatformError, conflict, idempotency_conflict, not_found, stale_revision
from app.core.models import Course, CourseMember, User
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import course_member_role
from app.modules.teams.models import CourseTeamPublication, Team, TeamVersion, TeamVersionMember
from app.modules.workspace.models import Conversation

from .models import (
    AssessmentActivity,
    AssessmentAttempt,
    AssessmentAttemptEvent,
    AssessmentAttemptQuestion,
    AssessmentCourseReport,
    AssessmentCourseReportEvidence,
    AssessmentCourseReportMutation,
    AssessmentCourseReportRevision,
    LearningRecord,
)
from .recipes import declared_assessment_role, declared_recipe
from .schemas import (
    AssessmentActivityListItem,
    AssessmentActorReport,
    AssessmentCourseReportDTO,
    AssessmentCourseReportReceipt,
    AssessmentReportContent,
    AssessmentReportDownload,
)
from .service import _canonical, _hash, _now


def _validated_activity(
    db: Session,
    actor: AuthContext,
    *,
    course_id: str,
    activity_id: str,
) -> AssessmentActivity:
    if (
        actor.user.status != "active"
        or course_member_role(db, str(actor.user.id), course_id) != "teacher"
    ):
        raise not_found()
    activity = db.scalar(
        select(AssessmentActivity).where(
            AssessmentActivity.id == activity_id,
            AssessmentActivity.course_id == course_id,
        )
    )
    if activity is None:
        raise not_found()
    publication, team, version = db.execute(
        select(CourseTeamPublication, Team, TeamVersion)
        .join(Team, Team.id == CourseTeamPublication.team_id)
        .join(
            TeamVersion,
            (TeamVersion.id == CourseTeamPublication.team_version_id)
            & (TeamVersion.team_id == CourseTeamPublication.team_id),
        )
        .where(
            CourseTeamPublication.id == activity.publication_id,
            CourseTeamPublication.course_id == course_id,
            CourseTeamPublication.team_id == activity.team_id,
            CourseTeamPublication.team_version_id == activity.team_version_id,
            CourseTeamPublication.state == "published",
            CourseTeamPublication.publisher_user_id == activity.publisher_user_id,
            CourseTeamPublication.authorization_epoch == Team.authorization_epoch,
            Team.id == activity.team_id,
            Team.course_id == course_id,
            Team.owner_user_id == activity.publisher_user_id,
            Team.ownership_scope == "personal",
            Team.visibility == "public",
            Team.deleted_at.is_(None),
            Team.current_version_seq == TeamVersion.version_seq,
            TeamVersion.id == activity.team_version_id,
            TeamVersion.authorization_epoch == Team.authorization_epoch,
        )
    ).first() or (None, None, None)
    if publication is None or team is None or version is None:
        raise not_found()
    if course_member_role(db, activity.publisher_user_id, course_id) != "teacher":
        raise not_found()
    leader = db.scalar(
        select(TeamVersionMember).where(
            TeamVersionMember.team_version_id == version.id,
            TeamVersionMember.is_leader.is_(True),
        )
    )
    if leader is None or leader.agent_version_id != activity.recipe_version_id:
        raise not_found()
    from app.core.models import AgentVersion

    recipe_version = db.get(AgentVersion, activity.recipe_version_id)
    if recipe_version is None or declared_recipe(recipe_version.agent_md) != activity.recipe_id:
        raise not_found()
    for role, member_id, version_id in (
        ("evaluator", activity.evaluator_team_member_id, activity.evaluator_agent_version_id),
        (
            "boundary_summarizer",
            activity.boundary_team_member_id,
            activity.boundary_agent_version_id,
        ),
    ):
        bound_member = db.get(TeamVersionMember, member_id)
        bound_version = db.get(AgentVersion, version_id)
        if (
            bound_member is None
            or bound_member.team_version_id != activity.team_version_id
            or bound_member.agent_version_id != version_id
            or bound_version is None
            or bound_version.state != "published"
            or declared_assessment_role(bound_version.agent_md) != role
        ):
            raise not_found()
    return activity


def list_authorized_assessment_activities(
    db: Session,
    actor: AuthContext,
    *,
    course_id: str,
) -> list[AssessmentActivityListItem]:
    """List current published activities without reading or counting Private attempts."""

    if (
        actor.user.status != "active"
        or course_member_role(db, str(actor.user.id), course_id) != "teacher"
    ):
        raise not_found()
    rows = db.scalars(
        select(AssessmentActivity)
        .where(AssessmentActivity.course_id == course_id)
        .order_by(AssessmentActivity.created_at.desc(), AssessmentActivity.id)
    ).all()
    output: list[AssessmentActivityListItem] = []
    for activity in rows:
        try:
            _validated_activity(
                db,
                actor,
                course_id=course_id,
                activity_id=activity.id,
            )
        except PlatformError:
            continue
        team_version = db.get(TeamVersion, activity.team_version_id)
        if team_version is not None:
            output.append(
                AssessmentActivityListItem(
                    id=UUID(activity.id),
                    name="Diagnostic assessment",
                    team_name=team_version.display_name,
                    created_at=activity.created_at,
                )
            )
    return output


def _eligible_attempts(db: Session, activity: AssessmentActivity) -> list[AssessmentAttempt]:
    return list(
        db.scalars(
            select(AssessmentAttempt)
            .join(Conversation, Conversation.id == AssessmentAttempt.source_conversation_id)
            .join(
                CourseMember,
                (CourseMember.course_id == activity.course_id)
                & (CourseMember.user_id == AssessmentAttempt.actor_user_id),
            )
            .join(User, User.id == AssessmentAttempt.actor_user_id)
            .where(
                AssessmentAttempt.activity_id == activity.id,
                AssessmentAttempt.team_id == activity.team_id,
                AssessmentAttempt.recipe_id == activity.recipe_id,
                AssessmentAttempt.chat_visibility == "public",
                Conversation.user_id == AssessmentAttempt.actor_user_id,
                Conversation.course_id == activity.course_id,
                Conversation.origin == "published_course_team",
                Conversation.entry_kind == "maya_team",
                Conversation.chat_visibility == "public",
                Conversation.publication_id == activity.publication_id,
                Conversation.team_id == activity.team_id,
                Conversation.team_version_id == activity.team_version_id,
                Conversation.withdrawn_at.is_(None),
                CourseMember.course_id == activity.course_id,
                CourseMember.user_id == AssessmentAttempt.actor_user_id,
                CourseMember.role == "student",
                User.status == "active",
            )
            .order_by(AssessmentAttempt.started_at, AssessmentAttempt.id)
        ).all()
    )


def _build_snapshot(
    db: Session,
    activity: AssessmentActivity,
) -> tuple[list[AssessmentAttempt], AssessmentReportContent, str]:
    attempts = _eligible_attempts(db, activity)
    attempt_ids = [attempt.id for attempt in attempts]
    records = (
        db.scalars(select(LearningRecord).where(LearningRecord.attempt_id.in_(attempt_ids))).all()
        if attempt_ids
        else []
    )
    attempts_by_id = {attempt.id: attempt for attempt in attempts}
    record_ids = [record.id for record in records]
    evidence_events = (
        db.scalars(
            select(AssessmentAttemptEvent).where(
                AssessmentAttemptEvent.learning_record_id.in_(record_ids)
            )
        ).all()
        if record_ids
        else []
    )
    events_by_record = {event.learning_record_id: event for event in evidence_events}
    from .attempts import _attempt_question_rows

    questions = [
        question for attempt in attempts for question in _attempt_question_rows(db, attempt.id)
    ]
    questions_by_id = {question.id: question for question in questions}
    valid_records: list[LearningRecord] = []
    valid_question_records: dict[str, set[str]] = defaultdict(set)
    for record in records:
        attempt = attempts_by_id.get(record.attempt_id or "")
        event = events_by_record.get(record.id)
        question = questions_by_id.get(event.question_id or "") if event is not None else None
        if (
            attempt is not None
            and event is not None
            and question is not None
            and record.actor_user_id == attempt.actor_user_id
            and record.course_id == activity.course_id
            and record.conversation_id == attempt.source_conversation_id
            and record.team_id == activity.team_id
            and record.team_version_id == activity.team_version_id
            and record.origin == "published_course_team"
            and record.chat_visibility == "public"
            and record.activity_id == activity.id
            and event.attempt_id == attempt.id
            and event.activity_id == activity.id
            and event.actor_user_id == attempt.actor_user_id
            and event.event_kind == record.record_kind
            and question.attempt_id == attempt.id
        ):
            valid_records.append(record)
            valid_question_records[question.id].add(record.record_kind)
    actor_attempts: dict[str, list[AssessmentAttempt]] = defaultdict(list)
    for attempt in attempts:
        actor_attempts[attempt.actor_user_id].append(attempt)
    actor_records: dict[str, list[LearningRecord]] = defaultdict(list)
    for record in valid_records:
        if record.record_kind == "answer":
            actor_records[record.actor_user_id].append(record)
    actor_questions: dict[str, list[AssessmentAttemptQuestion]] = defaultdict(list)
    attempt_actor = {attempt.id: attempt.actor_user_id for attempt in attempts}
    for question in questions:
        actor_id = attempt_actor.get(question.attempt_id)
        if actor_id is not None:
            actor_questions[actor_id].append(question)

    actor_rows: list[AssessmentActorReport] = []
    valid_record_ids = {record.id for record in valid_records}
    for actor_id, actor_attempt_list in sorted(actor_attempts.items()):
        questions_for_actor = actor_questions[actor_id]
        user = db.get(User, actor_id)
        actor_rows.append(
            AssessmentActorReport(
                student_name=user.display_name if user is not None else "Student",
                learner_ref=f"Learner-{_hash(actor_id)[:6].upper()}",
                attempt_count=len(actor_attempt_list),
                completed_count=sum(row.status == "completed" for row in actor_attempt_list),
                abandoned_count=sum(row.status == "abandoned" for row in actor_attempt_list),
                in_progress_count=sum(row.status == "in_progress" for row in actor_attempt_list),
                paused_count=sum(row.status == "paused" for row in actor_attempt_list),
                effective_answer_count=sum(
                    row.resolution == "answered"
                    and row.effective_answer_record_id in valid_record_ids
                    for row in questions_for_actor
                ),
                raw_answer_count=len(actor_records[actor_id]),
                skipped_count=sum(
                    row.resolution == "skipped"
                    and "skip" in valid_question_records.get(row.id, set())
                    for row in questions_for_actor
                ),
            )
        )
    course = db.get(Course, activity.course_id)
    team_version = db.get(TeamVersion, activity.team_version_id)
    if course is None or team_version is None:
        raise not_found()
    content = AssessmentReportContent(
        course_name=course.name,
        team_name=team_version.display_name,
        activity_name="Diagnostic assessment",
        generated_at=_now(),
        student_count=len(actor_attempts),
        attempt_count=len(attempts),
        completed_count=sum(row.status == "completed" for row in attempts),
        abandoned_count=sum(row.status == "abandoned" for row in attempts),
        in_progress_count=sum(row.status == "in_progress" for row in attempts),
        paused_count=sum(row.status == "paused" for row in attempts),
        effective_answer_count=sum(
            row.resolution == "answered" and row.effective_answer_record_id in valid_record_ids
            for row in questions
        ),
        raw_answer_count=sum(record.record_kind == "answer" for record in valid_records),
        skipped_count=sum(
            row.resolution == "skipped" and "skip" in valid_question_records.get(row.id, set())
            for row in questions
        ),
        actors=actor_rows,
    )
    source_manifest = {
        "activity_id": activity.id,
        "publication_id": activity.publication_id,
        "attempts": [
            {
                "id": row.id,
                "actor_user_id": row.actor_user_id,
                "status": row.status,
                "revision": row.revision,
                "question_selection_revision": row.question_selection_revision,
                "chat_visibility": row.chat_visibility,
                "source_conversation_id": row.source_conversation_id,
            }
            for row in attempts
        ],
        "questions": [
            {
                "id": row.id,
                "attempt_id": row.attempt_id,
                "status": row.status,
                "resolution": row.resolution,
                "effective_answer_record_id": row.effective_answer_record_id,
            }
            for row in sorted(questions, key=lambda item: (item.attempt_id, item.ordinal, item.id))
        ],
        "answer_records": [
            {"id": row.id, "attempt_id": row.attempt_id, "payload_hash": row.payload_hash}
            for row in sorted(
                valid_records, key=lambda item: (item.attempt_id or "", item.created_at, item.id)
            )
            if row.record_kind == "answer"
        ],
    }
    source_hash = _hash(_canonical(source_manifest))
    return attempts, content, source_hash


def read_assessment_activity_aggregate(
    db: Session,
    actor: AuthContext,
    *,
    course_id: str,
    activity_id: str,
) -> AssessmentReportContent:
    activity = _validated_activity(db, actor, course_id=course_id, activity_id=activity_id)
    _attempts, content, _source_hash = _build_snapshot(db, activity)
    return content


def _report_dto(
    report: AssessmentCourseReport,
    revision: AssessmentCourseReportRevision,
) -> AssessmentCourseReportDTO:
    return AssessmentCourseReportDTO(
        id=UUID(report.id),
        course_id=UUID(report.course_id),
        activity_id=UUID(report.activity_id),
        revision_id=UUID(revision.id),
        revision_seq=revision.revision_seq,
        source_hash=revision.source_hash,
        content=AssessmentReportContent.model_validate_json(revision.report_json),
        created_at=revision.created_at,
    )


def create_assessment_course_report(
    db: Session,
    actor: AuthContext,
    *,
    course_id: str,
    activity_id: str,
    client_event_id: str | UUID,
) -> AssessmentCourseReportReceipt:
    """Persist one idempotent teacher report revision over eligible source evidence."""

    activity = _validated_activity(db, actor, course_id=course_id, activity_id=activity_id)
    request_hash = _hash(
        _canonical(
            {
                "operation": "create_assessment_course_report",
                "course_id": course_id,
                "activity_id": activity_id,
            }
        )
    )
    event_id = str(client_event_id)
    mutation = db.scalar(
        select(AssessmentCourseReportMutation).where(
            AssessmentCourseReportMutation.actor_user_id == str(actor.user.id),
            AssessmentCourseReportMutation.client_event_id == event_id,
        )
    )
    if mutation is not None:
        if mutation.request_hash != request_hash:
            raise idempotency_conflict()
        report = db.get(AssessmentCourseReport, mutation.report_id)
        revision = db.get(AssessmentCourseReportRevision, mutation.revision_id)
        if report is None or revision is None:
            raise conflict("assessment_report_state_invalid", "The saved report is unavailable.")
        return AssessmentCourseReportReceipt(report=_report_dto(report, revision))

    attempts, content, source_hash = _build_snapshot(db, activity)
    report = db.scalar(
        select(AssessmentCourseReport).where(
            AssessmentCourseReport.course_id == course_id,
            AssessmentCourseReport.activity_id == activity.id,
        )
    )
    timestamp = _now()
    if report is None:
        report = AssessmentCourseReport(
            id=str(uuid4()),
            course_id=course_id,
            activity_id=activity.id,
            owner_user_id=str(actor.user.id),
            current_revision_seq=1,
            created_at=timestamp,
            updated_at=timestamp,
        )
        next_seq = 1
    else:
        previous_seq = report.current_revision_seq
        next_seq = previous_seq + 1
        changed = db.execute(
            update(AssessmentCourseReport)
            .where(
                AssessmentCourseReport.id == report.id,
                AssessmentCourseReport.current_revision_seq == previous_seq,
            )
            .values(current_revision_seq=next_seq, updated_at=timestamp)
            .execution_options(synchronize_session=False)
        )
        if getattr(changed, "rowcount", 0) != 1:
            raise stale_revision(
                db.scalar(
                    select(AssessmentCourseReport.current_revision_seq).where(
                        AssessmentCourseReport.id == report.id
                    )
                )
            )
        report.current_revision_seq = next_seq
        report.updated_at = timestamp
    revision = AssessmentCourseReportRevision(
        id=str(uuid4()),
        report_id=report.id,
        course_id=course_id,
        activity_id=activity.id,
        revision_seq=next_seq,
        actor_user_id=str(actor.user.id),
        client_event_id=event_id,
        request_hash=request_hash,
        source_hash=source_hash,
        report_json=content.model_dump_json(),
        created_at=timestamp,
    )
    try:
        with db.begin_nested():
            db.add(report)
            db.add(revision)
            db.flush()
            for attempt in attempts:
                db.add(
                    AssessmentCourseReportEvidence(
                        report_revision_id=revision.id,
                        attempt_id=attempt.id,
                        created_at=timestamp,
                    )
                )
            db.add(
                AssessmentCourseReportMutation(
                    id=str(uuid4()),
                    actor_user_id=str(actor.user.id),
                    client_event_id=event_id,
                    request_hash=request_hash,
                    report_id=report.id,
                    revision_id=revision.id,
                    created_at=timestamp,
                )
            )
            db.flush()
    except IntegrityError:
        replay = db.scalar(
            select(AssessmentCourseReportMutation).where(
                AssessmentCourseReportMutation.actor_user_id == str(actor.user.id),
                AssessmentCourseReportMutation.client_event_id == event_id,
            )
        )
        if replay is None or replay.request_hash != request_hash:
            raise idempotency_conflict() from None
        saved_report = db.get(AssessmentCourseReport, replay.report_id)
        saved_revision = db.get(AssessmentCourseReportRevision, replay.revision_id)
        if saved_report is None or saved_revision is None:
            raise conflict(
                "assessment_report_state_invalid", "The saved report is unavailable."
            ) from None
        return AssessmentCourseReportReceipt(report=_report_dto(saved_report, saved_revision))
    db.refresh(report)
    db.refresh(revision)
    return AssessmentCourseReportReceipt(report=_report_dto(report, revision))


def _report_markdown(report: AssessmentCourseReportDTO) -> str:
    content = report.content
    lines = [
        f"# {content.activity_name}",
        "",
        f"Course: {content.course_name}",
        f"Team: {content.team_name}",
        f"Report generated: {content.generated_at.isoformat()}",
        f"Report version: {report.revision_seq}",
        "",
        "## Course totals",
        "",
        "| Measure | Count |",
        "| --- | ---: |",
        f"| Students | {content.student_count} |",
        f"| Attempts | {content.attempt_count} |",
        f"| Completed | {content.completed_count} |",
        f"| Abandoned | {content.abandoned_count} |",
        f"| In progress | {content.in_progress_count} |",
        f"| Paused | {content.paused_count} |",
        f"| Effective answers | {content.effective_answer_count} |",
        f"| Raw answer records | {content.raw_answer_count} |",
        f"| Skipped questions | {content.skipped_count} |",
        "",
        "## Learner participation",
        "",
        "| Student | Attempts | Completed | Abandoned | In progress | Paused | Effective | "
        "Raw answers | Skipped |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in content.actors:
        lines.append(
            f"| {row.student_name} ({row.learner_ref}) | {row.attempt_count} | "
            f"{row.completed_count} | "
            f"{row.abandoned_count} | {row.in_progress_count} | {row.paused_count} | "
            f"{row.effective_answer_count} | {row.raw_answer_count} | {row.skipped_count} |"
        )
    return "\n".join(lines) + "\n"


def download_assessment_course_report(
    db: Session,
    actor: AuthContext,
    *,
    report_id: str,
    revision_id: str | None = None,
) -> AssessmentReportDownload:
    """Recheck current course publication and evidence before returning report bytes."""

    report = db.get(AssessmentCourseReport, report_id)
    if report is None:
        raise not_found()
    activity = _validated_activity(
        db,
        actor,
        course_id=report.course_id,
        activity_id=report.activity_id,
    )
    revision = (
        db.get(AssessmentCourseReportRevision, revision_id)
        if revision_id is not None
        else db.scalar(
            select(AssessmentCourseReportRevision).where(
                AssessmentCourseReportRevision.report_id == report.id,
                AssessmentCourseReportRevision.revision_seq == report.current_revision_seq,
            )
        )
    )
    if revision is None or revision.report_id != report.id:
        raise not_found()
    _attempts, _content, source_hash = _build_snapshot(db, activity)
    if source_hash != revision.source_hash:
        raise conflict(
            "assessment_report_stale",
            "The eligible Public assessment evidence changed. Generate a new report revision "
            "before downloading.",
        )
    content = AssessmentCourseReportDTO(
        id=UUID(report.id),
        course_id=UUID(report.course_id),
        activity_id=UUID(report.activity_id),
        revision_id=UUID(revision.id),
        revision_seq=revision.revision_seq,
        source_hash=revision.source_hash,
        content=AssessmentReportContent.model_validate_json(revision.report_json),
        created_at=revision.created_at,
    )
    slug = (
        "-".join(
            part
            for part in re.sub(r"[^\w-]+", "-", content.content.team_name.lower()).split("-")
            if part
        )[:64]
        or "activity"
    )
    return AssessmentReportDownload(
        filename=f"assessment-report-{slug}-r{revision.revision_seq}.md",
        content_type="text/markdown; charset=utf-8",
        content=_report_markdown(content),
    )


__all__ = [
    "create_assessment_course_report",
    "download_assessment_course_report",
    "list_authorized_assessment_activities",
    "read_assessment_activity_aggregate",
]
