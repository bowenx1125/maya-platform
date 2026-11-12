"""Self-service avatar and password behavior across public projections."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.models import Agent, AgentVersion, GroupMember, User
from app.modules.avatars import DEFAULT_AVATAR_CONFIG
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.test_auth_self_registration import register

AVATAR = "scholar-round:sage"
COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"


def _headers(csrf: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf}


def test_avatar_flows_through_session_group_and_roster(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    with TestClient(app) as student:
        payload, csrf = login(student, "bowen")
        user_id = payload["user"]["id"]
        group_id = payload["user"]["groups"][0]["group_id"]
        response = student.patch(
            "/api/v1/auth/me",
            json={"avatar": AVATAR},
            headers=_headers(csrf),
        )
        assert response.status_code == 200, response.text
        assert response.json()["user"]["avatar"] == AVATAR
        member = next(
            row
            for row in student.get(f"/api/v1/groups/{group_id}").json()["members"]
            if row["user_id"] == user_id
        )
        assert member["avatar"] == AVATAR

    with TestClient(app) as teacher:
        _payload, _csrf = login(teacher)
        entry = next(
            row
            for row in teacher.get(f"/api/v1/courses/{COURSE_ID}/roster").json()["entries"]
            if row["user_id"] == user_id
        )
        assert entry["avatar"] == AVATAR


def test_invalid_avatar_fails_closed(client: TestClient) -> None:
    _payload, csrf = login(client, "bowen")
    response = client.patch(
        "/api/v1/auth/me",
        json={"avatar": "../../not-a-scholar"},
        headers=_headers(csrf),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "avatar_invalid"


def test_a_student_renames_themselves_and_classmates_see_it(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    with TestClient(app) as student:
        registration = register(student)
        assert registration.status_code == 201, registration.text
        csrf = registration.json()["csrf_token"]
        user_id = registration.json()["user"]["id"]
        renamed = student.patch(
            "/api/v1/auth/me",
            json={"display_name": "  Ada   Lovelace "},
            headers=_headers(csrf),
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["user"]["display_name"] == "Ada Lovelace"
        # A rename alone leaves the avatar as it was.
        assert renamed.json()["user"]["avatar"] is None

        empty = student.patch(
            "/api/v1/auth/me",
            json={"display_name": "   "},
            headers=_headers(renamed.json()["csrf_token"]),
        )
        assert empty.status_code == 422
        assert empty.json()["code"] == "display_name_invalid"

    with TestClient(app) as teacher:
        login(teacher)
        entry = next(
            row
            for row in teacher.get(f"/api/v1/courses/{COURSE_ID}/roster").json()["entries"]
            if row["user_id"] == user_id
        )
        assert entry["display_name"] == "Ada Lovelace"


def test_a_catalog_account_keeps_the_name_the_account_list_gives_it(
    client: TestClient,
) -> None:
    payload, csrf = login(client, "bowen")
    response = client.patch(
        "/api/v1/auth/me",
        json={"display_name": "Someone Else"},
        headers=_headers(csrf),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "display_name_managed"
    me = client.get("/api/v1/auth/me").json()
    assert me["user"]["display_name"] == payload["user"]["display_name"]


def test_password_change_keeps_current_session_and_revokes_others(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    with TestClient(app) as current:
        registration = register(current)
        assert registration.status_code == 201
        csrf = registration.json()["csrf_token"]
        with TestClient(app) as other:
            assert (
                other.post(
                    "/api/v1/auth/login",
                    json={"username": "new-student", "password": "correct-horse-1"},
                ).status_code
                == 200
            )
            changed = current.post(
                "/api/v1/auth/password",
                json={
                    "current_password": "correct-horse-1",
                    "new_password": "new-classroom-password",
                },
                headers=_headers(csrf),
            )
            assert changed.status_code == 204, changed.text
            assert current.get("/api/v1/auth/me").status_code == 200
            assert other.get("/api/v1/auth/me").status_code == 401

    with TestClient(app) as signed_out:
        assert (
            signed_out.post(
                "/api/v1/auth/login",
                json={"username": "new-student", "password": "correct-horse-1"},
            ).status_code
            == 401
        )
        assert (
            signed_out.post(
                "/api/v1/auth/login",
                json={"username": "new-student", "password": "new-classroom-password"},
            ).status_code
            == 200
        )


def test_catalog_account_can_replace_its_password(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    with TestClient(app) as student:
        _payload, csrf = login(student, "bowen")
        response = student.post(
            "/api/v1/auth/password",
            json={
                "current_password": "demo-password",
                "new_password": "student-owned-password",
            },
            headers=_headers(csrf),
        )
        assert response.status_code == 204, response.text
    with TestClient(app) as signed_out:
        assert (
            signed_out.post(
                "/api/v1/auth/login",
                json={"username": "bowen", "password": "demo-password"},
            ).status_code
            == 401
        )
        assert (
            signed_out.post(
                "/api/v1/auth/login",
                json={"username": "bowen", "password": "student-owned-password"},
            ).status_code
            == 202
        )


def test_wrong_current_password_does_not_change_the_credential(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    with TestClient(app) as student:
        registration = register(student)
        csrf = registration.json()["csrf_token"]
        response = student.post(
            "/api/v1/auth/password",
            json={"current_password": "wrong-password", "new_password": "replacement"},
            headers=_headers(csrf),
        )
        assert response.status_code == 401
        assert response.json()["code"] == "password_incorrect"
    with TestClient(app) as signed_out:
        assert (
            signed_out.post(
                "/api/v1/auth/login",
                json={"username": "new-student", "password": "correct-horse-1"},
            ).status_code
            == 200
        )


def test_published_agent_exposes_confirming_author_avatar(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as teacher:
        with database.session() as session:
            membership = session.scalar(select(GroupMember).order_by(GroupMember.user_id))
            assert membership is not None
            author = session.get(User, membership.user_id)
            assert author is not None
            author.avatar = AVATAR
            author_id = author.id
            now = datetime.now(UTC)
            agent_id = str(uuid4())
            version_id = str(uuid4())
            session.add(
                Agent(
                    id=agent_id,
                    group_id=membership.group_id,
                    owner_user_id=author_id,
                    visibility="public",
                    name="Authored Agent",
                    description="",
                    status="active",
                    current_published_version_id=version_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                AgentVersion(
                    id=version_id,
                    agent_id=agent_id,
                    version_seq=0,
                    state="published",
                    published_visibility="public",
                    revision=1,
                    agent_md="",
                    persona_confirmation_revision=1,
                    student_confirmed_at=now,
                    persona_confirming_user_id=author_id,
                    persona_required=False,
                    avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
                    published_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
        login(teacher)
        published = teacher.get(f"/api/v1/courses/{COURSE_ID}/published-agents")
        assert published.status_code == 200, published.text
        item = next(row for row in published.json() if row["author"]["user_id"] == author_id)
        assert item["author"]["avatar"] == AVATAR
        # A list card needs no AGENT.md text or document list; the editor reads its own.
        assert all(
            row["current_version"]["agent_md"] == ""
            and row["current_version"]["enabled_documents"] == []
            and row["current_version"]["version_label"]
            for row in published.json()
        )
