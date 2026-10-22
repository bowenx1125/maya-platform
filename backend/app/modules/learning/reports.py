"""Persisted teacher reports over current formal assessment attempts."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import PlatformError, conflict, idempotency_conflict, not_found, stale_revision
from app.core.models import Course, CourseMember, Group, GroupMember, User
from app.core.version_label import team_version_label
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import course_member_role
from app.modules.knowledge_sets.models import KnowledgeSet
from app.modules.teams.models import CourseTeamPublication, Team, TeamVersion, TeamVersionMember
from app.modules.workspace.models import Conversation

from .models import (
    AssessmentActivity,
    AssessmentActivityQuestion,
    AssessmentAttempt,
    AssessmentAttemptEvent,
    AssessmentAttemptQuestion,
    AssessmentCourseReport,
    AssessmentCourseReportEvidence,
    AssessmentCourseReportMutation,
    AssessmentCourseReportRevision,
    LearningRecord,
)
from .recipes import declared_recipe
from .schemas import (
    AssessmentActivityListItem,
    AssessmentActorReport,
    AssessmentCourseReportDTO,
    AssessmentCourseReportReceipt,
    AssessmentReportContent,
    AssessmentReportDownload,
    BoundarySummaryContent,
)
from .service import _canonical, _hash, _now


def _validated_activity(
    db: Session,
    actor: AuthContext,
    *,
    course_id: str,
    activity_id: str,
    allow_revoked: bool = False,
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
    if activity.team_id is None and (activity.team_name_snapshot or "").strip():
        return activity
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
            # Bug (2026-10-13): a Team's new version (an Agent republished, a
            # RAG edit, a Team edit) retains its old publication, and its
            # students' results vanished from every teacher read. A retained
            # version's results stay readable; only a revoked one is gone.
            # Owner request (2026-10-18): publishing V3 revoked V1/V2 and
            # hid their attempts from Record. Record reads them as revoked.
            CourseTeamPublication.state.in_(
                ("published", "retained", "revoked") if allow_revoked else ("published", "retained")
            ),
            CourseTeamPublication.publisher_user_id == activity.publisher_user_id,
            Team.id == activity.team_id,
            Team.course_id == course_id,
            Team.owner_user_id == activity.publisher_user_id,
            Team.ownership_scope == "personal",
            Team.visibility == "public",
            Team.deleted_at.is_(None),
            TeamVersion.id == activity.team_version_id,
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
    from app.modules.workspace.formal_assessment import resolve_formal_assessment

    roster = db.scalars(
        select(TeamVersionMember).where(
            TeamVersionMember.team_version_id == activity.team_version_id
        )
    ).all()
    try:
        roles = resolve_formal_assessment(
            recipe_version.agent_md,
            [(item.id, item.display_name) for item in roster],
        )
    except PlatformError:
        roles = None
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
        expected_member_id = None
        if roles is not None:
            expected_member_id = roles.scorer_id if role == "evaluator" else roles.summarizer_id
        if (
            bound_member is None
            or bound_member.team_version_id != activity.team_version_id
            or bound_member.agent_version_id != version_id
            or bound_version is None
            # Republishing the Agent supersedes the version this test used.
            or bound_version.state not in {"published", "superseded"}
            or expected_member_id != member_id
        ):
            raise not_found()
    return activity


_TEACHER_PHASES = frozenset(
    {"answering", "summary_not_saved", "scoring_not_saved", "paused", "completed"}
)


def _activity_label(db: Session, activity: AssessmentActivity, team_version: TeamVersion) -> str:
    """Team and Knowledge names, then the Team version.

    One title of ``Diagnostic assessment · V1.0`` hid which questionnaire a
    row belonged to. The version suffix still separates republished Teams.
    """

    names: list[str] = []
    for (name,) in db.execute(
        select(KnowledgeSet.display_name)
        .join(
            AssessmentActivityQuestion,
            AssessmentActivityQuestion.knowledge_set_id == KnowledgeSet.id,
        )
        .where(
            AssessmentActivityQuestion.activity_id == activity.id,
            AssessmentActivityQuestion.selection_revision == activity.question_selection_revision,
        )
        .order_by(AssessmentActivityQuestion.ordinal, KnowledgeSet.id)
    ).all():
        cleaned = str(name).strip()
        if cleaned and cleaned not in names:
            names.append(cleaned)
    version = team_version_label(team_version.version_seq)
    team = team_version.display_name.strip()
    if names:
        return f"{team} · {', '.join(names)} · {version}"
    return f"{team} · {version}"


def _require_course_teacher(db: Session, actor: AuthContext, course_id: str) -> None:
    if (
        actor.user.status != "active"
        or course_member_role(db, str(actor.user.id), course_id) != "teacher"
    ):
        raise not_found()


def _authorized_activities(
    db: Session,
    actor: AuthContext,
    *,
    course_id: str,
    include_revoked: bool = False,
) -> list[tuple[AssessmentActivityListItem, AssessmentActivity]]:
    """Each current published activity, validated once, with its list item."""

    _require_course_teacher(db, actor, course_id)
    rows = db.scalars(
        select(AssessmentActivity)
        .where(AssessmentActivity.course_id == course_id)
        .order_by(AssessmentActivity.created_at.desc(), AssessmentActivity.id)
    ).all()
    output: list[tuple[AssessmentActivityListItem, AssessmentActivity]] = []
    for row in rows:
        try:
            activity = _validated_activity(
                db,
                actor,
                course_id=course_id,
                activity_id=row.id,
                allow_revoked=include_revoked,
            )
        except PlatformError:
            continue
        team_version = (
            db.get(TeamVersion, activity.team_version_id) if activity.team_version_id else None
        )
        if team_version is not None:
            label = _activity_label(db, activity, team_version)
            team_name = team_version.display_name
        elif (activity.team_name_snapshot or "").strip():
            label = activity.team_name_snapshot.strip()
            team_name = label
        else:
            continue
        output.append(
            (
                AssessmentActivityListItem(
                    id=UUID(activity.id),
                    name=label,
                    team_name=team_name,
                    created_at=activity.created_at,
                ),
                activity,
            )
        )
    return output


def list_authorized_assessment_activities(
    db: Session,
    actor: AuthContext,
    *,
    course_id: str,
) -> list[AssessmentActivityListItem]:
    """List current published activities without reading or counting Private attempts."""

    return [item for item, _activity in _authorized_activities(db, actor, course_id=course_id)]


def _eligible_attempts(db: Session, activity: AssessmentActivity) -> list[AssessmentAttempt]:
    """Formal attempts whose answers still belong to this activity.

    A live chat must still be that activity's published Team chat. Deleting
    the chat clears ``source_conversation_id`` and the attempt stays. Deleting
    the Team clears the activity's team id; the attempt keeps the id it was
    taken against and the name stored on the activity.
    """

    conversation_is_this_activity = [
        Conversation.user_id == AssessmentAttempt.actor_user_id,
        Conversation.course_id == activity.course_id,
        Conversation.origin == "published_course_team",
        Conversation.entry_kind == "maya_team",
        Conversation.chat_visibility == AssessmentAttempt.chat_visibility,
    ]
    if activity.publication_id is not None:
        conversation_is_this_activity.append(Conversation.publication_id == activity.publication_id)
    if activity.team_id is not None:
        conversation_is_this_activity.append(Conversation.team_id == activity.team_id)
    if activity.team_version_id is not None:
        conversation_is_this_activity.append(
            Conversation.team_version_id == activity.team_version_id
        )
    team_match = (
        AssessmentAttempt.team_id == activity.team_id
        if activity.team_id is not None
        else AssessmentAttempt.team_id.is_not(None)
    )
    return list(
        db.scalars(
            select(AssessmentAttempt)
            .outerjoin(Conversation, Conversation.id == AssessmentAttempt.source_conversation_id)
            .join(
                CourseMember,
                (CourseMember.course_id == activity.course_id)
                & (CourseMember.user_id == AssessmentAttempt.actor_user_id),
            )
            .join(User, User.id == AssessmentAttempt.actor_user_id)
            .where(
                AssessmentAttempt.activity_id == activity.id,
                team_match,
                AssessmentAttempt.recipe_id == activity.recipe_id,
                or_(
                    AssessmentAttempt.source_conversation_id.is_(None),
                    and_(*conversation_is_this_activity),
                ),
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
            and record.chat_visibility == attempt.chat_visibility
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

    from .execution import _boundary_for_attempt, attempt_has_final_evidence

    # Each learner's newest completed attempt with intact final evidence speaks
    # for their current boundary; earlier attempts stay in the counts only.
    latest_boundaries: dict[str, tuple[str, str, BoundarySummaryContent]] = {}
    for attempt in attempts:
        boundary = _boundary_for_attempt(db, attempt) if attempt.status == "completed" else None
        if boundary is None:
            continue
        try:
            if not attempt_has_final_evidence(db, attempt):
                continue
            summary = BoundarySummaryContent.model_validate_json(boundary[1].content_json)
        except (PlatformError, ValueError):
            continue
        latest_boundaries[attempt.actor_user_id] = (attempt.id, boundary[1].id, summary)

    actor_rows: list[AssessmentActorReport] = []
    valid_record_ids = {record.id for record in valid_records}
    for actor_id, actor_attempt_list in sorted(actor_attempts.items()):
        questions_for_actor = actor_questions[actor_id]
        user = db.get(User, actor_id)
        latest = latest_boundaries.get(actor_id)
        boundary_content = latest[2] if latest is not None else None
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
                boundary_summary=boundary_content.summary if boundary_content else None,
                mastery_evidence=boundary_content.strengths if boundary_content else [],
                weak_points=boundary_content.areas_to_explore if boundary_content else [],
                not_yet_verified=boundary_content.not_yet_verified if boundary_content else [],
            )
        )
    course = db.get(Course, activity.course_id)
    team_version = db.get(TeamVersion, activity.team_version_id)
    if course is None or team_version is None:
        raise not_found()
    content = AssessmentReportContent(
        course_name=course.name,
        team_name=team_version.display_name,
        activity_name=_activity_label(db, activity, team_version),
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
        "boundaries": [
            {"attempt_id": attempt_id, "revision_id": revision_id}
            for attempt_id, revision_id, _summary in sorted(latest_boundaries.values())
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
    lines.extend(["", "## Knowledge boundaries"])
    for row in content.actors:
        lines.extend(["", f"### {row.student_name} ({row.learner_ref})", ""])
        if row.boundary_summary is None:
            lines.append("No completed diagnosis yet.")
            continue
        lines.extend([row.boundary_summary, ""])
        for label, items in (
            ("Mastery evidence", row.mastery_evidence),
            ("Weak points", row.weak_points),
            ("Not yet verified", row.not_yet_verified),
        ):
            lines.append(f"- {label}: {'; '.join(items) if items else 'None recorded.'}")
    return "\n".join(lines) + "\n"


def _cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|") or "—"


def attempt_teacher_phase(db: Session, attempt: AssessmentAttempt) -> str:
    """What a teacher should be told. A missing summary is not still answering."""

    if attempt.status != "in_progress":
        return attempt.status
    from app.modules.learning.attempts import awaits_follow_up_round
    from app.modules.learning.finalizer import _next_purpose

    if awaits_follow_up_round(db, attempt.id):
        return "answering"
    purpose = _next_purpose(db, attempt)
    if purpose == "boundary_summarize":
        return "summary_not_saved"
    if purpose == "assessment_evaluate":
        return "scoring_not_saved"
    return "answering"


def attempt_answer_sheet(db: Session, attempt: AssessmentAttempt) -> dict[str, Any]:
    """One attempt's Questions with the student's own words, points and feedback."""

    from app.modules.knowledge_sets.schemas import QuestionContent

    from .attempts import _attempt_question_rows, _raw_answers
    from .execution import _assessment_for_attempt

    user = db.get(User, attempt.actor_user_id)
    answers: dict[int, list[str]] = defaultdict(list)
    for answer in _raw_answers(db, attempt):
        answers[answer.question_ordinal].append(answer.answer_text)
    scores: dict[int, tuple[float | None, str]] = {}
    evaluation = _assessment_for_attempt(db, attempt)
    if evaluation is not None:
        for item in json.loads(evaluation[1].content_json).get("questions", []):
            scores[int(item["question_ordinal"])] = (
                item.get("points_awarded"),
                str(item.get("feedback") or ""),
            )
    rows = _attempt_question_rows(db, attempt.id)
    offset = rows[0].ordinal if rows else 0
    questions: list[dict[str, Any]] = []
    for row in rows:
        ordinal = row.ordinal - offset
        content = (
            QuestionContent.model_validate_json(row.content_json) if row.content_json else None
        )
        awarded, feedback = scores.get(ordinal, (None, ""))
        total = None
        if content is not None:
            total = content.rubric.total_points
            if total is None and content.rubric.criteria:
                total = sum(criterion.points for criterion in content.rubric.criteria)
        questions.append(
            {
                "number": ordinal + 1,
                "prompt": content.prompt.splitlines()[0] if content else "",
                "answers": answers.get(ordinal, []),
                "skipped": row.resolution == "skipped",
                "points_awarded": awarded,
                "points_total": total,
                "feedback": feedback,
            }
        )
    ended_at = attempt.completed_at or attempt.abandoned_at
    return {
        "attempt_id": attempt.id,
        "student_name": user.display_name if user is not None else "Student",
        "learner_ref": f"Learner-{_hash(attempt.actor_user_id)[:6].upper()}",
        "status": attempt.status,
        "phase": attempt_teacher_phase(db, attempt),
        "started_at": attempt.started_at.isoformat(),
        "ended_at": ended_at.isoformat() if ended_at is not None else None,
        "questions": questions,
    }


def render_answer_sheet(sheet: dict[str, Any]) -> str:
    """The answer sheet as a Markdown table, written by the server."""

    started = str(sheet.get("started_at") or "")[:16].replace("T", " ")
    phase = str(sheet.get("phase") or "")
    shown_status = {
        "summary_not_saved": "in_progress · summary not saved",
        "scoring_not_saved": "in_progress · scores not saved",
    }.get(phase, str(sheet.get("status")))
    lines = [
        f"**{sheet.get('student_name')} ({sheet.get('learner_ref')}) · "
        f"{started} · {shown_status}**",
        "",
        "| No. | Question | Answer | Points | Feedback |",
        "| ---: | --- | --- | ---: | --- |",
    ]
    for question in sheet.get("questions") or []:
        given = question.get("answers") or (
            ["(skipped)"] if question.get("skipped") else ["(not answered)"]
        )
        awarded = question.get("points_awarded")
        total = question.get("points_total")
        points = (
            "—"
            if awarded is None or total == 0
            else f"{awarded:g}" + (f"/{total:g}" if total is not None else "")
        )
        lines.append(
            f"| {question.get('number')} | {_cell(str(question.get('prompt') or ''))} | "
            f"{_cell(' / '.join(str(item) for item in given))} | {points} | "
            f"{_cell(str(question.get('feedback') or ''))} |"
        )
    return "\n".join(lines)


def read_student_answers(
    db: Session,
    actor: AuthContext,
    *,
    course_id: str,
    activity_id: str,
    learner_ref: str | None = None,
    include_abandoned: bool = False,
) -> list[dict[str, Any]]:
    """Each formal attempt's answer sheet, newest first.

    Bug (2026-10-13): retyping answers from raw transcripts, the teacher's
    Agent took an older attempt for the newest and invented a date. The
    server now hands over the exact sheet and writes it under the reply.
    """

    activity = _validated_activity(db, actor, course_id=course_id, activity_id=activity_id)
    sheets: list[dict[str, Any]] = []
    for attempt in sorted(
        _eligible_attempts(db, activity), key=lambda row: row.started_at, reverse=True
    ):
        ref = f"Learner-{_hash(attempt.actor_user_id)[:6].upper()}"
        if learner_ref is not None and learner_ref != ref:
            continue
        if attempt.status == "abandoned" and not include_abandoned:
            continue
        sheets.append(attempt_answer_sheet(db, attempt))
    return sheets


def _attempt_rows(
    db: Session,
    actor: AuthContext,
    *,
    course_id: str,
    group_of: Callable[[str], tuple[str | None, str | None] | None],
    wanted: Callable[[AssessmentAttempt], bool] | None = None,
) -> list[dict[str, Any]]:
    """Formal attempts, newest first, each with its sheet and its group.

    Bug (2026-10-17, #123): the course list re-ran every activity check and
    attempt query once per group, so Record took seconds to open. Each
    activity is now validated once and its attempts read once; ``group_of``
    places a student, and an attempt with no group is left out.
    """

    results: list[dict[str, Any]] = []
    for item, activity in _authorized_activities(
        db, actor, course_id=course_id, include_revoked=True
    ):
        report_path: str | None = None
        report_read = False
        publication = (
            db.get(CourseTeamPublication, activity.publication_id)
            if activity.publication_id
            else None
        )
        team_version = (
            db.get(TeamVersion, activity.team_version_id) if activity.team_version_id else None
        )
        for attempt in _eligible_attempts(db, activity):
            # A teacher's delete hides the attempt. Deleting the chat does not.
            if attempt.status == "abandoned" or attempt.teacher_hidden_at is not None:
                continue
            group = group_of(attempt.actor_user_id)
            if group is None or (wanted is not None and not wanted(attempt)):
                continue
            if not report_read:
                report_path = _latest_report_path(db, actor, activity_id=activity.id)
                report_read = True
            sheet = attempt_answer_sheet(db, attempt)
            if sheet["phase"] not in _TEACHER_PHASES:
                raise not_found()
            awarded = [
                question["points_awarded"]
                for question in sheet["questions"]
                if question["points_awarded"] is not None
            ]
            totals = [
                question["points_total"]
                for question in sheet["questions"]
                if question["points_total"] is not None
            ]
            results.append(
                {
                    "attempt_id": attempt.id,
                    "user_id": attempt.actor_user_id,
                    "student_name": sheet["student_name"],
                    "test_name": item.name,
                    "team_name": item.team_name,
                    "status": attempt.status,
                    "phase": sheet["phase"],
                    "conversation_id": attempt.source_conversation_id,
                    "group_id": group[0],
                    "group_name": group[1],
                    "started_at": attempt.started_at,
                    "ended_at": attempt.completed_at,
                    "points_awarded": sum(awarded) if awarded else None,
                    "points_total": sum(totals) if totals else None,
                    "questions": sheet["questions"],
                    "report_download_path": report_path,
                    "publication_state": publication.state if publication else None,
                    "version_label": (
                        team_version_label(team_version.version_seq) if team_version else None
                    ),
                }
            )
    results.sort(key=lambda row: row["started_at"], reverse=True)
    return results


def read_group_results(
    db: Session,
    actor: AuthContext,
    *,
    course_id: str,
    user_ids: set[str],
    group_id: str | None = None,
    group_name: str | None = None,
) -> list[dict[str, Any]]:
    """Each formal attempt by these students, newest first, with its sheet.

    The same activities, eligibility and answer sheets the teacher's tools
    read, narrowed to one group's members. Abandoned attempts are left out,
    and each carries the teacher's latest course report for its test.
    """

    return _attempt_rows(
        db,
        actor,
        course_id=course_id,
        group_of=lambda user_id: (group_id, group_name) if user_id in user_ids else None,
    )


def list_course_assessment_attempts(
    db: Session,
    actor: AuthContext,
    *,
    course_id: str,
    group_id: str | None = None,
    attempt_id: str | None = None,
    conversation_id: str | None = None,
) -> list[dict[str, Any]]:
    """Formal attempts in a course, without the teacher entering a group.

    A conversation or attempt id that is not one of these attempts is not
    found. The same rule hides a group outside the course. A student in
    several groups is listed under the first by name.
    """

    _require_course_teacher(db, actor, course_id)
    groups = list(
        db.scalars(
            select(Group).where(Group.course_id == course_id).order_by(Group.name, Group.id)
        ).all()
    )
    if group_id is not None:
        groups = [group for group in groups if group.id == group_id]
        if not groups:
            raise not_found()
    order = {group.id: index for index, group in enumerate(groups)}
    placed: dict[str, tuple[str | None, str | None]] = {}
    if groups:
        memberships = db.execute(
            select(GroupMember.user_id, GroupMember.group_id).where(
                GroupMember.group_id.in_(list(order))
            )
        ).all()
        by_id = {group.id: group for group in groups}
        for user_id, member_group_id in sorted(memberships, key=lambda row: order[row[1]]):
            if user_id not in placed:
                group = by_id[member_group_id]
                placed[user_id] = (group.id, group.name)

    def wanted(attempt: AssessmentAttempt) -> bool:
        # A single sheet is asked for: build no other sheet.
        return (attempt_id is None or attempt.id == attempt_id) and (
            conversation_id is None or attempt.source_conversation_id == conversation_id
        )

    rows = _attempt_rows(db, actor, course_id=course_id, group_of=placed.get, wanted=wanted)
    if (attempt_id is not None or conversation_id is not None) and not rows:
        raise not_found()
    return rows


def list_my_assessment_attempts(
    db: Session,
    actor: AuthContext,
    *,
    course_id: str,
) -> list[dict[str, Any]]:
    """The signed-in student's own formal attempts in a course, newest first.

    Owner request (2026-10-18): the student's Brainform shows Record, like
    the teacher's, listing the assessment Teams the student took. Every row
    is read by ``actor_user_id`` from the session, so no request can name
    another student. Abandoned attempts stay out; a deleted chat does not hide its attempt. A
    revoked or superseded publication does not hide a student's own answers.
    Scores and feedback stay with the teacher.
    """

    if (
        actor.user.status != "active"
        or course_member_role(db, str(actor.user.id), course_id) is None
    ):
        raise not_found()
    own_id = str(actor.user.id)
    attempts = db.scalars(
        select(AssessmentAttempt)
        .join(AssessmentActivity, AssessmentActivity.id == AssessmentAttempt.activity_id)
        .outerjoin(Conversation, Conversation.id == AssessmentAttempt.source_conversation_id)
        .where(
            AssessmentAttempt.actor_user_id == own_id,
            # A teacher's Record delete hides the attempt here too.
            AssessmentAttempt.teacher_hidden_at.is_(None),
            AssessmentAttempt.status.in_(("in_progress", "paused", "completed")),
            AssessmentActivity.course_id == course_id,
            # A deleted Chat keeps its attempt in Record (owner, 2026-10-20).
            or_(
                AssessmentAttempt.source_conversation_id.is_(None),
                and_(Conversation.user_id == own_id, Conversation.course_id == course_id),
            ),
        )
        .order_by(AssessmentAttempt.started_at.desc(), AssessmentAttempt.id)
    ).all()
    group = db.execute(
        select(Group.id, Group.name)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(Group.course_id == course_id, GroupMember.user_id == own_id)
        .order_by(Group.name, Group.id)
        .limit(1)
    ).first()
    results: list[dict[str, Any]] = []
    for attempt in attempts:
        activity = db.get(AssessmentActivity, attempt.activity_id)
        team_version = (
            db.get(TeamVersion, activity.team_version_id)
            if activity is not None and activity.team_version_id
            else None
        )
        if activity is None or (
            team_version is None and not (activity.team_name_snapshot or "").strip()
        ):
            continue
        sheet = attempt_answer_sheet(db, attempt)
        if sheet["phase"] not in _TEACHER_PHASES:
            continue
        team_name = (
            team_version.display_name
            if team_version is not None
            else activity.team_name_snapshot.strip()
        )
        test_name = (
            _activity_label(db, activity, team_version) if team_version is not None else team_name
        )
        results.append(
            {
                "attempt_id": attempt.id,
                "user_id": attempt.actor_user_id,
                "student_name": sheet["student_name"],
                "test_name": test_name,
                "team_name": team_name,
                "status": attempt.status,
                "phase": sheet["phase"],
                "conversation_id": attempt.source_conversation_id,
                "group_id": group[0] if group else None,
                "group_name": group[1] if group else None,
                "started_at": attempt.started_at,
                "ended_at": attempt.completed_at,
                "points_awarded": None,
                "points_total": None,
                "questions": [
                    {**question, "points_awarded": None, "points_total": None, "feedback": ""}
                    for question in sheet["questions"]
                ],
                "report_download_path": None,
            }
        )
    return results


def hide_course_assessment_attempt(
    db: Session,
    actor: AuthContext,
    *,
    course_id: str,
    attempt_id: str,
) -> None:
    """A course teacher deletes an attempt from Record: a soft delete.

    Owner request (2026-10-18). Only the attempt is marked; its answers,
    chat, ledger and learning records stay, so it can be restored. Only a
    teacher of the attempt's course, on a student of that course, may do it.
    Repeating the delete changes nothing.
    """

    _require_course_teacher(db, actor, course_id)
    attempt = db.get(AssessmentAttempt, attempt_id)
    activity = db.get(AssessmentActivity, attempt.activity_id) if attempt else None
    if (
        attempt is None
        or activity is None
        or activity.course_id != course_id
        or course_member_role(db, attempt.actor_user_id, course_id) != "student"
    ):
        raise not_found()
    if attempt.teacher_hidden_at is None:
        db.execute(
            update(AssessmentAttempt)
            .where(
                AssessmentAttempt.id == attempt.id,
                AssessmentAttempt.teacher_hidden_at.is_(None),
            )
            .values(teacher_hidden_at=_now(), teacher_hidden_by_user_id=str(actor.user.id))
        )
        db.commit()


def _latest_report_path(db: Session, actor: AuthContext, *, activity_id: str) -> str | None:
    report = db.scalar(
        select(AssessmentCourseReport)
        .where(
            AssessmentCourseReport.activity_id == activity_id,
            AssessmentCourseReport.owner_user_id == actor.user.id,
        )
        .order_by(AssessmentCourseReport.updated_at.desc(), AssessmentCourseReport.id)
        .limit(1)
    )
    if report is None:
        return None
    revision = db.scalar(
        select(AssessmentCourseReportRevision).where(
            AssessmentCourseReportRevision.report_id == report.id,
            AssessmentCourseReportRevision.revision_seq == report.current_revision_seq,
        )
    )
    if revision is None:
        return None
    return f"/api/v1/learning/reports/{report.id}/download?revision_id={revision.id}"


def _raw_answer_markdown(db: Session, attempts: list[AssessmentAttempt]) -> str:
    """Each attempt's raw answers for the downloaded report.

    Owner request (2026-10-13): the report keeps the raw answers, not only the
    summaries. It reads the same eligible attempts the report counted.
    """

    lines = ["", "## Raw answers"]
    if not attempts:
        lines.extend(["", "No attempt yet."])
    for attempt in sorted(
        attempts, key=lambda item: (item.actor_user_id, item.started_at, item.id)
    ):
        lines.extend(["", render_answer_sheet(attempt_answer_sheet(db, attempt))])
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
    attempts, _content, source_hash = _build_snapshot(db, activity)
    if source_hash != revision.source_hash:
        raise conflict(
            "assessment_report_stale",
            "The eligible assessment evidence changed. Generate a new report revision "
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
        content=_report_markdown(content) + _raw_answer_markdown(db, attempts),
    )


__all__ = [
    "create_assessment_course_report",
    "download_assessment_course_report",
    "list_authorized_assessment_activities",
    "hide_course_assessment_attempt",
    "list_course_assessment_attempts",
    "list_my_assessment_attempts",
    "read_assessment_activity_aggregate",
]


def read_attempt_transcripts(
    db: Session,
    actor: AuthContext,
    *,
    course_id: str,
    activity_id: str,
    learner_ref: str | None = None,
    include_abandoned: bool = False,
) -> list[dict[str, object]]:
    """The raw messages of each formal attempt, from its start to its end.

    Owner decision (2026-10-12): the course teacher may read the whole test
    window of a student's formal attempt, Private Chats included. Messages
    before the start or after the end are ordinary chat and stay out.
    """

    from app.modules.workspace.models import (
        ConversationParticipant,
        ConversationTurn,
        TeamTurnResult,
    )

    activity = _validated_activity(db, actor, course_id=course_id, activity_id=activity_id)
    transcripts: list[dict[str, object]] = []
    # Newest first, each attempt on its own: blending an abandoned run into the
    # finished one put messages in a student's record they never sent there.
    attempts = sorted(
        _eligible_attempts(db, activity), key=lambda row: row.started_at, reverse=True
    )
    for attempt in attempts:
        ref = f"Learner-{_hash(attempt.actor_user_id)[:6].upper()}"
        if learner_ref is not None and learner_ref != ref:
            continue
        if attempt.status == "abandoned" and not include_abandoned:
            continue
        user = db.get(User, attempt.actor_user_id)
        ended_at = attempt.completed_at or attempt.abandoned_at
        statement = select(ConversationTurn).where(
            ConversationTurn.conversation_id == attempt.source_conversation_id,
            ConversationTurn.created_at >= attempt.started_at,
        )
        if ended_at is not None:
            statement = statement.where(ConversationTurn.created_at <= ended_at)
        messages: list[dict[str, str]] = []
        for turn in db.scalars(statement.order_by(ConversationTurn.position)):
            if turn.user_text:
                messages.append({"speaker": "student", "text": turn.user_text})
            for result, participant in db.execute(
                select(TeamTurnResult, ConversationParticipant)
                .join(
                    ConversationParticipant,
                    ConversationParticipant.id == TeamTurnResult.participant_id,
                )
                .where(TeamTurnResult.turn_id == turn.id, TeamTurnResult.state == "ready")
                .order_by(TeamTurnResult.ordinal)
            ):
                if result.assistant_text:
                    messages.append(
                        {"speaker": participant.display_name, "text": result.assistant_text}
                    )
        transcripts.append(
            {
                "attempt_id": attempt.id,
                "student_name": user.display_name if user is not None else "Student",
                "learner_ref": ref,
                "attempt_status": attempt.status,
                "chat_visibility": attempt.chat_visibility,
                "started_at": attempt.started_at.isoformat(),
                "ended_at": ended_at.isoformat() if ended_at is not None else None,
                "messages": messages,
            }
        )
    return transcripts
