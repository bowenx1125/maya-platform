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
from tests.quiz_export_helpers import read_export

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
    assert "filename*=UTF-8''Week%203%20Quiz.zip" in response.headers["content-disposition"]
    files = _read_zip(response)
    assert len(files) == 1
    name, row, questions, book = read_export(response.content)[0]
    assert name.endswith(".xlsx")
    assert row["taking_epoch"] == 1
    assert row["score_objective"] == 3.0
    assert row["score_max_objective"] == 3.0
    assert row["Participant name"]
    assert row["Username"] == "bowen"
    assert row["quiz_id"] == quiz_id
    assert row["course_id"] == COURSE_ID
    assert len(questions) == len(SAMPLE_ITEMS)
    assert questions[0]["Question"] == SAMPLE_ITEMS[0]["prompt"]
    assert questions[0]["Participant answer"] == "API gateway"
    assert questions[0]["Correct answer"] == "API gateway"
    assert questions[1]["Participant answer"] == "GET; HEAD"
    assert questions[2]["Participant answer"] == "Decouple producers"
    assert questions[2]["Correct answer"] == "Mentions decoupling."
    assert "Current paper" in book.sheetnames
    blob = str([list(sheet.values) for sheet in book]).lower()
    for forbidden in ("password", "csrf", "session_token", "access_token", "email"):
        assert forbidden not in blob


def test_teacher_export_zero_submissions(teacher: Actor) -> None:
    quiz_id = _create_publish_open(teacher)
    response = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    assert response.status_code == 200, response.text
    assert _read_zip(response) == {}
    assert read_export(response.content) == []


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
    assert 'filename="Week _3___X-Evil_ 1.zip"' in disposition
    workbooks = read_export(both.content)
    assert len({name.split("/")[0] for name, *_ in workbooks}) == 1
    assert len({name for name, *_ in workbooks}) == 2
    epochs = sorted(row["taking_epoch"] for _, row, _, _ in workbooks)
    assert epochs == [1, 2]

    epoch_one = teacher.get(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export?taking_epoch=1"
    )
    assert epoch_one.status_code == 200
    one_rows = [row for _, row, _, _ in read_export(epoch_one.content)]
    assert [row["taking_epoch"] for row in one_rows] == [1]
    assert one_rows[0]["taking_epoch_filter"] == 1

    empty = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export?taking_epoch=99")
    assert empty.status_code == 200
    assert read_export(empty.content) == []

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
    assert len(read_export(still.content)) == 2


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
    _, row, questions, book = read_export(response.content)[0]
    answer = next(item for item in questions if item["Question ID"] == "q3")
    assert row["score_manual"] == 1.0
    assert row["points_awarded"] == 4.0
    assert row["points_total"] == 6.0
    assert row["Total score"] == "4.0/6.0"
    assert answer["Teacher grade: points_awarded"] == 1.0
    assert answer["Answer: ai_score"] == 3.0
    assert answer["Result/score"] == 1.0
    assert answer["Teacher grade: feedback"] == "Thin."
    assert "password" not in str(list(book["Attempt"].values))


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
    assert read_export(response.content) == []


@pytest.mark.parametrize("display_name", ["../张同学/\\🙂", "..", "CON", "😀" * 80])
def test_export_duplicate_and_unsafe_names(teacher, student, app_bundle, display_name):
    from app.core.models import User

    quiz_id = _create_publish_open(teacher)
    submitted = _submit(quiz_id, student)
    assert submitted.status_code == 201, submitted.text
    with app_bundle[1].session() as db:
        original = db.get(ClassroomQuizAttempt, submitted.json()["id"])
        first = db.get(User, student.id)
        first.display_name = display_name
        second = User(
            id=str(uuid4()),
            username="exportstudent",
            display_name=display_name,
            created_at=datetime.now(UTC),
        )
        db.add(second)
        db.flush()
        fields = {
            column.name: getattr(original, column.name)
            for column in ClassroomQuizAttempt.__table__.columns
        }
        fields.update(id=str(uuid4()), actor_user_id=second.id)
        db.add(ClassroomQuizAttempt(**fields))
        db.commit()
    response = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    rows = read_export(response.content)
    assert len(rows) == 2
    folders = [name.split("/")[0] for name, *_ in rows]
    assert len(set(folders)) == 2
    assert folders[1] == folders[0] + " (2)"
    for path, metadata, _, book in rows:
        assert metadata["Participant name"] == display_name
        assert all(part not in (".", "..") for part in path.split("/"))
        assert "\\" not in path
        assert all(len(part.encode("utf-8")) <= 255 for part in path.split("/"))
        assert all(
            len(title) <= 31 and not any(char in title for char in "[]:*?/\\")
            for title in book.sheetnames
        )


def test_export_unanswered_snapshot_and_inert_strings(teacher, student, app_bundle):
    from app.modules.quiz.models import ClassroomQuiz

    quiz_id = _create_publish_open(teacher)
    submitted = _submit(quiz_id, student)
    assert submitted.status_code == 201
    with app_bundle[1].session() as db:
        attempt = db.get(ClassroomQuizAttempt, submitted.json()["id"])
        snapshot = json.loads(attempt.document_snapshot_json)
        snapshot["items"][0]["prompt"] = "=1+1\u0001"
        snapshot["items"][1]["prompt"] = "+SUM(A1)"
        snapshot["items"][2]["prompt"] = "-2+3"
        attempt.document_snapshot_json = json.dumps(snapshot)
        attempt.answers_json = json.dumps(
            [
                {"item_id": "q1", "choice_ids": [], "points_awarded": 0},
                {"item_id": "q3", "text": "@SUM(A1)\u0002", "points_awarded": None},
                {"item_id": "retired", "text": "Retained unknown answer"},
            ]
        )
        quiz = db.get(ClassroomQuiz, quiz_id)
        quiz.title = "../测验🙂/\\title"
        db.commit()
    response = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    _, _, questions, book = read_export(response.content)[0]
    assert len(questions) == 3
    assert questions[0]["Participant answer"] is None
    assert questions[1]["Participant answer"] is None
    assert questions[0]["Question"] == "=1+1"
    assert questions[2]["Participant answer"] == "@SUM(A1)"
    assert "Retained unknown answer" in str(list(book["Other answers"].values))
    for sheet in book:
        assert all(cell.data_type != "f" for row in sheet for cell in row)
    assert SAMPLE_ITEMS[0]["prompt"] in str(list(book["Current paper"].values))


def test_empty_draft_exports_empty_zip(teacher):
    created = teacher.post(f"/courses/{COURSE_ID}/quizzes", {"title": "Empty", "items": []})
    assert created.status_code == 201
    response = teacher.get(f"/courses/{COURSE_ID}/quizzes/{created.json()['id']}/attempts/export")
    assert response.status_code == 200
    assert _read_zip(response) == {}


def test_workbook_keeps_long_text_and_safe_cell_types():
    from app.modules.quiz.export import _workbook
    from app.modules.quiz.schemas import QuizItemTeacher
    from openpyxl import load_workbook

    text = "=" + "x" * 70000
    content = _workbook(
        metadata={"Participant name": "+Learner"},
        items=[QuizItemTeacher(id="q", type="long_text", prompt="-Question")],
        answers={"q": {"text": text}},
        grades={},
        quiz_payload={"document": {"items": []}},
    )
    book = load_workbook(io.BytesIO(content))
    sheet = book["Attempt"]
    heading = next(row[0].row for row in sheet if row[0].value == "Question #")
    cell = sheet.cell(heading + 1, 5)
    remainder = [row[3] for row in book["Long text"].values if row[1] == cell.coordinate]
    assert cell.value + "".join(remainder) == text
    assert all(cell.data_type != "f" for sheet in book for row in sheet for cell in row)
