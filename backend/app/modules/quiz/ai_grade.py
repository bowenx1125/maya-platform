"""Asynchronous AI grading for classroom quiz text items.

Submit never calls an LLM. Work is enqueued after commit and runs under a
process-wide semaphore so at most two attempts are graded at once.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings

from .document import loads_document, teacher_items_from_document
from .models import ClassroomQuizAttempt

TEXT_TYPES = ("short_text", "long_text")

# At most two gradings at once on a 2-core server; the queue holds the rest.
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="quiz-ai-grade")
_LOG = logging.getLogger("maya.quiz.ai_grade")
_grade_fn: Callable[..., float] | None = None

_SCORE_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def default_llm_callable(
    prompt: str,
    rules: str,
    text: str,
    score_min: float,
    score_max: float,
) -> float:
    """Call DashScope chat/completions and return a numeric score.

    Uses the same settings keys as production LLM (prefer
    ``DASHSCOPE_CHAT_API_KEY`` when set, else ``DASHSCOPE_API_KEY``). Endpoint
    comes from ``DashScopeLLMConfig.resolved_endpoint`` (llm_adapter), so this
    module never embeds a supplier host. Raises when credentials/region are
    missing or the HTTP/parse path fails; the worker catches that and leaves
    the item pending.
    """

    from app.providers.llm_adapter import DashScopeLLMConfig, LLMAdapterError

    settings = get_settings()
    chat_key = (settings.dashscope_chat_api_key or "").strip()
    api_key = chat_key or (settings.dashscope_api_key or "").strip()
    workspace_id = (settings.dashscope_workspace_id or "").strip()
    region = (settings.dashscope_region or "").strip()
    model_key = (settings.llm_model or "").strip()
    if not api_key or not workspace_id or not model_key or region != "cn-beijing":
        raise RuntimeError("quiz AI grading LLM is not configured")

    try:
        config = DashScopeLLMConfig(
            api_key=api_key,
            workspace_id=workspace_id,
            region=region,
            model_key=model_key,
        )
        endpoint = config.resolved_endpoint
    except LLMAdapterError as exc:
        raise RuntimeError("quiz AI grading LLM is not configured") from exc

    user_content = (
        "Grade the student answer. Return ONLY JSON of the form "
        '{"score": <number>} with no other text.\n'
        f"score_min={score_min}\n"
        f"score_max={score_max}\n"
        f"prompt:\n{prompt}\n"
        f"rules:\n{rules}\n"
        f"student_answer:\n{text}\n"
    )
    payload = {
        "model": config.model,
        "messages": [{"role": "user", "content": user_content}],
        "temperature": 0,
    }
    response = httpx.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60.0,
    )
    response.raise_for_status()
    body = response.json()
    content = body["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise RuntimeError("quiz AI grading LLM returned non-text content")
    return _parse_score_from_content(content)


def _parse_score_from_content(content: str) -> float:
    stripped = content.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict) and "score" in parsed:
        return float(parsed["score"])
    # Models sometimes wrap JSON in fences or prose; try a JSON object slice.
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and "score" in parsed:
            return float(parsed["score"])
    match = _SCORE_NUMBER_RE.search(stripped)
    if match is None:
        raise RuntimeError("quiz AI grading LLM response had no score")
    return float(match.group(0))


def llm_configured() -> bool:
    """True when the settings default_llm_callable needs are all present."""

    settings = get_settings()
    api_key = (settings.dashscope_chat_api_key or "").strip() or (
        settings.dashscope_api_key or ""
    ).strip()
    return bool(
        api_key
        and (settings.dashscope_workspace_id or "").strip()
        and (settings.llm_model or "").strip()
        and (settings.dashscope_region or "").strip() == "cn-beijing"
    )


def enqueue_quiz_ai_grade(
    attempt_id: str,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """Hand one attempt to the grading pool and return at once.

    Runs as a request background task. It must not wait on the pool: request
    handlers share the server's worker threads, and a class submitting
    together would otherwise park them all behind two slow LLM calls. The
    pool runs at most two gradings; the rest wait in its in-memory queue. A
    restart drops that queue and the items stay pending, which the teacher
    can still grade by hand.
    """

    if session_factory is None or (_grade_fn is None and not llm_configured()):
        # No LLM in this environment (tests, mock demo): stay pending.
        return
    _POOL.submit(_run_logged, attempt_id, session_factory)


def _run_logged(attempt_id: str, session_factory: Callable[[], Session]) -> None:
    try:
        run_quiz_ai_grade(attempt_id, session_factory=session_factory)
    except Exception:  # pragma: no cover - keep the pool thread alive
        _LOG.exception("quiz AI grading failed for attempt %s", attempt_id)


def run_quiz_ai_grade(
    attempt_id: str,
    *,
    llm_callable: Callable[..., float] | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """Grade pending AI text items for one attempt and persist the results.

    Three short steps so no row lock or transaction is held while the LLM
    answers (up to a minute per item): read what needs scoring, call the LLM
    with no transaction open, then lock the row and write only the items that
    still have neither an AI score nor a teacher grade.
    """

    if session_factory is None:
        return
    with session_factory() as db:
        pending = _pending_items(db, attempt_id)
    if not pending:
        return
    grade_fn = llm_callable or _grade_fn or default_llm_callable
    scores: dict[str, float] = {}
    for item_id, prompt, rules, text, lo, hi in pending:
        try:
            score = float(
                grade_fn(prompt=prompt, rules=rules, text=text, score_min=lo, score_max=hi)
            )
        except Exception:
            continue
        if math.isfinite(score):
            scores[item_id] = min(max(score, lo), hi)
    if not scores:
        return
    with session_factory() as db:
        _write_scores(db, attempt_id, scores)


def _pending_items(db: Session, attempt_id: str) -> list[tuple[str, str, str, str, float, float]]:
    from .service import _manual_grades

    attempt = db.get(ClassroomQuizAttempt, attempt_id)
    if attempt is None:
        return []
    items = teacher_items_from_document(loads_document(attempt.document_snapshot_json))
    answers = _answers_by_item(attempt.answers_json)
    grades = _manual_grades(attempt)
    pending: list[tuple[str, str, str, str, float, float]] = []
    for item in items:
        grading = item.grading
        if item.type not in TEXT_TYPES or grading is None or grading.mode != "ai":
            continue
        entry = answers.get(item.id)
        if entry is None or entry.get("ai_score") is not None or item.id in grades:
            continue
        if grading.score_min is None or grading.score_max is None:
            continue
        pending.append(
            (
                item.id,
                item.prompt,
                (grading.rules or "").strip(),
                str(entry.get("text") or ""),
                float(grading.score_min),
                float(grading.score_max),
            )
        )
    return pending


def _write_scores(db: Session, attempt_id: str, scores: dict[str, float]) -> None:
    from .service import _compute_score_manual, _grading_status, _manual_grades

    attempt = db.scalar(
        select(ClassroomQuizAttempt).where(ClassroomQuizAttempt.id == attempt_id).with_for_update()
    )
    if attempt is None:
        return
    raw_answers = json.loads(attempt.answers_json)
    if not isinstance(raw_answers, list):
        return
    answers = {
        str(row.get("item_id")): row
        for row in raw_answers
        if isinstance(row, dict) and row.get("item_id") is not None
    }
    for item_id, score in scores.items():
        entry = answers.get(item_id)
        if entry is None or entry.get("ai_score") is not None:
            continue
        entry["ai_score"] = score
        entry["points_awarded"] = score
    items = teacher_items_from_document(loads_document(attempt.document_snapshot_json))
    grades = _manual_grades(attempt)
    attempt.answers_json = json.dumps(raw_answers, ensure_ascii=False, separators=(",", ":"))
    attempt.score_manual = _compute_score_manual(items, grades, answers)
    attempt.grading_status = _grading_status(items, grades, answers)
    if attempt.grading_status == "complete" and attempt.graded_at is None:
        attempt.graded_at = datetime.now(UTC)
    db.commit()


def _answers_by_item(answers_json: str) -> dict[str, dict[str, Any]]:
    raw = json.loads(answers_json)
    if not isinstance(raw, list):
        return {}
    return {
        str(row.get("item_id")): row
        for row in raw
        if isinstance(row, dict) and row.get("item_id") is not None
    }
