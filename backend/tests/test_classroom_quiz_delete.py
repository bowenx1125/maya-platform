"""Owner 2026-11-08: deleting a quiz deletes it for good, with its Record."""

# The Quiz API suite's sign-in fixtures are imported, then named as test
# parameters, which is how pytest injects them.
# ruff: noqa: F811

from __future__ import annotations

from app.core.db import Database
from app.modules.quiz.models import ClassroomQuiz, ClassroomQuizAttempt
from app.seed import COURSE_ID
from sqlalchemy import func, select

from tests.test_classroom_quiz_api import (  # noqa: F401
    Actor,
    _create_publish_open,
    _submit,
    actors,
    student,
    teacher,
)


def _delete(actor: Actor, quiz_id: str):
    return actor.client.delete(
        f"/api/v1/courses/{COURSE_ID}/quizzes/{quiz_id}", headers=actor.headers
    )


def test_teacher_deletes_a_live_quiz_with_every_attempt(
    teacher: Actor, student: Actor, database: Database
) -> None:
    quiz_id = _create_publish_open(teacher)
    submitted = _submit(quiz_id, student)
    assert submitted.status_code == 201, submitted.text
    attempt_id = submitted.json()["id"]
    graded = teacher.client.put(
        f"/api/v1/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/{attempt_id}/grades",
        json={"grades": [{"item_id": "q3", "points_awarded": 1}]},
        headers=teacher.headers,
    )
    assert graded.status_code == 200, graded.text

    deleted = _delete(teacher, quiz_id)
    assert deleted.status_code == 204, deleted.text

    with database.session() as db:
        assert db.get(ClassroomQuiz, quiz_id) is None
        assert (
            db.scalar(
                select(func.count())
                .select_from(ClassroomQuizAttempt)
                .where(ClassroomQuizAttempt.quiz_id == quiz_id)
            )
            == 0
        )
    # Gone from the teacher list and both Records.
    listed = teacher.get(f"/courses/{COURSE_ID}/quizzes").json()
    assert all(row["id"] != quiz_id for row in listed)
    records = teacher.get(f"/courses/{COURSE_ID}/record-attempts").json()
    assert all(row.get("quiz_id") != quiz_id for row in records)
    own = student.get(f"/courses/{COURSE_ID}/my-record-attempts").json()
    assert all(row.get("quiz_id") != quiz_id for row in own)
    assert teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}").status_code == 404
    # A student still on the page can no longer submit to it.
    assert _submit(quiz_id, student).status_code == 404
    # A second delete finds nothing.
    assert _delete(teacher, quiz_id).status_code == 404


def test_a_draft_deletes_too(teacher: Actor) -> None:
    created = teacher.post(
        f"/courses/{COURSE_ID}/quizzes",
        {
            "title": "Draft only",
            "items": [{"id": "q1", "type": "short_text", "prompt": "Why?", "points": 1}],
        },
    )
    assert created.status_code == 201, created.text
    assert _delete(teacher, created.json()["id"]).status_code == 204


def test_students_cannot_delete_a_quiz(teacher: Actor, student: Actor) -> None:
    quiz_id = _create_publish_open(teacher)
    refused = _delete(student, quiz_id)
    assert refused.status_code in {403, 404}, refused.text
    assert teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}").status_code == 200
