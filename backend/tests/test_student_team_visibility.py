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

import pytest
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import CourseMember, Group, GroupMember, KnowledgeDocument, User
from app.modules.auth.dependencies import require_auth, require_authenticated_mutation
from app.modules.auth.models import UserCredential
from app.modules.knowledge.services import can_read_source
from app.modules.knowledge_sets.models import AgentKnowledgeSet, KnowledgeSet
from app.modules.teams.models import CourseTeamPublication, TeamVersionMember
from app.modules.teams.service import resolve_chat_entry, resolve_frozen_chat_selection
from app.modules.workspace.models import TeamTurnResult
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import select

from tests.conftest import login, post_message
from tests.test_mayaform_team_conversations import _create, _make_agent_version
from tests.test_mayaform_teams import (
    BOWEN_ID,
    COURSE_ID,
    MAYA_ID,
    _attach_personal_snapshot,
    _headers,
    _team_payload,
)

KAIKAI_ID = "bc170f51-45fb-5296-a36d-a2edc8f8d315"


def _add_teacher(database: Database) -> str:
    user_id = str(uuid4())
    username = f"teacher{user_id[:8]}"
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            User(
                id=user_id,
                username=username,
                display_name=f"Teacher {user_id[:8]}",
                status="active",
                created_at=now,
            )
        )
        db.flush()
        db.add(
            UserCredential(
                user_id=user_id,
                username=username,
                password_hash=PasswordHash.recommended().hash("demo-password"),
                created_at=now,
                updated_at=now,
            )
        )
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
    return login(client, username)[1]


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


def _resource_team(
    client: TestClient, database: Database, owner_id: str, group_id: str | None
) -> tuple[dict, dict, list[str], str]:
    csrf = _login_id(client, owner_id)
    agents = [
        _make_agent_version(
            database,
            owner_id=owner_id,
            name=f"Resource member {index}",
            visibility="public",
            group_id=group_id,
        )
        for index in range(2)
    ]
    document_id = _attach_personal_snapshot(database, agents[0][1])
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        document.owner_user_id = owner_id
    set_ids = []
    for index in range(2):
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
            headers=_headers(csrf, f"teacher-resource-set-{uuid4()}"),
            json={"display_name": f"Personal notes {index}"},
        )
        assert created.status_code == 201, created.text
        set_id = created.json()["id"]
        saved = client.put(
            f"/api/v1/knowledge-sets/{set_id}/markdown",
            headers=_headers(csrf, f"teacher-resource-markdown-{uuid4()}"),
            json={"expected_version_seq": 0, "markdown": f"# Notes\n\nEvidence {index}."},
        )
        assert saved.status_code == 200, saved.text
        set_ids.append(set_id)
    with database.session() as db:
        db.add(
            AgentKnowledgeSet(
                agent_id=agents[0][0],
                knowledge_set_id=set_ids[0],
                order_index=0,
                created_by_user_id=owner_id,
                created_at=datetime.now(UTC),
            )
        )
    payload = _team_payload([version_id for _, version_id in agents], visibility="public")
    payload["shared_knowledge_set_ids"] = [set_ids[1]]
    if group_id is not None:
        payload["group_id"] = group_id
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"teacher-resource-team-{uuid4()}"),
        json=payload,
    )
    assert created.status_code == 201, created.text
    return created.json(), payload, set_ids, document_id


@pytest.mark.parametrize("in_group", [False, True], ids=["personal", "group"])
@pytest.mark.parametrize("second_publisher", [False, True], ids=["maya", "second_teacher"])
def test_teacher_public_team_resources_open_reload_send_and_stream_across_groups(
    client: TestClient, database: Database, in_group: bool, second_publisher: bool
) -> None:
    second_teacher = _add_teacher(database)
    owner_id = second_teacher if second_publisher else MAYA_ID
    other_teacher = MAYA_ID if second_publisher else second_teacher
    _group_with(database, BOWEN_ID)
    _group_with(database, KAIKAI_ID)
    group_id = _group_with(database, owner_id) if in_group else None
    team, _payload, set_ids, document_id = _resource_team(client, database, owner_id, group_id)

    for viewer in (BOWEN_ID, KAIKAI_ID, other_teacher):
        csrf = _login_id(client, viewer)
        assert client.get(f"/api/v1/teams/{team['id']}").status_code == 200
        # Team use never grants direct access to the owner's personal resources.
        for set_id in set_ids:
            assert client.get(f"/api/v1/knowledge-sets/{set_id}").status_code == 404
        with database.session() as db:
            document = db.get(KnowledgeDocument, document_id)
            assert document is not None
            assert not can_read_source(db, viewer, document, require_active=True)
        session = _create(client, csrf, {"kind": "team", "team_id": team["id"]})
        assert session["entry_kind"] == "team"
        assert session["can_send"] is True
        reloaded = client.get(f"/api/v1/conversations/{session['id']}")
        assert reloaded.status_code == 200, reloaded.text
        assert reloaded.json()["can_send"] is True
        sent = post_message(
            client,
            f"/api/v1/conversations/{session['id']}/messages",
            headers=_headers(csrf),
            json={"request_id": str(uuid4()), "expected_revision": 0, "message": "Hello team"},
        )
        assert sent.status_code == 200, sent.text
        assert sent.json()["turns"][0]["state"] == "ready", sent.text
        streamed = client.post(
            f"/api/v1/conversations/{session['id']}/messages:stream",
            headers={**_headers(csrf), "Accept": "text/event-stream"},
            json={"request_id": str(uuid4()), "expected_revision": 1, "message": "Hello again"},
        )
        assert streamed.status_code == 200, streamed.text
        reloaded = client.get(f"/api/v1/conversations/{session['id']}")
        assert reloaded.status_code == 200, reloaded.text
        assert reloaded.json()["can_send"] is True
        assert [turn["state"] for turn in reloaded.json()["turns"]] == ["ready", "ready"]
        with database.session() as db:
            results = db.scalars(
                select(TeamTurnResult).where(TeamTurnResult.conversation_id == session["id"])
            ).all()
            assert len(results) == 4
            assert {result.state for result in results} == {"ready"}


@pytest.mark.parametrize("in_group", [False, True], ids=["personal", "group"])
@pytest.mark.parametrize("changed", ["shared_epoch", "member_epoch", "rag_epoch", "rag_identity"])
def test_teacher_team_resource_grant_still_rechecks_source_identity_and_epochs(
    client: TestClient, database: Database, in_group: bool, changed: str
) -> None:
    _group_with(database, BOWEN_ID)
    group_id = _group_with(database, MAYA_ID) if in_group else None
    team, _payload, set_ids, document_id = _resource_team(client, database, MAYA_ID, group_id)
    csrf = _login_id(client, BOWEN_ID)
    session = _create(client, csrf, {"kind": "team", "team_id": team["id"]})
    with database.session() as db:
        selection = resolve_chat_entry(db, BOWEN_ID, team["id"])
        resolve_frozen_chat_selection(db, BOWEN_ID, selection)
    with database.session() as db:
        if changed in {"shared_epoch", "member_epoch"}:
            row = db.get(KnowledgeSet, set_ids[1 if changed == "shared_epoch" else 0])
            assert row is not None
            row.authorization_epoch += 1
        elif changed == "rag_epoch":
            document = db.get(KnowledgeDocument, document_id)
            assert document is not None
            document.authorization_epoch += 1
        else:
            member = db.scalar(
                select(TeamVersionMember).where(
                    TeamVersionMember.team_version_id == team["current_version_id"],
                    TeamVersionMember.position == 0,
                )
            )
            assert member is not None
            member.raw_source_fences_json = "[]"
    with database.session() as db:
        with pytest.raises(PlatformError):
            resolve_frozen_chat_selection(db, BOWEN_ID, selection)
    refused = post_message(
        client,
        f"/api/v1/conversations/{session['id']}/messages",
        headers=_headers(csrf),
        json={"request_id": str(uuid4()), "expected_revision": 0, "message": "Still available?"},
    )
    if changed == "rag_epoch":
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == "team_member_source_unavailable"
    else:
        assert refused.status_code in {404, 409}, refused.text
    with database.session() as db:
        assert not db.scalars(
            select(TeamTurnResult).where(TeamTurnResult.conversation_id == session["id"])
        ).all()


def test_personal_teacher_team_recovers_exact_retained_publication_and_requires_live_grant(
    client: TestClient, database: Database
) -> None:
    team, payload, _set_ids, _document_id = _resource_team(client, database, MAYA_ID, None)
    with database.session() as db:
        selection = resolve_chat_entry(db, BOWEN_ID, team["id"])
    csrf = _login_id(client, MAYA_ID)
    updated = client.put(
        f"/api/v1/teams/{team['id']}",
        headers=_headers(csrf, f"teacher-resource-new-version-{uuid4()}"),
        json={**payload, "display_name": "New version", "expected_metadata_revision": 0},
    )
    assert updated.status_code == 200, updated.text
    with database.session() as db:
        publication = db.get(CourseTeamPublication, selection.publication_id)
        assert publication is not None and publication.state == "retained"
        resolve_frozen_chat_selection(db, BOWEN_ID, selection)
        publication.state = "revoked"
    with database.session() as db:
        with pytest.raises(PlatformError):
            resolve_frozen_chat_selection(db, BOWEN_ID, selection)
