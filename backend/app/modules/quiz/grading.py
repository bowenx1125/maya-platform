"""Objective grading for classroom quizzes — no LLM."""

from __future__ import annotations

from typing import Any

from .schemas import QuizAnswerSubmission, QuizItemTeacher


def _as_choice_set(values: list[str] | None) -> set[str]:
    return {str(v) for v in (values or [])}


def grade_objective(
    items: list[QuizItemTeacher],
    answers: list[QuizAnswerSubmission],
) -> tuple[float, float, str, list[dict[str, Any]]]:
    """Return (score, score_max, grading_status, normalized_answers).

    single/multiple: unordered set equality.
    short_text/long_text: stored only; contribute to pending/mixed.
    """

    by_id = {item.id: item for item in items}
    answered = {row.item_id: row for row in answers}
    score = 0.0
    score_max = 0.0
    has_objective = False
    has_pending = False
    normalized: list[dict[str, Any]] = []

    for item in items:
        points = float(item.points)
        submission = answered.get(item.id)
        entry: dict[str, Any] = {"item_id": item.id, "type": item.type, "points": points}

        if item.type in ("single", "multiple"):
            has_objective = True
            score_max += points
            expected = _as_choice_set(item.answer.choice_ids if item.answer is not None else None)
            got = _as_choice_set(submission.choice_ids if submission else None)
            correct = got == expected and len(expected) > 0
            if correct:
                score += points
            entry["choice_ids"] = sorted(got)
            entry["correct"] = correct
            entry["points_awarded"] = points if correct else 0.0
        else:
            has_pending = True
            text = "" if submission is None or submission.text is None else submission.text
            entry["text"] = text
            entry["correct"] = None
            entry["points_awarded"] = None

        normalized.append(entry)

    # Answers for unknown item ids are ignored for scoring but retained.
    for item_id, submission in answered.items():
        if item_id in by_id:
            continue
        normalized.append(
            {
                "item_id": item_id,
                "type": "unknown",
                "choice_ids": submission.choice_ids,
                "text": submission.text,
                "correct": None,
                "points_awarded": None,
            }
        )

    if has_objective and has_pending:
        grading_status = "mixed"
    elif has_pending and not has_objective:
        grading_status = "pending"
    else:
        grading_status = "complete"

    return score, score_max, grading_status, normalized
