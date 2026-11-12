"""Teacher-facing roster reads and account edits for one course."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_auth_self_registration import register

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
TEACHER_ID = "08b9de2d-bb75-5c71-a64b-231b48f9eb25"
HEADERS = {"Origin": "http://testserver"}


def _roster(client: TestClient) -> Any:
    return client.get(f"/api/v1/courses/{COURSE_ID}/roster")


def _entry(payload: Any, username: str) -> Any:
    return next(item for item in payload["entries"] if item["username"] == username)


def _update(client: TestClient, csrf: str, user_id: str, **fields: Any) -> Any:
    return client.patch(
        f"/api/v1/courses/{COURSE_ID}/members/{user_id}",
        json=fields,
        headers={**HEADERS, "X-CSRF-Token": csrf},
    )


def _register_student(app: Any, **kwargs: Any) -> str:
    with TestClient(app) as student:
        response = register(student, **kwargs)
        assert response.status_code == 201, response.text
        return str(response.json()["user"]["id"])


def test_roster_separates_editable_and_provisioned_accounts(
    client: TestClient, app_factory: Any
) -> None:
    app, _database, _settings = app_factory()
    _register_student(app)
    with TestClient(app) as teacher:
        login(teacher)
        response = _roster(teacher)
        assert response.status_code == 200, response.text
        payload = response.json()

    student = _entry(payload, "newstudent")
    assert student["source"] == "database"
    assert student["editable"] is True
    assert student["status"] == "active"
    assert [group["name"] for group in student["groups"]] == ["Team Aurora"]

    # The seven fixed identities are projections of the read-only catalog, so
    # the roster marks them as not editable rather than offering a lost edit.
    catalog = _entry(payload, "bowen")
    assert catalog["source"] == "catalog"
    assert catalog["editable"] is False


def test_teacher_renames_a_self_registered_student(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    user_id = _register_student(app)
    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        response = _update(teacher, csrf, user_id, display_name="  Ada   Lovelace ")
        assert response.status_code == 200, response.text
        # Surrounding and repeated whitespace is collapsed, as at registration.
        assert response.json()["display_name"] == "Ada Lovelace"


def test_teacher_moves_a_student_into_an_existing_group(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    first = _register_student(app, username="studentone", group_name="Team Aurora")
    second = _register_student(app, username="studenttwo", group_name="Team Borealis")
    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        # The name is the address: a different case and spacing must land in
        # the group the first student created, not beside it.
        response = _update(teacher, csrf, second, group_name="  team   AURORA ")
        assert response.status_code == 200, response.text
        moved = response.json()["groups"]
        assert len(moved) == 1

        roster = _roster(teacher).json()
        target = _entry(roster, "studentone")["groups"][0]["id"]
        assert moved[0]["id"] == target
        assert first != second


def test_deactivation_ends_the_session_and_blocks_login(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    user_id = _register_student(app)
    with TestClient(app) as student:
        student.post(
            "/api/v1/auth/login",
            json={"username": "newstudent", "password": "correct-horse-1"},
        )
        assert student.get("/api/v1/auth/me").status_code == 200

        with TestClient(app) as teacher:
            _payload, csrf = login(teacher)
            response = _update(teacher, csrf, user_id, status="inactive")
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "inactive"

        # The already-open session stops working; it is not left until expiry.
        assert student.get("/api/v1/auth/me").status_code == 401

    with TestClient(app) as blocked:
        assert (
            blocked.post(
                "/api/v1/auth/login",
                json={"username": "newstudent", "password": "correct-horse-1"},
            ).status_code
            == 401
        )


def test_reactivation_restores_login(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    user_id = _register_student(app)
    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        assert _update(teacher, csrf, user_id, status="inactive").status_code == 200
        assert _update(teacher, csrf, user_id, status="active").status_code == 200
    with TestClient(app) as student:
        assert (
            student.post(
                "/api/v1/auth/login",
                json={"username": "newstudent", "password": "correct-horse-1"},
            ).status_code
            == 200
        )


def test_catalog_account_edit_is_refused(client: TestClient) -> None:
    _payload, csrf = login(client)
    roster = _roster(client).json()
    target = _entry(roster, "bowen")["user_id"]
    response = _update(client, csrf, target, display_name="Renamed")
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "account_read_only"
    assert body["details"]["source"] == "catalog"


def test_teacher_cannot_deactivate_themselves(client: TestClient) -> None:
    _payload, csrf = login(client)
    response = _update(client, csrf, TEACHER_ID, status="inactive")
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "self_status_forbidden"


def test_student_may_not_read_or_edit_the_roster(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    with TestClient(app) as student:
        payload = register(student).json()
        csrf = payload["csrf_token"]
        user_id = str(payload["user"]["id"])
        assert _roster(student).status_code == 403
        assert _update(student, csrf, user_id, status="inactive").status_code == 403


def test_anonymous_roster_read_is_rejected(client: TestClient) -> None:
    assert _roster(client).status_code == 401


def test_empty_edit_is_rejected(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    user_id = _register_student(app)
    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        response = _update(teacher, csrf, user_id)
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "member_update_invalid"


def test_invalid_status_and_blank_name_are_rejected(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    user_id = _register_student(app)
    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        for fields in ({"status": "archived"}, {"display_name": "   "}, {"group_name": ""}):
            response = _update(teacher, csrf, user_id, **fields)
            assert response.status_code == 422, response.text
            assert response.json()["code"] == "member_update_invalid"


def test_member_outside_the_course_is_not_found(client: TestClient) -> None:
    _payload, csrf = login(client)
    response = _update(client, csrf, str(uuid4()), display_name="Ghost")
    assert response.status_code == 404, response.text


def test_roster_edit_requires_csrf(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    user_id = _register_student(app)
    with TestClient(app) as teacher:
        login(teacher)
        response = teacher.patch(
            f"/api/v1/courses/{COURSE_ID}/members/{user_id}",
            json={"display_name": "No CSRF"},
            headers=HEADERS,
        )
        assert response.status_code == 403, response.text
