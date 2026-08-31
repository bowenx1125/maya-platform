"""Zero-network recovery helpers for the accepted LLM stage ledger.

Recovery deliberately delegates only to the durable control repository.  A
stranded ``reserved`` attempt becomes ``not_sent``; ``sending`` and incomplete
accepted attempts become ``acceptance_unknown``; a complete accepted stage is
left available for local validation/publication.  This module has no provider
transport dependency, so importing or running it cannot issue a request.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.providers.control import ProviderOperationV1


class LLMRecoveryRepository(Protocol):
    """Minimal repository port required for startup reconciliation."""

    def recover_llm_startup(self) -> tuple[ProviderOperationV1, ...]:
        """Reconcile stranded operations without invoking a provider."""


def recover_llm_startup(
    repository: LLMRecoveryRepository,
) -> tuple[ProviderOperationV1, ...]:
    """Run deterministic zero-network recovery for LLM operations only."""

    return repository.recover_llm_startup()


def recover_provider_startup(
    repository: LLMRecoveryRepository,
) -> Sequence[ProviderOperationV1]:
    """Compatibility alias for callers that treat recovery as a sequence."""

    return recover_llm_startup(repository)


__all__ = ["LLMRecoveryRepository", "recover_llm_startup", "recover_provider_startup"]
