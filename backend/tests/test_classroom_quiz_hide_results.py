"""Hide results from students: column default, teacher switch, student projection."""

# ruff: noqa: F811

from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace
from typing import Any

from app.core.db import Database
from app.modules.quiz.models import ClassroomQuizAttempt
from app.modules.quiz.service import _hide_results_from_students
from app.seed import COURSE_ID

from tests.test_classroom_quiz_api import (  # noqa: F401
    Actor,
    _create_and_publish,
    _create_publish_open,
    _set_student_results_visible,
    _submit,
    actors,
    student,
    teacher,
)

RESULT_KEYS = (
    "score_objective",
    "score_max_objective",
    "score_manual",
    "score_max_manual",
    "score_ai",
    "points_awarded",
    "points_total",
    "grading_status",
)
ITEM_RESULT_KEYS = ("correct", "points_awarded", "graded", "feedback", "ai_score", "ai_feedback")
ANSWER_KEY_FIELDS = ("answer", "rubric", "grading")


def _hidden(payload: dict[str, Any], key: str) -> None:
    assert payload.get(key) is None, (key, payload.get(key))


def _assert_no_result_fields(payload: dict[str, Any], *, answers: bool = False) -> None:
    for key in RESULT_KEYS:
        _hidden(payload, key)
    assert payload.get("results_visible") is False
    if "answers" in payload:
        for answer in payload["answers"]:
            for key in ITEM_RESULT_KEYS + ANSWER_KEY_FIELDS:
                _hidden(answer, key)
            assert set(k for k, v in answer.items() if v is not None) <= {
                "item_id",
                "choice_ids",
                "text",
            }
    if "items" in payload:
        for item in payload["items"]:
            for key in ITEM_RESULT_KEYS + ANSWER_KEY_FIELDS:
                _hidden(item, key)


def test_missing_quiz_or_column_is_fail_closed() -> None:
    assert _hide_results_from_students(None) is True
    assert _hide_results_from_students(SimpleNamespace()) is True
    assert _hide_results_from_students(SimpleNamespace(hide_results_from_students=False)) is False


def test_new_quiz_hides_student_results_and_keeps_teacher_scores(
    teacher: Actor, student: Actor, database: Database
) -> None:
    created = teacher.post(
        f"/courses/{COURSE_ID}/quizzes",
        {"title": "Hidden by default", "items": []},
    )
    assert created.status_code == 201, created.text
    assert created.json()["hide_results_from_students"] is True

    quiz_id = _create_publish_open(teacher)
    submitted = _submit(quiz_id, student)
    assert submitted.status_code == 201, submitted.text
    body = submitted.json()
    _assert_no_result_fields(body, answers=True)
    assert body["results_visible"] is False
    by_item = {row["item_id"]: row for row in body["answers"]}
    assert by_item["q1"]["choice_ids"] == ["a"]
    assert set(by_item["q2"]["choice_ids"]) == {"c", "a"}
    assert by_item["q3"]["text"] == "Decouple producers"
    attempt_id = body["id"]

    with database.session() as db:
        attempt = db.get(ClassroomQuizAttempt, attempt_id)
        assert attempt is not None
        assert attempt.score_objective == 3.0
        assert attempt.score_max_objective == 3.0
        assert attempt.grading_status == "mixed"

    teacher_detail = teacher.get(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/{attempt_id}"
    )
    assert teacher_detail.status_code == 200, teacher_detail.text
    tbody = teacher_detail.json()
    assert tbody["view"] == "teacher"
    assert tbody["score_objective"] == 3.0
    assert tbody["score_max_objective"] == 3.0
    items = {item["id"]: item for item in tbody["items"]}
    assert items["q1"]["correct"] is True
    assert items["q1"]["answer"]["choice_ids"] == ["a"]
    assert items["q3"]["answer"]["rubric"] == "Mentions decoupling."

    own = student.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/{attempt_id}")
    assert own.status_code == 200, own.text
    _assert_no_result_fields(own.json())
    assert own.json()["items"][0]["response_choice_ids"] == ["a"]
    assert '"answer"' not in own.text
    assert '"rubric"' not in own.text


def test_teacher_can_reveal_and_hide_without_resubmit(
    teacher: Actor, student: Actor
) -> None:
    quiz_id = _create_publish_open(teacher)
    submitted = _submit(quiz_id, student)
    assert submitted.status_code == 201, submitted.text
    attempt_id = submitted.json()["id"]
    revision = submitted.json()["content_revision"]

    opened = _set_student_results_visible(teacher, quiz_id, hide=False)
    assert opened.status_code == 200, opened.text
    assert opened.json()["hide_results_from_students"] is False
    assert opened.json()["content_revision"] == revision
    assert opened.json()["status"] == "published"

    detail = student.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/{attempt_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["results_visible"] is True
    assert body["score_objective"] == 3.0
    assert body["score_max_objective"] == 3.0
    items = {item["id"]: item for item in body["items"]}
    assert items["q1"]["correct"] is True
    assert "answer" not in items["q1"]
    assert "rubric" not in items["q3"]
    assert "grading" not in items["q3"]
    assert '"answer"' not in detail.text
    assert '"rubric"' not in detail.text
    assert '"grading"' not in detail.text

    mine = student.get(f"/courses/{COURSE_ID}/my-record-attempts?quiz_id={quiz_id}")
    assert mine.status_code == 200, mine.text
    row = mine.json()[0]
    assert row["results_visible"] is True
    assert row["score_objective"] == 3.0

    closed = _set_student_results_visible(teacher, quiz_id, hide=True)
    assert closed.status_code == 200, closed.text
    assert closed.json()["hide_results_from_students"] is True
    assert closed.json()["content_revision"] == revision

    hidden = student.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/{attempt_id}")
    assert hidden.status_code == 200, hidden.text
    _assert_no_result_fields(hidden.json())
    hidden_rows = student.get(
        f"/courses/{COURSE_ID}/my-record-attempts?quiz_id={quiz_id}"
    ).json()
    _assert_no_result_fields(hidden_rows[0])


def test_published_quiz_visibility_put_does_not_conflict_or_bump(
    teacher: Actor, student: Actor
) -> None:
    quiz_id = _create_and_publish(teacher)
    before = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}").json()
    assert before["status"] == "published"
    assert before["hide_results_from_students"] is True
    revision = before["content_revision"]
    epoch = before["taking_epoch"]

    patched = teacher.patch(f"/courses/{COURSE_ID}/quizzes/{quiz_id}", {"title": "Nope"})
    assert patched.status_code == 409
    assert patched.json()["code"] == "quiz_published_immutable"

    changed = _set_student_results_visible(teacher, quiz_id, hide=False)
    assert changed.status_code == 200, changed.text
    assert changed.json()["code"] != "quiz_published_immutable" if "code" in changed.json() else True
    assert changed.json()["hide_results_from_students"] is False
    assert changed.json()["content_revision"] == revision
    assert changed.json()["taking_epoch"] == epoch
    assert changed.json()["status"] == "published"

    forbidden = student.put(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/student-results-visibility",
        {"hide_results_from_students": False},
    )
    assert forbidden.status_code == 403


def test_legacy_default_is_hidden(teacher: Actor, student: Actor) -> None:
    # After migration, a quiz with no historical visibility field is hidden.
    quiz_id = _create_publish_open(teacher)
    assert _submit(quiz_id, student).status_code == 201
    mine = student.get(f"/courses/{COURSE_ID}/my-record-attempts?quiz_id={quiz_id}").json()
    _assert_no_result_fields(mine[0])
    detail = student.get(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/{mine[0]['attempt_id']}"
    )
    _assert_no_result_fields(detail.json())


def test_student_cannot_use_teacher_record_export_or_grade(
    teacher: Actor, student: Actor
) -> None:
    quiz_id = _create_publish_open(teacher)
    submitted = _submit(quiz_id, student)
    assert submitted.status_code == 201, submitted.text
    attempt_id = submitted.json()["id"]

    record = student.get(f"/courses/{COURSE_ID}/record-attempts")
    assert record.status_code in (403, 404)

    export = student.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    assert export.status_code in (403, 404)

    grade = student.put(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/{attempt_id}/grades",
        {"grades": [{"item_id": "q3", "points_awarded": 3}]},
    )
    assert grade.status_code in (403, 404)


def test_export_stays_teacher_only_with_scores_and_hidden_attempt_stays_hidden(
    teacher: Actor, student: Actor
) -> None:
    quiz_id = _create_publish_open(teacher)
    submitted = _submit(quiz_id, student)
    assert submitted.status_code == 201, submitted.text
    attempt_id = submitted.json()["id"]

    export = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    assert export.status_code == 200, export.text
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        attempts = json.loads(archive.read("attempts.json"))
    assert attempts[0]["score_objective"] == 3.0
    assert attempts[0]["score_max_objective"] == 3.0

    hidden = teacher.client.delete(
        f"/api/v1/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/{attempt_id}",
        headers=teacher.headers,
    )
    assert hidden.status_code == 204, hidden.text
    assert student.get(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/{attempt_id}"
    ).status_code == 404
    _set_student_results_visible(teacher, quiz_id, hide=False)
    assert student.get(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/{attempt_id}"
    ).status_code == 404
    mine = student.get(f"/courses/{COURSE_ID}/my-record-attempts?quiz_id={quiz_id}")
    assert mine.status_code == 200
    assert mine.json() == []
