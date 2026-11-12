"""Teacher-initiated password reset for self-registered student accounts."""

from __future__ import annotations

from typing import Any

from app.core.models import SessionRecord, User
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.test_auth_self_registration import register

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
TEACHER_ID = "08b9de2d-bb75-5c71-a64b-231b48f9eb25"


def _reset(
    client: TestClient,
    csrf: str,
    user_id: str,
    **extra: Any,
) -> Any:
    body: dict[str, Any] = {"course_id": COURSE_ID, "user_id": user_id}
    body.update(extra)
    return client.post(
        "/api/v1/auth/password-resets",
        json=body,
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )


def _register_student(app: Any) -> str:
    with TestClient(app) as student:
        response = register(student)
        assert response.status_code == 201, response.text
        return str(response.json()["user"]["id"])


def test_teacher_reset_issues_a_working_password(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    user_id = _register_student(app)
    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        response = _reset(teacher, csrf, user_id)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["username"] == "newstudent"
        issued = result["password"]
        assert len(issued) == 8
    with TestClient(app) as student:
        # The old password stops working and the issued one takes over.
        assert (
            student.post(
                "/api/v1/auth/login",
                json={"username": "newstudent", "password": "correct-horse-1"},
            ).status_code
            == 401
        )
        assert (
            student.post(
                "/api/v1/auth/login",
                json={"username": "newstudent", "password": issued},
            ).status_code
            == 200
        )


def test_teacher_can_choose_the_replacement_password(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    user_id = _register_student(app)
    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        response = _reset(teacher, csrf, user_id, new_password="classroom-2026")
        assert response.status_code == 200, response.text
        assert response.json()["password"] == "classroom-2026"
    with TestClient(app) as student:
        assert (
            student.post(
                "/api/v1/auth/login",
                json={"username": "newstudent", "password": "classroom-2026"},
            ).status_code
            == 200
        )


def test_reset_revokes_the_students_existing_sessions(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as student:
        assert register(student).status_code == 201
        user_id = str(student.get("/api/v1/auth/me").json()["user"]["id"])
        assert student.get("/api/v1/auth/me").status_code == 200
        with TestClient(app) as teacher:
            _payload, csrf = login(teacher)
            assert _reset(teacher, csrf, user_id).status_code == 200
        # The student's cookie is still presented but no longer resolves.
        assert student.get("/api/v1/auth/me").status_code == 401
    with database.session() as session:
        rows = session.scalars(select(SessionRecord).where(SessionRecord.user_id == user_id)).all()
        assert rows
        assert all(row.revoked_at is not None for row in rows)


def test_generated_password_avoids_ambiguous_characters(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    user_id = _register_student(app)
    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        issued = _reset(teacher, csrf, user_id).json()["password"]
    # Read aloud in a classroom, these are the characters that get confused.
    assert not set(issued) & set("01OIl")


def test_student_cannot_reset_another_student(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    victim_id = _register_student(app)
    with TestClient(app) as attacker:
        response = register(attacker, username="attacker", group_name="Other")
        assert response.status_code == 201
        csrf = response.json()["csrf_token"]
        assert _reset(attacker, csrf, victim_id).status_code == 403


def test_anonymous_caller_cannot_reset(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    user_id = _register_student(app)
    with TestClient(app) as anonymous:
        response = anonymous.post(
            "/api/v1/auth/password-resets",
            json={"course_id": COURSE_ID, "user_id": user_id},
            headers={"Origin": "http://testserver", "X-CSRF-Token": "x" * 32},
        )
        assert response.status_code == 401


def test_reset_requires_a_csrf_token(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    user_id = _register_student(app)
    with TestClient(app) as teacher:
        login(teacher)
        response = teacher.post(
            "/api/v1/auth/password-resets",
            json={"course_id": COURSE_ID, "user_id": user_id},
            headers={"Origin": "http://testserver", "X-CSRF-Token": "wrong" * 8},
        )
        assert response.status_code == 403


def test_catalog_account_reports_that_it_cannot_be_reset(client: TestClient) -> None:
    _payload, csrf = login(client)
    response = _reset(client, csrf, TEACHER_ID)
    assert response.status_code == 422
    assert response.json()["code"] == "reset_not_supported"


def test_unknown_member_is_not_found(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        response = _reset(teacher, csrf, "11111111-1111-5111-8111-111111111111")
        assert response.status_code == 404


def test_rejects_an_unacceptable_chosen_password(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    user_id = _register_student(app)
    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        response = _reset(teacher, csrf, user_id, new_password="ab1")
        assert response.status_code == 422
        assert response.json()["code"] == "registration_invalid"


def test_reset_does_not_change_the_public_user_row(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    user_id = _register_student(app)
    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        assert _reset(teacher, csrf, user_id).status_code == 200
    with database.session() as session:
        user = session.get(User, user_id)
        assert user is not None
        assert user.username == "newstudent"
        assert user.status == "active"
