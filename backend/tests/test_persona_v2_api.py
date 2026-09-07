"""API seam for creating, confirming and publishing a five-section Persona."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import login
from tests.persona_v2_fixtures import persona_v2_markdown
from tests.test_wave4_persona_persistence import GROUP_DEMO_ID, _headers


def _create_agent(client: TestClient, csrf: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/agents",
        headers=_headers(csrf, **{"Idempotency-Key": "persona-v2-api-create-001"}),
        json={"name": "River Keeper", "description": "V2 Persona API fixture"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_five_section_persona_compiles_confirms_and_publishes(
    client: TestClient,
) -> None:
    _user, csrf = login(client, "bowen")
    agent = _create_agent(client, csrf)
    version_id = agent["versions"][0]["id"]
    avatar = agent["versions"][0]["avatar_config"]
    source = persona_v2_markdown()

    updated = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={
            "expected_revision": 0,
            "agent_md": source,
            "avatar_config": avatar,
        },
    )
    assert updated.status_code == 200, updated.text

    uploaded = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "persona-v2-api-upload-001"}),
        data={"target_agent_version_id": version_id, "expected_revision": "1"},
        files={"file": ("publish-v2.md", b"# Evidence\n\nBounded evidence.", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text

    compiled = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/compile",
        headers=_headers(csrf),
        json={"expected_revision": 2},
    )
    assert compiled.status_code == 200, compiled.text
    compiled_body = compiled.json()
    assert compiled_body["compiled"] is True
    assert compiled_body["compiler_version"] == "persona_template_v2"
    assert compiled_body["persona_spec"]["schema_version"] == "persona_spec_v2"
    assert "debate_strategy" not in compiled_body["persona_spec"]
    assert "boundaries" not in compiled_body["persona_spec"]

    confirmed = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/confirm",
        headers=_headers(csrf),
        json={
            "expected_revision": 2,
            "raw_agent_md_hash": compiled_body["raw_agent_md_hash"],
            "persona_spec_hash": compiled_body["persona_spec_hash"],
            "compiler_version": "persona_template_v2",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["persona_confirmed"] is True

    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": "persona-v2-api-publish-001"}),
        json={"expected_revision": 2},
    )
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["persona_confirmed"] is True
    assert body["persona_spec"]["schema_version"] == "persona_spec_v2"
    assert body["persona_compiler_version"] == "persona_template_v2"
