"""The password-gated Bowen chooser preserves identity, history and session scope."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import Agent, Course, CourseMember, Group, GroupMember, SessionRecord, User
from app.modules.auth.dependencies import get_auth_clock
from app.modules.auth.identity_choice import consume_choice
from app.modules.auth.models import LoginIdentityChallenge
from app.modules.auth.schemas import LoginIdentityChoiceRequest
from app.modules.auth.service import create_rotated_session, session_hash, sync_demo_accounts
from app.modules.org.classes import SECOND_CLASS_GROUP_ID, SECOND_CLASS_ID
from app.seed import BOWEN_ID, COURSE_ID, GROUP_DEMO_ID, KAIKAI_ID, TEACHER_ID
from fastapi.testclient import TestClient
from sqlalchemy import func, select

LOGIN = "/api/v1/auth/login"
CHOICE = "/api/v1/auth/identity-choice"


def challenge(client: TestClient) -> dict:
    response = client.post(LOGIN, json={"username": "bowen", "password": "demo-password"})
    assert response.status_code == 202, response.text
    assert "set-cookie" not in response.headers
    result = response.json()
    assert result["expires_in_seconds"] == 300
    assert len(result["choice_token"]) >= 43
    return result


def choose(client: TestClient, token: str, identity: str = "maya", course_id: str | None = None):
    body = {"choice_token": token, "identity": identity}
    if course_id is not None:
        body["course_id"] = course_id
    return client.post(CHOICE, json=body)


def test_challenge_has_database_options_no_session_and_only_hashed_token(client, database):
    result = challenge(client)
    assert client.cookies.get("maya_session") is None
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(SessionRecord)) == 0
        row = db.get(LoginIdentityChallenge, session_hash(result["choice_token"]))
        assert row.user_id == BOWEN_ID
        assert row.consumed_at is None
        assert row.client_fingerprint_hash == session_hash("peer:testclient")
        assert row.token_hash != result["choice_token"]
        assert result["options"]["classes"] == [
            {"course_id": item.id, "code": item.code, "name": item.name}
            for item in (db.get(Course, SECOND_CLASS_ID), db.get(Course, COURSE_ID))
        ]
        assert [(item["course_id"], item["name"]) for item in result["options"]["classes"]] == [
            ("74dbe1e0-4689-5b7a-87bc-c66a6b5a14dc", "Maya1001"),
            ("b1ae79ed-e4a6-5b02-9abd-3a3ae944284b", "Maya1002"),
        ]


@pytest.mark.parametrize("username", ["maya", "kaikai", "jade"])
def test_other_catalog_logins_keep_normal_session(client, database, username):
    response = client.post(LOGIN, json={"username": username, "password": "demo-password"})
    assert response.status_code == 200
    assert set(response.json()) == {"user", "csrf_token", "expires_at"}
    assert response.json()["user"]["username"] == username
    assert "maya_session=" in response.headers["set-cookie"]
    assert client.get("/api/v1/auth/me").json() == response.json()
    with database.session() as db:
        row = db.get(SessionRecord, session_hash(client.cookies.get("maya_session")))
        assert row.entered_via_user_id is None
        assert row.active_course_id is None
        assert db.scalar(select(func.count()).select_from(LoginIdentityChallenge)) == 0


def test_registered_student_is_ordinary_and_cannot_register_catalog_username(client):
    body = {
        "username": "ordinary",
        "password": "ordinary-password",
        "group_name": "Ordinary",
        "course_id": COURSE_ID,
    }
    registered = client.post("/api/v1/auth/register", json=body)
    assert registered.status_code == 201
    response = client.post(LOGIN, json={"username": body["username"], "password": body["password"]})
    assert response.status_code == 200
    assert response.json()["user"] == registered.json()["user"]
    for name in ("maya", "bowen"):
        assert (
            client.post("/api/v1/auth/register", json={**body, "username": name}).status_code == 409
        )


def test_maya_session_writes_as_maya_and_logout_revokes_only_it(client, database, app_bundle):
    app, _, settings = app_bundle
    with database.session() as db:
        before = db.get(User, BOWEN_ID).display_name
        groups = [
            (r.group_id, r.role, r.created_at)
            for r in db.scalars(select(GroupMember).where(GroupMember.user_id == BOWEN_ID))
        ]
        old_token, old_row, old_csrf = create_rotated_session(db, db.get(User, BOWEN_ID), settings)
        direct_token, direct_row, _ = create_rotated_session(db, db.get(User, TEACHER_ID), settings)
        old_id, direct_id = old_row.id_hash, direct_row.id_hash
    client.cookies.set("maya_session", old_token, domain="testserver.local", path="/")
    student_work = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/agents",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": old_csrf,
            "Idempotency-Key": "bowen-preserved-student-work",
        },
        json={"name": "Preserved student work"},
    )
    assert student_work.status_code == 201, student_work.text
    result = challenge(client)
    assert client.cookies.get("maya_session") == old_token
    with database.session() as db:
        assert db.get(SessionRecord, old_id).revoked_at is None
    response = choose(client, result["choice_token"])
    assert response.status_code == 200, response.text
    current = client.get("/api/v1/auth/me").json()
    assert current["user"]["id"] == TEACHER_ID
    assert current["user"]["username"] == "maya"
    assert all(row["role"] == "teacher" for row in current["user"]["courses"])
    assert {row["course_id"] for row in current["user"]["courses"]} >= {COURSE_ID, SECOND_CLASS_ID}
    headers = {"Origin": "http://testserver", "X-CSRF-Token": current["csrf_token"]}
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-agents",
        headers={**headers, "Idempotency-Key": "bowen-chooser-owner-test"},
        json={"name": "Chooser owner", "visibility": "private"},
    )
    assert created.status_code == 201, created.text
    token_hash = session_hash(client.cookies.get("maya_session"))
    with database.session() as db:
        assert db.get(Agent, created.json()["id"]).owner_user_id == TEACHER_ID
        assert (
            db.scalar(
                select(Agent.id).where(
                    Agent.name == "Chooser owner", Agent.owner_user_id == BOWEN_ID
                )
            )
            is None
        )
        row = db.get(SessionRecord, token_hash)
        assert row.user_id == TEACHER_ID
        assert row.entered_via_user_id == BOWEN_ID
        assert db.get(SessionRecord, old_id).revoked_at is not None
        assert db.get(SessionRecord, direct_id).revoked_at is None
        preserved = db.get(Agent, student_work.json()["id"])
        assert preserved.owner_user_id == BOWEN_ID
        assert preserved.name == "Preserved student work"
        assert db.get(User, BOWEN_ID).display_name == before
        assert [
            (r.group_id, r.role, r.created_at)
            for r in db.scalars(select(GroupMember).where(GroupMember.user_id == BOWEN_ID))
        ] == groups
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    with database.session() as db:
        assert db.get(SessionRecord, token_hash).revoked_at is not None
        assert db.get(SessionRecord, direct_id).revoked_at is None
    with TestClient(app) as other:
        other.cookies.set("maya_session", direct_token)
        assert other.get("/api/v1/auth/me").json()["user"]["id"] == TEACHER_ID


@pytest.mark.parametrize(
    "course_id,group_id", [(SECOND_CLASS_ID, SECOND_CLASS_GROUP_ID), (COURSE_ID, GROUP_DEMO_ID)]
)
def test_student_enrollment_additive_idempotent_and_active_per_session(
    client, database, app_bundle, course_id, group_id
):
    _, _, settings = app_bundle
    with database.session() as db:
        before_courses = {
            (r.course_id, r.role, r.created_at)
            for r in db.scalars(select(CourseMember).where(CourseMember.user_id == BOWEN_ID))
        }
        before_groups = {
            (r.group_id, r.role, r.created_at)
            for r in db.scalars(select(GroupMember).where(GroupMember.user_id == BOWEN_ID))
        }
        bowen = db.get(User, BOWEN_ID)
        before_user = (bowen.username, bowen.display_name, bowen.created_at)
    first_token = None
    for _ in range(2):
        response = choose(client, challenge(client)["choice_token"], "student", course_id)
        assert response.status_code == 200, response.text
        assert response.json()["user"]["id"] == BOWEN_ID
        assert response.json()["user"]["courses"][0] == {"course_id": course_id, "role": "student"}
        assert client.get("/api/v1/auth/me").json()["user"]["courses"][0]["course_id"] == course_id
        first_token = client.cookies.get("maya_session")
    with database.session() as db:
        assert db.get(CourseMember, (course_id, BOWEN_ID)).role == "student"
        assert db.get(GroupMember, (group_id, BOWEN_ID)) is not None
        assert before_courses <= {
            (r.course_id, r.role, r.created_at)
            for r in db.scalars(select(CourseMember).where(CourseMember.user_id == BOWEN_ID))
        }
        assert before_groups <= {
            (r.group_id, r.role, r.created_at)
            for r in db.scalars(select(GroupMember).where(GroupMember.user_id == BOWEN_ID))
        }
        bowen = db.get(User, BOWEN_ID)
        assert (bowen.username, bowen.display_name, bowen.created_at) == before_user
    # Another browser chooses the other class without rotating this browser's row.
    app = app_bundle[0]
    with TestClient(app) as other:
        other_course = COURSE_ID if course_id == SECOND_CLASS_ID else SECOND_CLASS_ID
        assert (
            choose(other, challenge(other)["choice_token"], "student", other_course).status_code
            == 200
        )
        client.cookies.clear()
        client.cookies.set("maya_session", first_token)
        assert client.get("/api/v1/auth/me").json()["user"]["courses"][0]["course_id"] == course_id
    sync_demo_accounts(database, settings)
    assert client.get("/api/v1/auth/me").status_code == 200
    with database.session() as db:
        assert db.get(CourseMember, (COURSE_ID, BOWEN_ID)) is not None
        assert db.get(CourseMember, (SECOND_CLASS_ID, BOWEN_ID)) is not None


@pytest.mark.parametrize(
    "course_id,group_id", [(SECOND_CLASS_ID, SECOND_CLASS_GROUP_ID), (COURSE_ID, GROUP_DEMO_ID)]
)
@pytest.mark.parametrize("moved", [False, True])
def test_student_login_preserves_revoked_or_changed_group_grants(
    client, database, course_id, group_id, moved
):
    enrolled = choose(client, challenge(client)["choice_token"], "student", course_id)
    assert enrolled.status_code == 200, enrolled.text
    with database.session() as db:
        db.delete(db.get(GroupMember, (group_id, BOWEN_ID)))
        if moved:
            group = Group(
                id=str(uuid4()),
                course_id=course_id,
                name="Chosen group",
                created_at=datetime.now(UTC),
            )
            db.add(group)
            db.flush()
            db.add(
                GroupMember(
                    group_id=group.id, user_id=BOWEN_ID, role="leader", created_at=datetime.now(UTC)
                )
            )
        db.flush()
        before_groups = {
            (r.group_id, r.role, r.created_at)
            for r in db.scalars(select(GroupMember).where(GroupMember.user_id == BOWEN_ID))
        }
        before_enrollment = db.get(CourseMember, (course_id, BOWEN_ID)).created_at
    for _ in range(2):
        response = choose(client, challenge(client)["choice_token"], "student", course_id)
        assert response.status_code == 200, response.text
        assert response.json()["user"]["id"] == BOWEN_ID
        with database.session() as db:
            assert db.get(GroupMember, (group_id, BOWEN_ID)) is None
            assert {
                (r.group_id, r.role, r.created_at)
                for r in db.scalars(select(GroupMember).where(GroupMember.user_id == BOWEN_ID))
            } == before_groups
            membership = db.get(CourseMember, (course_id, BOWEN_ID))
            assert membership.role == "student"
            assert membership.created_at == before_enrollment
            row = db.get(SessionRecord, session_hash(client.cookies.get("maya_session")))
            assert row.user_id == BOWEN_ID
            assert row.active_course_id == course_id
            assert row.entered_via_user_id == BOWEN_ID


@pytest.mark.parametrize("kind", ["garbage", "expired", "other-user", "fingerprint", "consumed"])
def test_invalid_tokens_fail_closed_without_session(client, database, kind):
    token = challenge(client)["choice_token"]
    with database.session() as db:
        row = db.get(LoginIdentityChallenge, session_hash(token))
        if kind == "expired":
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif kind == "other-user":
            row.user_id = KAIKAI_ID
        elif kind == "fingerprint":
            row.client_fingerprint_hash = session_hash("another-client")
        elif kind == "consumed":
            row.consumed_at = datetime.now(UTC)
    response = choose(client, "garbage" if kind == "garbage" else token)
    assert response.status_code == 401
    assert response.json()["code"] == "identity_choice_invalid"
    assert "set-cookie" not in response.headers
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(SessionRecord)) == 0


def test_replay_and_bad_course_choices(client):
    token = challenge(client)["choice_token"]
    for identity, course_id in [("student", None), ("student", str(uuid4())), ("maya", COURSE_ID)]:
        response = choose(client, token, identity, course_id)
        assert response.status_code == 422
        assert response.json()["code"] == "identity_choice_course_invalid"
    assert (
        client.post(
            CHOICE, json={"choice_token": token, "identity": "maya", "course_id": None}
        ).status_code
        == 422
    )
    assert choose(client, token).status_code == 200
    cookie = client.cookies.get("maya_session")
    response = choose(client, token)
    assert response.status_code == 401
    assert response.json()["code"] == "identity_choice_invalid"
    assert client.cookies.get("maya_session") == cookie


@pytest.mark.parametrize("user_id", [BOWEN_ID, TEACHER_ID])
def test_inactive_identity_cannot_enter(client, database, user_id):
    token = challenge(client)["choice_token"]
    with database.session() as db:
        db.get(User, user_id).status = "inactive"
    assert choose(client, token).status_code == 401
    with database.session() as db:
        assert db.get(LoginIdentityChallenge, session_hash(token)).consumed_at is None


def test_two_database_instances_atomic_consume_exactly_one_winner(client, database, app_bundle):
    token = challenge(client)["choice_token"]
    other = Database(app_bundle[2].database_url)
    barrier = Barrier(2)
    payload = LoginIdentityChoiceRequest(choice_token=token, identity="maya")

    def consume(db):
        with db.session() as session:
            barrier.wait(timeout=10)
            try:
                user = consume_choice(session, payload, "peer:testclient")
                create_rotated_session(session, user, app_bundle[2])
                session.commit()
                return "success"
            except PlatformError as error:
                session.rollback()
                return error.code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(consume, [database, other]))
        assert sorted(results) == ["identity_choice_invalid", "success"]
    finally:
        other.dispose()
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(SessionRecord)) == 1


def test_choice_limiter_bad_tokens_eventually_lock_out_and_origin_is_required(client, app_bundle):
    _, _, settings = app_bundle
    settings.auth_login_account_failure_limit = 2
    assert choose(client, "bad").status_code == 401
    assert choose(client, "bad").status_code == 401
    assert choose(client, "bad").status_code == 429
    settings.maya_env = "production"
    settings.classroom_public_base_url = "https://maya.example"
    assert choose(client, "bad").status_code == 403


def test_production_password_limiter_challenge_is_success_and_wrong_password_fails(
    client, app_bundle
):
    _, _, settings = app_bundle
    settings.maya_env = "production"
    settings.classroom_public_base_url = "http://testserver"
    settings.auth_login_account_failure_limit = 2
    client.headers["Origin"] = "http://testserver"
    for _ in range(3):
        challenge(client)
    for _ in range(2):
        assert (
            client.post(LOGIN, json={"username": "bowen", "password": "wrong"}).status_code == 401
        )
    assert (
        client.post(LOGIN, json={"username": "bowen", "password": "demo-password"}).status_code
        == 429
    )


def test_expiry_cutoff_and_cleanup(client, database, app_bundle):
    app = app_bundle[0]
    now = datetime.now(UTC)
    app.dependency_overrides[get_auth_clock] = lambda: now
    token = challenge(client)["choice_token"]
    app.dependency_overrides[get_auth_clock] = lambda: now + timedelta(seconds=300)
    assert choose(client, token).status_code == 401
    app.dependency_overrides[get_auth_clock] = lambda: now + timedelta(days=2)
    challenge(client)
    with database.session() as db:
        assert db.get(LoginIdentityChallenge, session_hash(token)) is None


def test_demo_quick_login_remains_plain_bowen_and_direct_maya(client, database, app_bundle):
    app_bundle[2].demo_quick_login = True
    for user_id in (BOWEN_ID, TEACHER_ID):
        response = client.post("/api/v1/auth/quick-login", json={"user_id": user_id})
        assert response.status_code == 200
        assert response.json()["user"]["id"] == user_id
        with database.session() as db:
            row = db.get(SessionRecord, session_hash(client.cookies.get("maya_session")))
            assert row.entered_via_user_id is None
            assert db.scalar(select(func.count()).select_from(LoginIdentityChallenge)) == 0


def test_fingerprint_uses_the_same_trusted_client_key_as_login(client, app_bundle):
    settings = app_bundle[2]
    settings.auth_trust_gateway_x_forwarded_for = True
    client.headers["X-Forwarded-For"] = "192.0.2.1"
    token = challenge(client)["choice_token"]
    client.headers["X-Forwarded-For"] = "192.0.2.2"
    assert choose(client, token).status_code == 401
    client.headers["X-Forwarded-For"] = "192.0.2.1"
    assert choose(client, token).status_code == 200
