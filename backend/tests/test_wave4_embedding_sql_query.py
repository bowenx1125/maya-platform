"""Durable SQL control tests for the injected W4 query embedding seam."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.core.db import Database
from app.modules.knowledge.providers.adapters import (
    EmbeddingAcceptanceUnknown,
    EmbeddingTransportNotSent,
)
from app.modules.knowledge.providers.embedding import ValidatedEmbeddingBatchV1
from app.modules.knowledge.providers.query_embedding import (
    QueryEmbeddingError,
    QueryEmbeddingProviderError,
    QueryEmbeddingService,
    query_hash,
)
from app.modules.knowledge.providers.runtime import AcceptedEmbeddingStageV1, EmbeddingStagePort
from app.modules.knowledge.providers.sql_query import (
    SQL_QUERY_MAX_REQUESTS,
    SQL_QUERY_MAX_TOTAL_TOKENS,
    SQL_QUERY_PROVIDER_OPERATION,
    SqlAlchemyQueryControlAdapter,
    SqlQueryBudgetError,
    SqlQueryIdentityError,
    SqlQueryPreflightError,
    SqlQueryStageError,
    controlled_query_provider,
)
from app.modules.knowledge.vector import REAL_EMBEDDING_IDENTITY
from app.providers.control import (
    ExportFieldV1,
    ExportManifestV1,
    ProviderPolicySnapshotV1,
    confirm_export_manifest,
)
from app.providers.control_repository import ProviderRepository


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _policy() -> ProviderPolicySnapshotV1:
    return ProviderPolicySnapshotV1(
        privacy_notice_retrieved_at="2026-08-31T00:00:00Z",
        privacy_notice_sha256=_digest("privacy"),
        service_terms_retrieved_at="2026-08-31T00:00:00Z",
        service_terms_sha256=_digest("terms"),
        faq_retrieved_at="2026-08-31T00:00:00Z",
        faq_sha256=_digest("faq"),
        no_training_basis="payg-api-terms-2026-08-31",
        prompt_response_logging_disabled=True,
        inference_log_backflow_disabled=True,
        optional_content_logging_disabled=True,
        service_improvement_disabled=True,
        storage_disclosed=True,
        retention_setting="unknown",
    )


@dataclass
class _Provider:
    calls: list[Any] = field(default_factory=list)
    failures: list[Exception] = field(default_factory=list)

    provider: str = REAL_EMBEDDING_IDENTITY.provider
    model_key: str = REAL_EMBEDDING_IDENTITY.model_key
    region: str = REAL_EMBEDDING_IDENTITY.region
    dimension: int = REAL_EMBEDDING_IDENTITY.dimension
    policy_version: str = REAL_EMBEDDING_IDENTITY.policy_version

    def embed_batch(self, batch: Any) -> ValidatedEmbeddingBatchV1:
        self.calls.append(batch)
        if self.failures:
            raise self.failures.pop(0)
        return ValidatedEmbeddingBatchV1(
            build_id=batch.build_id,
            build_manifest_hash=batch.build_manifest_hash,
            batch_index=batch.batch_index,
            chunk_ids=batch.chunk_ids,
            vectors=tuple((0.125,) * batch.dimension for _ in batch.items),
            model_key=batch.model_key,
            dimension=batch.dimension,
            embedding_provider=batch.embedding_provider,
            embedding_region=batch.embedding_region,
            policy_version=batch.policy_version,
        )


@dataclass
class _AtomicStage(EmbeddingStagePort):
    repository: ProviderRepository
    values: dict[str, AcceptedEmbeddingStageV1] = field(default_factory=dict)

    def get(self, operation_id: str) -> AcceptedEmbeddingStageV1 | None:
        return self.values.get(operation_id)

    def stage_accepted(self, value: AcceptedEmbeddingStageV1) -> AcceptedEmbeddingStageV1:
        current = self.repository.operation(value.operation_id)
        if current.state == "accepted":
            if current.staged_response_hash != value.response_hash:
                raise SqlQueryStageError("stage response hash changed")
        elif current.state == "sending":
            self.repository.mark_accepted(value.operation_id, response_hash=value.response_hash)
        else:
            raise SqlQueryStageError("stage operation is not sending")
        existing = self.values.get(value.operation_id)
        if existing is not None and existing != value:
            raise SqlQueryStageError("stage changed")
        self.values[value.operation_id] = value
        return value

    stage_and_accept = stage_accepted


@dataclass
class _BrokenStage(EmbeddingStagePort):
    error: Exception = field(default_factory=lambda: RuntimeError("corrupt stage"))

    def get(self, operation_id: str) -> AcceptedEmbeddingStageV1 | None:
        raise self.error

    def stage_accepted(self, value: AcceptedEmbeddingStageV1) -> AcceptedEmbeddingStageV1:
        raise self.error


def _snapshot(snapshot_id: str = "snapshot-query-sql") -> SimpleNamespace:
    return SimpleNamespace(
        id=snapshot_id,
        embedding_provider=REAL_EMBEDDING_IDENTITY.provider,
        embedding_model_key=REAL_EMBEDDING_IDENTITY.model_key,
        embedding_region=REAL_EMBEDDING_IDENTITY.region,
        embedding_dimension=REAL_EMBEDDING_IDENTITY.dimension,
        embedding_policy_version=REAL_EMBEDDING_IDENTITY.policy_version,
        source_filename="private/source.md",
        private_metadata={"student_id": "private"},
    )


def _fixture(
    tmp_path: Path,
    *,
    query_texts: tuple[str, ...] = ("alpha", "beta"),
    scope_id: str = "debate-turn-sql",
    attempt_no: int = 1,
    logical_item_id: str | None = "turn-query-item",
    snapshot_id: str = "snapshot-query-sql",
) -> tuple[
    Database,
    ProviderRepository,
    SqlAlchemyQueryControlAdapter,
    QueryEmbeddingService,
    _Provider,
    _AtomicStage,
]:
    database = Database(f"sqlite:///{tmp_path / f'{attempt_no}-{scope_id}.sqlite3'}")
    database.initialize_schema()
    policy = _policy()
    build_hash = _digest("snapshot-build")
    hashes = tuple(query_hash(value) for value in query_texts)
    manifest = ExportManifestV1(
        scope_id=scope_id,
        provider_operation=SQL_QUERY_PROVIDER_OPERATION,
        model_key=REAL_EMBEDDING_IDENTITY.model_key,
        policy_hash=policy.policy_hash,
        build_manifest_hash=build_hash,
        persona_spec_hash=_digest("persona"),
        fields=(
            ExportFieldV1("current_evidence_excerpt", _digest("evidence")),
            ExportFieldV1("opaque_local_id", _digest("query-ids")),
        ),
    )
    repository = ProviderRepository(database)
    policy_id = repository.save_policy_snapshot(policy)
    manifest_id = repository.save_export_manifest(manifest, policy_snapshot_id=policy_id)
    repository.save_export_confirmation(
        manifest_id,
        confirmation=confirm_export_manifest(
            manifest,
            policy,
            confirmed_at=datetime.now(UTC).isoformat(),
        ),
    )
    control = SqlAlchemyQueryControlAdapter(
        database,
        scope_id=scope_id,
        snapshot_id=snapshot_id,
        identity=REAL_EMBEDDING_IDENTITY,
        policy_hash=policy.policy_hash,
        export_manifest_hash=manifest.manifest_hash,
        build_manifest_hash=build_hash,
        query_hashes=hashes,
        attempt_no=attempt_no,
        logical_item_id=logical_item_id,
    )
    provider = _Provider()
    stage = _AtomicStage(repository)
    wrapped = controlled_query_provider(provider, control=control, stage_store=stage)
    service = QueryEmbeddingService(
        provider=wrapped,
        manifest=control,
        control=control,
        budget=control,
        build_manifest_hash=build_hash,
    )
    return database, repository, control, service, provider, stage


def test_sql_query_lifecycle_persists_one_sanitized_attempt_and_succeeds(
    tmp_path: Path,
) -> None:
    database, repository, control, service, provider, stage = _fixture(tmp_path)
    values = service.embed_subqueries(_snapshot(), ("alpha", "beta", "alpha"))

    assert len(values) == 3
    assert values[0] is values[2]
    assert len(provider.calls) == 1
    operation = control.operation
    assert operation is not None
    assert operation.state == "succeeded"
    assert operation.provider_operation == SQL_QUERY_PROVIDER_OPERATION
    assert repository.operations(scope_id=control.request.scope_id)[0].state == "succeeded"
    assert len(stage.values) == 1
    database.dispose()


def test_sql_operation_and_stage_projection_do_not_persist_query_or_private_metadata(
    tmp_path: Path,
) -> None:
    database, _repository, control, service, _provider, stage = _fixture(tmp_path)
    service.embed_subqueries(_snapshot(), ("alpha", "beta"))

    operation = control.operation
    assert operation is not None
    operation_record = json.dumps(
        operation.as_record(),
        sort_keys=True,
    )
    stage_record = repr(tuple(stage.values.values()))
    assert "alpha" not in operation_record
    assert "beta" not in operation_record
    assert "private/source.md" not in operation_record
    assert "student" not in operation_record
    assert "alpha" not in stage_record
    assert "private/source.md" not in stage_record
    database.dispose()


def test_sql_query_restart_reuses_complete_stage_without_provider_call(tmp_path: Path) -> None:
    database, repository, control, service, provider, stage = _fixture(tmp_path)
    first = service.embed_subqueries(_snapshot(), ("alpha", "beta"))
    assert len(provider.calls) == 1

    resumed_control = SqlAlchemyQueryControlAdapter(
        database,
        scope_id=control.request.scope_id,
        snapshot_id=control.request.snapshot_id,
        identity=control.request.identity,
        policy_hash=control.request.policy_hash,
        export_manifest_hash=control.request.export_manifest_hash,
        build_manifest_hash=control.request.build_manifest_hash,
        query_hashes=control.request.query_hashes,
        attempt_no=control.request.attempt_no,
        logical_item_id=control.logical_item_id,
    )
    resumed_provider = _Provider()
    resumed = QueryEmbeddingService(
        provider=controlled_query_provider(
            resumed_provider,
            control=resumed_control,
            stage_store=stage,
        ),
        manifest=resumed_control,
        control=resumed_control,
        budget=resumed_control,
        build_manifest_hash=control.request.build_manifest_hash,
    )
    second = resumed.embed_subqueries(_snapshot(), ("alpha", "beta"))
    assert second == first
    assert resumed_provider.calls == []
    assert repository.operations(scope_id=control.request.scope_id)[0].state == "succeeded"
    database.dispose()


@pytest.mark.parametrize("failure", (EmbeddingTransportNotSent(), EmbeddingAcceptanceUnknown()))
def test_not_sent_releases_budget_but_unknown_forbids_next_attempt(
    tmp_path: Path,
    failure: Exception,
) -> None:
    database, repository, control, service, provider, _stage = _fixture(
        tmp_path,
        query_texts=("alpha",),
    )
    provider.failures.append(failure)
    if isinstance(failure, EmbeddingTransportNotSent):
        with pytest.raises(EmbeddingTransportNotSent):
            service.embed_query(_snapshot(), "alpha")
    else:
        with pytest.raises(EmbeddingAcceptanceUnknown):
            service.embed_query(_snapshot(), "alpha")
    first = repository.operations(scope_id=control.request.scope_id)[0]
    expected_state = (
        "not_sent" if isinstance(failure, EmbeddingTransportNotSent) else "acceptance_unknown"
    )
    assert first.state == expected_state
    with database.engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT allocated_requests, allocated_total_tokens "
            "FROM provider_scope_budgets WHERE scope_id = ?",
            (control.request.scope_id,),
        ).one()
    if isinstance(failure, EmbeddingTransportNotSent):
        assert tuple(row) == (0, 0)
        second_control = SqlAlchemyQueryControlAdapter(
            database,
            scope_id=control.request.scope_id,
            snapshot_id=control.request.snapshot_id,
            identity=control.request.identity,
            policy_hash=control.request.policy_hash,
            export_manifest_hash=control.request.export_manifest_hash,
            build_manifest_hash=control.request.build_manifest_hash,
            query_hashes=control.request.query_hashes,
            attempt_no=2,
            logical_item_id=control.logical_item_id,
        )
        second_provider = _Provider()
        second_stage = _AtomicStage(repository)
        second_service = QueryEmbeddingService(
            provider=controlled_query_provider(
                second_provider,
                control=second_control,
                stage_store=second_stage,
            ),
            manifest=second_control,
            control=second_control,
            budget=second_control,
            build_manifest_hash=control.request.build_manifest_hash,
        )
        second_service.embed_query(_snapshot(), "alpha")
        assert len(second_provider.calls) == 1
        assert repository.operations(scope_id=control.request.scope_id)[-1].state == "succeeded"
    else:
        assert tuple(row)[0] == 1
        with pytest.raises(SqlQueryBudgetError, match="retry"):
            retry_control = SqlAlchemyQueryControlAdapter(
                database,
                scope_id=control.request.scope_id,
                snapshot_id=control.request.snapshot_id,
                identity=control.request.identity,
                policy_hash=control.request.policy_hash,
                export_manifest_hash=control.request.export_manifest_hash,
                build_manifest_hash=control.request.build_manifest_hash,
                query_hashes=control.request.query_hashes,
                attempt_no=2,
                logical_item_id=control.logical_item_id,
            )
            retry_control.reserve_query(
                snapshot_id=control.request.snapshot_id,
                identity=control.request.identity,
                query_hashes=control.request.query_hashes,
                request_count=1,
                total_tokens=1,
            )
    database.dispose()


def test_query_hash_mismatch_and_manifest_drift_fail_before_provider(tmp_path: Path) -> None:
    database, _repository, control, service, provider, _stage = _fixture(
        tmp_path,
        query_texts=("alpha",),
    )
    with pytest.raises(QueryEmbeddingError):
        service.embed_query(_snapshot(), "different")
    assert provider.calls == []
    with pytest.raises(SqlQueryPreflightError):
        control.require_exact_manifest(
            snapshot_id=control.request.snapshot_id,
            identity=control.request.identity,
            query_hashes=("f" * 64,),
        )
    database.dispose()


def test_provider_identity_and_hard_scope_caps_fail_closed(tmp_path: Path) -> None:
    database, repository, control, _service, _provider, _stage = _fixture(
        tmp_path,
        query_texts=("alpha",),
    )
    with pytest.raises(SqlQueryIdentityError):
        controlled_query_provider(
            _Provider(provider="mock"),
            control=control,
            stage_store=_AtomicStage(repository),
        )

    # The cap is enforced by the durable SQL repository, not by an in-memory
    # counter.  Each logical item is distinct so the request uniqueness fence
    # does not obscure the 25-request allowance.
    for index in range(SQL_QUERY_MAX_REQUESTS):
        text = f"query-{index}"
        scoped_control = SqlAlchemyQueryControlAdapter(
            database,
            scope_id=control.request.scope_id,
            snapshot_id=control.request.snapshot_id,
            identity=control.request.identity,
            policy_hash=control.request.policy_hash,
            export_manifest_hash=control.request.export_manifest_hash,
            build_manifest_hash=control.request.build_manifest_hash,
            query_hashes=(query_hash(text),),
            logical_item_id=f"logical-{index}",
        )
        scoped_provider = _Provider()
        scoped_service = QueryEmbeddingService(
            provider=controlled_query_provider(
                scoped_provider,
                control=scoped_control,
                stage_store=_AtomicStage(repository),
            ),
            manifest=scoped_control,
            control=scoped_control,
            budget=scoped_control,
            build_manifest_hash=control.request.build_manifest_hash,
        )
        scoped_service.embed_query(_snapshot(), text)
        assert scoped_control.operation is not None
    assert len(repository.operations(scope_id=control.request.scope_id)) == SQL_QUERY_MAX_REQUESTS
    blocked_control = SqlAlchemyQueryControlAdapter(
        database,
        scope_id=control.request.scope_id,
        snapshot_id=control.request.snapshot_id,
        identity=control.request.identity,
        policy_hash=control.request.policy_hash,
        export_manifest_hash=control.request.export_manifest_hash,
        build_manifest_hash=control.request.build_manifest_hash,
        query_hashes=(query_hash("query-over-cap"),),
        logical_item_id="logical-over-cap",
    )
    with pytest.raises(SqlQueryBudgetError):
        blocked_control.reserve_query(
            snapshot_id=control.request.snapshot_id,
            identity=control.request.identity,
            query_hashes=blocked_control.request.query_hashes,
            request_count=1,
            total_tokens=1,
        )
    assert (
        len(repository.operations(scope_id=control.request.scope_id)) == SQL_QUERY_MAX_REQUESTS + 1
    )
    database.dispose()


def test_missing_stage_fails_closed_without_second_provider_call(tmp_path: Path) -> None:
    database, repository, control, service, provider, _stage = _fixture(
        tmp_path,
        query_texts=("alpha",),
    )
    service.embed_query(_snapshot(), "alpha")
    assert len(provider.calls) == 1
    broken = _BrokenStage()
    resumed_control = SqlAlchemyQueryControlAdapter(
        database,
        scope_id=control.request.scope_id,
        snapshot_id=control.request.snapshot_id,
        identity=control.request.identity,
        policy_hash=control.request.policy_hash,
        export_manifest_hash=control.request.export_manifest_hash,
        build_manifest_hash=control.request.build_manifest_hash,
        query_hashes=control.request.query_hashes,
        attempt_no=control.request.attempt_no,
        logical_item_id=control.logical_item_id,
    )
    resumed_provider = _Provider()
    resumed = QueryEmbeddingService(
        provider=controlled_query_provider(
            resumed_provider,
            control=resumed_control,
            stage_store=broken,
        ),
        manifest=resumed_control,
        control=resumed_control,
        budget=resumed_control,
        build_manifest_hash=control.request.build_manifest_hash,
    )
    with pytest.raises(QueryEmbeddingProviderError):
        resumed.embed_query(_snapshot(), "alpha")
    assert resumed_provider.calls == []
    assert repository.operations(scope_id=control.request.scope_id)[0].state == "succeeded"
    database.dispose()


def test_query_request_caps_are_frozen() -> None:
    assert SQL_QUERY_MAX_REQUESTS == 25
    assert SQL_QUERY_MAX_TOTAL_TOKENS == 150_000
