"""Teacher opens and edits a student's public Agent in their course (hotfix).

PR #229: for a public, active Agent with an owner, the course teachers may
view, use, edit and delete it.  The teacher workbench loads the Agent, its
versions, the editor version and the libraries the editor offers; any 404 on
that path (the closed group library) surfaced as "This Agent was deleted or is
no longer shared with you." in the editor.
"""

from __future__ import annotations

from uuid import uuid4

from app.core.models import Agent, AgentVersion

from tests.conftest import login

GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


def _headers(csrf):
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())}


def _published_student_agent(client, visibility="public"):
    _, csrf = login(client, "bowen")
    response = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(csrf),
        json={"name": f"Student {visibility} {uuid4().hex[:6]}", "visibility": visibility},
    )
    assert response.status_code == 201, response.text
    agent = response.json()
    version_id = agent["versions"][0]["id"]
    database = client.app.state.database
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        version.state = "published"
        version.published_visibility = visibility
        db.get(Agent, agent["id"]).current_published_version_id = version_id
        db.commit()
    client.cookies.clear()
    return agent, version_id


def test_teacher_workbench_loads_and_edits_student_public_agent(client):
    agent, version_id = _published_student_agent(client)
    _, csrf = login(client, "maya")
    agent_id = agent["id"]
    detail = client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_edit"] is True
    assert detail.json()["can_delete"] is True
    course_id = detail.json()["course_id"]
    for url in (
        f"/api/v1/agents/{agent_id}/versions",
        f"/api/v1/agent-versions/{version_id}",
        f"/api/v1/groups/{GROUP_ID}",
        f"/api/v1/courses/{course_id}/knowledge-sets",
        f"/api/v1/agents/{agent_id}/knowledge-sets",
    ):
        response = client.get(url)
        assert response.status_code == 200, (url, response.text)
    # The group library stays closed to a teacher who has not joined the group
    # (test_teacher_group_visit); the editor must cope with that 404 itself.
    library = client.get(f"/api/v1/groups/{GROUP_ID}/knowledge-documents")
    assert library.status_code == 404
    nxt = client.post(f"/api/v1/agents/{agent_id}/versions", headers=_headers(csrf))
    assert nxt.status_code in (200, 201), nxt.text
    draft = nxt.json()
    for url in (
        f"/api/v1/agent-versions/{draft['id']}",
        f"/api/v1/agent-versions/{draft['id']}/rag-preview",
    ):
        response = client.get(url)
        assert response.status_code == 200, (url, response.text)
    saved = client.patch(
        f"/api/v1/agent-versions/{draft['id']}",
        headers=_headers(csrf),
        json={"expected_revision": draft["revision"], "agent_md": "# Teacher edit\nby teacher"},
    )
    assert saved.status_code == 200, saved.text


def test_teacher_still_cannot_open_student_private_agent(client):
    agent, _ = _published_student_agent(client, visibility="private")
    login(client, "maya")
    assert client.get(f"/api/v1/agents/{agent['id']}").status_code == 404
