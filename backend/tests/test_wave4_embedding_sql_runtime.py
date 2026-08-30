"""SQL control-ledger integration for the injected W4-EMBED runtime."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.core.db import Database
from app.modules.knowledge.providers import (
    InMemorySnapshotPublicationStore,
    MockEmbeddingProvider,
    SnapshotBuildV1,
    SnapshotEmbeddingRuntime,
    SqlAlchemyEmbeddingControlAdapter,
    prepare_snapshot_build,
)
from app.providers.control import (
    FIXED_MODELS,
    ExportFieldV1,
    ExportManifestV1,
    ProviderPolicySnapshotV1,
    confirm_export_manifest,
)
from app.providers.control_repository import PolicyExportStale, ProviderRepository


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
) -> tuple[SqlAlchemyEmbeddingControlAdapter, ProviderRepository, SnapshotBuildV1]:
    build = _build()
    policy = _policy()
    manifest = ExportManifestV1(
        scope_id=build.build_id,
        provider_operation="embedding",
        model_key=FIXED_MODELS["embedding"],
        policy_hash=policy.policy_hash,
        build_manifest_hash=build.manifest_hash,
        persona_spec_hash=build.persona_spec_hash,
        fields=(
            ExportFieldV1("current_evidence_excerpt", _digest("chunks")),
            ExportFieldV1("opaque_local_id", _digest("chunk-ids")),
        ),
    )
    repository = ProviderRepository(database)
    policy_id = repository.save_policy_snapshot(policy)
    manifest_id = repository.save_export_manifest(
        manifest,
        policy_snapshot_id=policy_id,
    )
    if confirmed:
        repository.save_export_confirmation(
            manifest_id,
            confirm_export_manifest(
                manifest,
                policy,
                confirmed_at=datetime.now(UTC).isoformat(),
            ),
        )
    return (
        SqlAlchemyEmbeddingControlAdapter(
            database,
            policy_hash=policy.policy_hash,
            export_manifest_hash=manifest.manifest_hash,
            build_manifest_hash=manifest.build_manifest_hash,
        ),
        repository,
        build,
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
    assert budget.max_requests == 20
    assert budget.max_total_tokens == 120_000
    assert budget.max_cost_cny == pytest.approx(0.10)
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
