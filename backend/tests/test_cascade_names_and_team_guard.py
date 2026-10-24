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


def test_agent_in_team_names_the_actors_own_teams_only(client: TestClient, database: Any) -> None:
    from app.modules.agents.router import _live_team_blockers

    from tests.test_mayaform_teams import BOWEN_ID

    _, csrf = login(client, "maya")
    first = _make_agent_version(database, owner_id=MAYA_ID, name="Named A", visibility="public")
    second = _make_agent_version(database, owner_id=MAYA_ID, name="Named B", visibility="public")
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, "cascade-team-named-create-1"),
        json={
            **_team_payload([first[1], second[1]], visibility="public"),
            "display_name": "Ethics circle",
        },
    )
    assert created.status_code == 201, created.text
    team_id = created.json()["id"]
    with database.session() as db:
        own = _live_team_blockers(db, first[0], MAYA_ID)
        assert own == {
            "teams": [{"team_id": team_id, "team_name": "Ethics circle", "group_id": None}],
            "other_team_count": 0,
        }
        assert _live_team_blockers(db, first[0], BOWEN_ID) == {
            "teams": [],
            "other_team_count": 1,
        }
    deleted = client.delete(
        f"/api/v1/agents/{first[0]}",
        headers=_headers(csrf, "cascade-team-named-delete1"),
    )
    assert deleted.status_code == 409, deleted.text
    body = deleted.json()
    assert body["code"] == "agent_in_team"
    assert body["details"]["teams"][0]["team_name"] == "Ethics circle"
