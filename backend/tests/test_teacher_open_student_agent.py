"""Who opens and edits an Agent, end to end over HTTP (owner decision, #229).

PRIVATE Agent: only its creator sees, opens or edits it.
PUBLIC Agent: the creator, same-group students and the course's teachers open
AND edit it (detail, versions, next version, draft save, Knowledge Set
binding, Done/publish).  A teacher of another course and a student of another
group get 404 everywhere.

The editor also loads the group Markdown library. A teacher who has entered
the group is a temporary member and browses and uploads that library the way
a groupmate does. It stays 404 until they enter; the frontend copes with that
404 (see frontend/tests/teacher-open-student-agent). Private Agents stay
readable on a visit and creator-only to edit.

Concurrent Done: the first editor publishes; the second, still based on the
older published version, is rejected with 409 stale_base_version.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.core.models import Agent, AgentVersion

from tests.conftest import login, make_foreign_group
from tests.persona_fixtures import confirmed_persona_fields
from tests.test_public_agent_group_edit import _add_user

GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


def _headers(csrf):
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())}


def _login_id(client, user_id):
    """Act as any user: seeded accounts log in; extra users ride an override."""

    from app.core.models import User
    from app.modules.auth.dependencies import require_auth, require_authenticated_mutation

    from tests.test_wave3_agent_metadata import _context

    database = client.app.state.database
    with database.session() as db:
        username = db.get(User, user_id).username
    client.app.dependency_overrides.pop(require_auth, None)
    client.app.dependency_overrides.pop(require_authenticated_mutation, None)
    client.cookies.clear()
    if username in {"bowen", "kaikai", "maya", "jade"}:
        return login(client, username)[1]
    context = _context(database, user_id)
    client.app.dependency_overrides[require_auth] = lambda: context
    client.app.dependency_overrides[require_authenticated_mutation] = lambda: context
    return "x" * 40


def _published_student_agent(client, visibility):
    """Bowen (student) creates and really publishes an Agent over HTTP."""

    _login_id(client, "60541c78-30f1-55c5-b2aa-207b6a766883")
    _, csrf = login(client, "bowen")
    name = f"Student {visibility} {uuid4().hex[:6]}"
    created = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(csrf),
        json={"name": name, "visibility": visibility},
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    draft = agent["versions"][0]
    persona = confirmed_persona_fields(name, datetime.now(UTC))["agent_md"]
    saved = client.patch(
        f"/api/v1/agent-versions/{draft['id']}",
        headers=_headers(csrf),
        json={"expected_revision": draft["revision"], "agent_md": persona},
    )
    assert saved.status_code == 200, saved.text
    published = client.post(
        f"/api/v1/agent-versions/{draft['id']}/publish",
        headers=_headers(csrf),
        json={"expected_revision": saved.json()["revision"]},
    )
    assert published.status_code == 200, published.text
    client.cookies.clear()
    return agent["id"], draft["id"], persona


def _edit_and_publish(client, csrf, agent_id, base_version_id, marker):
    nxt = client.post(
        f"/api/v1/agents/{agent_id}/versions",
        params={"expected_base_version_id": base_version_id},
        headers=_headers(csrf),
    )
    if nxt.status_code != 201:
        return nxt
    draft = nxt.json()
    saved = client.patch(
        f"/api/v1/agent-versions/{draft['id']}",
        headers=_headers(csrf),
        json={"expected_revision": draft["revision"], "agent_md": draft["agent_md"] + marker},
    )
    assert saved.status_code == 200, saved.text
    return client.post(
        f"/api/v1/agent-versions/{draft['id']}/publish",
        headers=_headers(csrf),
        json={"expected_revision": saved.json()["revision"]},
    )


@pytest.fixture
def people(client):
    database = client.app.state.database
    from app.seed import BOWEN_ID, COURSE_ID, KAIKAI_ID, TEACHER_ID

    foreign_group = make_foreign_group(database, COURSE_ID)

    return {
        "creator": BOWEN_ID,
        "groupmate": KAIKAI_ID,
        "course_teacher": TEACHER_ID,
        "other_group_student": _add_user(
            database, role="student", course_id=COURSE_ID, group_id=foreign_group
        ),
        "other_course_teacher": _add_user(database, role="teacher", course_id=str(uuid4())),
    }


ALLOWED = {
    ("creator", "private"),
    ("creator", "public"),
    ("groupmate", "public"),
    ("course_teacher", "public"),
}


@pytest.mark.parametrize("visibility", ["private", "public"])
@pytest.mark.parametrize(
    "who",
    ["creator", "groupmate", "course_teacher", "other_group_student", "other_course_teacher"],
)
def test_open_and_edit_matrix(client, people, who, visibility):
    agent_id, version_id, _ = _published_student_agent(client, visibility)
    csrf = _login_id(client, people[who])
    allowed = (who, visibility) in ALLOWED
    reads = {
        "detail": client.get(f"/api/v1/agents/{agent_id}"),
        "versions": client.get(f"/api/v1/agents/{agent_id}/versions"),
        "version": client.get(f"/api/v1/agent-versions/{version_id}"),
        "knowledge_sets": client.get(f"/api/v1/agents/{agent_id}/knowledge-sets"),
    }
    for name, response in reads.items():
        assert response.status_code == (200 if allowed else 404), (name, response.text)
    if allowed:
        detail = reads["detail"].json()
        assert detail["can_edit"] is True and detail["can_delete"] is True
        assert detail["last_edited_by_name"]
        assert detail["current_version_label"] == "V1.0"
        listed = client.get(f"/api/v1/groups/{GROUP_ID}/agents")
        if who != "course_teacher":
            assert any(item["id"] == agent_id for item in listed.json())
    else:
        listed = client.get(f"/api/v1/groups/{GROUP_ID}/agents")
        if listed.status_code == 200:
            assert all(item["id"] != agent_id for item in listed.json())

    # Knowledge Set binding (editor "Knowledge" picker) with the current revision.
    revision = reads["knowledge_sets"].json()["agent_metadata_revision"] if allowed else 0
    bound = client.put(
        f"/api/v1/agents/{agent_id}/knowledge-sets",
        headers=_headers(csrf),
        json={"expected_agent_metadata_revision": revision, "set_ids": []},
    )
    assert bound.status_code == (200 if allowed else 404), bound.text

    # Done: next version from the published base, save, publish.
    published = _edit_and_publish(client, csrf, agent_id, version_id, f"\n<!-- {who} -->")
    assert published.status_code == (200 if allowed else 404), published.text
    if allowed:
        detail = client.get(f"/api/v1/agents/{agent_id}").json()
        assert detail["current_version_label"] == "V1.1"
        from app.core.models import User

        with client.app.state.database.session() as db:
            name = db.get(User, people[who]).display_name
        assert detail["last_edited_by_name"] == name


def test_course_teacher_cannot_browse_unjoined_group_library(client):
    agent_id, _, _ = _published_student_agent(client, "public")
    login(client, "maya")
    assert client.get(f"/api/v1/agents/{agent_id}").status_code == 200
    library = client.get(f"/api/v1/groups/{GROUP_ID}/knowledge-documents")
    assert library.status_code == 404


def test_entered_teacher_browses_and_uploads_the_library_like_a_groupmate(client):
    """Join is a temporary membership for the group library.

    Public and private Agents in the group are editable for the visit. Another
    student's private file stays hidden. Leaving closes the library.
    """

    public_id, public_version, _ = _published_student_agent(client, "public")
    private_id, private_version, _ = _published_student_agent(client, "private")
    _, student_csrf = login(client, "bowen")
    library = f"/api/v1/groups/{GROUP_ID}/knowledge-documents"
    shared = client.post(
        library,
        headers=_headers(student_csrf),
        data={"visibility": "public"},
        files={"file": ("shared.md", b"# Shared\n\npublic notes", "text/markdown")},
    )
    assert shared.status_code == 201, shared.text
    secret = client.post(
        library,
        headers=_headers(student_csrf),
        data={"visibility": "private"},
        files={"file": ("secret.md", b"# Secret\n\nprivate notes", "text/markdown")},
    )
    assert secret.status_code == 201, secret.text
    shared_id = shared.json()["document"]["id"]
    secret_id = secret.json()["document"]["id"]

    _, teacher_csrf = login(client, "maya")
    assert client.get(library).status_code == 404
    refused = client.post(
        library,
        headers=_headers(teacher_csrf),
        data={"visibility": "public"},
        files={"file": ("nope.md", b"# Nope\n", "text/markdown")},
    )
    assert refused.status_code == 404

    joined = client.post(
        f"/api/v1/groups/{GROUP_ID}/membership",
        headers={"Origin": "http://testserver", "X-CSRF-Token": teacher_csrf},
    )
    assert joined.status_code == 200, joined.text
    listed = {item["id"] for item in client.get(library).json()}
    assert shared_id in listed
    assert secret_id not in listed
    assert client.get(f"/api/v1/knowledge-documents/{secret_id}").status_code == 404

    uploaded = client.post(
        library,
        headers=_headers(teacher_csrf),
        data={"visibility": "public"},
        files={"file": ("teacher.md", b"# Teacher\n\nadded in the visit", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    teacher_doc_id = uploaded.json()["document"]["id"]
    listed = {item["id"] for item in client.get(library).json()}
    assert {shared_id, teacher_doc_id} <= listed
    assert secret_id not in listed

    detail = client.get(f"/api/v1/agents/{public_id}")
    assert detail.status_code == 200 and detail.json()["can_edit"] is True
    edited = _edit_and_publish(client, teacher_csrf, public_id, public_version, "\nteacher member")
    assert edited.status_code == 200, edited.text

    private = client.get(f"/api/v1/agents/{private_id}")
    assert private.status_code == 200 and private.json()["can_edit"] is True
    assert private.json()["can_delete"] is False
    edited_private = _edit_and_publish(
        client, teacher_csrf, private_id, private_version, "\nteacher visit"
    )
    assert edited_private.status_code == 200, edited_private.text

    assert (
        client.delete(
            f"/api/v1/groups/{GROUP_ID}/membership",
            headers={"Origin": "http://testserver", "X-CSRF-Token": teacher_csrf},
        ).status_code
        == 204
    )
    assert client.get(library).status_code == 404


def test_second_done_on_a_stale_base_is_rejected(client):
    agent_id, base_id, _ = _published_student_agent(client, "public")
    # Teacher and groupmate both opened V1.0.  The teacher clicks Done first.
    teacher_csrf = _login_id(client, "08b9de2d-bb75-5c71-a64b-231b48f9eb25")
    first = _edit_and_publish(client, teacher_csrf, agent_id, base_id, "\nteacher")
    assert first.status_code == 200, first.text
    winner = first.json()
    # The groupmate clicks Done second, still based on V1.0.
    client.cookies.clear()
    _, kaikai_csrf = login(client, "kaikai")
    # Hover data the student sees: latest version and the teacher as editor.
    listed = client.get(f"/api/v1/groups/{GROUP_ID}/agents").json()
    card = next(item for item in listed if item["id"] == agent_id)
    assert card["current_version_label"] == "V1.1"
    from app.core.models import User

    with client.app.state.database.session() as db:
        teacher_name = db.get(User, "08b9de2d-bb75-5c71-a64b-231b48f9eb25").display_name
    assert card["last_edited_by_name"] == teacher_name
    second = _edit_and_publish(client, kaikai_csrf, agent_id, base_id, "\ngroupmate")
    assert second.status_code == 409, second.text
    body = second.json()
    assert body["code"] == "stale_base_version"
    assert body["details"]["expected_base_version_id"] == base_id
    assert body["details"]["current_published_version_id"] == winner["id"]
    assert body["details"]["current_version_label"] == "V1.1"
    with client.app.state.database.session() as db:
        agent = db.get(Agent, agent_id)
        assert agent.current_published_version_id == winner["id"]
        assert db.get(AgentVersion, winner["id"]).agent_md.endswith("teacher")
        # No orphan draft was created by the rejected request.
        assert (
            db.query(AgentVersion)
            .filter(AgentVersion.agent_id == agent_id, AgentVersion.state == "draft")
            .count()
            == 0
        )
    # After refreshing onto V1.1 the groupmate's Done goes through.
    retried = _edit_and_publish(client, kaikai_csrf, agent_id, winner["id"], "\ngroupmate")
    assert retried.status_code == 200, retried.text
    assert retried.json()["version_label"] == "V1.2"


def test_next_version_without_base_keeps_old_behaviour(client):
    agent_id, _, _ = _published_student_agent(client, "public")
    _, csrf = login(client, "bowen")
    nxt = client.post(f"/api/v1/agents/{agent_id}/versions", headers=_headers(csrf))
    assert nxt.status_code == 201, nxt.text
