"""W4-LLM-A turn orchestration over the Provider ports.

The LLM adapter, output mapper, price card, privacy scanner and tokenizer are
owned by the provider workstream.  This module intentionally contains no HTTP,
JSON-schema, price or tokenizer implementation.  It only coordinates their
ports with a durable operation ledger and the Debate publication seam.

All calls in this module are injected.  A missing adapter is a safe failure;
there is no default network client and no provider selector here.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal, Protocol, cast

from app.providers.control import (
    FIXED_MODELS,
    REPAIR_FEEDBACK_POLICY_HASH,
    ExportFieldV1,
    ExportManifestV1,
    LLMRecoveryInputV1,
    ProviderReservationRequestV1,
)
from app.providers.llm_adapter import (
    AttemptFailureKind,
    DashScopeLLMAdapter,
    DashScopeLLMConfig,
    LLMAcceptedCandidateV1,
    LLMRequestV1,
    LLMUsageV1,
    LLMValidatedResultV1,
    classify_transport_error,
)
from app.providers.llm_ledger import LLMAcceptedStageV1
from app.providers.llm_output import (
    REPAIR_CODES,
    LLMOutputError,
    MappedLLMTurnV1,
    map_provider_output,
)
from app.providers.llm_price_card import (
    LLM_INPUT_TOKEN_CAP,
    LLM_REQUEST_COST_CAP,
    LLM_RESERVED_OUTPUT_TOKEN_CAP,
    LLMBudgetCapV1,
    LLMPriceCardV1,
    debate_budget_cap,
)
from app.providers.llm_privacy import LLMOutboundManifestV1, scan_llm_outbound_messages
from app.providers.llm_tokenizer import tokenizer_authorized

from .evidence_trace import (
    align_mutual_learning_claim_ids,
    build_evidence_trace_bundle,
    derive_exact_speech_span,
)
from .mutual_learning_validator import MutualLearningValidator
from .prompt_attempt import repair_prompt_request
from .prompt_request import PromptMessageV1, PromptRequestV1, ProviderPromptV1
from .recovery_input import build_llm_recovery_input
from .retrieval import TurnSubquery
from .types import (
    EvidenceTraceClaimV1,
    FinalReadyTurn,
    GenerationContext,
    KeyClaimV1,
    MutualLearningTurnResultV1,
    SnapshotRetrievalReceipt,
    TurnValidationError,
    ValidatedTurn,
)
from .validator import final_ready_turn

LLM_DEBATE_OPERATION = "llm_debate_turn"
LLM_DEBATE_BUCKET = "llm_debate_turn"
LLM_MAX_ATTEMPTS = 2
LLM_MODEL_KEY = "qwen3.7-plus-2026-05-26"
LLM_REGION = "cn-beijing"
LLM_CONNECT_TIMEOUT_SECONDS = 5.0
LLM_TOTAL_TIMEOUT_SECONDS = 120.0


class LLMRuntimeError(RuntimeError):
    """A safe runtime failure with no provider response or user data."""

    def __init__(
        self, message: str = "LLM runtime failed safely", *, code: str = "llm_runtime_failed"
    ):
        super().__init__(message)
        self.code = str(code)[:64]


class LLMRuntimeLedgerPort(Protocol):
    """Ledger seam; implementations own ORM rows and SQL transactions."""

    def create_prepared(self, request: object, **kwargs: object) -> object: ...

    def reserve(self, operation_id: str, **kwargs: object) -> object: ...

    def transition(self, operation_id: str, **kwargs: object) -> object: ...

    def mark_accepted(self, operation_id: str, **kwargs: object) -> object: ...

    def mark_succeeded(self, operation_id: str, **kwargs: object) -> object: ...

    def mark_not_sent(self, operation_id: str, **kwargs: object) -> object: ...

    def mark_acceptance_unknown(self, operation_id: str, **kwargs: object) -> object: ...

    def mark_failed(self, operation_id: str, **kwargs: object) -> object: ...

    def get(self, operation_id: str) -> object | None: ...

    def recover_startup(self) -> Sequence[object]: ...


class LLMAcceptedStagePort(Protocol):
    """Sanitized accepted-stage seam owned by the ledger adapter."""

    def stage_llm_accepted(self, value: LLMAcceptedStageV1) -> LLMAcceptedStageV1: ...

    def get_llm_accepted_stage(self, operation_id: str) -> LLMAcceptedStageV1 | None: ...


class LLMAtomicPublicationPort(Protocol):
    """Turn + EvidenceTrace + usage + succeeded transaction seam."""

    def commit_turn_success(self, **kwargs: object) -> object: ...


class LLMDeferredPublicationPort(Protocol):
    """Server-only publication payload consumed by the playback transaction."""

    def commit_llm_turn_success(self, **kwargs: object) -> object: ...


class LLMManifestPreparationPort(Protocol):
    """Owner-bound manifest persistence used after the outbound scan."""

    def ensure_export_manifest(self, manifest: object, **kwargs: object) -> object: ...


class LLMConfirmationPort(Protocol):
    """Exact teacher confirmation lookup; no provider I/O."""

    def is_confirmed(
        self,
        *,
        manifest_hash: str,
        policy_hash: str,
        confirmation_revision: int,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class LLMGenerationFenceV1:
    predecessor_turn_ids: tuple[str, ...] = ()
    transcript_hash: str = ""
    cutoff_turn_index: int = -1
    generation: int = 0

    @classmethod
    def from_value(cls, value: object | None, prompt: PromptRequestV1) -> LLMGenerationFenceV1:
        if value is None:
            return cls(
                predecessor_turn_ids=tuple(item.turn_id for item in prompt.predecessors),
                transcript_hash=prompt.transcript_hash,
                cutoff_turn_index=max(
                    (item.turn_index for item in prompt.predecessors), default=-1
                ),
            )
        ids = _read(value, "predecessor_turn_ids", ())
        return cls(
            predecessor_turn_ids=(
                tuple(str(item) for item in _sequence(ids)) if _sequence(ids) else ()
            ),
            transcript_hash=str(_read(value, "transcript_hash", prompt.transcript_hash)),
            cutoff_turn_index=_as_int(_read(value, "cutoff_turn_index", -1), -1),
            generation=_as_int(
                _read(value, "generation", _read(value, "cancellation_generation", 0))
            ),
        )

    def as_record(self) -> dict[str, object]:
        return {
            "predecessor_turn_ids": list(self.predecessor_turn_ids),
            "transcript_hash": self.transcript_hash,
            "cutoff_turn_index": self.cutoff_turn_index,
            "generation": self.generation,
        }


@dataclass(frozen=True, slots=True)
class LLMPreparedAttemptV1:
    prompt: ProviderPromptV1
    request: object
    operation: object | None
    request_hash: str
    debate_id: str
    turn_id: str
    scope_id: str
    policy_hash: str
    manifest_hash: str
    confirmation_revision: int
    fence: LLMGenerationFenceV1
    budget: object
    price_card: object
    attempt_no: int = 1
    retrieval_reused: bool = False
    receipts: tuple[object, ...] = ()
    queries: tuple[object, ...] = ()
    build_manifest_hash: str = ""
    repair_policy_hash: str = ""
    generation_fence_hash: str = ""
    identity_tokens: tuple[str, ...] = ()
    outbound_manifest: object | None = None
    question_target_ids: tuple[str, ...] = ()

    @property
    def operation_id(self) -> str | None:
        value = _read(self.operation, "id")
        return str(value) if value else None

    def as_record(self) -> dict[str, object]:
        """Safe metadata only; request body/endpoint are omitted."""

        return {
            "debate_id": self.debate_id,
            "turn_id": self.turn_id,
            "scope_id": self.scope_id,
            "attempt_no": self.attempt_no,
            "request_hash": self.request_hash,
            "policy_hash": self.policy_hash,
            "manifest_hash": self.manifest_hash,
            "confirmation_revision": self.confirmation_revision,
            "fence": self.fence.as_record(),
            "generation_fence_hash": self.generation_fence_hash,
            "retrieval_reused": self.retrieval_reused,
        }


@dataclass(frozen=True, slots=True)
class LLMAttemptTraceV1:
    attempt_no: int
    request_hash: str
    operation_id: str | None
    provider_called: bool
    acceptance: Literal["not_sent", "accepted", "unknown", "none"]
    safe_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class LLMRunOutcomeV1:
    status: Literal[
        "succeeded",
        "prepared",
        "provider_confirmation_required",
        "not_sent",
        "acceptance_unknown",
        "failed",
    ]
    attempts: tuple[LLMAttemptTraceV1, ...] = ()
    operation: object | None = None
    stage: object | None = None
    result: MutualLearningTurnResultV1 | None = None
    final_ready: FinalReadyTurn | None = None
    safe_error_code: str | None = None
    retry_allowed: bool = False
    deferred_publication: object | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"


@dataclass(frozen=True, slots=True)
class LLMDeferredPublicationV1:
    """Opaque server-only handoff from generation to playback SQL.

    Runtime generation stages the accepted provider result and performs all
    local validation/evidence derivation, but deliberately leaves the
    operation in ``accepted``.  Playback consumes this value in its own
    SQLAlchemy Session together with the DebateTurn/TTS publication.
    """

    operation_id: str
    turn_id: str
    debate_id: str
    request_hash: str
    operation: object
    stage: object
    usage: object
    result: MutualLearningTurnResultV1
    final_ready: FinalReadyTurn
    recovery_input: LLMRecoveryInputV1 | None = None

    @property
    def publication(self) -> LLMDeferredPublicationV1:
        """Compatibility alias used by playback adapters."""

        return self


def _sequence(value: object) -> Sequence[object]:
    return (
        value
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
        else ()
    )


def _read(value: object | None, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _as_int(value: object, default: int = 0) -> int:
    """Narrow a ledger/provider scalar without accepting booleans."""

    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, (str, float, Decimal)):
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default
    return default


def _operation_state(value: object | None) -> str | None:
    state = _read(value, "state")
    return str(state) if state is not None else None


def _operation_id(value: object | None) -> str | None:
    identifier = _read(value, "id", _read(value, "operation_id"))
    return str(identifier) if identifier else None


def _hash_record(value: object) -> str:
    """Hash a small runtime identity record without exposing its contents."""

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _prepared_operation_id(scope_id: str, turn_id: str, attempt_no: int) -> str:
    """Derive a stable opaque operation ID for confirmation re-entry."""

    return _hash_record(
        {
            "provider_operation": LLM_DEBATE_OPERATION,
            "scope_id": scope_id,
            "turn_id": turn_id,
            "attempt_no": attempt_no,
        }
    )


def _safe_code(value: object, default: str = "llm_provider_failed") -> str:
    text = str(value)
    return (
        text
        if text
        and len(text) <= 64
        and all(char.isascii() and (char.isalnum() or char in "_.:-") for char in text)
        else default
    )


def _transport_decision(error: object) -> tuple[str, str, bool]:
    """Normalize the adapter's string acceptance classification safely."""

    classification: object = classify_transport_error(error)
    if isinstance(classification, str) and classification == "acceptance_unknown":
        # Protocol fakes may carry the richer acceptance fields directly on
        # the exception while the fixed adapter returns the string literal.
        if _read(error, "acceptance", _read(error, "acceptance_state")) is not None:
            classification = error
    if isinstance(classification, str):
        if classification == "not_sent":
            return "not_sent", "provider_not_sent", True
        return "acceptance_unknown", "acceptance_unknown", False
    acceptance = str(
        _result_value(
            classification,
            "acceptance",
            "acceptance_state",
            default="unknown",
        )
    )
    code = _safe_code(
        _result_value(
            classification,
            "safe_error_code",
            "code",
            default=("provider_not_sent" if acceptance == "not_sent" else "acceptance_unknown"),
        ),
        "acceptance_unknown",
    )
    not_sent = acceptance in {"not_sent", "transport_not_sent"} or (
        _result_value(classification, "retry_allowed", default=False) is True
        and code == "provider_not_sent"
    )
    return acceptance, code, not_sent


def _invoke(method: Callable[..., object], *args: object, **kwargs: object) -> object:
    """Use the post-0014 keyword shape, then the pre-migration shape."""

    try:
        return method(*args, **kwargs)
    except TypeError as first:
        if kwargs:
            try:
                return method(*args)
            except TypeError:
                raise first from None
        raise


def _method(value: object, *names: str) -> Callable[..., object] | None:
    for name in names:
        candidate = getattr(value, name, None)
        if callable(candidate):
            return cast(Callable[..., object], candidate)
    return None


def _result_value(value: object, *names: str, default: object = None) -> object:
    for name in names:
        candidate = _read(value, name)
        if candidate is not None:
            return candidate
    return default


class LLMTurnRuntime:
    """Coordinate one prepared Debate turn over injected provider ports."""

    def __init__(
        self,
        *,
        ledger: LLMRuntimeLedgerPort | object,
        adapter: object,
        stage_store: LLMAcceptedStagePort | object | None = None,
        manifest_store: LLMManifestPreparationPort | object | None = None,
        publication: LLMAtomicPublicationPort | object | None = None,
        confirmation: LLMConfirmationPort | Callable[..., bool] | object | None = None,
        price_card: object | None = None,
        tokenizer: object | None = None,
        agent_count: int = 2,
        round_count: int = 2,
        defer_publication: bool = False,
        max_attempts: int = LLM_MAX_ATTEMPTS,
        budget_cap: object | None = None,
    ) -> None:
        if isinstance(agent_count, bool) or not isinstance(agent_count, int) or agent_count < 2:
            raise ValueError("agent_count must be at least two")
        if round_count != 2:
            raise ValueError("LLM-A runtime is frozen to two rounds")
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts not in {1, 2}
        ):
            raise ValueError("max_attempts must be one or two")
        self.ledger = ledger
        self.adapter = adapter
        self.stage_store = stage_store
        self.manifest_store = manifest_store or ledger
        self.publication = publication
        self.confirmation = confirmation
        self.price_card = price_card or getattr(adapter, "price_card", None)
        self.tokenizer = tokenizer
        self.agent_count = agent_count
        self.round_count = round_count
        self.defer_publication = defer_publication
        self.max_attempts = max_attempts
        self.budget_cap = budget_cap
        self._recovery_inputs: dict[str, LLMRecoveryInputV1] = {}

    def _effective_max_attempts(self, prepared: object | None = None) -> int:
        """Honor the stricter one-shot ceiling carried by a turn manifest."""

        value = self.max_attempts
        manifest = _read(prepared, "outbound_manifest") if prepared is not None else None
        manifest_attempts = _read(manifest, "max_attempts") if manifest is not None else None
        if isinstance(manifest_attempts, int) and not isinstance(manifest_attempts, bool):
            value = min(value, manifest_attempts)
        return value

    def prepare_manifest(
        self,
        prompt: ProviderPromptV1,
        *,
        debate_id: str,
        turn_id: str,
        policy_hash: str,
        build_manifest_hash: str,
        policy_snapshot_id: str,
        course_id: str | None = None,
        group_id: str | None = None,
        agent_version_id: str | None = None,
        identity_tokens: Sequence[str] = (),
        outbound_manifest: LLMOutboundManifestV1 | None = None,
    ) -> ExportManifestV1:
        """Scan exact two-message bytes, then persist the owner-bound manifest.

        This is deliberately separate from :meth:`prepare`: the caller may
        expose the returned manifest for teacher confirmation before creating
        a zero-use operation.  No network boundary is reachable here.
        """

        if not isinstance(debate_id, str) or not debate_id:
            raise LLMRuntimeError(code="llm_owner_mismatch")
        if not isinstance(turn_id, str) or not turn_id:
            raise LLMRuntimeError(code="llm_owner_mismatch")
        if not isinstance(policy_hash, str) or not policy_hash:
            raise LLMRuntimeError(code="provider_preflight_blocked")
        if not isinstance(build_manifest_hash, str) or not build_manifest_hash:
            raise LLMRuntimeError(code="llm_build_manifest_missing")
        manifest = outbound_manifest or LLMOutboundManifestV1()
        self._require_adapter_preflight(manifest=manifest)
        self._scan(
            prompt,
            identity_tokens=identity_tokens,
            outbound_manifest=manifest,
        )
        try:
            cap = (
                cast(LLMBudgetCapV1, self.budget_cap)
                if self.budget_cap is not None
                else debate_budget_cap(
                    self.agent_count,
                    round_count=self.round_count,
                )
            )
            class_hashes = {
                "topic_and_platform_rules": prompt.request.rule_set_hash,
                "confirmed_structured_persona": prompt.request.persona_spec_hash,
                "public_predecessor_speech": prompt.request.transcript_hash,
                "current_evidence_excerpt": prompt.request.receipt_hash,
                "opaque_local_id": _hash_record((debate_id, turn_id)),
                "server_authored_structure_repair_feedback": REPAIR_FEEDBACK_POLICY_HASH,
            }
            fields = tuple(
                ExportFieldV1(field_class, class_hashes[field_class])
                for field_class in manifest.field_classes
                if field_class in class_hashes
            )
            result = ExportManifestV1(
                scope_id=debate_id,
                provider_operation=LLM_DEBATE_OPERATION,
                model_key=FIXED_MODELS[LLM_DEBATE_OPERATION],
                policy_hash=policy_hash,
                build_manifest_hash=build_manifest_hash,
                persona_spec_hash=prompt.request.persona_spec_hash,
                fields=fields,
                debate_id=debate_id,
                turn_id=turn_id,
                max_attempts=manifest.max_attempts,
                max_total_tokens=cap.max_total_tokens,
                max_cost_cny=float(cap.max_cost_cny),
                repair_policy_version=manifest.repair_policy_version,
                repair_policy_hash=manifest.repair_policy_hash,
            )
            ensure = _method(
                self.manifest_store,
                "ensure_export_manifest",
                "save_export_manifest",
            )
            if ensure is None:
                raise LLMRuntimeError(code="llm_manifest_store_unavailable")
            _invoke(
                ensure,
                result,
                policy_snapshot_id=policy_snapshot_id,
                course_id=course_id,
                group_id=group_id,
                agent_version_id=agent_version_id,
                debate_id=debate_id,
                turn_id=turn_id,
            )
            getter = _method(self.manifest_store, "get_export_manifest")
            persisted = _invoke(getter, result.manifest_hash) if getter is not None else result
            if not isinstance(persisted, ExportManifestV1) or persisted != result:
                raise LLMRuntimeError(code="llm_manifest_drift")
            return persisted
        except LLMRuntimeError:
            raise
        except Exception as exc:
            raise LLMRuntimeError(code="llm_manifest_prepare_failed") from exc

    def prepare(
        self,
        prompt: ProviderPromptV1,
        *,
        debate_id: str | None = None,
        turn_id: str | None = None,
        scope_id: str | None = None,
        policy_hash: str,
        manifest_hash: str,
        confirmation_revision: int = 1,
        fence: object | None = None,
        attempt_no: int = 1,
        retrieval_reused: bool = False,
        receipts: Sequence[object] = (),
        queries: Sequence[object] = (),
        build_manifest_hash: str = "",
        repair_policy_hash: str = "",
        identity_tokens: Sequence[str] = (),
        outbound_manifest: object | None = None,
        question_target_ids: Sequence[str] = (),
    ) -> LLMPreparedAttemptV1:
        """Freeze request identity and create a prepared zero-use operation."""

        if (
            isinstance(attempt_no, bool)
            or not isinstance(attempt_no, int)
            or attempt_no not in {1, 2}
            or attempt_no > self.max_attempts
        ):
            raise LLMRuntimeError(code="llm_attempt_exhausted")
        resolved_debate = debate_id or prompt.request.debate_id
        resolved_turn = turn_id or prompt.request.turn_id
        resolved_scope = scope_id or resolved_debate
        if resolved_debate != prompt.request.debate_id or resolved_turn != prompt.request.turn_id:
            raise LLMRuntimeError(code="llm_owner_mismatch")
        if confirmation_revision < 1:
            raise LLMRuntimeError(code="provider_revision_invalid")
        effective_manifest = cast(
            LLMOutboundManifestV1 | None,
            outbound_manifest or getattr(self.adapter, "outbound_manifest", None),
        )
        if effective_manifest is not None:
            manifest_attempts = _read(effective_manifest, "max_attempts")
            if (
                isinstance(manifest_attempts, int)
                and not isinstance(manifest_attempts, bool)
                and attempt_no > manifest_attempts
            ):
                raise LLMRuntimeError(code="llm_attempt_exceeds_manifest")
        effective_repair_policy_hash = repair_policy_hash or (
            effective_manifest.repair_policy_hash
            if effective_manifest is not None
            and effective_manifest.repair_policy_hash is not None
            else ""
        )
        self._require_adapter_preflight(manifest=effective_manifest)
        generation_fence = LLMGenerationFenceV1.from_value(fence, prompt.request)
        generation_fence_hash = _hash_record(generation_fence.as_record())
        self._scan(
            prompt,
            identity_tokens=identity_tokens,
            outbound_manifest=effective_manifest,
        )
        request = self._build_request(
            prompt,
            generation_fence=generation_fence_hash,
            policy_hash=policy_hash,
            export_manifest_hash=manifest_hash,
            repair_policy_hash=effective_repair_policy_hash,
            build_manifest_hash=build_manifest_hash,
            attempt_no=attempt_no,
            retrieval_reused=retrieval_reused,
            identity_tokens=identity_tokens,
            outbound_manifest=effective_manifest,
        )
        request_hash = self._request_hash(request, prompt)
        budget = _result_value(request, "budget", default=prompt.budget)
        price_card = self.price_card or _result_value(request, "price_card")
        cap = self._budget_cap(price_card, budget)
        ledger_request = self._reservation_request(
            request,
            prompt,
            request_hash=request_hash,
            debate_id=resolved_debate,
            turn_id=resolved_turn,
            scope_id=resolved_scope,
            policy_hash=policy_hash,
            manifest_hash=manifest_hash,
            attempt_no=attempt_no,
            cap=cap,
            price_card=price_card,
            build_manifest_hash=build_manifest_hash,
        )
        operation: object | None = None
        creator = _method(self.ledger, "create_prepared", "prepare")
        if creator is not None:
            try:
                operation = _invoke(creator, ledger_request, budget_bucket=LLM_DEBATE_BUCKET)
            except Exception as exc:
                # A teacher may confirm after an earlier zero-use prepare.
                # Re-enter that exact frozen operation instead of creating a
                # duplicate; any hash/state mismatch remains a hard failure.
                existing_get = _method(self.ledger, "get")
                existing = (
                    _invoke(
                        existing_get,
                        _prepared_operation_id(resolved_scope, resolved_turn, attempt_no),
                    )
                    if existing_get is not None
                    else None
                )
                if (
                    existing is None
                    or _operation_state(existing) != "prepared"
                    or _read(existing, "request_hash") != request_hash
                    or _read(existing, "policy_hash") != policy_hash
                    or _read(existing, "export_manifest_hash") != manifest_hash
                ):
                    raise LLMRuntimeError(code="llm_preparation_failed") from exc
                operation = existing
            self._assert_prepared_zero(operation)
        return LLMPreparedAttemptV1(
            prompt=prompt,
            request=request,
            operation=operation,
            request_hash=request_hash,
            debate_id=resolved_debate,
            turn_id=resolved_turn,
            scope_id=resolved_scope,
            policy_hash=policy_hash,
            manifest_hash=manifest_hash,
            confirmation_revision=confirmation_revision,
            fence=generation_fence,
            budget=budget,
            price_card=price_card,
            attempt_no=attempt_no,
            retrieval_reused=retrieval_reused,
            receipts=tuple(receipts),
            queries=tuple(queries),
            build_manifest_hash=build_manifest_hash,
            repair_policy_hash=effective_repair_policy_hash,
            generation_fence_hash=generation_fence_hash,
            identity_tokens=tuple(identity_tokens),
            outbound_manifest=effective_manifest,
            question_target_ids=tuple(question_target_ids),
        )

    def _require_adapter_preflight(self, *, manifest: object | None = None) -> None:
        """Fail closed unless a real adapter carries reviewed local inputs."""

        if not isinstance(self.adapter, DashScopeLLMAdapter):
            return
        tokenizer = self.tokenizer or getattr(self.adapter, "tokenizer", None)
        if tokenizer is None or not tokenizer_authorized(tokenizer):
            raise LLMRuntimeError(code="llm_tokenizer_unauthorized")
        card = cast(
            LLMPriceCardV1 | None,
            self.price_card or getattr(self.adapter, "price_card", None),
        )
        if card is None:
            raise LLMRuntimeError(code="llm_price_card_missing")
        try:
            rates = (
                card.input_rate,
                card.cached_input_rate,
                card.output_rate,
            )
            if any(value <= 0 for value in rates):
                raise LLMRuntimeError(code="llm_price_card_invalid")
        except LLMRuntimeError:
            raise
        except Exception as exc:
            raise LLMRuntimeError(code="llm_price_card_invalid") from exc
        if manifest is None and getattr(self.adapter, "outbound_manifest", None) is None:
            raise LLMRuntimeError(code="llm_manifest_missing")

    def _scan(
        self,
        prompt: ProviderPromptV1,
        *,
        identity_tokens: Sequence[str] = (),
        outbound_manifest: object | None = None,
    ) -> None:
        scanner = scan_llm_outbound_messages
        effective_manifest = cast(
            LLMOutboundManifestV1 | None,
            outbound_manifest or getattr(self.adapter, "outbound_manifest", None),
        )
        try:
            scanner(
                prompt.messages,
                identity_tokens=identity_tokens,
                field_classes=(
                    effective_manifest.field_classes if effective_manifest is not None else ()
                ),
            )
        except Exception as exc:
            raise LLMRuntimeError(
                code=_safe_code(_read(exc, "code"), "export_data_forbidden")
            ) from exc
        if self.tokenizer is not None and callable(tokenizer_authorized):
            try:
                authorized = bool(tokenizer_authorized(self.tokenizer))
            except Exception:
                authorized = False
            if not authorized:
                raise LLMRuntimeError(code="llm_tokenizer_unauthorized")

    def _build_request(
        self,
        prompt: ProviderPromptV1,
        *,
        generation_fence: str,
        policy_hash: str,
        export_manifest_hash: str,
        repair_policy_hash: str,
        build_manifest_hash: str,
        attempt_no: int,
        retrieval_reused: bool,
        identity_tokens: Sequence[str],
        outbound_manifest: object | None,
    ) -> object:
        builder = _method(self.adapter, "build_request", "request", "prepare_request")
        if builder is not None:
            try:
                value = _invoke(
                    builder,
                    prompt,
                    generation_fence=generation_fence,
                    policy_hash=policy_hash,
                    export_manifest_hash=export_manifest_hash,
                    repair_policy_hash=repair_policy_hash,
                    build_manifest_hash=build_manifest_hash,
                    attempt_no=attempt_no,
                    retrieval_reused=retrieval_reused,
                    identity_tokens=identity_tokens,
                    outbound_manifest=outbound_manifest,
                )
                if value is not None:
                    return value
            except Exception as exc:
                raise LLMRuntimeError(code="llm_request_invalid") from exc
        return prompt

    def _request_hash(self, request: object, prompt: ProviderPromptV1) -> str:
        value = _result_value(request, "request_hash", "hash")
        if isinstance(value, str) and value:
            return value
        hasher = _method(self.adapter, "request_hash", "compute_request_hash")
        if hasher is not None:
            try:
                candidate = _invoke(hasher, request)
                if isinstance(candidate, str) and candidate:
                    return candidate
            except Exception as exc:
                raise LLMRuntimeError(code="llm_request_hash_invalid") from exc
        # PromptRequest's hash is the only provider-free fallback.  The
        # adapter should normally supply a full endpoint/body hash.
        value = prompt.request.request_hash
        if not isinstance(value, str) or not value:
            raise LLMRuntimeError(code="llm_request_hash_invalid")
        return value

    def _budget_cap(self, price_card: object, budget: object) -> object:
        if self.budget_cap is not None:
            return self.budget_cap
        if callable(debate_budget_cap):
            try:
                return _invoke(
                    debate_budget_cap,
                    self.agent_count,
                    round_count=self.round_count,
                )
            except TypeError:
                try:
                    return _invoke(debate_budget_cap, self.agent_count)
                except Exception as exc:
                    raise LLMRuntimeError(code="llm_budget_invalid") from exc
            except Exception as exc:
                raise LLMRuntimeError(code="llm_budget_invalid") from exc
        return _result_value(budget, "cap", "budget_cap", default=budget)

    def _reservation_request(
        self,
        request: object,
        prompt: ProviderPromptV1,
        *,
        request_hash: str,
        debate_id: str,
        turn_id: str,
        scope_id: str,
        policy_hash: str,
        manifest_hash: str,
        attempt_no: int,
        cap: object,
        price_card: object,
        build_manifest_hash: str,
    ) -> object:
        builder = _method(self.adapter, "reservation_request", "build_reservation_request")
        if builder is not None:
            try:
                return _invoke(
                    builder,
                    request,
                    scope_id=scope_id,
                    debate_id=debate_id,
                    turn_id=turn_id,
                    policy_hash=policy_hash,
                    manifest_hash=manifest_hash,
                    request_hash=request_hash,
                    attempt_no=attempt_no,
                    budget_bucket=LLM_DEBATE_BUCKET,
                )
            except Exception as exc:
                raise LLMRuntimeError(code="llm_budget_invalid") from exc
        # The post-0014 ledger may accept keyword fields directly; preserve a
        # plain dict seam instead of defining another provider DTO here.
        budget_input = _as_int(
            _result_value(
                _result_value(request, "budget", default=prompt.budget),
                "max_input_tokens",
                "input_token_limit",
                default=0,
            )
        )
        budget_output = _as_int(
            _result_value(
                _result_value(request, "budget", default=prompt.budget),
                "max_output_tokens",
                "output_token_limit",
                "requested_output_tokens",
                default=0,
            )
        )
        max_tokens = budget_input + budget_output
        if max_tokens == 0:
            max_tokens = LLM_INPUT_TOKEN_CAP + LLM_RESERVED_OUTPUT_TOKEN_CAP
        # ``LLMBudgetCapV1.max_cost_cny`` is the debate-wide total.  A
        # reservation must carry the one-attempt ceiling, otherwise every
        # prepared turn would consume the complete 2x2 allowance and the
        # fifth call would fail despite the eight-call contract.
        max_cost: object = LLM_REQUEST_COST_CAP
        reservation_cost = _method(price_card, "reservation_cost")
        if reservation_cost is not None:
            try:
                max_cost = _invoke(
                    reservation_cost,
                    input_cap=budget_input or None,
                    output_cap=budget_output or None,
                )
            except (TypeError, ValueError):
                try:
                    max_cost = _invoke(reservation_cost)
                except Exception:
                    pass
        payload = {
            "operation_id": _prepared_operation_id(scope_id, turn_id, attempt_no),
            "scope_id": scope_id,
            "provider_operation": LLM_DEBATE_OPERATION,
            "logical_item_id": turn_id,
            "attempt_no": attempt_no,
            "request_hash": request_hash,
            "policy_hash": policy_hash,
            "export_manifest_hash": manifest_hash,
            "build_manifest_hash": build_manifest_hash
            or _result_value(request, "build_manifest_hash", default=prompt.request.receipt_hash),
            "model_key": LLM_MODEL_KEY,
            "max_tokens": max_tokens,
            "max_cost_cny": max_cost,
            "budget_bucket": LLM_DEBATE_BUCKET,
        }
        try:
            constructor = cast(
                Callable[..., ProviderReservationRequestV1], ProviderReservationRequestV1
            )
            return constructor(**payload)
        except Exception as exc:
            raise LLMRuntimeError(code="llm_budget_invalid") from exc

    @staticmethod
    def _assert_prepared_zero(operation: object) -> None:
        if _operation_state(operation) not in {None, "prepared"}:
            raise LLMRuntimeError(code="llm_preparation_failed")
        if any(
            _as_int(_read(operation, field, 0)) != 0
            for field in ("request_count", "charged_request_count")
        ):
            raise LLMRuntimeError(code="llm_preparation_failed")
        if _read(operation, "reservation_id") not in {None, ""}:
            raise LLMRuntimeError(code="llm_preparation_failed")

    def _confirmed(self, prepared: LLMPreparedAttemptV1, explicit: object | None) -> bool:
        if explicit is not None:
            return bool(explicit)
        value = self.confirmation
        if value is None:
            return False
        checker = _method(value, "is_confirmed", "confirmed")
        if checker is None and callable(value):
            checker = cast(Callable[..., object], value)
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

    def _send(self, prepared: LLMPreparedAttemptV1) -> object:
        sender = _method(
            self.adapter,
            "send_accepted",
            "execute",
            "send",
            "complete",
            "generate",
            "call",
        )
        if sender is None:
            raise LLMRuntimeError(code="llm_adapter_unavailable")
        if getattr(sender, "__name__", "") == "send_accepted":
            metadata = {
                "prompt": prepared.prompt,
                "generation_fence": prepared.generation_fence_hash,
                "policy_hash": prepared.policy_hash,
                "export_manifest_hash": prepared.manifest_hash,
                "repair_policy_hash": prepared.repair_policy_hash or None,
                "build_manifest_hash": prepared.build_manifest_hash,
                "attempt_no": prepared.attempt_no,
                "retrieval_reused": prepared.retrieval_reused,
                "identity_tokens": prepared.identity_tokens,
                "outbound_manifest": prepared.outbound_manifest,
                "question_target_ids": prepared.question_target_ids,
            }
            # Inspect the callable before invoking it.  A metadata mismatch is
            # a pre-call compatibility problem; catching ``TypeError`` after
            # invocation could otherwise repeat a real transport call made by
            # a protocol-compatible fake.
            try:
                parameters: tuple[inspect.Parameter, ...] = tuple(
                    inspect.signature(sender).parameters.values()
                )
            except (TypeError, ValueError):
                parameters = ()
            accepts_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
            )
            accepted_names = {
                parameter.name
                for parameter in parameters
                if parameter.kind
                in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
            }
            kwargs = metadata if accepts_kwargs else {
                name: value for name, value in metadata.items() if name in accepted_names
            }
            return sender(prepared.request, **kwargs)
        if getattr(sender, "__name__", "") == "execute":
            try:
                return _invoke(
                    sender,
                    prepared.prompt,
                    generation_fence=prepared.generation_fence_hash,
                    policy_hash=prepared.policy_hash,
                    export_manifest_hash=prepared.manifest_hash,
                    repair_policy_hash=prepared.repair_policy_hash or None,
                    build_manifest_hash=prepared.build_manifest_hash,
                    attempt_no=prepared.attempt_no,
                    retrieval_reused=prepared.retrieval_reused,
                    identity_tokens=prepared.identity_tokens,
                    outbound_manifest=prepared.outbound_manifest,
                    question_target_ids=prepared.question_target_ids,
                )
            except TypeError as first:
                # A protocol-compatible fake may expose ``execute(prompt)``;
                # never let a metadata mismatch create a second network call.
                try:
                    return _invoke(sender, prepared.prompt)
                except TypeError:
                    raise first from None
        try:
            return _invoke(sender, prepared.request, prompt=prepared.prompt)
        except TypeError:
            return _invoke(sender, prepared.prompt)

    def _transition(
        self,
        operation_id: str,
        action: str,
        *,
        code: str | None = None,
        response: object | None = None,
    ) -> object | None:
        method = _method(self.ledger, action)
        kwargs: dict[str, object] = {}
        if code is not None:
            kwargs["safe_error_code"] = code
        if response is not None:
            response_hash = _result_value(response, "response_hash", "hash")
            if response_hash is not None:
                kwargs["response_hash"] = response_hash
        if method is not None:
            return _invoke(method, operation_id, **kwargs)
        transition = _method(self.ledger, "transition")
        if transition is None:
            raise LLMRuntimeError(code="llm_operation_transition_failed")
        current = _method(self.ledger, "get")
        operation = _invoke(current, operation_id) if current is not None else None
        state = {
            "mark_accepted": "accepted",
            "mark_succeeded": "succeeded",
            "mark_not_sent": "not_sent",
            "mark_acceptance_unknown": "acceptance_unknown",
            "mark_failed": "failed",
        }.get(action)
        if state is None:
            raise LLMRuntimeError(code="llm_operation_transition_failed")
        kwargs = {"expected": _operation_state(operation) or "sending", "state": state, **kwargs}
        return _invoke(transition, operation_id, **kwargs)

    def _fail_operation(
        self,
        operation_id: str | None,
        operation: object | None,
        code: str,
    ) -> object | None:
        if operation_id is None:
            return operation
        if _operation_state(operation) in {"succeeded", "failed", "not_sent", "acceptance_unknown"}:
            return operation
        try:
            return self._transition(operation_id, "mark_failed", code=code)
        except Exception:
            return operation

    def _accepted_stage_value(
        self,
        prepared: LLMPreparedAttemptV1,
        response: object,
    ) -> object:
        """Adapt the provider result to the ledger-owned immutable stage DTO."""

        existing = _result_value(response, "accepted_stage", "stage")
        if isinstance(existing, LLMAcceptedStageV1):
            return existing
        if isinstance(existing, LLMAcceptedCandidateV1):
            response = existing
        operation_id = prepared.operation_id
        if operation_id is None:
            raise LLMRuntimeError(code="llm_stage_unavailable")
        request = prepared.request
        usage = _result_value(response, "usage")
        output_json = _result_value(
            response,
            "stage_json",
            "accepted_stage_json",
            "provider_output_json",
            "accepted_output_json",
            "output_json",
        )
        output_hash = _result_value(
            response,
            "stage_hash",
            "accepted_stage_hash",
            "provider_output_hash",
            "accepted_output_hash",
            "output_hash",
        )
        if not isinstance(output_json, str) or not isinstance(output_hash, str):
            raise LLMRuntimeError(code="llm_stage_unavailable")
        card = self.price_card or _read(response, "_price_card")
        fields: dict[str, object] = {
            "operation_id": operation_id,
            "turn_id": prepared.turn_id,
            "attempt_no": prepared.attempt_no,
            "request_hash": prepared.request_hash,
            "prompt_hash": _result_value(
                request, "prompt_hash", default=prepared.prompt.request_hash
            ),
            "prompt_contract_version": _result_value(
                request, "prompt_contract_version", default="PromptRequestV1"
            ),
            "schema_hash": _result_value(request, "schema_hash", "output_schema_hash", default=""),
            "tokenizer_id": _result_value(
                request,
                "tokenizer_id",
                default=_result_value(prepared.budget, "tokenizer_id", default=""),
            ),
            "tokenizer_hash": _result_value(
                request,
                "tokenizer_asset_hash",
                "tokenizer_hash",
                default=_result_value(prepared.budget, "tokenizer_asset_hash", default=""),
            ),
            "rule_set_hash": _result_value(
                request, "rule_set_hash", default=prepared.prompt.request.rule_set_hash
            ),
            "persona_spec_hash": _result_value(
                request, "persona_spec_hash", default=prepared.prompt.request.persona_spec_hash
            ),
            "transcript_hash": _result_value(
                request, "transcript_hash", default=prepared.prompt.request.transcript_hash
            ),
            "receipt_hash": _result_value(
                request, "receipt_hash", default=prepared.prompt.request.receipt_hash
            ),
            "policy_hash": _result_value(request, "policy_hash", default=prepared.policy_hash),
            "export_manifest_hash": _result_value(
                request, "export_manifest_hash", default=prepared.manifest_hash
            ),
            "build_manifest_hash": _result_value(
                request,
                "build_manifest_hash",
                default=prepared.build_manifest_hash or prepared.prompt.request.receipt_hash,
            ),
            "model_key": _result_value(request, "model_key", default=LLM_MODEL_KEY),
            "output_json": output_json,
            "output_hash": output_hash,
            "prompt_tokens": _as_int(
                _result_value(usage, "prompt_tokens", "input_tokens", default=0)
            ),
            "cached_input_tokens": _as_int(
                _result_value(usage, "cached_input_tokens", "cached_tokens", default=0)
            ),
            "completion_tokens": _as_int(
                _result_value(usage, "completion_tokens", "output_tokens", default=0)
            ),
            "total_tokens": _as_int(_result_value(usage, "total_tokens", default=0)),
            "retrieval_reused": prepared.retrieval_reused,
            "safe_error_code": _result_value(response, "safe_error_code", default=None),
            "generation_fence": _result_value(
                request, "generation_fence", default=prepared.generation_fence_hash
            ),
            "repair_policy_hash": _result_value(
                request, "repair_policy_hash", default=prepared.repair_policy_hash or None
            ),
            "repair_policy_version": _result_value(
                response,
                "repair_policy_version",
                default=None,
            )
            or (
                _read(prepared.outbound_manifest, "repair_policy_version")
                if prepared.repair_policy_hash
                else None
            ),
            "estimated_cost_cny": _result_value(response, "estimated_cost_cny", default=0),
            "actual_cost_cny": _result_value(response, "actual_cost_cny", default=None),
        }
        if card is not None:
            fields.update(
                {
                    "price_card_version": _result_value(card, "version", default="price-card-v1"),
                    "input_price_cny_per_million": _result_value(
                        card,
                        "input_price_per_million",
                        "input_rate",
                        default=0,
                    ),
                    "cached_input_price_cny_per_million": _result_value(
                        card,
                        "cached_input_price_per_million",
                        "cached_input_rate",
                        default=0,
                    ),
                    "output_price_cny_per_million": _result_value(
                        card,
                        "output_price_per_million",
                        "output_rate",
                        default=0,
                    ),
                }
            )
        try:
            constructor = cast(Callable[..., LLMAcceptedStageV1], LLMAcceptedStageV1)
            return constructor(**fields)
        except Exception as exc:
            raise LLMRuntimeError(code="llm_stage_unavailable") from exc

    @staticmethod
    def _has_accepted_payload(response: object) -> bool:
        output_json = _result_value(
            response,
            "stage_json",
            "accepted_stage_json",
            "accepted_output_json",
            "provider_output_json",
            "output_json",
        )
        output_hash = _result_value(
            response,
            "stage_hash",
            "accepted_stage_hash",
            "accepted_output_hash",
            "provider_output_hash",
            "output_hash",
        )
        return isinstance(output_json, str) and isinstance(output_hash, str)

    def _validate_accepted(
        self,
        prepared: LLMPreparedAttemptV1,
        accepted: object,
        stage: object | None,
    ) -> object:
        """Validate/map sanitized accepted content after durable staging."""

        validator = _method(
            self.adapter,
            "validate_accepted",
            "validate_staged_output",
            "map_accepted_output",
        )
        if validator is None:
            return accepted
        try:
            try:
                return _invoke(
                    validator,
                    accepted,
                    stage=stage,
                    request=prepared.request,
                )
            except TypeError:
                return _invoke(validator, accepted)
        except LLMOutputError as exc:
            request = _read(accepted, "request", default=prepared.request)
            usage = _read(accepted, "usage")
            safe_code = str(exc.code)
            failure_kind: AttemptFailureKind = (
                "structure_invalid"
                if safe_code in {
                    "output_truncated",
                    "json_invalid",
                    "schema_invalid",
                    "reference_invalid",
                    "rule_invalid",
                }
                else (
                    "provider_usage_unknown"
                    if safe_code == "provider_usage_unknown"
                    else (
                        "provider_usage_overrun"
                        if safe_code in {"provider_usage_overrun", "provider_cost_overrun"}
                        else "provider_terminal"
                    )
                )
            )
            return LLMValidatedResultV1(
                status="failed",
                acceptance="accepted",
                failure_kind=failure_kind,
                safe_error_code=safe_code,
                request=cast(LLMRequestV1, request),
                usage=cast(LLMUsageV1 | None, usage),
                accepted_candidate=(
                    accepted if isinstance(accepted, LLMAcceptedCandidateV1) else None
                ),
                json_pointers=tuple(exc.json_pointers),
                estimated_cost_cny=cast(
                    Decimal, _read(accepted, "estimated_cost_cny", default=Decimal("0"))
                ),
                actual_cost_cny=cast(Decimal | None, _read(accepted, "actual_cost_cny")),
            )
        except Exception:
            if _read(accepted, "schema_valid") is False:
                return accepted
            raise

    def _stage(
        self,
        prepared: LLMPreparedAttemptV1,
        response: object,
        *,
        context: GenerationContext | None = None,
    ) -> tuple[object, object | None]:
        accepted = self._accepted_stage_value(prepared, response)
        recovery_input: LLMRecoveryInputV1 | None = None
        combined_store = _method(
            self.stage_store,
            "stage_accepted_with_recovery",
            "stage_llm_accepted_with_recovery",
        )
        if combined_store is None:
            combined_store = _method(
                self.ledger,
                "stage_accepted_with_recovery",
                "stage_llm_accepted_with_recovery",
            )
        # Legacy/unit callers may intentionally exercise the stage-only port
        # without a GenerationContext.  The production playback path always
        # supplies context and therefore takes the combined stage+recovery
        # seam; retain the older stage-only behavior for those fakes.
        if combined_store is not None and context is None:
            combined_store = None
        if combined_store is not None:
            try:
                assert context is not None
                recovery_input = build_llm_recovery_input(prepared, context, stage=accepted)
                accepted = _invoke(combined_store, accepted, recovery_input)
                if prepared.operation_id is not None:
                    self._recovery_inputs[prepared.operation_id] = recovery_input
            except Exception as exc:
                raise LLMRuntimeError(code="llm_stage_unavailable") from exc
        stage_method = (
            _method(
                self.stage_store,
                "stage_llm_accepted",
                "save_llm_accepted_stage",
                "persist_llm_accepted_stage",
                "record_llm_accepted_stage",
            )
            if self.stage_store is not None
            else None
        )
        # The post-0014 ledger owns the immutable accepted-stage row and its
        # sending->accepted transition.  A dedicated stage_store remains a
        # valid fake for focused tests, but production adapters should expose
        # this atomic method on the ledger.
        if stage_method is None:
            stage_method = _method(
                self.ledger,
                "stage_llm_accepted",
                "stage_accepted_llm",
                "record_llm_accepted",
            )
        if stage_method is not None and combined_store is None:
            try:
                accepted = _invoke(
                    stage_method,
                    accepted,
                    operation_id=prepared.operation_id,
                    turn_id=prepared.turn_id,
                    attempt_no=prepared.attempt_no,
                )
            except Exception as exc:
                raise LLMRuntimeError(code="llm_stage_unavailable") from exc
        operation: object | None = prepared.operation
        if (
            (stage_method is not None or combined_store is not None)
            and prepared.operation_id is not None
        ):
            getter = _method(self.ledger, "get")
            if getter is not None:
                operation = _invoke(getter, prepared.operation_id)
        if (
            combined_store is None
            and
            stage_method is None
            and prepared.operation_id is not None
            and _operation_state(operation) != "accepted"
        ):
            operation = self._transition(prepared.operation_id, "mark_accepted", response=response)
        return operation or response, accepted

    def _map_result(self, response: object, prompt: PromptRequestV1) -> MutualLearningTurnResultV1:
        value = _result_value(response, "result", "mapped", "turn", "output", default=response)
        if isinstance(value, MutualLearningTurnResultV1):
            return value
        mapper = map_provider_output
        if callable(mapper):
            try:
                mapped = _invoke(mapper, value, prompt)
            except TypeError:
                mapped = _invoke(mapper, value, request=prompt)
            candidate = _result_value(mapped, "result", "turn", "value", default=mapped)
            if isinstance(candidate, MutualLearningTurnResultV1):
                return candidate
        raise LLMRuntimeError(code="llm_output_invalid")

    def _repair_request(self, prepared: LLMPreparedAttemptV1, response: object) -> object:
        code = _safe_code(
            _result_value(
                response, "safe_error_code", "error_code", "code", default="schema_invalid"
            ),
            "schema_invalid",
        )
        if code not in REPAIR_CODES:
            code = "schema_invalid"
        pointers_value = _result_value(response, "json_pointers", "pointers", default=())
        pointers = tuple(str(item) for item in _sequence(pointers_value))[:12]
        try:
            # PromptRequestV1 owns the immutable identity check.  The provider
            # adapter then serializes this request; no adapter-specific copy
            # of the repair schema is needed here.
            try:
                return repair_prompt_request(
                    prepared.prompt.request,
                    safe_error_code=code,
                    json_pointers=pointers,
                )
            except Exception:
                # The current PromptRequest contract accepts a single root
                # pointer while the provider mapper may return nested paths;
                # the root remains a closed, non-sensitive repair hint.
                return repair_prompt_request(
                    prepared.prompt.request,
                    safe_error_code=code,
                    json_pointers=("/",),
                )
        except Exception as exc:
            raise LLMRuntimeError(code="llm_repair_policy_invalid") from exc

    def _attempt_two(
        self, prepared: LLMPreparedAttemptV1, *, response: object | None = None
    ) -> LLMPreparedAttemptV1:
        request = prepared.request
        if response is None:
            # A proven not-sent transport retry reuses the exact frozen
            # provider prompt and retrieval identity.  Only the durable
            # attempt number changes; the adapter owns its wire idempotency.
            prompt = prepared.prompt
        else:
            request = self._repair_request(prepared, response)
            builder = _method(self.adapter, "prompt_from_request", "provider_prompt_from_request")
            if builder is not None:
                try:
                    prompt = cast(ProviderPromptV1, _invoke(builder, prepared.prompt, request))
                except Exception as exc:
                    raise LLMRuntimeError(code="llm_repair_policy_invalid") from exc
            elif isinstance(request, PromptRequestV1):
                user = request.canonical_json()
                prompt = ProviderPromptV1(
                    request=request,
                    messages=(
                        prepared.prompt.system_message,
                        PromptMessageV1(role="user", content=user),
                    ),
                    budget=prepared.prompt.budget,
                    request_hash=request.request_hash,
                    system_rules_hash=prepared.prompt.system_rules_hash,
                )
            else:
                raise LLMRuntimeError(code="llm_repair_policy_invalid")
        return self.prepare(
            prompt,
            debate_id=prepared.debate_id,
            turn_id=prepared.turn_id,
            scope_id=prepared.scope_id,
            policy_hash=prepared.policy_hash,
            manifest_hash=prepared.manifest_hash,
            confirmation_revision=prepared.confirmation_revision,
            fence=prepared.fence,
            attempt_no=2,
            retrieval_reused=True,
            receipts=prepared.receipts,
            queries=prepared.queries,
            build_manifest_hash=prepared.build_manifest_hash,
            repair_policy_hash=prepared.repair_policy_hash,
            identity_tokens=prepared.identity_tokens,
            outbound_manifest=prepared.outbound_manifest,
            question_target_ids=prepared.question_target_ids,
        )

    @staticmethod
    def _attach_evidence_trace(
        checked: object,
        *,
        prepared: LLMPreparedAttemptV1,
        context: GenerationContext,
    ) -> ValidatedTurn:
        """Derive server-owned trace rows after mutual-result validation."""

        checked_turn = cast(ValidatedTurn, checked)
        result = checked_turn.result
        if not isinstance(result, MutualLearningTurnResultV1):
            return checked_turn
        claims: Sequence[EvidenceTraceClaimV1 | KeyClaimV1] = result.evidence_trace_claims
        if not claims and result.key_claims:
            try:
                for claim in result.key_claims:
                    derive_exact_speech_span(result.speech, claim.claim_text)
            except ValueError:
                # Legacy Mock results may contain summaries rather than exact
                # spans.  Do not manufacture provenance for those rows.
                claims = ()
            else:
                claims = tuple(result.key_claims)
        if not claims:
            if getattr(context.turn, "barrier", "prefix") == "round":
                raise TurnValidationError(
                    "Strict mutual-learning turns require evidence trace claims.",
                    code="evidence_trace_missing",
                )
            return checked_turn
        try:
            bundle = build_evidence_trace_bundle(
                context.turn.turn_id,
                result.speech,
                claims,
                cast(Sequence[SnapshotRetrievalReceipt], prepared.receipts),
                cast(Sequence[TurnSubquery], prepared.queries),
                snapshot_id=context.participant.snapshot_id,
            )
            aligned = align_mutual_learning_claim_ids(result, bundle)
        except Exception as exc:
            raise TurnValidationError("The mutual evidence trace is invalid.") from exc
        return replace(
            checked_turn,
            result=aligned,
            evidence_trace=tuple(item.model_dump(mode="json") for item in bundle.traces),
        )

    def run(
        self,
        prepared: LLMPreparedAttemptV1,
        *,
        context: GenerationContext | None = None,
        confirmed: object | None = None,
        validator: MutualLearningValidator | None = None,
    ) -> LLMRunOutcomeV1:
        if not self._confirmed(prepared, confirmed):
            trace = LLMAttemptTraceV1(
                prepared.attempt_no,
                prepared.request_hash,
                prepared.operation_id,
                False,
                "none",
                "provider_confirmation_required",
            )
            return LLMRunOutcomeV1(
                "provider_confirmation_required",
                attempts=(trace,),
                operation=prepared.operation,
                safe_error_code="provider_confirmation_required",
                retry_allowed=True,
            )
        current = prepared
        traces: list[LLMAttemptTraceV1] = []
        max_attempts = self._effective_max_attempts(prepared)
        while current.attempt_no <= max_attempts:
            operation: object | None = current.operation
            operation_id = current.operation_id
            try:
                operation = current.operation
                reserve = _method(self.ledger, "reserve")
                if operation_id is not None:
                    if reserve is None:
                        raise LLMRuntimeError(code="llm_reservation_failed")
                    try:
                        _invoke(reserve, operation_id, budget_bucket=LLM_DEBATE_BUCKET)
                    except Exception as exc:
                        raise LLMRuntimeError(code="llm_reservation_failed") from exc
                    sending = _method(self.ledger, "mark_sending")
                    if sending is not None:
                        try:
                            operation = _invoke(sending, operation_id)
                        except Exception as exc:
                            raise LLMRuntimeError(code="llm_sending_transition_failed") from exc
                    else:
                        transition = _method(self.ledger, "transition")
                        if transition is None:
                            raise LLMRuntimeError(code="llm_sending_transition_failed")
                        try:
                            operation = _invoke(
                                transition,
                                operation_id,
                                expected="reserved",
                                state="sending",
                            )
                        except Exception as exc:
                            raise LLMRuntimeError(code="llm_sending_transition_failed") from exc
                # Re-check the exact wire messages after the durable sending
                # fence and immediately before the adapter boundary.  A
                # privacy/manifest failure is a local terminal failure, never
                # an acceptance-unknown transport event.
                self._scan(
                    current.prompt,
                    identity_tokens=current.identity_tokens,
                    outbound_manifest=current.outbound_manifest,
                )
                response = self._send(current)
            except LLMRuntimeError as exc:
                # Reservation/sending failures happen before any adapter
                # boundary and therefore are terminal zero-call failures.
                if exc.code.startswith("llm_") or exc.code in {
                    "llm_reservation_failed",
                    "llm_sending_transition_failed",
                    "llm_operation_transition_failed",
                    "llm_preparation_failed",
                    "llm_outbound_data_forbidden",
                    "llm_manifest_field_forbidden",
                    "llm_manifest_fields_missing",
                    "llm_manifest_invalid",
                    "llm_repair_policy_missing",
                    "llm_repair_policy_stale",
                    "llm_repair_field_missing",
                    "llm_tokenizer_unauthorized",
                }:
                    if operation_id is not None:
                        try:
                            operation = self._transition(
                                operation_id,
                                "mark_failed",
                                code=exc.code,
                            )
                        except Exception:
                            pass
                    traces.append(
                        LLMAttemptTraceV1(
                            current.attempt_no,
                            current.request_hash,
                            operation_id,
                            False,
                            "none",
                            exc.code,
                        )
                    )
                    return LLMRunOutcomeV1(
                        "failed",
                        tuple(traces),
                        operation,
                        safe_error_code=exc.code,
                    )
                acceptance, code, not_sent = _transport_decision(exc)
                if not_sent:
                    if operation_id is not None:
                        operation = self._transition(
                            operation_id,
                            "mark_not_sent",
                            code="provider_not_sent",
                        )
                    traces.append(
                        LLMAttemptTraceV1(
                            current.attempt_no,
                            current.request_hash,
                            operation_id,
                            True,
                            "not_sent",
                            "provider_not_sent",
                        )
                    )
                    if current.attempt_no == 1 and max_attempts >= 2:
                        current = self._attempt_two(current)
                        continue
                    return LLMRunOutcomeV1(
                        "not_sent",
                        tuple(traces),
                        operation,
                        safe_error_code="provider_not_sent",
                    )
                if operation_id is not None:
                    operation = self._transition(
                        operation_id,
                        "mark_acceptance_unknown",
                        code="acceptance_unknown",
                    )
                traces.append(
                    LLMAttemptTraceV1(
                        current.attempt_no,
                        current.request_hash,
                        operation_id,
                        True,
                        "unknown",
                        "acceptance_unknown",
                    )
                )
                return LLMRunOutcomeV1(
                    "acceptance_unknown",
                    tuple(traces),
                    operation,
                    safe_error_code="acceptance_unknown",
                )
            except Exception as exc:
                acceptance, code, not_sent = _transport_decision(exc)
                if not_sent:
                    if operation_id is not None:
                        operation = self._transition(
                            operation_id,
                            "mark_not_sent",
                            code="provider_not_sent",
                        )
                    traces.append(
                        LLMAttemptTraceV1(
                            current.attempt_no,
                            current.request_hash,
                            operation_id,
                            True,
                            "not_sent",
                            "provider_not_sent",
                        )
                    )
                    if current.attempt_no == 1 and max_attempts >= 2:
                        current = self._attempt_two(current)
                        continue
                    return LLMRunOutcomeV1(
                        "not_sent",
                        tuple(traces),
                        operation,
                        safe_error_code="provider_not_sent",
                    )
                if operation_id is not None:
                    operation = self._transition(
                        operation_id,
                        "mark_acceptance_unknown",
                        code="acceptance_unknown",
                    )
                traces.append(
                    LLMAttemptTraceV1(
                        current.attempt_no,
                        current.request_hash,
                        operation_id,
                        True,
                        "unknown",
                        "acceptance_unknown",
                    )
                )
                return LLMRunOutcomeV1(
                    "acceptance_unknown",
                    tuple(traces),
                    operation,
                    safe_error_code="acceptance_unknown",
                )
            response_acceptance = str(
                _result_value(response, "acceptance", "acceptance_state", default="accepted")
            )
            if response_acceptance in {"not_sent", "transport_not_sent"}:
                code = "provider_not_sent"
                if operation_id is not None:
                    operation = self._transition(
                        operation_id,
                        "mark_not_sent",
                        code=code,
                    )
                traces.append(
                    LLMAttemptTraceV1(
                        current.attempt_no,
                        current.request_hash,
                        operation_id,
                        True,
                        "not_sent",
                        code,
                    )
                )
                if current.attempt_no == 1 and max_attempts >= 2:
                    current = self._attempt_two(current)
                    continue
                return LLMRunOutcomeV1(
                    "not_sent",
                    tuple(traces),
                    operation,
                    safe_error_code=code,
                )
            if response_acceptance not in {"accepted", ""}:
                code = "acceptance_unknown"
                if operation_id is not None:
                    operation = self._transition(
                        operation_id,
                        "mark_acceptance_unknown",
                        code=code,
                    )
                traces.append(
                    LLMAttemptTraceV1(
                        current.attempt_no,
                        current.request_hash,
                        operation_id,
                        True,
                        "unknown",
                        code,
                    )
                )
                return LLMRunOutcomeV1(
                    "acceptance_unknown",
                    tuple(traces),
                    operation,
                    safe_error_code=code,
                )
            # The fixed adapter returns an immutable validated-result object;
            # keep that envelope so usage, hashes and acceptance state reach
            # the stage ledger.  Legacy fakes may still wrap the result under
            # ``accepted``/``validated``.
            if _read(response, "request") is not None and _read(response, "acceptance") is not None:
                accepted = response
            else:
                accepted = _result_value(
                    response, "accepted", "validated", "response", default=response
                )
            stage: object | None = None
            recovery_input: LLMRecoveryInputV1 | None = None
            has_stage = _result_value(accepted, "accepted_stage", "stage") is not None
            if has_stage or self._has_accepted_payload(accepted):
                try:
                    operation, stage = self._stage(
                        current,
                        accepted,
                        context=context,
                    )
                    recovery_input = self._recovery_inputs.pop(operation_id or "", None)
                except LLMRuntimeError as exc:
                    operation = self._fail_operation(operation_id, operation, exc.code)
                    return LLMRunOutcomeV1(
                        "failed", tuple(traces), operation, safe_error_code=exc.code
                    )
            accepted = self._validate_accepted(current, accepted, stage)
            safe_error = _result_value(accepted, "safe_error_code", "error_code", "code")
            repairable = bool(_result_value(accepted, "repairable", "retry_allowed", default=False))
            if (
                not repairable
                and current.attempt_no == 1
                and max_attempts >= 2
                and _result_value(accepted, "failure_kind") == "structure_invalid"
                and str(
                    _result_value(accepted, "acceptance", "acceptance_state", default="accepted")
                )
                in {"accepted", ""}
            ):
                # Provider references and other mapper-level shape failures
                # are safe to repair with the closed code/pointer envelope;
                # raw rejected content never enters the second request.
                repairable = True
            if (
                not repairable
                and current.attempt_no == 1
                and max_attempts >= 2
                and safe_error in {"output_truncated", "json_invalid", "schema_invalid"}
                and _read(accepted, "schema_valid") is False
            ):
                repairable = True
            if safe_error and not repairable:
                code = _safe_code(safe_error)
                if operation_id is not None:
                    operation = self._transition(operation_id, "mark_failed", code=code)
                traces.append(
                    LLMAttemptTraceV1(
                        current.attempt_no,
                        current.request_hash,
                        operation_id,
                        True,
                        "accepted",
                        code,
                    )
                )
                return LLMRunOutcomeV1(
                    "failed",
                    tuple(traces),
                    self._fail_operation(operation_id, operation, code),
                    stage=stage,
                    safe_error_code=code,
                )
            if repairable:
                code = _safe_code(safe_error or "schema_invalid", "schema_invalid")
                traces.append(
                    LLMAttemptTraceV1(
                        current.attempt_no,
                        current.request_hash,
                        operation_id,
                        True,
                        "accepted",
                        code,
                    )
                )
                if current.attempt_no == 1 and max_attempts >= 2:
                    operation = self._fail_operation(operation_id, operation, code)
                    current = self._attempt_two(current, response=accepted)
                    continue
                return LLMRunOutcomeV1(
                    "failed",
                    tuple(traces),
                    self._fail_operation(operation_id, operation, code),
                    stage=stage,
                    safe_error_code=code,
                )
            try:
                result = self._map_result(accepted, current.prompt.request)
                final: FinalReadyTurn | None = None
                if context is not None:
                    checked = (validator or MutualLearningValidator()).validate(
                        result,
                        plan=context.turn,
                        participant=context.participant,
                        participants=context.participants,
                        receipts=cast(
                            Sequence[SnapshotRetrievalReceipt], current.receipts
                        ),
                        predecessors=context.predecessors,
                        pending_question=context.effective_pending_question,
                    )
                    checked = self._attach_evidence_trace(
                        checked,
                        prepared=current,
                        context=context,
                    )
                    final = final_ready_turn(
                        checked,
                        turn_id=context.turn.turn_id,
                        participant_id=context.participant.participant_id,
                        snapshot_id=context.participant.snapshot_id,
                        round_no=context.turn.round_no,
                        turn_index=context.turn.turn_index,
                        predecessor_turn_ids=current.fence.predecessor_turn_ids,
                        cutoff_turn_index=current.fence.cutoff_turn_index,
                        transcript_hash=current.fence.transcript_hash,
                        attempt=current.attempt_no,
                    )
                publication_result = self._publish(
                    current,
                    operation=operation,
                    stage=stage,
                    result=result,
                    final=final,
                    usage=_result_value(accepted, "usage"),
                )
                deferred_publication: object | None = None
                if isinstance(publication_result, LLMDeferredPublicationV1):
                    deferred_publication = publication_result
                elif publication_result is not None:
                    operation = publication_result
            except TurnValidationError:
                traces.append(
                    LLMAttemptTraceV1(
                        current.attempt_no,
                        current.request_hash,
                        operation_id,
                        True,
                        "accepted",
                        "rule_invalid",
                    )
                )
                if current.attempt_no == 1 and max_attempts >= 2:
                    operation = self._fail_operation(operation_id, operation, "rule_invalid")
                    current = self._attempt_two(current, response=accepted)
                    continue
                return LLMRunOutcomeV1(
                    "failed",
                    tuple(traces),
                    self._fail_operation(operation_id, operation, "rule_invalid"),
                    stage=stage,
                    safe_error_code="rule_invalid",
                )
            except LLMRuntimeError as exc:
                operation = self._fail_operation(operation_id, operation, exc.code)
                return LLMRunOutcomeV1(
                    "failed", tuple(traces), operation, stage=stage, safe_error_code=exc.code
                )
            traces.append(
                LLMAttemptTraceV1(
                    current.attempt_no, current.request_hash, operation_id, True, "accepted"
                )
            )
            return LLMRunOutcomeV1(
                "succeeded",
                tuple(traces),
                operation,
                stage=stage,
                result=result,
                final_ready=final,
                deferred_publication=(
                    LLMDeferredPublicationV1(
                        operation_id=str(operation_id),
                        turn_id=current.turn_id,
                        debate_id=current.debate_id,
                        request_hash=current.request_hash,
                        operation=operation,
                        stage=stage,
                        usage=_result_value(accepted, "usage"),
                        result=result,
                        final_ready=final,
                        recovery_input=recovery_input,
                    )
                    if self.defer_publication
                    and operation_id is not None
                    and stage is not None
                    and final is not None
                    else deferred_publication
                ),
            )
        return LLMRunOutcomeV1("failed", tuple(traces), safe_error_code="llm_attempt_exhausted")

    execute = run

    def _publish(
        self,
        prepared: LLMPreparedAttemptV1,
        *,
        operation: object,
        stage: object,
        result: MutualLearningTurnResultV1,
        final: FinalReadyTurn | None,
        usage: object,
    ) -> object | None:
        if self.defer_publication:
            # The accepted stage has already been made durable.  Playback
            # owns the final DebateTurn/Evidence/usage CAS in its Session.
            return None
        method = _method(self.publication, "commit_turn_success", "publish_atomic", "publish")
        if method is not None:
            try:
                _invoke(
                    method,
                    operation_id=prepared.operation_id,
                    turn_id=prepared.turn_id,
                    debate_id=prepared.debate_id,
                    operation=operation,
                    stage=stage,
                    usage=usage,
                    result=result,
                    final_ready=final,
                    evidence_trace=(final.evidence_trace if final is not None else ()),
                    request_hash=prepared.request_hash,
                )
            except Exception as exc:
                raise LLMRuntimeError(code="llm_publication_failed") from exc
        if prepared.operation_id is not None and _operation_state(operation) != "succeeded":
            return self._transition(prepared.operation_id, "mark_succeeded")
        return operation

    def resume_accepted_stage(
        self,
        stage: object,
        result: MutualLearningTurnResultV1,
        *,
        context: GenerationContext | None = None,
        receipts: Sequence[object] = (),
        queries: Sequence[object] = (),
        validator: MutualLearningValidator | None = None,
        recovery_input: LLMRecoveryInputV1 | None = None,
    ) -> LLMRunOutcomeV1:
        """Validate and publish a durable accepted stage without transport."""

        operation_id = _operation_id(stage)
        if operation_id is None:
            return LLMRunOutcomeV1("failed", stage=stage, safe_error_code="llm_stage_invalid")
        getter = _method(self.ledger, "get")
        operation = _invoke(getter, operation_id) if getter is not None else None
        if _operation_state(operation) not in {"accepted", "succeeded"}:
            return LLMRunOutcomeV1(
                "failed",
                operation=operation,
                stage=stage,
                safe_error_code="llm_stage_unavailable",
            )
        final: FinalReadyTurn | None = None
        try:
            if context is not None:
                checked = (validator or MutualLearningValidator()).validate(
                    result,
                    plan=context.turn,
                    participant=context.participant,
                    participants=context.participants,
                    receipts=cast(Sequence[SnapshotRetrievalReceipt], receipts),
                    predecessors=context.predecessors,
                    pending_question=context.effective_pending_question,
                )
                prepared = LLMPreparedAttemptV1(
                    prompt=cast(ProviderPromptV1, object()),
                    request=object(),
                    operation=operation,
                    request_hash=str(_read(stage, "request_hash", "")),
                    debate_id=context.debate_id,
                    turn_id=context.turn.turn_id,
                    scope_id=context.debate_id,
                    policy_hash=str(_read(stage, "policy_hash", "")),
                    manifest_hash=str(_read(stage, "export_manifest_hash", "")),
                    confirmation_revision=1,
                    fence=LLMGenerationFenceV1(
                        predecessor_turn_ids=tuple(item.turn_id for item in context.predecessors),
                        transcript_hash=str(_read(stage, "transcript_hash", "")),
                        cutoff_turn_index=context.turn.turn_index - 1,
                    ),
                    budget=object(),
                    price_card=object(),
                    attempt_no=_as_int(_read(stage, "attempt_no", 1), 1),
                    retrieval_reused=bool(_read(stage, "retrieval_reused", False)),
                    receipts=tuple(receipts),
                    queries=tuple(queries),
                    generation_fence_hash=str(_read(stage, "generation_fence", "")),
                )
                checked = self._attach_evidence_trace(
                    checked,
                    prepared=prepared,
                    context=context,
                )
                final = final_ready_turn(
                    checked,
                    turn_id=context.turn.turn_id,
                    participant_id=context.participant.participant_id,
                    snapshot_id=context.participant.snapshot_id,
                    round_no=context.turn.round_no,
                    turn_index=context.turn.turn_index,
                    predecessor_turn_ids=prepared.fence.predecessor_turn_ids,
                    cutoff_turn_index=prepared.fence.cutoff_turn_index,
                    transcript_hash=prepared.fence.transcript_hash,
                    attempt=prepared.attempt_no,
                )
                result = cast(MutualLearningTurnResultV1, checked.result)
            publication = _method(
                self.publication, "commit_turn_success", "publish_atomic", "publish"
            )
            if self.defer_publication:
                if final is None:
                    raise LLMRuntimeError(code="llm_recovery_context_missing")
                return LLMRunOutcomeV1(
                    "succeeded",
                    operation=operation,
                    stage=stage,
                    result=result,
                    final_ready=final,
                    deferred_publication=LLMDeferredPublicationV1(
                        operation_id=operation_id,
                        turn_id=str(_read(stage, "turn_id", "")),
                        debate_id=context.debate_id if context is not None else "",
                        request_hash=str(_read(stage, "request_hash", "")),
                        operation=operation,
                        stage=stage,
                        usage=stage,
                        result=result,
                        final_ready=final,
                        recovery_input=recovery_input,
                    ),
                )
            if publication is not None:
                _invoke(
                    publication,
                    operation_id=operation_id,
                    turn_id=str(_read(stage, "turn_id", "")),
                    operation=operation,
                    stage=stage,
                    usage=stage,
                    result=result,
                    final_ready=final,
                    evidence_trace=(final.evidence_trace if final is not None else ()),
                    request_hash=str(_read(stage, "request_hash", "")),
                )
            elif _operation_state(operation) != "succeeded":
                marker = _method(self.ledger, "mark_succeeded")
                if marker is None:
                    raise LLMRuntimeError(code="llm_publication_failed")
                operation = _invoke(marker, operation_id)
            return LLMRunOutcomeV1(
                "succeeded",
                operation=operation,
                stage=stage,
                result=result,
                final_ready=final,
            )
        except TurnValidationError as exc:
            return LLMRunOutcomeV1(
                "failed",
                operation=operation,
                stage=stage,
                safe_error_code=_safe_code(getattr(exc, "code", "rule_invalid"), "rule_invalid"),
            )
        except Exception:
            return LLMRunOutcomeV1(
                "failed",
                operation=operation,
                stage=stage,
                safe_error_code="llm_recovery_failed",
            )

    def generate_turn(self, prompt: ProviderPromptV1) -> MutualLearningTurnResultV1:
        """Provider-neutral direct adapter seam for existing Mock tests."""

        sender = _method(self.adapter, "generate_turn", "generate", "complete", "send")
        if sender is None:
            raise LLMRuntimeError(code="llm_adapter_unavailable")
        try:
            value = _invoke(sender, prompt)
            return self._map_result(value, prompt.request)
        except LLMRuntimeError:
            raise
        except Exception as exc:
            raise LLMRuntimeError(code="llm_output_invalid") from exc


LLMRuntime = LLMTurnRuntime
LLMGenerationRuntime = LLMTurnRuntime
LLMProviderAdapter = DashScopeLLMAdapter
OpenAICompatibleLLMAdapter = DashScopeLLMAdapter


__all__ = [
    "DashScopeLLMAdapter",
    "DashScopeLLMConfig",
    "LLMAcceptedStagePort",
    "LLMAcceptedStageV1",
    "LLMAtomicPublicationPort",
    "LLMDeferredPublicationPort",
    "LLMDeferredPublicationV1",
    "LLMAttemptTraceV1",
    "LLMConfirmationPort",
    "LLMGenerationFenceV1",
    "LLMGenerationRuntime",
    "LLMRuntime",
    "LLMRuntimeError",
    "LLMRuntimeLedgerPort",
    "LLMManifestPreparationPort",
    "LLMPreparedAttemptV1",
    "LLMRunOutcomeV1",
    "LLMProviderAdapter",
    "LLMTurnRuntime",
    "LLM_DEBATE_BUCKET",
    "LLM_DEBATE_OPERATION",
    "LLM_MAX_ATTEMPTS",
    "LLM_MODEL_KEY",
    "LLM_REGION",
    "LLM_CONNECT_TIMEOUT_SECONDS",
    "LLM_TOTAL_TIMEOUT_SECONDS",
    "LLMRequestV1",
    "LLMUsageV1",
    "LLMValidatedResultV1",
    "MappedLLMTurnV1",
    "OpenAICompatibleLLMAdapter",
]
