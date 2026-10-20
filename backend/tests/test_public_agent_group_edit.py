"""Public Agents: groupmates and course teachers edit/delete; others cannot.

Role x action matrix (2026-10-20 owner decision):
creator / groupmate / other-group student / teacher same course /
teacher other course  x  view, edit, publish-next, delete.
Private Agents stay creator-only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import Agent, AgentEditAudit, AgentVersion, CourseMember, User
from app.core.models import GroupMember as WorkspaceMember
from app.modules.agents.router import _student_delete_scope
from app.modules.knowledge.services import (
    public_agent_editor_role,
    visible_student_agent,
    visible_student_version,
)
from app.seed import BOWEN_ID, COURSE_ID, KAIKAI_ID, TEACHER_ID

from tests.conftest import login, make_foreign_group
from tests.test_wave3_agent_metadata import _context

GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


def _headers(csrf):
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())}


def _create(client, csrf, name, visibility):
    response = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(csrf),
        json={"name": name, "visibility": visibility},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_user(database, *, role, course_id=COURSE_ID, group_id=None):
    user_id = str(uuid4())
    now = datetime.now(UTC)
    with database.session() as db:
        from app.core.models import Course

        if db.get(Course, course_id) is None:
            db.add(Course(id=course_id, code=f"c-{course_id}", name="Other", created_at=now))
            db.flush()
        db.add(
            User(
                id=user_id,
                username=f"u-{user_id}",
                display_name=f"U {role}",
                status="active",
                created_at=now,
            )
        )
        db.flush()
        db.add(CourseMember(course_id=course_id, user_id=user_id, role=role, created_at=now))
        if group_id is not None:
            db.add(
                WorkspaceMember(group_id=group_id, user_id=user_id, role="member", created_at=now)
            )
        db.commit()
    return user_id


@pytest.fixture
def actors(client):
    database = client.app.state.database
    foreign_group = make_foreign_group(database, COURSE_ID)
    return {
        "creator": BOWEN_ID,
        "groupmate": KAIKAI_ID,
        "other_group_student": _add_user(database, role="student", group_id=foreign_group),
        "teacher_same_course": TEACHER_ID,
        "teacher_other_course": _add_user(database, role="teacher", course_id=str(uuid4())),
    }


EXPECTED_PUBLIC = {
    "creator": "owner",
    "groupmate": "groupmate",
    "other_group_student": None,
    "teacher_same_course": "course_teacher",
    "teacher_other_course": None,
}


@pytest.mark.parametrize("who", list(EXPECTED_PUBLIC))
@pytest.mark.parametrize("visibility", ["public", "private"])
@pytest.mark.parametrize("published", [False, True])
def test_edit_and_delete_matrix(client, actors, who, visibility, published):
    _, csrf = login(client, "bowen")
    agent = _create(client, csrf, f"Matrix {who} {visibility} {published}", visibility)
    database = client.app.state.database
    context = _context(database, actors[who])
    expected = (
        EXPECTED_PUBLIC[who] if visibility == "public" else ("owner" if who == "creator" else None)
    )
    draft_id = agent["versions"][0]["id"]
    if published:
        with database.session() as db:
            version = db.get(AgentVersion, draft_id)
            version.state = "published"
            version.published_visibility = visibility
            db.get(Agent, agent["id"]).current_published_version_id = draft_id
            db.commit()
    elif who == "teacher_same_course":
        # Pre-publication rule: a teacher never meets an unpublished draft.
        expected = None
    with database.session() as db:
        row = db.get(Agent, agent["id"])
        assert public_agent_editor_role(db, context, row) == expected
        if expected is None:
            for check in (
                lambda: visible_student_agent(db, context, agent["id"]),
                lambda: visible_student_version(db, context, draft_id),
                lambda: _student_delete_scope(db, context, agent["id"]),
            ):
                with pytest.raises(PlatformError) as caught:
                    check()
                assert caught.value.status_code == 404
        else:
            assert visible_student_agent(db, context, agent["id"]).agent.id == agent["id"]
            assert visible_student_version(db, context, draft_id).version.id == draft_id
            assert _student_delete_scope(db, context, agent["id"]).id == agent["id"]


def test_groupmate_edits_records_last_editor_and_stale_save_conflicts(client):
    _, bowen_csrf = login(client, "bowen")
    agent = _create(client, bowen_csrf, "Shared Zhu Xi", "public")
    draft = agent["versions"][0]
    client.cookies.clear()
    _, kaikai_csrf = login(client, "kaikai")
    url = f"/api/v1/agent-versions/{draft['id']}"
    saved = client.patch(
        url,
        headers=_headers(kaikai_csrf),
        json={
            "expected_revision": draft["revision"],
            "agent_md": "# Shared Zhu Xi\nEdited by groupmate",
        },
    )
    assert saved.status_code == 200, saved.text
    stale = client.patch(
        url,
        headers=_headers(kaikai_csrf),
        json={"expected_revision": draft["revision"], "agent_md": "# Shared Zhu Xi\nStale"},
    )
    assert stale.status_code == 409, stale.text
    with client.app.state.database.session() as db:
        assert db.get(AgentEditAudit, agent["id"]).last_edited_by_user_id == KAIKAI_ID
        assert db.get(AgentVersion, draft["id"]).agent_md.endswith("Edited by groupmate")
    detail = client.get(f"/api/v1/agents/{agent['id']}").json()
    assert detail["can_edit"] is True and detail["can_delete"] is True
    assert detail["is_creator"] is False
    assert detail["last_edited_by_name"]


def test_groupmate_soft_deletes_public_agent_and_is_recorded(client):
    _, bowen_csrf = login(client, "bowen")
    agent = _create(client, bowen_csrf, "Deletable", "public")
    client.cookies.clear()
    _, kaikai_csrf = login(client, "kaikai")
    deleted = client.delete(f"/api/v1/agents/{agent['id']}", headers=_headers(kaikai_csrf))
    assert deleted.status_code == 204, deleted.text
    with client.app.state.database.session() as db:
        row = db.get(Agent, agent["id"])
        assert row.deleted_at is not None and row.status == "archived"
        assert db.get(AgentEditAudit, agent["id"]).deleted_by_user_id == KAIKAI_ID


def test_groupmate_cannot_touch_private_agent_over_http(client):
    _, bowen_csrf = login(client, "bowen")
    agent = _create(client, bowen_csrf, "Private one", "private")
    client.cookies.clear()
    _, kaikai_csrf = login(client, "kaikai")
    assert (
        client.delete(f"/api/v1/agents/{agent['id']}", headers=_headers(kaikai_csrf)).status_code
        == 404
    )
    patched = client.patch(
        f"/api/v1/agent-versions/{agent['versions'][0]['id']}",
        headers=_headers(kaikai_csrf),
        json={"expected_revision": 0, "agent_md": "# Private one\nx"},
    )
    assert patched.status_code == 404


def test_visibility_cannot_change_for_anyone(client):
    _, bowen_csrf = login(client, "bowen")
    agent = _create(client, bowen_csrf, "Locked", "public")
    response = client.patch(
        f"/api/v1/agents/{agent['id']}",
        headers=_headers(bowen_csrf),
        json={"expected_metadata_revision": 0, "visibility": "private"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "agent_visibility_locked"
