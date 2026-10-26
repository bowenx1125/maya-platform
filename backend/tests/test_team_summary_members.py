from __future__ import annotations

import json
from typing import Any

from app.core.models import AgentVersion
from fastapi.testclient import TestClient
from sqlalchemy import event

from tests.conftest import login
from tests.test_mayaform_teams import COURSE_ID, MAYA_ID, _headers, _make_agent_version

THEMES = ["warm_sand", "cool_slate", "purple", "default", "mint"]


def _seed_agents(database: Any, count: int, prefix: str) -> list[tuple[str, str]]:
    made = []
    for index in range(count):
        agent_id, version_id = _make_agent_version(
            database, owner_id=MAYA_ID, name=f"{prefix} {index}", visibility="public"
        )
        with database.session() as db:
            version = db.get(AgentVersion, version_id)
            assert version is not None
            version.avatar_config_json = json.dumps({"material_theme": THEMES[index % len(THEMES)]})
            db.commit()
        made.append((agent_id, version_id))
    return made


def _create(
    client: TestClient, csrf: str, agents: list[tuple[str, str]], leader: int, key: str
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, key),
        json={
            "display_name": f"Faces {key}",
            "visibility": "public",
            "members": [
                {"agent_version_id": version, "is_leader": index == leader, "position": index}
                for index, (_, version) in enumerate(agents)
            ],
            "shared_knowledge_set_ids": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_members_leader_first_capped_at_four(client: TestClient, database: Any) -> None:
    _, csrf = login(client, "maya")
    agents = _seed_agents(database, 5, "Face")
    team = _create(client, csrf, agents, leader=2, key="members-faces-team-0001")
    expected = [
        {"agent_id": agents[2][0], "material_theme": THEMES[2], "is_leader": True},
        {"agent_id": agents[0][0], "material_theme": THEMES[0], "is_leader": False},
        {"agent_id": agents[1][0], "material_theme": THEMES[1], "is_leader": False},
        {"agent_id": agents[3][0], "material_theme": THEMES[3], "is_leader": False},
    ]
    # Detail keeps its full member list.
    assert len(team["members"]) == 5

    listed = client.get(f"/api/v1/courses/{COURSE_ID}/teams", headers=_headers(csrf))
    assert listed.status_code == 200
    row = next(item for item in listed.json() if item["id"] == team["id"])
    assert row["members"] == expected
    assert row["member_count"] == 5

    _, student_csrf = login(client, "bowen")
    seen = client.get(f"/api/v1/courses/{COURSE_ID}/teams", headers=_headers(student_csrf))
    row = next(item for item in seen.json() if item["id"] == team["id"])
    assert row["members"] == expected


def test_missing_theme_is_null(client: TestClient, database: Any) -> None:
    _, csrf = login(client, "maya")
    first = _make_agent_version(database, owner_id=MAYA_ID, name="Bare A", visibility="public")
    second = _make_agent_version(database, owner_id=MAYA_ID, name="Bare B", visibility="public")
    team = _create(client, csrf, [first, second], leader=1, key="members-bare-team-0001")
    listed = client.get(f"/api/v1/courses/{COURSE_ID}/teams", headers=_headers(csrf)).json()
    row = next(item for item in listed if item["id"] == team["id"])
    assert row["members"] == [
        {"agent_id": second[0], "material_theme": None, "is_leader": True},
        {"agent_id": first[0], "material_theme": None, "is_leader": False},
    ]


def _member_queries(database: Any, client: TestClient, csrf: str) -> tuple[int, int]:
    seen = [0]

    def tick(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        if "team_version_members" in statement:
            seen[0] += 1

    event.listen(database.engine, "before_cursor_execute", tick)
    try:
        response = client.get(f"/api/v1/courses/{COURSE_ID}/teams", headers=_headers(csrf))
    finally:
        event.remove(database.engine, "before_cursor_execute", tick)
    assert response.status_code == 200
    return seen[0], len(response.json())


def test_member_load_is_one_query_for_any_number_of_teams(
    client: TestClient, database: Any
) -> None:
    _, csrf = login(client, "maya")
    agents = _seed_agents(database, 2, "Batch")
    _create(client, csrf, agents, leader=0, key="members-batch-team-0001")
    one, teams_before = _member_queries(database, client, csrf)
    for index in range(3):
        more = _seed_agents(database, 2, f"Batch{index}")
        _create(client, csrf, more, leader=1, key=f"members-batch-team-10{index}x")
    many, teams_after = _member_queries(database, client, csrf)
    assert teams_after == teams_before + 3
    assert one == 1
    assert many == 1
