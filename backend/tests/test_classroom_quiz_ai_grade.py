"""Classroom Quiz AI grading (contract B): validation, strip, async worker."""

# The Quiz API suite's sign-in fixtures are imported, then named as test
# parameters, which is how pytest injects them.
# ruff: noqa: F811

from __future__ import annotations

import json
from typing import Any

import pytest
from app.core.db import Database
from app.modules.quiz.ai_grade import run_quiz_ai_grade
from app.modules.quiz.models import ClassroomQuizAttempt
from app.seed import COURSE_ID

from tests.test_classroom_quiz_api import (  # noqa: F401
    Actor,
    actors,
    student,
    teacher,
)


def _ai_item(**grading_overrides: Any) -> dict[str, Any]:
    grading: dict[str, Any] = {
        "mode": "ai",
        "score_min": 0,
        "score_max": 5,
        "rules": "Award points for mentioning decoupling.",
    }
    grading.update(grading_overrides)
    return {
        "id": "q_ai",
        "type": "short_text",
        "required": True,
        "prompt": "Name one reason to use a queue.",
        "points": 5,
        "grading": grading,
    }


def _manual_text_item() -> dict[str, Any]:
    return {
        "id": "q_manual",
        "type": "short_text",
        "required": True,
        "prompt": "Define idempotency.",
        "answer": {"rubric": "Mentions repeating safely."},
        "points": 2,
    }


def _choice_item() -> dict[str, Any]:
    return {
        "id": "q_choice",
        "type": "single",
        "required": True,
        "prompt": "Which layer handles auth?",
        "choices": [
            {"id": "a", "label": "API gateway"},
            {"id": "b", "label": "Database"},
        ],
        "answer": {"choice_ids": ["a"]},
        "points": 1,
    }


def _assert_grading_invalid(response: Any) -> None:
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "quiz_grading_invalid"


def test_ai_mode_missing_rules_returns_422(teacher: Actor) -> None:
    created = teacher.post(
        f"/courses/{COURSE_ID}/quizzes",
        {"title": "AI missing rules", "items": [_ai_item(rules="")]},
    )
    _assert_grading_invalid(created)


def test_ai_mode_missing_score_bounds_returns_422(teacher: Actor) -> None:
    missing_min = _ai_item()
    del missing_min["grading"]["score_min"]
    _assert_grading_invalid(
        teacher.post(
            f"/courses/{COURSE_ID}/quizzes",
            {"title": "AI missing min", "items": [missing_min]},
        )
    )
    missing_max = _ai_item()
    del missing_max["grading"]["score_max"]
    _assert_grading_invalid(
        teacher.post(
            f"/courses/{COURSE_ID}/quizzes",
            {"title": "AI missing max", "items": [missing_max]},
        )
    )


def test_ai_mode_invalid_range_returns_422(teacher: Actor) -> None:
    _assert_grading_invalid(
        teacher.post(
            f"/courses/{COURSE_ID}/quizzes",
            {"title": "AI min>max", "items": [_ai_item(score_min=4, score_max=1)]},
        )
    )
    _assert_grading_invalid(
        teacher.post(
            f"/courses/{COURSE_ID}/quizzes",
            {"title": "AI max>points", "items": [_ai_item(score_max=9)]},
        )
    )
    _assert_grading_invalid(
        teacher.post(
            f"/courses/{COURSE_ID}/quizzes",
            {"title": "AI min<0", "items": [_ai_item(score_min=-1)]},
        )
    )
    # NaN is not JSON-serializable over HTTP; validate the document layer directly.
    from app.core.errors import PlatformError
    from app.modules.quiz.document import validate_teacher_items
    from app.modules.quiz.schemas import QuizItemTeacher

    nan_item = QuizItemTeacher.model_validate(_ai_item(score_min=0))
    assert nan_item.grading is not None
    nan_item.grading.score_min = float("nan")
    with pytest.raises(PlatformError) as exc_info:
        validate_teacher_items([nan_item])
    assert exc_info.value.code == "quiz_grading_invalid"
    assert exc_info.value.status_code == 422


def test_manual_mode_and_absent_grading_still_publish(teacher: Actor) -> None:
    items = [
        {
            "id": "q1",
            "type": "short_text",
            "required": True,
            "prompt": "Explain a queue.",
            "points": 3,
        },
        {
            "id": "q2",
            "type": "short_text",
            "required": True,
            "prompt": "Explain a lock.",
            "points": 3,
            "grading": {"mode": "manual"},
        },
    ]
    created = teacher.post(
        f"/courses/{COURSE_ID}/quizzes",
        {"title": "Manual text", "items": items},
    )
    assert created.status_code == 201, created.text
    quiz_id = created.json()["id"]
    published = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"


def test_student_get_strips_grading_and_answer(teacher: Actor, student: Actor) -> None:
    created = teacher.post(
        f"/courses/{COURSE_ID}/quizzes",
        {"title": "AI paper", "items": [_ai_item()]},
    )
    assert created.status_code == 201, created.text
    quiz_id = created.json()["id"]
    assert created.json()["items"][0]["grading"]["mode"] == "ai"
    published = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/publish")
    assert published.status_code == 200, published.text

    response = student.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}")
    assert response.status_code == 200, response.text
    assert '"grading"' not in response.text
    assert '"answer"' not in response.text
    assert '"rubric"' not in response.text
    for item in response.json()["items"]:
        assert "grading" not in item
        assert "answer" not in item
        assert "rubric" not in item


def _create_publish_open(teacher: Actor, items: list[dict[str, Any]]) -> str:
    created = teacher.post(
        f"/courses/{COURSE_ID}/quizzes",
        {"title": "AI live", "items": items},
    )
    assert created.status_code == 201, created.text
    quiz_id = created.json()["id"]
    assert teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/publish").status_code == 200
    opened = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/start-taking")
    assert opened.status_code == 200, opened.text
    return quiz_id


def test_submit_does_not_call_llm(teacher: Actor, student: Actor) -> None:
    calls: list[float] = []

    def mock_llm(**_kwargs: Any) -> float:
        calls.append(1.0)
        return 4.0

    quiz_id = _create_publish_open(teacher, [_ai_item()])
    submitted = student.post(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts",
        {"answers": [{"item_id": "q_ai", "text": "Decouple producers"}]},
    )
    assert submitted.status_code == 201, submitted.text
    assert mock_llm is not None
    assert calls == []
    body = submitted.json()
    assert body["grading_status"] == "pending"
    assert calls == []


def test_worker_writes_clamped_ai_score_and_updates_status(
    teacher: Actor, student: Actor, database: Database
) -> None:
    quiz_id = _create_publish_open(teacher, [_ai_item()])
    submitted = student.post(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts",
        {"answers": [{"item_id": "q_ai", "text": "Decouple producers"}]},
    )
    assert submitted.status_code == 201, submitted.text
    attempt_id = submitted.json()["id"]
    assert submitted.json()["grading_status"] == "pending"

    calls = {"n": 0}

    def mock_llm(**_kwargs: Any) -> float:
        calls["n"] += 1
        return 4.0

    run_quiz_ai_grade(
        attempt_id,
        llm_callable=mock_llm,
        session_factory=database.session_factory,
    )
    assert calls["n"] == 1

    with database.session() as db:
        attempt = db.get(ClassroomQuizAttempt, attempt_id)
        assert attempt is not None
        answers = json.loads(attempt.answers_json)
        entry = next(row for row in answers if row["item_id"] == "q_ai")
        assert entry["ai_score"] == 4.0
        assert entry["points_awarded"] == 4.0
        assert attempt.grading_status == "complete"
        assert attempt.score_manual == 4.0

    detail = student.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/{attempt_id}")
    assert detail.status_code == 200, detail.text
    item = {row["id"]: row for row in detail.json()["items"]}["q_ai"]
    assert item["graded"] is True
    assert item["points_awarded"] == 4.0
    assert "grading" not in item


def test_worker_keeps_pending_when_manual_text_remains(
    teacher: Actor, student: Actor, database: Database
) -> None:
    quiz_id = _create_publish_open(teacher, [_ai_item(), _manual_text_item()])
    submitted = student.post(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts",
        {
            "answers": [
                {"item_id": "q_ai", "text": "Decouple producers"},
                {"item_id": "q_manual", "text": "Retry safely"},
            ]
        },
    )
    assert submitted.status_code == 201, submitted.text
    attempt_id = submitted.json()["id"]
    run_quiz_ai_grade(
        attempt_id,
        llm_callable=lambda **_kwargs: 4.0,
        session_factory=database.session_factory,
    )
    with database.session() as db:
        attempt = db.get(ClassroomQuizAttempt, attempt_id)
        assert attempt is not None
        assert attempt.grading_status == "pending"
        assert attempt.score_manual == 4.0


def test_worker_mixed_when_choice_and_unscored_manual_remain(
    teacher: Actor, student: Actor, database: Database
) -> None:
    quiz_id = _create_publish_open(teacher, [_choice_item(), _ai_item(), _manual_text_item()])
    submitted = student.post(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts",
        {
            "answers": [
                {"item_id": "q_choice", "choice_ids": ["a"]},
                {"item_id": "q_ai", "text": "Decouple producers"},
                {"item_id": "q_manual", "text": "Retry safely"},
            ]
        },
    )
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["grading_status"] == "mixed"
    attempt_id = submitted.json()["id"]
    run_quiz_ai_grade(
        attempt_id,
        llm_callable=lambda **_kwargs: 4.0,
        session_factory=database.session_factory,
    )
    with database.session() as db:
        attempt = db.get(ClassroomQuizAttempt, attempt_id)
        assert attempt is not None
        assert attempt.grading_status == "mixed"


def test_worker_clamps_scores_to_configured_range(
    teacher: Actor, student: Actor, database: Database
) -> None:
    quiz_id = _create_publish_open(teacher, [_ai_item(score_min=1, score_max=4)])
    high = student.post(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts",
        {"answers": [{"item_id": "q_ai", "text": "too high"}]},
    )
    assert high.status_code == 201, high.text
    run_quiz_ai_grade(
        high.json()["id"],
        llm_callable=lambda **_kwargs: 99,
        session_factory=database.session_factory,
    )
    with database.session() as db:
        attempt = db.get(ClassroomQuizAttempt, high.json()["id"])
        assert attempt is not None
        entry = next(row for row in json.loads(attempt.answers_json) if row["item_id"] == "q_ai")
        assert entry["ai_score"] == 4.0

    # A second student/epoch would be heavier; run clamp-low on a fresh quiz.
    quiz_low = _create_publish_open(teacher, [_ai_item(score_min=1, score_max=4)])
    # Same student cannot submit twice on a new quiz in the same course — new quiz is fine.
    low = student.post(
        f"/courses/{COURSE_ID}/quizzes/{quiz_low}/attempts",
        {"answers": [{"item_id": "q_ai", "text": "too low"}]},
    )
    assert low.status_code == 201, low.text
    run_quiz_ai_grade(
        low.json()["id"],
        llm_callable=lambda **_kwargs: -1,
        session_factory=database.session_factory,
    )
    with database.session() as db:
        attempt = db.get(ClassroomQuizAttempt, low.json()["id"])
        assert attempt is not None
        entry = next(row for row in json.loads(attempt.answers_json) if row["item_id"] == "q_ai")
        assert entry["ai_score"] == 1.0
