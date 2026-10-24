"""Failed uploads and empty abandoned Agents are removed, not left behind."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.core.models import (
    Agent,
    AgentVersion,
    KnowledgeDocument,
    StoredFile,
    VoiceProfile,
    VoiceProviderOperation,
)
from app.modules.agents.cleanup import sweep_abandoned_agents
from app.modules.knowledge.recovery import purge_failed_knowledge_uploads
from app.modules.teams.models import TeamVersionMember
from app.modules.voices.cleanup import sweep_failed_voices
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_mayaform_team_conversations import _team
from tests.test_wave1_agents_knowledge import GROUP_DEMO_ID, _headers, _make_agent


def test_a_new_upload_that_never_indexes_is_not_kept(
    client: TestClient, database: Any, monkeypatch: Any
) -> None:
    from app.modules.knowledge import router as knowledge_router

    _user, csrf = login(client, "bowen")
    _agent, version_id = _make_agent(client, csrf)

    def fail_chunks(_text: str) -> list[object]:
        raise RuntimeError("injected index failure")

    monkeypatch.setattr(knowledge_router, "build_chunks", fail_chunks)
    failed = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "junk-upload-index-fail-1"}),
        data={"target_agent_version_id": version_id, "expected_revision": "0"},
        files={"file": ("missed.md", b"# Missed\n\nnot kept", "text/markdown")},
    )
    assert failed.status_code == 503, failed.text
    assert failed.json()["code"] == "rag_index_failed"
    with database.session() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeDocument)
                .where(KnowledgeDocument.source_filename == "missed.md")
            )
            == 0
        )


def test_purge_removes_only_never_indexed_failed_uploads(app_factory: Any) -> None:
    app, database, settings = app_factory()
    with TestClient(app):
        pass
    now = datetime.now(UTC)
    failed_id = str(uuid4())
    failed_file_id = str(uuid4())
    kept_id = str(uuid4())
    kept_file_id = str(uuid4())
    root = settings.resolved_data_root
    failed_path = root / "groups" / GROUP_DEMO_ID / "failed-upload.md"
    kept_path = root / "groups" / GROUP_DEMO_ID / "reindex-failed.md"
    failed_path.parent.mkdir(parents=True, exist_ok=True)
    failed_path.write_bytes(b"# failed")
    kept_path.write_bytes(b"# kept")
    with database.session() as db:
        db.add_all(
            [
                StoredFile(
                    id=failed_file_id,
                    kind="markdown",
                    relative_path=f"groups/{GROUP_DEMO_ID}/failed-upload.md",
                    sha256="a" * 64,
                    size_bytes=8,
                    state="active",
                    created_at=now,
                    updated_at=now,
                ),
                StoredFile(
                    id=kept_file_id,
                    kind="markdown",
                    relative_path=f"groups/{GROUP_DEMO_ID}/reindex-failed.md",
                    sha256="b" * 64,
                    size_bytes=6,
                    state="active",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                KnowledgeDocument(
                    id=failed_id,
                    group_id=GROUP_DEMO_ID,
                    source_filename="failed-upload.md",
                    stored_file_id=failed_file_id,
                    char_count=8,
                    index_status="failed",
                    index_revision=0,
                    safe_error_code="provider_unavailable",
                    workspace_state="active",
                    content_hash="a" * 64,
                    created_at=now,
                    updated_at=now,
                ),
                KnowledgeDocument(
                    id=kept_id,
                    group_id=GROUP_DEMO_ID,
                    source_filename="reindex-failed.md",
                    stored_file_id=kept_file_id,
                    char_count=6,
                    index_status="failed",
                    index_revision=1,
                    safe_error_code="provider_unavailable",
                    workspace_state="active",
                    content_hash="b" * 64,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        db.commit()
        assert purge_failed_knowledge_uploads(db, root) == 1
        db.commit()
    assert not failed_path.exists()
    assert kept_path.read_bytes() == b"# kept"
    with database.session() as db:
        assert db.get(KnowledgeDocument, failed_id) is None
        assert db.get(StoredFile, failed_file_id) is None
        assert db.get(KnowledgeDocument, kept_id) is not None


def _draft(client: TestClient, csrf: str, name: str, key: str) -> tuple[str, str]:
    created = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/agents",
        headers=_headers(csrf, **{"Idempotency-Key": key}),
        json={"name": name, "description": "", "visibility": "private"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    return body["id"], body["versions"][0]["id"]


def test_sweep_removes_old_empty_agents_and_failed_voices(
    client: TestClient, database: Any
) -> None:
    _user, csrf = login(client, "bowen")
    old_empty, old_version = _draft(client, csrf, "Old empty", "junk-old-empty-agent-01")
    recent, _recent_version = _draft(client, csrf, "Recent empty", "junk-recent-empty-agent1")
    written, written_version = _draft(client, csrf, "Written draft", "junk-written-draft-ag01")
    team, _versions, _csrf = _team(client, database)
    _, csrf = login(client, "bowen")
    referenced, referenced_version = _draft(
        client, csrf, "Referenced empty", "junk-referenced-empty01"
    )
    retired, _retired_version = _draft(client, csrf, "Retired empty", "junk-retired-empty-ag01")
    old = datetime.now(UTC) - timedelta(hours=2)
    refused = str(uuid4())
    charged = str(uuid4())
    enroll_failed = str(uuid4())
    supplier_held = str(uuid4())
    with database.session() as db:
        draft = db.get(AgentVersion, written_version)
        assert draft is not None
        draft.agent_md = "# Kept"
        for agent_id in (old_empty, written, referenced, retired):
            agent = db.get(Agent, agent_id)
            assert agent is not None
            agent.updated_at = old
        retired_row = db.get(Agent, retired)
        assert retired_row is not None
        # What a same-name retry leaves: a soft-deleted empty draft.
        retired_row.deleted_at = old
        retired_row.status = "archived"
        db.add(
            TeamVersionMember(
                id=str(uuid4()),
                team_version_id=team["current_version_id"],
                agent_id=referenced,
                agent_version_id=referenced_version,
                position=2,
                is_leader=False,
                display_name="Referenced empty",
                avatar_config_json="{}",
                own_knowledge_set_snapshots_json="[]",
                raw_source_fences_json="[]",
                created_at=old,
            )
        )
        db.add_all(
            [
                VoiceProfile(
                    id=refused,
                    scope="personal",
                    group_id=None,
                    display_name="Refused sample",
                    status="failed",
                    provider_key="mock",
                    target_model_key="qwen3-tts-flash",
                    recovery_name=f"refused-{uuid4()}",
                    provenance_json="{}",
                    safe_error_code="voice_clone_refused",
                    created_at=old,
                    updated_at=old,
                ),
                VoiceProfile(
                    id=charged,
                    scope="personal",
                    group_id=None,
                    display_name="Charged refusal",
                    status="failed",
                    provider_key="mock",
                    target_model_key="qwen3-tts-flash",
                    recovery_name=f"charged-{uuid4()}",
                    provenance_json="{}",
                    safe_error_code="voice_clone_refused",
                    created_at=old,
                    updated_at=old,
                ),
                VoiceProfile(
                    id=enroll_failed,
                    scope="personal",
                    group_id=None,
                    display_name="Enrollment failed",
                    status="failed",
                    provider_key="mock",
                    target_model_key="qwen3-tts-flash",
                    recovery_name=f"enroll-failed-{uuid4()}",
                    provenance_json="{}",
                    safe_error_code="voice_enrollment_failed",
                    created_at=old,
                    updated_at=old,
                ),
                VoiceProfile(
                    id=supplier_held,
                    scope="personal",
                    group_id=None,
                    display_name="Degraded with a supplier voice",
                    status="failed",
                    provider_key="mock",
                    target_model_key="qwen3-tts-flash",
                    recovery_name=f"supplier-held-{uuid4()}",
                    provenance_json="{}",
                    external_id_encrypted=b"sealed",
                    safe_error_code="voice_enrollment_failed",
                    created_at=old,
                    updated_at=old,
                ),
            ]
        )
        db.flush()
        db.add(
            VoiceProviderOperation(
                id=str(uuid4()),
                profile_id=charged,
                operation_type="enroll",
                profile_scope="personal",
                state="failed",
                attempt=1,
                claim_token="t" * 16,
                request_hash="c" * 64,
                provider_deadline=old,
                charged_request_count=1,
                safe_error_code="voice_clone_refused",
                created_at=old,
                updated_at=old,
            )
        )
        db.commit()
        assert sweep_abandoned_agents(db) >= 1
        assert sweep_failed_voices(db) == 3
    with database.session() as db:
        assert db.get(Agent, old_empty) is None
        assert db.get(AgentVersion, old_version) is None
        assert db.get(Agent, recent) is not None
        assert db.get(Agent, written) is not None
        assert db.get(Agent, referenced) is not None
        assert db.get(Agent, retired) is None
        assert db.get(VoiceProfile, refused) is None
        assert db.get(VoiceProfile, enroll_failed) is None
        kept = db.get(VoiceProfile, supplier_held)
        assert kept is not None and kept.status == "failed"
        # Real deletion (#242): a charged failure goes too, ledger rows with it.
        assert db.get(VoiceProfile, charged) is None
        assert (
            db.scalar(
                select(VoiceProviderOperation).where(VoiceProviderOperation.profile_id == charged)
            )
            is None
        )
