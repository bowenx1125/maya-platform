"""The Agent list carries what a card shows, so a page needs no versions reads."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.core.models import AgentVersion
from app.modules.demo_baseline.service import ensure_demo_baseline
from sqlalchemy import select

from tests.conftest import login

GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


def _headers(csrf: str) -> dict[str, str]:
    return {
        "Origin": "http://testserver",
        "X-CSRF-Token": csrf,
        "Idempotency-Key": str(uuid4()),
    }


def test_published_and_draft_cards_carry_label_and_theme(
    app_bundle: Any, client: Any, database: Any
) -> None:
    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    _, csrf = login(client, "bowen")
    created = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents", headers=_headers(csrf), json={"name": "Card Draft"}
    )
    assert created.status_code == 201, created.text
    draft_id = created.json()["id"]
    with database.session() as db:
        draft = db.scalar(select(AgentVersion).where(AgentVersion.agent_id == draft_id))
        assert draft is not None
        draft.avatar_config_json = json.dumps({"material_theme": "civic olive"})
        db.commit()

    listed = client.get(f"/api/v1/groups/{GROUP_ID}/agents")
    assert listed.status_code == 200, listed.text
    cards = {item["name"]: item for item in listed.json()}

    # A published Agent: the published label and its avatar theme.
    published = next(item for item in cards.values() if item["current_published_version_id"])
    versions = client.get(f"/api/v1/agents/{published['id']}/versions").json()
    current = next(v for v in versions if v["id"] == published["current_published_version_id"])
    assert published["card_version_label"] == published["current_version_label"]
    assert published["card_version_label"] == current["version_label"]
    assert published["card_material_theme"] == (current["avatar_config"] or {}).get(
        "material_theme"
    )

    # A draft-only Agent: the draft's label and theme.
    card = cards["Card Draft"]
    assert card["current_published_version_id"] is None
    assert card["card_version_label"] is not None
    assert card["card_material_theme"] == "civic olive"


def test_card_fields_keep_the_list_cost_per_agent_small(
    app_bundle: Any, client: Any, database: Any
) -> None:
    from sqlalchemy import event

    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    _, csrf = login(client, "bowen")

    def count_list() -> int:
        statements: list[str] = []

        def record(*_args: Any) -> None:
            statements.append("q")

        event.listen(database.engine, "after_cursor_execute", record)
        try:
            assert client.get(f"/api/v1/groups/{GROUP_ID}/agents").status_code == 200
        finally:
            event.remove(database.engine, "after_cursor_execute", record)
        return len(statements)

    before = count_list()
    for index in range(3):
        response = client.post(
            f"/api/v1/groups/{GROUP_ID}/agents",
            headers=_headers(csrf),
            json={"name": f"Card {index}"},
        )
        assert response.status_code == 201, response.text
    after = count_list()
    # Draft cards read their draft row each (as before this change); the new
    # card fields add nothing per Agent beyond that.
    assert after - before <= 3 * 4, (before, after)
