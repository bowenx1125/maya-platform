"""A teacher who enters a group sees its members, results and recent work."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_mayaform_teams import BOWEN_ID, _headers
from tests.test_teacher_observer import _group_with_private_work


def test_an_entered_teacher_reads_the_groups_overview(client: TestClient, database: Any) -> None:
    work = _group_with_private_work(client, database)
    overview = f"/api/v1/groups/{work['group']}/overview"
    membership = f"/api/v1/groups/{work['group']}/membership"

    # A member of the group cannot read it: the overview is the teacher's.
    assert client.get(overview).status_code == 404

    _, csrf = login(client, "maya")
    assert client.get(overview).status_code == 404
    assert client.post(membership, headers=_headers(csrf)).status_code == 200

    response = client.get(overview)
    assert response.status_code == 200, response.text
    payload = response.json()
    [member] = payload["members"]
    assert member["user_id"] == BOWEN_ID
    assert sorted(agent["name"] for agent in member["agents"]) == [
        "Quiet voice A",
        "Quiet voice B",
    ]
    assert {agent["visibility"] for agent in member["agents"]} == {"private"}
    assert [team["id"] for team in member["teams"]] == [work["team"]]
    assert (member["rag_count"], member["voice_count"]) == (1, 0)
    assert payload["results"] == []

    kinds = [event["kind"] for event in payload["activity"]]
    assert kinds.count("agent_created") == 2
    assert {"team_created", "rag_added"} <= set(kinds)
    assert {event["user_id"] for event in payload["activity"]} == {BOWEN_ID}
    assert {event["display_name"] for event in payload["activity"]} == {member["display_name"]}
    times = [event["at"] for event in payload["activity"]]
    assert times == sorted(times, reverse=True)

    # Leaving the group closes it again.
    assert client.delete(membership, headers=_headers(csrf)).status_code == 204
    assert client.get(overview).status_code == 404
