from __future__ import annotations

from typing import Any

from app.core.naming import dedup_name
from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_mayaform_teams import (
    COURSE_ID,
    MAYA_ID,
    _headers,
    _make_agent_version,
    _team_payload,
)


def test_dedup_name_free_name_is_kept() -> None:
    assert dedup_name("Zhu Xi", ["Confucius"]) == "Zhu Xi"


def test_dedup_name_adds_one_above_the_highest_suffix() -> None:
    assert dedup_name("Zhu Xi", ["zhu xi"]) == "Zhu Xi-2"
    assert dedup_name("Zhu Xi", ["Zhu Xi", "Zhu Xi-2"]) == "Zhu Xi-3"
    assert dedup_name("Zhu Xi", ["Zhu Xi", "Zhu Xi-5"]) == "Zhu Xi-6"
    assert dedup_name("Zhu Xi-2", ["Zhu Xi", "Zhu Xi-2"]) == "Zhu Xi-3"


def test_dedup_filename_keeps_extension() -> None:
    assert dedup_name("RAG_总知识库.md", ["RAG_总知识库.md"], keep_extension=True) == (
        "RAG_总知识库-2.md"
    )
    assert dedup_name("notes.md", ["notes.md", "notes-2.md"], keep_extension=True) == "notes-3.md"
    assert dedup_name("notes.md", ["notes.txt"], keep_extension=True) == "notes.md"


def test_agent_in_live_team_is_detected_and_released_when_team_is_deleted(
    client: TestClient, database: Any
) -> None:
    from app.modules.agents.router import _agent_in_live_team

    _, csrf = login(client, "maya")
    first = _make_agent_version(database, owner_id=MAYA_ID, name="Guard A", visibility="public")
    second = _make_agent_version(database, owner_id=MAYA_ID, name="Guard B", visibility="public")
    loose = _make_agent_version(database, owner_id=MAYA_ID, name="Guard C", visibility="public")
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, "cascade-team-guard-create-01"),
        json=_team_payload([first[1], second[1]], visibility="public"),
    )
    assert created.status_code == 201, created.text
    with database.session() as db:
        assert _agent_in_live_team(db, first[0])
        assert not _agent_in_live_team(db, loose[0])
    deleted = client.delete(
        f"/api/v1/teams/{created.json()['id']}",
        headers=_headers(csrf, "cascade-team-guard-delete-01"),
    )
    assert deleted.status_code == 204
    with database.session() as db:
        assert not _agent_in_live_team(db, first[0])
