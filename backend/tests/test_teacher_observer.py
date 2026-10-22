"""A teacher who enters a group reads its private Agents, and only reads them.

The group library is the members' library: an entered teacher browses and
uploads it the way a groupmate does, and does not see another student's
private file.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.models import Group, GroupMember, KnowledgeDocument, StoredFile
from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_mayaform_teams import (
    BOWEN_ID,
    COURSE_ID,
    _headers,
    _make_agent_version,
    _team_payload,
)


def _group_with_private_work(client: TestClient, database: Any) -> dict[str, str]:
    """Bowen's own group: two private Agents, a private Team and a private source."""

    group_id = str(uuid4())
    now = datetime.now(UTC)
    content = "Notes only Bowen chose to keep to himself.\n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    file_id, document_id = str(uuid4()), str(uuid4())
    with database.session() as db:
        db.add(
            Group(id=group_id, course_id=COURSE_ID, name=f"Circle {group_id[:8]}", created_at=now)
        )
        db.add(GroupMember(group_id=group_id, user_id=BOWEN_ID, role="member", created_at=now))
        db.add(
            StoredFile(
                id=file_id,
                kind="markdown",
                relative_path=f"knowledge/{file_id}.md",
                sha256=digest,
                size_bytes=len(content.encode("utf-8")),
                state="active",
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(
            KnowledgeDocument(
                id=document_id,
                group_id=group_id,
                owner_user_id=BOWEN_ID,
                course_id=COURSE_ID,
                ownership_scope="group",
                visibility="private",
                authorization_epoch=0,
                source_filename="private-notes.md",
                stored_file_id=file_id,
                char_count=len(content),
                index_status="ready",
                index_revision=1,
                workspace_state="active",
                content_hash=digest,
                safe_error_code=None,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    first = _make_agent_version(
        database, owner_id=BOWEN_ID, name="Quiet voice A", visibility="private", group_id=group_id
    )
    second = _make_agent_version(
        database, owner_id=BOWEN_ID, name="Quiet voice B", visibility="private", group_id=group_id
    )
    _, bowen_csrf = login(client, "bowen")
    payload = _team_payload([first[1], second[1]], visibility="private")
    payload["group_id"] = group_id
    team = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(bowen_csrf, f"observer-team-{uuid4()}"),
        json=payload,
    )
    assert team.status_code == 201, team.text
    return {
        "group": group_id,
        "agent": first[0],
        "version": first[1],
        "team": team.json()["id"],
        "document": document_id,
    }


def test_an_entered_teacher_reads_a_groups_private_work(client: TestClient, database: Any) -> None:
    work = _group_with_private_work(client, database)
    _, csrf = login(client, "maya")
    headers = _headers(csrf)
    agents = f"/api/v1/groups/{work['group']}/agents"
    documents = f"/api/v1/groups/{work['group']}/knowledge-documents"
    membership = f"/api/v1/groups/{work['group']}/membership"

    # From outside the group the teacher sees none of it.
    assert work["agent"] not in {item["id"] for item in client.get(agents).json()}
    assert client.get(f"/api/v1/agents/{work['agent']}").status_code == 404
    assert client.get(f"/api/v1/teams/{work['team']}").status_code == 404
    assert client.get(documents).status_code == 404

    assert client.post(membership, headers=headers).status_code == 200

    listed = {item["id"]: item for item in client.get(agents).json()}
    assert work["agent"] in listed
    assert listed[work["agent"]]["can_edit"] is False
    detail = client.get(f"/api/v1/agents/{work['agent']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_edit"] is False
    assert client.get(f"/api/v1/agents/{work['agent']}/versions").status_code == 200
    assert client.get(f"/api/v1/agents/{work['agent']}/knowledge-sets").status_code == 200
    version = client.get(f"/api/v1/agent-versions/{work['version']}")
    assert version.status_code == 200, version.text
    assert version.json()["agent_md"] == "# Quiet voice A"
    assert (
        client.get(f"/api/v1/agent-versions/{work['version']}/agent-md/download").status_code == 200
    )

    # The group's own listing shows its private Team; the course listing,
    # which feeds Chatform and Memory, does not offer what cannot be chatted to.
    group_teams = client.get(
        f"/api/v1/courses/{COURSE_ID}/teams", params={"group_id": work["group"]}
    ).json()
    assert work["team"] in {team["id"] for team in group_teams}
    course_teams = client.get(f"/api/v1/courses/{COURSE_ID}/teams").json()
    assert work["team"] not in {team["id"] for team in course_teams}
    team = client.get(f"/api/v1/teams/{work['team']}")
    assert team.status_code == 200, team.text
    assert team.json()["can_edit"] is False

    listed_documents = {item["id"]: item for item in client.get(documents).json()}
    assert work["document"] not in listed_documents
    assert client.get(f"/api/v1/knowledge-documents/{work['document']}").status_code == 404
    uploaded = client.post(
        documents,
        headers=_headers(csrf, f"observer-library-upload-{uuid4()}"),
        data={"visibility": "public"},
        files={"file": ("visit.md", b"# Visit\n\nteacher library note", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    uploaded_id = uploaded.json()["document"]["id"]
    listed_documents = {item["id"]: item for item in client.get(documents).json()}
    assert listed_documents[uploaded_id]["can_manage_visibility"] is True
    assert work["document"] not in listed_documents

    # Leaving closes it again.
    assert client.delete(membership, headers=headers).status_code == 204
    assert client.get(f"/api/v1/agents/{work['agent']}").status_code == 404
    assert client.get(f"/api/v1/teams/{work['team']}").status_code == 404


def test_an_entered_teacher_cannot_change_or_talk_to_private_work(
    client: TestClient, database: Any
) -> None:
    work = _group_with_private_work(client, database)
    _, csrf = login(client, "maya")
    headers = _headers(csrf)
    assert (
        client.post(f"/api/v1/groups/{work['group']}/membership", headers=headers).status_code
        == 200
    )

    rename = client.patch(
        f"/api/v1/agents/{work['agent']}",
        headers=headers,
        json={"name": "Taken over", "expected_metadata_revision": 0},
    )
    assert rename.status_code in {403, 404}, rename.text
    delete = client.delete(
        f"/api/v1/agents/{work['agent']}",
        headers=_headers(csrf, f"observer-delete-{uuid4()}"),
    )
    assert delete.status_code in {403, 404}, delete.text
    hide = client.patch(
        f"/api/v1/knowledge-documents/{work['document']}",
        headers=headers,
        json={"visibility": "public", "expected_authorization_epoch": 0},
    )
    assert hide.status_code in {403, 404, 422}, hide.text

    # Reading is not talking: private work cannot be invoked from Chatform.
    for entry in (
        {"kind": "agent", "version_id": work["version"]},
        {"kind": "team", "team_id": work["team"]},
    ):
        chat = client.post("/api/v1/conversations", headers=headers, json={"entry": entry})
        assert chat.status_code in {403, 404, 409}, chat.text


def test_groupmates_still_do_not_see_each_others_private_work(
    client: TestClient, database: Any
) -> None:
    work = _group_with_private_work(client, database)
    kaikai, _csrf = login(client, "kaikai")
    with database.session() as db:
        db.add(
            GroupMember(
                group_id=work["group"],
                user_id=kaikai["user"]["id"],
                role="member",
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
    listed = client.get(f"/api/v1/groups/{work['group']}/agents").json()
    assert work["agent"] not in {item["id"] for item in listed}
    assert client.get(f"/api/v1/agents/{work['agent']}").status_code == 404
    assert client.get(f"/api/v1/teams/{work['team']}").status_code == 404
