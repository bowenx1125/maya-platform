"""A teacher joins a group to see it as its students do."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_auth_self_registration import register

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
DEMO_GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
ORIGIN = {"Origin": "http://testserver"}


def _membership(group_id: str = DEMO_GROUP_ID) -> str:
    return f"/api/v1/groups/{group_id}/membership"


def test_joining_and_leaving_are_idempotent(client: TestClient) -> None:
    _payload, csrf = login(client)
    headers = {**ORIGIN, "X-CSRF-Token": csrf}
    membership = _membership()

    # Repeating either direction is not an error: the button reflects a state,
    # not a queue of actions.
    assert client.post(membership, headers=headers).status_code == 200
    assert client.post(membership, headers=headers).status_code == 200
    assert client.delete(membership, headers=headers).status_code == 204
    assert client.delete(membership, headers=headers).status_code == 204


def test_a_teacher_sees_groups_the_students_made(client: TestClient, app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    with TestClient(app) as student:
        assert register(student, group_name="Team Aurora").status_code == 201
    with TestClient(app) as teacher:
        login(teacher)
        groups = teacher.get(f"/api/v1/courses/{COURSE_ID}/groups").json()
        names = {group["name"] for group in groups}
        assert {"Demo Group", "Team Aurora"} <= names


def test_a_student_cannot_join_a_group_it_did_not_choose(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    with TestClient(app) as student:
        payload = register(student, group_name="Team Aurora").json()
        response = student.post(
            _membership(),
            headers={**ORIGIN, "X-CSRF-Token": payload["csrf_token"]},
        )
        # 403 rather than 404: the group is legitimately visible to them, it is
        # simply not theirs to join this way.
        assert response.status_code == 403


def test_student_drafts_open_only_after_the_teacher_joins(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    documents = f"/api/v1/groups/{DEMO_GROUP_ID}/knowledge-documents"
    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        headers = {**ORIGIN, "X-CSRF-Token": csrf}

        # Outside the group, the teacher view stays a summary: unfinished
        # student work is not visible from it.
        assert teacher.get(documents).status_code == 404

        assert teacher.post(_membership(), headers=headers).status_code == 200
        assert teacher.get(documents).status_code == 200

        # Leaving closes it again, so the visit is a deliberate, reversible act.
        assert teacher.delete(_membership(), headers=headers).status_code == 204
        assert teacher.get(documents).status_code == 404


def test_the_whole_workspace_opens_and_closes_with_the_visit(app_factory: Any) -> None:
    """One rule, checked across the surfaces a group workspace is made of.

    A draft agent is the sharpest case: it is invisible from the teacher view
    by design, so seeing it is only explicable by the membership row.
    """

    app, _database, _settings = app_factory()
    with TestClient(app) as student:
        payload = register(student, group_name="Team Aurora").json()
        group_id = payload["user"]["groups"][0]["group_id"]
        agent = student.post(
            f"/api/v1/groups/{group_id}/agents",
            json={"name": "Aurora", "visibility": "public"},
            headers={
                **ORIGIN,
                "X-CSRF-Token": payload["csrf_token"],
                "Idempotency-Key": "teacher-visit-workspace-key",
            },
        ).json()
    version_id = agent["current_draft_version_id"]

    surfaces = [
        f"/api/v1/agents/{agent['id']}",
        f"/api/v1/agent-versions/{version_id}",
        f"/api/v1/groups/{group_id}/knowledge-documents",
    ]
    # A course teacher lists the group's shared voices read-only with or
    # without entering (owner decision 2026-10-23).
    voices = f"/api/v1/groups/{group_id}/voice-profiles"
    listing = f"/api/v1/groups/{group_id}/agents"

    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        headers = {**ORIGIN, "X-CSRF-Token": csrf}
        membership = _membership(group_id)

        # The teacher view lists published work, so a group holding nothing but
        # a draft looks empty from outside and its parts are simply not there.
        assert teacher.get(listing).json() == []
        for url in surfaces:
            assert teacher.get(url).status_code == 404, url
        assert teacher.get(voices).status_code == 200

        assert teacher.post(membership, headers=headers).status_code == 200
        assert [row["id"] for row in teacher.get(listing).json()] == [agent["id"]]
        for url in surfaces:
            assert teacher.get(url).status_code == 200, url

        assert teacher.delete(membership, headers=headers).status_code == 204
        assert teacher.get(listing).json() == []
        for url in surfaces:
            assert teacher.get(url).status_code == 404, url
