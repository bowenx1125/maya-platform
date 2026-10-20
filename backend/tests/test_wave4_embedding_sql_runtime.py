"""SQL control-ledger integration for the injected W4-EMBED runtime."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import (
    Agent,
    AgentVersion,
    AgentVersionDocument,
    IdempotencyRecord,
    KnowledgeDocument,
    KnowledgeSnapshot,
    User,
)
from app.modules.agents.markdown import markdown_hash
from app.modules.knowledge.providers import (
    MOCK_EMBEDDING_MODEL,
    InMemorySnapshotPublicationStore,
    MockEmbeddingProvider,
    SnapshotBuildV1,
    SnapshotEmbeddingRuntime,
    SnapshotEmbeddingRuntimeError,
    SqlAlchemyEmbeddingControlAdapter,
    SqlAlchemyEmbeddingStageStore,
    SqlAlchemySnapshotPublicationStore,
    plan_embedding_batches,
    prepare_snapshot_build,
    recover_embedding_provider_startup,
    reservation_request_for_batch,
)
from app.modules.knowledge.providers.snapshot_build import SnapshotBuildInputDocument
from app.modules.knowledge.providers.sql_runtime import (
    EMBEDDING_MAX_COST_CNY,
    EMBEDDING_MAX_REQUESTS,
    EMBEDDING_MAX_TOTAL_TOKENS,
)
from app.modules.knowledge.services import document_file_content, renew_idempotency_lease
from app.providers.control import (
    ExportFieldV1,
    ExportManifestV1,
    ProviderPolicySnapshotV1,
    confirm_export_manifest,
)
from app.providers.control_repository import PolicyExportStale, ProviderRepository
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.persona_fixtures import confirmed_persona_fields
from tests.test_wave1_agents_knowledge import GROUP_DEMO_ID, _headers


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _build() -> SnapshotBuildV1:
    return prepare_snapshot_build(
        agent_version_id="agent-version-sql-runtime",
        knowledge_snapshot_id="snapshot-sql-runtime",
        draft_revision=3,
        persona_spec_hash=_digest("persona"),
        documents=(
            {
                "document_id": "document-sql-runtime",
                "source_filename": "lesson.md",
                "text": "A bounded formal lesson about recommendation governance.",
            },
        ),
    )


def _policy() -> ProviderPolicySnapshotV1:
    return ProviderPolicySnapshotV1(
        privacy_notice_retrieved_at="2026-08-30T00:00:00Z",
        privacy_notice_sha256=_digest("privacy"),
        service_terms_retrieved_at="2026-08-30T00:00:00Z",
        service_terms_sha256=_digest("terms"),
        faq_retrieved_at="2026-08-30T00:00:00Z",
        faq_sha256=_digest("faq"),
        no_training_basis="payg-api-terms-2026-08-30",
        prompt_response_logging_disabled=True,
        inference_log_backflow_disabled=True,
        optional_content_logging_disabled=True,
        service_improvement_disabled=True,
        storage_disclosed=True,
        retention_setting="unknown",
    )


def _prepare_control(
    database: Database,
    *,
    confirmed: bool,
    build: SnapshotBuildV1 | None = None,
    policy: ProviderPolicySnapshotV1 | None = None,
) -> tuple[SqlAlchemyEmbeddingControlAdapter, ProviderRepository, SnapshotBuildV1]:
    selected_build = build or _build()
    selected_policy = policy or _policy()
    manifest = ExportManifestV1(
        scope_id=selected_build.build_id,
        provider_operation="embedding",
        model_key=MOCK_EMBEDDING_MODEL,
        policy_hash=selected_policy.policy_hash,
        build_manifest_hash=selected_build.manifest_hash,
        persona_spec_hash=selected_build.persona_spec_hash,
        fields=(
            ExportFieldV1("current_evidence_excerpt", _digest("chunks")),
            ExportFieldV1("opaque_local_id", _digest("chunk-ids")),
        ),
    )
    repository = ProviderRepository(database)
    policy_id = repository.save_policy_snapshot(selected_policy)
    manifest_id = repository.save_export_manifest(
        manifest,
        policy_snapshot_id=policy_id,
    )
    if confirmed:
        repository.save_export_confirmation(
            manifest_id,
            confirm_export_manifest(
                manifest,
                selected_policy,
                confirmed_at=datetime.now(UTC).isoformat(),
            ),
        )
    return (
        SqlAlchemyEmbeddingControlAdapter(
            database,
            policy_hash=selected_policy.policy_hash,
            export_manifest_hash=manifest.manifest_hash,
            build_manifest_hash=manifest.build_manifest_hash,
        ),
        repository,
        selected_build,
    )


def test_sql_control_adapter_runs_confirmed_fake_embedding_with_durable_budget(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path}/embedding-control.sqlite3")
    database.initialize_schema()
    control, repository, build = _prepare_control(database, confirmed=True)
    provider = MockEmbeddingProvider()
    runtime = SnapshotEmbeddingRuntime(
        control=control,
        provider=provider,
        publisher=InMemorySnapshotPublicationStore(),
        provider_operation="embedding",
    )

    result = runtime.run(build, scope_id=build.build_id, current_build=build)

    assert result.status == "succeeded"
    assert provider.call_count == len(result.plan.batches)
    operations = repository.operations(scope_id=build.build_id)
    assert operations and all(operation.state == "succeeded" for operation in operations)
    budget = repository.get_scope_budget(build.build_id)
    assert budget is not None
    assert budget.max_requests == EMBEDDING_MAX_REQUESTS
    assert budget.max_total_tokens == EMBEDDING_MAX_TOTAL_TOKENS
    assert budget.max_cost_cny == pytest.approx(EMBEDDING_MAX_COST_CNY)
    database.dispose()


def test_sql_stage_store_commits_vectors_and_acceptance_before_publication(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path}/embedding-stage.sqlite3")
    database.initialize_schema()
    control, repository, build = _prepare_control(database, confirmed=True)
    provider = MockEmbeddingProvider()
    stages = SqlAlchemyEmbeddingStageStore(database)
    runtime = SnapshotEmbeddingRuntime(
        control=control,
        provider=provider,
        publisher=InMemorySnapshotPublicationStore(),
        stage_store=stages,
        provider_operation="embedding",
    )

    result = runtime.run(build, scope_id=build.build_id, current_build=build)

    assert result.status == "succeeded"
    assert provider.call_count == len(result.plan.batches)
    saved = stages.values(build_id=build.build_id)
    assert len(saved) == len(result.plan.batches)
    assert tuple(stage.batch_index for stage in saved) == tuple(range(len(result.plan.batches)))
    assert all(stage.embedding_provider == "mock" for stage in saved)
    assert all(stage.embedding_region == "local" for stage in saved)
    assert all(stage.model_key == "mock-sha256-v1" for stage in saved)
    assert all(stage.dimension == 256 for stage in saved)
    assert all(stage.policy_version == "w4-mock-v1" for stage in saved)
    operations = repository.operations(scope_id=build.build_id)
    assert operations and all(operation.state == "succeeded" for operation in operations)
    assert all(operation.staged_response_hash for operation in operations)
    database.dispose()


def test_sql_stage_store_rejects_corrupt_vector_without_silent_shape_repair(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path}/embedding-stage-corrupt.sqlite3")
    database.initialize_schema()
    control, _repository, build = _prepare_control(database, confirmed=True)
    stages = SqlAlchemyEmbeddingStageStore(database)
    result = SnapshotEmbeddingRuntime(
        control=control,
        provider=MockEmbeddingProvider(),
        publisher=InMemorySnapshotPublicationStore(),
        stage_store=stages,
        provider_operation="embedding",
    ).run(build, scope_id=build.build_id, current_build=build)
    operation_id = result.operations[0].id
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE embedding_accepted_vectors SET embedding_blob = X'0000' "
            "WHERE operation_id = ? AND item_index = 0",
            (operation_id,),
        )

    with pytest.raises(SnapshotEmbeddingRuntimeError) as raised:
        stages.get(operation_id)

    assert raised.value.code == "embedding_stage_invalid"
    database.dispose()


def test_provider_publish_lease_renewal_is_bounded_and_exact_token_cas(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path}/embedding-lease.sqlite3")
    database.initialize_schema()
    timestamp = datetime.now(UTC)
    with database.session() as db:
        db.add(
            User(
                id="bowen",
                username="embedding-lease-student",
                display_name="Embedding Lease Student",
                status="active",
                created_at=timestamp,
            )
        )
        db.flush()
        db.add(
            IdempotencyRecord(
                id="embedding-publish-lease",
                actor_user_id="bowen",
                operation="publishAgentVersion",
                key="embedding-publish-lease-key",
                request_hash="a" * 64,
                state="pending",
                claim_token="exact-claim-token",
                lease_expires_at=timestamp + timedelta(seconds=60),
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        db.commit()
    with database.session() as db:
        record = db.get(IdempotencyRecord, "embedding-publish-lease")
        assert record is not None
        renewed = renew_idempotency_lease(db, record, lease_seconds=900)
        assert renewed > timestamp + timedelta(seconds=60)
    with database.session() as db:
        record = db.get(IdempotencyRecord, "embedding-publish-lease")
        assert record is not None
        persisted_expiry = record.lease_expires_at
        if persisted_expiry.tzinfo is None:
            persisted_expiry = persisted_expiry.replace(tzinfo=UTC)
        assert persisted_expiry >= renewed
        record.claim_token = "replaced-token"
        db.commit()
        record.claim_token = "exact-claim-token"
        with pytest.raises(PlatformError, match="no longer owned"):
            renew_idempotency_lease(db, record, lease_seconds=900)
    database.dispose()


def test_embedding_startup_recovery_never_retries_and_preserves_complete_stage(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path}/embedding-recovery.sqlite3")
    database.initialize_schema()
    control, repository, build = _prepare_control(database, confirmed=True)
    batch = plan_embedding_batches(build).batches[0]

    reserved = control.create_prepared(
        reservation_request_for_batch(
            batch,
            scope_id=build.build_id,
            attempt_no=1,
            provider_operation="embedding",
        )
    )
    control.reserve(reserved)
    recovered = recover_embedding_provider_startup(database)
    assert tuple(item.state for item in recovered) == ("not_sent",)

    sending = control.create_prepared(
        reservation_request_for_batch(
            batch,
            scope_id=build.build_id,
            attempt_no=2,
            provider_operation="embedding",
        )
    )
    control.reserve(sending)
    control.mark_sending(sending.id)
    recovered = recover_embedding_provider_startup(database)
    assert tuple(item.state for item in recovered) == ("acceptance_unknown",)

    class ProcessCrash(BaseException):
        pass

    class CrashAfterAcceptedStage:
        atomic_operation_success = True

        def publish_atomic(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            raise ProcessCrash

    other_build = prepare_snapshot_build(
        agent_version_id=build.agent_version_id,
        knowledge_snapshot_id="snapshot-recovery-accepted",
        draft_revision=build.draft_revision,
        persona_spec_hash=build.persona_spec_hash,
        documents=tuple(
            {
                "document_id": document.document_id,
                "source_filename": document.source_filename,
                "text": document.normalized_text,
                "order_index": document.order_index,
                "source_sha256": document.source_sha256,
            }
            for document in build.documents
        ),
    )
    accepted_control, _other_repository, _ = _prepare_control(
        database,
        confirmed=True,
        build=other_build,
        policy=replace(_policy(), snapshot_revision=2),
    )
    provider = MockEmbeddingProvider()
    with pytest.raises(ProcessCrash):
        SnapshotEmbeddingRuntime(
            control=accepted_control,
            provider=provider,
            publisher=CrashAfterAcceptedStage(),  # type: ignore[arg-type]
            stage_store=SqlAlchemyEmbeddingStageStore(database),
            provider_operation="embedding",
        ).run(
            other_build,
            scope_id=other_build.build_id,
            current_build=other_build,
        )
    assert provider.call_count == 1
    recovered = recover_embedding_provider_startup(database)
    assert tuple(item.state for item in recovered) == ("accepted",)
    assert provider.call_count == 1
    accepted_operation = repository.operations(scope_id=other_build.build_id)[0]
    assert accepted_operation.state == "accepted"
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "DELETE FROM embedding_accepted_vectors WHERE operation_id = ?",
            (accepted_operation.id,),
        )
    recovered = recover_embedding_provider_startup(database)
    assert tuple(item.state for item in recovered) == ("acceptance_unknown",)
    assert provider.call_count == 1
    database.dispose()


def test_unconfirmed_sql_manifest_fails_before_fake_provider_call(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path}/embedding-unconfirmed.sqlite3")
    database.initialize_schema()
    control, _repository, build = _prepare_control(database, confirmed=False)
    provider = MockEmbeddingProvider()
    runtime = SnapshotEmbeddingRuntime(
        control=control,
        provider=provider,
        publisher=InMemorySnapshotPublicationStore(),
        provider_operation="embedding",
    )

    with pytest.raises(PolicyExportStale):
        runtime.run(build, scope_id=build.build_id, current_build=build)
    assert provider.call_count == 0
    database.dispose()


def test_sql_publisher_commits_real_vector_snapshot_and_operation_success_atomically(
    client: TestClient,
) -> None:
    app = cast(FastAPI, client.app)
    database = app.state.database
    settings = app.state.settings
    assert isinstance(database, Database)
    _user, csrf = login(client, "bowen")
    created = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/agents",
        headers=_headers(csrf, **{"Idempotency-Key": "embed-sql-publish-agent-001"}),
        json={"name": "Embedding Publisher", "description": "Runtime publication fixture"},
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    version_id = agent["versions"][0]["id"]
    raw = confirmed_persona_fields("Embedding Publisher", datetime.now(UTC))["agent_md"]
    updated = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={
            "expected_revision": 0,
            "agent_md": raw,
            "avatar_config": agent["versions"][0]["avatar_config"],
        },
    )
    assert updated.status_code == 200, updated.text
    uploaded = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "embed-sql-publish-doc-001"}),
        data={"target_agent_version_id": version_id, "expected_revision": "1"},
        files={
            "file": (
                "lesson.md",
                b"# Formal lesson\n\nRecommendation governance needs accountable evidence.",
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text

    data_root = settings.resolved_data_root
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        assert version is not None
        agent_row = db.get(Agent, version.agent_id)
        assert agent_row is not None
        documents = list(
            db.scalars(
                select(KnowledgeDocument)
                .join(
                    AgentVersionDocument,
                    AgentVersionDocument.document_id == KnowledgeDocument.id,
                )
                .where(
                    AgentVersionDocument.agent_version_id == version.id,
                    AgentVersionDocument.enabled.is_(True),
                )
                .order_by(AgentVersionDocument.order_index)
            ).all()
        )
        build = prepare_snapshot_build(
            agent_version_id=version.id,
            knowledge_snapshot_id=str(uuid4()),
            draft_revision=version.revision,
            persona_spec_hash=markdown_hash(version.agent_md),
            documents=tuple(
                SnapshotBuildInputDocument.from_bytes(
                    document_id=document.id,
                    source_filename=document.source_filename,
                    source_bytes=document_file_content(data_root, document),
                    order_index=index,
                )
                for index, document in enumerate(documents)
            ),
        )
        control, repository, _ = _prepare_control(database, confirmed=True, build=build)
        provider = MockEmbeddingProvider()
        publisher = SqlAlchemySnapshotPublicationStore(
            db,
            data_root=data_root,
            version=version,
            agent=agent_row,
            expected_revision=version.revision,
        )
        result = SnapshotEmbeddingRuntime(
            control=control,
            provider=provider,
            publisher=publisher,
            provider_operation="embedding",
        ).run(build, scope_id=build.build_id, current_build=build)
        assert result.status == "succeeded"
        assert result.snapshot_id == build.knowledge_snapshot_id

    with database.session() as db:
        published = db.get(AgentVersion, version_id)
        assert published is not None and published.state == "published"
        assert published.knowledge_snapshot_id == build.knowledge_snapshot_id
        snapshot = db.get(KnowledgeSnapshot, build.knowledge_snapshot_id)
        assert snapshot is not None and snapshot.embedding_key == "mock-sha256-v1"
        assert snapshot.chunks
        assert all(chunk.embedding_dimension == 256 for chunk in snapshot.chunks)
    operations = repository.operations(scope_id=build.build_id)
    assert operations and all(operation.state == "succeeded" for operation in operations)
