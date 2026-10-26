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


def test_last_edited_comes_from_the_latest_content_version(
    client: TestClient, app_bundle: Any
) -> None:
    from datetime import datetime

    from app.modules.knowledge_sets.models import KnowledgeDocumentVersion

    from tests.test_agent_source_cascade import _h

    _app, database, _settings = app_bundle
    owner, csrf = login(client, "bowen")
    doc = _upload(client, csrf, "edited.md", b"# E\n\nE1", "rag-edit-upload-0001")
    first = _rows(client)[doc]
    assert first["last_edited_by_user_id"] == owner["user"]["id"]
    assert first["last_edited_by_username"] == _username(database, "bowen")
    assert first["last_edited_at"] is not None
    current = client.get(f"/api/v1/knowledge-documents/{doc}").json()
    # Single-document endpoints leave the library-only fields null.
    assert current["last_edited_by_user_id"] is None and current["last_edited_at"] is None
    replaced = client.post(
        f"/api/v1/knowledge-documents/{doc}/replace",
        headers=_h(csrf, "rag-edit-replace-000001"),
        data={
            "expected_content_hash": current["content_hash"],
            "expected_index_revision": str(current["index_revision"]),
        },
        files={"file": ("edited.md", b"# E\n\nE2", "text/markdown")},
    )
    assert replaced.status_code == 201, replaced.text
    row = _rows(client)[replaced.json()["id"]]
    with database.session() as db:
        latest = db.scalars(
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == replaced.json()["id"])
            .order_by(KnowledgeDocumentVersion.version_seq.desc())
        ).first()
        assert latest is not None
        assert latest.version_seq >= 2
        assert latest.created_by_user_id == owner["user"]["id"]
        assert row["last_edited_by_user_id"] == latest.created_by_user_id
        assert datetime.fromisoformat(row["last_edited_at"]) == latest.created_at
    assert datetime.fromisoformat(row["last_edited_at"]) >= datetime.fromisoformat(
        first["last_edited_at"]
    )


def test_latest_versions_are_one_query(client: TestClient, app_bundle: Any) -> None:
    _app, database, _settings = app_bundle
    _, csrf = login(client, "bowen")
    for index in range(3):
        _upload(
            client, csrf, f"v{index}.md", f"# V{index}\n\nV".encode(), f"rag-v{index}-upload-0001"
        )
    statements: list[str] = []

    def keep(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    event.listen(database.engine, "before_cursor_execute", keep)
    try:
        assert client.get(f"/api/v1/groups/{GROUP_ID}/knowledge-documents").status_code == 200
    finally:
        event.remove(database.engine, "before_cursor_execute", keep)
    assert sum("knowledge_document_versions" in item for item in statements) == 1
