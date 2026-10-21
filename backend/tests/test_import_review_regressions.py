from __future__ import annotations

import json

import pytest
from app.core.db import Database
from app.core.models import FileOperation, IdempotencyRecord, KnowledgeDocument
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.test_knowledge_generation_brainform import _create_set
from tests.test_wave3_knowledge import GROUP_DEMO_ID, _headers, _make_agent


@pytest.mark.parametrize("scope", ["agent", "private", "public"])
def test_invalid_upload_then_same_filename_valid_upload(
    client: TestClient, database: Database, scope: str
) -> None:
    _, csrf = login(client, "bowen")
    fields = {"visibility": "public" if scope == "public" else "private"}
    if scope == "agent":
        _, version_id = _make_agent(client, csrf, "import-audit", "Import Audit")
        fields.update(target_agent_version_id=version_id, expected_revision="0")
    url = f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents"
    invalid_key = f"invalid-{scope}-import-123456"
    response = client.post(
        url,
        headers=_headers(csrf, **{"Idempotency-Key": invalid_key}),
        data=fields,
        files={"file": ("lesson.md", b"# Lesson\ninvalid\x00content", "text/markdown")},
    )
    assert response.status_code == 422, response.text
    error = response.json()
    assert error["code"] == "knowledge_import_invalid"
    assert error["details"]["reason"] == "invalid_control_chars"
    with database.session() as session:
        record = session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.key == invalid_key)
        )
        assert record is not None and record.state == "abandoned"
        assert (
            session.scalar(
                select(FileOperation.id).where(FileOperation.idempotency_record_id == record.id)
            )
            is None
        )
        assert (
            session.scalar(
                select(KnowledgeDocument.id).where(KnowledgeDocument.source_filename == "lesson.md")
            )
            is None
        )
    corrected = client.post(
        url,
        headers=_headers(csrf, **{"Idempotency-Key": f"corrected-{scope}-import-123456"}),
        data=fields,
        files={"file": ("lesson.md", b"# Lesson\nvalid content", "text/markdown")},
    )
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["document"]["source_filename"] == "lesson.md"


def test_invalid_replacement_does_not_poison_same_filename_retry(
    client: TestClient, database: Database
) -> None:
    _, csrf = login(client, "bowen")
    created = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "create-import-audit-123456"}),
        files={"file": ("lesson.md", b"# Original\nvalid content", "text/markdown")},
    )
    assert created.status_code == 201, created.text
    document = created.json()["document"]
    url = f"/api/v1/knowledge-documents/{document['id']}/replace"
    fields = {
        "expected_content_hash": document["content_hash"],
        "expected_index_revision": str(document["index_revision"]),
    }
    invalid_key = "replace-invalid-import-audit-123456"
    response = client.post(
        url,
        headers=_headers(csrf, **{"Idempotency-Key": invalid_key}),
        data=fields,
        files={"file": ("lesson.md", b"# Replacement\ninvalid\x00content", "text/markdown")},
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "knowledge_import_invalid"
    assert response.json()["details"]["reason"] == "invalid_control_chars"
    with database.session() as session:
        stored = session.get(KnowledgeDocument, document["id"])
        assert stored is not None and stored.content_hash == document["content_hash"]
        assert stored.index_revision == document["index_revision"]
        assert (
            session.scalar(select(IdempotencyRecord.id).where(IdempotencyRecord.key == invalid_key))
            is None
        )
    corrected = client.post(
        url,
        headers=_headers(csrf, **{"Idempotency-Key": "replace-corrected-import-audit-123456"}),
        data=fields,
        files={"file": ("lesson.md", b"# Replacement\nvalid content", "text/markdown")},
    )
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["source_filename"] == "lesson.md"
    assert corrected.json()["content_hash"] != document["content_hash"]


@pytest.mark.parametrize(
    "invalid, reason", [("\x00", "invalid_control_chars"), ("\ud800", "invalid_utf8")]
)
def test_agent_editor_rejects_control_chars_before_saving(
    client: TestClient, invalid: str, reason: str
) -> None:
    _, csrf = login(client, "bowen")
    agent_id, version_id = _make_agent(client, csrf, "editor-import-audit", "Editor Import Audit")
    response = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf, **{"Content-Type": "application/json"}),
        content=json.dumps(
            {"expected_revision": 0, "agent_md": f"# Agent\ninvalid{invalid}content"}
        ),
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "file_operation_failed"
    assert response.json()["details"]["reason"] == reason
    current = client.get(f"/api/v1/agents/{agent_id}").json()["versions"][0]
    assert current["revision"] == 0
    corrected = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={"expected_revision": 0, "agent_md": "# Agent\nvalid content"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["revision"] == 1


@pytest.mark.parametrize(
    "invalid, reason", [("\x00", "invalid_control_chars"), ("\ud800", "invalid_utf8")]
)
def test_knowledge_editor_rejects_invalid_characters_and_recovers(
    client: TestClient, database: Database, invalid: str, reason: str
) -> None:
    _, csrf = login(client, "bowen")
    knowledge_set = _create_set(client, csrf, "Import audit", group_id=GROUP_DEMO_ID)
    set_id = knowledge_set["id"]
    invalid_key = "knowledge-editor-invalid-123456"
    response = client.put(
        f"/api/v1/knowledge-sets/{set_id}/markdown",
        headers=_headers(
            csrf, **{"Idempotency-Key": invalid_key, "Content-Type": "application/json"}
        ),
        content=json.dumps(
            {"expected_version_seq": 0, "markdown": f"# Lesson\ninvalid{invalid}content"}
        ),
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "knowledge_import_invalid"
    assert response.json()["details"]["reason"] == reason
    with database.session() as session:
        assert (
            session.scalar(
                select(IdempotencyRecord.id).where(
                    IdempotencyRecord.key == invalid_key, IdempotencyRecord.state == "pending"
                )
            )
            is None
        )
    corrected = client.put(
        f"/api/v1/knowledge-sets/{set_id}/markdown",
        headers=_headers(csrf, **{"Idempotency-Key": "knowledge-editor-corrected-123456"}),
        json={"expected_version_seq": 0, "markdown": "# Lesson\nvalid content"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["version_seq"] == 1


def test_agent_and_knowledge_editors_preserve_blank_draft_saves(client: TestClient) -> None:
    _, csrf = login(client, "bowen")
    _, version_id = _make_agent(client, csrf, "blank-import-audit", "Blank Import Audit")
    agent = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={"expected_revision": 0, "agent_md": "\r\n\t "},
    )
    assert agent.status_code == 200, agent.text
    assert agent.json()["agent_md"] == "\n\t "
    knowledge_set = _create_set(client, csrf, "Blank import audit", group_id=GROUP_DEMO_ID)
    knowledge = client.put(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}/markdown",
        headers=_headers(csrf, **{"Idempotency-Key": "knowledge-blank-editor-123456"}),
        json={"expected_version_seq": 0, "markdown": "\r\n\t "},
    )
    assert knowledge.status_code == 200, knowledge.text
    assert knowledge.json()["markdown"] == "\r\n\t "
