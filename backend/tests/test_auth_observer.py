"""The shared MAYA teaching account and teacher group membership."""

from __future__ import annotations

from typing import Any

from app.core.models import CourseMember, GroupMember, User
from app.modules.auth.observer import OBSERVER_USER_ID, OBSERVER_USERNAME
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.test_auth_self_registration import register

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_A_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
MAYA_PASSWORD = "classroom-observer-2026"


def _maya_app(app_factory: Any, password: str | None = MAYA_PASSWORD) -> Any:
    app, database, settings = app_factory(maya_password=password)
    return app, database, settings


def _login_maya(client: TestClient, password: str = MAYA_PASSWORD) -> tuple[Any, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": OBSERVER_USERNAME, "password": password},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload, payload["csrf_token"]


def test_maya_is_provisioned_and_can_sign_in(app_factory: Any) -> None:
    app, database, _settings = _maya_app(app_factory)
    with TestClient(app) as client:
        payload, _csrf = _login_maya(client)
        assert payload["user"]["username"] == OBSERVER_USERNAME
        assert payload["user"]["courses"] == [{"course_id": COURSE_ID, "role": "teacher"}]
    with database.session() as session:
        user = session.get(User, OBSERVER_USER_ID)
        assert user is not None
        assert user.status == "active"


def test_maya_is_absent_without_a_configured_password(app_factory: Any) -> None:
    app, database, _settings = _maya_app(app_factory, password=None)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": OBSERVER_USERNAME, "password": MAYA_PASSWORD},
        )
        assert response.status_code == 401
    with database.session() as session:
        assert session.get(User, OBSERVER_USER_ID) is None


def test_removing_the_password_disables_the_account(app_factory: Any) -> None:
    app, database, _settings = _maya_app(app_factory)
    with TestClient(app) as client:
        _login_maya(client)
    # A second app over the same database with no configured password.
    disabled_app, _database, _settings = app_factory(maya_password=None)
    with TestClient(disabled_app) as client:
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": OBSERVER_USERNAME, "password": MAYA_PASSWORD},
            ).status_code
            == 401
        )
    with database.session() as session:
        user = session.get(User, OBSERVER_USER_ID)
        assert user is not None
        assert user.status == "disabled"


def test_maya_sees_every_group_including_student_created_ones(app_factory: Any) -> None:
    app, _database, _settings = _maya_app(app_factory)
    with TestClient(app) as student:
        assert register(student, group_name="Team Aurora").status_code == 201
    with TestClient(app) as client:
        _login_maya(client)
        groups = client.get(f"/api/v1/courses/{COURSE_ID}/groups").json()
        names = {group["name"] for group in groups}
        assert {"Demo Group", "Team Aurora"} <= names


def test_maya_can_join_any_group_without_being_chosen(app_factory: Any) -> None:
    app, database, _settings = _maya_app(app_factory)
    with TestClient(app) as student:
        assert register(student, group_name="Team Aurora").status_code == 201
        group_id = student.get("/api/v1/auth/me").json()["user"]["groups"][0]["group_id"]
    with TestClient(app) as client:
        _payload, csrf = _login_maya(client)
        response = client.post(
            f"/api/v1/groups/{group_id}/membership",
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )
        assert response.status_code == 200, response.text
        members = {member["display_name"] for member in response.json()["members"]}
        assert OBSERVER_USERNAME in members
    with database.session() as session:
        row = session.scalar(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == OBSERVER_USER_ID,
            )
        )
        assert row is not None


def test_joining_and_leaving_are_idempotent(app_factory: Any) -> None:
    app, _database, _settings = _maya_app(app_factory)
    with TestClient(app) as client:
        _payload, csrf = _login_maya(client)
        headers = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
        membership = f"/api/v1/groups/{GROUP_A_ID}/membership"
        # Both directions are idempotent: a repeated call is not an error.
        assert client.post(membership, headers=headers).status_code == 200
        assert client.post(membership, headers=headers).status_code == 200
        assert client.delete(membership, headers=headers).status_code == 204
        assert client.delete(membership, headers=headers).status_code == 204


def test_student_cannot_join_a_group_it_did_not_choose(app_factory: Any) -> None:
    app, _database, _settings = _maya_app(app_factory)
    with TestClient(app) as student:
        response = register(student, group_name="Team Aurora")
        assert response.status_code == 201
        csrf = response.json()["csrf_token"]
        # Group A belongs to other students; a student may not add itself.
        assert (
            student.post(
                f"/api/v1/groups/{GROUP_A_ID}/membership",
                headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
            ).status_code
            == 403
        )


def test_join_requires_csrf(app_factory: Any) -> None:
    app, _database, _settings = _maya_app(app_factory)
    with TestClient(app) as client:
        _login_maya(client)
        assert (
            client.post(
                f"/api/v1/groups/{GROUP_A_ID}/membership",
                headers={"Origin": "http://testserver", "X-CSRF-Token": "wrong" * 8},
            ).status_code
            == 403
        )


def test_maya_username_cannot_be_registered(app_factory: Any) -> None:
    app, _database, _settings = _maya_app(app_factory)
    with TestClient(app) as client:
        response = register(client, username="maya")
        assert response.status_code == 409
        assert response.json()["code"] == "username_taken"


def test_password_change_takes_effect_on_restart(app_factory: Any) -> None:
    app, database, _settings = _maya_app(app_factory)
    with TestClient(app) as client:
        _login_maya(client)
    rotated_app, _database, _settings = app_factory(maya_password="a-different-observer-password")
    with TestClient(rotated_app) as client:
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": OBSERVER_USERNAME, "password": MAYA_PASSWORD},
            ).status_code
            == 401
        )
        _login_maya(client, password="a-different-observer-password")


def test_maya_holds_the_teacher_role_for_reset(app_factory: Any) -> None:
    """Full teacher rights, exercised through an existing teacher-only route."""

    app, database, _settings = _maya_app(app_factory)
    with TestClient(app) as student:
        assert register(student).status_code == 201
        user_id = student.get("/api/v1/auth/me").json()["user"]["id"]
    with TestClient(app) as client:
        _payload, csrf = _login_maya(client)
        response = client.post(
            "/api/v1/auth/password-resets",
            json={"course_id": COURSE_ID, "user_id": user_id},
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )
        assert response.status_code == 200, response.text
    with database.session() as session:
        role = session.scalar(
            select(CourseMember.role).where(
                CourseMember.course_id == COURSE_ID,
                CourseMember.user_id == OBSERVER_USER_ID,
            )
        )
        assert role == "teacher"
