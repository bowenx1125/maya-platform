"""Keyless choice grading and immutable historical submissions."""

# ruff: noqa: F811
from __future__ import annotations

import io
import json
import zipfile
from copy import deepcopy
from typing import Any

import pytest
from app.core.db import Database
from app.modules.quiz.models import ClassroomQuizAttempt
from app.seed import COURSE_ID
from fastapi import FastAPI

from tests.test_classroom_quiz_api import (  # noqa: F401
    SAMPLE_ITEMS,
    Actor,
    _set_student_results_visible,
    actors,
    student,
    teacher,
)
from tests.test_classroom_quiz_attempt_review import _put


@pytest.mark.parametrize(
    "standard",
    [
        "missing",
        None,
        {},
        {"choice_ids": None},
        {"choice_ids": []},
        {"choice_ids": ["", " ", "\t\n"]},
        {"choice_ids": "a"},
        {"choice_ids": {"a": True}},
        {"choice_ids": 1},
    ],
)
@pytest.mark.parametrize(
    "selection,score,correct",
    [
        (["b"], 3, True),
        (["a", "c"], 3, True),
        ([], 0, None),
        (["", " ", "\t"], 0, None),
        (["invalid"], 0, False),
        (None, 0, None),
    ],
)
def test_quiz_no_standard_answer(
    teacher: Actor,
    student: Actor,
    standard: Any,
    selection: list[str] | None,
    score: float,
    correct: bool | None,
) -> None:
    items = deepcopy(SAMPLE_ITEMS)
    for item in items[:2]:
        if standard == "missing":
            item.pop("answer")
        else:
            item["answer"] = standard
    created = teacher.post(f"/courses/{COURSE_ID}/quizzes", {"title": "Opinion", "items": items})
    assert created.status_code == 201, created.text
    base = f"/courses/{COURSE_ID}/quizzes/{created.json()['id']}"
    assert teacher.post(f"{base}/publish").status_code == 200
    assert teacher.post(f"{base}/start-taking").status_code == 200
    projection = student.get(base)
    for key in ("answer", "rubric", "grading"):
        assert f'"{key}"' not in projection.text
    response = student.post(
        f"{base}/attempts",
        {
            "answers": [
                {"item_id": item["id"], "choice_ids": selection}
                for item in items[:2]
                if selection is not None
            ]
            + [{"item_id": "q3", "text": "Opinion"}]
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["results_visible"] is False
    assert "score_objective" not in body
    attempt_id = body["id"]
    teacher_detail = teacher.get(f"{base}/attempts/{attempt_id}")
    assert teacher_detail.status_code == 200, teacher_detail.text
    assert teacher_detail.json()["score_objective"] == score
    for item in teacher_detail.json()["items"][:2]:
        assert item["correct"] is correct
        assert item["points_awarded"] == (item["points"] if correct else 0)
    hidden = student.get(f"{base}/attempts/{attempt_id}")
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["results_visible"] is False
    assert hidden.json().get("score_objective") is None
    for item in hidden.json()["items"][:2]:
        assert item.get("correct") is None
        assert item.get("points_awarded") is None
    opened = _set_student_results_visible(teacher, created.json()["id"], hide=False)
    assert opened.status_code == 200, opened.text
    detail = student.get(f"{base}/attempts/{attempt_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["results_visible"] is True
    assert detail.json()["score_objective"] == score
    for item in detail.json()["items"][:2]:
        assert item["correct"] is correct
        assert item["points_awarded"] == (item["points"] if correct else 0)
    for key in ("answer", "rubric", "grading"):
        assert f'"{key}"' not in hidden.text
        assert f'"{key}"' not in detail.text


@pytest.mark.parametrize("selection", [["b"], [], ["", " \t"], None])
def test_quiz_historical_keyless_scores_preserve_manual_and_answers(
    app_bundle: tuple[FastAPI, Database, Any],
    teacher: Actor,
    student: Actor,
    selection: list[str] | None,
) -> None:
    from tests.test_classroom_quiz_api import _create_publish_open

    quiz_id = _create_publish_open(teacher)
    response = student.post(
        f"/courses/{COURSE_ID}/quizzes/{quiz_id}/attempts",
        {
            "answers": [
                {"item_id": item_id, "choice_ids": selection}
                for item_id in ("q1", "q2")
                if selection is not None
            ]
            + [{"item_id": "q3", "text": "Opinion"}]
        },
    )
    assert response.status_code == 201, response.text
    submitted = response.json()
    expected_score = 3 if selection == ["b"] else 0
    expected_correct = True if expected_score else None
    attempt_id = submitted["id"]
    base = f"/courses/{COURSE_ID}/quizzes/{quiz_id}"
    path = f"{base}/attempts/{attempt_id}"
    assert (
        _put(
            teacher, f"{path}/grades", {"grades": [{"item_id": "q3", "points_awarded": 2}]}
        ).status_code
        == 200
    )
    database = app_bundle[1]
    with database.session() as db:
        attempt = db.get(ClassroomQuizAttempt, attempt_id)
        assert attempt is not None
        paper = json.loads(attempt.document_snapshot_json)
        paper["items"][0].pop("answer", None)
        paper["items"][1]["answer"] = {"choice_ids": ["", " \t"]}
        attempt.document_snapshot_json = json.dumps(paper)
        original_answers = attempt.answers_json
        original_grades = attempt.manual_grades_json
        db.commit()
    opened = _set_student_results_visible(teacher, quiz_id, hide=False)
    assert opened.status_code == 200, opened.text
    for actor in (teacher, student):
        detail = actor.get(path).json()
        assert detail["score_objective"] == expected_score
        assert detail["points_awarded"] == expected_score + 2
        assert all(item["correct"] is expected_correct for item in detail["items"][:2])
        assert all(
            item["points_awarded"] == (item["points"] if expected_score else 0)
            for item in detail["items"][:2]
        )
        record_kind = "record-attempts" if actor is teacher else "my-record-attempts"
        records = actor.get(f"/courses/{COURSE_ID}/{record_kind}?quiz_id={quiz_id}").json()
        assert records[0]["points_awarded"] == expected_score + 2
    for key in ("answer", "rubric", "grading"):
        assert f'"{key}"' not in student.get(path).text
    with zipfile.ZipFile(io.BytesIO(teacher.get(f"{base}/attempts/export").content)) as archive:
        row = json.loads(archive.read("attempts.json"))[0]
        assert row["points_awarded"] == expected_score + 2
        assert all(answer["correct"] is expected_correct for answer in row["answers"][:2])
        assert all(
            answer["points_awarded"] == (answer["points"] if expected_score else 0)
            for answer in row["answers"][:2]
        )
    with database.session() as db:
        attempt = db.get(ClassroomQuizAttempt, attempt_id)
        assert attempt is not None
        assert attempt.answers_json == original_answers
        assert attempt.manual_grades_json == original_grades
        assert attempt.score_objective == 0
        assert attempt.score_manual == 2


@pytest.mark.parametrize("standard", [["a", "b"], ["unknown"]])
def test_quiz_nonempty_standard_still_validated(teacher: Actor, standard: list[str]) -> None:
    items = deepcopy(SAMPLE_ITEMS)
    items[0]["answer"] = {"choice_ids": standard}
    response = teacher.post(
        f"/courses/{COURSE_ID}/quizzes", {"title": "Invalid key", "items": items}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "quiz_answer_invalid"


@pytest.mark.parametrize("standard", [["", "a", " \t"], ["", "unknown"]])
def test_quiz_blank_key_entries_do_not_hide_nonblank_ids(
    teacher: Actor, standard: list[str]
) -> None:
    items = deepcopy(SAMPLE_ITEMS)
    items[0]["answer"] = {"choice_ids": standard}
    response = teacher.post(f"/courses/{COURSE_ID}/quizzes", {"title": "Mixed key", "items": items})
    if "unknown" in standard:
        assert response.status_code == 422
        assert response.json()["code"] == "quiz_answer_invalid"
    else:
        assert response.status_code == 201, response.text
        assert response.json()["items"][0]["answer"]["choice_ids"] == ["a"]
