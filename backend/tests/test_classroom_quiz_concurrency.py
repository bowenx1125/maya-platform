"""Classroom Quiz concurrency hardening (M1–M3 self-checks)."""

# Fixtures are imported, then named as test parameters, which is how pytest
# injects them.
# ruff: noqa: F811

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from app.modules.quiz import ai_grade
from app.modules.quiz import service as quiz_service
from app.seed import COURSE_ID
from sqlalchemy.exc import IntegrityError

from tests.test_classroom_quiz_api import (  # noqa: F401
    Actor,
    _create_publish_open,
    _submit,
    actors,
    student,
    teacher,
)


class _FakeOrig(Exception):
    def __init__(self, message: str, constraint_name: str | None = None) -> None:
        super().__init__(message)
        self.diag = type("Diag", (), {"constraint_name": constraint_name})()


def test_integrity_helper_recognizes_unique_constraint() -> None:
    exc = IntegrityError(
        "INSERT",
        {},
        _FakeOrig(
            "duplicate key value violates unique constraint "
            '"ux_classroom_quiz_attempts_quiz_actor_epoch"',
            constraint_name="ux_classroom_quiz_attempts_quiz_actor_epoch",
        ),
    )
    assert quiz_service._is_quiz_attempt_unique_integrity(exc) is True


def test_concurrent_double_submit_one_created_rest_409(teacher: Actor, student: Actor) -> None:
    quiz_id = _create_publish_open(teacher)
    barrier = Barrier(2)
    results: list[int] = []
    lock = threading.Lock()

    def one() -> None:
        barrier.wait(timeout=30)
        response = _submit(quiz_id, student)
        with lock:
            results.append(response.status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(one) for _ in range(2)]
        for future in futures:
            future.result(timeout=60)

    assert sorted(results) == [201, 409]
    again = _submit(quiz_id, student)
    assert again.status_code == 409
    assert again.json()["code"] == "quiz_attempt_exists"


def test_concurrent_double_start_taking_one_open(teacher: Actor) -> None:
    quiz_id = _create_publish_open(teacher)
    paused = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/pause-taking")
    assert paused.status_code == 200, paused.text

    barrier = Barrier(2)
    results: list[tuple[int, Any]] = []
    lock = threading.Lock()

    def one() -> None:
        barrier.wait(timeout=30)
        response = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/start-taking")
        with lock:
            results.append((response.status_code, response.json()))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(one) for _ in range(2)]
        for future in futures:
            future.result(timeout=60)

    codes = sorted(code for code, _ in results)
    assert codes == [200, 409]
    opened = [body for code, body in results if code == 200][0]
    assert opened["taking_open"] is True
    conflicted = [body for code, body in results if code == 409][0]
    assert conflicted["code"] == "quiz_taking_already_open"


def test_queue_stats_expose_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    ai_grade.reset_queue_for_tests()
    monkeypatch.setattr(ai_grade, "llm_configured", lambda: True)
    monkeypatch.setattr(ai_grade, "_ensure_workers", lambda: None)
    assert ai_grade.enqueue_quiz_ai_grade(
        "x",
        session_factory=lambda: None,  # type: ignore[arg-type, return-value]
    )
    stats = ai_grade.queue_stats()
    assert stats["maxdepth"] == 256
    assert stats["workers"] == 2
    assert stats["depth"] == 1
    assert stats["rejected_full"] == 0
    ai_grade.reset_queue_for_tests()
