from __future__ import annotations

from typing import Any

from app.core.models import User
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from tests.conftest import login
from tests.test_agent_source_cascade import GROUP_ID, _agent_with_docs, _upload

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"


def _username(database: Any, login_name: str) -> str:
    with database.session() as db:
        user = db.scalar(select(User).where(User.username == login_name))
        assert user is not None
        return user.username


def _rows(client: TestClient) -> dict[str, dict[str, Any]]:
    listed = client.get(f"/api/v1/groups/{GROUP_ID}/knowledge-documents")
    assert listed.status_code == 200, listed.text
    return {row["id"]: row for row in listed.json()}


def test_group_library_lists_owner_and_only_usable_agents(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, _settings = app_bundle
    owner, csrf = login(client, "bowen")
    doc = _upload(client, csrf, "used.md", b"# Used\n\nUSED_CANARY", "rag-used-up-0001")
    free = _upload(client, csrf, "free.md", b"# Free\n\nFREE_CANARY", "rag-free-up-0001")
    public_agent = _agent_with_docs(client, csrf, "Used Public", [doc])
    private_agent = _agent_with_docs(client, csrf, "Used Private", [doc], visibility="private")

    mine = _rows(client)
    assert mine[doc]["owner_user_id"] == owner["user"]["id"]
    assert mine[doc]["owner_username"] == _username(database, "bowen")
    assert mine[doc]["used_by_agents"] == sorted(
        [
            {"agent_id": private_agent, "name": "Used Private"},
            {"agent_id": public_agent, "name": "Used Public"},
        ],
        key=lambda item: item["name"].casefold(),
    )
    assert mine[free]["used_by_agents"] == []

    # A groupmate sees the public file and only the Agents they may use.
    login(client, "kaikai")
    theirs = _rows(client)
    assert theirs[doc]["owner_username"] == _username(database, "bowen")
    assert theirs[doc]["used_by_agents"] == [{"agent_id": public_agent, "name": "Used Public"}]

    # Matches the per-file endpoint for the same caller.
    login(client, "bowen")
    single = client.get(f"/api/v1/knowledge-documents/{doc}/affected-agents")
    assert single.status_code == 200
    assert sorted(single.json(), key=lambda item: item["name"]) == mine[doc]["used_by_agents"]


def test_teacher_workspace_library_has_the_new_fields(client: TestClient) -> None:
    _, csrf = login(client, "maya")
    listed = client.get(f"/api/v1/courses/{COURSE_ID}/workspace-documents")
    assert listed.status_code == 200, listed.text
    for row in listed.json():
        assert row["used_by_agents"] is not None
        assert "owner_username" in row
    del csrf


def _count(database: Any, client: TestClient) -> tuple[int, int]:
    seen = [0]

    def tick(*_args: Any) -> None:
        seen[0] += 1

    event.listen(database.engine, "before_cursor_execute", tick)
    try:
        listed = client.get(f"/api/v1/groups/{GROUP_ID}/knowledge-documents")
    finally:
        event.remove(database.engine, "before_cursor_execute", tick)
    assert listed.status_code == 200
    return seen[0], len(listed.json())


def test_library_query_count_does_not_grow_with_documents(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, _settings = app_bundle
    _, csrf = login(client, "bowen")
    first = _upload(client, csrf, "n1.md", b"# N1\n\nN1_CANARY", "rag-n1-upload-0001")
    _agent_with_docs(client, csrf, "Batch Agent", [first])
    before, docs_before = _count(database, client)
    more = [
        _upload(
            client,
            csrf,
            f"m{index}.md",
            f"# M{index}\n\nM{index}".encode(),
            f"rag-m{index}-upload-0001",
        )
        for index in range(4)
    ]
    _agent_with_docs(client, csrf, "Batch Agent Two", more)
    after, docs_after = _count(database, client)
    assert docs_after == docs_before + 4
    # One extra Agent may add its own visibility check, never one per document.
    assert after - before <= 4, (before, after)
