"""Teacher ZIP export of classroom quiz attempts as participant workbooks."""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import User
from app.modules.auth.service import AuthContext

from .document import loads_document, teacher_items_from_document
from .models import ClassroomQuizAttempt
from .service import (
    _display_name,
    _effective_objective,
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
    name = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', "_", title).strip(" .")[:60].rstrip(" .")
    if not name:
        return "quiz"
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", name):
        name = f"_{name}"
    return name


def _cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        value = ILLEGAL_CHARACTERS_RE.sub("", value).replace("\ufffe", "").replace("\uffff", "")
    return value


def _append(sheet: Worksheet, values: list[Any]) -> None:
    # Explicit string cells keep formula-like student/teacher input inert and faithful.
    # Excel truncates long cells; retain their remaining text in a continuation sheet.
    cells: list[Any] = []
    for value in values:
        value = _cell(value)
        cells.append(value[:32767] if isinstance(value, str) else value)
    sheet.append(cells)
    row = sheet.max_row
    for index, value in enumerate(values, 1):
        value = _cell(value)
        if isinstance(value, str):
            sheet.cell(row, index).data_type = "s"
            if len(value) > 32767:
                # Continuations live on their own sheet to preserve table columns.
                overflow = (
                    sheet.parent["Long text"]
                    if "Long text" in sheet.parent
                    else sheet.parent.create_sheet("Long text")
                )
                for start in range(32767, len(value), 32767):
                    _append(
                        overflow,
                        [
                            sheet.title,
                            f"{get_column_letter(index)}{row}",
                            start,
                            value[start : start + 32767],
                        ],
                    )


def _table(
    sheet: Worksheet,
    items: list[Any],
    answers: dict[str, dict[str, Any]],
    grades: dict[str, dict[str, Any]],
) -> None:
    answer_keys = sorted({key for answer in answers.values() for key in answer})
    grade_keys = sorted({key for grade in grades.values() for key in grade})
    columns = [
        "Question #",
        "Question",
        "Question type",
        "Options",
        "Participant answer",
        "Correct answer",
        "Result/score",
        "Points available",
        "Question ID",
        "Required",
        "Grading rules",
        *[f"Answer: {key}" for key in answer_keys],
        *[f"Teacher grade: {key}" for key in grade_keys],
    ]
    _append(sheet, columns)
    heading_row = sheet.max_row
    for cell in sheet[heading_row]:
        cell.font = Font(bold=True)
    for number, item in enumerate(items, 1):
        answer = answers.get(item.id, {})
        grade = grades.get(item.id, {})
        choices = {choice.id: choice.label for choice in item.choices}
        selected = answer.get("choice_ids") or []
        participant_answer = (
            "; ".join(choices.get(key, key) for key in selected)
            if selected
            else answer.get("text", "")
        )
        correct = ""
        if item.answer:
            correct = (
                "; ".join(choices.get(key, key) for key in item.answer.choice_ids or [])
                or item.answer.rubric
                or ""
            )
        score = grade.get("points_awarded", answer.get("points_awarded"))
        _append(
            sheet,
            [
                number,
                item.prompt,
                item.type,
                "\n".join(f"{choice.id}: {choice.label}" for choice in item.choices),
                participant_answer,
                correct,
                score,
                item.points,
                item.id,
                item.required,
                item.grading.model_dump() if item.grading else None,
                *[answer.get(key) for key in answer_keys],
                *[grade.get(key) for key in grade_keys],
            ],
        )
    sheet.freeze_panes = f"E{heading_row + 1}"
    sheet.auto_filter.ref = f"A{heading_row}:{get_column_letter(len(columns))}{sheet.max_row}"
    for column, width in {"A": 14, "B": 55, "C": 20, "D": 40, "E": 55, "F": 55, "G": 18}.items():
        sheet.column_dimensions[column].width = width


def _workbook(
    *,
    metadata: dict[str, Any],
    items: list[Any],
    answers: dict[str, dict[str, Any]],
    grades: dict[str, dict[str, Any]],
    quiz_payload: dict[str, Any],
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Attempt"
    for label, value in metadata.items():
        _append(sheet, [label, value])
    _append(sheet, [])
    _table(sheet, items, answers, grades)
    known_ids = {item.id for item in items}
    orphan_ids = (answers.keys() | grades.keys()) - known_ids
    if orphan_ids:
        other = workbook.create_sheet("Other answers")
        answer_keys = sorted({key for item_id in orphan_ids for key in answers.get(item_id, {})})
        grade_keys = sorted({key for item_id in orphan_ids for key in grades.get(item_id, {})})
        _append(
            other,
            [
                "Question ID",
                *[f"Answer: {key}" for key in answer_keys],
                *[f"Teacher grade: {key}" for key in grade_keys],
            ],
        )
        for item_id in sorted(orphan_ids):
            _append(
                other,
                [
                    item_id,
                    *[answers.get(item_id, {}).get(key) for key in answer_keys],
                    *[grades.get(item_id, {}).get(key) for key in grade_keys],
                ],
            )
    current = workbook.create_sheet("Current paper")
    for key, value in quiz_payload.items():
        if key != "document":
            _append(current, [key, value])
    document = quiz_payload["document"]
    for key, value in document.items():
        if key != "items":
            _append(current, [key, value])
    _append(current, [])
    _table(current, teacher_items_from_document(document), {}, {})
    for page in workbook:
        for row in page:
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def export_quiz_attempts(
    db: Session,
    actor: AuthContext,
    course_id: str,
    quiz_id: str,
    taking_epoch: int | None = None,
) -> QuizAttemptsExport:
    """Include the same submitted, non-hidden attempts as the former JSON archive."""
    _require_teacher(db, actor, course_id)
    quiz = _get_quiz(db, course_id, quiz_id)
    query = select(ClassroomQuizAttempt).where(
        ClassroomQuizAttempt.quiz_id == quiz.id,
        ClassroomQuizAttempt.status == "submitted",
        ClassroomQuizAttempt.teacher_hidden_at.is_(None),
    )
    if taking_epoch is not None:
        query = query.where(ClassroomQuizAttempt.taking_epoch == taking_epoch)
    attempts = list(
        db.scalars(
            query.order_by(ClassroomQuizAttempt.submitted_at.desc(), ClassroomQuizAttempt.id)
        ).all()
    )
    quiz_payload = {
        "title": quiz.title,
        "status": quiz.status,
        "content_revision": quiz.content_revision,
        "taking_open": quiz.taking_open,
        "taking_epoch": quiz.taking_epoch,
        "document": loads_document(quiz.document_json),
    }
    folders: dict[str, str] = {}
    used: set[str] = set()
    file_counts: dict[str, int] = {}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for attempt in attempts:
            name = _display_name(db, attempt.actor_user_id)
            user = db.get(User, attempt.actor_user_id)
            if attempt.actor_user_id not in folders:
                base = _safe_title(name)
                folder = base
                suffix = 2
                while folder.casefold() in used:
                    folder = f"{base} ({suffix})"
                    suffix += 1
                folders[attempt.actor_user_id] = folder
                used.add(folder.casefold())
            folder = folders[attempt.actor_user_id]
            file_counts[folder] = file_counts.get(folder, 0) + 1
            suffix_text = f" ({file_counts[folder]})" if file_counts[folder] > 1 else ""
            objective, answers = _effective_objective(attempt)
            items = _snapshot_items(attempt)
            manual_max = _manual_max(items)
            metadata = {
                "Participant name": name,
                "Username": user.username if user else None,
                "Submitted time": _iso(attempt.submitted_at),
                "Total score": (
                    f"{objective + attempt.score_manual}/{attempt.score_max_objective + manual_max}"
                ),
                "attempt_id": attempt.id,
                "actor_user_id": attempt.actor_user_id,
                "content_revision": attempt.content_revision,
                "taking_epoch": attempt.taking_epoch,
                "grading_status": attempt.grading_status,
                "score_objective": objective,
                "score_max_objective": attempt.score_max_objective,
                "score_manual": attempt.score_manual,
                "score_max_manual": manual_max,
                "points_awarded": objective + attempt.score_manual,
                "points_total": attempt.score_max_objective + manual_max,
                "graded_at": _iso(attempt.graded_at),
                "exported_at": _iso(datetime.now(UTC)),
                "course_id": course_id,
                "quiz_id": quiz.id,
                "taking_epoch_filter": taking_epoch,
            }
            archive.writestr(
                f"{folder}/{_safe_title(name)}{suffix_text}.xlsx",
                _workbook(
                    metadata=metadata,
                    items=items,
                    answers=answers,
                    grades=_manual_grades(attempt),
                    quiz_payload=quiz_payload,
                ),
            )
    return QuizAttemptsExport(content=buffer.getvalue(), filename=f"{_safe_title(quiz.title)}.zip")


__all__ = ["QuizAttemptsExport", "export_quiz_attempts"]
