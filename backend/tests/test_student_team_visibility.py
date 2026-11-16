"""Student/teacher Team visibility across groups.

Rules covered:
- Teacher-owned Public Teams (personal or group) are usable by every group.
- Students cannot see or use other groups' student Teams.
- A student always sees their own Teams, including personal ones.
- Teachers see every group's Public Teams.
- ``is_teacher_owned`` is true for any course teacher owner (≥2 teachers).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.core.db import Database
from app.core.models import CourseMember, Group, GroupMember, User
from app.modules.auth.dependencies import require_auth, require_authenticated_mutation
from fastapi.testclient import TestClient

from tests.conftest import login, post_message
from tests.test_mayaform_team_conversations import _create, _make_agent_version
from tests.test_mayaform_teams import BOWEN_ID, COURSE_ID, MAYA_ID, _headers, _team_payload
from tests.test_wave3_agent_metadata import _context

KAIKAI_ID = "bc170f51-45fb-5296-a36d-a2edc8f8d315"


def _add_teacher(database: Database) -> str:
    user_id = str(uuid4())
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            User(
                id=user_id,
                username=f"teacher-{user_id[:8]}",
                display_name=f"Teacher {user_id[:8]}",
                status="active",
                created_at=now,
            )
        )
        db.flush()
        db.add(CourseMember(course_id=COURSE_ID, user_id=user_id, role="teacher", created_at=now))
        db.commit()
    return user_id


def _clear_auth_overrides(client: TestClient) -> None:
    client.app.dependency_overrides.pop(require_auth, None)
    client.app.dependency_overrides.pop(require_authenticated_mutation, None)


def _login_id(client: TestClient, user_id: str) -> str:
    database = client.app.state.database
    with database.session() as db:
        username = db.get(User, user_id).username  # type: ignore[union-attr]
    _clear_auth_overrides(client)
    client.cookies.clear()
    if username in {"bowen", "kaikai", "maya", "jade"}:
        return login(client, username)[1]
    context = _context(database, user_id)
    client.app.dependency_overrides[require_auth] = lambda: context
    client.app.dependency_overrides[require_authenticated_mutation] = lambda: context
    return "x" * 40


def _group_with(database: Database, *user_ids: str) -> str:
    group_id = str(uuid4())
    with database.session() as db:
        db.add(
            Group(
                id=group_id,
                course_id=COURSE_ID,
                name=f"Circle {group_id[:8]}",
                created_at=datetime.now(UTC),
            )
        )
        for user_id in user_ids:
            db.add(
                GroupMember(
                    group_id=group_id,
                    user_id=user_id,
                    role="member",
                    created_at=datetime.now(UTC),
                )
            )
        db.commit()
    return group_id


def _public_team(
    client: TestClient,
    database: Database,
    *,
    owner_login: str | None,
    owner_id: str,
    group_id: str | None,
    name: str,
) -> dict:
    if owner_login:
        _clear_auth_overrides(client)
        _, csrf = login(client, owner_login)
    else:
        csrf = _login_id(client, owner_id)
    versions = [
        _make_agent_version(
            database,
            owner_id=owner_id,
            name=f"{name} voice {index}",
            visibility="public",
            group_id=group_id,
        )[1]
        for index in range(2)
    ]
    payload = _team_payload(versions, visibility="public")
    payload["display_name"] = name
    if group_id is not None:
        payload["group_id"] = group_id
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"team-{uuid4()}"),
        json=payload,
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_student_group_list_keeps_own_and_teacher_public_hides_other_student_teams(
    client: TestClient, database: Database
) -> None:
    bowen_group = _group_with(database, BOWEN_ID)
    kaikai_group = _group_with(database, KAIKAI_ID)
    second_teacher = _add_teacher(database)

    own_group_team = _public_team(
        client,
        database,
        owner_login="bowen",
        owner_id=BOWEN_ID,
        group_id=bowen_group,
        name="Bowen group team",
    )
    own_personal = _public_team(
        client,
        database,
        owner_login="bowen",
        owner_id=BOWEN_ID,
        group_id=None,
        name="Bowen personal team",
    )
    other_student = _public_team(
        client,
        database,
        owner_login="kaikai",
        owner_id=KAIKAI_ID,
        group_id=kaikai_group,
        name="Kaikai group team",
    )
    teacher_personal = _public_team(
        client,
        database,
        owner_login="maya",
        owner_id=MAYA_ID,
        group_id=None,
        name="Maya personal public",
    )
    with database.session() as db:
        db.add(
            GroupMember(
                group_id=kaikai_group,
                user_id=MAYA_ID,
                role="member",
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
    teacher_group = _public_team(
        client,
        database,
        owner_login="maya",
        owner_id=MAYA_ID,
        group_id=kaikai_group,
        name="Maya group public",
    )
    second_teacher_team = _public_team(
        client,
        database,
        owner_login=None,
        owner_id=second_teacher,
        group_id=None,
        name="Second teacher public",
    )

    _clear_auth_overrides(client)
    _, csrf = login(client, "bowen")
    listed = client.get(
        f"/api/v1/courses/{COURSE_ID}/teams",
        params={"group_id": bowen_group},
        headers=_headers(csrf),
    )
    assert listed.status_code == 200, listed.text
    by_id = {row["id"]: row for row in listed.json()}
    assert own_group_team["id"] in by_id
    assert own_personal["id"] in by_id
    assert teacher_personal["id"] in by_id
    assert teacher_group["id"] in by_id
    assert second_teacher_team["id"] in by_id
    assert other_student["id"] not in by_id
    assert by_id[teacher_personal["id"]]["is_teacher_owned"] is True
    assert by_id[teacher_group["id"]]["is_teacher_owned"] is True
    assert by_id[second_teacher_team["id"]]["is_teacher_owned"] is True
    assert by_id[own_group_team["id"]]["is_teacher_owned"] is False
    assert by_id[own_personal["id"]]["can_edit"] is True
    assert by_id[teacher_personal["id"]]["can_edit"] is False

    detail = client.get(f"/api/v1/teams/{teacher_group['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["is_teacher_owned"] is True
    session = _create(client, csrf, {"kind": "team", "team_id": teacher_group["id"]})
    assert session["can_send"] is True
    sent = post_message(
        client,
        f"/api/v1/conversations/{session['id']}/messages",
        headers=_headers(csrf),
        json={"request_id": str(uuid4()), "expected_revision": 0, "message": "hi"},
    )
    assert sent.status_code == 200, sent.text

    assert client.get(f"/api/v1/teams/{other_student['id']}").status_code == 404
    refused = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={"entry": {"kind": "team", "team_id": other_student["id"]}},
    )
    assert refused.status_code == 404, refused.text


def test_teachers_list_every_groups_public_teams(client: TestClient, database: Database) -> None:
    bowen_group = _group_with(database, BOWEN_ID)
    kaikai_group = _group_with(database, KAIKAI_ID)
    second_teacher = _add_teacher(database)
    bowen_team = _public_team(
        client,
        database,
        owner_login="bowen",
        owner_id=BOWEN_ID,
        group_id=bowen_group,
        name="Bowen public",
    )
    kaikai_team = _public_team(
        client,
        database,
        owner_login="kaikai",
        owner_id=KAIKAI_ID,
        group_id=kaikai_group,
        name="Kaikai public",
    )
    second_team = _public_team(
        client,
        database,
        owner_login=None,
        owner_id=second_teacher,
        group_id=None,
        name="Second teacher team",
    )

    for teacher_id, login_name in ((MAYA_ID, "maya"), (second_teacher, None)):
        if login_name:
            _clear_auth_overrides(client)
            csrf = login(client, login_name)[1]
        else:
            csrf = _login_id(client, teacher_id)
        listed = client.get(f"/api/v1/courses/{COURSE_ID}/teams", headers=_headers(csrf))
        assert listed.status_code == 200, listed.text
        ids = {row["id"] for row in listed.json()}
        assert {bowen_team["id"], kaikai_team["id"], second_team["id"]} <= ids
        session = _create(client, csrf, {"kind": "team", "team_id": kaikai_team["id"]})
        assert session["can_send"] is True
