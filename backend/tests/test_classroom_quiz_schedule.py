"""One-shot schedules fire atomically on reads and in every replica's sweep."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from app.modules.quiz import schedules, service
from app.modules.quiz.models import ClassroomQuiz
from app.modules.quiz.schedules import QuizScheduleSweeper, sweep_due_quiz_schedules
from app.seed import COURSE_ID
from sqlalchemy import inspect

from tests.test_classroom_quiz_api import Actor, _create_and_publish, _create_publish_open, _submit
from tests.test_classroom_quiz_api import actors as actors
from tests.test_classroom_quiz_api import student as student
from tests.test_classroom_quiz_api import teacher as teacher
from tests.test_classroom_quiz_exemption import _path, _paused, _put, _rows, _student_views


def _schedule(actor: Actor, quiz_id: str, start: datetime | None, end: datetime | None) -> Any:
    return actor.client.put(
        f"/api/v1{_path(quiz_id)}/schedule",
        json={
            "start_at": start.isoformat() if start is not None else None,
            "end_at": end.isoformat() if end is not None else None,
        },
        headers=actor.headers,
    )


def _stored(database, quiz_id: str) -> ClassroomQuiz:
    with database.session() as db:
        return db.get(ClassroomQuiz, quiz_id)


def test_schedule_replacement_clearing_and_student_dtos(teacher, student, database) -> None:
    quiz_id = _create_and_publish(teacher)
    start = datetime.now(UTC) + timedelta(hours=1)
    end = start + timedelta(hours=1)
    for starts, ends in [
        (start, None),
        (None, end),
        (start, end),
        (None, end),
        (start, None),
        (None, None),
    ]:
        response = _schedule(teacher, quiz_id, starts, ends)
        assert response.status_code == 200, response.text
        teacher_list = teacher.get(f"/courses/{COURSE_ID}/quizzes").json()[0]
        for view in [response.json(), teacher_list, *_student_views(student, quiz_id)]:
            assert view["scheduled_start_at"] == (
                starts.isoformat().replace("+00:00", "Z") if starts else None
            )
            assert view["scheduled_end_at"] == (
                ends.isoformat().replace("+00:00", "Z") if ends else None
            )
    offset = start.astimezone(timezone(timedelta(hours=8)))
    assert _schedule(teacher, quiz_id, offset, None).status_code == 200
    assert _stored(database, quiz_id).scheduled_start_at == start
    assert teacher.get(_path(quiz_id)).json()["scheduled_start_at"].endswith("Z")


@pytest.mark.parametrize("field", ["start_at", "end_at"])
def test_both_schedule_keys_required(teacher, field) -> None:
    quiz_id = _create_and_publish(teacher)
    response = teacher.client.put(
        f"/api/v1{_path(quiz_id)}/schedule", json={field: None}, headers=teacher.headers
    )
    assert response.status_code == 400
    assert response.json()["code"] == "malformed_request"


@pytest.mark.parametrize("field", ["start", "end"])
@pytest.mark.parametrize("kind", ["naive", "past", "now"])
def test_schedule_time_validation(teacher, monkeypatch, field, kind) -> None:
    quiz_id = _create_and_publish(teacher)
    now = datetime.now(UTC)
    monkeypatch.setattr(service, "_now", lambda: now)
    at = now + timedelta(hours=1)
    if kind == "naive":
        at = at.replace(tzinfo=None)
    else:
        at = now - timedelta(seconds=1) if kind == "past" else now
    response = _schedule(
        teacher, quiz_id, at if field == "start" else None, at if field == "end" else None
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == (
        "quiz_schedule_naive" if kind == "naive" else "quiz_schedule_in_past"
    )
    if kind != "naive":
        assert response.json()["message"] == "Choose a time in the future."
    assert teacher.get(_path(quiz_id)).json()[f"scheduled_{field}_at"] is None


@pytest.mark.parametrize("offset", [-1, 0])
def test_schedule_order_validation_leaves_existing_schedule(teacher, offset) -> None:
    quiz_id = _create_and_publish(teacher)
    start = datetime.now(UTC) + timedelta(hours=1)
    assert _schedule(teacher, quiz_id, start, None).status_code == 200
    response = _schedule(teacher, quiz_id, start, start + timedelta(seconds=offset))
    assert response.status_code == 422
    assert response.json()["code"] == "quiz_schedule_order"
    assert response.json()["message"] == "The end time must be after the start time."
    assert teacher.get(_path(quiz_id)).json()["scheduled_start_at"] is not None


def test_schedule_authorization_publication_unknown_and_csrf(teacher, student) -> None:
    quiz_id = _create_and_publish(teacher)
    at = datetime.now(UTC) + timedelta(hours=1)
    assert _schedule(student, quiz_id, at, None).status_code in (403, 404)
    assert _schedule(teacher, str(uuid4()), at, None).status_code == 404
    response = teacher.client.put(
        f"/api/v1{_path(quiz_id)}/schedule",
        json={"start_at": None, "end_at": None},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 403
    assert teacher.post(f"{_path(quiz_id)}/unpublish").status_code == 200
    response = _schedule(teacher, quiz_id, at, None)
    assert response.status_code == 409
    assert response.json()["code"] == "quiz_not_published"
    assert response.json()["message"] == "The quiz is not published."


def test_due_start_opens_new_epoch_clears_exemptions_allows_retake(
    teacher, student, actors, database, monkeypatch
) -> None:
    quiz_id = _create_publish_open(teacher)
    assert _submit(quiz_id, student).status_code == 201
    assert teacher.post(f"{_path(quiz_id)}/pause-taking").status_code == 200
    assert _put(teacher, quiz_id, [actors("jade").id]).status_code == 200
    at = datetime.now(UTC) + timedelta(minutes=1)
    assert _schedule(teacher, quiz_id, at, None).status_code == 200
    monkeypatch.setattr(service, "_now", lambda: at)
    # The submit gate itself must fire a start when the loop has not run.
    response = _submit(quiz_id, student)
    assert response.status_code == 201, response.text
    assert response.json()["taking_epoch"] == 2
    quiz = _stored(database, quiz_id)
    assert quiz.taking_open is True
    assert quiz.scheduled_start_at is None
    assert _rows(database, quiz_id) == []


def test_due_end_keeps_epoch_and_exemptions(teacher, student, database, monkeypatch) -> None:
    quiz_id = _create_publish_open(teacher)
    assert _put(teacher, quiz_id, [student.id]).status_code == 200
    at = datetime.now(UTC) + timedelta(minutes=1)
    assert _schedule(teacher, quiz_id, None, at).status_code == 200
    monkeypatch.setattr(service, "_now", lambda: at)
    detail = student.get(_path(quiz_id)).json()
    assert detail["taking_open"] is False
    assert detail["taking_epoch"] == 1
    assert detail["scheduled_end_at"] is None
    assert detail["can_take_now"] is True
    assert len(_rows(database, quiz_id)) == 1
    assert _submit(quiz_id, student).status_code == 201


def test_both_due_finish_paused_in_new_epoch(teacher, database) -> None:
    quiz_id = _create_and_publish(teacher)
    start = datetime.now(UTC) + timedelta(minutes=1)
    end = start + timedelta(minutes=1)
    assert _schedule(teacher, quiz_id, start, end).status_code == 200
    assert sweep_due_quiz_schedules(database.session_factory, end) == 1
    quiz = _stored(database, quiz_id)
    assert quiz.taking_epoch == 1
    assert quiz.taking_open is False
    assert quiz.scheduled_start_at is None
    assert quiz.scheduled_end_at is None
    assert sweep_due_quiz_schedules(database.session_factory, end) == 0


def test_manual_actions_cancel_only_corresponding_schedule(teacher, database) -> None:
    quiz_id = _create_and_publish(teacher)
    start = datetime.now(UTC) + timedelta(hours=1)
    end = start + timedelta(hours=1)
    assert _schedule(teacher, quiz_id, start, end).status_code == 200
    response = teacher.post(f"{_path(quiz_id)}/start-taking")
    assert response.status_code == 200
    assert response.json()["scheduled_start_at"] is None
    assert datetime.fromisoformat(response.json()["scheduled_end_at"]) == end
    assert _schedule(teacher, quiz_id, start, end).status_code == 200
    response = teacher.post(f"{_path(quiz_id)}/pause-taking")
    assert response.status_code == 200
    assert datetime.fromisoformat(response.json()["scheduled_start_at"]) == start
    assert response.json()["scheduled_end_at"] is None
    assert _stored(database, quiz_id).taking_epoch == 1


@pytest.mark.parametrize("already_open", [False, True])
def test_due_redundant_action_is_cleared_without_epoch_change(
    teacher, database, already_open
) -> None:
    quiz_id = _create_publish_open(teacher) if already_open else _paused(teacher)
    at = datetime.now(UTC) + timedelta(minutes=1)
    assert (
        _schedule(
            teacher, quiz_id, at if already_open else None, None if already_open else at
        ).status_code
        == 200
    )
    assert sweep_due_quiz_schedules(database.session_factory, at) == 1
    quiz = _stored(database, quiz_id)
    assert quiz.taking_epoch == 1
    assert quiz.taking_open is already_open
    assert quiz.scheduled_start_at is None
    assert quiz.scheduled_end_at is None


@pytest.mark.parametrize("action", ["start", "end"])
def test_draft_due_schedule_is_skipped_and_never_revived(
    teacher, database, monkeypatch, action
) -> None:
    quiz_id = _create_publish_open(teacher)
    at = datetime.now(UTC) + timedelta(minutes=1)
    assert (
        _schedule(
            teacher, quiz_id, at if action == "start" else None, at if action == "end" else None
        ).status_code
        == 200
    )
    assert teacher.post(f"{_path(quiz_id)}/unpublish").status_code == 200
    assert getattr(_stored(database, quiz_id), f"scheduled_{action}_at") == at
    assert sweep_due_quiz_schedules(database.session_factory, at) == 1
    quiz = _stored(database, quiz_id)
    assert quiz.status == "draft"
    assert quiz.taking_epoch == 1
    assert quiz.taking_open is False
    assert getattr(quiz, f"scheduled_{action}_at") is None
    monkeypatch.setattr(service, "_now", lambda: at)
    assert teacher.post(f"{_path(quiz_id)}/publish").status_code == 200
    assert teacher.get(_path(quiz_id)).json()["taking_open"] is False


@pytest.mark.parametrize(
    "read",
    [
        "detail",
        "list",
        "exemptions",
        "grant",
        "delete",
        "clear",
        "schedule",
        "manual_start",
        "manual_pause",
    ],
)
def test_lazy_paths_apply_due_before_read_or_mutation(
    teacher, student, database, monkeypatch, read
) -> None:
    quiz_id = _paused(teacher)
    at = datetime.now(UTC) + timedelta(minutes=1)
    assert _schedule(teacher, quiz_id, at, None).status_code == 200
    monkeypatch.setattr(service, "_now", lambda: at)
    if read == "detail":
        response = student.get(_path(quiz_id))
        assert response.json()["can_take_now"] is True
    elif read == "list":
        response = student.get(f"/courses/{COURSE_ID}/quizzes")
        assert response.json()[0]["can_take_now"] is True
    elif read == "exemptions":
        response = teacher.get(f"{_path(quiz_id)}/exemptions")
        assert response.json()["taking_epoch"] == 2
    elif read == "grant":
        response = _put(teacher, quiz_id, [student.id])
        assert response.json()["taking_epoch"] == 2
    elif read in ("delete", "clear"):
        suffix = f"/{student.id}" if read == "delete" else ""
        response = teacher.client.delete(
            f"/api/v1{_path(quiz_id)}/exemptions{suffix}", headers=teacher.headers
        )
    elif read == "schedule":
        response = _schedule(teacher, quiz_id, None, at + timedelta(hours=1))
    else:
        action = "start-taking" if read == "manual_start" else "pause-taking"
        response = teacher.post(f"{_path(quiz_id)}/{action}")
    assert response.status_code == (
        409 if read == "manual_start" else 204 if read in ("delete", "clear") else 200
    ), response.text
    quiz = _stored(database, quiz_id)
    assert quiz.taking_epoch == 2
    assert quiz.taking_open is (read != "manual_pause")
    assert quiz.scheduled_start_at is None


def test_late_end_blocks_nonexempt_submit(teacher, student, monkeypatch) -> None:
    quiz_id = _create_publish_open(teacher)
    at = datetime.now(UTC) + timedelta(minutes=1)
    assert _schedule(teacher, quiz_id, None, at).status_code == 200
    monkeypatch.setattr(service, "_now", lambda: at)
    response = _submit(quiz_id, student)
    assert response.status_code == 409
    assert response.json()["code"] == "quiz_taking_closed"


def test_sweep_counts_only_due_quizzes_and_continues_after_failure(
    teacher, database, monkeypatch, caplog
) -> None:
    ids = [_create_and_publish(teacher) for _ in range(3)]
    at = datetime.now(UTC) + timedelta(minutes=1)
    for quiz_id in ids[:2]:
        assert _schedule(teacher, quiz_id, at, None).status_code == 200
    assert _schedule(teacher, ids[2], at + timedelta(hours=1), None).status_code == 200
    original = service.apply_due_schedules

    def apply(db, quiz_id, now):
        if quiz_id == ids[0]:
            raise RuntimeError("private exception contents must not be logged")
        return original(db, quiz_id, now)

    monkeypatch.setattr(service, "apply_due_schedules", apply)
    assert sweep_due_quiz_schedules(database.session_factory, at) == 1
    assert "quiz_schedule_apply_failed" in caplog.text
    assert "private exception contents" not in caplog.text
    monkeypatch.setattr(service, "apply_due_schedules", original)
    assert sweep_due_quiz_schedules(database.session_factory, at) == 1
    assert sweep_due_quiz_schedules(database.session_factory, at) == 0
    assert _stored(database, ids[2]).taking_epoch == 0


@pytest.mark.parametrize("use_sweep", [False, True])
def test_concurrent_firing_has_one_effect(teacher, database, use_sweep) -> None:
    quiz_id = _create_and_publish(teacher)
    at = datetime.now(UTC) + timedelta(minutes=1)
    assert _schedule(teacher, quiz_id, at, None).status_code == 200
    barrier = threading.Barrier(4)

    def fire():
        if use_sweep:
            barrier.wait(timeout=30)
            return sweep_due_quiz_schedules(database.session_factory, at)
        with database.session() as db:
            # Every contender holds the same stale pre-fire object; the lock must re-read it.
            quiz = db.get(ClassroomQuiz, quiz_id)
            assert quiz is not None
            barrier.wait(timeout=30)
            return int(service.apply_due_schedules(db, quiz_id, at))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fire) for _ in range(4)]
        results = [future.result(timeout=60) for future in futures]
    assert sum(results) == 1
    quiz = _stored(database, quiz_id)
    assert quiz.taking_epoch == 1
    assert quiz.taking_open is True
    assert quiz.scheduled_start_at is None
    assert sweep_due_quiz_schedules(database.session_factory, at) == 0


def test_schedule_model_matches_migration(database) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    database.upgrade_schema()
    with database.engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "include_object": lambda obj, name, kind, reflected, compare_to: (
                    name == "classroom_quizzes" if kind == "table" else True
                )
            },
        )
        assert compare_metadata(context, ClassroomQuiz.metadata) == []
        indexes = {item["name"] for item in inspect(connection).get_indexes("classroom_quizzes")}
        assert {
            "ix_classroom_quizzes_scheduled_start",
            "ix_classroom_quizzes_scheduled_end",
        } <= indexes


def test_sweeper_thread_stops_and_test_app_does_not_start_it(teacher, monkeypatch) -> None:
    calls = threading.Event()
    monkeypatch.setattr(schedules, "SWEEP_SECONDS", 0.01)
    monkeypatch.setattr(schedules, "sweep_due_quiz_schedules", lambda factory: calls.set())
    sweeper = QuizScheduleSweeper(lambda: None)
    sweeper.start()
    thread = sweeper._thread
    sweeper.start()
    assert thread is sweeper._thread
    assert calls.wait(timeout=2)
    sweeper.close()
    assert not thread.is_alive()
    assert not any(t.name == "maya-quiz-schedules" for t in threading.enumerate())


@pytest.mark.parametrize("action", ["start", "end"])
def test_republish_does_not_revive_overdue_draft_schedule(
    teacher, database, monkeypatch, action
) -> None:
    quiz_id = _paused(teacher)
    at = datetime.now(UTC) + timedelta(minutes=1)
    assert (
        _schedule(
            teacher, quiz_id, at if action == "start" else None, at if action == "end" else None
        ).status_code
        == 200
    )
    assert teacher.post(f"{_path(quiz_id)}/unpublish").status_code == 200
    monkeypatch.setattr(service, "_now", lambda: at)
    response = teacher.post(f"{_path(quiz_id)}/publish")
    assert response.status_code == 200, response.text
    assert response.json()["scheduled_start_at"] is None
    assert response.json()["scheduled_end_at"] is None
    assert response.json()["taking_open"] is False
    assert response.json()["taking_epoch"] == 1
    assert sweep_due_quiz_schedules(database.session_factory, at) == 0
