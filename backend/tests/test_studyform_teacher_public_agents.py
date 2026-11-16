"""Studyform: students see, open and single-chat teachers' Public Agents.

Teacher-owned Public Agents stay owner/course-teacher editable; students do
not gain edit or delete. The sticker flag ``is_teacher_owned`` is true for
every course teacher owner (never a single hard-coded account).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.db import Database
from app.core.models import CourseMember, User
from app.core.models import GroupMember as WorkspaceMember
from app.modules.auth.dependencies import require_auth, require_authenticated_mutation
from app.modules.workspace.models import Conversation
from fastapi.testclient import TestClient

from tests.conftest import login, post_message
from tests.test_mayaform_team_conversations import _make_agent_version, _team
from tests.test_mayaform_teams import BOWEN_ID, COURSE_ID, MAYA_ID, _headers, _team_payload
from tests.test_wave3_agent_metadata import _context

FORBIDDEN_MEMBER_FIELDS = {"agent_md", "persona", "instructions", "system_prompt", "prompt"}
GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


def _add_teacher(database: Database, *, course_id: str = COURSE_ID) -> str:
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
        db.add(CourseMember(course_id=course_id, user_id=user_id, role="teacher", created_at=now))
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


def _legacy_single_chat(database: Database, version_id: str, user_id: str) -> str:
    """A single chat a student opened with a teacher's public Agent."""
    conversation_id = str(uuid4())
    with database.session() as db:
        from app.core.models import AgentVersion

        version = db.get(AgentVersion, version_id)
        assert version is not None
        db.add(
            Conversation(
                id=conversation_id,
                user_id=user_id,
                course_id=COURSE_ID,
                entry_kind="agent",
                chat_visibility="private",
                origin="single_agent",
                agent_version_id=version_id,
                snapshot_id=version.knowledge_snapshot_id,
                agent_name_snapshot="Legacy",
                agent_authorization_epoch=0,
                revision=0,
                active_request_id=None,
                created_at=datetime.now(UTC),
            )
        )
    return conversation_id


def _walk_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys |= _walk_keys(item)
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys |= _walk_keys(item)
        return keys
    return set()


def test_student_can_list_open_and_single_chat_teacher_public_agent(
    client: TestClient, database: Database
) -> None:
    team, versions, _teacher_csrf = _team(client, database)
    with database.session() as db:
        from app.core.models import AgentVersion

        agent_ids = [db.get(AgentVersion, v).agent_id for v in versions]  # type: ignore[union-attr]
    legacy_id = _legacy_single_chat(database, versions[0], BOWEN_ID)

    _student, csrf = login(client, "bowen")
    chat_agents = client.get(f"/api/v1/courses/{COURSE_ID}/chat-agents").json()
    assert {row["agent_id"] for row in chat_agents} >= set(agent_ids)
    published = client.get(f"/api/v1/courses/{COURSE_ID}/published-agents").json()
    published_ids = {row["agent"]["id"] for row in published}
    assert published_ids >= set(agent_ids)
    for row in published:
        if row["agent"]["id"] in agent_ids:
            assert row["agent"]["is_teacher_owned"] is True
            assert row["agent"]["can_edit"] is False
            assert row["agent"]["can_delete"] is False

    for agent_id, version_id in zip(agent_ids, versions, strict=True):
        detail = client.get(f"/api/v1/agents/{agent_id}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["is_teacher_owned"] is True
        assert body["can_edit"] is False
        assert body["can_delete"] is False
        assert client.get(f"/api/v1/agents/{agent_id}/versions").status_code == 200
        assert client.get(f"/api/v1/agent-versions/{version_id}").status_code == 200
        opened = client.post(
            "/api/v1/conversations",
            headers=_headers(csrf),
            json={"entry": {"kind": "agent", "version_id": version_id}},
        )
        assert opened.status_code == 200, opened.text
        assert opened.json()["can_send"] is True

    # The Team still works; roster stays free of prompt fields.
    directory = client.get(f"/api/v1/courses/{COURSE_ID}/maya-teams")
    assert directory.status_code == 200
    entry = next(row for row in directory.json() if row["id"] == team["id"])
    assert {m["display_name"] for m in entry["members"]} == {
        "Teacher member 0",
        "Teacher member 1",
    }
    assert not _walk_keys(directory.json()) & FORBIDDEN_MEMBER_FIELDS

    # A pre-existing single chat stays sendable once the Agent is visible again.
    legacy = client.get(f"/api/v1/conversations/{legacy_id}")
    assert legacy.status_code == 200
    assert legacy.json()["can_send"] is True
    sent = post_message(
        client,
        f"/api/v1/conversations/{legacy_id}/messages",
        headers=_headers(csrf),
        json={"request_id": str(uuid4()), "expected_revision": 0, "message": "still here?"},
    )
    assert sent.status_code == 200, sent.text


def test_two_teachers_public_agents_are_teacher_owned_and_student_usable(
    client: TestClient, database: Database
) -> None:
    second_teacher = _add_teacher(database)
    agents: list[tuple[str, str, str]] = []
    for owner_id, label in ((MAYA_ID, "Maya"), (second_teacher, "Second")):
        agent_id, version_id = _make_agent_version(
            database, owner_id=owner_id, name=f"{label} public guide", visibility="public"
        )
        agents.append((owner_id, agent_id, version_id))

    _student, csrf = login(client, "bowen")
    for _owner_id, agent_id, version_id in agents:
        detail = client.get(f"/api/v1/agents/{agent_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["is_teacher_owned"] is True
        assert detail.json()["can_edit"] is False
        chat = client.post(
            "/api/v1/conversations",
            headers=_headers(csrf),
            json={"entry": {"kind": "agent", "version_id": version_id}},
        )
        assert chat.status_code == 200, chat.text

    # Second teacher opens the first teacher's Agent (use, not student edit).
    second_csrf = _login_id(client, second_teacher)
    first_agent_id = agents[0][1]
    first_version_id = agents[0][2]
    detail = client.get(f"/api/v1/agents/{first_agent_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["is_teacher_owned"] is True
    chat = client.post(
        "/api/v1/conversations",
        headers=_headers(second_csrf),
        json={"entry": {"kind": "agent", "version_id": first_version_id}},
    )
    assert chat.status_code == 200, chat.text


def test_teacher_and_student_owned_agents_are_unaffected(
    client: TestClient, database: Database
) -> None:
    teacher_agent, teacher_version = _make_agent_version(
        database, owner_id=MAYA_ID, name="Teacher own public", visibility="public"
    )
    own_agent, own_version = _make_agent_version(
        database, owner_id=BOWEN_ID, name="Student own", visibility="private"
    )
    _teacher, teacher_csrf = login(client, "maya")
    assert client.get(f"/api/v1/agents/{teacher_agent}").status_code == 200
    teacher_chat = client.post(
        "/api/v1/conversations",
        headers=_headers(teacher_csrf),
        json={"entry": {"kind": "agent", "version_id": teacher_version}},
    )
    assert teacher_chat.status_code == 200, teacher_chat.text

    _student, csrf = login(client, "bowen")
    assert client.get(f"/api/v1/agents/{own_agent}").status_code == 200
    own_chat = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={"entry": {"kind": "agent", "version_id": own_version}},
    )
    assert own_chat.status_code == 200, own_chat.text
    assert own_chat.json()["can_send"] is True


def test_student_can_build_a_team_from_teacher_public_agents(
    client: TestClient, database: Database
) -> None:
    _a, teacher_version = _make_agent_version(
        database, owner_id=MAYA_ID, name="Teacher picker", visibility="public"
    )
    _b, own_version = _make_agent_version(
        database, owner_id=BOWEN_ID, name="Student picker", visibility="public"
    )
    _student, csrf = login(client, "bowen")
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"sf-team-{uuid4()}"),
        json=_team_payload([own_version, teacher_version], visibility="public"),
    )
    assert created.status_code == 201, created.text
    assert created.json()["can_edit"] is True
    assert created.json()["is_teacher_owned"] is False


def test_student_cannot_edit_or_delete_teacher_group_public_agent(
    client: TestClient, database: Database
) -> None:
    """Even when a teacher Agent is group-scoped, students stay non-editors."""

    now = datetime.now(UTC)
    with database.session() as db:
        existing = db.get(WorkspaceMember, (GROUP_ID, MAYA_ID))
        if existing is None:
            db.add(
                WorkspaceMember(group_id=GROUP_ID, user_id=MAYA_ID, role="member", created_at=now)
            )
            db.commit()
    agent_id, version_id = _make_agent_version(
        database,
        owner_id=MAYA_ID,
        name="Teacher group public",
        visibility="public",
        group_id=GROUP_ID,
    )
    _student, csrf = login(client, "bowen")
    detail = client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_edit"] is False
    assert detail.json()["can_delete"] is False
    assert detail.json()["is_teacher_owned"] is True
    refused = client.delete(f"/api/v1/agents/{agent_id}", headers=_headers(csrf, f"del-{uuid4()}"))
    assert refused.status_code == 404, refused.text
    patched = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf, f"patch-{uuid4()}"),
        json={"expected_revision": 0, "agent_md": "# no"},
    )
    assert patched.status_code == 404, patched.text
