"""Teacher zip export of classroom quiz attempts (json + md)."""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.auth.service import AuthContext

from .document import loads_document
from .models import ClassroomQuizAttempt
from .service import (
    _display_name,
    _get_quiz,
    _manual_grades,
    _manual_max,
    _require_teacher,
    _snapshot_items,
)


@dataclass(frozen=True)
class QuizAttemptsExport:
    content: bytes
    filename: str
    content_type: str = "application/zip"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _safe_title(title: str) -> str:
    slug = "-".join(
        part for part in re.sub(r"[^\w-]+", "-", title.lower(), flags=re.ASCII).split("-") if part
    )[:64]
    return slug or "quiz"


def _quiz_id_short(quiz_id: str) -> str:
    compact = quiz_id.replace("-", "")
    return compact[:8]


def _format_answer(answer: Any) -> str:
    if not isinstance(answer, dict):
        return json.dumps(answer, ensure_ascii=False)
    item_id = answer.get("item_id") or "?"
    if "choice_ids" in answer:
        choices = answer.get("choice_ids") or []
        return f"{item_id}: {', '.join(str(c) for c in choices)}"
    if "text" in answer:
        return f"{item_id}: {answer.get('text') or ''}"
    return f"{item_id}: {json.dumps(answer, ensure_ascii=False)}"


def _build_summary_md(
    *,
    title: str,
    exported_at: str,
    attempt_rows: list[dict[str, Any]],
) -> str:
    lines = [
        f"# {title}",
        f"Exported: {exported_at}",
        f"Attempts: {len(attempt_rows)}",
        "",
    ]
    if not attempt_rows:
        lines.append("No submissions yet.")
        lines.append("")
        return "\n".join(lines)

    lines.extend(
        [
            "| Student | Score | Grading | Submitted | Epoch |",
            "|---|---|---|---|---|",
        ]
    )
    for row in attempt_rows:
        score_cell = f"{row['points_awarded']}/{row['points_total']}"
        lines.append(
            "| {student} | {score} | {grading} | {submitted} | {epoch} |".format(
                student=row["student_name"],
                score=score_cell,
                grading=row["grading_status"],
                submitted=row["submitted_at"] or "",
                epoch=row["taking_epoch"],
            )
        )
    lines.append("")
    for row in attempt_rows:
        lines.append(f"## {row['student_name']}")
        answers = row.get("answers") or []
        if not answers:
            lines.append("- (no answers)")
        else:
            for answer in answers:
                lines.append(f"- {_format_answer(answer)}")
        lines.append("")
    return "\n".join(lines)


def export_quiz_attempts(
    db: Session,
    actor: AuthContext,
    course_id: str,
    quiz_id: str,
    taking_epoch: int | None = None,
) -> QuizAttemptsExport:
    """Build an in-memory zip of submitted (non-hidden) attempts for one quiz."""

    _require_teacher(db, actor, course_id)
    quiz = _get_quiz(db, course_id, quiz_id)

    query = select(ClassroomQuizAttempt).where(
        ClassroomQuizAttempt.quiz_id == quiz.id,
        ClassroomQuizAttempt.status == "submitted",
        ClassroomQuizAttempt.teacher_hidden_at.is_(None),
    )
    if taking_epoch is not None:
        query = query.where(ClassroomQuizAttempt.taking_epoch == taking_epoch)
    attempts = list(db.scalars(query.order_by(ClassroomQuizAttempt.submitted_at.desc())).all())

    exported_at = _iso(_now()) or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    document = loads_document(quiz.document_json)

    attempt_rows: list[dict[str, Any]] = []
    for attempt in attempts:
        answers_raw = json.loads(attempt.answers_json)
        if not isinstance(answers_raw, list):
            answers_raw = []
        score_max_manual = _manual_max(_snapshot_items(attempt))
        attempt_rows.append(
            {
                "attempt_id": attempt.id,
                "actor_user_id": attempt.actor_user_id,
                "student_name": _display_name(db, attempt.actor_user_id),
                "content_revision": attempt.content_revision,
                "taking_epoch": attempt.taking_epoch,
                "submitted_at": _iso(attempt.submitted_at),
                "grading_status": attempt.grading_status,
                "score_objective": attempt.score_objective,
                "score_max_objective": attempt.score_max_objective,
                "score_manual": attempt.score_manual,
                "score_max_manual": score_max_manual,
                "points_awarded": attempt.score_objective + attempt.score_manual,
                "points_total": attempt.score_max_objective + score_max_manual,
                "graded_at": _iso(attempt.graded_at),
                "manual_grades": _manual_grades(attempt),
                "answers": answers_raw,
            }
        )

    manifest = {
        "schema_version": 1,
        "exported_at": exported_at,
        "course_id": course_id,
        "quiz_id": quiz.id,
        "quiz_title": quiz.title,
        "quiz_status": quiz.status,
        "content_revision": quiz.content_revision,
        "taking_epoch_filter": taking_epoch,
        "attempt_count": len(attempt_rows),
        "filter": "source=quiz; teacher_hidden excluded; status=submitted",
    }
    quiz_payload = {
        "title": quiz.title,
        "status": quiz.status,
        "content_revision": quiz.content_revision,
        "taking_open": quiz.taking_open,
        "taking_epoch": quiz.taking_epoch,
        "document": document,
    }
    summary_md = _build_summary_md(
        title=quiz.title,
        exported_at=exported_at,
        attempt_rows=attempt_rows,
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
        zf.writestr(
            "quiz.json",
            json.dumps(quiz_payload, ensure_ascii=False, indent=2) + "\n",
        )
        zf.writestr(
            "attempts.json",
            json.dumps(attempt_rows, ensure_ascii=False, indent=2) + "\n",
        )
        zf.writestr("summary.md", summary_md)
        if not attempt_rows:
            zf.writestr("README.md", "No submissions yet.\n")

    filename = f"quiz-{_safe_title(quiz.title)}-{_quiz_id_short(quiz.id)}-attempts.zip"
    return QuizAttemptsExport(content=buffer.getvalue(), filename=filename)


def _now() -> datetime:
    return datetime.now(UTC)


__all__ = ["QuizAttemptsExport", "export_quiz_attempts"]
