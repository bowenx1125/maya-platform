"""Classroom Quiz persistence, publish gates, submit + objective grading."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import conflict, forbidden, not_found, unprocessable
from app.core.models import Group, User
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import course_member_role
from app.modules.workspace.access import course_member

from .document import (
    assert_no_answer_keys,
    build_document_dict,
    content_hash_for,
    document_has_ai_grading,
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
    GradeQuizAttemptRequest,
    PatchQuizRequest,
    QuizAnswerSubmission,
    QuizAttemptDTO,
    QuizAttemptItemStudent,
    QuizAttemptItemTeacher,
    QuizSettings,
    QuizSummaryDTO,
    RecordAttemptDTO,
    StudentQuizAttemptDetailDTO,
    StudentQuizDTO,
    SubmitQuizAttemptRequest,
    TeacherQuizAttemptDetailDTO,
    TeacherQuizDTO,
)

TEXT_TYPES = ("short_text", "long_text")
CHOICE_TYPES = ("single", "multiple")


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
        taking_open=quiz.taking_open,
        taking_epoch=quiz.taking_epoch,
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
        taking_open=quiz.taking_open,
        taking_epoch=quiz.taking_epoch,
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
        taking_open=False,
        taking_epoch=0,
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
    # A draft can never be open for taking.
    quiz.taking_open = False
    quiz.updated_at = _now()
    db.commit()
    db.refresh(quiz)
    return _teacher_dto(db, quiz)


def delete_quiz(db: Session, actor: AuthContext, course_id: str, quiz_id: str) -> None:
    """Delete a quiz for good, with every attempt (Record) taken on it.

    Owner decision 2026-11-08: a real delete in any state, draft or published,
    open or paused. Attempts go first in the same transaction (the foreign
    key also cascades), so no submission, grade or AI score outlives its
    quiz. An AI grading job still queued finds no attempt and stops.
    """

    _require_teacher(db, actor, course_id)
    quiz = db.scalar(
        select(ClassroomQuiz)
        .where(ClassroomQuiz.id == quiz_id, ClassroomQuiz.course_id == course_id)
        .with_for_update()
    )
    if quiz is None:
        raise not_found()
    db.execute(delete(ClassroomQuizAttempt).where(ClassroomQuizAttempt.quiz_id == quiz_id))
    db.delete(quiz)
    db.commit()


def _get_quiz_for_update(db: Session, course_id: str, quiz_id: str) -> ClassroomQuiz:
    """Load the quiz row with a write lock for taking open/close RMW."""

    quiz = db.scalar(
        select(ClassroomQuiz)
        .where(ClassroomQuiz.id == quiz_id, ClassroomQuiz.course_id == course_id)
        .with_for_update()
    )
    if quiz is None:
        raise not_found()
    return quiz


def start_taking(db: Session, actor: AuthContext, course_id: str, quiz_id: str) -> TeacherQuizDTO:
    """Open the published paper for taking; first open starts a new epoch."""

    _require_teacher(db, actor, course_id)
    quiz = _get_quiz_for_update(db, course_id, quiz_id)
    if quiz.status != "published":
        raise conflict("quiz_not_published", "The quiz is not published.")
    if quiz.taking_open:
        raise conflict(
            "quiz_taking_already_open",
            "The quiz is already open for taking.",
        )
    quiz.taking_epoch = int(quiz.taking_epoch) + 1
    quiz.taking_open = True
    quiz.updated_at = _now()
    db.commit()
    db.refresh(quiz)
    return _teacher_dto(db, quiz)


def pause_taking(db: Session, actor: AuthContext, course_id: str, quiz_id: str) -> TeacherQuizDTO:
    """Close taking without touching the epoch; re-opening keeps the epoch."""

    _require_teacher(db, actor, course_id)
    quiz = _get_quiz_for_update(db, course_id, quiz_id)
    if quiz.status != "published":
        raise conflict("quiz_not_published", "The quiz is not published.")
    if not quiz.taking_open:
        raise conflict(
            "quiz_taking_already_closed",
            "The quiz is already closed for taking.",
        )
    quiz.taking_open = False
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
    """Submit one attempt for the current taking epoch.

    Hot-path notes (concurrency ladder):
    - Duplicate detection relies on the unique index + IntegrityError → 409;
      no pre-insert existence SELECT (avoids an extra round-trip under load).
    - ``document_snapshot_json`` reuses ``quiz.document_json`` as-is (no
      re-serialize). Document is parsed once for objective grading only.
    - Skip ``db.refresh`` after commit; expire_on_commit=False keeps fields.
    """

    role = _require_member(db, actor, course_id)
    if role == "teacher":
        raise forbidden("Teachers cannot submit quiz attempts.")
    quiz = _get_quiz(db, course_id, quiz_id)
    if quiz.status != "published":
        raise not_found()
    if not quiz.taking_open:
        raise conflict(
            "quiz_taking_closed",
            "The quiz is not open for taking right now.",
        )
    epoch = int(quiz.taking_epoch)
    # Reuse the stored JSON string for the snapshot; parse once for grading.
    document_json = quiz.document_json
    document = loads_document(document_json)
    items = teacher_items_from_document(document)
    score, score_max, grading_status, normalized = grade_objective(items, body.answers)
    answers_json = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    now = _now()
    attempt_id = str(uuid4())
    actor_user_id = str(actor.user.id)
    attempt = ClassroomQuizAttempt(
        id=attempt_id,
        quiz_id=quiz.id,
        course_id=course_id,
        actor_user_id=actor_user_id,
        content_revision=quiz.content_revision,
        taking_epoch=epoch,
        document_snapshot_json=document_json,
        answers_json=answers_json,
        score_objective=score,
        score_max_objective=score_max,
        grading_status=grading_status,
        status="submitted",
        submitted_at=now,
        teacher_hidden_at=None,
    )
    db.add(attempt)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_quiz_attempt_unique_integrity(exc):
            raise conflict(
                "quiz_attempt_exists",
                "This quiz has already been submitted.",
            ) from exc
        raise
    return QuizAttemptDTO(
        id=UUID(attempt_id),
        quiz_id=UUID(quiz.id),
        course_id=UUID(course_id),
        actor_user_id=UUID(actor_user_id),
        content_revision=quiz.content_revision,
        taking_epoch=epoch,
        status="submitted",
        grading_status=grading_status,  # type: ignore[arg-type]
        score_objective=score,
        score_max_objective=score_max,
        answers=normalized,
        submitted_at=now,
    )


def _display_name(db: Session, user_id: str) -> str:
    user = db.get(User, user_id)
    if user is None:
        return "Unknown"
    return user.display_name or user.username


def list_my_record_attempts(
    db: Session, actor: AuthContext, course_id: str, quiz_id: str | None = None
) -> list[RecordAttemptDTO]:
    """Student Record: quiz attempts + legacy chat attempts, newest first.

    With ``quiz_id`` only that quiz's attempts are returned (chat excluded).
    """

    from app.modules.learning.reports import list_my_assessment_attempts

    role = _require_member(db, actor, course_id)
    rows: list[RecordAttemptDTO] = []

    quiz_query = select(ClassroomQuizAttempt).where(
        ClassroomQuizAttempt.course_id == course_id,
        ClassroomQuizAttempt.actor_user_id == str(actor.user.id),
        ClassroomQuizAttempt.teacher_hidden_at.is_(None),
    )
    if quiz_id is not None:
        quiz_query = quiz_query.where(ClassroomQuizAttempt.quiz_id == quiz_id)
    quiz_attempts = db.scalars(quiz_query.order_by(ClassroomQuizAttempt.submitted_at.desc())).all()
    for attempt in quiz_attempts:
        rows.append(_quiz_record_row(db, attempt))

    # Legacy chat attempts stay readable.
    if quiz_id is not None:
        chat_rows = []
    elif role != "teacher":
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
    db: Session, actor: AuthContext, course_id: str, quiz_id: str | None = None
) -> list[RecordAttemptDTO]:
    """Teacher Record aggregate across quiz + chat sources.

    With ``quiz_id`` only that quiz's attempts are returned (chat excluded).
    """

    from app.modules.learning.reports import list_course_assessment_attempts

    _require_teacher(db, actor, course_id)
    rows: list[RecordAttemptDTO] = []

    quiz_query = select(ClassroomQuizAttempt).where(
        ClassroomQuizAttempt.course_id == course_id,
        ClassroomQuizAttempt.teacher_hidden_at.is_(None),
    )
    if quiz_id is not None:
        quiz_query = quiz_query.where(ClassroomQuizAttempt.quiz_id == quiz_id)
    quiz_attempts = db.scalars(quiz_query.order_by(ClassroomQuizAttempt.submitted_at.desc())).all()
    for attempt in quiz_attempts:
        rows.append(_quiz_record_row(db, attempt))

    if quiz_id is not None:
        chat_source: list[dict[str, Any]] = []
    else:
        chat_source = list(list_course_assessment_attempts(db, actor, course_id=course_id))
    for chat in chat_source:
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


def _snapshot_items(attempt: ClassroomQuizAttempt) -> list[Any]:
    """The paper this attempt answered: grading never follows later edits."""

    return teacher_items_from_document(loads_document(attempt.document_snapshot_json))


def _manual_grades(attempt: ClassroomQuizAttempt) -> dict[str, dict[str, Any]]:
    raw = json.loads(attempt.manual_grades_json or "{}")
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)}


def _manual_max(items: list[Any]) -> float:
    return float(sum(float(item.points) for item in items if item.type in TEXT_TYPES))


def _answers_by_id(attempt: ClassroomQuizAttempt) -> dict[str, dict[str, Any]]:
    raw = json.loads(attempt.answers_json)
    if not isinstance(raw, list):
        return {}
    return {
        str(row.get("item_id")): row
        for row in raw
        if isinstance(row, dict) and row.get("item_id") is not None
    }


def _effective_objective(
    attempt: ClassroomQuizAttempt,
) -> tuple[float, dict[str, dict[str, Any]]]:
    # Old attempts retain their answer payloads; only keyless choice results
    # are projected anew, leaving teacher and AI text grades untouched.
    answers = _answers_by_id(attempt)
    score = attempt.score_objective
    for item in _snapshot_items(attempt):
        if item.type not in CHOICE_TYPES or (item.answer and item.answer.choice_ids):
            continue
        answer = answers.get(item.id, {})
        submission = QuizAnswerSubmission(
            item_id=item.id, choice_ids=answer.get("choice_ids") or []
        )
        awarded, _, _, normalized = grade_objective([item], [submission])
        score += awarded - float(answer.get("points_awarded") or 0)
        answers[item.id] = {**answer, **normalized[0]}
    return score, answers


def _item_grading_mode(item: Any) -> str:
    grading = getattr(item, "grading", None)
    if grading is None:
        return "manual"
    if isinstance(grading, dict):
        return str(grading.get("mode") or "manual")
    return str(getattr(grading, "mode", None) or "manual")


def _text_item_graded(
    item: Any, grades: dict[str, dict[str, Any]], answers: dict[str, dict[str, Any]]
) -> bool:
    if item.id in grades:
        return True
    if _item_grading_mode(item) == "ai":
        return (answers.get(item.id) or {}).get("ai_score") is not None
    return False


def _compute_score_manual(
    items: list[Any], grades: dict[str, dict[str, Any]], answers: dict[str, dict[str, Any]]
) -> float:
    total = 0.0
    for item in items:
        if item.type not in TEXT_TYPES:
            continue
        if item.id in grades:
            total += float(grades[item.id].get("points_awarded") or 0)
            continue
        ai_score = (answers.get(item.id) or {}).get("ai_score")
        if ai_score is not None:
            total += float(ai_score)
    return total


def _compute_score_ai(answers: dict[str, dict[str, Any]]) -> float | None:
    """Sum of written ai_score values; None when none have been scored yet."""

    scores = [
        float(row["ai_score"])
        for row in answers.values()
        if isinstance(row, dict) and row.get("ai_score") is not None
    ]
    return sum(scores) if scores else None


def _grading_status(
    items: list[Any],
    grades: dict[str, dict[str, Any]],
    answers: dict[str, dict[str, Any]] | None = None,
) -> str:
    """complete once every text item is teacher-graded or AI-scored."""

    answers = answers or {}
    text_items = [item for item in items if item.type in TEXT_TYPES]
    if all(_text_item_graded(item, grades, answers) for item in text_items):
        return "complete"
    return "mixed" if any(item.type in CHOICE_TYPES for item in items) else "pending"


def _quiz_record_row(db: Session, attempt: ClassroomQuizAttempt) -> RecordAttemptDTO:
    score_objective, _ = _effective_objective(attempt)
    quiz = db.get(ClassroomQuiz, attempt.quiz_id)
    score_max_manual = _manual_max(_snapshot_items(attempt))
    return RecordAttemptDTO(
        source="quiz",
        attempt_id=UUID(attempt.id),
        user_id=UUID(attempt.actor_user_id),
        student_name=_display_name(db, attempt.actor_user_id),
        title=quiz.title if quiz is not None else "Quiz",
        status=attempt.status,
        submitted_at=attempt.submitted_at,
        score_objective=score_objective,
        score_max_objective=attempt.score_max_objective,
        grading_status=attempt.grading_status,  # type: ignore[arg-type]
        score_ai=_compute_score_ai(_answers_by_id(attempt)),
        quiz_id=UUID(attempt.quiz_id),
        # Totals cover text items too, so an ungraded paper never reads as a
        # full score over its choice questions alone.
        points_awarded=score_objective + attempt.score_manual,
        points_total=attempt.score_max_objective + score_max_manual,
        phase="completed" if attempt.grading_status == "complete" else "grading_pending",
        taking_epoch=attempt.taking_epoch,
        content_revision=attempt.content_revision,
    )


def _visible_attempt(
    db: Session, course_id: str, quiz_id: str, attempt_id: str, *, lock: bool = False
) -> ClassroomQuizAttempt:
    query = select(ClassroomQuizAttempt).where(
        ClassroomQuizAttempt.id == attempt_id,
        ClassroomQuizAttempt.quiz_id == quiz_id,
        ClassroomQuizAttempt.course_id == course_id,
        ClassroomQuizAttempt.teacher_hidden_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    attempt = db.scalar(query)
    if attempt is None:
        raise not_found()
    return attempt


def _attempt_detail(
    db: Session, attempt: ClassroomQuizAttempt, *, teacher: bool
) -> TeacherQuizAttemptDetailDTO | StudentQuizAttemptDetailDTO:
    items = _snapshot_items(attempt)
    grades = _manual_grades(attempt)
    score_objective, answers = _effective_objective(attempt)
    item_cls = QuizAttemptItemTeacher if teacher else QuizAttemptItemStudent
    rows: list[Any] = []
    for item in items:
        answer = answers.get(item.id, {})
        grade = grades.get(item.id)
        entry: dict[str, Any] = {
            "id": item.id,
            "type": item.type,
            "required": item.required,
            "prompt": item.prompt,
            "choices": item.choices,
            "points": float(item.points),
        }
        if item.type in CHOICE_TYPES:
            entry["response_choice_ids"] = list(answer.get("choice_ids") or [])
            entry["correct"] = answer.get("correct")
            entry["points_awarded"] = answer.get("points_awarded")
            entry["graded"] = True
        else:
            entry["response_text"] = str(answer.get("text") or "")
            if answer.get("ai_score") is not None:
                entry["ai_score"] = float(answer["ai_score"])
            if grade is not None:
                entry["graded"] = True
                entry["points_awarded"] = float(grade.get("points_awarded") or 0)
                entry["feedback"] = str(grade.get("feedback") or "")
            elif answer.get("ai_score") is not None:
                entry["graded"] = True
                entry["points_awarded"] = float(answer["ai_score"])
                feedback = answer.get("ai_feedback")
                entry["feedback"] = None if feedback is None else str(feedback)
            else:
                entry["graded"] = False
        if teacher:
            entry["answer"] = item.answer
            entry["ai_grading"] = item.type in TEXT_TYPES and _item_grading_mode(item) == "ai"
        rows.append(item_cls(**entry))
    known = {item.id for item in items}
    for item_id, answer in answers.items():
        if item_id in known:
            continue
        rows.append(
            item_cls(
                id=item_id,
                type="unknown",
                response_choice_ids=answer.get("choice_ids"),
                response_text=answer.get("text"),
            )
        )
    quiz = db.get(ClassroomQuiz, attempt.quiz_id)
    score_max_manual = _manual_max(items)
    payload: dict[str, Any] = {
        "id": UUID(attempt.id),
        "quiz_id": UUID(attempt.quiz_id),
        "course_id": UUID(attempt.course_id),
        "user_id": UUID(attempt.actor_user_id),
        "student_name": _display_name(db, attempt.actor_user_id),
        "title": quiz.title if quiz is not None else "Quiz",
        "content_revision": attempt.content_revision,
        "taking_epoch": attempt.taking_epoch,
        "status": "submitted",
        "grading_status": attempt.grading_status,
        "score_objective": score_objective,
        "score_max_objective": attempt.score_max_objective,
        "score_manual": attempt.score_manual,
        "score_max_manual": score_max_manual,
        "score_ai": _compute_score_ai(answers),
        "points_awarded": score_objective + attempt.score_manual,
        "points_total": attempt.score_max_objective + score_max_manual,
        "submitted_at": attempt.submitted_at,
        "graded_at": attempt.graded_at,
        "items": rows,
    }
    if teacher:
        return TeacherQuizAttemptDetailDTO(**payload)
    # Rebuilt through the student DTO: its items carry no answer field.
    detail = StudentQuizAttemptDetailDTO(**payload)
    assert_no_answer_keys(detail.model_dump(mode="json"))
    return detail


def get_attempt_for_actor(
    db: Session, actor: AuthContext, course_id: str, quiz_id: str, attempt_id: str
) -> TeacherQuizAttemptDetailDTO | StudentQuizAttemptDetailDTO:
    """A teacher reads any visible attempt; a student only their own."""

    role = _require_member(db, actor, course_id)
    _get_quiz(db, course_id, quiz_id)
    attempt = _visible_attempt(db, course_id, quiz_id, attempt_id)
    if role == "teacher":
        return _attempt_detail(db, attempt, teacher=True)
    if attempt.actor_user_id != str(actor.user.id):
        raise not_found()
    return _attempt_detail(db, attempt, teacher=False)


def hide_attempt(
    db: Session, actor: AuthContext, course_id: str, quiz_id: str, attempt_id: str
) -> None:
    """Hide an attempt from Record, counts and export, for the student too.

    The row stays (with its epoch), so hiding never reopens that round for
    the student.
    """

    _require_teacher(db, actor, course_id)
    _get_quiz(db, course_id, quiz_id)
    attempt = _visible_attempt(db, course_id, quiz_id, attempt_id, lock=True)
    attempt.teacher_hidden_at = _now()
    db.commit()


def grade_attempt(
    db: Session,
    actor: AuthContext,
    course_id: str,
    quiz_id: str,
    attempt_id: str,
    body: GradeQuizAttemptRequest,
) -> TeacherQuizAttemptDetailDTO:
    """A teacher's hand grade for text items; choice items keep the key's score."""

    _require_teacher(db, actor, course_id)
    _get_quiz(db, course_id, quiz_id)
    attempt = _visible_attempt(db, course_id, quiz_id, attempt_id, lock=True)
    items = {item.id: item for item in _snapshot_items(attempt)}
    seen: set[str] = set()
    for grade in body.grades:
        item = items.get(grade.item_id)
        if item is None or item.type not in TEXT_TYPES or grade.item_id in seen:
            raise unprocessable(
                "quiz_grade_item_invalid",
                "Only each text question of this attempt can be graded, once per request.",
                {"item_id": grade.item_id},
            )
        seen.add(grade.item_id)
        if grade.points_awarded > float(item.points):
            raise unprocessable(
                "quiz_grade_points_invalid",
                "Points cannot exceed the question's points.",
                {"item_id": grade.item_id, "max_points": float(item.points)},
            )
    grades = _manual_grades(attempt)
    now = _now()
    for grade in body.grades:
        grades[grade.item_id] = {
            "points_awarded": float(grade.points_awarded),
            "feedback": grade.feedback,
            "graded_by_user_id": str(actor.user.id),
            "graded_at": now.isoformat(),
        }
    answers = _answers_by_id(attempt)
    snapshot_items = list(items.values())
    attempt.manual_grades_json = json.dumps(grades, ensure_ascii=False, separators=(",", ":"))
    attempt.score_manual = _compute_score_manual(snapshot_items, grades, answers)
    attempt.grading_status = _grading_status(snapshot_items, grades, answers)
    attempt.graded_at = now
    db.commit()
    db.refresh(attempt)
    detail = _attempt_detail(db, attempt, teacher=True)
    assert isinstance(detail, TeacherQuizAttemptDetailDTO)
    return detail


def _integrity_detail(exc: IntegrityError) -> str:
    orig = exc.orig
    parts = [str(orig)]
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None) if diag is not None else None
    if constraint_name:
        parts.append(str(constraint_name))
    return " ".join(parts).lower()


def _is_quiz_attempt_unique_integrity(exc: IntegrityError) -> bool:
    """True when the loser of a concurrent submit hit the epoch unique index."""

    detail = _integrity_detail(exc)
    if "ux_classroom_quiz_attempts_quiz_actor_epoch" in detail:
        return True
    # SQLite / generic drivers often omit the constraint name and only name columns.
    return (
        "classroom_quiz_attempts" in detail.replace("-", "_")
        and "unique" in detail
        and "quiz_id" in detail
        and "actor_user_id" in detail
        and "taking_epoch" in detail
    )


def attempt_needs_ai_grade(db: Session, attempt_id: str) -> bool:
    """True when the frozen paper has text items marked for AI grading."""

    attempt = db.get(ClassroomQuizAttempt, attempt_id)
    if attempt is None:
        return False
    return document_has_ai_grading(loads_document(attempt.document_snapshot_json))
