from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.models import TeacherGroupAccess, User
from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_mayaform_teams import (
    BOWEN_ID,
    COURSE_ID,
    GROUP_ID,
    MAYA_ID,
    _headers,
    _make_agent_version,
    _team_payload,
)


def _name(database: Any, user_id: str) -> str:
    with database.session() as db:
        user = db.get(User, user_id)
        assert user is not None
        return user.display_name


def _listed(client: TestClient, csrf: str, team_id: str, query: str = "") -> dict[str, Any]:
    response = client.get(f"/api/v1/courses/{COURSE_ID}/teams{query}", headers=_headers(csrf))
    assert response.status_code == 200, response.text
    rows = [row for row in response.json() if row["id"] == team_id]
    assert len(rows) == 1, response.json()
    return rows[0]


def _enter(database: Any) -> None:
    with database.session() as db:
        db.add(TeacherGroupAccess(group_id=GROUP_ID, user_id=MAYA_ID, created_at=datetime.now(UTC)))
        db.commit()


def test_owner_and_non_owner_on_a_public_teacher_team(client: TestClient, database: Any) -> None:
    _, csrf = login(client, "maya")
    first = _make_agent_version(database, owner_id=MAYA_ID, name="Edit A", visibility="public")
    second = _make_agent_version(database, owner_id=MAYA_ID, name="Edit B", visibility="public")
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, "d-summary-owner-team-0001"),
        json=_team_payload([first[1], second[1]], visibility="public"),
    )
    assert created.status_code == 201, created.text
    team = created.json()
    assert team["can_delete"] is True
    assert team["last_edited_by_name"] == _name(database, MAYA_ID)

    owner_row = _listed(client, csrf, team["id"])
    assert owner_row["can_edit"] is True
    assert owner_row["can_delete"] is True
    assert owner_row["last_edited_by_name"] == _name(database, MAYA_ID)
    assert owner_row["updated_at"] == team["updated_at"]

    _, student_csrf = login(client, "bowen")
    student_row = _listed(client, student_csrf, team["id"])
    assert student_row["can_edit"] is False
    assert student_row["can_delete"] is False
    assert student_row["last_edited_by_name"] == _name(database, MAYA_ID)
    refused = client.delete(
        f"/api/v1/teams/{team['id']}", headers=_headers(student_csrf, "d-summary-del-0001")
    )
    assert refused.status_code == 404

    _, csrf = login(client, "maya")
    assert (
        client.delete(
            f"/api/v1/teams/{team['id']}", headers=_headers(csrf, "d-summary-del-0002")
        ).status_code
        == 204
    )


def test_visiting_teacher_cannot_delete_a_student_group_team(
    client: TestClient, database: Any
) -> None:
    _, student_csrf = login(client, "bowen")
    first = _make_agent_version(
        database, owner_id=BOWEN_ID, name="Group A", visibility="public", group_id=GROUP_ID
    )
    second = _make_agent_version(
        database, owner_id=BOWEN_ID, name="Group B", visibility="public", group_id=GROUP_ID
    )
    payload = _team_payload([first[1], second[1]], visibility="private")
    payload["group_id"] = GROUP_ID
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(student_csrf, "d-summary-group-team-0001"),
        json=payload,
    )
    assert created.status_code == 201, created.text
    team = created.json()
    owner_row = _listed(client, student_csrf, team["id"], f"?group_id={GROUP_ID}")
    assert owner_row["can_delete"] is True
    assert owner_row["last_edited_by_name"] == _name(database, BOWEN_ID)

    _enter(database)
    _, teacher_csrf = login(client, "maya")
    visiting = _listed(client, teacher_csrf, team["id"], f"?group_id={GROUP_ID}")
    assert visiting["can_edit"] is False
    assert visiting["can_delete"] is False
    assert visiting["last_edited_by_name"] == _name(database, BOWEN_ID)
    refused = client.delete(
        f"/api/v1/teams/{team['id']}", headers=_headers(teacher_csrf, "d-summary-del-0003")
    )
    assert refused.status_code == 404


def test_visiting_teacher_owns_a_group_team_only_while_entered(
    client: TestClient, database: Any
) -> None:
    first = _make_agent_version(
        database, owner_id=BOWEN_ID, name="Visit A", visibility="public", group_id=GROUP_ID
    )
    second = _make_agent_version(
        database, owner_id=BOWEN_ID, name="Visit B", visibility="public", group_id=GROUP_ID
    )
    _enter(database)
    _, csrf = login(client, "maya")
    payload = _team_payload([first[1], second[1]], visibility="public")
    payload["group_id"] = GROUP_ID
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, "d-summary-visit-team-0001"),
        json=payload,
    )
    assert created.status_code == 201, created.text
    team = created.json()
    assert _listed(client, csrf, team["id"], f"?group_id={GROUP_ID}")["can_delete"] is True

    with database.session() as db:
        db.query(TeacherGroupAccess).filter_by(group_id=GROUP_ID, user_id=MAYA_ID).delete()
        db.commit()
    detail = client.get(f"/api/v1/teams/{team['id']}", headers=_headers(csrf))
    if detail.status_code == 200:
        assert detail.json()["can_delete"] is False
    assert (
        client.delete(
            f"/api/v1/teams/{team['id']}", headers=_headers(csrf, "d-summary-del-0004")
        ).status_code
        == 404
    )
