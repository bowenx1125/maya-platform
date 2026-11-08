"""Owner 2026-11-08: a private Agent can be made public (never back).

It behaves like an identical public copy replacing the private one: its RAG
goes public with it, its AGENT.md and Voice stay, and its name moves to the
public namespace. It stays the same Agent, so its chats carry on.
"""

from __future__ import annotations

from app.core.models import AgentVersion, KnowledgeDocument
from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_w1_personal_workspace import GROUP_ID, _headers


def _agent(client: TestClient, csrf: str, name: str, visibility: str) -> tuple[str, str]:
    created = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(csrf, **{"Idempotency-Key": f"make-public-{name}-{visibility}"}),
        json={"name": name, "visibility": visibility},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"], created.json()["versions"][0]["id"]


def test_private_agent_goes_public_with_its_rag(client: TestClient) -> None:
    _, csrf = login(client, "bowen")
    agent_id, version_id = _agent(client, csrf, "Convert Me", "private")
    uploaded = client.post(
        f"/api/v1/groups/{GROUP_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "make-public-rag-001"}),
        data={"target_agent_version_id": version_id, "expected_revision": "0"},
        files={"file": ("notes.md", b"# Notes\n\nPrivate notes", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["document"]["visibility"] == "private"
    document_id = uploaded.json()["document"]["id"]
    with client.app.state.database.session() as db:
        epoch = db.get(KnowledgeDocument, document_id).authorization_epoch
    revision = client.get(f"/api/v1/agents/{agent_id}").json()["metadata_revision"]

    made = client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=_headers(csrf),
        json={"expected_metadata_revision": revision, "visibility": "public"},
    )
    assert made.status_code == 200, made.text
    assert made.json()["visibility"] == "public"
    assert made.json()["id"] == agent_id
    with client.app.state.database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document.visibility == "public"
        assert document.authorization_epoch == epoch + 1
        assert db.get(AgentVersion, version_id).draft_visibility == "public"

    back = client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=_headers(csrf),
        json={
            "expected_metadata_revision": made.json()["metadata_revision"],
            "visibility": "private",
        },
    )
    assert back.status_code == 409, back.text
    assert back.json()["code"] == "agent_public_is_final"


def test_public_name_clash_gets_a_suffix(client: TestClient) -> None:
    _owner, csrf = login(client, "bowen")
    _agent(client, csrf, "Twin", "public")
    private_id, _version = _agent(client, csrf, "Twin", "private")
    made = client.patch(
        f"/api/v1/agents/{private_id}",
        headers=_headers(csrf),
        json={"expected_metadata_revision": 0, "visibility": "public"},
    )
    assert made.status_code == 200, made.text
    assert made.json()["name"] == "Twin-2"


def test_only_the_creator_can_make_it_public(client: TestClient) -> None:
    _owner, owner_csrf = login(client, "bowen")
    agent_id, _version = _agent(client, owner_csrf, "Mine", "private")
    _teacher, teacher_csrf = login(client, "maya")
    joined = client.post(f"/api/v1/groups/{GROUP_ID}/membership", headers=_headers(teacher_csrf))
    assert joined.status_code == 200, joined.text
    refused = client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=_headers(teacher_csrf),
        json={"expected_metadata_revision": 0, "visibility": "public"},
    )
    assert refused.status_code in {403, 404}, refused.text
    _owner, owner_csrf = login(client, "bowen")
    assert client.get(f"/api/v1/agents/{agent_id}").json()["visibility"] == "private"
