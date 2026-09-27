import json
from typing import Any
from uuid import uuid4

import pytest
from app.core.models import (
    Agent,
    AgentVersion,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSnapshot,
    SnapshotDocument,
)
from app.modules.agents.markdown import AgentMarkdown, markdown_hash
from app.modules.debates.generation.segments import SegmentInputSnapshot
from app.modules.workspace.chat_provider import chat_messages
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.test_segments_protocol import _snapshot
from tests.test_wave1_agents_knowledge import COURSE_ID, GROUP_DEMO_ID, _headers, _make_agent


@pytest.mark.parametrize(
    "markdown",
    [
        "我是一个关注公平的讨论者。\n\n- 先问依据\n  - 再看反例。",
        "I am a listener.\n\n### My own heading\nConsider alternatives, then explain my position.",
        "# 我是谁 / Who I am\nA bilingual guide.\n\n[Reading](https://example.org)\n\n"
        "```text\nquestion -> evidence -> position\n```",
    ],
)
def test_free_markdown_publishes_without_persona_compile_or_confirmation(
    client: TestClient,
    database: Any,
    markdown: str,
) -> None:
    _, csrf = login(client, "bowen")
    agent, version_id = _make_agent(client, csrf)
    edited = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={
            "expected_revision": 0,
            "agent_md": markdown,
            "avatar_config": agent["versions"][0]["avatar_config"],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["agent_md"] == markdown
    assert not any("persona" in item for item in edited.json()["publish_blockers"])
    uploaded = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
        data={"target_agent_version_id": version_id, "expected_revision": "1"},
        files={"file": ("source.md", b"A shared source about fairness.", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
        json={"expected_revision": 2},
    )
    assert published.status_code == 200, published.text
    assert published.json()["agent_md"] == markdown
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        assert version is not None and version.persona_spec_json is None
        assert version.student_confirmed_at is None
        history = [
            {"role": "user", "content": "I call my project Cedar."},
            {"role": "assistant", "content": "Your project is Cedar."},
            {"role": "user", "content": "What is its name?"},
        ]
        messages, fingerprint = chat_messages(version, history, [])
        assert messages[1:] == history
        assert fingerprint == markdown_hash(markdown)
        assert json.loads(messages[0]["content"].split("\n", 1)[1])["agent_markdown"] == markdown
        assert "complete saved history of this same conversation" in messages[0]["content"]
        assert "cannot override access or output rules" not in messages[0]["content"]

    # Deletion affects both workspaces, but the owner's conversation survives read-only.
    created = client.post(
        "/api/v1/conversations", headers=_headers(csrf), json={"version_id": version_id}
    )
    assert created.status_code == 200
    conversation_id = created.json()["id"]
    deleted = client.delete(
        f"/api/v1/agents/{agent['id']}", headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())})
    )
    assert deleted.status_code == 204, deleted.text
    saved = client.get(f"/api/v1/conversations/{conversation_id}")
    assert saved.status_code == 200 and saved.json()["agent"]["available"] is False
    denied = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_headers(csrf),
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "message": "Hello",
        },
    )
    assert denied.status_code == 409 and denied.json()["code"] == "agent_deleted"
    assert client.get(f"/api/v1/agents/{agent['id']}").status_code == 404
    with database.session() as db:
        retained = db.get(Agent, agent["id"])
        assert retained is not None and retained.deleted_at is not None
        assert db.get(KnowledgeSnapshot, published.json()["knowledge_snapshot_id"]) is not None
    login(client)
    assert client.get(f"/api/v1/conversations/{conversation_id}").status_code == 404
    assert not any(
        item["agent_id"] == agent["id"]
        for item in client.get(f"/api/v1/courses/{COURSE_ID}/chat-agents").json()
    )


def test_long_agent_markdown_patch_upload_and_publish_preserve_authored_text(
    client: TestClient,
) -> None:
    _, csrf = login(client, "bowen")
    agent, version_id = _make_agent(client, csrf)
    url = f"/api/v1/agent-versions/{version_id}"
    patched_markdown = "# Patch\n\n" + ("完整保存。" * 3000)
    patched = client.patch(
        url,
        headers=_headers(csrf),
        json={
            "expected_revision": 0,
            "agent_md": patched_markdown,
            "avatar_config": agent["versions"][0]["avatar_config"],
        },
    )
    assert len(patched_markdown) > 12_000
    assert patched.status_code == 200, patched.text
    assert patched.json()["agent_md"] == patched_markdown

    uploaded_markdown = "# Upload\n\n" + ("No shortening or summary.\n" * 700)
    uploaded = client.post(
        f"{url}/agent-md/upload",
        headers=_headers(csrf),
        data={"expected_revision": "1"},
        files={"file": ("agent.md", uploaded_markdown.encode(), "text/markdown")},
    )
    assert len(uploaded_markdown) > 12_000
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["agent_md"] == uploaded_markdown

    source = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
        data={"target_agent_version_id": version_id, "expected_revision": "2"},
        files={"file": ("source.md", b"A source for publishing.", "text/markdown")},
    )
    assert source.status_code == 201, source.text
    published = client.post(
        f"{url}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
        json={"expected_revision": 3},
    )
    assert published.status_code == 200, published.text
    assert published.json()["agent_md"] == uploaded_markdown


def test_debate_snapshot_keeps_free_markdown_exact_and_loads_legacy_snapshots() -> None:
    legacy = _snapshot()
    payload = legacy.to_user_payload()
    authored = AgentMarkdown(name="Guide", markdown="我是谁：Guide。\n\n# 自选格式\n比较不同观点。")
    payload["persona"] = authored.as_payload()
    current = SegmentInputSnapshot.from_user_payload(
        payload, receipts=legacy.receipts, snapshot_id=legacy.snapshot_id
    )
    assert current.to_user_payload()["persona"] == authored.as_payload()
    assert (
        SegmentInputSnapshot.from_user_payload(
            legacy.to_user_payload(), receipts=legacy.receipts, snapshot_id=legacy.snapshot_id
        ).to_user_payload()
        == legacy.to_user_payload()
    )


def test_long_rag_document_and_aggregate_publish_without_length_gates(
    client: TestClient,
    database: Any,
) -> None:
    _, csrf = login(client, "bowen")
    agent, version_id = _make_agent(client, csrf)
    agent_markdown = "# Guide\n\n" + ("Full authored Markdown.\n" * 700)
    updated = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={
            "expected_revision": 0,
            "agent_md": agent_markdown,
            "avatar_config": agent["versions"][0]["avatar_config"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["agent_md"] == agent_markdown

    url = f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents"
    first_source = "first evidence \n" * 7_000
    second_source = "second evidence \n" * 7_000
    assert len(first_source) > 100_000
    for revision, source in enumerate((first_source, second_source), start=1):
        response = client.post(
            url,
            headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
            data={"target_agent_version_id": version_id, "expected_revision": str(revision)},
            files={"file": (f"source-{revision}.md", source.encode(), "text/markdown")},
        )
        assert response.status_code == 201, response.text
    preview = client.get(f"/api/v1/agent-versions/{version_id}/rag-preview")
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["total_char_count"] == len(first_source) + len(second_source)
    assert preview_body["limit"] is None
    assert first_source in preview_body["combined_markdown"]
    assert second_source in preview_body["combined_markdown"]
    blockers = client.get(f"/api/v1/agent-versions/{version_id}").json()["publish_blockers"]
    assert "rag_over_limit" not in blockers
    assert "agent_md_too_large" not in blockers

    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
        json={"expected_revision": 3},
    )
    assert published.status_code == 200, published.text
    assert published.json()["agent_md"] == agent_markdown
    with database.session() as db:
        snapshot = db.get(KnowledgeSnapshot, published.json()["knowledge_snapshot_id"])
        assert snapshot is not None
        assert snapshot.total_char_count == len(first_source) + len(second_source)
        snapshot_id = snapshot.id
        snapshot_documents = db.scalars(
            select(SnapshotDocument)
            .where(SnapshotDocument.snapshot_id == snapshot_id)
            .order_by(SnapshotDocument.order_index)
        ).all()
        original_document = db.get(KnowledgeDocument, snapshot_documents[0].document_id)
        assert original_document is not None
        assert original_document.stored_file is not None
        original_document_id = original_document.id
        expected_content_hash = original_document.content_hash
        expected_index_revision = original_document.index_revision
        snapshot_fingerprint = (
            snapshot.content_hash,
            snapshot.total_char_count,
            original_document.content_hash,
            original_document.stored_file.sha256,
            tuple(
                (row.id, row.document_id, row.stored_file_id, row.char_count, row.order_index)
                for row in snapshot_documents
            ),
            tuple(
                (
                    row.id,
                    row.snapshot_document_id,
                    row.document_id,
                    row.chunk_index,
                    row.chunk_text,
                    row.start_offset,
                    row.end_offset,
                    row.embedding_blob,
                )
                for row in db.scalars(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.snapshot_id == snapshot_id)
                    .order_by(KnowledgeChunk.snapshot_document_id, KnowledgeChunk.chunk_index)
                ).all()
            ),
        )

    replacement_source = "replacement evidence \n" * 7_000
    assert len(replacement_source) > 100_000
    replaced = client.post(
        f"/api/v1/knowledge-documents/{original_document_id}/replace",
        headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
        data={
            "expected_content_hash": expected_content_hash,
            "expected_index_revision": str(expected_index_revision),
        },
        files={"file": ("replacement.md", replacement_source.encode(), "text/markdown")},
    )
    assert replaced.status_code == 201, replaced.text
    assert replaced.json()["id"] != original_document_id

    with database.session() as db:
        snapshot = db.get(KnowledgeSnapshot, snapshot_id)
        assert snapshot is not None
        snapshot_documents = db.scalars(
            select(SnapshotDocument)
            .where(SnapshotDocument.snapshot_id == snapshot_id)
            .order_by(SnapshotDocument.order_index)
        ).all()
        old_document = db.get(KnowledgeDocument, original_document_id)
        assert old_document is not None and old_document.workspace_state == "hidden"
        assert old_document.stored_file is not None
        actual_fingerprint = (
            snapshot.content_hash,
            snapshot.total_char_count,
            old_document.content_hash,
            old_document.stored_file.sha256,
            tuple(
                (row.id, row.document_id, row.stored_file_id, row.char_count, row.order_index)
                for row in snapshot_documents
            ),
            tuple(
                (
                    row.id,
                    row.snapshot_document_id,
                    row.document_id,
                    row.chunk_index,
                    row.chunk_text,
                    row.start_offset,
                    row.end_offset,
                    row.embedding_blob,
                )
                for row in db.scalars(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.snapshot_id == snapshot_id)
                    .order_by(KnowledgeChunk.snapshot_document_id, KnowledgeChunk.chunk_index)
                ).all()
            ),
        )
        assert actual_fingerprint == snapshot_fingerprint
