"""Restart-safe local recovery for W4-LLM-A operations.

Recovery deliberately has no transport dependency.  ``reserved`` operations
that never committed ``sending`` may be released by the ledger; stranded
``sending`` operations become ``acceptance_unknown`` and are never retried.
An accepted stage can be handed back to the runtime for local validation and
atomic publication without issuing another provider request.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from app.providers.control import LLMRecoveryInputV1
from app.providers.llm_adapter import LLMAcceptedCandidateV1, LLMRequestV1

from .mutual_learning_prompts import mutual_learning_platform_rules
from .prompt_budget import preflight_prompt_budget
from .prompt_request import (
    PromptMessageV1,
    PromptRequestV1,
    ProviderPromptV1,
    render_prompt_system_message,
)
from .recovery_input import (
    context_from_recovery_input,
    queries_from_recovery_input,
    receipts_from_recovery_input,
    request_from_recovery_input,
)
from .runtime import (
    LLMAcceptedStageV1,
    LLMRunOutcomeV1,
    LLMRuntimeError,
    LLMTurnRuntime,
    _operation_id,
    _operation_state,
)
from .types import GenerationContext, MutualLearningTurnResultV1


def _stage_read(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, (str, float)):
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default
    return default


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _text_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _participant_fence(value: object) -> tuple[object, ...]:
    return (
        _stage_read(value, "participant_id", ""),
        _stage_read(value, "agent_id", ""),
        _stage_read(value, "slot", ""),
        _as_int(_stage_read(value, "order_index", 0)),
        _stage_read(value, "snapshot_id", ""),
        _stage_read(value, "stance_mode", "open"),
        _stage_read(value, "initial_stance"),
        _stage_read(value, "current_stance"),
        _stage_read(value, "persona_spec_hash"),
    )


def _plan_fence(value: object) -> tuple[object, ...]:
    predecessor_ids = _stage_read(value, "predecessor_ids", ()) or ()
    return (
        _stage_read(value, "turn_id", ""),
        _stage_read(value, "participant_id", ""),
        _stage_read(value, "slot", ""),
        _as_int(_stage_read(value, "order_index", 0)),
        _as_int(_stage_read(value, "round_no", 0)),
        _as_int(_stage_read(value, "turn_index", 0)),
        _stage_read(value, "phase", ""),
        _stage_read(value, "next_participant_id"),
        bool(_stage_read(value, "is_final", False)),
        tuple(str(item) for item in _sequence(predecessor_ids)),
        _stage_read(value, "barrier", "prefix"),
        bool(_stage_read(value, "is_final_round", False)),
    )


def _predecessor_fence(value: object) -> tuple[object, ...]:
    predecessor_ids = _stage_read(value, "predecessor_turn_ids", ()) or ()
    return (
        _stage_read(value, "turn_id", ""),
        _stage_read(value, "participant_id", ""),
        _stage_read(value, "snapshot_id", ""),
        _as_int(_stage_read(value, "round_no", 0)),
        _as_int(_stage_read(value, "turn_index", 0)),
        _text_hash(_stage_read(value, "speech", "")),
        _stage_read(value, "transcript_hash", ""),
        _as_int(_stage_read(value, "cutoff_turn_index", -1), -1),
        tuple(str(item) for item in _sequence(predecessor_ids)),
        _stage_read(value, "publication_status", "final_ready"),
    )


def _question_fence(value: object | None) -> tuple[object, ...] | None:
    if value is None:
        return None
    return (
        _stage_read(value, "question_id", ""),
        _stage_read(value, "source_turn_id", ""),
        _stage_read(value, "source_participant_id", ""),
        _stage_read(value, "target_participant_id", ""),
        _text_hash(_stage_read(value, "text", "")),
    )


def _assert_context_matches(
    live: GenerationContext,
    recovered: GenerationContext,
) -> None:
    """Require the local DB prefix to be exactly the staged recovery fence."""

    live_participants = tuple(_participant_fence(item) for item in live.participants)
    recovered_participants = tuple(_participant_fence(item) for item in recovered.participants)
    live_predecessors = tuple(_predecessor_fence(item) for item in live.predecessors)
    recovered_predecessors = tuple(_predecessor_fence(item) for item in recovered.predecessors)
    if (
        live.debate_id != recovered.debate_id
        or live.topic != recovered.topic
        or live.output_language != recovered.output_language
        or _plan_fence(live.turn) != _plan_fence(recovered.turn)
        or _participant_fence(live.participant) != _participant_fence(recovered.participant)
        or live_participants != recovered_participants
        or live_predecessors != recovered_predecessors
        or _question_fence(live.effective_pending_question)
        != _question_fence(recovered.effective_pending_question)
    ):
        raise LLMRuntimeError(code="llm_recovery_fence_stale")


class LLMRecoveryLedgerPort(Protocol):
    """Minimal startup recovery view implemented by the durable ledger."""

    def recover_startup(self) -> Sequence[object]: ...

    def get(self, operation_id: str) -> object | None: ...

    def load_llm_accepted_bundle(self, operation_id: str) -> object | None: ...


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
        stage_store: object | None = None,
        runtime: LLMTurnRuntime | None = None,
        recovery_store: object | None = None,
        adapter: object | None = None,
    ) -> None:
        self.ledger = ledger
        self.stage_store = stage_store
        self.runtime = runtime
        self.recovery_store = recovery_store
        self.adapter = adapter

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
                if (
                    self.recovery_store is not None
                    and self.adapter is not None
                    and self.runtime is not None
                ):
                    resumed = self.resume_accepted(identifier)
                    if resumed.status == "succeeded":
                        recovered.append(identifier)
                    elif resumed.status == "acceptance_unknown":
                        unknown.append(identifier)
                    elif resumed.safe_error_code == "llm_recovery_input_unavailable":
                        # Legacy 0014 accepted stages remain safely blocked;
                        # they are neither failed nor eligible for a provider
                        # retry because the exact continuation input is absent.
                        resumable.append(identifier)
                    else:
                        failed.append(identifier)
                else:
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
            recovery_input: object | None = None
            if result_loader is None:
                bundle = self._load_bundle(operation_id)
                if bundle is None:
                    raise LLMRuntimeError(
                        "accepted recovery input is unavailable",
                        code="llm_recovery_input_unavailable",
                    )
                bundled_stage = self._bundle_value(bundle, "stage", "accepted_stage")
                bundled_input = self._bundle_value(
                    bundle,
                    "recovery_input",
                    "input",
                    "accepted_recovery_input",
                )
                if bundled_stage is not None:
                    stage = bundled_stage
                if bundled_input is None:
                    raise LLMRuntimeError(
                        "accepted recovery input is unavailable",
                        code="llm_recovery_input_unavailable",
                    )
                recovery_input = self._recovery_input(bundled_input)
                recovered_context = context_from_recovery_input(recovery_input)
                if context is None:
                    context = recovered_context
                else:
                    _assert_context_matches(context, recovered_context)
                result = self._map_staged_result(stage, recovery_input)
            loaded: MutualLearningTurnResultV1 | tuple[object, ...]
            if result_loader is None:
                loaded = result
            else:
                loaded = result_loader(cast(LLMAcceptedStageV1, stage))
            receipts: Sequence[object] = ()
            queries: Sequence[object] = ()
            if recovery_input is not None:
                receipts = receipts_from_recovery_input(cast(LLMRecoveryInputV1, recovery_input))
                from .retrieval import TurnSubquery

                queries = tuple(
                    TurnSubquery(str(item["query_kind"]), str(item["text"]))
                    for item in queries_from_recovery_input(
                        cast(LLMRecoveryInputV1, recovery_input)
                    )
                )
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
                local_resume = cast(Callable[..., LLMRunOutcomeV1], resume)
                return local_resume(
                    stage,
                    result,
                    context=context,
                    receipts=receipts,
                    queries=queries,
                    validator=validator,
                    recovery_input=recovery_input,
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
        if not callable(getter):
            return None
        value = getter(operation_id)
        return cast(object | None, value)

    def _load_bundle(self, operation_id: str) -> object | None:
        getter = getattr(self.recovery_store, "load_accepted_bundle", None)
        if not callable(getter):
            getter = getattr(self.recovery_store, "load_llm_accepted_bundle", None)
        if callable(getter):
            return cast(object | None, getter(operation_id))
        getter = getattr(self.ledger, "load_llm_accepted_bundle", None)
        return cast(object | None, getter(operation_id)) if callable(getter) else None

    @staticmethod
    def _bundle_value(bundle: object, *names: str) -> object | None:
        if isinstance(bundle, Mapping):
            for name in names:
                if bundle.get(name) is not None:
                    return cast(object, bundle[name])
            return None
        if isinstance(bundle, Sequence) and not isinstance(bundle, (str, bytes, bytearray)):
            # Stable provider-port tuple: (operation, stage, recovery_input).
            index = {"stage": 1, "accepted_stage": 1, "recovery_input": 2, "input": 2}.get(
                names[0], -1
            )
            if 0 <= index < len(bundle):
                return cast(object, bundle[index])
            return None
        for name in names:
            value = getattr(bundle, name, None)
            if value is not None:
                return cast(object, value)
        return None

    @staticmethod
    def _recovery_input(value: object) -> LLMRecoveryInputV1:
        if isinstance(value, LLMRecoveryInputV1):
            return value
        raise LLMRuntimeError(code="llm_recovery_input_unavailable")

    def _map_staged_result(
        self,
        stage: object,
        recovery_input: LLMRecoveryInputV1,
    ) -> MutualLearningTurnResultV1:
        if self.adapter is None:
            raise LLMRuntimeError(code="llm_recovery_unavailable")
        try:
            request_value = request_from_recovery_input(recovery_input)
            prompt_request = PromptRequestV1.model_validate(request_value)
            system = render_prompt_system_message(
                rule_set_id=prompt_request.rule_set_id,
                rule_set_hash=prompt_request.rule_set_hash,
                rules=mutual_learning_platform_rules(
                    context_from_recovery_input(recovery_input).output_language
                ),
            )
            user = prompt_request.canonical_json()
            budget = preflight_prompt_budget(
                (system, user),
                request_bytes=len(user.encode("utf-8")),
            )
            prompt = ProviderPromptV1(
                request=prompt_request,
                messages=(
                    PromptMessageV1(role="system", content=system),
                    PromptMessageV1(role="user", content=user),
                ),
                budget=budget,
                request_hash=prompt_request.request_hash,
                system_rules_hash=prompt_request.rule_set_hash,
            )
            request = LLMRequestV1(
                endpoint="",
                method="POST",
                body={},
                messages=prompt.messages,
                prompt=prompt,
                budget=budget,
                request_hash=str(_stage_read(stage, "request_hash", "")),
                prompt_contract_version=str(_stage_read(stage, "prompt_contract_version", "")),
                schema_hash=str(_stage_read(stage, "schema_hash", "")),
                tokenizer_id=str(_stage_read(stage, "tokenizer_id", "")),
                tokenizer_asset_hash=str(_stage_read(stage, "tokenizer_hash", "")),
                rule_set_hash=str(_stage_read(stage, "rule_set_hash", "")),
                persona_spec_hash=str(_stage_read(stage, "persona_spec_hash", "")),
                transcript_hash=str(_stage_read(stage, "transcript_hash", "")),
                receipt_hash=str(_stage_read(stage, "receipt_hash", "")),
                turn_id=str(_stage_read(stage, "turn_id", "")),
                generation_fence=str(_stage_read(stage, "generation_fence", "")),
                policy_hash=str(_stage_read(stage, "policy_hash", "")),
                export_manifest_hash=str(_stage_read(stage, "export_manifest_hash", "")),
                repair_policy_hash=str(_stage_read(stage, "repair_policy_hash", "") or ""),
                build_manifest_hash=str(_stage_read(stage, "build_manifest_hash", "")),
                outbound_field_classes=(),
                identity_tokens=(),
                attempt_no=_as_int(_stage_read(stage, "attempt_no", 0)),
                retrieval_reused=bool(getattr(stage, "retrieval_reused", False)),
            )
            candidate = LLMAcceptedCandidateV1.from_staged_json(
                request,
                str(_stage_read(stage, "output_json", "")),
                stage_hash=str(_stage_read(stage, "output_hash", "")),
            )
            validator = getattr(self.adapter, "validate_accepted", None)
            if not callable(validator):
                raise LLMRuntimeError(code="llm_recovery_unavailable")
            mapped = validator(candidate)
            result = getattr(mapped, "result", None)
            if not isinstance(result, MutualLearningTurnResultV1):
                raise LLMRuntimeError(code="llm_recovery_failed")
            return result
        except LLMRuntimeError:
            raise
        except Exception as exc:
            raise LLMRuntimeError(code="llm_recovery_failed") from exc


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
