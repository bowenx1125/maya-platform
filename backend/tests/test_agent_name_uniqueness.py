"""Workspace Agent names are serialized without rewriting historical duplicates."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.core.models import Agent, AgentVersion
from app.modules.agents.router import create_agent, update_agent_metadata
from app.modules.agents.schemas import AgentCreateRequest, UpdateAgentMetadataRequest
from sqlalchemy import select

from tests.conftest import login, make_foreign_group
from tests.test_wave3_agent_metadata import _context, _run_race

GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


def _headers(csrf, key=None):
    return {
        "Origin": "http://testserver",
        "X-CSRF-Token": csrf,
        "Idempotency-Key": key or str(uuid4()),
    }


def _create(client, csrf, name, key=None):
    return client.post(
        f"/api/v1/groups/{GROUP_ID}/agents", headers=_headers(csrf, key), json={"name": name}
    )


def _seed_agent(database, name, *, deleted=False, group_id=GROUP_ID):
    timestamp = datetime.now(UTC)
    with database.session() as db:
        row = Agent(
            id=str(uuid4()),
            group_id=group_id,
            name=name,
            description="",
            metadata_revision=0,
            status="active",
            created_at=timestamp,
            updated_at=timestamp,
            deleted_at=timestamp if deleted else None,
        )
        db.add(row)
        db.flush()
        return row.id


@pytest.mark.parametrize("name", ["Ｂｏｗｅｎ", "bowen", "  BOWEN  "])
def test_create_with_taken_normalized_name_gets_numeric_suffix(client, name):
    _, csrf = login(client, "bowen")
    created = _create(client, csrf, "Bowen")
    assert created.status_code == 201
    filled = client.patch(
        f"/api/v1/agent-versions/{created.json()['versions'][0]['id']}",
        headers=_headers(csrf),
        json={"expected_revision": 0, "agent_md": "Body"},
    )
    assert filled.status_code == 200, filled.text
    second = _create(client, csrf, name)
    assert second.status_code == 201, second.text
    assert second.json()["name"] == f"{name.strip()}-2"


def test_suffix_continues_after_highest_existing(client):
    _, csrf = login(client, "bowen")
    for _ in range(2):
        agent = _create(client, csrf, "Zhu Xi").json()
        client.patch(
            f"/api/v1/agent-versions/{agent['versions'][0]['id']}",
            headers=_headers(csrf),
            json={"expected_revision": 0, "agent_md": "Body"},
        )
    third = _create(client, csrf, "Zhu Xi")
    assert third.json()["name"] == "Zhu Xi-3"
    explicit = _create(client, csrf, "Zhu Xi-2")
    assert explicit.status_code == 201, explicit.text
    assert explicit.json()["name"] == "Zhu Xi-4"


@pytest.mark.parametrize("upload", [False, True])
def test_agent_md_heading_never_renames_the_agent(client, upload):
    """Owner 2026-11-08: the name is set on its own card, not by AGENT.md."""
    _, csrf = login(client, "bowen")
    assert _create(client, csrf, "Taken Name").status_code == 201
    agent = _create(client, csrf, "Original").json()
    version = agent["versions"][0]
    url = f"/api/v1/agent-versions/{version['id']}"
    if upload:
        response = client.post(
            f"{url}/agent-md/upload",
            headers=_headers(csrf),
            data={"expected_revision": str(version["revision"])},
            files={"file": ("AGENT.md", b"# taken name\nChanged content", "text/markdown")},
        )
    else:
        response = client.patch(
            url,
            headers=_headers(csrf),
            json={
                "expected_revision": version["revision"],
                "agent_md": "# taken name\nChanged content",
            },
        )
    assert response.status_code == 200, response.text
    with client.app.state.database.session() as db:
        saved = db.get(AgentVersion, version["id"])
        assert saved.revision == version["revision"] + 1
        assert saved.agent_md == "# taken name\nChanged content"
        renamed = db.get(Agent, agent["id"])
        assert renamed.name == "Original"
        assert renamed.metadata_revision == 0


def test_rename_to_a_taken_name_gets_a_suffix(client):
    _, csrf = login(client, "bowen")
    assert _create(client, csrf, "Taken Name").status_code == 201
    agent = _create(client, csrf, "Original").json()
    renamed = client.patch(
        f"/api/v1/agents/{agent['id']}",
        headers=_headers(csrf),
        json={"expected_metadata_revision": 0, "name": "taken name"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "taken name-2"


def test_public_heading_owned_by_classmate_does_not_block_new_agent(client):
    """A public sample heading owned by another student must not block save."""
    _, other_csrf = login(client, "kaikai")
    taken = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(other_csrf),
        json={"name": "Zhu Xi", "visibility": "public"},
    )
    if taken.status_code == 404:
        pytest.skip("second student is not a member of the seed group")
    assert taken.status_code == 201, taken.text
    client.cookies.clear()
    _, csrf = login(client, "bowen")
    agent = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(csrf),
        json={"name": "Zhu Xi (Su voice)", "visibility": "public"},
    ).json()
    response = client.patch(
        f"/api/v1/agents/{agent['id']}",
        headers=_headers(csrf),
        json={"expected_metadata_revision": 0, "name": "Zhu Xi"},
    )
    assert response.status_code == 200, response.text
    with client.app.state.database.session() as db:
        assert db.get(Agent, agent["id"]).name == "Zhu Xi-2"


def test_retry_reclaims_own_abandoned_empty_draft_name(client):
    _, csrf = login(client, "bowen")
    first = _create(client, csrf, "Retry Me")
    assert first.status_code == 201
    retried = _create(client, csrf, "retry me")
    assert retried.status_code == 201, retried.text
    with client.app.state.database.session() as db:
        assert db.get(Agent, first.json()["id"]) is None
        assert db.get(Agent, retried.json()["id"]).deleted_at is None


def test_retry_does_not_reclaim_other_visibility_draft(client):
    _, csrf = login(client, "bowen")
    public = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(csrf),
        json={"name": "Scoped", "visibility": "public"},
    ).json()
    private = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(csrf),
        json={"name": "Scoped", "visibility": "private"},
    )
    assert private.status_code == 201, private.text
    with client.app.state.database.session() as db:
        assert db.get(Agent, public["id"]).deleted_at is None


def test_retry_does_not_reclaim_draft_with_content(client):
    _, csrf = login(client, "bowen")
    first = _create(client, csrf, "Has Content").json()
    saved = client.patch(
        f"/api/v1/agent-versions/{first['versions'][0]['id']}",
        headers=_headers(csrf),
        json={"expected_revision": 0, "agent_md": "Body without heading"},
    )
    assert saved.status_code == 200, saved.text
    second = _create(client, csrf, "has content")
    assert second.status_code == 201, second.text
    assert second.json()["name"] == "has content-2"
    with client.app.state.database.session() as db:
        assert db.get(Agent, first["id"]).deleted_at is None


def test_historical_duplicates_are_not_rewritten_and_same_name_save_is_allowed(client):
    _, csrf = login(client, "bowen")
    agent = _create(client, csrf, "Legacy duplicate").json()
    database = client.app.state.database
    old_id = _seed_agent(database, "LEGACY DUPLICATE")
    response = client.patch(
        f"/api/v1/agent-versions/{agent['versions'][0]['id']}",
        headers=_headers(csrf),
        json={"expected_revision": 0, "agent_md": "# Legacy duplicate\nEdited body"},
    )
    assert response.status_code == 200, response.text
    with database.session() as db:
        assert db.get(Agent, old_id).name == "LEGACY DUPLICATE"
        assert db.get(Agent, old_id).deleted_at is None
        assert db.get(Agent, agent["id"]).name == "Legacy duplicate"


def test_deleted_or_other_workspace_names_do_not_block_creation(client):
    _, csrf = login(client, "bowen")
    database = client.app.state.database
    _seed_agent(database, "Available again", deleted=True)
    foreign_group = make_foreign_group(database, "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b")
    _seed_agent(database, "Available again", group_id=foreign_group)
    response = _create(client, csrf, "available again")
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("operations", ["create-create", "save-save", "create-save"])
def test_concurrent_normalized_name_claims_have_one_winner(client, operations):
    user, csrf = login(client, "bowen")
    database = client.app.state.database
    context = _context(database, user["user"]["id"])
    first = _create(client, csrf, "First").json()
    second = _create(client, csrf, "Second").json()

    def create(db):
        return create_agent(
            UUID(GROUP_ID),
            AgentCreateRequest(name="Concurrent Name"),
            idempotency_key=str(uuid4()),
            context=context,
            db=db,
        )

    def save(agent, name):
        def operation(db):
            return update_agent_metadata(
                UUID(agent["id"]),
                UpdateAgentMetadataRequest(expected_metadata_revision=0, name=name),
                _csrf_header="c" * 32,
                context=context,
                db=db,
            )

        return operation

    a = create if operations.startswith("create") else save(first, "Concurrent Name")
    b = create if operations.endswith("create") else save(second, "ＣＯＮＣＵＲＲＥＮＴ NAME")
    results = _run_race(database, a, b)
    errors = [result for result in results if isinstance(result, Exception)]
    # Nobody fails any more: the loser gets "-2" (or, for two creates, may
    # reclaim the winner's still-empty draft). Exactly one live Agent holds
    # the bare normalized name either way (asserted below).
    assert errors == [], results
    with database.session() as db:
        names = db.scalars(
            select(Agent.name).where(Agent.group_id == GROUP_ID, Agent.deleted_at.is_(None))
        ).all()
        from app.modules.agents.router import _agent_name_key

        assert sum(_agent_name_key(name) == "concurrent name" for name in names) == 1
