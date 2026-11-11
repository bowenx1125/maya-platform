"""Quiz results visibility applies to every student projection of past attempts."""

from __future__ import annotations

import importlib
import io
import json
import zipfile
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.db import ALEMBIC_HEAD
from app.core.models import Course, CourseMember
from app.modules.quiz.models import ClassroomQuiz, ClassroomQuizAttempt
from app.seed import COURSE_ID
from sqlalchemy import insert, inspect, text

from tests.test_classroom_quiz_api import (
    SAMPLE_ITEMS,
    Actor,
    _create_publish_open,
    _set_results_visible,
    _submit,
)
from tests.test_classroom_quiz_api import actors as actors
from tests.test_classroom_quiz_api import student as student
from tests.test_classroom_quiz_api import teacher as teacher


def _path(quiz_id: str) -> str:
    return f"/courses/{COURSE_ID}/quizzes/{quiz_id}"


def _put(actor: Actor, quiz_id: str, body: dict[str, Any]) -> Any:
    return actor.client.put(f"/api/v1{_path(quiz_id)}/results", json=body, headers=actor.headers)


def _assert_hidden(payload: dict[str, Any], *, detail: bool = False) -> None:
    assert payload["show_results"] is False
    for key, value in payload.items():
        if key.startswith(("score_", "points_")) or key == "grading_status":
            assert value is None, key
    if detail:
        assert payload["graded_at"] is None
        items = {item["id"]: item for item in payload["items"]}
        assert items["q1"]["response_choice_ids"] == ["a"]
        assert items["q2"]["response_choice_ids"] == ["a", "c"]
        assert items["q3"]["response_text"] == "Decouple producers"
        assert items["q1"]["prompt"] == SAMPLE_ITEMS[0]["prompt"]
        assert items["q1"]["choices"] == SAMPLE_ITEMS[0]["choices"]
        for item in payload["items"]:
            assert item["correct"] is None
            assert item["points_awarded"] is None
            assert item["feedback"] is None
            assert item["ai_score"] is None
            assert item["graded"] is False
            assert "answer" not in item
            assert "grading" not in item


def test_new_quizzes_hide_results_outside_the_document(teacher, student, database) -> None:
    quiz_id = _create_publish_open(teacher, show_results=False)
    for actor in (teacher, student):
        detail = actor.get(_path(quiz_id)).json()
        assert detail["show_results"] is False
        summaries = actor.get(f"/courses/{COURSE_ID}/quizzes").json()
        assert next(row for row in summaries if row["id"] == quiz_id)["show_results"] is False
    with database.session() as db:
        quiz = db.get(ClassroomQuiz, quiz_id)
        assert quiz.show_results is False
        assert "show_results" not in json.loads(quiz.document_json)
        assert "show_results" not in json.loads(quiz.settings_json)
    _set_results_visible(teacher, quiz_id)
    created = teacher.post(
        f"/courses/{COURSE_ID}/quizzes", {"title": "Another quiz", "items": SAMPLE_ITEMS}
    )
    assert created.status_code == 201
    assert created.json()["show_results"] is False


def test_hidden_submit_records_and_detail_keep_only_student_answers(
    teacher, student, database
) -> None:
    quiz_id = _create_publish_open(teacher, show_results=False)
    submitted = _submit(quiz_id, student)
    assert submitted.status_code == 201, submitted.text
    body = submitted.json()
    _assert_hidden(body)
    assert body["status"] == "submitted"
    assert body["taking_epoch"] == 1
    answers = {answer["item_id"]: answer for answer in body["answers"]}
    assert answers["q1"]["choice_ids"] == ["a"]
    assert answers["q3"]["text"] == "Decouple producers"
    for answer in body["answers"]:
        assert set(answer) <= {"item_id", "type", "choice_ids", "text"}
    attempt_id = body["id"]
    # AI grades and teacher feedback must stay private after background grading too.
    with database.session() as db:
        attempt = db.get(ClassroomQuizAttempt, attempt_id)
        normalized = json.loads(attempt.answers_json)
        normalized[2].update(ai_score=2.25, ai_feedback="AI feedback")
        attempt.answers_json = json.dumps(normalized)
        db.commit()
    graded = teacher.client.put(
        f"/api/v1{_path(quiz_id)}/attempts/{attempt_id}/grades",
        json={"grades": [{"item_id": "q3", "points_awarded": 2.5, "feedback": "Feedback"}]},
        headers=teacher.headers,
    )
    assert graded.status_code == 200, graded.text
    assert graded.json()["points_awarded"] == 5.5
    assert graded.json()["items"][2]["ai_score"] == 2.25
    teacher_detail = teacher.get(f"{_path(quiz_id)}/attempts/{attempt_id}").json()
    teacher_rows = teacher.get(f"/courses/{COURSE_ID}/record-attempts?quiz_id={quiz_id}").json()
    export = teacher.get(f"{_path(quiz_id)}/attempts/export")
    assert export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        exported = json.loads(archive.read("attempts.json"))[0]
        assert exported["points_awarded"] == 5.5
        assert exported["manual_grades"]["q3"]["feedback"] == "Feedback"
    for show in (False, True, False):
        _set_results_visible(teacher, quiz_id, show)
        detail = student.get(f"{_path(quiz_id)}/attempts/{attempt_id}")
        assert detail.status_code == 200, detail.text
        for suffix in ("", f"?quiz_id={quiz_id}"):
            response = student.get(f"/courses/{COURSE_ID}/my-record-attempts{suffix}")
            assert response.status_code == 200, response.text
            row = next(row for row in response.json() if row["attempt_id"] == attempt_id)
            assert row["show_results"] is show
            assert row["taking_epoch"] == 1
            assert row["content_revision"] == 1
            assert row["submitted_at"] == body["submitted_at"]
            if show:
                assert row["points_awarded"] == 5.5
                assert row["score_ai"] == 2.25
                assert row["grading_status"] == "complete"
                assert row["phase"] == "completed"
            else:
                _assert_hidden(row)
                assert row["phase"] is None
        if show:
            visible = detail.json()
            assert visible["show_results"] is True
            assert visible["points_awarded"] == 5.5
            assert visible["grading_status"] == "complete"
            assert visible["items"][0]["correct"] is True
            assert visible["items"][2]["feedback"] == "Feedback"
            assert visible["items"][2]["ai_score"] == 2.25
            assert visible["items"][2]["graded"] is True
            assert '"answer"' not in detail.text
        else:
            _assert_hidden(detail.json(), detail=True)
        current = teacher.get(f"{_path(quiz_id)}/attempts/{attempt_id}").json()
        assert {k: v for k, v in current.items() if k != "show_results"} == {
            k: v for k, v in teacher_detail.items() if k != "show_results"
        }
        current_rows = teacher.get(f"/courses/{COURSE_ID}/record-attempts?quiz_id={quiz_id}").json()
        assert {k: v for k, v in current_rows[0].items() if k != "show_results"} == {
            k: v for k, v in teacher_rows[0].items() if k != "show_results"
        }
        assert student.get(f"{_path(quiz_id)}/attempts/export").status_code == 404
        assert student.get(f"/courses/{COURSE_ID}/record-attempts").status_code == 404
    assert teacher.post(f"{_path(quiz_id)}/pause-taking").status_code == 200
    assert teacher.post(f"{_path(quiz_id)}/start-taking").status_code == 200
    later = _submit(quiz_id, student)
    assert later.status_code == 201
    _assert_hidden(later.json())
    _set_results_visible(teacher, quiz_id)
    rows = student.get(f"/courses/{COURSE_ID}/my-record-attempts?quiz_id={quiz_id}").json()
    assert len(rows) == 2
    assert all(row["show_results"] is True and row["score_objective"] == 3 for row in rows)


def test_results_toggle_requires_course_teacher_and_csrf(teacher, student, database) -> None:
    quiz_id = _create_publish_open(teacher, show_results=False)
    assert _put(student, quiz_id, {"show_results": True}).status_code == 403
    assert _put(teacher, str(uuid4()), {"show_results": True}).status_code == 404
    for headers in (
        {"Origin": "http://testserver"},
        {**teacher.headers, "X-CSRF-Token": "x" * 32},
        {**teacher.headers, "Origin": "https://other.invalid"},
    ):
        response = teacher.client.put(
            f"/api/v1{_path(quiz_id)}/results", json={"show_results": True}, headers=headers
        )
        assert response.status_code == 403
    other_course = str(uuid4())
    now = datetime.now(UTC)
    with database.session() as db:
        db.delete(db.get(CourseMember, {"course_id": COURSE_ID, "user_id": student.id}))
        db.add(Course(id=other_course, code=other_course, name="Other", created_at=now))
        db.flush()
        db.add(
            CourseMember(course_id=other_course, user_id=student.id, role="teacher", created_at=now)
        )
        db.commit()
    assert _put(student, quiz_id, {"show_results": True}).status_code == 404
    assert teacher.get(_path(quiz_id)).json()["show_results"] is False


@pytest.mark.parametrize("initial_show_results", [False, True])
def test_submit_uses_visibility_changed_during_grading(
    teacher, student, monkeypatch, initial_show_results
) -> None:
    from app.modules.quiz import service

    quiz_id = _create_publish_open(teacher, show_results=initial_show_results)
    grade = service.grade_objective

    def grade_and_toggle(*args, **kwargs):
        result = grade(*args, **kwargs)
        _set_results_visible(teacher, quiz_id, not initial_show_results)
        return result

    monkeypatch.setattr(service, "grade_objective", grade_and_toggle)
    submitted = _submit(quiz_id, student)
    assert submitted.status_code == 201, submitted.text
    payload = submitted.json()
    if initial_show_results:
        _assert_hidden(payload)
        for answer in payload["answers"]:
            assert set(answer) <= {"item_id", "type", "choice_ids", "text"}
    else:
        assert payload["show_results"] is True
        assert payload["score_objective"] == 3
        assert payload["answers"][0]["correct"] is True


@pytest.mark.parametrize(
    "body", [{}, {"show_results": None}, {"show_results": "false"}, {"show_results": 1}]
)
def test_results_toggle_fails_closed_on_invalid_values(teacher, body) -> None:
    quiz_id = _create_publish_open(teacher, show_results=False)
    assert _put(teacher, quiz_id, body).status_code in (400, 422)
    assert teacher.get(_path(quiz_id)).json()["show_results"] is False


def test_results_migration_preserves_existing_rows_and_changes_insert_defaults(
    database, teacher
) -> None:
    quiz_id = _create_publish_open(teacher, show_results=False)
    # create_all fixtures have no Alembic version table until the schema is stamped.
    database.upgrade_schema()
    with database.engine.begin() as connection:
        connection.execute(text("ALTER TABLE classroom_quizzes DROP COLUMN show_results"))
        connection.execute(
            text("UPDATE alembic_version SET version_num = '0090_bowen_identity_choice'")
        )
    database.upgrade_schema()
    assert database.check_ready()
    with database.engine.begin() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == ALEMBIC_HEAD
        assert (
            connection.scalar(
                text("SELECT show_results FROM classroom_quizzes WHERE id = :id"), {"id": quiz_id}
            )
            is True
        )
        columns = {
            column["name"]: column
            for column in inspect(connection).get_columns("classroom_quizzes")
        }
        assert columns["show_results"]["nullable"] is False
        assert columns["show_results"]["default"] == "false"
        # Omit the column in raw SQL so the database's default, not the ORM's, is exercised.
        connection.execute(
            text("""
            INSERT INTO classroom_quizzes
                (id, course_id, title, status, schema_version, settings_json, document_json,
                 content_revision, created_by_user_id, taking_open, taking_epoch,
                 created_at, updated_at)
            VALUES (:id, :course, 'SQL insert', 'draft', 1, '{}', '{}', 0, :teacher,
                    false, 0, now(), now())
        """),
            {"id": "sql-quiz", "course": COURSE_ID, "teacher": teacher.id},
        )
        assert (
            connection.scalar(
                text("SELECT show_results FROM classroom_quizzes WHERE id = 'sql-quiz'")
            )
            is False
        )
        connection.execute(
            insert(ClassroomQuiz).values(
                id="model-quiz",
                course_id=COURSE_ID,
                title="Model insert",
                created_by_user_id=teacher.id,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        assert (
            connection.scalar(
                text("SELECT show_results FROM classroom_quizzes WHERE id = 'model-quiz'")
            )
            is False
        )


def test_results_migration_emits_backfill_before_changing_default() -> None:
    migration = importlib.import_module("migrations.versions.0091_quiz_show_results")
    output = io.StringIO()
    context = MigrationContext.configure(
        url="postgresql://", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    assert "ADD COLUMN show_results BOOLEAN DEFAULT true" in sql
    assert "ALTER COLUMN show_results SET DEFAULT false" in sql
    assert "ALTER COLUMN show_results SET NOT NULL" in sql
    assert sql.index("DEFAULT true") < sql.index("SET DEFAULT false")
    assert "DROP COLUMN show_results" in sql


@pytest.mark.parametrize("show_results", [False, True])
@pytest.mark.parametrize("teacher_view", [False, True])
def test_results_projection_survives_response_union_serialization(
    show_results, teacher_view
) -> None:
    from unittest.mock import Mock

    from app.core.models import User
    from app.modules.quiz import service
    from app.modules.quiz.schemas import StudentQuizAttemptDetailDTO, TeacherQuizAttemptDetailDTO
    from pydantic import TypeAdapter
    from sqlalchemy.orm import Session

    quiz_id, attempt_id, user_id = (str(uuid4()) for _ in range(3))
    quiz = ClassroomQuiz(id=quiz_id, title="Projection", show_results=show_results)
    attempt = ClassroomQuizAttempt(
        id=attempt_id,
        quiz_id=quiz_id,
        course_id=COURSE_ID,
        actor_user_id=user_id,
        content_revision=1,
        taking_epoch=1,
        status="submitted",
        grading_status="complete",
        score_objective=3,
        score_max_objective=3,
        score_manual=2.5,
        submitted_at=datetime.now(UTC),
        graded_at=datetime.now(UTC),
        document_snapshot_json=json.dumps({"items": SAMPLE_ITEMS}),
        answers_json=json.dumps(
            [
                {"item_id": "q1", "choice_ids": ["a"], "correct": True, "points_awarded": 1},
                {"item_id": "q2", "choice_ids": ["a", "c"], "correct": True, "points_awarded": 2},
                {
                    "item_id": "q3",
                    "text": "Decouple producers",
                    "ai_score": 2.25,
                    "ai_feedback": "AI",
                },
                {"item_id": "unknown", "text": "Own extra answer"},
            ]
        ),
        manual_grades_json=json.dumps({"q3": {"points_awarded": 2.5, "feedback": "Feedback"}}),
    )
    db = Mock(spec=Session)
    db.get.side_effect = lambda model, key: (
        quiz if model is ClassroomQuiz else User(id=user_id, display_name="Student")
    )
    detail = service._attempt_detail(db, attempt, teacher=teacher_view)
    adapter = TypeAdapter(TeacherQuizAttemptDetailDTO | StudentQuizAttemptDetailDTO)
    payload = json.loads(adapter.dump_json(adapter.validate_python(detail)))
    row = service._quiz_record_row(db, attempt, teacher=teacher_view).model_dump(mode="json")
    assert payload["view"] == ("teacher" if teacher_view else "student")
    assert payload["show_results"] is show_results
    assert payload["items"][-1]["response_text"] == "Own extra answer"
    if teacher_view or show_results:
        assert payload["points_awarded"] == 5.5
        assert payload["score_ai"] == 2.25
        assert payload["items"][0]["correct"] is True
        assert payload["items"][2]["feedback"] == "Feedback"
        assert payload["items"][2]["ai_score"] == 2.25
        assert row["points_awarded"] == 5.5
        assert row["grading_status"] == "complete"
    else:
        _assert_hidden(payload, detail=True)
        _assert_hidden(row)
        assert row["phase"] is None
    assert ("answer" in payload["items"][0]) is teacher_view


@pytest.mark.parametrize("show_results", [False, True, None])
@pytest.mark.parametrize("initial_show_results", [False, True])
def test_submit_redacts_receipt_without_changing_stored_grading(
    show_results, initial_show_results, monkeypatch
) -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock

    from app.modules.quiz import service
    from app.modules.quiz.schemas import SubmitQuizAttemptRequest
    from sqlalchemy.orm import Session

    quiz_id, user_id = str(uuid4()), str(uuid4())
    quiz = ClassroomQuiz(
        id=quiz_id,
        course_id=COURSE_ID,
        show_results=initial_show_results,
        status="published",
        taking_open=True,
        taking_epoch=1,
        content_revision=1,
        document_json=json.dumps({"items": SAMPLE_ITEMS}),
    )
    db = Mock(spec=Session)
    db.get.return_value = quiz

    def scalar(statement):
        if list(statement.selected_columns.keys()) == ["show_results"]:
            db.commit.assert_called_once()
            return show_results
        return None

    db.scalar.side_effect = scalar
    monkeypatch.setattr(service, "_require_member", lambda *_args: "student")
    receipt = service.submit_attempt(
        db,
        SimpleNamespace(user=SimpleNamespace(id=user_id)),
        COURSE_ID,
        quiz_id,
        SubmitQuizAttemptRequest.model_validate(
            {
                "answers": [
                    {"item_id": "q1", "choice_ids": ["a"]},
                    {"item_id": "q2", "choice_ids": ["a", "c"]},
                    {"item_id": "q3", "text": "Own answer"},
                    {"item_id": "unknown", "text": "Own extra answer"},
                ]
            }
        ),
    ).model_dump(mode="json")
    stored = db.add.call_args.args[0]
    assert stored.score_objective == 3
    assert stored.score_max_objective == 3
    assert stored.grading_status == "mixed"
    assert json.loads(stored.answers_json)[0]["correct"] is True
    db.commit.assert_called_once()
    assert receipt["show_results"] is (show_results is True)
    assert receipt["answers"][2]["text"] == "Own answer"
    assert receipt["answers"][3]["text"] == "Own extra answer"
    if show_results:
        assert receipt["score_objective"] == 3
        assert receipt["grading_status"] == "mixed"
        assert receipt["answers"][0]["correct"] is True
        assert receipt["answers"][0]["points_awarded"] == 1
    else:
        _assert_hidden(receipt)
        for answer in receipt["answers"]:
            assert set(answer) <= {"item_id", "type", "choice_ids", "text"}
