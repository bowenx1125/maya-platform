"""A teacher deletes a self-registered account: the person and their private
work go; shared work, grades and records stay."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.models import CourseMember, GroupMember, SessionRecord, User
from app.modules.auth.models import UserCredential
from app.modules.workspace.models import Conversation
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_auth_self_registration import register

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
TEACHER_ID = "08b9de2d-bb75-5c71-a64b-231b48f9eb25"
HEADERS = {"Origin": "http://testserver"}


def _delete(client: TestClient, csrf: str, user_id: str) -> Any:
    return client.delete(
        f"/api/v1/courses/{COURSE_ID}/members/{user_id}",
        headers={**HEADERS, "X-CSRF-Token": csrf},
    )


def test_deleting_an_account_removes_the_person_and_their_private_work(
    app_factory: Any,
) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as student:
        created = register(student, username="leaving-student", password="abcde")
        assert created.status_code == 201, created.text
        user_id = str(created.json()["user"]["id"])
        csrf = created.json()["csrf_token"]
        group_id = created.json()["user"]["groups"][0]["group_id"]
        agent = student.post(
            f"/api/v1/groups/{group_id}/agents",
            headers={**HEADERS, "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())},
            json={"name": "My private helper"},
        )
        assert agent.status_code == 201, agent.text
        agent_id = agent.json()["id"]
    with TestClient(app) as teacher:
        _, teacher_csrf = login(teacher)
        assert _delete(teacher, teacher_csrf, user_id).status_code == 204
        roster = teacher.get(f"/api/v1/courses/{COURSE_ID}/roster").json()
        assert all(entry["user_id"] != user_id for entry in roster["entries"])
        # A second delete finds nobody.
        assert _delete(teacher, teacher_csrf, user_id).status_code == 404
    with database.session() as db:
        from app.core.models import Agent

        assert db.get(Agent, agent_id) is None
        user = db.get(User, user_id)
        assert user is not None  # only an anchor for any records
        assert user.username != "leaving-student"
        assert user.display_name == "Deleted account"
        assert user.status == "inactive"
        for model, column in (
            (SessionRecord, SessionRecord.user_id),
            (UserCredential, UserCredential.user_id),
            (CourseMember, CourseMember.user_id),
            (GroupMember, GroupMember.user_id),
            (Conversation, Conversation.user_id),
        ):
            count = db.scalar(select(func.count()).select_from(model).where(column == user_id))
            assert count == 0, model.__name__
    # The account cannot sign in, and its username is free again.
    with TestClient(app) as again:
        refused = again.post(
            "/api/v1/auth/login",
            json={"username": "leaving-student", "password": "abcde"},
        )
        assert refused.status_code in {401, 403}
        reused = register(again, username="leaving-student", password="abcde")
        assert reused.status_code == 201, reused.text


def test_a_teacher_cannot_delete_themselves_or_a_catalog_account(client: TestClient) -> None:
    _, csrf = login(client)
    assert _delete(client, csrf, TEACHER_ID).status_code == 409
    roster = client.get(f"/api/v1/courses/{COURSE_ID}/roster").json()
    catalog = next(entry for entry in roster["entries"] if entry["username"] == "bowen")
    refused = _delete(client, csrf, catalog["user_id"])
    assert refused.status_code == 409
    assert refused.json()["code"] == "account_read_only"


def test_a_student_cannot_delete_accounts(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    with TestClient(app) as student:
        created = register(student, username="curious-student", password="abcde")
        csrf = created.json()["csrf_token"]
        assert _delete(student, csrf, TEACHER_ID).status_code in {403, 404}
