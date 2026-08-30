from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import app.modules.knowledge.router as knowledge_router
from app.core.db import Database
from app.core.models import (
    AgentVersion,
    AgentVersionDocument,
    FileOperation,
    Job,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSnapshot,
    SnapshotDocument,
    StoredFile,
)
from app.modules.knowledge.markdown import build_chunks, mock_embedding, normalize_markdown
from app.modules.knowledge.vector import MockEmbeddingProvider, MockVectorStore, StoredVectorRow
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from tests.conftest import login

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
BOWEN_GROUP_ID = "66ee37fb-5772-5c8f-bb63-46d1783c53ae"
KAIKAI_GROUP_ID = "699112be-780b-5ffd-9a87-3762f596c558"


def _headers(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, **extra}


def _make_agent(client: TestClient, csrf: str) -> tuple[dict[str, Any], str]:
    response = client.post(
        f"/api/v1/groups/{BOWEN_GROUP_ID}/agents",
        headers=_headers(csrf, **{"Idempotency-Key": "create-wave1-agent-001"}),
        json={"name": "Maya Guide", "description": "A small Demo guide."},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body, body["versions"][0]["id"]


def _assert_business_error(response: Any, code: str) -> dict[str, Any]:
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == code
    assert body["code"] != "malformed_request"
    assert set(body) == {"code", "message", "details", "request_id"}
    assert isinstance(body["details"], dict)
    UUID(body["request_id"])
    return body


def _insert_over_limit_document(
    database: Database,
    data_root: Path,
    version_id: str,
) -> str:
    source = b"# oversized\n"
    document_id = str(uuid4())
    stored_file_id = str(uuid4())
    relative_path = f"groups/{BOWEN_GROUP_ID}/knowledge/{document_id}/source.md"
    source_path = data_root / relative_path
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(source)
    source_sha = hashlib.sha256(source).hexdigest()
    timestamp = datetime.now(UTC)
    with database.session() as session:
        session.add(
            StoredFile(
                id=stored_file_id,
                kind="markdown",
                relative_path=relative_path,
                sha256=source_sha,
                size_bytes=len(source),
                state="active",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        session.flush()
        session.add(
            KnowledgeDocument(
                id=document_id,
                group_id=BOWEN_GROUP_ID,
                source_filename="oversized.md",
                stored_file_id=stored_file_id,
                char_count=100_001,
                index_status="ready",
                index_revision=1,
                workspace_state="active",
                content_hash=hashlib.sha256(source).hexdigest(),
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        session.flush()
        session.add(
            AgentVersionDocument(
                agent_version_id=version_id,
                document_id=document_id,
                enabled=True,
                order_index=0,
            )
        )
    return document_id


def test_wave1_student_flow_snapshot_teacher_projection_and_404(client: TestClient) -> None:
    _user, csrf = login(client, "student-bowen-1")
    agent, version_id = _make_agent(client, csrf)
    avatar = agent["versions"][0]["avatar_config"]

    response = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={
            "expected_revision": 0,
            "agent_md": "# Maya\nExplain the source.",
            "avatar_config": avatar,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 1

    response = client.post(
        f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "upload-wave1-document-001"}),
        data={"target_agent_version_id": version_id, "expected_revision": "1"},
        files={
            "file": (
                "lesson.md",
                b"# Maya\n\nMaya is a cultural exchange guide.",
                "text/markdown",
            )
        },
    )
    assert response.status_code == 201, response.text
    mutation = response.json()
    document_id = mutation["document"]["id"]
    assert mutation["agent_version"]["revision"] == 2
    assert mutation["document"]["index_status"] == "ready"

    # A completed idempotency key replays the exact original body rather than
    # trying to apply the stale revision a second time.
    replay = client.post(
        f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "upload-wave1-document-001"}),
        data={"target_agent_version_id": version_id, "expected_revision": "1"},
        files={
            "file": (
                "lesson.md",
                b"# Maya\n\nMaya is a cultural exchange guide.",
                "text/markdown",
            )
        },
    )
    assert replay.status_code == 201
    assert replay.json() == mutation

    chat = client.post(
        f"/api/v1/agent-versions/{version_id}/chat",
        headers=_headers(csrf),
        json={"message": "Maya"},
    )
    assert chat.status_code == 200
    assert chat.json()["retrieval_status"] == "matched"
    assert chat.json()["sources"][0]["source_filename"] == "lesson.md"

    unrelated_chat = client.post(
        f"/api/v1/agent-versions/{version_id}/chat",
        headers=_headers(csrf),
        json={"message": "TikTok recommendation algorithm"},
    )
    assert unrelated_chat.status_code == 200
    assert unrelated_chat.json()["retrieval_status"] == "no_match"
    assert unrelated_chat.json()["sources"] == []

    publish = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": "publish-wave1-agent-001"}),
        json={"expected_revision": 2},
    )
    assert publish.status_code == 200, publish.text
    published = publish.json()
    snapshot_id = published["knowledge_snapshot_id"]
    assert published["state"] == "published"

    teacher, teacher_csrf = login(client, "teacher-demo")
    candidates = client.get(f"/api/v1/courses/{COURSE_ID}/published-agents")
    assert candidates.status_code == 200
    assert any(item["agent"]["id"] == agent["id"] for item in candidates.json())
    assert client.get(f"/api/v1/agents/{agent['id']}").json()["versions"][0]["state"] == "published"
    snapshot = client.get(f"/api/v1/knowledge-snapshots/{snapshot_id}")
    assert snapshot.status_code == 200
    assert snapshot.json()["documents"][0]["source_filename"] == "lesson.md"
    assert client.get(f"/api/v1/knowledge-snapshots/{snapshot_id}/download").status_code == 200
    assert teacher["user"]["id"] and teacher_csrf

    _student, other_csrf = login(client, "student-kaikai-1")
    assert client.get(f"/api/v1/agents/{agent['id']}").status_code == 404
    assert client.get(f"/api/v1/knowledge-documents/{document_id}").status_code == 404
    assert client.get(f"/api/v1/knowledge-snapshots/{snapshot_id}").status_code == 404
    assert client.get(f"/api/v1/groups/{BOWEN_GROUP_ID}/agents").status_code == 404
    assert other_csrf


def test_wave1_revision_and_workspace_invariants(client: TestClient) -> None:
    _user, csrf = login(client, "student-bowen-1")
    agent, version_id = _make_agent(client, csrf)
    stale = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={"expected_revision": 1, "agent_md": "stale"},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_revision"
    assert stale.json()["details"]["current_revision"] == 0

    invalid = client.post(
        f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "upload-wave1-invalid-001"}),
        data={"target_agent_version_id": version_id, "expected_revision": "0"},
        files={"file": ("lesson.txt", b"not markdown", "text/plain")},
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "file_operation_failed"


def test_wave1_deterministic_markdown_and_migration_constraints(tmp_path: Path) -> None:
    document = normalize_markdown("lesson.md", b"\xef\xbb\xbf# Heading\r\n\r\nalpha beta")
    assert document.normalized == "# Heading\n\nalpha beta"
    assert document.char_count == len(document.normalized)
    chunks = build_chunks(document.normalized)
    assert chunks[0].text == document.normalized
    assert document.normalized[chunks[0].start_offset : chunks[0].end_offset] == chunks[0].text
    assert len(mock_embedding("\t\n")) == 1024


def test_wave1_migration_has_required_indexes(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'migration.sqlite3'}", tmp_path)
    database.upgrade_schema()
    inspector = inspect(database.engine)
    assert {"kind", "relative_path", "sha256", "size", "state"}.issubset(
        {item["name"] for item in inspector.get_columns("stored_files")}
    )
    assert {"combined_file_id", "embedding_model_key", "chunking_config_json"}.issubset(
        {item["name"] for item in inspector.get_columns("knowledge_snapshots")}
    )
    assert "text" in {item["name"] for item in inspector.get_columns("knowledge_chunks")}
    assert "frozen_file_id" in {
        item["name"] for item in inspector.get_columns("snapshot_documents")
    }
    assert {"uq_agent_versions_agent_seq"} == {
        item["name"] for item in inspector.get_unique_constraints("agent_versions")
    }
    assert "uq_agent_versions_one_draft" in {
        item["name"] for item in inspector.get_indexes("agent_versions")
    }
    assert "uq_agent_version_documents_enabled_order" in {
        item["name"] for item in inspector.get_indexes("agent_version_documents")
    }
    assert {"uq_snapshot_documents_source", "uq_snapshot_documents_order"} == {
        item["name"] for item in inspector.get_unique_constraints("snapshot_documents")
    }
    database.dispose()


def test_wave1_mock_vector_is_byte_stable_and_tie_breaks() -> None:
    provider = MockEmbeddingProvider()
    first = provider.embed("Maya")
    assert first == mock_embedding("Maya")
    store = MockVectorStore(
        [
            StoredVectorRow("b", "b.md", "B", first, 256, provider.key, 0, 1),
            StoredVectorRow("a", "a.md", "A", first, 256, provider.key, 0, 0),
        ]
    )
    assert [item.chunk_id for item in store.search("Maya")] == ["a", "b"]


def test_wave1_teacher_prepublication_visibility_and_authorized_empty_list(
    client: TestClient,
) -> None:
    _user, csrf = login(client, "student-bowen-1")
    assert client.get(f"/api/v1/groups/{BOWEN_GROUP_ID}/agents").json() == []
    agent, version_id = _make_agent(client, csrf)

    teacher, _teacher_csrf = login(client, "teacher-demo")
    assert teacher["user"]["id"]
    group_agents = client.get(f"/api/v1/groups/{BOWEN_GROUP_ID}/agents")
    assert group_agents.status_code == 200
    assert group_agents.json() == []
    assert client.get(f"/api/v1/agents/{agent['id']}").status_code == 404
    assert client.get(f"/api/v1/agent-versions/{version_id}").status_code == 404

    # An authorized student with no Agent in the other seeded group receives
    # an ordinary empty list rather than a false 404.
    _student, _student_csrf = login(client, "student-bowen-1")
    empty = client.get(f"/api/v1/groups/{KAIKAI_GROUP_ID}/agents")
    assert empty.status_code == 404  # the student is not authorized for Group B


def test_wave1_upload_missing_revision_is_scoped_stale_conflict(client: TestClient) -> None:
    _user, csrf = login(client, "student-bowen-1")
    _agent, version_id = _make_agent(client, csrf)
    response = client.post(
        f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "upload-missing-revision-001"}),
        data={"target_agent_version_id": version_id},
        files={"file": ("lesson.md", b"# Lesson", "text/markdown")},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "stale_revision"
    assert response.json()["details"] == {"current_revision": 0}


def test_wave1_upload_idempotency_includes_raw_source_bytes(client: TestClient) -> None:
    _user, csrf = login(client, "student-bowen-1")
    _agent, version_id = _make_agent(client, csrf)
    first = client.post(
        f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "upload-newline-hash-001"}),
        data={"target_agent_version_id": version_id, "expected_revision": "0"},
        files={"file": ("lesson.md", b"# Lesson\r\n", "text/markdown")},
    )
    assert first.status_code == 201, first.text
    conflict = client.post(
        f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "upload-newline-hash-001"}),
        data={"target_agent_version_id": version_id, "expected_revision": "0"},
        files={"file": ("lesson.md", b"# Lesson\n", "text/markdown")},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


def test_wave1_upload_crash_journal_recovers_exact_tree(
    app_factory: Any,
    monkeypatch: Any,
) -> None:
    app, database, settings = app_factory()
    original = knowledge_router.saga_checkpoint

    def crash(boundary: str) -> None:
        if boundary == "upload.staged":
            raise RuntimeError("injected crash")

    monkeypatch.setattr(knowledge_router, "saga_checkpoint", crash)
    with TestClient(app, raise_server_exceptions=False) as client:
        _user, csrf = login(client, "student-bowen-1")
        _agent, version_id = _make_agent(client, csrf)
        response = client.post(
            f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
            headers=_headers(csrf, **{"Idempotency-Key": "upload-crash-journal-001"}),
            data={"target_agent_version_id": version_id, "expected_revision": "0"},
            files={"file": ("lesson.md", b"# Lesson", "text/markdown")},
        )
        assert response.status_code == 503
    monkeypatch.setattr(knowledge_router, "saga_checkpoint", original)

    with database.session() as session:
        operation = session.scalar(
            select(FileOperation).where(FileOperation.operation_kind == "document_upload")
        )
        assert operation is not None
        assert operation.state == "cleanup_required"
    assert list((settings.resolved_data_root / "tmp" / "publish").iterdir())

    restarted = app_factory()
    with TestClient(restarted[0], raise_server_exceptions=False):
        pass
    with database.session() as session:
        operation = session.scalar(
            select(FileOperation).where(FileOperation.operation_kind == "document_upload")
        )
        assert operation is not None
        assert operation.state == "recovered"
    assert list((settings.resolved_data_root / "tmp" / "publish").iterdir()) == []


def test_wave1_reindex_failure_preserves_previous_complete_index(
    client: TestClient,
    monkeypatch: Any,
) -> None:
    _user, csrf = login(client, "student-bowen-1")
    _agent, version_id = _make_agent(client, csrf)
    uploaded = client.post(
        f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "reindex-source-upload-001"}),
        data={"target_agent_version_id": version_id, "expected_revision": "0"},
        files={"file": ("lesson.md", b"# Lesson\n\nMaya", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document"]["id"]

    def fail_chunks(_text: str) -> list[object]:
        raise RuntimeError("injected index failure")

    monkeypatch.setattr(knowledge_router, "build_chunks", fail_chunks)
    result = client.post(
        f"/api/v1/knowledge-documents/{document_id}/reindex",
        headers=_headers(csrf, **{"Idempotency-Key": "reindex-failure-001"}),
    )
    assert result.status_code == 202
    assert result.json()["status"] == "failed"
    assert result.json()["safe_error_code"] == "provider_unavailable"

    metadata = client.get(f"/api/v1/knowledge-documents/{document_id}")
    assert metadata.status_code == 200
    assert metadata.json()["index_status"] == "failed"


def test_wave1_snapshot_chunk_cannot_cross_snapshot_source(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        _user, csrf = login(client, "student-bowen-1")
        agent, version_id = _make_agent(client, csrf)
        client.patch(
            f"/api/v1/agent-versions/{version_id}",
            headers=_headers(csrf),
            json={
                "expected_revision": 0,
                "agent_md": "# Agent",
                "avatar_config": agent["versions"][0]["avatar_config"],
            },
        )
        uploaded = client.post(
            f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
            headers=_headers(csrf, **{"Idempotency-Key": "cross-snapshot-upload-001"}),
            data={"target_agent_version_id": version_id, "expected_revision": "1"},
            files={"file": ("lesson.md", b"# Lesson", "text/markdown")},
        )
        assert uploaded.status_code == 201, uploaded.text
        published = client.post(
            f"/api/v1/agent-versions/{version_id}/publish",
            headers=_headers(csrf, **{"Idempotency-Key": "cross-snapshot-publish-001"}),
            json={"expected_revision": 2},
        )
        assert published.status_code == 200, published.text

    timestamp = datetime.now(UTC)
    with database.session() as session:
        first_snapshot = session.scalar(select(KnowledgeSnapshot))
        assert first_snapshot is not None
        first_document = session.scalar(
            select(SnapshotDocument).where(SnapshotDocument.snapshot_id == first_snapshot.id)
        )
        assert first_document is not None
        second_version_id = str(uuid4())
        second_snapshot_id = str(uuid4())
        second_file_id = str(uuid4())
        second_frozen_id = str(uuid4())
        session.add(
            AgentVersion(
                id=second_version_id,
                agent_id=first_snapshot.agent_version.agent_id,
                version_seq=1,
                state="superseded",
                revision=0,
                agent_md="# Agent",
                avatar_config_json="{}",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        session.flush()
        session.add(
            StoredFile(
                id=second_file_id,
                kind="snapshot_rag",
                relative_path=f"snapshots/{second_snapshot_id}/rag.md",
                sha256="0" * 64,
                size_bytes=1,
                state="active",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        session.flush()
        session.add(
            KnowledgeSnapshot(
                id=second_snapshot_id,
                agent_version_id=second_version_id,
                stored_file_id=second_file_id,
                content_hash="0" * 64,
                total_char_count=1,
                embedding_key="mock-sha256-v1",
                chunking_json="{}",
                created_at=timestamp,
            )
        )
        session.flush()
        session.add(
            StoredFile(
                id=second_frozen_id,
                kind="snapshot_source",
                relative_path=f"snapshots/{second_snapshot_id}/documents/{uuid4()}.md",
                sha256="0" * 64,
                size_bytes=1,
                state="active",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        session.flush()
        session.add(
            SnapshotDocument(
                id=str(uuid4()),
                snapshot_id=second_snapshot_id,
                document_id=first_document.document_id,
                stored_file_id=second_frozen_id,
                source_filename="lesson.md",
                char_count=1,
                order_index=0,
            )
        )
        session.flush()
        session.add(
            KnowledgeChunk(
                id=str(uuid4()),
                snapshot_id=second_snapshot_id,
                snapshot_document_id=first_document.id,
                document_id=first_document.document_id,
                chunk_index=0,
                chunk_text="# Lesson",
                start_offset=0,
                end_offset=8,
                embedding_blob=mock_embedding("Lesson"),
                embedding_dimension=256,
                embedding_key="mock-sha256-v1",
            )
        )
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
        else:  # pragma: no cover - the composite FK is the assertion
            raise AssertionError("cross-snapshot chunk relation was accepted")


def test_wave1_startup_recovery_marks_document_failed_and_job_interrupted(
    app_factory: Any,
) -> None:
    app, database, settings = app_factory()
    with TestClient(app):
        pass
    timestamp = datetime.now(UTC)
    document_id = str(uuid4())
    stored_file_id = str(uuid4())
    job_id = str(uuid4())
    source = settings.resolved_data_root / "groups" / BOWEN_GROUP_ID / "recovery.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"# recovery")
    with database.session() as session:
        session.add(
            StoredFile(
                id=stored_file_id,
                kind="markdown",
                relative_path=f"groups/{BOWEN_GROUP_ID}/recovery.md",
                sha256="0" * 64,
                size_bytes=10,
                state="active",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        session.flush()
        session.add(
            KnowledgeDocument(
                id=document_id,
                group_id=BOWEN_GROUP_ID,
                source_filename="recovery.md",
                stored_file_id=stored_file_id,
                char_count=10,
                index_status="indexing",
                index_revision=0,
                workspace_state="active",
                content_hash="0" * 64,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        session.flush()
        session.add(
            Job(
                id=job_id,
                document_id=document_id,
                operation="reindex_document",
                state="running",
                attempt=1,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    restarted = app_factory()
    with TestClient(restarted[0]):
        pass
    with database.session() as session:
        document = session.get(KnowledgeDocument, document_id)
        job = session.get(Job, job_id)
        assert document is not None and document.index_status == "failed"
        assert document.safe_error_code == "provider_unavailable"
        assert job is not None and job.state == "interrupted"
        assert job.safe_error_code == "provider_unavailable"


def test_wave1_explicit_business_422_codes_are_not_transport_malformed_request(
    client: TestClient,
) -> None:
    _user, csrf = login(client, "student-bowen-1")
    agent, version_id = _make_agent(client, csrf)
    invalid_avatar = {**agent["versions"][0]["avatar_config"], "template_id": "unknown"}
    avatar_error = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={"expected_revision": 0, "avatar_config": invalid_avatar},
    )
    _assert_business_error(avatar_error, "avatar_missing")

    upload_error = client.post(
        f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "business-422-upload-001"}),
        data={"target_agent_version_id": version_id, "expected_revision": "0"},
        files={"file": ("lesson.txt", b"not markdown", "text/plain")},
    )
    _assert_business_error(upload_error, "file_operation_failed")

    set_error = client.put(
        f"/api/v1/agent-versions/{version_id}/knowledge-documents",
        headers=_headers(csrf),
        json={"expected_revision": 0, "document_ids": [version_id, version_id]},
    )
    _assert_business_error(set_error, "file_operation_failed")

    md_error = client.post(
        f"/api/v1/agent-versions/{version_id}/agent-md/upload",
        headers=_headers(csrf),
        files={"file": ("agent.txt", b"not markdown", "text/plain")},
        data={"expected_revision": "0"},
    )
    _assert_business_error(md_error, "file_operation_failed")

    chat_error = client.post(
        f"/api/v1/agent-versions/{version_id}/chat",
        headers=_headers(csrf),
        json={"message": "hello"},
    )
    _assert_business_error(chat_error, "agent_md_missing")

    publish_error = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": "business-publish-001"}),
        json={"expected_revision": 0},
    )
    publish_body = _assert_business_error(publish_error, "agent_md_missing")
    assert publish_body["details"] == {"publish_blockers": ["agent_md_missing", "rag_missing"]}


def test_wave1_rag_over_limit_is_422_for_upload_set_and_chat(
    app_factory: Any,
) -> None:
    app, database, settings = app_factory()
    with TestClient(app) as client:
        _user, csrf = login(client, "student-bowen-1")
        agent, version_id = _make_agent(client, csrf)
        updated = client.patch(
            f"/api/v1/agent-versions/{version_id}",
            headers=_headers(csrf),
            json={
                "expected_revision": 0,
                "agent_md": "# Agent",
                "avatar_config": agent["versions"][0]["avatar_config"],
            },
        )
        assert updated.status_code == 200, updated.text
        document_id = _insert_over_limit_document(
            database,
            settings.resolved_data_root,
            version_id,
        )

        upload_error = client.post(
            f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
            headers=_headers(csrf, **{"Idempotency-Key": "over-limit-upload-001"}),
            data={"target_agent_version_id": version_id, "expected_revision": "1"},
            files={"file": ("small.md", b"# Small", "text/markdown")},
        )
        _assert_business_error(upload_error, "rag_over_limit")

        set_error = client.put(
            f"/api/v1/agent-versions/{version_id}/knowledge-documents",
            headers=_headers(csrf),
            json={"expected_revision": 1, "document_ids": [document_id]},
        )
        _assert_business_error(set_error, "rag_over_limit")

        chat_error = client.post(
            f"/api/v1/agent-versions/{version_id}/chat",
            headers=_headers(csrf),
            json={"message": "hello"},
        )
        _assert_business_error(chat_error, "rag_over_limit")

        with database.session() as session:
            version = session.get(AgentVersion, version_id)
            assert version is not None
            assert version.revision == 1
            relations = session.scalars(
                select(AgentVersionDocument).where(
                    AgentVersionDocument.agent_version_id == version_id
                )
            ).all()
            assert [(row.document_id, row.enabled, row.order_index) for row in relations] == [
                (document_id, True, 0)
            ]
