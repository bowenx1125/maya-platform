"""A course teacher uses a student's public Team: read and chat, never edit.

Bug (2026-10-19): ``can_read_team`` listed a student's public Team to the
course's teachers and the Chat opened, but every send was refused as not found
because the Team recheck needed the owner or a student inside the group. The
teacher now chats with it as themselves: members, RAG and Knowledge are still
checked against what the teacher may read.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.models import Group, GroupMember
from app.modules.workspace.models import TeamTurnResult
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login, post_message
from tests.test_mayaform_team_conversations import _create, _make_agent_version
from tests.test_mayaform_teams import BOWEN_ID, COURSE_ID, _headers, _team_payload

KAIKAI_ID = "bc170f51-45fb-5296-a36d-a2edc8f8d315"


def _group_with(database: Database, *user_ids: str) -> str:
    group_id = str(uuid4())
    with database.session() as db:
        db.add(
            Group(
                id=group_id,
                course_id=COURSE_ID,
                name=f"Circle {group_id[:8]}",
                created_at=datetime.now(UTC),
            )
        )
        for user_id in user_ids:
            db.add(
                GroupMember(
                    group_id=group_id,
                    user_id=user_id,
                    role="member",
                    created_at=datetime.now(UTC),
                )
            )
        db.commit()
    return group_id


def _student_public_team(
    client: TestClient,
    database: Database,
    *,
    group_id: str | None,
    shared_set: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    _, csrf = login(client, "bowen")
    versions = [
        _make_agent_version(
            database,
            owner_id=BOWEN_ID,
            name=f"Student voice {index}",
            visibility="public",
            group_id=group_id,
        )[1]
        for index in range(2)
    ]
    payload = _team_payload(versions, visibility="public")
    if group_id is not None:
        payload["group_id"] = group_id
    if shared_set:
        created_set = client.post(
            f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
            headers=_headers(csrf, f"student-private-set-{uuid4()}"),
            json={"display_name": "My own notes"},
        )
        assert created_set.status_code == 201, created_set.text
        payload["shared_knowledge_set_ids"] = [created_set.json()["id"]]
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"student-public-team-{uuid4()}"),
        json=payload,
    )
    assert created.status_code == 201, created.text
    return created.json(), payload, csrf


def _send(client: TestClient, csrf: str, session_id: str, revision: int, text: str) -> Any:
    return post_message(
        client,
        f"/api/v1/conversations/{session_id}/messages",
        headers=_headers(csrf),
        json={"request_id": str(uuid4()), "expected_revision": revision, "message": text},
    )


@pytest.mark.parametrize("in_group", [True, False], ids=["group_team", "personal_team"])
def test_teacher_sends_to_student_public_team_and_cannot_edit(
    client: TestClient, database: Database, in_group: bool
) -> None:
    group_id = _group_with(database, BOWEN_ID) if in_group else None
    team, payload, _student_csrf = _student_public_team(client, database, group_id=group_id)

    _, teacher_csrf = login(client, "maya")
    listed = client.get(f"/api/v1/courses/{COURSE_ID}/teams", headers=_headers(teacher_csrf))
    assert listed.status_code == 200, listed.text
    mine = [item for item in listed.json() if item["id"] == team["id"]]
    assert len(mine) == 1 and mine[0]["can_edit"] is False

    session = _create(client, teacher_csrf, {"kind": "team", "team_id": team["id"]})
    assert session["entry_kind"] == "team"
    assert session["origin"] == "custom_team"
    assert session["can_send"] is True
    reloaded = client.get(f"/api/v1/conversations/{session['id']}")
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["can_send"] is True

    sent = _send(client, teacher_csrf, session["id"], 0, "Hello team")
    assert sent.status_code == 200, sent.text
    turns = sent.json()["turns"]
    assert len(turns) == 1 and turns[0]["state"] in {"ready", "partial"}, turns
    with database.session() as db:
        results = db.scalars(
            select(TeamTurnResult).where(TeamTurnResult.conversation_id == session["id"])
        ).all()
    # One Agent call per member, all answered.
    assert len(results) == 2
    assert {result.state for result in results} == {"ready"}
    streamed = client.post(
        f"/api/v1/conversations/{session['id']}/messages:stream",
        headers={**_headers(teacher_csrf), "Accept": "text/event-stream"},
        json={"request_id": str(uuid4()), "expected_revision": 1, "message": "Hello again"},
    )
    assert streamed.status_code == 200, streamed.text

    # Read and use only: the teacher can neither save a new version nor delete.
    saved = client.put(
        f"/api/v1/teams/{team['id']}",
        headers=_headers(teacher_csrf, f"teacher-edit-student-team-{uuid4()}"),
        json={
            "display_name": "Taken over",
            "visibility": "public",
            "members": payload["members"],
            "shared_knowledge_set_ids": [],
            "expected_metadata_revision": team["metadata_revision"],
        },
    )
    assert saved.status_code == 404, saved.text
    deleted = client.delete(
        f"/api/v1/teams/{team['id']}",
        headers=_headers(teacher_csrf, f"teacher-delete-student-team-{uuid4()}"),
    )
    assert deleted.status_code == 404, deleted.text


def test_teacher_chat_closes_when_the_student_deletes_the_team(
    client: TestClient, database: Database
) -> None:
    group_id = _group_with(database, BOWEN_ID)
    team, _payload, _ = _student_public_team(client, database, group_id=group_id)
    _, teacher_csrf = login(client, "maya")
    session = _create(client, teacher_csrf, {"kind": "team", "team_id": team["id"]})
    assert session["can_send"] is True

    _, student_csrf = login(client, "bowen")
    removed = client.delete(
        f"/api/v1/teams/{team['id']}",
        headers=_headers(student_csrf, f"student-delete-team-{uuid4()}"),
    )
    assert removed.status_code == 204, removed.text

    login(client, "maya")
    closed = client.get(f"/api/v1/conversations/{session['id']}").json()
    assert closed["can_send"] is False
    assert closed["team"]["deleted"] is True


def test_teacher_is_refused_a_student_team_carrying_private_knowledge(
    client: TestClient, database: Database
) -> None:
    """The teacher is checked as themselves: a student's personal (private)
    Knowledge Set on the Team is refused, never borrowed through the owner."""

    team, _payload, _ = _student_public_team(client, database, group_id=None, shared_set=True)
    _, teacher_csrf = login(client, "maya")
    response = client.post(
        "/api/v1/conversations",
        headers=_headers(teacher_csrf),
        json={"entry": {"kind": "team", "team_id": team["id"]}},
    )
    assert response.status_code == 404, response.text


def test_another_student_outside_the_group_still_cannot_use_it(
    client: TestClient, database: Database, caplog: pytest.LogCaptureFixture
) -> None:
    group_id = _group_with(database, BOWEN_ID)
    team, _payload, _ = _student_public_team(client, database, group_id=group_id)
    _, outsider_csrf = login(client, "kaikai")
    response = client.post(
        "/api/v1/conversations",
        headers=_headers(outsider_csrf),
        json={"entry": {"kind": "team", "team_id": team["id"]}},
    )
    assert response.status_code == 404, response.text

    # A student who could open it, then left the group, is refused on send
    # and the refusal is logged with its reason.
    with database.session() as db:
        db.add(
            GroupMember(
                group_id=group_id,
                user_id=KAIKAI_ID,
                role="member",
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
    _, outsider_csrf = login(client, "kaikai")
    session = _create(client, outsider_csrf, {"kind": "team", "team_id": team["id"]})
    with database.session() as db:
        member = db.get(GroupMember, (group_id, KAIKAI_ID))
        assert member is not None
        db.delete(member)
        db.commit()
    with caplog.at_level(logging.WARNING):
        refused = _send(client, outsider_csrf, session["id"], 0, "Still here?")
    assert refused.status_code in {404, 409}, refused.text
    assert "Team chat refused" in caplog.text
    assert "reason=not_in_team_group" in caplog.text
