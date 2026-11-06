"""QuizDocument validation and student projection (strip answer/rubric)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.errors import unprocessable

from .schemas import (
    QuizDocumentStudent,
    QuizDocumentTeacher,
    QuizItemStudent,
    QuizItemTeacher,
    QuizSettings,
)

ALLOWED_TYPES = frozenset({"single", "multiple", "short_text", "long_text"})


def dumps_document(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def loads_document(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise unprocessable("quiz_document_invalid", "Quiz document must be an object.")
    return data


def content_hash_for(document_json: str) -> str:
    return hashlib.sha256(document_json.encode("utf-8")).hexdigest()


def validate_teacher_items(items: list[QuizItemTeacher]) -> None:
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            raise unprocessable("quiz_item_duplicate", f"Duplicate item id: {item.id}")
        seen.add(item.id)
        if item.type not in ALLOWED_TYPES:
            raise unprocessable("quiz_item_type_invalid", f"Unsupported item type: {item.type}")
        if item.type in ("single", "multiple"):
            if len(item.choices) < 2:
                raise unprocessable(
                    "quiz_item_choices_invalid",
                    f"Item {item.id} needs at least two choices.",
                )
            choice_ids = {c.id for c in item.choices}
            if len(choice_ids) != len(item.choices):
                raise unprocessable(
                    "quiz_item_choices_invalid",
                    f"Item {item.id} has duplicate choice ids.",
                )
            if item.answer is None or not item.answer.choice_ids:
                raise unprocessable(
                    "quiz_answer_required",
                    f"Item {item.id} needs answer.choice_ids.",
                )
            if item.type == "single" and len(item.answer.choice_ids) != 1:
                raise unprocessable(
                    "quiz_answer_invalid",
                    f"Item {item.id} single answer must have exactly one choice.",
                )
            unknown = [cid for cid in item.answer.choice_ids if cid not in choice_ids]
            if unknown:
                raise unprocessable(
                    "quiz_answer_invalid",
                    f"Item {item.id} answer references unknown choices.",
                )
        else:
            # Subjective: answer.rubric optional in v1 (AI grading out).
            if item.choices:
                raise unprocessable(
                    "quiz_item_choices_invalid",
                    f"Item {item.id} text items must not include choices.",
                )


def build_document_dict(
    *,
    quiz_id: str,
    group_id: str | None,
    title: str,
    locale: str,
    status: str,
    settings: QuizSettings,
    items: list[QuizItemTeacher],
) -> dict[str, Any]:
    validate_teacher_items(items)
    doc = QuizDocumentTeacher(
        schema_version=1,
        quiz_id=quiz_id,  # type: ignore[arg-type]
        group_id=group_id,  # type: ignore[arg-type]
        title=title,
        locale=locale,
        status=status,  # type: ignore[arg-type]
        settings=settings,
        items=items,
    )
    return json.loads(doc.model_dump_json())


def teacher_items_from_document(document: dict[str, Any]) -> list[QuizItemTeacher]:
    raw_items = document.get("items") or []
    return [QuizItemTeacher.model_validate(item) for item in raw_items]


def settings_from_document(document: dict[str, Any]) -> QuizSettings:
    return QuizSettings.model_validate(document.get("settings") or {})


def strip_answers(document: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of the document with answer/rubric removed from items."""

    items_out: list[dict[str, Any]] = []
    for item in document.get("items") or []:
        if not isinstance(item, dict):
            continue
        cleaned = {key: value for key, value in item.items() if key not in ("answer", "rubric")}
        # Nested rubric under answer already removed with answer; belt-and-suspenders:
        if "answer" in cleaned:
            del cleaned["answer"]
        items_out.append(cleaned)
    return {
        "schema_version": int(document.get("schema_version") or 1),
        "quiz_id": document.get("quiz_id"),
        "group_id": document.get("group_id"),
        "title": document.get("title") or "",
        "locale": document.get("locale") or "en",
        "status": "published",
        "settings": document.get("settings") or {},
        "items": items_out,
    }


def student_document(document: dict[str, Any], *, quiz_id: str) -> QuizDocumentStudent:
    stripped = strip_answers(document)
    stripped["quiz_id"] = quiz_id
    items = [QuizItemStudent.model_validate(item) for item in stripped["items"]]
    return QuizDocumentStudent(
        schema_version=int(stripped.get("schema_version") or 1),
        quiz_id=quiz_id,  # type: ignore[arg-type]
        group_id=stripped.get("group_id"),  # type: ignore[arg-type]
        title=str(stripped.get("title") or ""),
        locale=str(stripped.get("locale") or "en"),
        status="published",
        settings=QuizSettings.model_validate(stripped.get("settings") or {}),
        items=items,
    )


def assert_no_answer_keys(payload: dict[str, Any]) -> None:
    """Raise if a student-facing payload still contains answer/rubric keys."""

    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        if "answer" in item or "rubric" in item:
            raise unprocessable(
                "quiz_answer_leak",
                "Student quiz projection must not include answer or rubric.",
            )
        nested = item.get("answer")
        if isinstance(nested, dict) and "rubric" in nested:
            raise unprocessable(
                "quiz_answer_leak",
                "Student quiz projection must not include answer or rubric.",
            )
