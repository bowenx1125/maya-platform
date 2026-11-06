"""Classroom Quiz M1–M3: CRUD, publish gate, student strip, submit grade, Record."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.models import Course, CourseMember
from app.seed import COURSE_ID
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import login

SAMPLE_ITEMS = [
    {
        "id": "q1",
        "type": "single",
        "required": True,
        "prompt": "Which layer handles auth?",
        "choices": [
            {"id": "a", "label": "API gateway"},
            {"id": "b", "label": "Database"},
            {"id": "c", "label": "CDN"},
        ],
        "answer": {"choice_ids": ["a"]},
        "points": 1,
    },
    {
        "id": "q2",
        "type": "multiple",
        "required": True,
        "prompt": "Select all HTTP safe methods.",
        "choices": [
            {"id": "a", "label": "GET"},
            {"id": "b", "label": "POST"},
            {"id": "c", "label": "HEAD"},
        ],
        "answer": {"choice_ids": ["a", "c"]},
        "points": 2,
    },
    {
        "id": "q3",
        "type": "short_text",
        "required": True,
        "prompt": "Name one reason to use a queue.",
        "answer": {"rubric": "Mentions decoupling."},
        "points": 3,
    },
]


class Actor:
    def __init__(self, client: TestClient, username: str) -> None:
        self.client = client
        payload, self.csrf = login(client, username)
        self.id: str = payload["user"]["id"]
        self.headers = {"Origin": "http://testserver", "X-CSRF-Token": self.csrf}

    def get(self, path: str) -> Any:
        return self.client.get(f"/api/v1{path}")

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.client.post(f"/api/v1{path}", json=body or {}, headers=self.headers)

    def patch(self, path: str, body: dict[str, Any]) -> Any:
        return self.client.patch(f"/api/v1{path}", json=body, headers=self.headers)


@pytest.fixture
def actors(app_bundle: tuple[FastAPI, Database, Any]):
    """Separate TestClients so teacher/student sessions do not overwrite each other."""

    app = app_bundle[0]
    with ExitStack() as stack:
        def sign_in(username: str) -> Actor:
            return Actor(stack.enter_context(TestClient(app)), username)

        yield sign_in


@pytest.fixture
def teacher(actors) -> Actor:
    return actors("maya")


@pytest.fixture
def student(actors) -> Actor:
    return actors("bowen")


def _create_and_publish(teacher: Actor) -> str:
    created = teacher.post(
        f"/courses/{COURSE_ID}/quizzes",
        {"title": "Week 3 Quiz", "items": SAMPLE_ITEMS},
    )
    assert created.status_code == 201, created.text
    quiz_id = created.json()["id"]
    published = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert published.json()["content_revision"] == 1
    # Publish never opens taking; submissions need an explicit start-taking.
    assert published.json()["taking_open"] is False
    assert published.json()["taking_epoch"] == 0
    return quiz_id


def _create_publish_open(teacher: Actor) -> str:
    quiz_id = _create_and_publish(teacher)
    opened = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/start-taking")
    assert opened.status_code == 200, opened.text
    assert opened.json()["taking_open"] is True
    assert opened.json()["taking_epoch"] == 1
    return quiz_id


def _submit(quiz_id: str, student: Actor, *, wrong: bool = False) -> Any:
    answers = (
        [
            {"item_id": "q1", "choice_ids": ["b"]},
            {"item_id": "q2", "choice_ids": ["a"]},
            {"item_id": "q3", "text": "x"},
        ]
        if wrong
        else [
            {"item_id": "q1", "choice_ids": ["a"]},
            {"item_id": "q2", "choice_ids": ["c", "a"]},
            {"item_id": "q3", "text": "Decouple producers"},
        ]
    )
    return student.post(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts",
        {"answers": answers},
    )


def test_teacher_crud_publish_unpublish_and_edit_gate(teacher: Actor, student: Actor) -> None:
    created = teacher.post(
        f"/courses/{COURSE_ID}/quizzes",
        {"title": "Draft Quiz", "items": SAMPLE_ITEMS},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    quiz_id = body["id"]
    assert body["status"] == "draft"
    assert body["items"][0]["answer"]["choice_ids"] == ["a"]

    # Student must not see drafts in list / detail.
    listed = student.get(f"/courses/{COURSE_ID}/quizzes")
    assert listed.status_code == 200
    assert all(row["id"] != quiz_id for row in listed.json())
    assert student.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}").status_code == 404

    # Published edit blocked until unpublish.
    pub = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/publish")
    assert pub.status_code == 200, pub.text
    blocked = teacher.patch(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}",
        {"title": "Hot edit"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "quiz_published_immutable"

    unpub = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/unpublish")
    assert unpub.status_code == 200
    assert unpub.json()["status"] == "draft"
    patched = teacher.patch(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}",
        {"title": "Revised Quiz"},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Revised Quiz"


def test_student_get_strips_answer_and_rubric(teacher: Actor, student: Actor) -> None:
    quiz_id = _create_and_publish(teacher)
    response = student.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "published"
    assert "items" in payload
    raw = response.text
    assert '"answer"' not in raw
    assert '"rubric"' not in raw
    for item in payload["items"]:
        assert "answer" not in item
        assert "rubric" not in item
        assert "prompt" in item


def test_submit_grades_objective_and_pending_subjective(
    teacher: Actor, student: Actor
) -> None:
    quiz_id = _create_and_publish(teacher)
    # Publish alone does not open taking: submission is rejected.
    closed = _submit(quiz_id, student)
    assert closed.status_code == 409
    assert closed.json()["code"] == "quiz_taking_closed"

    opened = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/start-taking")
    assert opened.status_code == 200, opened.text
    # multiple unordered; single correct; short_text pending
    submitted = _submit(quiz_id, student)
    assert submitted.status_code == 201, submitted.text
    body = submitted.json()
    assert body["score_objective"] == 3.0
    assert body["score_max_objective"] == 3.0
    assert body["grading_status"] == "mixed"
    assert body["content_revision"] == 1

    again = _submit(quiz_id, student)
    assert again.status_code == 409
    assert again.json()["code"] == "quiz_attempt_exists"
    assert submitted.json()["taking_epoch"] == 1

    mine = student.get(f"/courses/{COURSE_ID}/my-record-attempts")
    assert mine.status_code == 200, mine.text
    quiz_rows = [row for row in mine.json() if row["source"] == "quiz"]
    assert len(quiz_rows) >= 1
    assert quiz_rows[0]["quiz_id"] == quiz_id
    assert quiz_rows[0]["score_objective"] == 3.0

    teacher_rows = teacher.get(f"/courses/{COURSE_ID}/record-attempts")
    assert teacher_rows.status_code == 200
    assert any(row["source"] == "quiz" and row["quiz_id"] == quiz_id for row in teacher_rows.json())


def test_wrong_answers_score_zero(teacher: Actor, student: Actor) -> None:
    quiz_id = _create_publish_open(teacher)
    submitted = _submit(quiz_id, student, wrong=True)
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["score_objective"] == 0.0
    assert submitted.json()["score_max_objective"] == 3.0


def test_retest_after_pause_and_restart(teacher: Actor, student: Actor) -> None:
    quiz_id = _create_publish_open(teacher)
    first = _submit(quiz_id, student)
    assert first.status_code == 201, first.text
    assert first.json()["taking_epoch"] == 1

    paused = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/pause-taking")
    assert paused.status_code == 200, paused.text
    assert paused.json()["taking_open"] is False
    assert paused.json()["taking_epoch"] == 1

    # Closed between epochs: no submission, and a repeat close 409s.
    blocked = _submit(quiz_id, student)
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "quiz_taking_closed"
    again_pause = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/pause-taking")
    assert again_pause.status_code == 409
    assert again_pause.json()["code"] == "quiz_taking_already_closed"

    # Re-opening after pause starts a new epoch: the student may retake.
    reopened = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/start-taking")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["taking_epoch"] == 2
    second = _submit(quiz_id, student)
    assert second.status_code == 201, second.text
    assert second.json()["taking_epoch"] == 2

    # Same-epoch duplicate still 409s.
    duplicate = _submit(quiz_id, student)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "quiz_attempt_exists"

    rows = student.get(f"/courses/{COURSE_ID}/my-record-attempts").json()
    quiz_rows = [
        row for row in rows if row["source"] == "quiz" and row["quiz_id"] == quiz_id
    ]
    assert len(quiz_rows) == 2

    # start-taking while already open 409s.
    duplicate_open = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/start-taking")
    assert duplicate_open.status_code == 409
    assert duplicate_open.json()["code"] == "quiz_taking_already_open"


def test_record_attempts_quiz_id_filter(teacher: Actor, student: Actor) -> None:
    quiz_a = _create_publish_open(teacher)
    quiz_b = _create_publish_open(teacher)
    assert _submit(quiz_a, student).status_code == 201
    assert _submit(quiz_b, student).status_code == 201

    for actor in (teacher, student):
        path = (
            f"/courses/{COURSE_ID}/record-attempts"
            if actor is teacher
            else f"/courses/{COURSE_ID}/my-record-attempts"
        )
        all_rows = actor.get(path)
        assert all_rows.status_code == 200
        chat_or_quiz = all_rows.json()
        assert {row["quiz_id"] for row in chat_or_quiz if row["quiz_id"]} >= {
            quiz_a,
            quiz_b,
        }

        filtered = actor.get(
            f"/courses/{COURSE_ID}/record-attempts?quiz_id={quiz_a}"
            if actor is teacher
            else f"/courses/{COURSE_ID}/my-record-attempts?quiz_id={quiz_a}"
        )
        assert filtered.status_code == 200
        rows = filtered.json()
        assert rows, "quiz_id filter must keep the matching quiz attempts"
        assert all(row["quiz_id"] == quiz_a for row in rows)
        assert all(row["source"] == "quiz" for row in rows)
        assert {row["attempt_id"] for row in rows}.isdisjoint(
            {row["attempt_id"] for row in chat_or_quiz if row["quiz_id"] == quiz_b}
        )


def test_cross_course_member_cannot_see_quiz(
    app_bundle: tuple[FastAPI, Database, Any],
    teacher: Actor,
    student: Actor,
) -> None:
    quiz_id = _create_and_publish(teacher)
    _app, database, _settings = app_bundle
    other_course = str(uuid4())
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            Course(
                id=other_course,
                code=f"other-{other_course[:8]}",
                name="Other Course",
                created_at=now,
            )
        )
        # Move student off demo course into the other course only.
        demo_membership = db.get(CourseMember, {"course_id": COURSE_ID, "user_id": student.id})
        assert demo_membership is not None
        db.delete(demo_membership)
        db.add(
            CourseMember(
                course_id=other_course,
                user_id=student.id,
                role="student",
                created_at=now,
            )
        )
        db.commit()

    # Student no longer in demo course → list/detail 404 (membership not_found).
    assert student.get(f"/courses/{COURSE_ID}/quizzes").status_code == 404
    assert student.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}").status_code == 404
    assert (
        student.post(
            f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts",
            {"answers": [{"item_id": "q1", "choice_ids": ["a"]}]},
        ).status_code
        == 404
    )


def test_student_cannot_create_quiz(student: Actor) -> None:
    response = student.post(
        f"/courses/{COURSE_ID}/quizzes",
        {"title": "Nope", "items": SAMPLE_ITEMS},
    )
    # workspace.access teacher gate → not_found
    assert response.status_code in (403, 404)
