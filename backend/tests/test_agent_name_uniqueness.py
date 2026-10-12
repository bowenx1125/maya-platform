"""Workspace Agent names are serialized without rewriting historical duplicates."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import Agent, AgentVersion
from app.modules.agents.router import create_agent, update_agent_draft
from app.modules.agents.schemas import AgentCreateRequest, UpdateAgentDraftRequest
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
def test_create_rejects_normalized_duplicate_and_releases_idempotency_claim(client, name):
    _, csrf = login(client, "bowen")
    created = _create(client, csrf, "Bowen")
    assert created.status_code == 201
    key = str(uuid4())
    rejected = _create(client, csrf, name, key)
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "agent_name_conflict"
    assert "delete" in rejected.json()["message"]
    deleted = client.delete(f"/api/v1/agents/{created.json()['id']}", headers=_headers(csrf))
    assert deleted.status_code == 204, deleted.text
    retried = _create(client, csrf, name, key)
    assert retried.status_code == 201, retried.text


@pytest.mark.parametrize("upload", [False, True])
def test_markdown_conflict_preserves_both_name_and_draft(client, upload):
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
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "agent_name_conflict"
    with client.app.state.database.session() as db:
        saved = db.get(AgentVersion, version["id"])
        assert saved.revision == version["revision"]
        assert saved.agent_md == version["agent_md"]
        assert db.get(Agent, agent["id"]).name == "Original"
        assert db.get(Agent, agent["id"]).metadata_revision == 0


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
    settings = client.app.state.settings
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
            result = update_agent_draft(
                UUID(agent["versions"][0]["id"]),
                UpdateAgentDraftRequest(expected_revision=0, agent_md=f"# {name}"),
                context=context,
                db=db,
                settings=settings,
            )
            db.commit()
            return result

        return operation

    a = create if operations.startswith("create") else save(first, "Concurrent Name")
    b = create if operations.endswith("create") else save(second, "ＣＯＮＣＵＲＲＥＮＴ NAME")
    results = _run_race(database, a, b)
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(errors) == 1, results
    assert isinstance(errors[0], PlatformError), results
    assert errors[0].code == "agent_name_conflict", results
    with database.session() as db:
        names = db.scalars(
            select(Agent.name).where(Agent.group_id == GROUP_ID, Agent.deleted_at.is_(None))
        ).all()
        from app.modules.agents.router import _agent_name_key

        assert sum(_agent_name_key(name) == "concurrent name" for name in names) == 1
