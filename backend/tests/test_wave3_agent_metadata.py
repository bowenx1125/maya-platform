from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Event, Thread
from typing import Any, cast
from uuid import UUID, uuid4

import app.modules.agents.router as agents_router
import pytest
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import (
    Agent,
    AgentVersion,
    AgentVersionDocument,
    FileOperation,
    IdempotencyRecord,
    KnowledgeDocument,
    KnowledgeSnapshot,
    ProviderOperation,
    StoredFile,
    User,
    VoiceProfile,
)
from app.modules.agents.router import delete_agent, publish_agent_version
from app.modules.agents.schemas import ExpectedRevisionRequest
from app.modules.auth.service import AuthContext
from app.modules.avatars import DEFAULT_AVATAR_CONFIG
from app.modules.debates.models import Debate, DebateParticipant
from app.modules.debates.schemas import DebateDraftRequest, DebateParticipantInput
from app.modules.debates.setup.service import create_debate_draft
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import login, make_foreign_group
from tests.persona_fixtures import confirmed_persona_fields

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_DEMO_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
KAIKAI_GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
STUDENT_BOWEN_ID = "60541c78-30f1-55c5-b2aa-207b6a766883"
TEACHER_ID = "08b9de2d-bb75-5c71-a64b-231b48f9eb25"


def _headers(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, **extra}


def _context(database: Any, user_id: str) -> AuthContext:
    """Build a detached auth context for direct independent-session races."""

    with database.session() as session:
        user = session.get(User, user_id)
        assert user is not None
    return AuthContext(
        raw_session_token="race-session",
        session=cast(Any, None),
        user=user,
        csrf_token="race-csrf",
    )


def _run_race(
    database: Any,
    first: Any,
    second: Any,
) -> tuple[Any, Any]:
    """Start two independent SQLAlchemy sessions behind one barrier."""

    barrier = Barrier(2)

    def run(operation: Any) -> Any:
        db = database.session_factory()
        try:
            barrier.wait(timeout=10)
            return operation(db)
        except Exception as error:  # preserve race evidence for the assertion
            return error
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(run, first)
        second_future = pool.submit(run, second)
        return first_future.result(timeout=30), second_future.result(timeout=30)


def _result_status(result: Any) -> int | None:
    return getattr(result, "status_code", None)


def _result_code(result: Any) -> str | None:
    return getattr(result, "code", None)


def _insert_published_agent(
    database: Any,
    *,
    group_id: str,
    name: str,
) -> tuple[str, str, str]:
    """Seed one complete immutable release for history/debate tests."""

    agent_id, version_id, snapshot_id, file_id = (str(uuid4()) for _ in range(4))
    now = datetime.now(UTC)
    relative_path = f"groups/{group_id}/knowledge/{file_id}/source.md"
    source_path = Path(database.data_root) / relative_path
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(f"# {name}\n\nEvidence.", encoding="utf-8")
    with database.session() as session:
        session.add(
            StoredFile(
                id=file_id,
                kind="markdown",
                relative_path=relative_path,
                sha256="a" * 64,
                size_bytes=10,
                state="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            Agent(
                id=agent_id,
                group_id=group_id,
                name=name,
                description=f"{name} perspective",
                metadata_revision=0,
                status="active",
                current_published_version_id=version_id,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            AgentVersion(
                id=version_id,
                agent_id=agent_id,
                version_seq=0,
                state="published",
                revision=1,
                avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
                voice_profile_id=None,
                knowledge_snapshot_id=snapshot_id,
                published_at=now,
                created_at=now,
                updated_at=now,
                **confirmed_persona_fields(name, now),
            )
        )
        session.add(
            KnowledgeSnapshot(
                id=snapshot_id,
                agent_version_id=version_id,
                stored_file_id=file_id,
                content_hash="b" * 64,
                total_char_count=10,
                embedding_key="mock",
                chunking_json="{}",
                created_at=now,
            )
        )
    return agent_id, version_id, snapshot_id


def _create_agent(
    client: TestClient,
    csrf: str,
    key: str = "wave3-create-agent-001",
    description: str = "",
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/agents",
        headers=_headers(csrf, **{"Idempotency-Key": key}),
        json={"name": "Metadata Agent", "description": description},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _prepare_draft_for_publish(
    client: TestClient,
    csrf: str,
    key_suffix: str,
) -> tuple[str, str]:
    """Create one valid draft through the public setup path."""

    agent = _create_agent(client, csrf, f"wave3-race-create-{key_suffix}")
    version = agent["versions"][0]
    version_id = version["id"]
    avatar = version["avatar_config"]
    persona_source = confirmed_persona_fields("Metadata Agent", datetime.now(UTC))["agent_md"]
    updated = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={"expected_revision": 0, "agent_md": persona_source, "avatar_config": avatar},
    )
    assert updated.status_code == 200, updated.text
    uploaded = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": f"wave3-race-upload-{key_suffix}"}),
        data={"target_agent_version_id": version_id, "expected_revision": "1"},
        files={"file": ("race.md", b"# Race\n\nEvidence", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    compiled = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/compile",
        headers=_headers(csrf),
        json={"expected_revision": 2},
    )
    assert compiled.status_code == 200, compiled.text
    compiled_body = compiled.json()
    confirmed = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/confirm",
        headers=_headers(csrf),
        json={
            "expected_revision": 2,
            "raw_agent_md_hash": compiled_body["raw_agent_md_hash"],
            "persona_spec_hash": compiled_body["persona_spec_hash"],
            "compiler_version": "persona_template_v1",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    return agent["id"], version_id


def test_metadata_patch_is_cas_only_and_empty_description_has_no_fallback(
    client: TestClient,
) -> None:
    _user, csrf = login(client, "bowen")
    agent = _create_agent(client, csrf, description="  ")
    agent_id = agent["id"]

    assert agent["metadata_revision"] == 0
    assert agent["description"] == ""
    version_id = agent["versions"][0]["id"]
    changed = client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=_headers(csrf),
        json={"expected_metadata_revision": 0, "description": "  "},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["description"] == ""
    assert changed.json()["metadata_revision"] == 1
    assert changed.json()["versions"][0]["revision"] == 0

    stale = client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=_headers(csrf),
        json={"expected_metadata_revision": 0, "description": "new"},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "stale_metadata_revision"
    assert stale.json()["details"] == {"current_metadata_revision": 1}

    filled = client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=_headers(csrf),
        json={"expected_metadata_revision": 1, "description": "A current lens"},
    )
    assert filled.status_code == 200, filled.text
    assert filled.json()["description"] == "A current lens"
    assert filled.json()["metadata_revision"] == 2
    assert client.get(f"/api/v1/agent-versions/{version_id}").status_code == 200


def test_delete_eligible_agent_removes_only_agent_draft_state(client: TestClient) -> None:
    _user, csrf = login(client, "bowen")
    agent = _create_agent(client, csrf, "wave3-delete-agent-001")
    version_id = agent["versions"][0]["id"]
    upload = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "wave3-delete-upload-001"}),
        data={"target_agent_version_id": version_id, "expected_revision": "0"},
        files={"file": ("shared.md", b"# Shared\n\nPreserve me", "text/markdown")},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["document"]["id"]

    deleted = client.delete(
        f"/api/v1/agents/{agent['id']}",
        headers=_headers(csrf, **{"Idempotency-Key": "wave3-delete-agent-001"}),
    )
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/v1/agents/{agent['id']}").status_code == 404
    assert client.get(f"/api/v1/knowledge-documents/{document_id}").status_code == 200


def test_delete_hides_agent_and_preserves_versions_group_files_and_audit(
    client: TestClient,
) -> None:
    """The delete boundary removes Agent-owned draft rows, never group data."""

    _user, csrf = login(client, "bowen")
    agent = _create_agent(client, csrf, "wave3-preserve-resources-001")
    version_id = agent["versions"][0]["id"]
    upload = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "wave3-preserve-upload-001"}),
        data={"target_agent_version_id": version_id, "expected_revision": "0"},
        files={"file": ("preserve.md", b"# Preserve\n\nShared", "text/markdown")},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["document"]["id"]

    app = cast(Any, client.app)
    database = app.state.database
    now = datetime.now(UTC)
    voice_id = str(uuid4())
    stored_file_id = str(uuid4())
    operation_id = str(uuid4())
    relative_path = f"groups/{GROUP_DEMO_ID}/unrelated/{stored_file_id}.bin"
    stored_path = Path(database.data_root) / relative_path
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_bytes(b"keep")
    with database.session() as session:
        session.add(
            VoiceProfile(
                id=voice_id,
                scope="group",
                group_id=GROUP_DEMO_ID,
                display_name="Preserved voice",
                status="ready",
                provider_key="mock",
                target_model_key="mock-voice",
                external_id_encrypted=None,
                recovery_name=f"preserved-{voice_id}",
                provenance_json="{}",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            StoredFile(
                id=stored_file_id,
                kind="voice_sample",
                relative_path=relative_path,
                sha256="c" * 64,
                size_bytes=4,
                state="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            FileOperation(
                id=operation_id,
                idempotency_record_id=None,
                operation_kind="unrelated_audit",
                entity_id=agent["id"],
                request_id=str(uuid4()),
                source_relative_path=None,
                target_relative_path=None,
                expected_sha256=None,
                state="prepared",
                safe_error_code=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        document = session.get(KnowledgeDocument, document_id)
        assert document is not None
        source_file_id = document.stored_file_id

    # Audit storage is host-owned and intentionally not an ORM Agent relation.
    # Insert a generic row in the real shared schema and prove Agent deletion
    # cannot sweep it.
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO audit_logs "
                "(id, event_type, details_json, created_at) "
                "VALUES (:id, :event_type, :details_json, :created_at)"
            ),
            {
                "id": str(uuid4()),
                "event_type": "agent.fixture_created",
                "details_json": '{"scope":"unrelated"}',
                "created_at": datetime.now(UTC),
            },
        )

    deleted = client.delete(
        f"/api/v1/agents/{agent['id']}",
        headers=_headers(csrf, **{"Idempotency-Key": "wave3-preserve-delete-001"}),
    )
    assert deleted.status_code == 204, deleted.text
    with database.session() as session:
        retained = session.get(Agent, agent["id"])
        assert retained is not None and retained.deleted_at is not None
        assert retained.status == "archived"
        assert session.get(AgentVersion, version_id) is not None
        assert session.get(AgentVersionDocument, (version_id, document_id)) is not None
        assert session.get(KnowledgeDocument, document_id) is not None
        assert session.get(StoredFile, source_file_id) is not None
        assert session.get(StoredFile, stored_file_id) is not None
        assert session.get(VoiceProfile, voice_id) is not None
        assert session.get(FileOperation, operation_id) is not None
    assert stored_path.exists()
    with database.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM audit_logs")).scalar_one() == 1


def test_delete_rejects_history_teacher_and_cross_group(
    client: TestClient, database: Database
) -> None:
    _user, csrf = login(client, "bowen")
    agent = _create_agent(client, csrf, "wave3-delete-reject-001")

    teacher, teacher_csrf = login(client, "maya")
    del teacher
    teacher_delete = client.delete(
        f"/api/v1/agents/{agent['id']}",
        headers=_headers(teacher_csrf, **{"Idempotency-Key": "wave3-teacher-delete-001"}),
    )
    assert teacher_delete.status_code == 403, teacher_delete.text

    # Delete is group-membership scoped. There is one seeded group, so the
    # cross-group branch is exercised by moving the Agent into a group the
    # caller is not a member of; it must then be not found, not forbidden.
    foreign_group_id = make_foreign_group(database, COURSE_ID)
    with database.session() as session:
        moved = session.get(Agent, agent["id"])
        assert moved is not None
        moved.group_id = foreign_group_id
        session.commit()

    _other, other_csrf = login(client, "bowen")
    cross_group = client.delete(
        f"/api/v1/agents/{agent['id']}",
        headers=_headers(other_csrf, **{"Idempotency-Key": "wave3-cross-delete-001"}),
    )
    assert cross_group.status_code == 404, cross_group.text


def test_delete_removes_unreferenced_published_agent_from_both_workspaces(
    client: TestClient,
) -> None:
    _user, csrf = login(client, "bowen")
    agent = _create_agent(client, csrf, "wave3-published-agent-001")
    metadata = client.patch(
        f"/api/v1/agents/{agent['id']}",
        headers=_headers(csrf),
        json={"expected_metadata_revision": 0, "description": "Current metadata"},
    )
    assert metadata.status_code == 200, metadata.text
    version_id = agent["versions"][0]["id"]
    avatar = agent["versions"][0]["avatar_config"]
    persona_source = confirmed_persona_fields("Metadata Agent", datetime.now(UTC))["agent_md"]
    updated = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={"expected_revision": 0, "agent_md": persona_source, "avatar_config": avatar},
    )
    assert updated.status_code == 200, updated.text
    uploaded = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "wave3-publish-upload-001"}),
        data={"target_agent_version_id": version_id, "expected_revision": "1"},
        files={"file": ("published.md", b"# Published", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    compiled = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/compile",
        headers=_headers(csrf),
        json={"expected_revision": 2},
    )
    assert compiled.status_code == 200, compiled.text
    compiled_body = compiled.json()
    confirmed = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/confirm",
        headers=_headers(csrf),
        json={
            "expected_revision": 2,
            "raw_agent_md_hash": compiled_body["raw_agent_md_hash"],
            "persona_spec_hash": compiled_body["persona_spec_hash"],
            "compiler_version": "persona_template_v1",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": "wave3-publish-agent-001"}),
        json={"expected_revision": 2},
    )
    assert published.status_code == 200, published.text

    _teacher, _teacher_csrf = login(client, "maya")
    candidates = client.get(f"/api/v1/courses/{COURSE_ID}/published-agents")
    assert candidates.status_code == 200, candidates.text
    current = next(item for item in candidates.json() if item["agent"]["id"] == agent["id"])
    assert current["agent"]["description"] == "Current metadata"
    assert current["agent"]["metadata_revision"] == 1

    _student, csrf = login(client, "bowen")
    rejected = client.delete(
        f"/api/v1/agents/{agent['id']}",
        headers=_headers(csrf, **{"Idempotency-Key": "wave3-published-delete-001"}),
    )
    assert rejected.status_code == 204, rejected.text
    assert client.get(f"/api/v1/agents/{agent['id']}").status_code == 404
    assert not any(
        item["id"] == agent["id"]
        for item in client.get(f"/api/v1/groups/{GROUP_DEMO_ID}/agents").json()
    )
    login(client, "maya")
    assert not any(
        item["agent"]["id"] == agent["id"]
        for item in client.get(f"/api/v1/courses/{COURSE_ID}/published-agents").json()
    )
    assert client.get(f"/api/v1/agent-versions/{version_id}").status_code == 404


def test_archived_legacy_agent_without_history_remains_delete_eligible(
    client: TestClient,
) -> None:
    _user, csrf = login(client, "bowen")
    agent = _create_agent(client, csrf, "wave3-legacy-archived-001")
    app = cast(Any, client.app)
    database = app.state.database
    with database.session() as session:
        row = session.get(Agent, agent["id"])
        assert row is not None
        row.status = "archived"

    listed = client.get(f"/api/v1/groups/{GROUP_DEMO_ID}/agents")
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == agent["id"] for item in listed.json())
    deleted = client.delete(
        f"/api/v1/agents/{agent['id']}",
        headers=_headers(csrf, **{"Idempotency-Key": "wave3-legacy-delete-001"}),
    )
    assert deleted.status_code == 204, deleted.text


def test_delete_idempotent_replay_is_204(client: TestClient) -> None:
    _user, csrf = login(client, "bowen")
    agent = _create_agent(client, csrf, "wave3-replay-create-001")
    headers = _headers(csrf, **{"Idempotency-Key": "wave3-replay-delete-001"})
    first = client.delete(f"/api/v1/agents/{agent['id']}", headers=headers)
    second = client.delete(f"/api/v1/agents/{agent['id']}", headers=headers)
    assert first.status_code == 204, first.text
    assert second.status_code == 204, second.text


def test_double_delete_with_a_new_key_is_a_stable_not_found(client: TestClient) -> None:
    _user, csrf = login(client, "bowen")
    agent = _create_agent(client, csrf, "wave3-double-delete-001")
    first = client.delete(
        f"/api/v1/agents/{agent['id']}",
        headers=_headers(csrf, **{"Idempotency-Key": "wave3-double-delete-a"}),
    )
    second = client.delete(
        f"/api/v1/agents/{agent['id']}",
        headers=_headers(csrf, **{"Idempotency-Key": "wave3-double-delete-b"}),
    )
    assert first.status_code == 204, first.text
    assert second.status_code == 404, second.text


def test_delete_preserves_snapshots_and_formerly_published_drafts(
    client: TestClient,
) -> None:
    """Tombstones preserve immutable records instead of bypassing their FKs."""

    app = cast(Any, client.app)
    database = app.state.database
    snapshot_agent_id, snapshot_version_id, snapshot_id = _insert_published_agent(
        database,
        group_id=GROUP_DEMO_ID,
        name="Snapshot retained",
    )
    formerly_published_id, formerly_published_version_id, _ = _insert_published_agent(
        database,
        group_id=GROUP_DEMO_ID,
        name="Formerly published",
    )
    now = datetime.now(UTC)
    formerly_draft_id = str(uuid4())
    with database.session() as session:
        formerly = session.get(Agent, formerly_published_id)
        old_version = session.get(AgentVersion, formerly_published_version_id)
        assert formerly is not None and old_version is not None
        formerly.current_published_version_id = None
        old_version.state = "superseded"
        session.add(
            AgentVersion(
                id=formerly_draft_id,
                agent_id=formerly_published_id,
                version_seq=1,
                state="draft",
                revision=0,
                agent_md="",
                avatar_config_json="{}",
                created_at=now,
                updated_at=now,
            )
        )

    # A raw FK attempt must lose as well; this proves the database guard is not
    # being bypassed by the endpoint's application-level history query.
    session = database.session_factory()
    try:
        row = session.get(Agent, snapshot_agent_id)
        assert row is not None
        session.delete(row)
        with pytest.raises(IntegrityError):
            session.flush()
    finally:
        session.rollback()
        session.close()

    _student, csrf = login(client, "bowen")
    for index, agent_id in enumerate((snapshot_agent_id, formerly_published_id)):
        response = client.delete(
            f"/api/v1/agents/{agent_id}",
            headers=_headers(csrf, **{"Idempotency-Key": f"wave3-history-{index}-001"}),
        )
        assert response.status_code == 204, response.text
        assert client.get(f"/api/v1/agents/{agent_id}").status_code == 404
    with database.session() as session:
        assert session.get(Agent, snapshot_agent_id) is not None
        assert session.get(AgentVersion, formerly_draft_id) is not None
        assert session.get(KnowledgeSnapshot, snapshot_id) is not None


def test_description_metadata_does_not_mutate_release_or_debate_inputs(
    client: TestClient,
) -> None:
    app = cast(Any, client.app)
    database = app.state.database
    first_id, first_version_id, first_snapshot_id = _insert_published_agent(
        database,
        group_id=GROUP_DEMO_ID,
        name="Metadata one",
    )
    second_id, _second_version_id, _second_snapshot_id = _insert_published_agent(
        database,
        group_id=KAIKAI_GROUP_ID,
        name="Metadata two",
    )

    _teacher, teacher_csrf = login(client, "maya")
    debate = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=_headers(teacher_csrf, **{"Idempotency-Key": "wave3-meta-debate-001"}),
        json={
            "topic": "Should evidence remain explicit?",
            "participants": [
                {"agent_id": first_id, "stance_mode": "open"},
                {"agent_id": second_id, "stance_mode": "open"},
            ],
            "round_count": 4,
        },
    )
    assert debate.status_code == 201, debate.text
    debate_payload = debate.json()
    participant_before = {item["agent_id"]: item for item in debate_payload["participants"]}[
        first_id
    ]
    with database.session() as session:
        version_before = session.get(AgentVersion, first_version_id)
        snapshot_before = session.get(KnowledgeSnapshot, first_snapshot_id)
        assert version_before is not None and snapshot_before is not None
        revision_before = version_before.revision
        version_snapshot_before = version_before.knowledge_snapshot_id
        snapshot_hash_before = snapshot_before.content_hash
        debate_before = session.get(Debate, debate_payload["id"])
        assert debate_before is not None
        topic_before = debate_before.topic

    _student, student_csrf = login(client, "bowen")
    changed = client.patch(
        f"/api/v1/agents/{first_id}",
        headers=_headers(student_csrf),
        json={"expected_metadata_revision": 0, "description": "Changed now"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["description"] == "Changed now"
    with database.session() as session:
        version_after = session.get(AgentVersion, first_version_id)
        snapshot_after = session.get(KnowledgeSnapshot, first_snapshot_id)
        participant_after = session.scalar(
            select(DebateParticipant).where(
                DebateParticipant.debate_id == debate_payload["id"],
                DebateParticipant.agent_id == first_id,
            )
        )
        debate_after = session.get(Debate, debate_payload["id"])
        assert version_after is not None
        assert snapshot_after is not None
        assert participant_after is not None
        assert debate_after is not None
        assert version_after.revision == revision_before
        assert version_after.knowledge_snapshot_id == version_snapshot_before
        assert snapshot_after.content_hash == snapshot_hash_before
        assert participant_after.agent_name == participant_before["agent_name"]
        assert participant_after.agent_version_id == participant_before["agent_version_id"]
        assert (
            participant_after.knowledge_snapshot_id == participant_before["knowledge_snapshot_id"]
        )
        assert debate_after.topic == topic_before


@pytest.mark.parametrize("operation_order", ["delete-first", "publish-first"])
def test_delete_and_publish_race_has_one_serialized_winner(
    client: TestClient,
    operation_order: str,
) -> None:
    """Independent sessions and a start barrier exercise both writer orders."""

    _student, csrf = login(client, "bowen")
    agent_id, version_id = _prepare_draft_for_publish(client, csrf, operation_order)
    database = cast(Any, client.app).state.database
    settings = cast(Any, client.app).state.settings
    student_context = _context(database, STUDENT_BOWEN_ID)
    charged_operation_id = str(uuid4())
    with database.session() as session:
        draft = session.get(AgentVersion, version_id)
        assert draft is not None
        saved_draft = (draft.agent_md, draft.revision)
        saved_documents = set(
            session.scalars(
                select(AgentVersionDocument.document_id).where(
                    AgentVersionDocument.agent_version_id == version_id
                )
            )
        )
        now = datetime.now(UTC)
        session.add(
            ProviderOperation(
                id=charged_operation_id,
                scope_id=agent_id,
                provider_operation="llm",
                logical_item_id=version_id,
                attempt_no=1,
                request_hash="a" * 64,
                max_tokens=0,
                max_cost_cny=0,
                policy_hash="b" * 64,
                export_manifest_hash="c" * 64,
                state="succeeded",
                request_count=1,
                charged_request_count=1,
                created_at=now,
                updated_at=now,
            )
        )

    def delete_operation(db: Any) -> Any:
        return delete_agent(
            UUID(agent_id),
            idempotency_key=f"wave3-race-delete-{operation_order}",
            _csrf_header="x" * 32,
            context=student_context,
            db=db,
        )

    def publish_operation(db: Any) -> Any:
        return publish_agent_version(
            UUID(version_id),
            ExpectedRevisionRequest(expected_revision=2),
            idempotency_key=f"wave3-race-publish-{operation_order}",
            _csrf_header="x" * 32,
            context=student_context,
            db=db,
            settings=settings,
        )

    first, second = (
        (delete_operation, publish_operation)
        if operation_order == "delete-first"
        else (publish_operation, delete_operation)
    )
    first_result, second_result = _run_race(database, first, second)
    delete_result = first_result if operation_order == "delete-first" else second_result
    publish_result = second_result if operation_order == "delete-first" else first_result

    if _result_status(delete_result) == 204:
        # Removal now retains a tombstone and draft for existing chat history.
        # Publication must still lose and must not create a snapshot.
        assert isinstance(publish_result, PlatformError), repr(publish_result)
        assert _result_code(publish_result) in {"not_found", "invalid_state"}
        with database.session() as session:
            removed = session.get(Agent, agent_id)
            retained = session.get(AgentVersion, version_id)
            assert removed is not None and retained is not None
            assert removed.status == "archived" and removed.deleted_at is not None
            assert removed.current_published_version_id is None
            assert retained.agent_id == removed.id and retained.state == "draft"
            assert (retained.agent_md, retained.revision) == saved_draft
            assert retained.knowledge_snapshot_id is None
            assert (
                session.scalar(
                    select(KnowledgeSnapshot.id).where(
                        KnowledgeSnapshot.agent_version_id == version_id
                    )
                )
                is None
            )
            assert (
                set(
                    session.scalars(
                        select(AgentVersionDocument.document_id).where(
                            AgentVersionDocument.agent_version_id == version_id
                        )
                    )
                )
                == saved_documents
            )
        assert client.get(f"/api/v1/agents/{agent_id}").status_code == 404
        assert client.get(f"/api/v1/agent-versions/{version_id}").status_code == 404
        visible = client.get(f"/api/v1/groups/{GROUP_DEMO_ID}/agents")
        assert visible.status_code == 200, visible.text
        assert agent_id not in {item["id"] for item in visible.json()}
    else:
        # Publication committed first: the delete's final history check must
        # lose with the stable retained-history error.
        assert _result_code(delete_result) == "agent_history_retained", repr(delete_result)
        assert not isinstance(publish_result, Exception), repr(publish_result)
        with database.session() as session:
            published = session.get(Agent, agent_id)
            version = session.get(AgentVersion, version_id)
            assert published is not None and version is not None
            assert version.state == "published"
            assert published.current_published_version_id == version_id

    with database.session() as session:
        charged = session.get(ProviderOperation, charged_operation_id)
        assert charged is not None
        assert (charged.state, charged.request_count, charged.charged_request_count) == (
            "succeeded",
            1,
            1,
        )
        assert charged.logical_item_id == version_id


@pytest.mark.parametrize("operation_order", ["delete-first", "debate-first"])
def test_delete_and_create_debate_race_is_fk_safe(
    client: TestClient,
    operation_order: str,
) -> None:
    """A Debate participant and an Agent delete cannot both commit."""

    database = cast(Any, client.app).state.database
    first_agent_id, _first_version_id, _first_snapshot_id = _insert_published_agent(
        database,
        group_id=GROUP_DEMO_ID,
        name=f"Race one {operation_order}",
    )
    second_agent_id, _second_version_id, _second_snapshot_id = _insert_published_agent(
        database,
        group_id=KAIKAI_GROUP_ID,
        name=f"Race two {operation_order}",
    )
    payload = DebateDraftRequest(
        topic="Can a race preserve frozen inputs?",
        round_count=4,
        participants=[
            DebateParticipantInput(agent_id=UUID(first_agent_id), stance_mode="open"),
            DebateParticipantInput(agent_id=UUID(second_agent_id), stance_mode="open"),
        ],
    )
    student_context = _context(database, STUDENT_BOWEN_ID)

    def delete_operation(db: Any) -> Any:
        return delete_agent(
            UUID(first_agent_id),
            idempotency_key=f"wave3-debate-race-delete-{operation_order}",
            _csrf_header="x" * 32,
            context=student_context,
            db=db,
        )

    def debate_operation(db: Any) -> Any:
        result = create_debate_draft(
            db,
            actor_user_id=TEACHER_ID,
            course_id=COURSE_ID,
            payload=payload,
            idempotency_key=f"wave3-debate-race-create-{operation_order}",
        )
        # Route dependencies commit after the service returns.  Mirror that
        # boundary for this direct independent-session race.
        db.commit()
        return result

    first, second = (
        (delete_operation, debate_operation)
        if operation_order == "delete-first"
        else (debate_operation, delete_operation)
    )
    first_result, second_result = _run_race(database, first, second)
    delete_result = first_result if operation_order == "delete-first" else second_result
    debate_result = second_result if operation_order == "delete-first" else first_result

    with database.session() as session:
        retained = session.get(Agent, first_agent_id)
        assert retained is not None
        participants = session.scalars(
            select(DebateParticipant).where(
                DebateParticipant.agent_id == first_agent_id,
            )
        ).all()
        if _result_status(delete_result) == 204:
            assert isinstance(debate_result, PlatformError), repr(debate_result)
            assert retained.deleted_at is not None
            assert len(participants) == 0
        else:
            assert _result_code(delete_result) == "agent_history_retained", repr(delete_result)
            assert not isinstance(debate_result, Exception), repr(debate_result)
            assert retained.deleted_at is None
            assert len(participants) == 1


@pytest.mark.parametrize("publish_first", [False, True])
def test_http_publish_delete_order_has_stable_envelopes_and_terminal_claims(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    publish_first: bool,
) -> None:
    """Force each commit order through the real HTTP routes and DB sessions."""

    _student, csrf = login(client, "bowen")
    agent_id, version_id = _prepare_draft_for_publish(
        client,
        csrf,
        "publish-first" if publish_first else "delete-first",
    )
    app = cast(Any, client.app)
    database = app.state.database
    publish_key = f"wave3-http-publish-{int(publish_first)}"
    delete_key = f"wave3-http-delete-{int(publish_first)}"
    guard_ready = Event()
    release_publish = Event()
    publish_result: dict[str, Any] = {}
    original_guard = agents_router._acquire_publish_guard

    def controlled_guard(*args: Any, **kwargs: Any) -> Any:
        if publish_first:
            result = original_guard(*args, **kwargs)
            guard_ready.set()
            assert release_publish.wait(timeout=15)
            return result
        guard_ready.set()
        assert release_publish.wait(timeout=15)
        return original_guard(*args, **kwargs)

    monkeypatch.setattr(agents_router, "_acquire_publish_guard", controlled_guard)

    def publish_request() -> None:
        publish_result["response"] = client.post(
            f"/api/v1/agent-versions/{version_id}/publish",
            headers=_headers(csrf, **{"Idempotency-Key": publish_key}),
            json={"expected_revision": 2},
        )

    thread = Thread(target=publish_request)
    thread.start()
    assert guard_ready.wait(timeout=15)
    deleted = client.delete(
        f"/api/v1/agents/{agent_id}",
        headers=_headers(csrf, **{"Idempotency-Key": delete_key}),
    )
    release_publish.set()
    thread.join(timeout=30)
    assert not thread.is_alive()
    published = publish_result.get("response")
    assert published is not None

    with database.session() as session:
        claims = {
            row.key: row.state
            for row in session.scalars(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.key.in_((publish_key, delete_key))
                )
            ).all()
        }
        guards = session.scalars(
            select(FileOperation).where(
                FileOperation.operation_kind == "agent_publish_guard",
                FileOperation.entity_id == agent_id,
            )
        ).all()
        snapshots = session.scalars(
            select(KnowledgeSnapshot)
            .join(
                AgentVersion,
                AgentVersion.id == KnowledgeSnapshot.agent_version_id,
            )
            .where(AgentVersion.agent_id == agent_id)
        ).all()
        versions = session.scalars(
            select(AgentVersion).where(AgentVersion.agent_id == agent_id)
        ).all()
        snapshot_operations = session.scalars(
            select(FileOperation).where(
                FileOperation.operation_kind == "snapshot_publish",
                FileOperation.entity_id.in_([item.id for item in snapshots]),
            )
        ).all()
        snapshot_files = session.scalars(
            select(StoredFile).where(
                StoredFile.kind.in_(("snapshot_rag", "snapshot_source")),
                StoredFile.relative_path.like("snapshots/%"),
            )
        ).all()

    assert claims[publish_key] in {"completed", "abandoned"}
    assert claims[delete_key] in {"completed", "abandoned"}
    if publish_first:
        assert published.status_code == 200, published.text
        assert published.json()["state"] == "published"
        assert deleted.status_code == 409, deleted.text
        assert deleted.json()["code"] == "agent_history_retained"
        assert claims[publish_key] == "completed"
        assert claims[delete_key] == "abandoned"
        assert len(snapshots) == 1
        assert len(versions) == 1 and versions[0].state == "published"
        assert len(guards) == 1 and guards[0].state == "committed"
        assert len(snapshot_operations) == 1 and snapshot_operations[0].state == "committed"
        assert snapshot_files and all(item.state == "active" for item in snapshot_files)
    else:
        assert deleted.status_code == 204, deleted.text
        assert published.status_code == 404, published.text
        assert published.json()["code"] == "not_found"
        assert claims[publish_key] == "abandoned"
        assert claims[delete_key] == "completed"
        assert snapshots == []
        assert len(versions) == 1 and versions[0].state == "draft"
        assert guards == []
        assert snapshot_operations == []
        assert snapshot_files == []


def test_publish_failure_recovers_guard_and_abandons_pending_claim(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-guard failure leaves no pending writer fence or partial release."""

    _student, csrf = login(client, "bowen")
    agent_id, version_id = _prepare_draft_for_publish(client, csrf, "failure-recovery")
    app = cast(Any, client.app)
    database = app.state.database
    publish_key = "wave3-publish-failure-001"

    def fail_snapshot(*_args: Any, **_kwargs: Any) -> Any:
        raise PlatformError("injected_publish_failure", "Injected publish failure.", 503)

    monkeypatch.setattr(agents_router, "create_snapshot", fail_snapshot)
    failed = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": publish_key}),
        json={"expected_revision": 2},
    )
    assert failed.status_code == 503, failed.text
    assert failed.json()["code"] == "injected_publish_failure"
    with database.session() as session:
        claim = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.operation == "publishAgentVersion",
                IdempotencyRecord.key == publish_key,
            )
        )
        guard = session.scalar(
            select(FileOperation).where(
                FileOperation.operation_kind == "agent_publish_guard",
                FileOperation.entity_id == agent_id,
            )
        )
        agent = session.get(Agent, agent_id)
        version = session.get(AgentVersion, version_id)
        snapshots = session.scalars(
            select(KnowledgeSnapshot)
            .join(
                AgentVersion,
                AgentVersion.id == KnowledgeSnapshot.agent_version_id,
            )
            .where(AgentVersion.agent_id == agent_id)
        ).all()
        assert claim is not None and claim.state == "abandoned"
        assert guard is not None and guard.state == "recovered"
        assert agent is not None and agent.current_published_version_id is None
        assert version is not None and version.state == "draft"
        assert snapshots == []
