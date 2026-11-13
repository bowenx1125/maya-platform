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


def _make_public(client: TestClient, csrf: str, agent_id: str, revision: int = 0):
    return client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=_headers(csrf),
        json={"expected_metadata_revision": revision, "visibility": "public"},
    )


def test_only_the_creator_can_make_a_private_agent_public(client: TestClient) -> None:
    """A caller who cannot read a private Agent cannot publish it either."""

    from app.core.models import Agent
    from app.modules.org.classes import SECOND_CLASS_ID
    from app.seed import BOWEN_ID

    from tests.test_auth_self_registration import register

    _, owner_csrf = login(client, "bowen")
    creator_id, _version = _agent(client, owner_csrf, "Creator publishes", "private")
    before = client.get(f"/api/v1/agents/{creator_id}")
    assert before.status_code == 200, before.text
    assert before.json()["can_manage_visibility"] is True
    made = _make_public(client, owner_csrf, creator_id, before.json()["metadata_revision"])
    assert made.status_code == 200, made.text
    assert made.json()["visibility"] == "public"
    assert made.json()["is_creator"] is True
    assert made.json()["can_manage_visibility"] is False

    _, owner_csrf = login(client, "bowen")
    groupmate_id, _version = _agent(client, owner_csrf, "Groupmate publishes", "private")
    client.cookies.clear()
    _, kaikai_csrf = login(client, "kaikai")
    detail = client.get(f"/api/v1/agents/{groupmate_id}")
    assert detail.status_code == 404
    made = client.patch(
        f"/api/v1/agents/{groupmate_id}",
        headers=_headers(kaikai_csrf),
        json={
            "expected_metadata_revision": 0,
            "visibility": "public",
            "name": "Stolen",
            "description": "Not the groupmate's draft.",
        },
    )
    assert made.status_code in {403, 404}, made.text
    client.cookies.clear()
    _, owner_csrf = login(client, "bowen")
    kept = client.get(f"/api/v1/agents/{groupmate_id}")
    assert kept.status_code == 200, kept.text
    assert kept.json()["visibility"] == "private"
    assert kept.json()["name"] == "Groupmate publishes"
    assert kept.json()["description"] == ""
    with client.app.state.database.session() as db:
        assert db.get(Agent, groupmate_id).owner_user_id == BOWEN_ID

    _, owner_csrf = login(client, "bowen")
    teacher_id, _version = _agent(client, owner_csrf, "Teacher publishes", "private")
    client.cookies.clear()
    _, maya_csrf = login(client, "maya")
    assert client.get(f"/api/v1/agents/{teacher_id}").status_code == 404
    made = _make_public(client, maya_csrf, teacher_id)
    assert made.status_code in {403, 404}, made.text

    # Bowen signed in as Maya is that same teacher account.
    _, owner_csrf = login(client, "bowen")
    via_id, _version = _agent(client, owner_csrf, "Bowen as Maya publishes", "private")
    client.cookies.clear()
    challenge = client.post(
        "/api/v1/auth/login", json={"username": "bowen", "password": "demo-password"}
    )
    assert challenge.status_code == 202, challenge.text
    chosen = client.post(
        "/api/v1/auth/identity-choice",
        json={"choice_token": challenge.json()["choice_token"], "identity": "maya"},
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["user"]["username"] == "maya"
    made = _make_public(client, chosen.json()["csrf_token"], via_id)
    assert made.status_code in {403, 404}, made.text
    with client.app.state.database.session() as db:
        assert db.get(Agent, via_id).owner_user_id == BOWEN_ID
        assert db.get(Agent, via_id).visibility == "private"

    _, owner_csrf = login(client, "bowen")
    foreign_id, _version = _agent(client, owner_csrf, "Other group cannot", "private")
    client.cookies.clear()
    other = register(client, username="othergroupstudent", group_name="Elsewhere")
    assert other.status_code == 201, other.text
    refused = _make_public(client, other.json()["csrf_token"], foreign_id)
    assert refused.status_code == 404, refused.text

    client.cookies.clear()
    outsider = register(
        client,
        username="outsiderstudent",
        group_name="Far Group",
        course_id=SECOND_CLASS_ID,
    )
    assert outsider.status_code == 201, outsider.text
    refused = _make_public(client, outsider.json()["csrf_token"], foreign_id)
    assert refused.status_code == 404, refused.text
    client.cookies.clear()
    _, owner_csrf = login(client, "bowen")
    assert client.get(f"/api/v1/agents/{foreign_id}").json()["visibility"] == "private"
