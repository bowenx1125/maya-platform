"""Agent rename through PATCH updateAgentMetadata."""

from __future__ import annotations

from typing import Any

from app.core.models import AgentVersion
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.test_wave3_agent_metadata import _create_agent, _headers


def _patch(client: TestClient, csrf: str, agent_id: str, body: dict[str, Any]) -> Any:
    return client.patch(f"/api/v1/agents/{agent_id}", headers=_headers(csrf), json=body)


def test_rename_trims_bumps_revision_and_keeps_description(
    client: TestClient, database: Any
) -> None:
    _user, csrf = login(client, "bowen")
    agent = _create_agent(client, csrf, "rename-ok-000001", description="Keep me")
    renamed = _patch(
        client, csrf, agent["id"], {"expected_metadata_revision": 0, "name": "  Zhu Xi  "}
    )
    assert renamed.status_code == 200, renamed.text
    body = renamed.json()
    assert body["name"] == "Zhu Xi"
    assert body["description"] == "Keep me"
    assert body["metadata_revision"] == 1
    assert client.get(f"/api/v1/agents/{agent['id']}").json()["name"] == "Zhu Xi"
    # No new version is published by a rename.
    with database.session() as session:
        versions = session.scalars(
            select(AgentVersion).where(AgentVersion.agent_id == agent["id"])
        ).all()
    assert len(versions) == 1


def test_rename_validation_codes(client: TestClient) -> None:
    _user, csrf = login(client, "bowen")
    agent = _create_agent(client, csrf, "rename-bad-000001")
    empty = _patch(client, csrf, agent["id"], {"expected_metadata_revision": 0, "name": "   "})
    assert empty.status_code == 422, empty.text
    assert empty.json()["code"] == "agent_name_required"
    long = _patch(client, csrf, agent["id"], {"expected_metadata_revision": 0, "name": "x" * 121})
    assert long.status_code == 422, long.text
    assert long.json()["code"] == "agent_name_too_long"
    exact = _patch(client, csrf, agent["id"], {"expected_metadata_revision": 0, "name": "y" * 120})
    assert exact.status_code == 200, exact.text
    assert exact.json()["name"] == "y" * 120


def test_create_uses_the_same_name_codes(client: TestClient) -> None:
    _user, csrf = login(client, "bowen")
    for key, name, code in (
        ("rename-create-empty1", "  ", "agent_name_required"),
        ("rename-create-long01", "z" * 121, "agent_name_too_long"),
    ):
        response = client.post(
            "/api/v1/groups/7813f937-902c-5534-bfb2-ad773a43aeda/agents",
            headers=_headers(csrf, **{"Idempotency-Key": key}),
            json={"name": name, "visibility": "public"},
        )
        assert response.status_code == 422, response.text
        assert response.json()["code"] == code


def test_rename_collision_gets_suffix_and_own_name_is_noop(client: TestClient) -> None:
    _user, csrf = login(client, "bowen")
    _create_agent(client, csrf, "rename-taken-00001", name="Laozi")
    agent = _create_agent(client, csrf, "rename-mover-00001", name="Mencius")
    taken = _patch(client, csrf, agent["id"], {"expected_metadata_revision": 0, "name": "laozi"})
    assert taken.status_code == 200, taken.text
    assert taken.json()["name"] == "laozi-2"
    same = _patch(client, csrf, agent["id"], {"expected_metadata_revision": 1, "name": "LAOZI-2"})
    assert same.status_code == 200, same.text
    assert same.json()["name"] == "LAOZI-2"
    assert same.json()["metadata_revision"] == 2


def test_rename_stale_revision_and_non_editor(client: TestClient) -> None:
    _user, csrf = login(client, "bowen")
    agent = _create_agent(client, csrf, "rename-stale-00001")
    assert (
        _patch(
            client, csrf, agent["id"], {"expected_metadata_revision": 0, "name": "A"}
        ).status_code
        == 200
    )
    stale = _patch(client, csrf, agent["id"], {"expected_metadata_revision": 0, "name": "B"})
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "stale_metadata_revision"
    _teacher, teacher_csrf = login(client, "maya")
    denied = _patch(
        client, teacher_csrf, agent["id"], {"expected_metadata_revision": 1, "name": "C"}
    )
    assert denied.status_code == 404, denied.text


def test_description_only_update_keeps_name(client: TestClient) -> None:
    _user, csrf = login(client, "bowen")
    agent = _create_agent(client, csrf, "rename-desc-000001", name="Xunzi")
    changed = _patch(
        client, csrf, agent["id"], {"expected_metadata_revision": 0, "description": "New lens"}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["name"] == "Xunzi"
    assert changed.json()["description"] == "New lens"
    null_name = _patch(client, csrf, agent["id"], {"expected_metadata_revision": 1, "name": None})
    assert null_name.status_code == 200, null_name.text
    assert null_name.json()["name"] == "Xunzi"
    assert null_name.json()["description"] == "New lens"
