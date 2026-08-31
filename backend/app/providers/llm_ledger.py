"""Provider-neutral LLM accepted-stage/usage ledger ports.

The concrete SQL implementation remains in ``control_repository``.  This
module gives the LLM runtime a small dependency-free boundary for staging an
accepted response before product validation and for loading it during local
restart recovery.
"""

from __future__ import annotations

from typing import Protocol

from app.providers.control import LLMAcceptedStageV1


class LLMStageStore(Protocol):
    """Immutable accepted-stage persistence needed by a turn runtime."""

    def stage_llm_accepted(self, stage: LLMAcceptedStageV1) -> LLMAcceptedStageV1:
        """Persist an accepted stage and advance the operation to ``accepted``."""

    def get_llm_accepted_stage(self, operation_id: str) -> LLMAcceptedStageV1 | None:
        """Read one stage for local validation/publication recovery."""


AcceptedLLMStageV1 = LLMAcceptedStageV1
LLMUsageLedgerV1 = LLMAcceptedStageV1


__all__ = ["AcceptedLLMStageV1", "LLMAcceptedStageV1", "LLMStageStore", "LLMUsageLedgerV1"]
