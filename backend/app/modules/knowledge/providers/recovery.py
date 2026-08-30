"""Zero-network startup reconciliation for durable Embedding attempts."""

from __future__ import annotations

from app.core.db import Database
from app.providers.control import ProviderOperationV1
from app.providers.control_repository import ProviderRepository

from .sql_stage import SqlAlchemyEmbeddingStageStore


def recover_embedding_provider_startup(
    database: Database,
) -> tuple[ProviderOperationV1, ...]:
    """Reconcile stranded embedding ledger rows without calling a provider.

    A committed ``reserved`` row proves that transport was never permitted and
    can release its allowance.  ``sending`` can never be inferred accepted.
    ``accepted`` remains locally resumable only when the complete sanitized
    stage agrees with every frozen operation identity; otherwise it becomes
    acceptance-unknown and is never retried automatically.
    """

    repository = ProviderRepository(database)
    stages = SqlAlchemyEmbeddingStageStore(database)
    recovered: list[ProviderOperationV1] = []
    for operation in repository.operations():
        if operation.provider_operation != "embedding" or operation.state not in {
            "reserved",
            "sending",
            "accepted",
        }:
            continue
        if operation.state == "reserved":
            recovered.append(
                repository.mark_not_sent(
                    operation.id,
                    safe_error_code="recovered_not_sent",
                )
            )
            continue
        if operation.state == "sending":
            recovered.append(
                repository.mark_acceptance_unknown(
                    operation.id,
                    safe_error_code="recovered_acceptance_unknown",
                )
            )
            continue
        try:
            stage = stages.get(operation.id)
        except Exception:
            stage = None
        if (
            stage is not None
            and operation.staged_response_hash == stage.response_hash
            and operation.scope_id == stage.build_id
            and operation.build_manifest_hash == stage.build_manifest_hash
            and operation.model_key == stage.model_key
        ):
            recovered.append(operation)
            continue
        recovered.append(
            repository.mark_acceptance_unknown(
                operation.id,
                safe_error_code="recovered_stage_invalid",
            )
        )
    return tuple(recovered)


__all__ = ["recover_embedding_provider_startup"]
