"""Durable, provider-neutral runtime seam for ``segments_v2`` turns.

The legacy :class:`LLMTurnRuntime` remains the v1 path.  This module uses the
same injected ledger and publication ports but keeps the segment request,
candidate, and result types separate, so accepted paragraph JSON is never
reinterpreted as v1 claims or position fields.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast
from uuid import NAMESPACE_URL, uuid5

from app.core.config import configured_debate_llm_model
from app.core.errors import PlatformError
from app.core.llm_admission import debate_llm_slot
from app.providers.control import LLMAcceptedStageV1, ProviderReservationRequestV1
from app.providers.llm_adapter import LLMAdapterError
from app.providers.llm_price_card import (
    LLM_INPUT_TOKEN_CAP,
    LLM_REQUEST_COST_CAP,
    LLM_RESERVED_OUTPUT_TOKEN_CAP,
)
from app.providers.llm_segments import (
    SegmentAcceptedCandidateV2,
    SegmentLLMAdapter,
    SegmentLLMRequestV2,
    SegmentRecoveryInputV2,
    segment_prompt_version,
)
from app.providers.llm_transport import LLMAcceptanceUnknown, LLMTransportNotSent

from .four_round import visible_predecessors
from .mutual_learning_prompts import compute_mutual_transcript_hash
from .segments import (
    SEGMENT_OUTPUT_SALVAGED,
    SegmentInputSnapshot,
    SegmentProtocolError,
    SegmentTurnResult,
    StoredSegmentTurnResult,
    load_segment_turn_result,
    load_stored_segment_turn_result,
    salvage_segment_output,
    validate_segment_output,
)
from .types import (
    FinalReadyTurn,
    GenerationContext,
    PublicSource,
    ValidatedTurn,
)
from .validator import final_ready_turn

SEGMENT_MAX_ATTEMPTS = 2
LOGGER = logging.getLogger(__name__)
SEGMENT_REPAIR_CODES = frozenset(
    {
        "json_invalid",
        "schema_invalid",
        "segment_shape_invalid",
        "segment_count_invalid",
        "segment_text_invalid",
        "segment_history_copy",
        # v4 repetition rules; the repair attempt accepts what comes back.
        "segment_history_stump",
        "segment_self_repetition",
        "segment_over_length",
        "segment_too_short",
        "segment_language_mismatch",
    }
)

_V2_HASH = "d911e9af5381af8cea22f171fdd11f1a07f18ccdf2f703bdfbee1e4d096292f7"


def _repair_policy_version(policy_hash: str | None) -> str | None:
    if not policy_hash:
        return None
    if policy_hash == _V2_HASH:
        return "repair_feedback_v2"
    return "repair_feedback_v1"


def _repair_feedback(
    _candidate: SegmentAcceptedCandidateV2,
    code: str,
    pointers: Sequence[str],
    *,
    policy_hash: str | None = None,
    error: object | None = None,
) -> dict[str, object]:
    source = error if error is not None else _candidate
    actual_units = getattr(source, "actual_units", None)
    unit_cap = getattr(source, "unit_cap", None)
    language = getattr(source, "language", None)
    repetition = getattr(source, "repetition_ratio_percent", None)
    if _repair_policy_version(policy_hash) == "repair_feedback_v2":
        payload: dict[str, object] = {
            "schema_version": "repair_feedback_v2",
            "safe_error_code": code,
            "json_pointers": list(pointers),
        }
        if isinstance(actual_units, int) and not isinstance(actual_units, bool):
            payload["actual_units"] = actual_units
        if isinstance(unit_cap, int) and not isinstance(unit_cap, bool):
            payload["unit_cap"] = unit_cap
        if language in {"zh", "en"}:
            payload["language"] = language
        if isinstance(repetition, int) and not isinstance(repetition, bool):
            payload["repetition_ratio_percent"] = repetition
        return payload
    return {"code": code, "json_pointers": list(pointers)}


class SegmentRuntimeError(RuntimeError):
    """A safe v2 runtime failure with no provider response content."""

    def __init__(
        self,
        message: str = "segment runtime failed safely",
        *,
        code: str = "segment_runtime_failed",
    ) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SegmentAttempt:
    attempt_no: int
    request_hash: str
    operation_id: str | None
    provider_called: bool
    acceptance: Literal["none", "accepted", "not_sent", "unknown"]
    safe_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class SegmentPreparedAttempt:
    snapshot: SegmentInputSnapshot
    request: SegmentLLMRequestV2
    operation: object | None
    debate_id: str
    turn_id: str
    scope_id: str
    policy_hash: str
    manifest_hash: str
    build_manifest_hash: str
    confirmation_revision: int = 1
    attempt_no: int = 1
    retrieval_reused: bool = False

    @property
    def operation_id(self) -> str | None:
        value = getattr(self.operation, "id", None)
        return str(value) if value else None


@dataclass(frozen=True, slots=True)
class SegmentRunOutcome:
    status: Literal[
        "succeeded",
        "provider_confirmation_unavailable",
        "not_sent",
        "acceptance_unknown",
        "failed",
    ]
    attempts: tuple[SegmentAttempt, ...] = ()
    operation: object | None = None
    stage: object | None = None
    result: SegmentTurnResult | None = None
    final_ready: FinalReadyTurn | None = None
    safe_error_code: str | None = None
    retry_allowed: bool = False
    deferred_publication: SegmentDeferredPublicationV2 | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded" and self.result is not None


@dataclass(frozen=True, slots=True)
class SegmentDeferredPublicationV2:
    """Accepted v2 handoff consumed by the playback transaction."""

    operation_id: str
    turn_id: str
    debate_id: str
    request_hash: str
    operation: object
    stage: object
    usage: object
    result: SegmentTurnResult
    final_ready: FinalReadyTurn
    recovery_input: object | None = None

    @property
    def publication(self) -> SegmentDeferredPublicationV2:
        return self


def _read(value: object | None, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _method(value: object, *names: str) -> Callable[..., object] | None:
    for name in names:
        candidate = getattr(value, name, None)
        if callable(candidate):
            return cast(Callable[..., object], candidate)
    return None


def _invoke(method: Callable[..., object], *args: object, **kwargs: object) -> object:
    if kwargs:
        try:
            inspect.signature(method).bind(*args, **kwargs)
        except (TypeError, ValueError):
            try:
                inspect.signature(method).bind(*args)
            except (TypeError, ValueError) as exc:
                raise TypeError("segment port signature does not match") from exc
            return method(*args)
    return method(*args, **kwargs)


def _hash(value: object) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _operation_key(scope_id: str, turn_id: str, attempt_no: int) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"maya:segments_v2:{scope_id}:{turn_id}:{attempt_no}",
        )
    )


def _operation_state(value: object | None) -> str | None:
    state = _read(value, "state")
    return str(state) if state is not None else None


class SegmentLLMRuntime:
    """Prepare, stage, validate, and publish one explicit v2 turn."""

    protocol = "segments_v2"

    def __init__(
        self,
        *,
        ledger: object,
        adapter: SegmentLLMAdapter | object,
        stage_store: object | None = None,
        publication: object | None = None,
        confirmation: Callable[..., bool] | object | None = None,
        defer_publication: bool = False,
        max_attempts: int = SEGMENT_MAX_ATTEMPTS,
    ) -> None:
        if isinstance(max_attempts, bool) or max_attempts not in {1, 2}:
            raise ValueError("max_attempts must be one or two")
        self.ledger = ledger
        self.adapter = adapter
        self.stage_store = stage_store
        self.publication = publication
        self.confirmation = confirmation
        self.defer_publication = defer_publication
        self.max_attempts = max_attempts

    def prepare(
        self,
        snapshot: SegmentInputSnapshot,
        *,
        debate_id: str,
        turn_id: str,
        policy_hash: str,
        manifest_hash: str,
        build_manifest_hash: str,
        confirmation_revision: int = 1,
        generation_fence: str = "",
        repair_policy_hash: str = "",
        identity_tokens: Sequence[str] = (),
        outbound_manifest: object | None = None,
        attempt_no: int = 1,
        retrieval_reused: bool = False,
        repair_feedback: Mapping[str, object] | None = None,
        queries: Sequence[object] = (),
    ) -> SegmentPreparedAttempt:
        if not isinstance(snapshot, SegmentInputSnapshot):
            raise SegmentRuntimeError(code="segment_snapshot_invalid")
        if (
            not debate_id
            or not turn_id
            or not policy_hash
            or not manifest_hash
            or not build_manifest_hash
        ):
            raise SegmentRuntimeError(code="segment_identity_missing")
        if confirmation_revision < 1 or attempt_no not in {1, 2} or attempt_no > self.max_attempts:
            raise SegmentRuntimeError(code="segment_attempt_invalid")
        builder = _method(self.adapter, "build_request", "prepare")
        if builder is None:
            raise SegmentRuntimeError(code="segment_adapter_unavailable")
        try:
            request = cast(
                SegmentLLMRequestV2,
                _invoke(
                    builder,
                    snapshot,
                    debate_id=debate_id,
                    turn_id=turn_id,
                    generation_fence=generation_fence,
                    policy_hash=policy_hash,
                    export_manifest_hash=manifest_hash,
                    build_manifest_hash=build_manifest_hash,
                    repair_policy_hash=repair_policy_hash,
                    attempt_no=attempt_no,
                    retrieval_reused=retrieval_reused,
                    identity_tokens=identity_tokens,
                    outbound_manifest=outbound_manifest,
                    repair_feedback=repair_feedback,
                    queries=queries,
                ),
            )
        except Exception as exc:
            raise SegmentRuntimeError(code=getattr(exc, "code", "segment_request_invalid")) from exc
        if not isinstance(request, SegmentLLMRequestV2):
            raise SegmentRuntimeError(code="segment_request_invalid")
        reservation = ProviderReservationRequestV1(
            scope_id=debate_id,
            provider_operation="llm_debate_turn",
            logical_item_id=turn_id,
            attempt_no=attempt_no,
            request_hash=request.request_hash,
            max_tokens=LLM_INPUT_TOKEN_CAP + LLM_RESERVED_OUTPUT_TOKEN_CAP,
            max_cost_cny=float(LLM_REQUEST_COST_CAP),
            policy_hash=policy_hash,
            export_manifest_hash=manifest_hash,
            build_manifest_hash=build_manifest_hash,
            model_key=configured_debate_llm_model(),
            operation_id=_operation_key(debate_id, turn_id, attempt_no),
        )
        operation: object | None = None
        creator = _method(self.ledger, "create_prepared", "prepare")
        if creator is not None:
            try:
                operation = _invoke(creator, reservation, budget_bucket="llm_debate_turn")
            except Exception as exc:
                getter = _method(self.ledger, "get")
                existing = _invoke(getter, reservation.operation_id) if getter is not None else None
                if existing is not None and _operation_state(existing) in {"not_sent", "failed"}:
                    mover = _method(self.ledger, "transition")
                    if mover is None or (
                        _operation_state(existing) == "failed" and attempt_no < self.max_attempts
                    ):
                        if (
                            existing is not None
                            and _operation_state(existing) == "failed"
                            and attempt_no < self.max_attempts
                        ):
                            return self.prepare(
                                snapshot,
                                debate_id=debate_id,
                                turn_id=turn_id,
                                policy_hash=policy_hash,
                                manifest_hash=manifest_hash,
                                build_manifest_hash=build_manifest_hash,
                                confirmation_revision=confirmation_revision,
                                generation_fence=generation_fence,
                                repair_policy_hash=repair_policy_hash,
                                identity_tokens=identity_tokens,
                                outbound_manifest=outbound_manifest,
                                attempt_no=attempt_no + 1,
                                retrieval_reused=retrieval_reused,
                                repair_feedback=repair_feedback,
                                queries=queries,
                            )
                    if mover is None:
                        raise SegmentRuntimeError(code="segment_preparation_failed") from exc
                    # Spent failed attempts (teacher Preview Retry) often rebuild
                    # with current clamps/salvage → a new request_hash. Plain
                    # failed→prepared keeps the old identity and then staging
                    # rejects the accepted stage; rebind hashes while preserving
                    # charged-request history.
                    reprepare = _method(self.ledger, "reprepare_failed")
                    if (
                        reprepare is not None
                        and _operation_state(existing) == "failed"
                        and (
                            _read(existing, "request_hash") != request.request_hash
                            or _read(existing, "policy_hash") != policy_hash
                            or _read(existing, "export_manifest_hash") != manifest_hash
                            or _read(existing, "build_manifest_hash") != build_manifest_hash
                        )
                    ):
                        try:
                            operation = _invoke(
                                reprepare,
                                reservation.operation_id,
                                request_hash=request.request_hash,
                                policy_hash=policy_hash,
                                export_manifest_hash=manifest_hash,
                                build_manifest_hash=build_manifest_hash,
                                max_tokens=reservation.max_tokens,
                                max_cost_cny=reservation.max_cost_cny,
                                model_key=reservation.model_key,
                            )
                        except Exception as reprepare_exc:
                            raise SegmentRuntimeError(
                                code="segment_preparation_failed"
                            ) from reprepare_exc
                    else:
                        operation = _invoke(
                            mover,
                            reservation.operation_id,
                            expected=_operation_state(existing),
                            state="prepared",
                        )
                elif (
                    existing is None
                    or _operation_state(existing) != "prepared"
                    or _read(existing, "request_hash") != request.request_hash
                ):
                    raise SegmentRuntimeError(code="segment_preparation_failed") from exc
                else:
                    operation = existing
        return SegmentPreparedAttempt(
            snapshot=snapshot,
            request=request,
            operation=operation,
            debate_id=debate_id,
            turn_id=turn_id,
            scope_id=debate_id,
            policy_hash=policy_hash,
            manifest_hash=manifest_hash,
            build_manifest_hash=build_manifest_hash,
            confirmation_revision=confirmation_revision,
            attempt_no=attempt_no,
            retrieval_reused=retrieval_reused,
        )

    def _confirmed(self, prepared: SegmentPreparedAttempt, explicit: object | None) -> bool:
        if explicit is not None:
            return bool(explicit)
        checker = (
            _method(self.confirmation, "is_confirmed", "confirmed")
            if self.confirmation is not None
            else None
        )
        if checker is None and callable(self.confirmation):
            checker = cast(Callable[..., object], self.confirmation)
        if checker is None:
            return False
        try:
            return bool(
                _invoke(
                    checker,
                    manifest_hash=prepared.manifest_hash,
                    policy_hash=prepared.policy_hash,
                    confirmation_revision=prepared.confirmation_revision,
                )
            )
        except Exception:
            return False

    def _latest_operation(self, operation_id: str | None, fallback: object | None) -> object | None:
        if operation_id is None:
            return fallback
        getter = _method(self.ledger, "get")
        if getter is None:
            return fallback
        try:
            return _invoke(getter, operation_id) or fallback
        except Exception:
            return fallback

    def _transition(
        self,
        operation_id: str | None,
        action: str,
        *,
        code: str | None = None,
        response_hash: str | None = None,
    ) -> object | None:
        if operation_id is None:
            return None
        method = _method(self.ledger, action)
        if method is not None:
            call_kwargs = {"safe_error_code": code} if code is not None else {}
            if response_hash is not None:
                call_kwargs["response_hash"] = response_hash
            return _invoke(method, operation_id, **call_kwargs)
        transition = _method(self.ledger, "transition")
        if transition is None:
            return None
        state = {
            "mark_sending": "sending",
            "mark_accepted": "accepted",
            "mark_succeeded": "succeeded",
            "mark_not_sent": "not_sent",
            "mark_acceptance_unknown": "acceptance_unknown",
            "mark_failed": "failed",
        }.get(action)
        if state is None:
            return None
        getter = _method(self.ledger, "get")
        operation = _invoke(getter, operation_id) if getter is not None else None
        kwargs: dict[str, object] = {
            "expected": _operation_state(operation) or "sending",
            "state": state,
        }
        if code is not None:
            kwargs["safe_error_code"] = code
        if response_hash is not None:
            kwargs["response_hash"] = response_hash
        return _invoke(transition, operation_id, **kwargs)

    def _stage_salvaged_payload(
        self, prepared: SegmentPreparedAttempt, raw: object
    ) -> tuple[str, str]:
        """Persist a locally salvaged stored payload so deferred publish can CAS."""

        salvaged = salvage_segment_output(
            raw if isinstance(raw, (Mapping, str)) else {},
            prepared.snapshot,
        )
        stored = salvaged.as_stored_payload()
        output_json = json.dumps(stored, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return output_json, _hash(stored)

    def _can_structure_repair(self, prepared: SegmentPreparedAttempt, code: str | None) -> bool:
        return (
            prepared.attempt_no == 1
            and self.max_attempts == 2
            and prepared.request.authorized_max_attempts == 2
            and code in SEGMENT_REPAIR_CODES
        )

    def _stage(
        self,
        prepared: SegmentPreparedAttempt,
        candidate: SegmentAcceptedCandidateV2,
        *,
        transcript_hash: str,
    ) -> LLMAcceptedStageV1 | None:
        if prepared.operation_id is None:
            return None
        output_json = candidate.output_json
        output_hash = candidate.output_hash
        repairable = prepared.attempt_no < 2 and prepared.request.authorized_max_attempts == 2
        if candidate.provider_output is not None:
            try:
                checked = validate_segment_output(
                    candidate.provider_output,
                    prepared.snapshot,
                    allow_history_copy=prepared.attempt_no >= 2,
                    repairable=repairable,
                )
                stored = checked.as_stored_payload()
                output_json = json.dumps(
                    stored, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                output_hash = _hash(stored)
            except SegmentProtocolError as exc:
                if repairable and self._can_structure_repair(prepared, exc.code):
                    # Keep the accepted provider JSON for the one repair attempt.
                    pass
                else:
                    # Attempts are spent: stage the salvaged speech so later
                    # deferred publication can CAS against a usable payload.
                    output_json, output_hash = self._stage_salvaged_payload(
                        prepared, candidate.provider_output
                    )
        if output_json is None or output_hash is None:
            code = candidate.safe_error_code or "provider_response_invalid"
            if self._can_structure_repair(prepared, code):
                diagnostic = {
                    "protocol_version": "segments_v2",
                    "status": "diagnostic",
                    "safe_error_code": code,
                }
                output_json = json.dumps(
                    diagnostic, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                output_hash = _hash(diagnostic)
            else:
                output_json, output_hash = self._stage_salvaged_payload(prepared, {})
        tokenizer_id = str(getattr(self.adapter, "tokenizer", object()).__class__.__name__)
        tokenizer_hash = _hash(tokenizer_id)
        stage = LLMAcceptedStageV1(
            operation_id=prepared.operation_id,
            turn_id=prepared.turn_id,
            attempt_no=prepared.attempt_no,
            request_hash=prepared.request.request_hash,
            prompt_hash=prepared.request.prompt_hash,
            prompt_contract_version=segment_prompt_version(prepared.snapshot),
            schema_hash=prepared.request.schema_hash,
            tokenizer_id=tokenizer_id,
            tokenizer_hash=tokenizer_hash,
            rule_set_hash=_hash("segments_v2"),
            persona_spec_hash=_hash(prepared.snapshot.persona.as_payload()),
            transcript_hash=transcript_hash,
            receipt_hash=prepared.snapshot.receipt_hash,
            policy_hash=prepared.policy_hash,
            export_manifest_hash=prepared.manifest_hash,
            build_manifest_hash=prepared.build_manifest_hash,
            model_key=configured_debate_llm_model(),
            output_json=output_json,
            output_hash=output_hash,
            prompt_tokens=candidate.usage.prompt_tokens if candidate.usage else 0,
            cached_input_tokens=candidate.usage.cached_input_tokens if candidate.usage else 0,
            completion_tokens=candidate.usage.completion_tokens if candidate.usage else 0,
            total_tokens=candidate.usage.total_tokens if candidate.usage else 0,
            estimated_cost_cny=candidate.estimated_cost_cny,
            actual_cost_cny=candidate.actual_cost_cny,
            retrieval_reused=prepared.retrieval_reused,
            safe_error_code=candidate.safe_error_code,
            repair_policy_version=_repair_policy_version(prepared.request.repair_policy_hash),
            repair_policy_hash=prepared.request.repair_policy_hash or None,
            generation_fence=prepared.request.generation_fence,
        )
        recovery_input = SegmentRecoveryInputV2.from_request(
            prepared.request,
            operation_id=prepared.operation_id,
        )
        recovery_store = _method(
            self.stage_store,
            "stage_segment_accepted_with_recovery",
            "stage_segments_accepted_with_recovery",
        )
        if recovery_store is None:
            recovery_store = _method(
                self.ledger,
                "stage_segment_accepted_with_recovery",
                "stage_segments_accepted_with_recovery",
            )
        if recovery_store is not None:
            persisted = _invoke(recovery_store, stage, recovery_input)
            return cast(LLMAcceptedStageV1, persisted or stage)
        store = _method(self.stage_store, "stage_llm_accepted", "save_llm_accepted_stage")
        if store is None:
            store = _method(self.ledger, "stage_llm_accepted", "stage_accepted_llm")
        if store is not None:
            persisted = _invoke(store, stage)
            return cast(LLMAcceptedStageV1, persisted or stage)
        return stage

    def _final_ready(
        self, result: SegmentTurnResult, context: GenerationContext, attempt: int
    ) -> FinalReadyTurn:
        visible = visible_predecessors(context)
        validated = ValidatedTurn(
            result=result,
            retrieval_status="matched" if result.snapshot.receipts else "no_match",
            grounding_mode="rag_grounded" if result.used_receipts else "general_reasoning",
            used_receipts=result.used_receipts,
            public_sources=tuple(
                PublicSource(
                    source_filename=item.source_filename,
                    chunk_id=item.chunk_id,
                    evidence_id=item.resolved_evidence_id(),
                    rank=item.rank,
                    score=item.score,
                )
                for item in result.used_receipts
            ),
            word_count=len(result.speech.split()),
        )
        return final_ready_turn(
            validated,
            turn_id=context.turn.turn_id,
            participant_id=context.participant.participant_id,
            snapshot_id=context.participant.snapshot_id,
            round_no=context.turn.round_no,
            turn_index=context.turn.turn_index,
            predecessor_turn_ids=tuple(item.turn_id for item in visible),
            cutoff_turn_index=max((item.turn_index for item in visible), default=-1),
            transcript_hash=compute_mutual_transcript_hash(visible),
            attempt=attempt,
        )

    def run(
        self,
        prepared: SegmentPreparedAttempt,
        *,
        context: GenerationContext,
        confirmed: object | None = None,
    ) -> SegmentRunOutcome:
        if not self._confirmed(prepared, confirmed):
            return SegmentRunOutcome(
                "provider_confirmation_unavailable",
                attempts=(
                    SegmentAttempt(
                        prepared.attempt_no,
                        prepared.request.request_hash,
                        prepared.operation_id,
                        False,
                        "none",
                        "provider_confirmation_unavailable",
                    ),
                ),
                operation=prepared.operation,
                retry_allowed=True,
                safe_error_code="provider_confirmation_unavailable",
            )
        current = prepared
        traces: list[SegmentAttempt] = []
        while current.attempt_no <= self.max_attempts:
            operation_id = current.operation_id
            operation = current.operation
            try:
                try:
                    self._transition(operation_id, "reserve")
                    self._transition(operation_id, "mark_sending")
                except Exception:
                    self._transition(operation_id, "mark_failed", code="segment_reservation_failed")
                    return SegmentRunOutcome(
                        "failed",
                        tuple(traces),
                        operation,
                        safe_error_code="segment_reservation_failed",
                    )
                operation = self._latest_operation(operation_id, operation)
                sender = _method(self.adapter, "send_accepted")
                if sender is None:
                    raise SegmentRuntimeError(code="segment_adapter_unavailable")
                # Debate priority (2026-10-19): the transport's own slot
                # request is re-entrant inside this one.
                with debate_llm_slot():
                    candidate = cast(SegmentAcceptedCandidateV2, _invoke(sender, current.request))
            except (LLMTransportNotSent, PlatformError):
                # PlatformError: refused before sending (admission busy, host
                # memory pressure); nothing left the host, so it is not unknown.
                self._transition(operation_id, "mark_not_sent", code="provider_not_sent")
                traces.append(
                    SegmentAttempt(
                        current.attempt_no,
                        current.request.request_hash,
                        operation_id,
                        True,
                        "not_sent",
                        "provider_not_sent",
                    )
                )
                return SegmentRunOutcome(
                    "not_sent",
                    tuple(traces),
                    operation,
                    safe_error_code="provider_not_sent",
                )
            except LLMAcceptanceUnknown:
                self._transition(operation_id, "mark_acceptance_unknown", code="acceptance_unknown")
                traces.append(
                    SegmentAttempt(
                        current.attempt_no,
                        current.request.request_hash,
                        operation_id,
                        True,
                        "unknown",
                        "acceptance_unknown",
                    )
                )
                return SegmentRunOutcome(
                    "acceptance_unknown",
                    tuple(traces),
                    operation,
                    safe_error_code="acceptance_unknown",
                )
            except SegmentRuntimeError as exc:
                self._transition(operation_id, "mark_failed", code=exc.code)
                return SegmentRunOutcome(
                    "failed", tuple(traces), operation, safe_error_code=exc.code
                )
            except LLMAdapterError as exc:
                code = str(getattr(exc, "code", "segment_provider_failed"))
                self._transition(operation_id, "mark_failed", code=code)
                return SegmentRunOutcome("failed", tuple(traces), operation, safe_error_code=code)
            except Exception:
                self._transition(operation_id, "mark_acceptance_unknown", code="acceptance_unknown")
                return SegmentRunOutcome(
                    "acceptance_unknown",
                    tuple(traces),
                    operation,
                    safe_error_code="acceptance_unknown",
                )

            visible = visible_predecessors(context)
            transcript_hash = compute_mutual_transcript_hash(visible)
            try:
                stage = self._stage(current, candidate, transcript_hash=transcript_hash)
            except Exception as exc:
                cause: BaseException = exc
                while cause.__cause__ is not None:
                    cause = cause.__cause__
                trace = cause.__traceback__
                while trace is not None and trace.tb_next is not None:
                    trace = trace.tb_next
                LOGGER.error(
                    "Segment stage failed error_type=%s safe_code=%s line=%s",
                    type(cause).__name__,
                    getattr(cause, "code", "segment_stage_failed"),
                    trace.tb_lineno if trace is not None else 0,
                )
                self._transition(operation_id, "mark_failed", code="segment_stage_failed")
                return SegmentRunOutcome(
                    "failed",
                    tuple(traces),
                    operation,
                    safe_error_code="segment_stage_failed",
                )
            operation = self._latest_operation(operation_id, operation)
            if stage is not None and _operation_state(operation) == "sending":
                operation = (
                    self._transition(
                        operation_id,
                        "mark_accepted",
                        response_hash=stage.output_hash,
                    )
                    or operation
                )
            if candidate.provider_output is None:
                code = candidate.safe_error_code or "provider_response_invalid"
                traces.append(
                    SegmentAttempt(
                        current.attempt_no,
                        current.request.request_hash,
                        operation_id,
                        True,
                        "accepted",
                        code,
                    )
                )
                if self._can_structure_repair(current, code):
                    operation = (
                        self._transition(operation_id, "mark_failed", code=code) or operation
                    )
                    current = self.prepare(
                        current.snapshot,
                        debate_id=current.debate_id,
                        turn_id=current.turn_id,
                        policy_hash=current.policy_hash,
                        manifest_hash=current.manifest_hash,
                        build_manifest_hash=current.build_manifest_hash,
                        confirmation_revision=current.confirmation_revision,
                        generation_fence=current.request.generation_fence,
                        repair_policy_hash=current.request.repair_policy_hash,
                        identity_tokens=current.request.identity_tokens,
                        outbound_manifest=None,
                        attempt_no=2,
                        retrieval_reused=True,
                        queries=current.request.queries,
                        repair_feedback=_repair_feedback(
                            candidate,
                            code,
                            candidate.json_pointers,
                            policy_hash=current.request.repair_policy_hash,
                        ),
                    )
                    continue
                # Keep the operation accepted: deferred publication CAS requires
                # accepted→succeeded, and _stage already stored salvaged speech.
                result = salvage_segment_output({}, current.snapshot)
                LOGGER.warning(
                    "Segment output salvaged after empty provider output "
                    "safe_code=%s salvage=%s turn_id=%s: the model returned no "
                    "usable segments; the server built a short fallback speech "
                    "so the debate can continue. Retry this turn to regenerate.",
                    code,
                    result.salvage_warning or SEGMENT_OUTPUT_SALVAGED,
                    current.turn_id,
                )
                final = self._final_ready(result, context, current.attempt_no)
                if not self.defer_publication:
                    publisher = _method(
                        self.publication, "commit_turn_success", "publish_atomic", "publish"
                    )
                    if publisher is not None:
                        _invoke(
                            publisher,
                            operation_id=operation_id,
                            turn_id=current.turn_id,
                            debate_id=current.debate_id,
                            stage=stage,
                            result=result,
                            final_ready=final,
                            evidence_trace=(),
                            request_hash=current.request.request_hash,
                        )
                    operation = self._transition(operation_id, "mark_succeeded") or operation
                traces.append(
                    SegmentAttempt(
                        current.attempt_no,
                        current.request.request_hash,
                        operation_id,
                        True,
                        "accepted",
                        result.salvage_warning or SEGMENT_OUTPUT_SALVAGED,
                    )
                )
                deferred = (
                    SegmentDeferredPublicationV2(
                        operation_id=operation_id or "",
                        turn_id=current.turn_id,
                        debate_id=current.debate_id,
                        request_hash=current.request.request_hash,
                        operation=operation,
                        stage=stage,
                        usage=stage,
                        result=result,
                        final_ready=final,
                        recovery_input=SegmentRecoveryInputV2.from_request(
                            current.request,
                            operation_id=operation_id,
                        ),
                    )
                    if self.defer_publication and operation_id is not None and stage is not None
                    else None
                )
                return SegmentRunOutcome(
                    "succeeded",
                    tuple(traces),
                    operation,
                    stage,
                    result,
                    final,
                    safe_error_code=result.salvage_warning or SEGMENT_OUTPUT_SALVAGED,
                    deferred_publication=deferred,
                )
            validator = _method(self.adapter, "validate_accepted")
            if validator is None:
                return SegmentRunOutcome(
                    "failed",
                    tuple(traces),
                    operation,
                    stage,
                    safe_error_code="segment_adapter_unavailable",
                )
            try:
                result = cast(SegmentTurnResult, _invoke(validator, candidate))
            except SegmentProtocolError as exc:
                traces.append(
                    SegmentAttempt(
                        current.attempt_no,
                        current.request.request_hash,
                        operation_id,
                        True,
                        "accepted",
                        exc.code,
                    )
                )
                if self._can_structure_repair(current, exc.code):
                    operation = (
                        self._transition(operation_id, "mark_failed", code=exc.code) or operation
                    )
                    current = self.prepare(
                        current.snapshot,
                        debate_id=current.debate_id,
                        turn_id=current.turn_id,
                        policy_hash=current.policy_hash,
                        manifest_hash=current.manifest_hash,
                        build_manifest_hash=current.build_manifest_hash,
                        confirmation_revision=current.confirmation_revision,
                        generation_fence=current.request.generation_fence,
                        repair_policy_hash=current.request.repair_policy_hash,
                        identity_tokens=current.request.identity_tokens,
                        attempt_no=2,
                        retrieval_reused=True,
                        queries=current.request.queries,
                        repair_feedback=_repair_feedback(
                            candidate,
                            exc.code,
                            exc.json_pointers,
                            policy_hash=current.request.repair_policy_hash,
                            error=exc,
                        ),
                    )
                    continue
                # Provider attempts are spent: locally salvage so Preview/later
                # turns keep moving. Leave the ledger accepted — mark_failed
                # would block deferred publication (accepted→succeeded only).
                result = salvage_segment_output(
                    candidate.provider_output if candidate.provider_output is not None else {},
                    current.snapshot,
                )
                LOGGER.warning(
                    "Segment output salvaged after provider attempts "
                    "safe_code=%s salvage=%s turn_id=%s: the model output missed "
                    "the segment contract; the server trimmed or rebuilt a usable "
                    "speech so the debate can continue. Retry this turn if the "
                    "wording looks wrong.",
                    exc.code,
                    result.salvage_warning or SEGMENT_OUTPUT_SALVAGED,
                    current.turn_id,
                )
            final = self._final_ready(result, context, current.attempt_no)
            if not self.defer_publication:
                publisher = _method(
                    self.publication, "commit_turn_success", "publish_atomic", "publish"
                )
                if publisher is not None:
                    _invoke(
                        publisher,
                        operation_id=operation_id,
                        turn_id=current.turn_id,
                        debate_id=current.debate_id,
                        stage=stage,
                        result=result,
                        final_ready=final,
                        evidence_trace=(),
                        request_hash=current.request.request_hash,
                    )
                operation = self._transition(operation_id, "mark_succeeded") or operation
            traces.append(
                SegmentAttempt(
                    current.attempt_no, current.request.request_hash, operation_id, True, "accepted"
                )
            )
            deferred = (
                SegmentDeferredPublicationV2(
                    operation_id=operation_id or "",
                    turn_id=current.turn_id,
                    debate_id=current.debate_id,
                    request_hash=current.request.request_hash,
                    operation=operation,
                    stage=stage,
                    usage=stage,
                    result=result,
                    final_ready=final,
                    recovery_input=SegmentRecoveryInputV2.from_request(
                        current.request,
                        operation_id=operation_id,
                    ),
                )
                if self.defer_publication and operation_id is not None and stage is not None
                else None
            )
            return SegmentRunOutcome(
                "succeeded",
                tuple(traces),
                operation,
                stage,
                result,
                final,
                safe_error_code=result.salvage_warning,
                deferred_publication=deferred,
            )
        return SegmentRunOutcome(
            "failed", tuple(traces), safe_error_code="segment_attempt_exhausted"
        )

    def resume_accepted_stage(
        self,
        stage: object,
        *,
        snapshot: SegmentInputSnapshot,
        context: GenerationContext,
        stored_result: StoredSegmentTurnResult | Mapping[str, object] | None = None,
        recovery_input: SegmentRecoveryInputV2 | None = None,
    ) -> SegmentRunOutcome:
        """Validate an accepted stored result without making another call."""

        operation_id_value = _read(stage, "operation_id")
        operation_id = str(operation_id_value) if operation_id_value else None
        getter = _method(self.ledger, "get")
        operation = _invoke(getter, operation_id) if getter and operation_id else None
        if operation_id is None or _operation_state(operation) not in {"accepted", "succeeded"}:
            return SegmentRunOutcome(
                "failed",
                operation=operation,
                stage=stage,
                safe_error_code="segment_stage_unavailable",
            )
        try:
            if _read(stage, "prompt_contract_version") != segment_prompt_version(snapshot):
                raise SegmentProtocolError("stored segment prompt version is stale")
            if _read(stage, "receipt_hash") != snapshot.receipt_hash:
                raise SegmentProtocolError("stored segment receipts are stale")
            visible = visible_predecessors(context)
            if _read(stage, "transcript_hash") != compute_mutual_transcript_hash(visible):
                raise SegmentProtocolError("stored segment transcript is stale")
            if stored_result is None:
                output_json = _read(stage, "output_json")
                if not isinstance(output_json, str):
                    raise SegmentProtocolError("stored segment output is unavailable")
                stored_result = load_stored_segment_turn_result(json.loads(output_json))
            stored_payload: Mapping[str, object]
            if isinstance(stored_result, StoredSegmentTurnResult):
                stored_payload = stored_result.as_payload()
            else:
                stored_payload = stored_result
            attempt_value = _read(stage, "attempt_no", 1)
            attempt_no = (
                attempt_value
                if isinstance(attempt_value, int) and not isinstance(attempt_value, bool)
                else 1
            )
            result = load_segment_turn_result(stored_payload, snapshot)
            final = self._final_ready(
                result,
                context,
                attempt_no,
            )
        except (SegmentProtocolError, TypeError, ValueError, json.JSONDecodeError):
            self._transition(operation_id, "mark_failed", code="segment_stage_invalid")
            return SegmentRunOutcome(
                "failed",
                operation=operation,
                stage=stage,
                safe_error_code="segment_stage_invalid",
            )
        if not self.defer_publication:
            publisher = _method(
                self.publication, "commit_turn_success", "publish_atomic", "publish"
            )
            if publisher is not None:
                _invoke(
                    publisher,
                    operation_id=operation_id,
                    turn_id=context.turn.turn_id,
                    debate_id=context.debate_id,
                    stage=stage,
                    result=result,
                    final_ready=final,
                    evidence_trace=(),
                    request_hash=str(_read(stage, "request_hash", "")),
                )
            if _operation_state(operation) != "succeeded":
                operation = self._transition(operation_id, "mark_succeeded") or operation
        deferred = (
            SegmentDeferredPublicationV2(
                operation_id=operation_id,
                turn_id=context.turn.turn_id,
                debate_id=context.debate_id,
                request_hash=str(_read(stage, "request_hash", "")),
                operation=operation,
                stage=stage,
                usage=stage,
                result=result,
                final_ready=final,
                recovery_input=recovery_input,
            )
            if self.defer_publication
            else None
        )
        return SegmentRunOutcome(
            "succeeded",
            operation=operation,
            stage=stage,
            result=result,
            final_ready=final,
            deferred_publication=deferred,
        )


__all__ = [
    "SEGMENT_MAX_ATTEMPTS",
    "SegmentAttempt",
    "SegmentDeferredPublicationV2",
    "SegmentLLMRuntime",
    "SegmentPreparedAttempt",
    "SegmentRunOutcome",
    "SegmentRuntimeError",
]
