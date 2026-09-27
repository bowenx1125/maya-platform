from __future__ import annotations

import hashlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Event, Thread
from typing import Any, cast

import app.modules.knowledge.replacement as replacement_service
import app.modules.knowledge.router as knowledge_router
import app.modules.knowledge.services as knowledge_services
import pytest
from app.core.db import Database
from app.core.models import (
    Agent,
    AgentVersion,
    AgentVersionDocument,
    FileOperation,
    FileReference,
    Job,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeSnapshot,
    SnapshotDocument,
    StoredFile,
)
from app.modules.debates.models import DebateParticipant
from app.modules.knowledge.files import (
    FileBoundaryError,
    content_disposition,
    frozen_download_filename,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login, make_foreign_group
from tests.persona_fixtures import confirmed_persona_fields

GROUP_DEMO_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"


def _headers(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, **extra}


def _make_agent(client: TestClient, csrf: str, key: str, name: str) -> tuple[str, str]:
    response = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/agents",
        headers=_headers(csrf, **{"Idempotency-Key": f"create-{key}-123456"}),
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["id"], body["versions"][0]["id"]


def _upload(
    client: TestClient,
    csrf: str,
    version_id: str,
    key: str,
    filename: str,
    content: bytes,
    expected_revision: int,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": f"upload-{key}-123456"}),
        data={
            "target_agent_version_id": version_id,
            "expected_revision": str(expected_revision),
        },
        files={"file": (filename, content, "text/markdown")},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _confirm_persona(
    client: TestClient,
    csrf: str,
    version_id: str,
    expected_revision: int,
) -> None:
    compiled = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/compile",
        headers=_headers(csrf),
        json={"expected_revision": expected_revision},
    )
    assert compiled.status_code == 200, compiled.text
    body = compiled.json()
    confirmed = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/confirm",
        headers=_headers(csrf),
        json={
            "expected_revision": expected_revision,
            "raw_agent_md_hash": body["raw_agent_md_hash"],
            "persona_spec_hash": body["persona_spec_hash"],
            "compiler_version": "persona_template_v1",
        },
    )
    assert confirmed.status_code == 200, confirmed.text


def _prepare_publishable_draft(
    client: TestClient,
    csrf: str,
    key: str,
    name: str = "Race Agent",
) -> tuple[str, str, dict[str, Any]]:
    agent_id, version_id = _make_agent(client, csrf, key, name)
    detail = client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200, detail.text
    updated = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={
            "expected_revision": 0,
            "agent_md": confirmed_persona_fields(name, datetime.now(UTC))["agent_md"],
            "avatar_config": detail.json()["versions"][0]["avatar_config"],
        },
    )
    assert updated.status_code == 200, updated.text
    uploaded = _upload(
        client,
        csrf,
        version_id,
        f"{key}-source",
        "race.md",
        b"# Race\n\nEvidence",
        1,
    )
    _confirm_persona(client, csrf, version_id, expected_revision=2)
    return agent_id, version_id, uploaded


def _assert_storage_recovered(database: Any, data_root: Path) -> None:
    recoverable = ("prepared", "staged", "promoted", "cleanup_required")
    with database.session() as session:
        assert (
            session.scalars(select(FileOperation).where(FileOperation.state.in_(recoverable))).all()
            == []
        )
        assert session.scalars(select(Job).where(Job.state.in_(("pending", "running")))).all() == []
        stored_files = session.scalars(select(StoredFile)).all()
        stored_paths = {row.relative_path for row in stored_files}
        for row in stored_files:
            if row.state != "active":
                continue
            assert (
                session.scalar(
                    select(FileReference.id).where(FileReference.stored_file_id == row.id)
                )
                is not None
            )
    disk_paths = {
        str(path.relative_to(data_root)) for path in data_root.rglob("*.md") if path.is_file()
    }
    assert disk_paths <= stored_paths
    publish_root = data_root / "tmp" / "publish"
    if publish_root.exists():
        assert list(publish_root.iterdir()) == []


def _release_fingerprint(database: Any, data_root: Path, agent_id: str) -> dict[str, Any]:
    """Capture immutable release rows, bytes and frozen debate inputs."""

    with database.session() as session:
        versions = session.scalars(
            select(AgentVersion)
            .where(
                AgentVersion.agent_id == agent_id,
                AgentVersion.state.in_(("published", "superseded")),
            )
            .order_by(AgentVersion.version_seq)
        ).all()
        version_ids = [row.id for row in versions]
        snapshots = session.scalars(
            select(KnowledgeSnapshot)
            .where(KnowledgeSnapshot.agent_version_id.in_(version_ids))
            .order_by(KnowledgeSnapshot.id)
        ).all()
        snapshot_ids = [row.id for row in snapshots]
        documents = session.scalars(
            select(SnapshotDocument)
            .where(SnapshotDocument.snapshot_id.in_(snapshot_ids))
            .order_by(SnapshotDocument.id)
        ).all()
        chunks = session.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.snapshot_id.in_(snapshot_ids))
            .order_by(KnowledgeChunk.id)
        ).all()
        stored_ids = {row.stored_file_id for row in snapshots} | {
            row.stored_file_id for row in documents
        }
        stored_files = session.scalars(
            select(StoredFile).where(StoredFile.id.in_(stored_ids)).order_by(StoredFile.id)
        ).all()
        participants = session.scalars(
            select(DebateParticipant)
            .where(DebateParticipant.agent_id == agent_id)
            .order_by(DebateParticipant.id)
        ).all()

        version_values = [
            (
                row.id,
                row.agent_id,
                row.version_seq,
                row.state,
                row.revision,
                row.agent_md,
                row.avatar_config_json,
                row.voice_profile_id,
                row.knowledge_snapshot_id,
                row.published_at,
            )
            for row in versions
        ]
        snapshot_values = [
            (
                row.id,
                row.agent_version_id,
                row.stored_file_id,
                row.content_hash,
                row.total_char_count,
                row.embedding_key,
                row.chunking_json,
            )
            for row in snapshots
        ]
        document_values = [
            (
                row.id,
                row.snapshot_id,
                row.document_id,
                row.stored_file_id,
                row.source_filename,
                row.char_count,
                row.order_index,
            )
            for row in documents
        ]
        chunk_values = [
            (
                row.id,
                row.snapshot_id,
                row.snapshot_document_id,
                row.document_id,
                row.chunk_index,
                row.chunk_text,
                row.start_offset,
                row.end_offset,
                row.embedding_blob,
                row.embedding_dimension,
                row.embedding_key,
            )
            for row in chunks
        ]
        file_values = []
        for row in stored_files:
            file_bytes = (data_root / row.relative_path).read_bytes()
            assert hashlib.sha256(file_bytes).hexdigest() == row.sha256
            file_values.append(
                (
                    row.id,
                    row.kind,
                    row.relative_path,
                    row.sha256,
                    row.size_bytes,
                    row.state,
                    file_bytes,
                )
            )
        participant_values = [
            tuple(getattr(row, column.name) for column in DebateParticipant.__table__.columns)
            for row in participants
        ]
    return {
        "versions": version_values,
        "snapshots": snapshot_values,
        "documents": document_values,
        "chunks": chunk_values,
        "files": file_values,
        "participants": participant_values,
    }


def test_frozen_download_names_are_encoded_and_reject_paths() -> None:
    filename = frozen_download_filename("证据.md", "Bowen Guide", "V1.0", ordinal=1)
    header = content_disposition(filename)
    assert 'filename="' in header
    assert "filename*=UTF-8''" in header
    assert "%E8%AF%81%E6%8D%AE" in header
    with pytest.raises(FileBoundaryError):
        content_disposition("../unsafe.md")


def test_library_create_does_not_auto_enable_a_draft(client: TestClient) -> None:
    _user, csrf = login(client, "bowen")
    _agent_id, version_id = _make_agent(client, csrf, "library", "Library Agent")
    response = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "library-create-123456"}),
        files={"file": ("standalone.md", b"# Library", "text/markdown")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["agent_version"] is None
    document_id = response.json()["document"]["id"]
    # The draft projection is enough to prove no relation was auto-created;
    # standalone creation has no target version to mutate.
    version = client.get(f"/api/v1/agent-versions/{version_id}")
    assert version.status_code == 200
    assert version.json()["enabled_documents"] == []
    assert client.get(f"/api/v1/knowledge-documents/{document_id}").status_code == 200


def test_replacement_updates_all_current_drafts_including_disabled_relation(
    app_factory: Any,
) -> None:
    app, database, settings = app_factory()
    with TestClient(app) as client:
        _user, csrf = login(client, "bowen")
        _agent_one, version_one = _make_agent(client, csrf, "replace-one", "One")
        _agent_two, version_two = _make_agent(client, csrf, "replace-two", "Two")
        uploaded = _upload(
            client,
            csrf,
            version_one,
            "old",
            "old.md",
            b"# Old\n\nShared source",
            0,
        )
        old_id = uploaded["document"]["id"]
        selected = client.put(
            f"/api/v1/agent-versions/{version_two}/knowledge-documents",
            headers=_headers(csrf),
            json={"expected_revision": 0, "document_ids": [old_id]},
        )
        assert selected.status_code == 200, selected.text
        with database.session() as session:
            relation = session.get(AgentVersionDocument, (version_two, old_id))
            assert relation is not None
            relation.enabled = False

        with database.session() as session:
            old = session.get(KnowledgeDocument, old_id)
            assert old is not None
            old_hash = old.content_hash
            old_index_revision = old.index_revision

        replaced = client.post(
            f"/api/v1/knowledge-documents/{old_id}/replace",
            headers=_headers(csrf, **{"Idempotency-Key": "replace-shared-123456"}),
            data={
                "expected_content_hash": old_hash,
                "expected_index_revision": str(old_index_revision),
            },
            files={"file": ("new.md", b"# New\n\nUpdated source", "text/markdown")},
        )
        assert replaced.status_code == 201, replaced.text
        new_id = replaced.json()["id"]
        assert new_id != old_id
        assert [
            item["id"]
            for item in client.get(f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents").json()
        ] == [new_id]

    with database.session() as session:
        old = session.get(KnowledgeDocument, old_id)
        new = session.get(KnowledgeDocument, new_id)
        assert old is not None and old.workspace_state == "hidden"
        assert new is not None and new.workspace_state == "active"
        relations = session.scalars(select(AgentVersionDocument)).all()
        assert {(row.agent_version_id, row.document_id, row.enabled) for row in relations} == {
            (version_one, new_id, True),
            (version_two, new_id, False),
        }
        versions = {
            row.id: row.revision
            for row in session.scalars(
                select(AgentVersion).where(AgentVersion.id.in_([version_one, version_two]))
            ).all()
        }
        assert versions == {version_one: 2, version_two: 2}
        assert settings.resolved_data_root.exists()


def test_replacement_without_draft_references_becomes_library_document(app_factory: Any) -> None:
    app, database, settings = app_factory()
    with TestClient(app) as client:
        _user, csrf = login(client, "bowen")
        created = client.post(
            f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
            headers=_headers(csrf, **{"Idempotency-Key": "orphan-create-123456"}),
            files={"file": ("old.md", b"# Old", "text/markdown")},
        )
        assert created.status_code == 201, created.text
        old = created.json()["document"]
        with database.session() as session:
            old_row = session.get(KnowledgeDocument, old["id"])
            assert old_row is not None
            old_hash = old_row.content_hash
        replacement = client.post(
            f"/api/v1/knowledge-documents/{old['id']}/replace",
            headers=_headers(csrf, **{"Idempotency-Key": "orphan-replace-123456"}),
            data={"expected_content_hash": old_hash, "expected_index_revision": "1"},
            files={"file": ("new.md", b"# New", "text/markdown")},
        )
        assert replacement.status_code == 201, replacement.text
        new_id = replacement.json()["id"]
        assert [
            item["id"]
            for item in client.get(f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents").json()
        ] == [new_id]
    with database.session() as session:
        old_row = session.get(KnowledgeDocument, old["id"])
        new_row = session.get(KnowledgeDocument, new_id)
        assert old_row is not None and old_row.workspace_state == "hidden"
        assert new_row is not None and new_row.workspace_state == "active"
        assert settings.resolved_data_root.exists()


def test_replacement_staged_journal_recovers_after_crash(
    app_factory: Any,
    monkeypatch: Any,
) -> None:
    app, database, settings = app_factory()
    original = cast(Callable[[str], None], cast(Any, knowledge_router).saga_checkpoint)

    def crash(boundary: str) -> None:
        if boundary == "replace.staged":
            raise RuntimeError("injected replacement crash")

    monkeypatch.setattr(knowledge_router, "saga_checkpoint", crash)
    with TestClient(app, raise_server_exceptions=False) as client:
        _user, csrf = login(client, "bowen")
        _agent_id, version_id = _make_agent(client, csrf, "crash", "Crash")
        uploaded = _upload(client, csrf, version_id, "crash-old", "old.md", b"# Old", 0)
        old_id = uploaded["document"]["id"]
        with database.session() as session:
            old = session.get(KnowledgeDocument, old_id)
            assert old is not None
            old_hash = old.content_hash
        response = client.post(
            f"/api/v1/knowledge-documents/{old_id}/replace",
            headers=_headers(csrf, **{"Idempotency-Key": "replace-crash-123456"}),
            data={"expected_content_hash": old_hash, "expected_index_revision": "1"},
            files={"file": ("new.md", b"# New", "text/markdown")},
        )
        assert response.status_code == 503
    monkeypatch.setattr(knowledge_router, "saga_checkpoint", original)

    with database.session() as session:
        operation = session.scalar(
            select(FileOperation).where(FileOperation.operation_kind == "document_replace")
        )
        assert operation is not None and operation.state == "cleanup_required"
        old = session.get(KnowledgeDocument, old_id)
        assert old is not None and old.workspace_state == "active"
    assert list((settings.resolved_data_root / "tmp" / "publish").iterdir())

    restarted = app_factory()
    with TestClient(restarted[0], raise_server_exceptions=False):
        pass
    with database.session() as session:
        operation = session.scalar(
            select(FileOperation).where(FileOperation.operation_kind == "document_replace")
        )
        assert operation is not None and operation.state == "recovered"
    assert list((settings.resolved_data_root / "tmp" / "publish").iterdir()) == []


def test_published_agent_rag_and_sources_use_server_names_and_scope(
    client: TestClient,
    database: Database,
) -> None:
    _student, csrf = login(client, "bowen")
    agent_id, version_id = _make_agent(client, csrf, "download", "Download Agent")
    detail = client.get(f"/api/v1/agents/{agent_id}")
    assert detail.status_code == 200, detail.text
    avatar = detail.json()["versions"][0]["avatar_config"]
    persona_source = confirmed_persona_fields("Download Agent", datetime.now(UTC))["agent_md"]
    updated = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={
            "expected_revision": 0,
            "agent_md": persona_source,
            "avatar_config": avatar,
        },
    )
    assert updated.status_code == 200, updated.text
    first = _upload(
        client,
        csrf,
        version_id,
        "download-one",
        "same.md",
        b"# First\n\nAlpha",
        1,
    )
    second = _upload(
        client,
        csrf,
        version_id,
        "download-two",
        "same.md",
        b"# Second\n\nBeta",
        2,
    )
    _confirm_persona(client, csrf, version_id, expected_revision=3)
    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": "download-publish-123456"}),
        json={"expected_revision": 3},
    )
    assert published.status_code == 200, published.text
    snapshot_id = published.json()["knowledge_snapshot_id"]
    assert snapshot_id

    agent_md = client.get(f"/api/v1/agent-versions/{version_id}/agent-md/download")
    assert agent_md.status_code == 200, agent_md.text
    assert agent_md.text == persona_source
    assert agent_md.headers["content-disposition"].startswith(
        'attachment; filename="AGENT--Download-Agent--V1.0.md"'
    )

    rag = client.get(f"/api/v1/knowledge-snapshots/{snapshot_id}/download")
    assert rag.status_code == 200, rag.text
    assert "# First" in rag.text and "# Second" in rag.text
    assert rag.headers["content-disposition"].startswith(
        'attachment; filename="RAG--Download-Agent--V1.0.md"'
    )

    snapshot = client.get(f"/api/v1/knowledge-snapshots/{snapshot_id}")
    assert snapshot.status_code == 200, snapshot.text
    documents = snapshot.json()["documents"]
    assert len(documents) == 2
    for document, expected_base in zip(
        documents,
        ("same", "same"),
        strict=True,
    ):
        source = client.get(
            f"/api/v1/knowledge-snapshots/{snapshot_id}/documents/{document['id']}/download"
        )
        assert source.status_code == 200, source.text
        expected_filename = (
            f"{expected_base}--Download-Agent--V1.0--{document['order_index'] + 1:02d}.md"
        )
        assert source.headers["content-disposition"].startswith(
            f'attachment; filename="{expected_filename}"'
        )

    _teacher, teacher_csrf = login(client, "maya")
    del teacher_csrf
    assert client.get(f"/api/v1/agent-versions/{version_id}/agent-md/download").status_code == 200
    assert client.get(f"/api/v1/knowledge-snapshots/{snapshot_id}/download").status_code == 200
    teacher_source = client.get(
        f"/api/v1/knowledge-snapshots/{snapshot_id}/documents/{documents[0]['id']}/download"
    )
    assert teacher_source.status_code == 200, teacher_source.text
    assert teacher_source.text == "# First\n\nAlpha"

    # Downloads are group-membership scoped. There is one seeded group, so the
    # out-of-scope branch is exercised by moving the Agent into a group the
    # caller does not belong to.
    foreign_group_id = make_foreign_group(database, COURSE_ID)
    with database.session() as session:
        moved = session.get(Agent, agent_id)
        assert moved is not None
        moved.group_id = foreign_group_id
        session.commit()

    _other, other_csrf = login(client, "bowen")
    del other_csrf
    assert client.get(f"/api/v1/agent-versions/{version_id}/agent-md/download").status_code == 404
    assert client.get(f"/api/v1/knowledge-snapshots/{snapshot_id}/download").status_code == 404
    assert (
        client.get(
            f"/api/v1/knowledge-snapshots/{snapshot_id}/documents/{documents[0]['id']}/download"
        ).status_code
        == 404
    )

    # Snapshot source IDs and the Agent version are both immutable; the
    # download helpers must never substitute the current user's group.
    assert first["document"]["id"] != second["document"]["id"]


def test_two_database_threads_concurrent_replace_have_one_winner(
    app_factory: Any,
) -> None:
    app_one, database, settings = app_factory()
    app_two, database_two, _settings_two = app_factory()
    assert database.engine.url == database_two.engine.url
    with (
        TestClient(app_one, raise_server_exceptions=False) as client_one,
        TestClient(app_two, raise_server_exceptions=False) as client_two,
    ):
        _user_one, csrf_one = login(client_one, "bowen")
        _user_two, csrf_two = login(client_two, "bowen")
        _agent_id, _version_id, uploaded = _prepare_publishable_draft(
            client_one, csrf_one, "concurrent-replace", "Concurrent Replace"
        )
        old = uploaded["document"]
        barrier = Barrier(2)

        def replace(client: TestClient, csrf: str, key: str, content: bytes) -> Any:
            barrier.wait(timeout=15)
            return client.post(
                f"/api/v1/knowledge-documents/{old['id']}/replace",
                headers=_headers(csrf, **{"Idempotency-Key": key}),
                data={
                    "expected_content_hash": old["content_hash"],
                    "expected_index_revision": str(old["index_revision"]),
                },
                files={"file": ("replacement.md", content, "text/markdown")},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                replace,
                client_one,
                csrf_one,
                "concurrent-replace-one",
                b"# Replacement one",
            )
            second = pool.submit(
                replace,
                client_two,
                csrf_two,
                "concurrent-replace-two",
                b"# Replacement two",
            )
            results = [first.result(timeout=30), second.result(timeout=30)]

        assert sorted(response.status_code for response in results) == [201, 409]
        with database.session() as session:
            documents = session.scalars(
                select(KnowledgeDocument).where(KnowledgeDocument.group_id == GROUP_DEMO_ID)
            ).all()
            old_row = session.get(KnowledgeDocument, old["id"])
            operations = session.scalars(
                select(FileOperation).where(FileOperation.operation_kind == "document_replace")
            ).all()
            assert old_row is not None and old_row.workspace_state == "hidden"
            active = [row for row in documents if row.workspace_state == "active"]
            assert len(active) == 1
            assert {row.state for row in operations} == {"committed", "recovered"}
            version = session.scalar(
                select(AgentVersion).where(AgentVersion.id == uploaded["agent_version"]["id"])
            )
            assert version is not None and version.revision == 3
        _assert_storage_recovered(database, settings.resolved_data_root)


@pytest.mark.parametrize("winner", ["replace", "publish"])
def test_replace_publish_forced_order_has_one_stable_winner(
    app_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    winner: str,
) -> None:
    app_one, database, settings = app_factory()
    app_two, _database_two, _settings_two = app_factory()
    checkpoint_entered = Event()
    release_checkpoint = Event()
    replace_entered = Event()
    publish_entered = Event()

    with (
        TestClient(app_one, raise_server_exceptions=False) as client_one,
        TestClient(app_two, raise_server_exceptions=False) as client_two,
    ):
        _user_one, csrf_one = login(client_one, "bowen")
        _user_two, csrf_two = login(client_two, "bowen")
        agent_id, version_id, uploaded = _prepare_publishable_draft(
            client_one,
            csrf_one,
            f"replace-publish-{winner}",
            f"Replace Publish {winner}",
        )
        old = uploaded["document"]
        publish_key = f"forced-publish-{winner}-123456"
        replace_key = f"forced-replace-{winner}-123456"

        if winner == "replace":
            original_checkpoint = cast(
                Callable[[str], None], cast(Any, knowledge_router).saga_checkpoint
            )

            def replace_checkpoint(boundary: str) -> None:
                original_checkpoint(boundary)
                if boundary == "replace.before_final_commit":
                    checkpoint_entered.set()
                    assert release_checkpoint.wait(timeout=20)

            monkeypatch.setattr(knowledge_router, "saga_checkpoint", replace_checkpoint)

            def replace_request() -> None:
                replace_entered.set()
                replace_result["response"] = client_one.post(
                    f"/api/v1/knowledge-documents/{old['id']}/replace",
                    headers=_headers(csrf_one, **{"Idempotency-Key": replace_key}),
                    data={
                        "expected_content_hash": old["content_hash"],
                        "expected_index_revision": str(old["index_revision"]),
                    },
                    files={"file": ("replacement.md", b"# Replaced", "text/markdown")},
                )

            replace_result: dict[str, Any] = {}
            publish_result: dict[str, Any] = {}
            replace_thread = Thread(target=replace_request)
            replace_thread.start()
            assert replace_entered.wait(timeout=15)
            assert checkpoint_entered.wait(timeout=20)

            def publish_request() -> None:
                publish_entered.set()
                publish_result["response"] = client_two.post(
                    f"/api/v1/agent-versions/{version_id}/publish",
                    headers=_headers(csrf_two, **{"Idempotency-Key": publish_key}),
                    json={"expected_revision": 2},
                )

            publish_thread = Thread(target=publish_request)
            publish_thread.start()
            assert publish_entered.wait(timeout=15)
            release_checkpoint.set()
            replace_thread.join(timeout=30)
            publish_thread.join(timeout=30)
            assert not replace_thread.is_alive() and not publish_thread.is_alive()
            assert replace_result["response"].status_code == 201
            assert publish_result["response"].status_code == 409
            assert publish_result["response"].json()["code"] in {
                "stale_revision",
                "invalid_state",
            }
        else:
            original_checkpoint = knowledge_services.saga_checkpoint
            original_references = replacement_service._draft_document_references
            release_replacement_capture = Event()
            replacement_captured = Event()

            def publish_checkpoint(boundary: str) -> None:
                original_checkpoint(boundary)
                if boundary == "publish.before_final_commit":
                    checkpoint_entered.set()
                    assert release_checkpoint.wait(timeout=20)

            monkeypatch.setattr(knowledge_services, "saga_checkpoint", publish_checkpoint)

            def captured_references(db: Any, document_id: str) -> Any:
                references = original_references(db, document_id)
                if not replacement_captured.is_set():
                    replacement_captured.set()
                    assert release_replacement_capture.wait(timeout=20)
                return references

            monkeypatch.setattr(
                replacement_service,
                "_draft_document_references",
                captured_references,
            )

            replace_result = {}
            publish_result = {}

            def publish_request() -> None:
                publish_entered.set()
                publish_result["response"] = client_one.post(
                    f"/api/v1/agent-versions/{version_id}/publish",
                    headers=_headers(csrf_one, **{"Idempotency-Key": publish_key}),
                    json={"expected_revision": 2},
                )

            def replace_request() -> None:
                replace_entered.set()
                replace_result["response"] = client_two.post(
                    f"/api/v1/knowledge-documents/{old['id']}/replace",
                    headers=_headers(csrf_two, **{"Idempotency-Key": replace_key}),
                    data={
                        "expected_content_hash": old["content_hash"],
                        "expected_index_revision": str(old["index_revision"]),
                    },
                    files={"file": ("replacement.md", b"# Replaced", "text/markdown")},
                )

            replace_thread = Thread(target=replace_request)
            replace_thread.start()
            assert replace_entered.wait(timeout=15)
            assert replacement_captured.wait(timeout=20)

            publish_thread = Thread(target=publish_request)
            publish_thread.start()
            assert publish_entered.wait(timeout=15)
            assert checkpoint_entered.wait(timeout=20)
            release_checkpoint.set()
            publish_thread.join(timeout=30)
            release_replacement_capture.set()
            replace_thread.join(timeout=30)
            assert not publish_thread.is_alive() and not replace_thread.is_alive()
            assert publish_result["response"].status_code == 200
            assert replace_result["response"].status_code == 409
            assert replace_result["response"].json()["code"] in {
                "stale_revision",
                "invalid_state",
            }

        with database.session() as session:
            old_row = session.get(KnowledgeDocument, old["id"])
            versions = session.scalars(
                select(AgentVersion).where(AgentVersion.agent_id == agent_id)
            ).all()
            operations = session.scalars(
                select(FileOperation).where(
                    FileOperation.operation_kind.in_(("document_replace", "snapshot_publish"))
                )
            ).all()
            assert old_row is not None
            if winner == "replace":
                assert old_row.workspace_state == "hidden"
                assert len([row for row in versions if row.state == "published"]) == 0
            else:
                assert old_row.workspace_state == "active"
                assert len([row for row in versions if row.state == "published"]) == 1
            assert all(row.state in {"committed", "recovered"} for row in operations)
        _assert_storage_recovered(database, settings.resolved_data_root)


def test_large_replacement_is_copy_on_write_for_every_enabled_draft_and_file(
    app_factory: Any,
) -> None:
    app, database, settings = app_factory()
    with TestClient(app, raise_server_exceptions=False) as client:
        _user, csrf = login(client, "bowen")
        _agent_one, version_one = _make_agent(client, csrf, "over-limit-one", "Limit One")
        _agent_two, version_two = _make_agent(client, csrf, "over-limit-two", "Limit Two")
        first = _upload(
            client,
            csrf,
            version_one,
            "over-limit-source",
            "original.md",
            b"# Original\n\nShared source",
            0,
        )
        old = first["document"]
        selected = client.put(
            f"/api/v1/agent-versions/{version_two}/knowledge-documents",
            headers=_headers(csrf),
            json={"expected_revision": 0, "document_ids": [old["id"]]},
        )
        assert selected.status_code == 200, selected.text

        with database.session() as session:
            old_row = session.get(KnowledgeDocument, old["id"])
            assert old_row is not None and old_row.stored_file is not None
            old_file = old_row.stored_file
            old_bytes = (settings.resolved_data_root / old_file.relative_path).read_bytes()
            before_relations = [
                (row.agent_version_id, row.document_id, row.enabled, row.order_index)
                for row in session.scalars(select(AgentVersionDocument)).all()
            ]
            before_versions = {
                row.id: (row.revision, row.state, row.knowledge_snapshot_id)
                for row in session.scalars(
                    select(AgentVersion).where(AgentVersion.id.in_([version_one, version_two]))
                ).all()
            }
            before_chunks = [
                (
                    row.id,
                    row.document_id,
                    row.chunk_index,
                    row.chunk_text,
                    row.start_offset,
                    row.end_offset,
                    row.embedding_blob,
                )
                for row in session.scalars(
                    select(KnowledgeDocumentChunk).where(
                        KnowledgeDocumentChunk.document_id == old["id"]
                    )
                ).all()
            ]
        oversized = b"# Replacement\n\n" + (b"evidence " * 12_000)
        assert len(oversized.decode("utf-8")) > 100_000
        replaced = client.post(
            f"/api/v1/knowledge-documents/{old['id']}/replace",
            headers=_headers(csrf, **{"Idempotency-Key": "over-limit-replace-123456"}),
            data={
                "expected_content_hash": old["content_hash"],
                "expected_index_revision": str(old["index_revision"]),
            },
            files={"file": ("oversized.md", oversized, "text/markdown")},
        )
        assert replaced.status_code == 201, replaced.text
        replacement = replaced.json()
        assert replacement["id"] != old["id"]
        assert replacement["char_count"] == len(oversized.decode("utf-8"))

        with database.session() as session:
            old_row = session.get(KnowledgeDocument, old["id"])
            assert old_row is not None and old_row.workspace_state == "hidden"
            assert old_row.content_hash == old["content_hash"]
            assert old_row.index_revision == old["index_revision"]
            assert old_row.stored_file is not None
            assert old_row.stored_file.id == old_file.id
            new_row = session.get(KnowledgeDocument, replacement["id"])
            assert new_row is not None and new_row.stored_file is not None
            assert (
                settings.resolved_data_root / new_row.stored_file.relative_path
            ).read_bytes() == oversized
            assert [
                (row.agent_version_id, row.document_id, row.enabled, row.order_index)
                for row in session.scalars(select(AgentVersionDocument)).all()
            ] == [
                (version_id, replacement["id"], enabled, order_index)
                for version_id, _document_id, enabled, order_index in before_relations
            ]
            after_versions = {
                row.id: (row.revision, row.state, row.knowledge_snapshot_id)
                for row in session.scalars(
                    select(AgentVersion).where(AgentVersion.id.in_([version_one, version_two]))
                ).all()
            }
            assert after_versions == {
                version_id: (revision + 1, state, snapshot_id)
                for version_id, (revision, state, snapshot_id) in before_versions.items()
            }
            after_old_chunks = [
                (
                    row.id,
                    row.document_id,
                    row.chunk_index,
                    row.chunk_text,
                    row.start_offset,
                    row.end_offset,
                    row.embedding_blob,
                )
                for row in session.scalars(
                    select(KnowledgeDocumentChunk).where(
                        KnowledgeDocumentChunk.document_id == old["id"]
                    )
                ).all()
            ]
            assert after_old_chunks == before_chunks
            new_chunks = session.scalars(
                select(KnowledgeDocumentChunk).where(
                    KnowledgeDocumentChunk.document_id == replacement["id"]
                )
            ).all()
            assert new_chunks
        assert (settings.resolved_data_root / old_file.relative_path).read_bytes() == old_bytes
        _assert_storage_recovered(database, settings.resolved_data_root)


@pytest.mark.parametrize("fault", ["index", "file", "db", "cas", "commit"])
def test_replacement_faults_recover_without_active_orphans(
    app_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    app, database, settings = app_factory()
    with TestClient(app, raise_server_exceptions=False) as client:
        _user, csrf = login(client, "bowen")
        _agent_id, _version_id, uploaded = _prepare_publishable_draft(
            client, csrf, f"replacement-fault-{fault}", f"Fault {fault}"
        )
        old = uploaded["document"]

        if fault == "index":

            def fail_index(*_args: Any, **_kwargs: Any) -> Any:
                raise RuntimeError("injected index fault")

            monkeypatch.setattr(replacement_service, "build_chunks", fail_index)
        elif fault == "file":

            def fail_file(*_args: Any, **_kwargs: Any) -> Any:
                raise RuntimeError("injected file fault")

            monkeypatch.setattr(replacement_service, "stage_atomic", fail_file)
        elif fault == "db":

            def fail_db(*_args: Any, **_kwargs: Any) -> Any:
                raise RuntimeError("injected DB fault")

            monkeypatch.setattr(replacement_service, "replace_document_chunks", fail_db)
        elif fault == "cas":
            original_references = replacement_service._draft_document_references
            reference_calls = 0

            def fail_cas(db: Any, document_id: str) -> Any:
                nonlocal reference_calls
                reference_calls += 1
                references = original_references(db, document_id)
                return () if reference_calls == 2 else references

            monkeypatch.setattr(replacement_service, "_draft_document_references", fail_cas)
        else:
            original_factory = database.session_factory

            def fail_commit_factory() -> Any:
                session = original_factory()

                def fail_commit() -> None:
                    raise RuntimeError("injected commit fault")

                session.commit = fail_commit
                return session

            cast(Any, database).session_factory = fail_commit_factory

        failed = client.post(
            f"/api/v1/knowledge-documents/{old['id']}/replace",
            headers=_headers(csrf, **{"Idempotency-Key": f"fault-{fault}-1234567"}),
            data={
                "expected_content_hash": old["content_hash"],
                "expected_index_revision": str(old["index_revision"]),
            },
            files={"file": ("replacement.md", b"# Fault replacement", "text/markdown")},
        )
        assert failed.status_code in {409, 503}, failed.text

        if fault == "commit":
            cast(Any, database).session_factory = original_factory

    restarted_app, restarted_database, _restarted_settings = app_factory()
    with TestClient(restarted_app, raise_server_exceptions=False):
        pass
    with restarted_database.session() as session:
        old_row = session.get(KnowledgeDocument, old["id"])
        assert old_row is not None and old_row.workspace_state == "active"
    _assert_storage_recovered(restarted_database, settings.resolved_data_root)


@pytest.mark.parametrize(
    "boundary",
    [
        "replace.prepared",
        "replace.staged",
        "replace.promoted",
        "replace.before_final_commit",
    ],
)
def test_replacement_checkpoint_faults_recover_after_restart(
    app_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    app, database, settings = app_factory()
    original_checkpoint = cast(Callable[[str], None], cast(Any, knowledge_router).saga_checkpoint)

    def crash(checkpoint: str) -> None:
        original_checkpoint(checkpoint)
        if checkpoint == boundary:
            raise RuntimeError("injected checkpoint fault")

    monkeypatch.setattr(knowledge_router, "saga_checkpoint", crash)
    with TestClient(app, raise_server_exceptions=False) as client:
        _user, csrf = login(client, "bowen")
        _agent_id, _version_id, uploaded = _prepare_publishable_draft(
            client, csrf, f"checkpoint-{boundary.replace('.', '-')}", "Checkpoint Fault"
        )
        old = uploaded["document"]
        failed = client.post(
            f"/api/v1/knowledge-documents/{old['id']}/replace",
            headers=_headers(csrf, **{"Idempotency-Key": f"checkpoint-{boundary}-123456"}),
            data={
                "expected_content_hash": old["content_hash"],
                "expected_index_revision": str(old["index_revision"]),
            },
            files={"file": ("replacement.md", b"# Checkpoint replacement", "text/markdown")},
        )
        assert failed.status_code == 503, failed.text

    restarted_app, restarted_database, _restarted_settings = app_factory()
    with TestClient(restarted_app, raise_server_exceptions=False):
        pass
    with restarted_database.session() as session:
        old_row = session.get(KnowledgeDocument, old["id"])
        assert old_row is not None and old_row.workspace_state == "active"
    _assert_storage_recovered(restarted_database, settings.resolved_data_root)


def test_published_and_superseded_release_fingerprint_survives_metadata_change(
    app_factory: Any,
) -> None:
    app, database, settings = app_factory()
    with TestClient(app, raise_server_exceptions=False) as client:
        _student, csrf = login(client, "bowen")
        first_agent, first_version, first_upload = _prepare_publishable_draft(
            client, csrf, "fingerprint-first", "Fingerprint First"
        )
        first_published = client.post(
            f"/api/v1/agent-versions/{first_version}/publish",
            headers=_headers(csrf, **{"Idempotency-Key": "fingerprint-publish-one"}),
            json={"expected_revision": 2},
        )
        assert first_published.status_code == 200, first_published.text

        next_version = client.post(
            f"/api/v1/agents/{first_agent}/versions",
            headers=_headers(csrf, **{"Idempotency-Key": "fingerprint-next-version"}),
        )
        assert next_version.status_code == 201, next_version.text
        second_version = next_version.json()["id"]
        _confirm_persona(client, csrf, second_version, expected_revision=0)
        second_published = client.post(
            f"/api/v1/agent-versions/{second_version}/publish",
            headers=_headers(csrf, **{"Idempotency-Key": "fingerprint-publish-two"}),
            json={"expected_revision": 0},
        )
        assert second_published.status_code == 200, second_published.text

        current_draft = client.post(
            f"/api/v1/agents/{first_agent}/versions",
            headers=_headers(csrf, **{"Idempotency-Key": "fingerprint-current-draft"}),
        )
        assert current_draft.status_code == 201, current_draft.text
        current_draft_id = current_draft.json()["id"]
        old_document_id = first_upload["document"]["id"]
        with database.session() as session:
            draft = session.get(AgentVersion, current_draft_id)
            relation = session.get(AgentVersionDocument, (current_draft_id, old_document_id))
            assert draft is not None and draft.state == "draft" and draft.revision == 0
            assert relation is not None and relation.enabled is True

        second_agent, _second_version, _second_upload = _prepare_publishable_draft(
            client, csrf, "fingerprint-other", "Fingerprint Other"
        )
        other_published = client.post(
            f"/api/v1/agent-versions/{_second_version}/publish",
            headers=_headers(csrf, **{"Idempotency-Key": "fingerprint-publish-other"}),
            json={"expected_revision": 2},
        )
        assert other_published.status_code == 200, other_published.text

        _teacher, teacher_csrf = login(client, "maya")
        debate = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(teacher_csrf, **{"Idempotency-Key": "fingerprint-debate"}),
            json={
                "topic": "Frozen inputs remain stable",
                "participants": [
                    {"agent_id": first_agent, "stance_mode": "open"},
                    {"agent_id": second_agent, "stance_mode": "open"},
                ],
                "round_count": 4,
            },
        )
        assert debate.status_code == 201, debate.text

        before = _release_fingerprint(database, settings.resolved_data_root, first_agent)
        assert {row[3] for row in before["versions"]} == {"published", "superseded"}
        assert before["snapshots"] and before["documents"] and before["chunks"]
        assert before["participants"]
        _student_again, student_csrf = login(client, "bowen")
        replaced = client.post(
            f"/api/v1/knowledge-documents/{old_document_id}/replace",
            headers=_headers(
                student_csrf,
                **{"Idempotency-Key": "fingerprint-source-replace"},
            ),
            data={
                "expected_content_hash": first_upload["document"]["content_hash"],
                "expected_index_revision": str(first_upload["document"]["index_revision"]),
            },
            files={
                "file": (
                    "history-replacement.md",
                    b"# Replaced history source",
                    "text/markdown",
                )
            },
        )
        assert replaced.status_code == 201, replaced.text
        new_document_id = replaced.json()["id"]
        with database.session() as session:
            draft = session.get(AgentVersion, current_draft_id)
            new_relation = session.get(
                AgentVersionDocument,
                (current_draft_id, new_document_id),
            )
            old_relation = session.get(
                AgentVersionDocument,
                (current_draft_id, old_document_id),
            )
            old_document = session.get(KnowledgeDocument, old_document_id)
            assert draft is not None and draft.revision == 1
            assert new_relation is not None and new_relation.enabled is True
            assert old_relation is None
            assert old_document is not None and old_document.workspace_state == "hidden"
        after = _release_fingerprint(database, settings.resolved_data_root, first_agent)
        assert after == before
