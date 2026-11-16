from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.models import Agent, Course, CourseMember, Group, User
from app.main import _bootstrap_accounts, create_app
from app.modules.auth.models import UserCredential
from app.modules.org.classes import SECOND_CLASS_ID
from app.modules.workspace.models import Conversation
from app.seed import COURSE_ID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import complete_student_login
from tests.test_mayaform_team_conversations import _create, _make_agent_version


@pytest.fixture
def class_app(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]], tmp_path: Path
) -> Iterator[tuple[TestClient, Database, Settings]]:
    _, database, base = app_factory()
    catalog = tmp_path / "class-accounts.private.md"
    rows = [
        ("maya", "Maya", "teacher", ""),
        ("maya1001", "Maya1001", "teacher", ""),
        ("maya1002", "Maya1002", "teacher", ""),
        ("bowen", "bowen", "student", "group-demo"),
        ("kaikai", "kaikai", "student", "group-demo"),
        ("jade", "jade", "student", "group-demo"),
    ]
    catalog.write_text(
        "| account_key | username | display_name | password | role | group |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        + "".join(
            f"| {key} | {name} | {name} | test-class-password | {role} | {group} |\n"
            for key, name, role, group in rows
        )
    )
    catalog.chmod(0o600)
    settings = base.model_copy(update={"demo_accounts_file": catalog})
    with TestClient(create_app(settings, database)) as client:
        yield client, database, settings


def sign_in(client: TestClient, username: str) -> tuple[dict[str, Any], dict[str, str]]:
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "test-class-password"}
    )
    response = complete_student_login(client, response)
    assert response.status_code == 200, response.text
    body = response.json()
    return body, {"Origin": "http://testserver", "X-CSRF-Token": body["csrf_token"]}


def test_teachers_are_scoped_and_existing_students_stay_in_first_class(class_app: Any) -> None:
    client, database, _ = class_app
    for teacher, expected in [
        ("Maya", {COURSE_ID, SECOND_CLASS_ID}),
        ("Maya1002", {COURSE_ID}),
        ("Maya1001", {SECOND_CLASS_ID}),
    ]:
        session, _ = sign_in(client, teacher)
        assert {item["course_id"] for item in session["user"]["courses"]} == expected
        courses = client.get("/api/v1/courses").json()
        assert {item["id"] for item in courses} == expected
        for course in {COURSE_ID, SECOND_CLASS_ID}:
            roster = client.get(f"/api/v1/courses/{course}/roster")
            assert roster.status_code == (200 if course in expected else 404)
    for student in ["bowen", "kaikai", "jade"]:
        session, _ = sign_in(client, student)
        assert [item["course_id"] for item in session["user"]["courses"]] == [COURSE_ID]
    with database.session() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(CourseMember)
                .where(CourseMember.course_id == SECOND_CLASS_ID, CourseMember.role == "student")
            )
            == 0
        )


def test_existing_reversed_labels_are_corrected_without_moving_students_or_work(
    class_app: Any,
) -> None:
    client, database, settings = class_app
    maya1001, _ = sign_in(client, "Maya1001")
    maya1002, _ = sign_in(client, "Maya1002")
    student, _ = sign_in(client, "bowen")
    user_id = student["user"]["id"]
    group_id = student["user"]["groups"][0]["group_id"]
    agent_id, _ = _make_agent_version(
        database, owner_id=user_id, name="Existing work", group_id=group_id, visibility="public"
    )
    now = datetime.now(UTC)
    with database.session() as db:
        db.get(Course, COURSE_ID).name = "Maya1001"
        db.get(Course, SECOND_CLASS_ID).name = "Maya1002"
        for teacher, correct, old in [
            (maya1001, SECOND_CLASS_ID, COURSE_ID),
            (maya1002, COURSE_ID, SECOND_CLASS_ID),
        ]:
            teacher_id = teacher["user"]["id"]
            db.delete(db.get(CourseMember, (correct, teacher_id)))
            db.add(CourseMember(course_id=old, user_id=teacher_id, role="teacher", created_at=now))
        db.commit()
    _bootstrap_accounts(database, settings)
    _bootstrap_accounts(database, settings)
    corrected, _ = sign_in(client, "Maya1002")
    assert corrected["user"]["courses"] == [{"course_id": COURSE_ID, "role": "teacher"}]
    assert "bowen" in client.get(f"/api/v1/courses/{COURSE_ID}/roster").text
    assert client.get(f"/api/v1/courses/{SECOND_CLASS_ID}/roster").status_code == 404
    corrected, _ = sign_in(client, "Maya1001")
    assert corrected["user"]["courses"] == [{"course_id": SECOND_CLASS_ID, "role": "teacher"}]
    assert client.get(f"/api/v1/courses/{COURSE_ID}/roster").status_code == 404
    with database.session() as db:
        assert db.get(Course, COURSE_ID).name == "Maya1002"
        assert db.get(Course, SECOND_CLASS_ID).name == "Maya1001"
        assert db.get(CourseMember, (COURSE_ID, user_id)).role == "student"
        assert db.get(Group, group_id).course_id == COURSE_ID
        assert db.get(Agent, agent_id).course_id == COURSE_ID


def test_registration_chooses_class_and_rejects_invalid_groups(class_app: Any) -> None:
    client, database, _ = class_app
    options = client.get("/api/v1/auth/registration-options").json()
    assert [(item["course_id"], item["course_name"]) for item in options["classes"]] == [
        (COURSE_ID, "Maya1002"),
        (SECOND_CLASS_ID, "Maya1001"),
    ]
    chosen = next(item for item in options["classes"] if item["course_id"] == SECOND_CLASS_ID)
    body = {
        "username": "newclasstwo",
        "password": "student-password",
        "course_id": SECOND_CLASS_ID,
        "group_name": chosen["group_name"],
    }
    with database.session() as db:
        before = db.scalar(select(func.count()).select_from(Group))
    invalid = client.post("/api/v1/auth/register", json={**body, "group_name": "   "})
    assert invalid.status_code == 422, invalid.text
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(Group)) == before
        assert db.scalar(select(User).where(User.username == body["username"])) is None
    missing = client.post(
        "/api/v1/auth/register",
        json={key: value for key, value in body.items() if key != "course_id"},
    )
    assert missing.status_code == 422
    response = client.post("/api/v1/auth/register", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["user"]["courses"] == [{"course_id": SECOND_CLASS_ID, "role": "student"}]
    assert client.get(f"/api/v1/courses/{COURSE_ID}").status_code == 404
    _, _ = sign_in(client, "Maya1002")
    assert "newclasstwo" not in client.get(f"/api/v1/courses/{COURSE_ID}/roster").text
    sign_in(client, "Maya1001")
    assert "newclasstwo" in client.get(f"/api/v1/courses/{SECOND_CLASS_ID}/roster").text


def test_profile_switch_is_immediate_and_survives_catalog_restart(class_app: Any) -> None:
    client, database, settings = class_app
    session, headers = sign_in(client, "kaikai")
    user_id = session["user"]["id"]
    old_group = session["user"]["groups"][0]["group_id"]
    moved = client.patch("/api/v1/auth/me", headers=headers, json={"course_id": SECOND_CLASS_ID})
    assert moved.status_code == 200, moved.text
    assert moved.json()["user"]["courses"] == [{"course_id": SECOND_CLASS_ID, "role": "student"}]
    assert client.get(f"/api/v1/groups/{old_group}").status_code == 404
    assert client.get(f"/api/v1/courses/{COURSE_ID}").status_code == 404
    assert client.get(f"/api/v1/courses/{SECOND_CLASS_ID}").status_code == 200
    _bootstrap_accounts(database, settings)
    current = client.get("/api/v1/auth/me")
    assert current.status_code == 200, current.text
    assert current.json()["user"]["courses"] == [{"course_id": SECOND_CLASS_ID, "role": "student"}]
    with database.session() as db:
        assert db.get(User, user_id) is not None
        assert db.get(Group, old_group) is not None
        assert db.get(UserCredential, user_id) is None


def test_class_teacher_cannot_move_themselves(class_app: Any) -> None:
    client, _, _ = class_app
    _, headers = sign_in(client, "Maya1002")
    response = client.patch("/api/v1/auth/me", headers=headers, json={"course_id": SECOND_CLASS_ID})
    assert response.status_code == 409, response.text
    assert client.get("/api/v1/auth/me").json()["user"]["courses"] == [
        {"course_id": COURSE_ID, "role": "teacher"}
    ]


def test_registration_creates_or_joins_group_only_in_chosen_class(class_app: Any) -> None:
    client, database, _ = class_app
    with database.session() as db:
        original = db.scalar(
            select(Group).where(Group.course_id == COURSE_ID, Group.name == "No Group")
        )
        original_id = original.id
        group_count = db.scalar(select(func.count()).select_from(Group))
    body = {
        "username": "classtwogroupone",
        "password": "student-password",
        "course_id": SECOND_CLASS_ID,
        "group_name": "Demo Group",
    }
    first = client.post("/api/v1/auth/register", json=body)
    assert first.status_code == 201, first.text
    group_id = first.json()["user"]["groups"][0]["group_id"]
    assert group_id != original_id
    second = client.post(
        "/api/v1/auth/register",
        json={**body, "username": "classtwogrouptwo", "group_name": "  demo   GROUP "},
    )
    assert second.status_code == 201, second.text
    assert second.json()["user"]["groups"][0]["group_id"] == group_id
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(Group)) == group_count + 1
        assert db.get(Group, group_id).course_id == SECOND_CLASS_ID
    options = client.get("/api/v1/auth/registration-options").json()
    choices = {item["course_id"]: item["groups"] for item in options["classes"]}
    assert {item["name"]: item["member_count"] for item in choices[SECOND_CLASS_ID]} == {
        "No Group": 0,
        "Demo Group": 2,
    }
    assert {item["name"]: item["member_count"] for item in choices[COURSE_ID]}["No Group"] == 3


def test_teacher_creates_named_class_visible_at_registration_and_restart(class_app: Any) -> None:
    client, database, settings = class_app
    _, headers = sign_in(client, "Maya1002")
    created = client.post("/api/v1/courses", headers=headers, json={"name": "  History   2026 "})
    assert created.status_code == 201, created.text
    course = created.json()
    course_id = course["id"]
    assert course["name"] == "History 2026"
    assert course["student_count"] == 0
    assert client.get(f"/api/v1/courses/{course_id}/roster").status_code == 200
    duplicate = client.post("/api/v1/courses", headers=headers, json={"name": "history 2026"})
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "class_name_taken"
    invalid = client.post("/api/v1/courses", headers=headers, json={"name": "  "})
    assert invalid.status_code == 422
    options = client.get("/api/v1/auth/registration-options").json()
    choice = next(item for item in options["classes"] if item["course_id"] == course_id)
    assert choice["course_name"] == "History 2026"
    assert choice["groups"] == [{"name": "No Group", "member_count": 0}]
    joined = client.post(
        "/api/v1/auth/register",
        json={
            "username": "historystudent",
            "password": "student-password",
            "course_id": course_id,
            "group_name": "History team",
        },
    )
    assert joined.status_code == 201, joined.text
    assert joined.json()["user"]["courses"] == [{"course_id": course_id, "role": "student"}]
    _, student_headers = sign_in(client, "kaikai")
    moved = client.patch("/api/v1/auth/me", headers=student_headers, json={"course_id": course_id})
    assert moved.status_code == 200, moved.text
    with database.session() as db:
        assert db.get(Group, moved.json()["user"]["groups"][0]["group_id"]).name == "No Group"
    _bootstrap_accounts(database, settings)
    for teacher, expected in [
        ("Maya1002", {COURSE_ID, course_id}),
        ("Maya1001", {SECOND_CLASS_ID}),
        ("Maya", {COURSE_ID, SECOND_CLASS_ID, course_id}),
    ]:
        current, _ = sign_in(client, teacher)
        assert {item["course_id"] for item in current["user"]["courses"]} == expected
        assert client.get(f"/api/v1/courses/{course_id}/roster").status_code == (
            200 if course_id in expected else 404
        )
    sign_in(client, "Maya1002")
    assert "historystudent" in client.get(f"/api/v1/courses/{course_id}/roster").text


def test_class_creation_rejects_students_and_missing_csrf(class_app: Any) -> None:
    client, database, _ = class_app
    _, headers = sign_in(client, "bowen")
    denied = client.post("/api/v1/courses", headers=headers, json={"name": "Unauthorized"})
    assert denied.status_code == 403
    sign_in(client, "Maya")
    csrf = client.post("/api/v1/courses", json={"name": "Missing CSRF"})
    assert csrf.status_code == 403
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(Course)) == 2


def test_unrelated_course_is_not_a_class_or_catalog_teacher_scope(class_app: Any) -> None:
    client, database, settings = class_app
    foreign_id = str(uuid4())
    with database.session() as db:
        db.add(
            Course(
                id=foreign_id, code="unrelated", name="Other course", created_at=datetime.now(UTC)
            )
        )
        db.flush()
        db.add(
            Group(
                id=str(uuid4()),
                course_id=foreign_id,
                name="Other group",
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
    _bootstrap_accounts(database, settings)
    options = client.get("/api/v1/auth/registration-options").json()
    assert {row["course_id"] for row in options["classes"]} == {COURSE_ID, SECOND_CLASS_ID}
    root, _ = sign_in(client, "Maya")
    assert {row["course_id"] for row in root["user"]["courses"]} == {COURSE_ID, SECOND_CLASS_ID}
    assert client.get(f"/api/v1/courses/{foreign_id}/roster").status_code == 404
    _, headers = sign_in(client, "bowen")
    assert (
        client.patch("/api/v1/auth/me", headers=headers, json={"course_id": foreign_id}).status_code
        == 422
    )
    refused = client.post(
        "/api/v1/auth/register",
        json={
            "username": "foreignjoin",
            "password": "test-password",
            "course_id": foreign_id,
            "group_name": "Other group",
        },
    )
    assert refused.status_code == 422
    with database.session() as db:
        assert db.scalar(select(User).where(User.username == "foreignjoin")) is None


def test_registered_students_work_and_password_survive_class_change(class_app: Any) -> None:
    client, database, settings = class_app
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "classmovestudent",
            "password": "student-password",
            "course_id": COURSE_ID,
            "group_name": "Demo Group",
        },
    )
    assert response.status_code == 201, response.text
    session = response.json()
    user_id = session["user"]["id"]
    group_id = session["user"]["groups"][0]["group_id"]
    agent_id, version_id = _make_agent_version(
        database, owner_id=user_id, name="Original class work", group_id=group_id
    )
    assert client.get(f"/api/v1/agents/{agent_id}").status_code == 200
    chat = _create(client, session["csrf_token"], {"kind": "agent", "version_id": version_id})
    assert [row["id"] for row in client.get("/api/v1/conversations").json()] == [chat["id"]]
    with database.session() as db:
        password_hash = db.get(UserCredential, user_id).password_hash
    moved = client.patch(
        "/api/v1/auth/me",
        headers={"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]},
        json={"course_id": SECOND_CLASS_ID},
    )
    assert moved.status_code == 200, moved.text
    assert client.get(f"/api/v1/agents/{agent_id}").status_code == 404
    assert client.get(f"/api/v1/conversations/{chat['id']}").status_code == 404
    assert client.get("/api/v1/conversations").json() == []
    _bootstrap_accounts(database, settings)
    with database.session() as db:
        assert db.get(Agent, agent_id).group_id == group_id
        assert db.get(Conversation, chat["id"]).course_id == COURSE_ID
        assert db.get(UserCredential, user_id).password_hash == password_hash
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "classmovestudent", "password": "student-password"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["user"]["courses"] == [{"course_id": SECOND_CLASS_ID, "role": "student"}]


@pytest.mark.parametrize(
    "suffix",
    [
        "roster",
        "groups",
        "teams",
        "maya-teams",
        "workspace-agents",
        "workspace-documents",
        "knowledge-sets",
        "voice-profiles",
        "debates",
        "live",
    ],
)
def test_class_resources_cannot_be_read_by_other_class_teacher(class_app: Any, suffix: str) -> None:
    client, _, _ = class_app
    path = f"/api/v1/courses/{COURSE_ID}/{suffix}"
    sign_in(client, "Maya1002")
    allowed = client.get(path)
    assert allowed.status_code == 200, allowed.text
    sign_in(client, "Maya1001")
    denied = client.get(path)
    assert denied.status_code == 404, denied.text


def test_same_teacher_public_agents_stay_in_separate_class_catalogs(class_app: Any) -> None:
    client, database, _ = class_app
    current, _ = sign_in(client, "Maya")
    owner_id = current["user"]["id"]
    first, _ = _make_agent_version(
        database,
        owner_id=owner_id,
        name="Class one public agent",
        course_id=COURSE_ID,
        visibility="public",
    )
    second, _ = _make_agent_version(
        database,
        owner_id=owner_id,
        name="Class two public agent",
        course_id=SECOND_CLASS_ID,
        visibility="public",
    )
    for course_id, own, other in [(COURSE_ID, first, second), (SECOND_CLASS_ID, second, first)]:
        response = client.get(f"/api/v1/courses/{course_id}/published-agents")
        assert response.status_code == 200, response.text
        rows = response.json()
        assert own in {item["agent"]["id"] for item in rows}
        assert other not in {item["agent"]["id"] for item in rows}
        assert all(item["agent"]["course_id"] == course_id for item in rows)


def test_class_teacher_cannot_erase_another_class_history(class_app: Any) -> None:
    client, database, _ = class_app
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "username": "historyowner",
            "password": "student-password",
            "course_id": COURSE_ID,
            "group_name": "Historical group",
        },
    )
    assert registered.status_code == 201
    session = registered.json()
    user_id = session["user"]["id"]
    agent_id, _ = _make_agent_version(
        database,
        owner_id=user_id,
        name="Original class work",
        group_id=session["user"]["groups"][0]["group_id"],
    )
    moved = client.patch(
        "/api/v1/auth/me",
        headers={"Origin": "http://testserver", "X-CSRF-Token": session["csrf_token"]},
        json={"course_id": SECOND_CLASS_ID},
    )
    assert moved.status_code == 200, moved.text
    _, headers = sign_in(client, "Maya1001")
    path = f"/api/v1/courses/{SECOND_CLASS_ID}/members/{user_id}"
    denied = client.delete(path, headers=headers)
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == "account_delete_scope_forbidden"
    with database.session() as db:
        assert db.get(User, user_id) is not None
        assert db.get(Agent, agent_id) is not None
    _, headers = sign_in(client, "Maya")
    erased = client.delete(path, headers=headers)
    assert erased.status_code == 204, erased.text
    with database.session() as db:
        assert db.get(User, user_id) is None
        assert db.get(Agent, agent_id) is None
