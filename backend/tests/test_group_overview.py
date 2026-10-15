"""A course teacher sees a group's members, results and recent work.

Entering still reveals private work. Formal attempts do not wait for it.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_mayaform_teams import BOWEN_ID, _headers
from tests.test_teacher_group_visit import COURSE_ID
from tests.test_teacher_observer import _group_with_private_work


def test_an_entered_teacher_reads_the_groups_overview(client: TestClient, database: Any) -> None:
    work = _group_with_private_work(client, database)
    overview = f"/api/v1/groups/{work['group']}/overview"
    membership = f"/api/v1/groups/{work['group']}/membership"

    # A member of the group cannot read it: the overview is the teacher's.
    assert client.get(overview).status_code == 404

    _, csrf = login(client, "maya")
    # Attempts are readable before Enter. Private Agents, Teams and RAG are not.
    closed = client.get(overview)
    assert closed.status_code == 200, closed.text
    [closed_member] = closed.json()["members"]
    assert closed_member["user_id"] == BOWEN_ID
    assert closed_member["agents"] == []
    assert closed_member["teams"] == []
    assert (closed_member["rag_count"], closed_member["voice_count"]) == (0, 0)
    assert closed.json()["results"] == []
    assert closed.json()["activity"] == []

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

    # Leaving hides private work again. The attempt read stays open.
    assert client.delete(membership, headers=_headers(csrf)).status_code == 204
    left = client.get(overview)
    assert left.status_code == 200, left.text
    assert left.json()["members"][0]["agents"] == []
    assert left.json()["activity"] == []


def test_a_teacher_lists_attempts_without_entering_a_group(
    client: TestClient, database: Any
) -> None:
    work = _group_with_private_work(client, database)
    url = f"/api/v1/learning/courses/{COURSE_ID}/assessment-attempts"
    missing = str(uuid4())

    assert client.get(url).status_code == 404

    login(client, "maya")
    listed = client.get(url)
    assert listed.status_code == 200, listed.text
    assert listed.json() == []
    assert client.get(f"{url}?group_id={work['group']}").json() == []
    assert client.get(f"{url}?group_id={missing}").status_code == 404
    assert client.get(f"{url}?attempt_id={missing}").status_code == 404
    assert client.get(f"{url}?conversation_id={missing}").status_code == 404
