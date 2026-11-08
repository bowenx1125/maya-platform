"""Classroom Quiz teacher zip export of attempts."""

from __future__ import annotations

import io
import json
import zipfile
from contextlib import ExitStack
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.models import Course, CourseMember
from app.modules.quiz.models import ClassroomQuizAttempt
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


@pytest.fixture
def actors(app_bundle: tuple[FastAPI, Database, Any]):
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


def _create_publish_open(teacher: Actor) -> str:
    created = teacher.post(
        f"/courses/{COURSE_ID}/quizzes",
        {"title": "Week 3 Quiz", "items": SAMPLE_ITEMS},
    )
    assert created.status_code == 201, created.text
    quiz_id = created.json()["id"]
    published = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/publish")
    assert published.status_code == 200, published.text
    opened = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/start-taking")
    assert opened.status_code == 200, opened.text
    return quiz_id


def _submit(quiz_id: str, student: Actor) -> Any:
    return student.post(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts",
        {
            "answers": [
                {"item_id": "q1", "choice_ids": ["a"]},
                {"item_id": "q2", "choice_ids": ["c", "a"]},
                {"item_id": "q3", "text": "Decouple producers"},
            ]
        },
    )


def _read_zip(response) -> dict[str, bytes]:
    assert response.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def test_teacher_export_with_submission(teacher: Actor, student: Actor) -> None:
    quiz_id = _create_publish_open(teacher)
    submitted = _submit(quiz_id, student)
    assert submitted.status_code == 201, submitted.text

    response = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    assert response.status_code == 200, response.text
    assert "application/zip" in response.headers["content-type"]
    assert "attachment;" in response.headers["content-disposition"]
    assert "attempts.zip" in response.headers["content-disposition"]

    files = _read_zip(response)
    assert "manifest.json" in files
    assert "quiz.json" in files
    assert "attempts.json" in files
    assert "summary.md" in files

    manifest = json.loads(files["manifest.json"])
    assert manifest["schema_version"] == 1
    assert manifest["attempt_count"] == 1
    assert manifest["quiz_id"] == quiz_id
    assert manifest["course_id"] == COURSE_ID
    assert "teacher_hidden excluded" in manifest["filter"]

    attempts = json.loads(files["attempts.json"])
    assert len(attempts) == 1
    row = attempts[0]
    assert row["taking_epoch"] == 1
    assert row["score_objective"] == 3.0
    assert row["score_max_objective"] == 3.0
    assert isinstance(row["answers"], list)
    assert len(row["answers"]) >= 1
    assert row["student_name"]
    assert "email" not in row
    assert "password" not in row
    assert "token" not in row

    blob = b"".join(files.values()).decode("utf-8", errors="ignore").lower()
    for forbidden in ("password", "csrf", "session_token", "access_token"):
        assert forbidden not in blob

    summary = files["summary.md"].decode("utf-8")
    assert "Week 3 Quiz" in summary
    assert row["student_name"] in summary


def test_teacher_export_zero_submissions(teacher: Actor) -> None:
    quiz_id = _create_publish_open(teacher)
    response = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    assert response.status_code == 200, response.text
    files = _read_zip(response)
    manifest = json.loads(files["manifest.json"])
    assert manifest["attempt_count"] == 0
    assert json.loads(files["attempts.json"]) == []
    assert "README.md" in files
    assert b"No submissions yet." in files["README.md"]
    assert b"No submissions yet." in files["summary.md"]


def test_student_export_forbidden(teacher: Actor, student: Actor) -> None:
    quiz_id = _create_publish_open(teacher)
    response = student.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    assert response.status_code in (403, 404)


def test_export_isolates_course_epoch_and_auth(
    teacher: Actor, student: Actor, app_bundle: tuple[FastAPI, Database, Any]
) -> None:
    """A teacher of another course, a stranger, and a bad epoch cannot read the zip."""

    created = teacher.post(
        f"/courses/{COURSE_ID}/quizzes",
        {"title": 'Week "3"\r\nX-Evil: 1', "items": SAMPLE_ITEMS},
    )
    assert created.status_code == 201, created.text
    quiz_id = created.json()["id"]
    assert teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/publish").status_code == 200
    assert teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/start-taking").status_code == 200

    submitted = _submit(quiz_id, student)
    assert submitted.status_code == 201, submitted.text
    teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/pause-taking")
    reopened = teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/start-taking")
    assert reopened.status_code == 200, reopened.text
    again = _submit(quiz_id, student)
    assert again.status_code == 201, again.text

    both = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    assert both.status_code == 200, both.text
    disposition = both.headers["content-disposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert disposition.count('"') == 2
    assert "X-Evil" not in disposition
    files = _read_zip(both)
    epochs = sorted(row["taking_epoch"] for row in json.loads(files["attempts.json"]))
    assert epochs == [1, 2]

    epoch_one = teacher.get(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export?taking_epoch=1"
    )
    assert epoch_one.status_code == 200
    one_rows = json.loads(_read_zip(epoch_one)["attempts.json"])
    assert [row["taking_epoch"] for row in one_rows] == [1]
    assert json.loads(_read_zip(epoch_one)["manifest.json"])["taking_epoch_filter"] == 1

    empty = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export?taking_epoch=99")
    assert empty.status_code == 200
    assert json.loads(_read_zip(empty)["manifest.json"])["attempt_count"] == 0

    bad = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export?taking_epoch=nope")
    assert bad.status_code == 400
    assert bad.json()["code"] == "malformed_request"

    fresh = TestClient(app_bundle[0])
    anon = fresh.get(f"/api/v1/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    assert anon.status_code == 401

    other_course = str(uuid4())
    now = datetime.now(UTC)
    db = app_bundle[1]
    with db.session() as session:
        session.add(
            Course(
                id=other_course,
                code=f"other-{other_course[:8]}",
                name="Other Course",
                created_at=now,
            )
        )
        membership = session.get(CourseMember, {"course_id": COURSE_ID, "user_id": student.id})
        assert membership is not None
        session.delete(membership)
        session.add(
            CourseMember(
                course_id=other_course,
                user_id=student.id,
                role="teacher",
                created_at=now,
            )
        )
        session.commit()

    assert student.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export").status_code == 404
    assert (
        student.get(f"/courses/{other_course}/quizzes/{quiz_id}/attempts/export").status_code == 404
    )
    # The original course teacher still exports only that course's rows.
    still = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    assert still.status_code == 200
    assert json.loads(_read_zip(still)["manifest.json"])["attempt_count"] == 2


def test_export_totals_follow_teacher_grade_over_ai_score(
    teacher: Actor, student: Actor, app_bundle: tuple[FastAPI, Database, Any]
) -> None:
    """#386 regression: a later hand grade wins in the zip totals; AI stays on the answer."""

    quiz_id = _create_publish_open(teacher)
    submitted = _submit(quiz_id, student)
    assert submitted.status_code == 201, submitted.text
    attempt_id = submitted.json()["id"]

    db = app_bundle[1]
    with db.session() as session:
        attempt = session.get(ClassroomQuizAttempt, attempt_id)
        assert attempt is not None
        answers = json.loads(attempt.answers_json)
        for row in answers:
            if row.get("item_id") == "q3":
                row["ai_score"] = 3.0
                row["points_awarded"] = 3.0
        attempt.answers_json = json.dumps(answers, ensure_ascii=False, separators=(",", ":"))
        attempt.score_manual = 3.0
        attempt.grading_status = "complete"
        session.commit()

    graded = teacher.client.put(
        f"/api/v1/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/{attempt_id}/grades",
        json={"grades": [{"item_id": "q3", "points_awarded": 1, "feedback": "Thin."}]},
        headers=teacher.headers,
    )
    assert graded.status_code == 200, graded.text

    response = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    assert response.status_code == 200, response.text
    files = _read_zip(response)
    row = json.loads(files["attempts.json"])[0]
    summary = files["summary.md"].decode("utf-8")
    answer = next(item for item in row["answers"] if item["item_id"] == "q3")
    assert row["score_manual"] == 1.0
    assert row["points_awarded"] == 4.0
    assert row["points_total"] == 6.0
    assert row["manual_grades"]["q3"]["points_awarded"] == 1.0
    assert answer["ai_score"] == 3.0
    assert "4.0/6.0" in summary
    assert "password" not in row
    paper = json.loads(files["quiz.json"])["document"]["items"]
    assert next(item["answer"]["choice_ids"] for item in paper if item["id"] == "q1") == ["a"]


def test_hidden_attempt_excluded(
    teacher: Actor, student: Actor, app_bundle: tuple[FastAPI, Database, Any]
) -> None:
    quiz_id = _create_publish_open(teacher)
    submitted = _submit(quiz_id, student)
    assert submitted.status_code == 201, submitted.text
    attempt_id = submitted.json()["id"]

    db = app_bundle[1]
    with db.session() as session:
        attempt = session.get(ClassroomQuizAttempt, attempt_id)
        assert attempt is not None
        attempt.teacher_hidden_at = datetime.now(UTC)
        session.commit()

    response = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    assert response.status_code == 200, response.text
    files = _read_zip(response)
    manifest = json.loads(files["manifest.json"])
    assert manifest["attempt_count"] == 0
    assert json.loads(files["attempts.json"]) == []
