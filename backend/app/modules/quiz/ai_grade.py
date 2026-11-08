"""Asynchronous AI grading for classroom quiz text items.

Submit never calls an LLM. Work is enqueued after commit and runs under a
process-wide semaphore so at most two attempts are graded at once.
"""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .document import loads_document, teacher_items_from_document
from .models import ClassroomQuizAttempt

TEXT_TYPES = ("short_text", "long_text")

_WORKER_LIMIT = threading.Semaphore(2)
_grade_fn: Callable[..., float] | None = None


def default_llm_callable(
    prompt: str,
    rules: str,
    text: str,
    score_min: float,
    score_max: float,
) -> float:
    """Production default: no-op unless a caller injects a callable.

    Wiring DashScope here would pull provider config, secrets, and HTTP into
    the quiz module. Leave the item pending when nothing is injected.
    """

    raise RuntimeError("quiz AI grading LLM is not configured")


def enqueue_quiz_ai_grade(
    attempt_id: str,
    *,
    runner: Callable[..., Any] | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """Schedule background grading without invoking an LLM on this thread."""

    work = runner or run_quiz_ai_grade

    def _target() -> None:
        if work is run_quiz_ai_grade:
            work(attempt_id, session_factory=session_factory)
        else:
            work(attempt_id)

    thread = threading.Thread(
        target=_target,
        name=f"quiz-ai-grade-{attempt_id}",
        daemon=True,
    )
    thread.start()


def run_quiz_ai_grade(
    attempt_id: str,
    *,
    llm_callable: Callable[..., float] | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """Grade pending AI text items for one attempt and persist the results."""

    _WORKER_LIMIT.acquire()
    try:
        if session_factory is None:
            return
        with session_factory() as db:
            _grade_attempt_in_session(db, attempt_id, llm_callable=llm_callable)
    finally:
        _WORKER_LIMIT.release()


def _grade_attempt_in_session(
    db: Session,
    attempt_id: str,
    *,
    llm_callable: Callable[..., float] | None,
) -> None:
    from .service import _compute_score_manual, _grading_status, _manual_grades

    attempt = db.scalar(
        select(ClassroomQuizAttempt).where(ClassroomQuizAttempt.id == attempt_id).with_for_update()
    )
    if attempt is None:
        return

    items = teacher_items_from_document(loads_document(attempt.document_snapshot_json))
    raw_answers = json.loads(attempt.answers_json)
    if not isinstance(raw_answers, list):
        return
    answers_by_id = {
        str(row.get("item_id")): row
        for row in raw_answers
        if isinstance(row, dict) and row.get("item_id") is not None
    }
    grade_fn = llm_callable or _grade_fn or default_llm_callable

    for item in items:
        if item.type not in TEXT_TYPES:
            continue
        grading = item.grading
        if grading is None or grading.mode != "ai":
            continue
        entry = answers_by_id.get(item.id)
        if entry is None or entry.get("ai_score") is not None:
            continue
        if grading.score_min is None or grading.score_max is None:
            continue
        lo = float(grading.score_min)
        hi = float(grading.score_max)
        try:
            raw_score = grade_fn(
                prompt=item.prompt,
                rules=(grading.rules or "").strip(),
                text=str(entry.get("text") or ""),
                score_min=lo,
                score_max=hi,
            )
            score = float(raw_score)
            if not math.isfinite(score):
                continue
            score = min(max(score, lo), hi)
        except Exception:
            continue
        entry["ai_score"] = score
        entry["points_awarded"] = score

    grades = _manual_grades(attempt)
    attempt.answers_json = json.dumps(raw_answers, ensure_ascii=False, separators=(",", ":"))
    attempt.score_manual = _compute_score_manual(items, grades, answers_by_id)
    attempt.grading_status = _grading_status(items, grades, answers_by_id)
    if attempt.grading_status == "complete" and attempt.graded_at is None:
        attempt.graded_at = datetime.now(UTC)
    db.commit()
