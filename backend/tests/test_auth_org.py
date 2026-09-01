from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.models import SessionRecord
from app.modules.auth.service import session_hash
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from tests.conftest import login, make_foreign_group

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_DEMO_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


def test_health_and_auth_rotation_csrf_logout(client: TestClient, app_factory: Any) -> None:
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready"}
    first, csrf = login(client)
    first_cookie = client.cookies.get("maya_session")
    assert len(first["csrf_token"]) >= 32
    app, database, _settings = app_factory()
    with TestClient(app) as isolated_client:
        isolated_payload, _isolated_csrf = login(isolated_client)
        with database.session() as session:
            row = session.scalar(select(SessionRecord))
            assert row is not None
            assert isolated_client.cookies.get("maya_session") not in row.id_hash
            assert isolated_payload["csrf_token"] not in row.csrf_hash
    assert client.get("/api/v1/auth/me").json()["csrf_token"] == csrf
    second, csrf2 = login(client)
    assert second["csrf_token"] != csrf
    assert client.cookies.get("maya_session") != first_cookie
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf2},
        ).status_code
        == 204
    )
    assert client.get("/api/v1/auth/me").status_code == 401


def test_cookie_secure_follows_https_origin(app_factory: Any) -> None:
    app, _database, settings = app_factory()
    settings.classroom_public_base_url = "https://classroom.example"
    with TestClient(app, base_url="https://testserver") as https_client:
        response = https_client.post(
            "/api/v1/auth/login",
            json={"username": "maya", "password": "demo-password"},
        )
        assert response.status_code == 200
        assert "Secure" in response.headers["set-cookie"]


def test_session_expiry_and_csrf_failures(client: TestClient, app_factory: Any) -> None:
    _payload, csrf = login(client)
    assert (
        client.post("/api/v1/auth/logout", headers={"Origin": "http://testserver"}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "http://evil.example", "X-CSRF-Token": csrf},
        ).status_code
        == 403
    )

    app, database, _settings = app_factory()
    with TestClient(app) as other_client:
        _payload, _csrf = login(other_client)
        with database.session() as session:
            row = session.get(SessionRecord, session_hash(other_client.cookies.get("maya_session")))
            assert row is not None
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert other_client.get("/api/v1/auth/me").status_code == 401


def test_demo_mode_false_hides_switch(client: TestClient, app_factory: Any) -> None:
    app, _database, _settings = app_factory(demo_mode=False)
    with TestClient(app) as disabled_client:
        _payload, csrf = login(disabled_client)
        assert disabled_client.get("/api/v1/auth/demo-identities").status_code == 404
        assert (
            disabled_client.post(
                "/api/v1/auth/switch",
                headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
                json={"user_id": "60541c78-30f1-55c5-b2aa-207b6a766883"},
            ).status_code
            == 404
        )


def test_org_scope_teacher_and_student(client: TestClient, database: Any) -> None:
    teacher, _csrf = login(client)
    assert teacher["user"]["courses"][0]["course_id"] == COURSE_ID
    course = client.get(f"/api/v1/courses/{COURSE_ID}")
    assert course.status_code == 200
    assert len(course.json()["members"]) == 4
    groups = client.get(f"/api/v1/courses/{COURSE_ID}/groups")
    assert {item["id"] for item in groups.json()} == {GROUP_DEMO_ID}
    assert len(client.get(f"/api/v1/groups/{GROUP_DEMO_ID}").json()["members"]) == 3

    foreign_group_id = make_foreign_group(database, COURSE_ID)
    switched = client.post(
        "/api/v1/auth/switch",
        headers={"Origin": "http://testserver", "X-CSRF-Token": _csrf},
        json={"user_id": "60541c78-30f1-55c5-b2aa-207b6a766883"},
    ).json()
    student_groups = client.get(f"/api/v1/courses/{COURSE_ID}/groups")
    assert [item["id"] for item in student_groups.json()] == [GROUP_DEMO_ID]
    assert client.get(f"/api/v1/groups/{foreign_group_id}").status_code == 404
    assert switched["user"]["groups"][0]["group_id"] == GROUP_DEMO_ID


def test_cross_scope_group_query_applies_membership_in_same_select(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    statements: list[str] = []

    def capture(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        statements.append(statement.lower())

    event.listen(database.engine, "before_cursor_execute", capture)
    try:
        with TestClient(app) as scoped_client:
            _payload, csrf = login(scoped_client, "maya")
            switched = scoped_client.post(
                "/api/v1/auth/switch",
                headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
                json={"user_id": "60541c78-30f1-55c5-b2aa-207b6a766883"},
            )
            assert switched.status_code == 200
            foreign_group_id = make_foreign_group(database, COURSE_ID)
            statements.clear()
            response = scoped_client.get(f"/api/v1/groups/{foreign_group_id}")
            assert response.status_code == 404
    finally:
        event.remove(database.engine, "before_cursor_execute", capture)

    scoped_group_queries = [
        statement
        for statement in statements
        if "from groups" in statement and "course_members" in statement
    ]
    assert scoped_group_queries
    assert "left outer join group_members" in scoped_group_queries[-1]
