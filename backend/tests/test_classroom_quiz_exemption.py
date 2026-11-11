"""Extended time stays student-scoped, epoch-scoped and independent of publication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from app.core.db import ALEMBIC_HEAD, Database
from app.core.models import CourseMember, User
from app.modules.quiz import service
from app.modules.quiz.models import ClassroomQuiz, ClassroomQuizAttempt, ClassroomQuizExemption
from app.seed import COURSE_ID
from sqlalchemy import delete, inspect, select, text

from tests.test_classroom_quiz_api import (
    Actor,
    _create_and_publish,
    _create_publish_open,
    _submit,
)
from tests.test_classroom_quiz_api import actors as actors
from tests.test_classroom_quiz_api import student as student
from tests.test_classroom_quiz_api import teacher as teacher


def _path(quiz_id: str) -> str:
    return f"/courses/{COURSE_ID}/quizzes/{quiz_id}"


def _put(teacher: Actor, quiz_id: str, ids: list[str], deadline: datetime | None = None) -> Any:
    return teacher.client.put(
        f"/api/v1{_path(quiz_id)}/exemptions",
        json={
            "student_ids": ids,
            "deadline_at": (deadline or datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
        headers=teacher.headers,
    )


def _delete(actor: Actor, quiz_id: str, student_id: str | None = None) -> Any:
    suffix = f"/{student_id}" if student_id else ""
    return actor.client.delete(f"/api/v1{_path(quiz_id)}/exemptions{suffix}", headers=actor.headers)


def _paused(teacher: Actor) -> str:
    quiz_id = _create_publish_open(teacher)
    assert teacher.post(f"{_path(quiz_id)}/pause-taking").status_code == 200
    return quiz_id


def _rows(database: Database, quiz_id: str) -> list[ClassroomQuizExemption]:
    with database.session() as db:
        return list(
            db.scalars(
                select(ClassroomQuizExemption).where(ClassroomQuizExemption.quiz_id == quiz_id)
            )
        )


def _assert_closed(response: Any) -> None:
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "quiz_taking_closed"
    assert response.json()["message"] == "The quiz is not open for taking right now."


def _student_views(student: Actor, quiz_id: str) -> list[dict[str, Any]]:
    detail = student.get(_path(quiz_id))
    assert detail.status_code == 200, detail.text
    listing = student.get(f"/courses/{COURSE_ID}/quizzes")
    assert listing.status_code == 200
    summary = next(row for row in listing.json() if row["id"] == quiz_id)
    assert summary["exemption_count"] == 0
    assert summary["exemption_deadline_latest"] is None
    assert '"exemptions"' not in detail.text
    assert '"answer"' not in detail.text
    assert '"rubric"' not in detail.text
    return [detail.json(), summary]


def test_paused_exemption_submit_and_viewer_dtos(teacher, student, actors) -> None:
    other = actors("jade")
    quiz_id = _paused(teacher)
    _assert_closed(_submit(quiz_id, student))
    for view in _student_views(student, quiz_id):
        assert view["can_take_now"] is False
        assert view["exempt_until"] is None
    deadline = datetime.now(UTC) + timedelta(hours=1)
    response = _put(teacher, quiz_id, [student.id], deadline)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["taking_epoch"] == 1
    assert payload["exemptions"][0]["active"] is True
    picker = {row["student_id"]: row for row in payload["students"]}
    assert teacher.id not in picker
    assert picker[student.id]["submitted"] is False
    assert datetime.fromisoformat(picker[student.id]["exempt_until"]) == deadline
    for view in _student_views(student, quiz_id):
        assert view["can_take_now"] is True
        assert view["taking_open"] is False
        assert datetime.fromisoformat(view["exempt_until"]) == deadline
    for view in _student_views(other, quiz_id):
        assert view["can_take_now"] is False
        assert view["exempt_until"] is None
    _assert_closed(_submit(quiz_id, other))
    for view in [
        teacher.get(_path(quiz_id)).json(),
        teacher.get(f"/courses/{COURSE_ID}/quizzes").json()[0],
    ]:
        assert view["exemption_count"] == 1
        assert datetime.fromisoformat(view["exemption_deadline_latest"]) == deadline
        assert view["exempt_until"] is None
        assert view["can_take_now"] is False
    assert _submit(quiz_id, student).status_code == 201
    for view in _student_views(student, quiz_id):
        assert view["can_take_now"] is False
    duplicate = _submit(quiz_id, student)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "quiz_attempt_exists"


def test_deadline_expiration_is_fresh_and_strict(teacher, student, monkeypatch) -> None:
    quiz_id = _paused(teacher)
    deadline = datetime.now(UTC) + timedelta(seconds=20)
    assert _put(teacher, quiz_id, [student.id], deadline).status_code == 200
    monkeypatch.setattr(service, "_now", lambda: deadline)
    _assert_closed(_submit(quiz_id, student))
    for view in _student_views(student, quiz_id):
        assert view["can_take_now"] is False
        assert view["exempt_until"] is None
    listing = teacher.get(f"{_path(quiz_id)}/exemptions").json()
    assert listing["exemptions"][0]["active"] is False
    picker = next(row for row in listing["students"] if row["student_id"] == student.id)
    assert datetime.fromisoformat(picker["exempt_until"]) == deadline
    assert teacher.get(_path(quiz_id)).json()["exemption_count"] == 0
    assert teacher.get(_path(quiz_id)).json()["exemption_deadline_latest"] is None
    monkeypatch.setattr(service, "_now", lambda: deadline + timedelta(seconds=1))
    _assert_closed(_submit(quiz_id, student))


@pytest.mark.parametrize("hidden", [False, True])
def test_grant_rejects_any_current_attempt_atomically(
    teacher, student, actors, database, hidden
) -> None:
    other = actors("jade")
    quiz_id = _create_publish_open(teacher)
    attempt = _submit(quiz_id, student)
    assert attempt.status_code == 201
    if hidden:
        with database.session() as db:
            db.get(ClassroomQuizAttempt, attempt.json()["id"]).teacher_hidden_at = datetime.now(UTC)
            db.commit()
    assert teacher.post(f"{_path(quiz_id)}/pause-taking").status_code == 200
    response = _put(teacher, quiz_id, [other.id, student.id])
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "quiz_exemption_already_submitted"
    assert response.json()["message"] == "Some students have already submitted."
    assert response.json()["details"] == {"student_ids": [student.id]}
    assert _rows(database, quiz_id) == []
    picker = teacher.get(f"{_path(quiz_id)}/exemptions").json()["students"]
    assert next(row for row in picker if row["student_id"] == student.id)["submitted"] is True


def test_inserted_exemption_does_not_bypass_attempt_unique_index(
    teacher, student, database
) -> None:
    quiz_id = _create_publish_open(teacher)
    assert _submit(quiz_id, student).status_code == 201
    assert teacher.post(f"{_path(quiz_id)}/pause-taking").status_code == 200
    _insert(database, quiz_id, student.id, 1)
    response = _submit(quiz_id, student)
    assert response.status_code == 409
    assert response.json()["code"] == "quiz_attempt_exists"
    for view in _student_views(student, quiz_id):
        assert view["can_take_now"] is False


def _insert(database: Database, quiz_id: str, student_id: str, epoch: int) -> None:
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            ClassroomQuizExemption(
                id=str(uuid4()),
                quiz_id=quiz_id,
                course_id=COURSE_ID,
                student_user_id=student_id,
                taking_epoch=epoch,
                deadline_at=now + timedelta(hours=1),
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()


@pytest.mark.parametrize("invalid_kind", ["teacher", "nonmember", "inactive", "unknown"])
def test_invalid_students_fail_whole_request(
    teacher, student, actors, database, invalid_kind
) -> None:
    other = actors("jade")
    quiz_id = _paused(teacher)
    invalid_id = teacher.id if invalid_kind == "teacher" else other.id
    with database.session() as db:
        if invalid_kind == "nonmember":
            db.execute(
                delete(CourseMember).where(
                    CourseMember.course_id == COURSE_ID, CourseMember.user_id == other.id
                )
            )
        elif invalid_kind == "inactive":
            db.get(User, other.id).status = "disabled"
        elif invalid_kind == "unknown":
            invalid_id = str(uuid4())
        db.commit()
    response = _put(teacher, quiz_id, [student.id, invalid_id])
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "quiz_exemption_invalid_student"
    assert response.json()["message"] == "Only students of this class can be extended."
    assert response.json()["details"] == {"student_ids": [invalid_id]}
    assert _rows(database, quiz_id) == []
    picker = teacher.get(f"{_path(quiz_id)}/exemptions").json()["students"]
    if invalid_kind != "unknown":
        assert invalid_id not in {row["student_id"] for row in picker}


@pytest.mark.parametrize("naive", [False, True])
def test_deadline_validation(teacher, student, database, naive) -> None:
    quiz_id = _paused(teacher)
    deadline = datetime.now(UTC) - timedelta(seconds=1)
    if naive:
        deadline = (deadline + timedelta(hours=1)).replace(tzinfo=None)
    response = _put(teacher, quiz_id, [student.id], deadline)
    assert response.status_code == 422, response.text
    expected = "quiz_exemption_deadline_naive" if naive else "quiz_exemption_deadline_past"
    assert response.json()["code"] == expected
    if not naive:
        assert response.json()["message"] == "The deadline must be in the future."
    assert _rows(database, quiz_id) == []


def test_never_started_grant_rejected_but_list_remove_allowed(teacher, student, database) -> None:
    quiz_id = _create_and_publish(teacher)
    response = _put(teacher, quiz_id, [student.id])
    assert response.status_code == 409
    assert response.json()["code"] == "quiz_exemption_not_started"
    assert response.json()["message"] == "Start taking once before extending time."
    assert _rows(database, quiz_id) == []
    assert teacher.get(f"{_path(quiz_id)}/exemptions").status_code == 200
    assert _delete(teacher, quiz_id, student.id).status_code == 204
    assert _delete(teacher, quiz_id).status_code == 204
    assert teacher.post(f"{_path(quiz_id)}/unpublish").status_code == 200
    assert _put(teacher, quiz_id, [student.id]).json()["code"] == "quiz_exemption_not_started"


def test_new_round_clears_all_rows_and_old_attempt_does_not_block_grant(
    teacher, student, database
) -> None:
    quiz_id = _paused(teacher)
    assert _put(teacher, quiz_id, [student.id]).status_code == 200
    _insert(database, quiz_id, student.id, 0)
    opened = teacher.post(f"{_path(quiz_id)}/start-taking")
    assert opened.status_code == 200
    assert opened.json()["taking_epoch"] == 2
    assert _rows(database, quiz_id) == []
    assert teacher.post(f"{_path(quiz_id)}/pause-taking").status_code == 200
    _assert_closed(_submit(quiz_id, student))
    assert _put(teacher, quiz_id, [student.id]).status_code == 200
    assert _submit(quiz_id, student).status_code == 201
    assert teacher.post(f"{_path(quiz_id)}/start-taking").status_code == 200
    assert _put(teacher, quiz_id, [student.id]).status_code == 200


def test_stale_rows_ignored_everywhere(teacher, student, database) -> None:
    quiz_id = _paused(teacher)
    _insert(database, quiz_id, student.id, 0)
    listing = teacher.get(f"{_path(quiz_id)}/exemptions").json()
    assert listing["exemptions"] == []
    assert all(row["exempt_until"] is None for row in listing["students"])
    assert teacher.get(_path(quiz_id)).json()["exemption_count"] == 0
    for view in _student_views(student, quiz_id):
        assert view["can_take_now"] is False
        assert view["exempt_until"] is None
    _assert_closed(_submit(quiz_id, student))


def test_unpublish_keeps_rows_and_allows_grant_edit_remove(
    teacher, student, actors, database
) -> None:
    other = actors("jade")
    quiz_id = _paused(teacher)
    assert _put(teacher, quiz_id, [student.id]).status_code == 200
    assert teacher.post(f"{_path(quiz_id)}/unpublish").status_code == 200
    assert len(_rows(database, quiz_id)) == 1
    assert _submit(quiz_id, student).status_code == 404
    assert _put(teacher, quiz_id, [other.id]).status_code == 200
    assert (
        _put(teacher, quiz_id, [student.id], datetime.now(UTC) + timedelta(hours=2)).status_code
        == 200
    )
    assert _delete(teacher, quiz_id, other.id).status_code == 204
    assert len(teacher.get(f"{_path(quiz_id)}/exemptions").json()["exemptions"]) == 1
    pub = teacher.post(f"{_path(quiz_id)}/publish")
    assert pub.status_code == 200
    assert pub.json()["taking_open"] is False
    assert pub.json()["taking_epoch"] == 1
    assert _submit(quiz_id, student).status_code == 201


def test_upsert_dedupe_distinct_deadlines_and_delete(teacher, student, actors, database) -> None:
    other = actors("jade")
    quiz_id = _paused(teacher)
    first = _put(teacher, quiz_id, [student.id, student.id]).json()["exemptions"][0]
    deadline = datetime.now(UTC) + timedelta(hours=2)
    updated = _put(teacher, quiz_id, [student.id], deadline).json()["exemptions"][0]
    assert updated["id"] == first["id"]
    assert updated["created_at"] == first["created_at"]
    assert updated["updated_at"] > first["updated_at"]
    assert datetime.fromisoformat(updated["deadline_at"]) == deadline
    response = _put(teacher, quiz_id, [other.id], deadline + timedelta(hours=1))
    assert response.status_code == 200
    rows = response.json()["exemptions"]
    assert len(rows) == 2
    assert len({row["deadline_at"] for row in rows}) == 2
    assert rows == sorted(
        rows, key=lambda row: (row["display_name"].casefold(), row["username"].casefold())
    )
    students = response.json()["students"]
    assert students == sorted(
        students, key=lambda row: (row["display_name"].casefold(), row["username"].casefold())
    )
    assert datetime.fromisoformat(
        teacher.get(_path(quiz_id)).json()["exemption_deadline_latest"]
    ) == deadline + timedelta(hours=1)
    for _ in range(2):
        assert _delete(teacher, quiz_id, student.id).status_code == 204
    assert len(_rows(database, quiz_id)) == 1
    for _ in range(2):
        assert _delete(teacher, quiz_id).status_code == 204
    assert _rows(database, quiz_id) == []


@pytest.mark.parametrize("size", [0, 501])
def test_student_ids_request_bounds(teacher, student, database, size) -> None:
    quiz_id = _paused(teacher)
    response = _put(teacher, quiz_id, [student.id] * size)
    assert response.status_code == 400
    assert response.json()["code"] == "malformed_request"
    assert _rows(database, quiz_id) == []


def test_teacher_endpoint_authorization_unknown_quiz_and_csrf(teacher, student) -> None:
    quiz_id = _paused(teacher)
    for response in [
        student.get(f"{_path(quiz_id)}/exemptions"),
        _put(student, quiz_id, [student.id]),
        _delete(student, quiz_id, student.id),
        _delete(student, quiz_id),
    ]:
        assert response.status_code in (403, 404)
    missing = str(uuid4())
    for response in [
        teacher.get(f"{_path(missing)}/exemptions"),
        _put(teacher, missing, [student.id]),
        _delete(teacher, missing, student.id),
        _delete(teacher, missing),
    ]:
        assert response.status_code == 404
    for method, suffix in [("put", ""), ("delete", ""), ("delete", f"/{student.id}")]:
        response = teacher.client.request(
            method,
            f"/api/v1{_path(quiz_id)}/exemptions{suffix}",
            headers={"Origin": "http://testserver"},
            json={
                "student_ids": [student.id],
                "deadline_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
        )
        assert response.status_code == 403


def test_exemptions_do_not_cross_quizzes_and_quiz_delete_cascades(
    teacher, student, database
) -> None:
    quiz_id = _paused(teacher)
    other = _paused(teacher)
    assert _put(teacher, quiz_id, [student.id]).status_code == 200
    _assert_closed(_submit(other, student))
    assert teacher.get(f"{_path(other)}/exemptions").json()["exemptions"] == []
    for view in _student_views(student, other):
        assert view["can_take_now"] is False
        assert view["exempt_until"] is None
    # Exercise the FK independently of the service's delete path.
    with database.session() as db:
        db.execute(delete(ClassroomQuiz).where(ClassroomQuiz.id == quiz_id))
        db.commit()
    assert _rows(database, quiz_id) == []
    assert _put(teacher, other, [student.id]).status_code == 200
    response = teacher.client.delete(f"/api/v1{_path(other)}", headers=teacher.headers)
    assert response.status_code == 204, response.text
    assert _rows(database, other) == []


def test_open_quiz_viewer_can_take_tracks_current_epoch_attempt(teacher, student) -> None:
    quiz_id = _create_publish_open(teacher)
    for view in _student_views(student, quiz_id):
        assert view["can_take_now"] is True
        assert view["exempt_until"] is None
    assert _submit(quiz_id, student).status_code == 201
    for view in _student_views(student, quiz_id):
        assert view["can_take_now"] is False
    assert teacher.post(f"{_path(quiz_id)}/pause-taking").status_code == 200
    assert teacher.post(f"{_path(quiz_id)}/start-taking").status_code == 200
    for view in _student_views(student, quiz_id):
        assert view["can_take_now"] is True


def test_quiz_exemption_migration_matches_model(postgres_url) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    database = Database(postgres_url)
    database.upgrade_schema()
    try:
        with database.engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version")) == ALEMBIC_HEAD
            )
            table = ClassroomQuizExemption.__table__
            context = MigrationContext.configure(
                connection,
                opts={
                    "include_object": lambda obj, name, kind, reflected, compare_to: (
                        name == table.name if kind == "table" else True
                    )
                },
            )
            assert compare_metadata(context, table.metadata) == []
            inspector = inspect(connection)
            assert (
                inspector.get_unique_constraints(table.name)[0]["name"]
                == "ux_classroom_quiz_exemptions_quiz_student_epoch"
            )
            fks = {
                fk["constrained_columns"][0]: fk["options"]["ondelete"]
                for fk in inspector.get_foreign_keys(table.name)
            }
            assert fks == {
                "quiz_id": "CASCADE",
                "course_id": "CASCADE",
                "student_user_id": "CASCADE",
                "created_by_user_id": "SET NULL",
            }
    finally:
        database.dispose()
