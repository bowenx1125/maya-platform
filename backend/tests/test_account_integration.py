"""Canonical identity races and teacher access across catalog synchronization."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import Database
from app.core.models import Group, GroupMember, TeacherGroupAccess, User
from app.modules.auth.models import UserCredential
from app.modules.auth.service import sync_demo_accounts
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import login
from tests.test_auth_self_registration import COURSE_ID, register
from tests.test_pw3_auth import _app


def test_concurrent_username_claim_has_one_winner_and_preserves_login(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    barrier = Barrier(2)
    with TestClient(app) as existing:
        original, _csrf = login(existing)

        def claim(name: str) -> int:
            # The outer client owns the application's one runtime lifespan;
            # concurrent requests must not rebind its background event loops.
            client = TestClient(app, raise_server_exceptions=False)
            barrier.wait(timeout=10)
            return register(client, username=name, password="abcde").status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(claim, ["ReviewRace", "reviewrace"]))
        assert sorted(statuses) == [201, 409]
        # A rejected registration must not rotate or revoke the caller's current cookie.
        assert register(existing, username="REVIEWRACE").status_code == 409
        assert existing.get("/api/v1/auth/me").json()["user"]["id"] == original["user"]["id"]
        with TestClient(app) as student:
            response = student.post(
                "/api/v1/auth/login", json={"username": "REVIEWRACE", "password": "abcde"}
            )
            assert response.status_code == 200
    with database.session() as session:
        assert (
            session.scalar(select(func.count(User.id)).where(User.username_key == "reviewrace"))
            == 1
        )
        assert session.scalar(select(func.count(UserCredential.user_id))) == 1
        session.add(
            User(
                id=str(uuid4()),
                username="reviewRACE",
                display_name="Duplicate",
                status="active",
                created_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_registration_and_move_share_unicode_group_identity(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        first = register(client, username="unicode-one", group_name="  Équipe   Straße ").json()
        second = register(client, username="unicode-two", group_name="ÉQUIPE STRASSE").json()
        third = register(client, username="unicode-three", group_name="Elsewhere").json()
        assert first["user"]["groups"] == second["user"]["groups"]
        _, csrf = login(client)
        response = client.patch(
            f"/api/v1/courses/{COURSE_ID}/members/{third['user']['id']}",
            json={"group_name": "Ｅ́quipe Straße"},
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
        assert response.json()["groups"][0]["id"] == first["user"]["groups"][0]["group_id"]
    with database.session() as session:
        assert (
            session.scalar(select(func.count(Group.id)).where(Group.name_key == "équipe strasse"))
            == 1
        )


def test_concurrent_first_group_joins_use_one_group(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    barrier = Barrier(2)
    with TestClient(app):

        def claim(name: str) -> dict[str, Any]:
            client = TestClient(app)
            barrier.wait(timeout=10)
            response = register(client, username=name, group_name="Équipe")
            assert response.status_code == 201
            return response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.map(claim, ["group-race-one", "group-race-two"])
        assert first["user"]["groups"] == second["user"]["groups"]
    with database.session() as session:
        assert session.scalar(select(func.count(Group.id)).where(Group.name_key == "équipe")) == 1


def test_teacher_access_survives_catalog_sync_and_allows_delete(tmp_path: Path) -> None:
    app, database, settings, _accounts = _app(tmp_path)
    with TestClient(app) as teacher:
        payload, csrf = login(teacher)
        teacher_id = payload["user"]["id"]
        group_id = teacher.get(f"/api/v1/courses/{COURSE_ID}/groups").json()[0]["id"]
        headers = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
        membership = f"/api/v1/groups/{group_id}/membership"
        assert teacher.post(membership, headers=headers).status_code == 200
        sync_demo_accounts(database, settings)
        response = teacher.get("/api/v1/auth/me")
        assert response.status_code == 200
        assert any(row["group_id"] == group_id for row in response.json()["user"]["groups"])
        with database.session() as session:
            assert session.get(TeacherGroupAccess, (group_id, teacher_id)) is not None
            assert session.get(GroupMember, (group_id, teacher_id)) is None
        agent = teacher.post(
            f"/api/v1/groups/{group_id}/agents",
            json={"name": "Teacher draft"},
            headers={**headers, "Idempotency-Key": "teacher-full-access-create"},
        )
        assert agent.status_code == 201
        agent_id = agent.json()["id"]
        removed = teacher.delete(
            f"/api/v1/agents/{agent_id}",
            headers={**headers, "Idempotency-Key": "teacher-full-access-delete"},
        )
        assert removed.status_code in {200, 204}
        assert teacher.delete(membership, headers=headers).status_code == 204
        assert teacher.get(f"/api/v1/groups/{group_id}/knowledge-documents").status_code == 404


def test_populated_migration_preserves_credentials_and_moves_teacher_access(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'upgrade.sqlite3'}")
    config = Config("alembic.ini")
    config.set_main_option("script_location", "migrations")
    config.attributes["database_url"] = database.database_url
    command.upgrade(config, "0028_student_self_registration")
    user_id, course_id, group_id = (str(uuid4()) for _ in range(3))
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, display_name, status, created_at) "
                "VALUES (:id, 'ReviewTeacher', 'Teacher', 'active', CURRENT_TIMESTAMP)"
            ),
            {"id": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO courses (id, code, name, created_at) "
                "VALUES (:id, 'review-course', 'Review', CURRENT_TIMESTAMP)"
            ),
            {"id": course_id},
        )
        connection.execute(
            text(
                "INSERT INTO groups (id, course_id, name, created_at) "
                "VALUES (:id, :course, 'Équipe', CURRENT_TIMESTAMP)"
            ),
            {"id": group_id, "course": course_id},
        )
        connection.execute(
            text(
                "INSERT INTO course_members (course_id, user_id, role, created_at) "
                "VALUES (:course, :user, 'teacher', CURRENT_TIMESTAMP)"
            ),
            {"course": course_id, "user": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO group_members (group_id, user_id, role, created_at) "
                "VALUES (:group, :user, 'member', CURRENT_TIMESTAMP)"
            ),
            {"group": group_id, "user": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO user_credentials "
                "(user_id, username, password_hash, created_at, updated_at) "
                "VALUES (:user, 'ReviewTeacher', 'synthetic-hash', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"user": user_id},
        )
    database.upgrade_schema()
    with database.session() as session:
        assert session.get(User, user_id).username_key == "reviewteacher"
        assert session.get(Group, group_id).name_key == "équipe"
        assert session.get(UserCredential, user_id).password_hash == "synthetic-hash"
        assert session.get(TeacherGroupAccess, (group_id, user_id)) is not None
        assert session.get(GroupMember, (group_id, user_id)) is None
        assert not session.execute(text("PRAGMA foreign_key_check")).all()
