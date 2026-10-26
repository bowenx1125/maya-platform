from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.models import Course, CourseMember
from app.modules.workspace.models import Conversation
from fastapi.testclient import TestClient

from tests.test_mayaform_team_conversations import _create, _make_agent_version, _team
from tests.test_mayaform_teams import BOWEN_ID, COURSE_ID, MAYA_ID, _headers

OTHER_COURSE = str(uuid4())


def _ids(client: TestClient, query: str = "") -> list[str]:
    response = client.get(f"/api/v1/conversations{query}")
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()]


def _seed(client: TestClient, database: Database) -> dict[str, str]:
    team, versions, csrf = _team(client, database)
    made = {
        "agent": _create(client, csrf, {"kind": "agent", "version_id": versions[0]})["id"],
        "team": _create(client, csrf, {"kind": "team", "team_id": team["id"]})["id"],
        "maya_team": _create(client, csrf, {"kind": "maya_team", "team_id": team["id"]})["id"],
    }
    with database.session() as db:
        db.add(
            Course(
                id=OTHER_COURSE,
                code=f"other-{OTHER_COURSE[:8]}",
                name="Other",
                created_at=datetime.now(UTC),
            )
        )
        db.flush()
        db.add(
            CourseMember(
                course_id=OTHER_COURSE,
                user_id=MAYA_ID,
                role="teacher",
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
    other_version = _make_agent_version(
        database,
        owner_id=MAYA_ID,
        name="Other course agent",
        visibility="public",
        course_id=OTHER_COURSE,
    )[1]
    made["other_agent"] = _create(client, csrf, {"kind": "agent", "version_id": other_version})[
        "id"
    ]
    withdrawn = _create(client, csrf, {"kind": "agent", "version_id": versions[1]})["id"]
    with database.session() as db:
        row = db.get(Conversation, withdrawn)
        assert row is not None
        row.withdrawn_at = datetime.now(UTC)
        db.commit()
    made["withdrawn"] = withdrawn
    return made


def test_filters_every_combination(client: TestClient, database: Database) -> None:
    made = _seed(client, database)
    everything = _ids(client)
    assert made["withdrawn"] not in everything
    assert {made["agent"], made["team"], made["maya_team"], made["other_agent"]} <= set(everything)

    def kept(query: str) -> list[str]:
        listed = _ids(client, query)
        # Same order as the unfiltered list; withdrawn stays out.
        assert listed == [item for item in everything if item in set(listed)]
        assert made["withdrawn"] not in listed
        return listed

    agents = kept("?entry_kind=agent")
    assert made["agent"] in agents and made["other_agent"] in agents
    assert made["team"] not in agents and made["maya_team"] not in agents

    teams = kept("?entry_kind=team")
    assert made["team"] in teams and made["maya_team"] in teams
    assert made["agent"] not in teams and made["other_agent"] not in teams

    course = kept(f"?course_id={COURSE_ID}")
    assert {made["agent"], made["team"], made["maya_team"]} <= set(course)
    assert made["other_agent"] not in course

    other = kept(f"?course_id={OTHER_COURSE}")
    assert other == [made["other_agent"]]

    assert kept(f"?entry_kind=agent&course_id={COURSE_ID}").count(made["agent"]) == 1
    assert made["other_agent"] not in kept(f"?entry_kind=agent&course_id={COURSE_ID}")
    assert kept(f"?entry_kind=team&course_id={OTHER_COURSE}") == []
    assert kept(f"?entry_kind=agent&course_id={OTHER_COURSE}") == [made["other_agent"]]
    assert set(kept(f"?entry_kind=team&course_id={COURSE_ID}")) >= {made["team"], made["maya_team"]}


def test_other_users_and_foreign_courses_stay_out(client: TestClient, database: Database) -> None:
    made = _seed(client, database)
    from tests.conftest import login

    login(client, "bowen")
    for query in ("", f"?course_id={COURSE_ID}", f"?course_id={OTHER_COURSE}", "?entry_kind=team"):
        listed = _ids(client, query)
        assert not set(made.values()) & set(listed)
    # A course the caller is not in lists nothing rather than an error.
    assert _ids(client, f"?course_id={OTHER_COURSE}") == []
    assert BOWEN_ID


@pytest.mark.parametrize(
    "query",
    [
        "?entry_kind=maya_team",
        "?entry_kind=Agent",
        "?entry_kind=",
        "?course_id=nope",
        "?course_id=",
    ],
)
def test_invalid_values_are_422(client: TestClient, database: Database, query: str) -> None:
    from tests.conftest import login

    _, csrf = login(client, "maya")
    response = client.get(f"/api/v1/conversations{query}", headers=_headers(csrf))
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "conversation_filter_invalid"
