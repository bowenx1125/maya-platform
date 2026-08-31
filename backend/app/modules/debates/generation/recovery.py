"""Restart-safe local recovery for W4-LLM-A operations.

Recovery deliberately has no transport dependency.  ``reserved`` operations
that never committed ``sending`` may be released by the ledger; stranded
``sending`` operations become ``acceptance_unknown`` and are never retried.
An accepted stage can be handed back to the runtime for local validation and
atomic publication without issuing another provider request.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from .runtime import (
    LLMAcceptedStagePort,
    LLMAcceptedStageV1,
    LLMRunOutcomeV1,
    LLMRuntimeError,
    LLMTurnRuntime,
    _operation_id,
    _operation_state,
)
from .types import GenerationContext, MutualLearningTurnResultV1


class LLMRecoveryLedgerPort(Protocol):
    """Minimal startup recovery view implemented by the durable ledger."""

    def recover_startup(self) -> Sequence[object]: ...

    def get(self, operation_id: str) -> object | None: ...


@dataclass(frozen=True, slots=True)
class LLMRecoveryReportV1:
    """Safe startup summary; no response body or provider metadata."""

    recovered_operations: tuple[str, ...] = ()
    acceptance_unknown_operations: tuple[str, ...] = ()
    resumable_accepted_operations: tuple[str, ...] = ()
    failed_operations: tuple[str, ...] = ()


class LLMRecoveryService:
    """Run ledger recovery and local accepted-stage continuation."""

    def __init__(
        self,
        ledger: LLMRecoveryLedgerPort | object,
        *,
        stage_store: LLMAcceptedStagePort | None = None,
        runtime: LLMTurnRuntime | None = None,
    ) -> None:
        self.ledger = ledger
        self.stage_store = stage_store
        self.runtime = runtime

    def recover_startup(self) -> LLMRecoveryReportV1:
        """Recover stranded states with zero transport calls."""

        method = getattr(self.ledger, "recover_startup", None)
        if not callable(method):
            return LLMRecoveryReportV1()
        values = tuple(
            item
            for item in method()
            if str(getattr(item, "provider_operation", "")) == "llm_debate_turn"
        )
        recovered: list[str] = []
        unknown: list[str] = []
        resumable: list[str] = []
        failed: list[str] = []
        for operation in values:
            identifier = _operation_id(operation)
            if identifier is None:
                continue
            state = _operation_state(operation)
            if state in {"not_sent", "acceptance_unknown"}:
                recovered.append(identifier)
            if state == "acceptance_unknown":
                unknown.append(identifier)
            if state == "accepted":
                resumable.append(identifier)
            if state == "failed":
                failed.append(identifier)
        return LLMRecoveryReportV1(
            recovered_operations=tuple(recovered),
            acceptance_unknown_operations=tuple(unknown),
            resumable_accepted_operations=tuple(resumable),
            failed_operations=tuple(failed),
        )

    recover = recover_startup

    def resume_accepted(
        self,
        operation_id: str,
        *,
        context: GenerationContext | None = None,
        validator: object | None = None,
        result_loader: Callable[[LLMAcceptedStageV1], MutualLearningTurnResultV1] | None = None,
    ) -> LLMRunOutcomeV1:
        """Validate/publish one staged accepted response without transport."""

        if self.stage_store is None or self.runtime is None:
            return LLMRunOutcomeV1("failed", safe_error_code="llm_recovery_unavailable")
        operation = self._get(operation_id)
        if operation is None or _operation_state(operation) != "accepted":
            return LLMRunOutcomeV1(
                "failed", operation=operation, safe_error_code="llm_stage_unavailable"
            )
        getter = getattr(self.stage_store, "get_llm_accepted_stage", None)
        if not callable(getter):
            getter = getattr(self.stage_store, "get", None)
        stage = getter(operation_id) if callable(getter) else None
        if stage is None:
            marker = getattr(self.ledger, "mark_acceptance_unknown", None)
            if callable(marker):
                try:
                    operation = marker(operation_id, safe_error_code="accepted_stage_missing")
                except Exception:
                    pass
            return LLMRunOutcomeV1(
                "acceptance_unknown",
                operation=operation,
                safe_error_code="accepted_stage_missing",
            )
        try:
            if result_loader is None:
                output = __import__("json").loads(stage.output_json)
                from .prompt_request import PromptRequestV1

                # A stage intentionally does not retain the canonical request
                # text.  Production adapters should supply ``result_loader``
                # from their immutable request rows; refusing here is safer
                # than inventing a request or touching the transport.
                del output, PromptRequestV1
                raise LLMRuntimeError(
                    "accepted stage request is unavailable", code="llm_recovery_unavailable"
                )
            loaded = result_loader(stage)
            receipts: Sequence[object] = ()
            queries: Sequence[object] = ()
            result = loaded
            if (
                isinstance(loaded, tuple)
                and loaded
                and isinstance(loaded[0], MutualLearningTurnResultV1)
            ):
                result = loaded[0]
                if len(loaded) > 1:
                    receipts = loaded[1]
                if len(loaded) > 2:
                    queries = loaded[2]
            resume = getattr(self.runtime, "resume_accepted_stage", None)
            if callable(resume):
                return resume(
                    stage,
                    result,
                    context=context,
                    receipts=receipts,
                    queries=queries,
                    validator=validator,
                )
            return LLMRunOutcomeV1(
                "succeeded",
                operation=operation,
                stage=stage,
                result=result,
            )
        except LLMRuntimeError as exc:
            return LLMRunOutcomeV1(
                "failed",
                operation=operation,
                stage=stage,
                safe_error_code=exc.code,
            )
        except Exception:
            return LLMRunOutcomeV1(
                "failed",
                operation=operation,
                stage=stage,
                safe_error_code="llm_recovery_failed",
            )

    def _get(self, operation_id: str) -> object | None:
        getter = getattr(self.ledger, "get", None)
        return getter(operation_id) if callable(getter) else None


def recover_llm_startup(ledger: LLMRecoveryLedgerPort | object) -> LLMRecoveryReportV1:
    """Explicit application-start hook; importing this module does no work."""

    return LLMRecoveryService(ledger).recover_startup()


startup_recovery_hook = recover_llm_startup


LLMRuntimeRecovery = LLMRecoveryService


__all__ = [
    "LLMRecoveryLedgerPort",
    "LLMRecoveryReportV1",
    "LLMRecoveryService",
    "LLMRuntimeRecovery",
    "recover_llm_startup",
    "startup_recovery_hook",
]
