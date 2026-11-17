"""Studyform: students see, open, chat, and edit teachers' Public Agents.

Students cannot delete teacher Agents. Course teachers keep main's delete
right on other teachers' Public Agents. Teacher Private Agents stay
owner-only. Student Public Agents keep the groupmate/course-teacher rule.
``is_teacher_owned`` is true for every course teacher owner (never a single
hard-coded account).
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
from tests.test_teacher_open_student_agent import _edit_and_publish
from tests.test_wave3_agent_metadata import _context

FORBIDDEN_MEMBER_FIELDS = {"agent_md", "persona", "instructions", "system_prompt", "prompt"}
GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
TEACHER_MD = "# Teacher public guide\n\nPublished content students must see."


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


def _teacher_public(
    database: Database,
    *,
    owner_id: str = MAYA_ID,
    name: str = "Teacher public",
    group_id: str | None = None,
) -> tuple[str, str]:
    agent_id, version_id = _make_agent_version(
        database, owner_id=owner_id, name=name, visibility="public", group_id=group_id
    )
    with database.session() as db:
        from app.core.models import AgentVersion

        version = db.get(AgentVersion, version_id)
        assert version is not None
        version.agent_md = TEACHER_MD
    return agent_id, version_id


def test_student_can_list_open_edit_and_single_chat_teacher_public_agent(
    client: TestClient, database: Database
) -> None:
    team, versions, _teacher_csrf = _team(client, database)
    with database.session() as db:
        from app.core.models import AgentVersion

        agent_ids = [db.get(AgentVersion, v).agent_id for v in versions]  # type: ignore[union-attr]
        for version_id in versions:
            version = db.get(AgentVersion, version_id)
            assert version is not None
            version.agent_md = TEACHER_MD
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
            assert row["agent"]["can_edit"] is True
            assert row["agent"]["can_delete"] is False
            assert row["current_version"]["agent_md"] == ""

    for agent_id, version_id in zip(agent_ids, versions, strict=True):
        detail = client.get(f"/api/v1/agents/{agent_id}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["is_teacher_owned"] is True
        assert body["can_edit"] is True
        assert body["can_delete"] is False
        assert body["current_published_version_id"] == version_id
        listed = client.get(f"/api/v1/agents/{agent_id}/versions")
        assert listed.status_code == 200, listed.text
        assert any(item["id"] == version_id for item in listed.json())
        version = client.get(f"/api/v1/agent-versions/{version_id}")
        assert version.status_code == 200, version.text
        assert version.json()["agent_md"] == TEACHER_MD
        opened = client.post(
            "/api/v1/conversations",
            headers=_headers(csrf),
            json={"entry": {"kind": "agent", "version_id": version_id}},
        )
        assert opened.status_code == 200, opened.text
        assert opened.json()["can_send"] is True

    # Student edits and publishes the teacher's Public Agent; cannot delete it
    # or revert Public→Private (visibility stays owner-only / final).
    first_agent_id, first_version_id = agent_ids[0], versions[0]
    published_edit = _edit_and_publish(
        client, csrf, first_agent_id, first_version_id, "\n<!-- student edit -->"
    )
    assert published_edit.status_code == 200, published_edit.text
    assert "<!-- student edit -->" in published_edit.json()["agent_md"]
    detail_after = client.get(f"/api/v1/agents/{first_agent_id}")
    assert detail_after.status_code == 200, detail_after.text
    assert detail_after.json()["can_manage_visibility"] is False
    reverted = client.patch(
        f"/api/v1/agents/{first_agent_id}",
        headers=_headers(csrf, f"vis-{uuid4()}"),
        json={
            "expected_metadata_revision": detail_after.json()["metadata_revision"],
            "visibility": "private",
        },
    )
    assert reverted.status_code == 404, reverted.text
    refused = client.delete(
        f"/api/v1/agents/{first_agent_id}", headers=_headers(csrf, f"del-{uuid4()}")
    )
    assert refused.status_code == 404, refused.text

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


def test_two_teachers_public_agents_are_editable_across_roles(
    client: TestClient, database: Database
) -> None:
    second_teacher = _add_teacher(database)
    agents: list[tuple[str, str, str]] = []
    for owner_id, label in ((MAYA_ID, "Maya"), (second_teacher, "Second")):
        agent_id, version_id = _teacher_public(
            database, owner_id=owner_id, name=f"{label} public guide"
        )
        agents.append((owner_id, agent_id, version_id))

    _student, csrf = login(client, "bowen")
    for _owner_id, agent_id, version_id in agents:
        detail = client.get(f"/api/v1/agents/{agent_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["is_teacher_owned"] is True
        assert detail.json()["can_edit"] is True
        assert detail.json()["can_delete"] is False
        assert client.get(f"/api/v1/agent-versions/{version_id}").json()["agent_md"] == TEACHER_MD
        chat = client.post(
            "/api/v1/conversations",
            headers=_headers(csrf),
            json={"entry": {"kind": "agent", "version_id": version_id}},
        )
        assert chat.status_code == 200, chat.text

    # Second teacher edits and may delete the first teacher's Public Agent
    # (main ba5d0031 delete right; only students lose delete).
    second_csrf = _login_id(client, second_teacher)
    first_agent_id = agents[0][1]
    first_version_id = agents[0][2]
    detail = client.get(f"/api/v1/agents/{first_agent_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_edit"] is True
    assert detail.json()["can_delete"] is True
    edited = _edit_and_publish(
        client, second_csrf, first_agent_id, first_version_id, "\n<!-- peer teacher -->"
    )
    assert edited.status_code == 200, edited.text
    deleted = client.delete(
        f"/api/v1/agents/{first_agent_id}", headers=_headers(second_csrf, f"del-{uuid4()}")
    )
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/v1/agents/{first_agent_id}").status_code == 404


def test_teacher_and_student_owned_agents_are_unaffected(
    client: TestClient, database: Database
) -> None:
    teacher_agent, teacher_version = _teacher_public(
        database, owner_id=MAYA_ID, name="Teacher own public"
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
    _a, teacher_version = _teacher_public(database, name="Teacher picker")
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


def test_student_edits_but_cannot_delete_teacher_group_public_agent(
    client: TestClient, database: Database
) -> None:
    """Group-scoped teacher Public Agents follow the same course-wide edit rule."""

    now = datetime.now(UTC)
    with database.session() as db:
        existing = db.get(WorkspaceMember, (GROUP_ID, MAYA_ID))
        if existing is None:
            db.add(
                WorkspaceMember(group_id=GROUP_ID, user_id=MAYA_ID, role="member", created_at=now)
            )
            db.commit()
    agent_id, version_id = _teacher_public(database, name="Teacher group public", group_id=GROUP_ID)
    _student, csrf = login(client, "bowen")
    detail = client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_edit"] is True
    assert detail.json()["can_delete"] is False
    assert detail.json()["is_teacher_owned"] is True
    assert client.get(f"/api/v1/agent-versions/{version_id}").json()["agent_md"] == TEACHER_MD
    edited = _edit_and_publish(client, csrf, agent_id, version_id, "\n<!-- group student -->")
    assert edited.status_code == 200, edited.text
    refused = client.delete(f"/api/v1/agents/{agent_id}", headers=_headers(csrf, f"del-{uuid4()}"))
    assert refused.status_code == 404, refused.text


def test_student_cannot_open_or_edit_teacher_private_agent(
    client: TestClient, database: Database
) -> None:
    agent_id, version_id = _make_agent_version(
        database, owner_id=MAYA_ID, name="Teacher private", visibility="private"
    )
    _student, csrf = login(client, "bowen")
    assert client.get(f"/api/v1/agents/{agent_id}").status_code == 404
    assert client.get(f"/api/v1/agents/{agent_id}/versions").status_code == 404
    assert client.get(f"/api/v1/agent-versions/{version_id}").status_code == 404
    patched = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf, f"patch-{uuid4()}"),
        json={"expected_revision": 0, "agent_md": "# no"},
    )
    assert patched.status_code == 404, patched.text
    chat = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={"entry": {"kind": "agent", "version_id": version_id}},
    )
    assert chat.status_code == 404, chat.text


def test_teacher_public_private_draft_stays_hidden_from_student_editors(
    client: TestClient, database: Database
) -> None:
    """#455: student editors see the published version, not a private draft."""

    import json

    from app.core.models import AgentDebateCard, AgentVersion
    from app.modules.agents.debate_cards import CARD_PROMPT_VERSION
    from app.modules.agents.markdown import markdown_hash

    from tests.test_debate_cards import CARD
    from tests.test_per_agent_cards import _save

    agent_id, published_id = _teacher_public(database, name="Teacher card fence")
    _, teacher_csrf = login(client, "maya")
    nxt = client.post(
        f"/api/v1/agents/{agent_id}/versions",
        headers=_headers(teacher_csrf, f"next-{uuid4()}"),
    )
    assert nxt.status_code == 201, nxt.text
    draft_id = nxt.json()["id"]
    assert _save(client, draft_id, teacher_csrf, "Private teacher draft").status_code == 200
    now = datetime.now(UTC)
    with database.session() as db:
        draft = db.get(AgentVersion, draft_id)
        assert draft is not None
        draft.draft_visibility = "private"
        row = db.get(AgentDebateCard, agent_id)
        payload = {
            "agent_version_id": draft_id,
            "agent_md_hash": markdown_hash("Private teacher draft"),
            "language": "en",
            "card_status": "fallback",
            "card_json": None,
            "card_safe_error_code": "debate_card_failed",
            "salvaged": False,
            "prompt_version": CARD_PROMPT_VERSION,
            "updated_at": now,
        }
        if row is None:
            db.add(AgentDebateCard(agent_id=agent_id, created_at=now, **payload))
        else:
            for key, value in payload.items():
                setattr(row, key, value)
        db.commit()

    _student, _csrf = login(client, "bowen")
    hidden = client.get(f"/api/v1/agent-versions/{draft_id}")
    assert hidden.status_code == 404
    assert "stored_card_status" not in hidden.text
    visible = client.get(f"/api/v1/agent-versions/{published_id}")
    assert visible.status_code == 200, visible.text
    assert visible.json()["agent_md"] == TEACHER_MD
    assert visible.json()["stored_card_status"] is None
    detail = client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_edit"] is True
    assert all(item["id"] != draft_id for item in detail.json()["versions"])
    listed = client.get(f"/api/v1/agents/{agent_id}/versions")
    assert listed.status_code == 200, listed.text
    assert all(item["id"] != draft_id for item in listed.json())
    # Published version may carry its own card status once the row points at it.
    with database.session() as db:
        row = db.get(AgentDebateCard, agent_id)
        assert row is not None
        row.agent_version_id = published_id
        row.agent_md_hash = markdown_hash(TEACHER_MD)
        row.card_status = "ready"
        row.card_json = json.dumps(CARD)
        row.card_safe_error_code = None
        row.salvaged = False
        db.commit()
    ready = client.get(f"/api/v1/agent-versions/{published_id}")
    assert ready.status_code == 200, ready.text
    assert ready.json()["stored_card_status"] == "ready"


def test_student_workbench_apis_for_teacher_public_personal_agent(
    client: TestClient, database: Database
) -> None:
    """Editor entry needs version+agent; personal workspace docs stay teacher-only.

    AgentWorkbench loads ``GET /courses/{id}/workspace-documents`` for personal
    Agents. That list is owner-teacher scoped (404 for students). The frontend
    soft-fails that 404 and keeps ``enabled_documents`` from the published
    version — so students must still read the version and edit/publish without
    ever listing the teacher's personal workspace.
    """

    agent_id, version_id = _teacher_public(
        database, owner_id=MAYA_ID, name="Teacher personal workbench"
    )
    _student, csrf = login(client, "bowen")

    workspace = client.get(f"/api/v1/courses/{COURSE_ID}/workspace-documents")
    assert workspace.status_code == 404, workspace.text

    detail = client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_edit"] is True
    assert detail.json()["can_delete"] is False
    assert detail.json()["ownership_scope"] == "personal"
    assert detail.json()["group_id"] is None

    version = client.get(f"/api/v1/agent-versions/{version_id}")
    assert version.status_code == 200, version.text
    body = version.json()
    assert body["agent_md"] == TEACHER_MD
    assert "enabled_documents" in body

    knowledge = client.get(f"/api/v1/agents/{agent_id}/knowledge-sets")
    assert knowledge.status_code == 200, knowledge.text

    edited = _edit_and_publish(client, csrf, agent_id, version_id, "\n<!-- workbench student -->")
    assert edited.status_code == 200, edited.text
    assert "<!-- workbench student -->" in edited.json()["agent_md"]


def test_student_public_agent_editor_rule_unchanged(client: TestClient, database: Database) -> None:
    """Same-group students and course teachers still edit student Public Agents."""

    from app.seed import TEACHER_ID

    from tests.conftest import make_foreign_group
    from tests.test_public_agent_group_edit import _add_user

    agent_id, version_id = _make_agent_version(
        database,
        owner_id=BOWEN_ID,
        name="Student public shared",
        visibility="public",
        group_id=GROUP_ID,
    )
    # Groupmate edits.
    _, kaikai_csrf = login(client, "kaikai")
    detail = client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_edit"] is True
    assert detail.json()["can_delete"] is True
    assert detail.json()["is_teacher_owned"] is False
    edited = _edit_and_publish(client, kaikai_csrf, agent_id, version_id, "\n<!-- groupmate -->")
    assert edited.status_code == 200, edited.text
    version_id = edited.json()["id"]

    # Course teacher edits.
    teacher_csrf = _login_id(client, TEACHER_ID)
    detail = client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_edit"] is True
    assert detail.json()["can_delete"] is True
    edited = _edit_and_publish(client, teacher_csrf, agent_id, version_id, "\n<!-- teacher -->")
    assert edited.status_code == 200, edited.text

    # Other-group student still cannot.
    other = _add_user(database, role="student", group_id=make_foreign_group(database, COURSE_ID))
    other_csrf = _login_id(client, other)
    assert client.get(f"/api/v1/agents/{agent_id}").status_code == 404
    patched = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(other_csrf, f"patch-{uuid4()}"),
        json={"expected_revision": 0, "agent_md": "# no"},
    )
    assert patched.status_code == 404, patched.text
