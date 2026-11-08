"""Quiz attempt review: detail, teacher hand grading, hide, Record epochs."""

# The Quiz API suite's sign-in fixtures are imported, then named as test
# parameters, which is how pytest injects them.
# ruff: noqa: F811

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from app.seed import COURSE_ID

from tests.test_classroom_quiz_api import (  # noqa: F401
    Actor,
    _create_publish_open,
    _submit,
    actors,
    student,
    teacher,
)


def _attempt_path(quiz_id: str, attempt_id: str) -> str:
    return f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/{attempt_id}"


def _put(actor: Actor, path: str, body: dict[str, Any]) -> Any:
    return actor.client.put(f"/api/v1{path}", json=body, headers=actor.headers)


def _delete(actor: Actor, path: str) -> Any:
    return actor.client.delete(f"/api/v1{path}", headers=actor.headers)


def _submitted(teacher: Actor, student: Actor) -> tuple[str, str]:
    quiz_id = _create_publish_open(teacher)
    response = _submit(quiz_id, student)
    assert response.status_code == 201, response.text
    return quiz_id, response.json()["id"]


def test_teacher_detail_has_key_and_student_detail_never_does(
    teacher: Actor, student: Actor, actors
) -> None:
    quiz_id, attempt_id = _submitted(teacher, student)

    detail = teacher.get(_attempt_path(quiz_id, attempt_id))
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["view"] == "teacher"
    assert body["taking_epoch"] == 1
    assert body["content_revision"] == 1
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id["q1"]["answer"]["choice_ids"] == ["a"]
    assert by_id["q1"]["response_choice_ids"] == ["a"]
    assert by_id["q1"]["correct"] is True
    assert by_id["q3"]["answer"]["rubric"] == "Mentions decoupling."
    assert by_id["q3"]["response_text"] == "Decouple producers"
    assert by_id["q3"]["graded"] is False
    # Text points count towards the total, so ungraded is not a full score.
    assert body["points_awarded"] == 3.0
    assert body["points_total"] == 6.0
    assert body["grading_status"] == "mixed"

    own = student.get(_attempt_path(quiz_id, attempt_id))
    assert own.status_code == 200, own.text
    assert own.json()["view"] == "student"
    assert '"answer"' not in own.text
    assert '"rubric"' not in own.text
    assert {item["id"]: item for item in own.json()["items"]}["q1"]["correct"] is True

    other = actors("kaikai")
    assert other.get(_attempt_path(quiz_id, attempt_id)).status_code == 404


def test_teacher_grades_text_items_by_hand(teacher: Actor, student: Actor) -> None:
    quiz_id, attempt_id = _submitted(teacher, student)
    grades_path = f"{_attempt_path(quiz_id, attempt_id)}/grades"

    too_many = _put(teacher, grades_path, {"grades": [{"item_id": "q3", "points_awarded": 4}]})
    assert too_many.status_code == 422
    assert too_many.json()["code"] == "quiz_grade_points_invalid"
    objective = _put(teacher, grades_path, {"grades": [{"item_id": "q1", "points_awarded": 0}]})
    assert objective.status_code == 422
    assert objective.json()["code"] == "quiz_grade_item_invalid"
    duplicate = _put(
        teacher,
        grades_path,
        {
            "grades": [
                {"item_id": "q3", "points_awarded": 1},
                {"item_id": "q3", "points_awarded": 2},
            ]
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["code"] == "quiz_grade_item_invalid"
    negative = _put(teacher, grades_path, {"grades": [{"item_id": "q3", "points_awarded": -1}]})
    assert negative.status_code in (400, 422)
    assert (
        _put(student, grades_path, {"grades": [{"item_id": "q3", "points_awarded": 3}]}).status_code
        == 404
    )

    graded = _put(
        teacher,
        grades_path,
        {"grades": [{"item_id": "q3", "points_awarded": 2.5, "feedback": "Name a second reason."}]},
    )
    assert graded.status_code == 200, graded.text
    body = graded.json()
    assert body["grading_status"] == "complete"
    assert body["score_objective"] == 3.0
    assert body["score_manual"] == 2.5
    assert body["points_awarded"] == 5.5
    assert body["graded_at"]

    regraded = _put(teacher, grades_path, {"grades": [{"item_id": "q3", "points_awarded": 3}]})
    assert regraded.json()["score_manual"] == 3.0

    own = student.get(_attempt_path(quiz_id, attempt_id)).json()
    q3 = {item["id"]: item for item in own["items"]}["q3"]
    assert q3["graded"] is True
    assert q3["points_awarded"] == 3.0
    assert q3["feedback"] == ""

    rows = teacher.get(f"/courses/{COURSE_ID}/record-attempts?quiz_id={quiz_id}").json()
    assert rows[0]["grading_status"] == "complete"
    assert rows[0]["phase"] == "completed"
    assert rows[0]["points_awarded"] == 6.0
    assert rows[0]["points_total"] == 6.0


def test_grading_follows_the_paper_the_student_answered(teacher: Actor, student: Actor) -> None:
    quiz_id, attempt_id = _submitted(teacher, student)
    assert teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/unpublish").status_code == 200
    current = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}").json()
    items = current["items"]
    for item in items:
        if item["id"] == "q3":
            item["points"] = 10
    assert (
        teacher.patch(f"/courses/{COURSE_ID}/quizzes/{quiz_id}", {"items": items}).status_code
        == 200
    )

    over_old_max = _put(
        teacher,
        f"{_attempt_path(quiz_id, attempt_id)}/grades",
        {"grades": [{"item_id": "q3", "points_awarded": 5}]},
    )
    assert over_old_max.status_code == 422
    assert over_old_max.json()["details"]["max_points"] == 3.0


def test_records_carry_epoch_and_revision(teacher: Actor, student: Actor) -> None:
    quiz_id, _attempt_id = _submitted(teacher, student)
    teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/pause-taking")
    teacher.post(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/start-taking")
    assert _submit(quiz_id, student, wrong=True).status_code == 201

    for path, actor in (
        (f"/courses/{COURSE_ID}/record-attempts?quiz_id={quiz_id}", teacher),
        (f"/courses/{COURSE_ID}/my-record-attempts?quiz_id={quiz_id}", student),
    ):
        rows = actor.get(path).json()
        assert sorted(row["taking_epoch"] for row in rows) == [1, 2]
        assert {row["content_revision"] for row in rows} == {1}
        assert {row["phase"] for row in rows} == {"grading_pending"}


def test_teacher_hide_removes_the_attempt_everywhere(teacher: Actor, student: Actor) -> None:
    quiz_id, attempt_id = _submitted(teacher, student)
    path = _attempt_path(quiz_id, attempt_id)

    assert _delete(student, path).status_code == 404
    hidden = _delete(teacher, path)
    assert hidden.status_code == 204, hidden.text
    assert _delete(teacher, path).status_code == 404

    assert teacher.get(path).status_code == 404
    assert student.get(path).status_code == 404
    assert teacher.get(f"/courses/{COURSE_ID}/record-attempts?quiz_id={quiz_id}").json() == []
    assert student.get(f"/courses/{COURSE_ID}/my-record-attempts?quiz_id={quiz_id}").json() == []
    summary = next(
        row for row in teacher.get(f"/courses/{COURSE_ID}/quizzes").json() if row["id"] == quiz_id
    )
    assert summary["attempt_count"] == 0

    export = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    assert export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export.content)) as zf:
        assert json.loads(zf.read("attempts.json")) == []

    # Hiding keeps the row, so the round stays submitted for the student.
    again = _submit(quiz_id, student)
    assert again.status_code == 409
    assert again.json()["code"] == "quiz_attempt_exists"


def test_export_carries_hand_grades(teacher: Actor, student: Actor) -> None:
    quiz_id, attempt_id = _submitted(teacher, student)
    _put(
        teacher,
        f"{_attempt_path(quiz_id, attempt_id)}/grades",
        {"grades": [{"item_id": "q3", "points_awarded": 2, "feedback": "Good."}]},
    )
    export = teacher.get(f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts/export")
    with zipfile.ZipFile(io.BytesIO(export.content)) as zf:
        row = json.loads(zf.read("attempts.json"))[0]
        summary = zf.read("summary.md").decode("utf-8")
    assert row["score_manual"] == 2.0
    assert row["points_awarded"] == 5.0
    assert row["points_total"] == 6.0
    assert row["manual_grades"]["q3"]["feedback"] == "Good."
    assert "5.0/6.0" in summary
