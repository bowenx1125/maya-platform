"""A student moves themselves into another existing group of their course."""

from __future__ import annotations

from typing import Any

from app.core.models import Agent, CourseMember, Group, GroupMember
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_auth_self_registration import COURSE_ID, register
from tests.test_mayaform_teams import _make_agent_version


def _headers(csrf: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf}


def _group_id(database: Any, name: str) -> str:
    with database.session() as db:
        return db.scalars(
            select(Group.id).where(Group.course_id == COURSE_ID, Group.name == name)
        ).one()


def test_a_student_moves_into_an_existing_group_and_leaves_their_work(
    app_factory: Any,
) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as other:
        joined = register(other, username="borealis-one", group_name="Team Borealis")
        assert joined.status_code == 201, joined.text
    with TestClient(app) as student:
        registration = register(student)
        assert registration.status_code == 201, registration.text
        user_id = registration.json()["user"]["id"]
        aurora = _group_id(database, "Team Aurora")
        borealis = _group_id(database, "Team Borealis")
        agent_id, _version_id = _make_agent_version(
            database, owner_id=user_id, name="Aurora voice", group_id=aurora
        )
        with database.session() as db:
            groups_before = db.scalar(select(func.count()).select_from(Group))

        # The name is matched the way registration matches it.
        moved = student.patch(
            "/api/v1/auth/me",
            json={"group_name": "  team   BOREALIS "},
            headers=_headers(registration.json()["csrf_token"]),
        )
        assert moved.status_code == 200, moved.text
        assert [row["group_id"] for row in moved.json()["user"]["groups"]] == [borealis]

        with database.session() as db:
            assert db.scalar(select(func.count()).select_from(Group)) == groups_before
            assert db.get(Agent, agent_id).group_id == aurora
        # The work stays in the group it was made in, so its owner no longer
        # reaches it from the new group.
        assert student.get(f"/api/v1/agents/{agent_id}").status_code == 404
        assert student.get(f"/api/v1/groups/{borealis}").status_code == 200
        assert student.get(f"/api/v1/groups/{aurora}").status_code == 404

    with TestClient(app) as teacher:
        login(teacher)
        entry = next(
            row
            for row in teacher.get(f"/api/v1/courses/{COURSE_ID}/roster").json()["entries"]
            if row["user_id"] == user_id
        )
        assert [group["name"] for group in entry["groups"]] == ["Team Borealis"]


def test_a_new_group_name_is_refused_and_creates_nothing(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as student:
        registration = register(student)
        assert registration.status_code == 201, registration.text
        aurora = _group_id(database, "Team Aurora")
        with database.session() as db:
            groups_before = db.scalar(select(func.count()).select_from(Group))
        for name in ("Team Nova", "   "):
            refused = student.patch(
                "/api/v1/auth/me",
                json={"group_name": name},
                headers=_headers(registration.json()["csrf_token"]),
            )
            assert refused.status_code == 422, refused.text
            assert refused.json()["code"] == "group_not_found"
        with database.session() as db:
            assert db.scalar(select(func.count()).select_from(Group)) == groups_before
        me = student.get("/api/v1/auth/me").json()
        assert [row["group_id"] for row in me["user"]["groups"]] == [aurora]


def test_catalog_accounts_keep_the_group_the_account_list_gives_them(
    client: TestClient,
) -> None:
    for username in ("bowen", "maya"):
        payload, csrf = login(client, username)
        refused = client.patch(
            "/api/v1/auth/me",
            json={"group_name": "Demo Group"},
            headers=_headers(csrf),
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "group_managed"
        me = client.get("/api/v1/auth/me").json()
        assert me["user"]["groups"] == payload["user"]["groups"]


def test_only_students_choose_their_own_group(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as account:
        registration = register(account)
        assert registration.status_code == 201, registration.text
        user_id = registration.json()["user"]["id"]
        with database.session() as db:
            membership = db.get(CourseMember, (COURSE_ID, user_id))
            assert membership is not None
            membership.role = "teacher"
            db.commit()
        refused = account.patch(
            "/api/v1/auth/me",
            json={"group_name": "Team Aurora"},
            headers=_headers(registration.json()["csrf_token"]),
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "group_change_forbidden"
        with database.session() as db:
            assert db.scalars(
                select(GroupMember.group_id).where(GroupMember.user_id == user_id)
            ).all() == [_group_id(database, "Team Aurora")]
