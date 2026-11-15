"""Student self-registration, group attachment and the database credential source."""

from __future__ import annotations

from typing import Any

from app.core.models import CourseMember, Group, GroupMember, User
from app.modules.auth.models import UserCredential
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"


def register(
    client: TestClient,
    username: str = "newstudent",
    password: str = "correct-horse-1",
    group_name: str = "Team Aurora",
    **extra: Any,
) -> Any:
    body: dict[str, Any] = {
        "username": username,
        "password": password,
        "group_name": group_name,
        "course_id": COURSE_ID,
    }
    body.update(extra)
    return client.post("/api/v1/auth/register", json=body)


def test_registration_creates_account_group_and_session(
    client: TestClient, app_factory: Any
) -> None:
    response = register(client)
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["user"]["username"] == "newstudent"
    # The display name defaults to the username rather than staying empty.
    assert payload["user"]["display_name"] == "newstudent"
    assert len(payload["user"]["groups"]) == 1
    assert payload["user"]["courses"] == [{"course_id": COURSE_ID, "role": "student"}]
    assert len(payload["csrf_token"]) >= 32
    # The session cookie is set by the same response: no second login step.
    assert client.cookies.get("maya_session")
    assert client.get("/api/v1/auth/me").status_code == 200


def test_registered_account_can_log_in_with_its_password(client: TestClient) -> None:
    assert register(client).status_code == 201
    client.cookies.clear()
    assert client.get("/api/v1/auth/me").status_code == 401
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "newstudent", "password": "correct-horse-1"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["username"] == "newstudent"


def test_registered_account_rejects_a_wrong_password(client: TestClient) -> None:
    assert register(client).status_code == 201
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "newstudent", "password": "correct-horse-2"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "password_incorrect"


def test_fixed_demo_catalog_still_authenticates(client: TestClient) -> None:
    """The writable source must not shadow the read-only Demo catalog."""

    assert register(client).status_code == 201
    client.cookies.clear()
    payload, _csrf = login(client)
    assert payload["user"]["username"] == "maya"


def test_same_group_name_joins_one_group(client: TestClient, app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as first:
        assert register(first, username="studentone", group_name="Team Aurora").status_code == 201
    with TestClient(app) as second:
        assert register(second, username="studenttwo", group_name="Team Aurora").status_code == 201
    with database.session() as session:
        groups = session.scalars(
            select(Group).where(Group.course_id == COURSE_ID, Group.name == "Team Aurora")
        ).all()
        assert len(groups) == 1
        member_count = session.scalar(
            select(func.count(GroupMember.user_id)).where(GroupMember.group_id == groups[0].id)
        )
        assert member_count == 2


def test_group_name_matching_is_case_and_space_insensitive(
    client: TestClient, app_factory: Any
) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as first:
        assert register(first, username="studentone", group_name="Team Aurora").status_code == 201
    with TestClient(app) as second:
        # A student typing a different case or stray spacing must land in the
        # same group, not silently create a near-duplicate one.
        assert (
            register(second, username="studenttwo", group_name="  team   aurora ").status_code
            == 201
        )
    with database.session() as session:
        groups = session.scalars(
            select(Group).where(Group.course_id == COURSE_ID, Group.name.ilike("team aurora"))
        ).all()
        assert len(groups) == 1


def test_duplicate_username_is_reported_as_a_conflict(client: TestClient, app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    with TestClient(app) as first:
        assert register(first).status_code == 201
    with TestClient(app) as second:
        response = register(second)
        assert response.status_code == 409
        assert response.json()["code"] == "username_taken"


def test_catalog_username_cannot_be_claimed(client: TestClient) -> None:
    response = register(client, username="maya")
    assert response.status_code == 409
    assert response.json()["code"] == "username_taken"


def test_reserved_maya_username_cannot_be_claimed(client: TestClient) -> None:
    for candidate in ("MAYA", "maya", "MaYa"):
        response = register(client, username=candidate)
        assert response.status_code == 409, candidate
        assert response.json()["code"] == "username_taken"


def test_rejects_unacceptable_username_and_password(client: TestClient) -> None:
    assert register(client, username="ab").status_code == 422
    assert register(client, username="has space").status_code == 422
    assert register(client, username="-leading").status_code == 422
    assert register(client, username="student.01").status_code == 422
    assert register(client, username="student_01").status_code == 422
    assert register(client, username="student-01").status_code == 422
    assert register(client, username="学生01").status_code == 422
    assert register(client, password="ab1").status_code == 422


def test_student01_is_a_valid_username(client: TestClient) -> None:
    response = register(client, username="student01")
    assert response.status_code == 201, response.text
    assert response.json()["user"]["username"] == "student01"


def test_rejects_blank_group_name(client: TestClient) -> None:
    assert register(client, group_name="   ").status_code == 422


def test_password_is_stored_only_as_a_hash(client: TestClient, app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as isolated:
        assert register(isolated, password="correct-horse-1").status_code == 201
    with database.session() as session:
        credential = session.scalar(select(UserCredential))
        assert credential is not None
        assert "correct-horse-1" not in credential.password_hash
        assert credential.password_hash.startswith("$")


def test_registration_options_expose_names_without_identities(client: TestClient) -> None:
    response = client.get("/api/v1/auth/registration-options")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["course_id"] == COURSE_ID
    names = {group["name"] for group in payload["groups"]}
    # The seeded groups are visible so a student can join an existing one.
    assert "No Group" in names
    for group in payload["groups"]:
        assert set(group) == {"name", "member_count"}
        assert group["member_count"] >= 0


def test_registration_options_count_new_members(client: TestClient) -> None:
    assert register(client, group_name="Team Aurora").status_code == 201
    payload = client.get("/api/v1/auth/registration-options").json()
    aurora = next(group for group in payload["groups"] if group["name"] == "Team Aurora")
    assert aurora["member_count"] == 1


def test_registered_student_sees_only_its_own_group(client: TestClient) -> None:
    assert register(client, group_name="Team Aurora").status_code == 201
    groups = client.get(f"/api/v1/courses/{COURSE_ID}/groups").json()
    assert [group["name"] for group in groups] == ["Team Aurora"]


def test_display_name_is_used_when_supplied(client: TestClient, app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as isolated:
        response = register(isolated, display_name="  Kai  Kai  ")
        assert response.status_code == 201
        assert response.json()["user"]["display_name"] == "Kai Kai"
    with database.session() as session:
        user = session.scalar(select(User).where(User.username == "newstudent"))
        assert user is not None
        assert user.display_name == "Kai Kai"
        membership = session.scalar(select(CourseMember).where(CourseMember.user_id == user.id))
        assert membership is not None
        assert membership.role == "student"


def test_sign_in_says_which_half_was_wrong(client: TestClient) -> None:
    """A student who mistyped their name should not hunt for their password."""

    missing = client.post(
        "/api/v1/auth/login",
        json={"username": "nobodyhere", "password": "correct-horse-1"},
    )
    assert missing.status_code == 401
    assert missing.json()["code"] == "account_not_found"

    wrong = client.post(
        "/api/v1/auth/login",
        json={"username": "maya", "password": "not-the-password"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["code"] == "password_incorrect"


def test_a_deactivated_account_says_so(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    with TestClient(app) as student:
        assert register(student).status_code == 201
    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        roster = teacher.get(f"/api/v1/courses/{COURSE_ID}/roster").json()
        target = next(item for item in roster["entries"] if item["username"] == "newstudent")
        assert (
            teacher.patch(
                f"/api/v1/courses/{COURSE_ID}/members/{target['user_id']}",
                json={"status": "inactive"},
                headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
            ).status_code
            == 200
        )
    with TestClient(app) as blocked:
        response = blocked.post(
            "/api/v1/auth/login",
            json={"username": "newstudent", "password": "correct-horse-1"},
        )
        assert response.status_code == 401
        assert response.json()["code"] == "account_inactive"


def test_a_removed_account_leaves_its_group_for_everyone_else(app_factory: Any) -> None:
    # Owner decision (2026-10-12): Remove reads as delete. The account's work
    # is kept for Restore, but classmates no longer see it in their group.
    app, _database, _settings = app_factory()
    with TestClient(app) as student:
        assert register(student).status_code == 201
    with TestClient(app) as classmate:
        joined = register(classmate, username="classmate")
        assert joined.status_code == 201, joined.text
        group_id = joined.json()["user"]["groups"][0]["group_id"]

        def names() -> set[str]:
            group = classmate.get(f"/api/v1/groups/{group_id}")
            assert group.status_code == 200, group.text
            return {member["display_name"] for member in group.json()["members"]}

        assert "newstudent" in names()
        with TestClient(app) as teacher:
            _payload, csrf = login(teacher)
            roster = teacher.get(f"/api/v1/courses/{COURSE_ID}/roster").json()
            target = next(item for item in roster["entries"] if item["username"] == "newstudent")
            removed = teacher.patch(
                f"/api/v1/courses/{COURSE_ID}/members/{target['user_id']}",
                json={"status": "inactive"},
                headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
            )
            assert removed.status_code == 200, removed.text
            course = teacher.get(f"/api/v1/courses/{COURSE_ID}").json()
            assert target["user_id"] not in {m["user_id"] for m in course["members"]}
        assert "newstudent" not in names()
        assert "classmate" in names()
