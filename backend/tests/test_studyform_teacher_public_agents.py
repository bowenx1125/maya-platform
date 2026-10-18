"""Studyform: a teacher's public Agent reaches students only through a Team.

Students keep seeing and chatting with a teacher's public Team, and see its
member names/avatars, but cannot list, open, download or single-chat with a
teacher's public Agent. Existing single chats stay readable but read-only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.db import Database
from app.core.models import AgentVersion
from app.modules.workspace.models import Conversation
from fastapi.testclient import TestClient

from tests.conftest import login, post_message
from tests.test_mayaform_team_conversations import _make_agent_version, _team
from tests.test_mayaform_teams import BOWEN_ID, COURSE_ID, MAYA_ID, _headers

FORBIDDEN_MEMBER_FIELDS = {"agent_md", "persona", "instructions", "system_prompt", "prompt"}


def _legacy_single_chat(database: Database, version_id: str, user_id: str) -> str:
    """A single chat a student opened before this rule existed."""
    conversation_id = str(uuid4())
    with database.session() as db:
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


def test_student_cannot_list_open_or_single_chat_teacher_public_agent(
    client: TestClient, database: Database
) -> None:
    team, versions, _teacher_csrf = _team(client, database)
    with database.session() as db:
        agent_ids = [db.get(AgentVersion, v).agent_id for v in versions]  # type: ignore[union-attr]
    legacy_id = _legacy_single_chat(database, versions[0], BOWEN_ID)

    _student, csrf = login(client, "bowen")
    chat_agents = client.get(f"/api/v1/courses/{COURSE_ID}/chat-agents").json()
    assert not {row["agent_id"] for row in chat_agents} & set(agent_ids)
    published = client.get(f"/api/v1/courses/{COURSE_ID}/published-agents").json()
    assert not {row["agent"]["id"] for row in published} & set(agent_ids)

    for agent_id, version_id in zip(agent_ids, versions, strict=True):
        assert client.get(f"/api/v1/agents/{agent_id}").status_code == 404
        assert client.get(f"/api/v1/agents/{agent_id}/versions").status_code == 404
        assert client.get(f"/api/v1/agent-versions/{version_id}").status_code == 404
        download = client.get(f"/api/v1/agent-versions/{version_id}/agent-md/download")
        assert download.status_code == 404
        refused = client.post(
            "/api/v1/conversations",
            headers=_headers(csrf),
            json={"entry": {"kind": "agent", "version_id": version_id}},
        )
        assert refused.status_code == 404
        legacy_shape = client.post(
            "/api/v1/conversations", headers=_headers(csrf), json={"version_id": version_id}
        )
        assert legacy_shape.status_code == 404
        memory = client.post(
            "/api/v1/conversations/memory-entry",
            headers=_headers(csrf),
            json={
                "action_id": str(uuid4()),
                "course_id": COURSE_ID,
                "source": {"kind": "agent", "agent_id": agent_id},
            },
        )
        assert memory.status_code == 404, memory.text

    # The Team is still there: summary, member names/avatars, no member prompt.
    directory = client.get(f"/api/v1/courses/{COURSE_ID}/maya-teams")
    assert directory.status_code == 200
    entry = next(row for row in directory.json() if row["id"] == team["id"])
    assert {m["display_name"] for m in entry["members"]} == {
        "Teacher member 0",
        "Teacher member 1",
    }
    assert all("avatar_config" in m for m in entry["members"])
    assert not _walk_keys(directory.json()) & FORBIDDEN_MEMBER_FIELDS
    detail = client.get(f"/api/v1/teams/{team['id']}")
    if detail.status_code == 200:
        assert detail.json()["can_edit"] is False
        assert not _walk_keys(detail.json()) & FORBIDDEN_MEMBER_FIELDS
    else:
        assert detail.status_code == 404

    # ...and a student can still open and talk to it; members run server-side.
    session = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={"entry": {"kind": "maya_team", "team_id": team["id"]}},
    )
    assert session.status_code == 200, session.text
    chat = session.json()
    assert chat["can_send"] is True
    assert not _walk_keys(chat) & FORBIDDEN_MEMBER_FIELDS
    sent = post_message(
        client,
        f"/api/v1/conversations/{chat['id']}/messages",
        headers=_headers(csrf),
        json={"request_id": str(uuid4()), "expected_revision": chat["revision"], "message": "hi"},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["turns"], sent.text

    # A pre-existing single chat stays readable, but it is read-only now.
    legacy = client.get(f"/api/v1/conversations/{legacy_id}")
    assert legacy.status_code == 200
    assert legacy.json()["can_send"] is False
    assert legacy.json()["agent"]["available"] is False
    blocked = post_message(
        client,
        f"/api/v1/conversations/{legacy_id}/messages",
        headers=_headers(csrf),
        json={"request_id": str(uuid4()), "expected_revision": 0, "message": "still here?"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "agent_unavailable"


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


def test_student_cannot_build_a_team_from_teacher_public_agents(
    client: TestClient, database: Database
) -> None:
    from tests.test_mayaform_teams import _team_payload

    _a, teacher_version = _make_agent_version(
        database, owner_id=MAYA_ID, name="Teacher picker", visibility="public"
    )
    _b, own_version = _make_agent_version(
        database, owner_id=BOWEN_ID, name="Student picker", visibility="private"
    )
    _student, csrf = login(client, "bowen")
    refused = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"sf-team-{uuid4()}"),
        json=_team_payload([own_version, teacher_version]),
    )
    assert refused.status_code == 404, refused.text
