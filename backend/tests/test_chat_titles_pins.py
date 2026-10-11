from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.db import Database
from app.modules.workspace.models import Conversation
from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_mayaform_team_conversations import _create, _make_agent_version, _team
from tests.test_mayaform_teams import MAYA_ID, _headers


def _patch(client: TestClient, csrf: str, chat_id: str, body: dict[str, Any]) -> Any:
    return client.patch(f"/api/v1/conversations/{chat_id}", headers=_headers(csrf), json=body)


def _history(client: TestClient) -> list[str]:
    return [item["id"] for item in client.get("/api/v1/conversations").json()]


def test_owner_renames_and_pins_a_chat_without_touching_its_turns(
    client: TestClient, database: Database
) -> None:
    team, versions, csrf = _team(client, database)
    older = _create(client, csrf, {"kind": "agent", "version_id": versions[0]})
    newer = _create(client, csrf, {"kind": "team", "team_id": team["id"]})
    assert older["title"] is None and older["pinned_at"] is None
    assert _history(client) == [newer["id"], older["id"]]

    renamed = _patch(client, csrf, older["id"], {"title": "  Justice notes  "})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Justice notes"
    # A name arranges the owner's history; it is not a Chat turn.
    assert renamed.json()["revision"] == older["revision"]
    assert renamed.json()["turns"] == older["turns"]

    pinned = _patch(client, csrf, older["id"], {"pinned": True})
    assert pinned.status_code == 200, pinned.text
    pinned_at = pinned.json()["pinned_at"]
    assert pinned_at is not None and pinned.json()["title"] == "Justice notes"
    assert _history(client) == [older["id"], newer["id"]]
    # Pinning again keeps the original pin time, so the order holds still.
    assert _patch(client, csrf, older["id"], {"pinned": True}).json()["pinned_at"] == pinned_at

    team_pinned = _patch(client, csrf, newer["id"], {"pinned": True, "title": "Seminar"})
    assert team_pinned.status_code == 200, team_pinned.text
    assert team_pinned.json()["entry_kind"] == "team"
    assert team_pinned.json()["title"] == "Seminar"
    assert _history(client) == [newer["id"], older["id"]]

    unpinned = _patch(client, csrf, newer["id"], {"pinned": False})
    assert unpinned.json()["pinned_at"] is None
    assert _history(client) == [older["id"], newer["id"]]
    cleared = _patch(client, csrf, older["id"], {"title": ""})
    assert cleared.json()["title"] is None
    assert client.get(f"/api/v1/conversations/{older['id']}").json()["title"] is None


def test_only_the_owner_may_rename_and_a_request_must_change_something(
    client: TestClient, database: Database
) -> None:
    _team_view, versions, csrf = _team(client, database)
    chat = _create(client, csrf, {"kind": "agent", "version_id": versions[0]})
    for body in ({}, {"pinned": None}, {"title": "x" * 81}, {"title": "ok", "extra": 1}):
        assert _patch(client, csrf, chat["id"], body).status_code == 400, body
    missing_csrf = client.patch(f"/api/v1/conversations/{chat['id']}", json={"pinned": True})
    assert missing_csrf.status_code in {400, 403}

    _, other_csrf = login(client, "bowen")
    assert _patch(client, other_csrf, chat["id"], {"title": "Mine now"}).status_code == 404
    _, csrf = login(client, "maya")
    deleted = client.delete(f"/api/v1/conversations/{chat['id']}", headers=_headers(csrf))
    assert deleted.status_code == 204
    assert _patch(client, csrf, chat["id"], {"pinned": True}).status_code == 404
    with database.session() as db:
        row = db.get(Conversation, chat["id"])
        assert row is not None and row.title is None and row.pinned_at is None


def test_a_chat_whose_agent_was_deleted_can_still_be_renamed_and_pinned(
    client: TestClient, database: Database
) -> None:
    agent_id, version_id = _make_agent_version(database, owner_id=MAYA_ID, name="Short lived")
    _, csrf = login(client, "maya")
    chat = _create(client, csrf, {"kind": "agent", "version_id": version_id})
    removed = client.delete(
        f"/api/v1/agents/{agent_id}", headers=_headers(csrf, f"delete-agent-{uuid4()}")
    )
    assert removed.status_code == 204, removed.text
    updated = _patch(client, csrf, chat["id"], {"title": "Kept", "pinned": True})
    assert updated.status_code == 200, updated.text
    assert updated.json()["agent"]["deleted"] is True
    assert updated.json()["title"] == "Kept" and updated.json()["pinned_at"] is not None
