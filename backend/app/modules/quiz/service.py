"""Classroom Quiz persistence, publish gates, submit + objective grading."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.core.errors import conflict, forbidden, not_found, unprocessable
from app.core.models import Group, User
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import course_member_role
from app.modules.workspace.access import course_member
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .document import (
    assert_no_answer_keys,
    build_document_dict,
    content_hash_for,
    dumps_document,
    loads_document,
    settings_from_document,
    strip_answers,
    teacher_items_from_document,
)
from .grading import grade_objective
from .models import ClassroomQuiz, ClassroomQuizAttempt
from .schemas import (
    CreateQuizRequest,
    PatchQuizRequest,
    QuizAttemptDTO,
    QuizSettings,
    QuizSummaryDTO,
    RecordAttemptDTO,
    StudentQuizDTO,
    SubmitQuizAttemptRequest,
    TeacherQuizDTO,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _require_member(db: Session, actor: AuthContext, course_id: str) -> str:
    role = course_member_role(db, str(actor.user.id), course_id)
    if role is None or actor.user.status != "active":
        raise not_found()
    return role


def _require_teacher(db: Session, actor: AuthContext, course_id: str) -> None:
    course_member(db, actor, course_id, teacher=True)


def _get_quiz(db: Session, course_id: str, quiz_id: str) -> ClassroomQuiz:
    quiz = db.get(ClassroomQuiz, quiz_id)
    if quiz is None or quiz.course_id != course_id:
        raise not_found()
    return quiz


def _attempt_count(db: Session, quiz_id: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(ClassroomQuizAttempt)
            .where(
                ClassroomQuizAttempt.quiz_id == quiz_id,
                ClassroomQuizAttempt.teacher_hidden_at.is_(None),
            )
        )
        or 0
    )


def _summary(db: Session, quiz: ClassroomQuiz) -> QuizSummaryDTO:
    return QuizSummaryDTO(
        id=UUID(quiz.id),
        course_id=UUID(quiz.course_id),
        group_id=UUID(quiz.group_id) if quiz.group_id else None,
        title=quiz.title,
        status=quiz.status,  # type: ignore[arg-type]
        schema_version=quiz.schema_version,
        content_revision=quiz.content_revision,
        attempt_count=_attempt_count(db, quiz.id),
        created_by_user_id=UUID(quiz.created_by_user_id),
        published_at=quiz.published_at,
        created_at=quiz.created_at,
        updated_at=quiz.updated_at,
    )


def _teacher_dto(db: Session, quiz: ClassroomQuiz) -> TeacherQuizDTO:
    document = loads_document(quiz.document_json)
    summary = _summary(db, quiz)
    return TeacherQuizDTO(
        **summary.model_dump(),
        settings=settings_from_document(document),
        locale=str(document.get("locale") or "en"),
        items=teacher_items_from_document(document),
    )


def _student_dto(quiz: ClassroomQuiz) -> StudentQuizDTO:
    document = loads_document(quiz.document_json)
    stripped = strip_answers(document)
    assert_no_answer_keys(stripped)
    # Rebuild via StudentQuizDTO fields only — never pass answer through.
    items = []
    for raw in stripped.get("items") or []:
        items.append(
            {
                "id": raw["id"],
                "type": raw["type"],
                "required": bool(raw.get("required", True)),
                "prompt": raw.get("prompt") or "",
                "choices": raw.get("choices") or [],
                "points": float(raw.get("points") or 1),
            }
        )
    return StudentQuizDTO(
        id=UUID(quiz.id),
        course_id=UUID(quiz.course_id),
        group_id=UUID(quiz.group_id) if quiz.group_id else None,
        title=quiz.title,
        status="published",
        schema_version=quiz.schema_version,
        content_revision=quiz.content_revision,
        settings=settings_from_document(document),
        locale=str(document.get("locale") or "en"),
        items=items,  # type: ignore[arg-type]
        published_at=quiz.published_at,
    )


def list_quizzes_for_actor(db: Session, actor: AuthContext, course_id: str) -> list[QuizSummaryDTO]:
    role = _require_member(db, actor, course_id)
    query = select(ClassroomQuiz).where(ClassroomQuiz.course_id == course_id)
    if role != "teacher":
        query = query.where(ClassroomQuiz.status == "published")
    rows = db.scalars(query.order_by(ClassroomQuiz.updated_at.desc(), ClassroomQuiz.id)).all()
    return [_summary(db, row) for row in rows]


def create_quiz(
    db: Session, actor: AuthContext, course_id: str, body: CreateQuizRequest
) -> TeacherQuizDTO:
    _require_teacher(db, actor, course_id)
    group_id = str(body.group_id) if body.group_id else None
    if group_id is not None:
        group = db.get(Group, group_id)
        if group is None or group.course_id != course_id:
            raise not_found()
    quiz_id = str(uuid4())
    settings = body.settings or QuizSettings()
    document = build_document_dict(
        quiz_id=quiz_id,
        group_id=group_id,
        title=body.title,
        locale=body.locale,
        status="draft",
        settings=settings,
        items=body.items,
    )
    raw = dumps_document(document)
    now = _now()
    quiz = ClassroomQuiz(
        id=quiz_id,
        course_id=course_id,
        group_id=group_id,
        title=body.title,
        status="draft",
        schema_version=1,
        settings_json=dumps_document(settings.model_dump()),
        document_json=raw,
        content_revision=0,
        content_hash=None,
        created_by_user_id=str(actor.user.id),
        published_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    return _teacher_dto(db, quiz)


def get_quiz_for_actor(
    db: Session, actor: AuthContext, course_id: str, quiz_id: str
) -> TeacherQuizDTO | StudentQuizDTO:
    role = _require_member(db, actor, course_id)
    quiz = _get_quiz(db, course_id, quiz_id)
    if role == "teacher":
        return _teacher_dto(db, quiz)
    if quiz.status != "published":
        raise not_found()
    return _student_dto(quiz)


def patch_quiz(
    db: Session,
    actor: AuthContext,
    course_id: str,
    quiz_id: str,
    body: PatchQuizRequest,
) -> TeacherQuizDTO:
    _require_teacher(db, actor, course_id)
    quiz = _get_quiz(db, course_id, quiz_id)
    if quiz.status == "published":
        raise conflict(
            "quiz_published_immutable",
            "Unpublish the quiz before editing it.",
        )
    document = loads_document(quiz.document_json)
    title = body.title if body.title is not None else quiz.title
    locale = body.locale if body.locale is not None else str(document.get("locale") or "en")
    settings = body.settings if body.settings is not None else settings_from_document(document)
    items = body.items if body.items is not None else teacher_items_from_document(document)
    group_id = quiz.group_id
    if "group_id" in body.model_fields_set:
        group_id = str(body.group_id) if body.group_id else None
        if group_id is not None:
            group = db.get(Group, group_id)
            if group is None or group.course_id != course_id:
                raise not_found()
    new_doc = build_document_dict(
        quiz_id=quiz.id,
        group_id=group_id,
        title=title,
        locale=locale,
        status="draft",
        settings=settings,
        items=items,
    )
    quiz.title = title
    quiz.group_id = group_id
    quiz.settings_json = dumps_document(settings.model_dump())
    quiz.document_json = dumps_document(new_doc)
    quiz.updated_at = _now()
    db.commit()
    db.refresh(quiz)
    return _teacher_dto(db, quiz)


def publish_quiz(db: Session, actor: AuthContext, course_id: str, quiz_id: str) -> TeacherQuizDTO:
    _require_teacher(db, actor, course_id)
    quiz = _get_quiz(db, course_id, quiz_id)
    if quiz.status == "published":
        raise conflict("quiz_already_published", "The quiz is already published.")
    document = loads_document(quiz.document_json)
    items = teacher_items_from_document(document)
    if not items:
        raise unprocessable("quiz_empty", "Publish requires at least one item.")
    # Re-validate answers before freeze.
    build_document_dict(
        quiz_id=quiz.id,
        group_id=quiz.group_id,
        title=quiz.title,
        locale=str(document.get("locale") or "en"),
        status="published",
        settings=settings_from_document(document),
        items=items,
    )
    document["status"] = "published"
    raw = dumps_document(document)
    now = _now()
    quiz.document_json = raw
    quiz.status = "published"
    quiz.content_revision = int(quiz.content_revision) + 1
    quiz.content_hash = content_hash_for(raw)
    quiz.published_at = now
    quiz.updated_at = now
    db.commit()
    db.refresh(quiz)
    return _teacher_dto(db, quiz)


def unpublish_quiz(db: Session, actor: AuthContext, course_id: str, quiz_id: str) -> TeacherQuizDTO:
    _require_teacher(db, actor, course_id)
    quiz = _get_quiz(db, course_id, quiz_id)
    if quiz.status != "published":
        raise conflict("quiz_not_published", "The quiz is not published.")
    document = loads_document(quiz.document_json)
    document["status"] = "draft"
    quiz.document_json = dumps_document(document)
    quiz.status = "draft"
    quiz.published_at = None
    quiz.updated_at = _now()
    db.commit()
    db.refresh(quiz)
    return _teacher_dto(db, quiz)


def submit_attempt(
    db: Session,
    actor: AuthContext,
    course_id: str,
    quiz_id: str,
    body: SubmitQuizAttemptRequest,
) -> QuizAttemptDTO:
    role = _require_member(db, actor, course_id)
    if role == "teacher":
        raise forbidden("Teachers cannot submit quiz attempts.")
    quiz = _get_quiz(db, course_id, quiz_id)
    if quiz.status != "published":
        raise not_found()
    existing = db.scalar(
        select(ClassroomQuizAttempt).where(
            ClassroomQuizAttempt.quiz_id == quiz.id,
            ClassroomQuizAttempt.actor_user_id == str(actor.user.id),
        )
    )
    if existing is not None:
        raise conflict("quiz_attempt_exists", "This quiz has already been submitted.")

    document = loads_document(quiz.document_json)
    items = teacher_items_from_document(document)
    score, score_max, grading_status, normalized = grade_objective(items, body.answers)
    now = _now()
    attempt = ClassroomQuizAttempt(
        id=str(uuid4()),
        quiz_id=quiz.id,
        course_id=course_id,
        actor_user_id=str(actor.user.id),
        content_revision=quiz.content_revision,
        document_snapshot_json=quiz.document_json,
        answers_json=json.dumps(normalized, ensure_ascii=False, separators=(",", ":")),
        score_objective=score,
        score_max_objective=score_max,
        grading_status=grading_status,
        status="submitted",
        submitted_at=now,
        teacher_hidden_at=None,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return QuizAttemptDTO(
        id=UUID(attempt.id),
        quiz_id=UUID(attempt.quiz_id),
        course_id=UUID(attempt.course_id),
        actor_user_id=UUID(attempt.actor_user_id),
        content_revision=attempt.content_revision,
        status="submitted",
        grading_status=attempt.grading_status,  # type: ignore[arg-type]
        score_objective=attempt.score_objective,
        score_max_objective=attempt.score_max_objective,
        answers=normalized,
        submitted_at=attempt.submitted_at,
    )


def _display_name(db: Session, user_id: str) -> str:
    user = db.get(User, user_id)
    if user is None:
        return "Unknown"
    return user.display_name or user.username


def list_my_record_attempts(
    db: Session, actor: AuthContext, course_id: str
) -> list[RecordAttemptDTO]:
    """Student Record: quiz attempts + legacy chat attempts, newest first."""

    from app.modules.learning.reports import list_my_assessment_attempts

    role = _require_member(db, actor, course_id)
    rows: list[RecordAttemptDTO] = []

    quiz_attempts = db.scalars(
        select(ClassroomQuizAttempt)
        .where(
            ClassroomQuizAttempt.course_id == course_id,
            ClassroomQuizAttempt.actor_user_id == str(actor.user.id),
            ClassroomQuizAttempt.teacher_hidden_at.is_(None),
        )
        .order_by(ClassroomQuizAttempt.submitted_at.desc())
    ).all()
    for attempt in quiz_attempts:
        quiz = db.get(ClassroomQuiz, attempt.quiz_id)
        title = quiz.title if quiz is not None else "Quiz"
        rows.append(
            RecordAttemptDTO(
                source="quiz",
                attempt_id=UUID(attempt.id),
                user_id=UUID(attempt.actor_user_id),
                student_name=_display_name(db, attempt.actor_user_id),
                title=title,
                status=attempt.status,
                submitted_at=attempt.submitted_at,
                score_objective=attempt.score_objective,
                score_max_objective=attempt.score_max_objective,
                grading_status=attempt.grading_status,  # type: ignore[arg-type]
                quiz_id=UUID(attempt.quiz_id),
                points_awarded=attempt.score_objective,
                points_total=attempt.score_max_objective,
                phase="completed" if attempt.grading_status == "complete" else "scoring_not_saved",
            )
        )

    # Legacy chat attempts stay readable.
    if role != "teacher":
        chat_rows = list_my_assessment_attempts(db, actor, course_id=course_id)
    else:
        chat_rows = []
    for chat in chat_rows:
        rows.append(
            RecordAttemptDTO(
                source="chat",
                attempt_id=UUID(str(chat["attempt_id"])),
                user_id=UUID(str(chat["user_id"])),
                student_name=str(chat.get("student_name") or ""),
                title=str(chat.get("test_name") or chat.get("team_name") or "Assessment"),
                status=str(chat.get("status") or ""),
                submitted_at=chat.get("ended_at") or chat.get("started_at"),
                conversation_id=(
                    UUID(str(chat["conversation_id"]))
                    if chat.get("conversation_id") is not None
                    else None
                ),
                points_awarded=chat.get("points_awarded"),
                points_total=chat.get("points_total"),
                phase=chat.get("phase"),
                team_name=chat.get("team_name"),
            )
        )

    rows.sort(
        key=lambda row: row.submitted_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return rows


def list_course_record_attempts(
    db: Session, actor: AuthContext, course_id: str
) -> list[RecordAttemptDTO]:
    """Teacher Record aggregate across quiz + chat sources."""

    from app.modules.learning.reports import list_course_assessment_attempts

    _require_teacher(db, actor, course_id)
    rows: list[RecordAttemptDTO] = []

    quiz_attempts = db.scalars(
        select(ClassroomQuizAttempt)
        .where(
            ClassroomQuizAttempt.course_id == course_id,
            ClassroomQuizAttempt.teacher_hidden_at.is_(None),
        )
        .order_by(ClassroomQuizAttempt.submitted_at.desc())
    ).all()
    for attempt in quiz_attempts:
        quiz = db.get(ClassroomQuiz, attempt.quiz_id)
        title = quiz.title if quiz is not None else "Quiz"
        rows.append(
            RecordAttemptDTO(
                source="quiz",
                attempt_id=UUID(attempt.id),
                user_id=UUID(attempt.actor_user_id),
                student_name=_display_name(db, attempt.actor_user_id),
                title=title,
                status=attempt.status,
                submitted_at=attempt.submitted_at,
                score_objective=attempt.score_objective,
                score_max_objective=attempt.score_max_objective,
                grading_status=attempt.grading_status,  # type: ignore[arg-type]
                quiz_id=UUID(attempt.quiz_id),
                points_awarded=attempt.score_objective,
                points_total=attempt.score_max_objective,
                phase="completed" if attempt.grading_status == "complete" else "scoring_not_saved",
            )
        )

    for chat in list_course_assessment_attempts(db, actor, course_id=course_id):
        rows.append(
            RecordAttemptDTO(
                source="chat",
                attempt_id=UUID(str(chat["attempt_id"])),
                user_id=UUID(str(chat["user_id"])),
                student_name=str(chat.get("student_name") or ""),
                title=str(chat.get("test_name") or chat.get("team_name") or "Assessment"),
                status=str(chat.get("status") or ""),
                submitted_at=chat.get("ended_at") or chat.get("started_at"),
                conversation_id=(
                    UUID(str(chat["conversation_id"]))
                    if chat.get("conversation_id") is not None
                    else None
                ),
                points_awarded=chat.get("points_awarded"),
                points_total=chat.get("points_total"),
                phase=chat.get("phase"),
                team_name=chat.get("team_name"),
            )
        )

    rows.sort(
        key=lambda row: row.submitted_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return rows
