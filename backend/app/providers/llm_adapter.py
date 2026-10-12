"""Fixed, injected-transport DashScope Chat adapter for W4-LLM-A.

This module deliberately stops at the provider boundary.  Durable operation
state, teacher confirmation and atomic publication belong to the runtime
worker and its repository port.  ``execute`` returns a hash/usage-rich result
that those layers can persist without importing an ORM model.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Literal, cast
from urllib.parse import urlsplit

import httpx

from app.modules.agents.persona import PersonaProviderViewV1, PersonaSpecV1
from app.modules.debates.generation.prompt_budget import (
    PromptBudgetError,
    PromptBudgetV1,
    preflight_prompt_budget,
)
from app.modules.debates.generation.prompt_request import (
    PromptMessageV1,
    ProviderPromptV1,
    build_provider_prompt_from_mutual_input,
)
from app.modules.debates.generation.types import (
    MutualLearningPromptInput,
    MutualLearningTurnResultV1,
)

if TYPE_CHECKING:
    from app.modules.debates.generation.segments import SegmentInputSnapshot, SegmentTurnResult

from .llm_output import (
    LLM_REPAIR_FEEDBACK_SCHEMA_HASH,
    LLM_TURN_OUTPUT_SCHEMA_HASH,
    LLMOutputError,
    MappedLLMTurnV1,
    RepairFeedbackV1,
    map_provider_output,
    parse_llm_output_json,
    provider_wire_output_schema,
    validate_llm_output,
)
from .llm_price_card import (
    LLM_INPUT_TOKEN_CAP,
    LLM_MODEL_KEY,
    LLM_REGION,
    LLM_REQUEST_BYTES_CAP,
    LLM_REQUESTED_OUTPUT_TOKEN_CAP,
    LLM_RESERVED_OUTPUT_TOKEN_CAP,
)
from .llm_privacy import (
    LLM_REPAIR_FEEDBACK_FIELD_CLASS,
    LLM_REPAIR_FEEDBACK_POLICY_HASH,
    LLM_REPAIR_FEEDBACK_POLICY_VERSION,
    LLMOutboundManifestV1,
    LLMOutboundPrivacyError,
    scan_llm_outbound_messages,
)
from .llm_tokenizer import (
    ConservativeLLMTokenizer,
    LLMTokenizerError,
    LLMTokenizerPort,
    tokenizer_asset_hash_valid,
)
from .llm_transport import (
    HttpxLLMTransport,
    LLMAcceptanceUnknown,
    LLMTransport,
    LLMTransportError,
    LLMTransportNotSent,
    LLMTransportResponse,
)

LLM_ENDPOINT_PATH: Final = "/compatible-mode/v1/chat/completions"
DEFAULT_DASHSCOPE_LLM_ENDPOINT_PATH: Final = LLM_ENDPOINT_PATH
LLM_PROVIDER_OPERATION: Final = "llm_debate_turn"
LLM_PROMPT_CONTRACT_VERSION: Final = "prompt_request_v1"
LLM_CONNECT_TIMEOUT: Final = 15.0
LLM_TOTAL_TIMEOUT: Final = 120.0
LLM_RESERVED_OUTPUT_TOKENS: Final = LLM_RESERVED_OUTPUT_TOKEN_CAP
REAL_LLM_MODEL: Final = LLM_MODEL_KEY
REAL_LLM_REGION: Final = LLM_REGION

AttemptAcceptance = Literal["not_sent", "accepted", "acceptance_unknown"]
AttemptStatus = Literal["succeeded", "failed", "not_sent", "acceptance_unknown"]
AttemptFailureKind = Literal[
    "none",
    "structure_invalid",
    "provider_rejected",
    "provider_terminal",
    "provider_usage_unknown",
    "provider_usage_overrun",
    "provider_cost_overrun",
    "transport_not_sent",
    "transport_unknown",
]


class LLMAdapterError(RuntimeError):
    """A pre-send adapter boundary failed with a safe code."""

    def __init__(
        self,
        message: str = "LLM adapter rejected the request",
        *,
        code: str = "llm_adapter_invalid",
    ) -> None:
        super().__init__(message)
        self.code = code


class LLMResponseError(LLMAdapterError):
    """The HTTP response was received but failed closed acceptance."""

    def __init__(
        self,
        message: str = "LLM provider response is invalid",
        *,
        code: str = "provider_response_invalid",
        json_pointers: Sequence[str] = (),
    ) -> None:
        super().__init__(message, code=code)
        self.json_pointers = tuple(json_pointers)


@dataclass(frozen=True, slots=True)
class DashScopeLLMConfig:
    """Fixed Beijing resource settings with the secret kept out of repr."""

    api_key: str = field(default="", repr=False)
    workspace_id: str = ""
    region: str = LLM_REGION
    model_key: str = ""
    endpoint: str | None = None
    policy_hash: str = ""
    repair_policy_hash: str = LLM_REPAIR_FEEDBACK_SCHEMA_HASH

    def __post_init__(self) -> None:
        if self.region != LLM_REGION:
            raise LLMAdapterError(code="llm_region_invalid")
        if not self.model_key:
            from app.core.config import configured_llm_model

            object.__setattr__(self, "model_key", configured_llm_model())
        model_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        if not isinstance(self.model_key, str) or any(
            char not in model_chars for char in self.model_key
        ):
            raise LLMAdapterError(code="llm_model_invalid")
        if (
            not isinstance(self.workspace_id, str)
            or not self.workspace_id
            or any(
                char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                for char in self.workspace_id
            )
        ):
            raise LLMAdapterError(code="llm_workspace_invalid")
        if self.endpoint is not None:
            self._validate_endpoint(self.endpoint)
        if self.repair_policy_hash != LLM_REPAIR_FEEDBACK_SCHEMA_HASH:
            raise LLMAdapterError(code="llm_repair_policy_stale")

    @staticmethod
    def _validate_endpoint(value: str) -> None:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise LLMAdapterError(code="llm_endpoint_invalid") from exc
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
        ):
            raise LLMAdapterError(code="llm_endpoint_invalid")

    @property
    def resolved_endpoint(self) -> str:
        expected_host = f"{self.workspace_id}.cn-beijing.maas.aliyuncs.com"
        value = self.endpoint or f"https://{expected_host}{LLM_ENDPOINT_PATH}"
        self._validate_endpoint(value)
        parsed = urlsplit(value)
        if parsed.hostname != expected_host or parsed.path != LLM_ENDPOINT_PATH:
            raise LLMAdapterError(code="llm_endpoint_invalid")
        return value

    @property
    def model(self) -> str:
        return self.model_key


@dataclass(frozen=True, slots=True)
class LLMRequestV1:
    """Exact provider request plus hash-only identity metadata."""

    endpoint: str
    method: Literal["POST"]
    body: Mapping[str, object]
    messages: tuple[PromptMessageV1, PromptMessageV1]
    prompt: ProviderPromptV1
    budget: PromptBudgetV1
    request_hash: str
    prompt_contract_version: str
    schema_hash: str
    tokenizer_id: str
    tokenizer_asset_hash: str
    rule_set_hash: str
    persona_spec_hash: str
    transcript_hash: str
    receipt_hash: str
    turn_id: str
    generation_fence: str
    policy_hash: str
    export_manifest_hash: str
    repair_policy_hash: str
    build_manifest_hash: str = ""
    outbound_field_classes: tuple[str, ...] = ()
    identity_tokens: tuple[str, ...] = ()
    attempt_no: int = 1
    retrieval_reused: bool = False

    @property
    def user_message(self) -> PromptMessageV1:
        return self.messages[1]

    @property
    def system_message(self) -> PromptMessageV1:
        return self.messages[0]

    @property
    def model_key(self) -> str:
        model = self.body.get("model")
        return model if isinstance(model, str) and model else LLM_MODEL_KEY

    @property
    def prompt_hash(self) -> str:
        return self.prompt.request.request_hash

    @property
    def output_schema_hash(self) -> str:
        return self.schema_hash


@dataclass(frozen=True, slots=True)
class LLMUsageV1:
    """Validated supplier usage used by the accepted-stage ledger."""

    prompt_tokens: int
    cached_input_tokens: int
    completion_tokens: int
    total_tokens: int

    @property
    def input_tokens(self) -> int:
        return self.prompt_tokens

    @property
    def output_tokens(self) -> int:
        return self.completion_tokens

    @property
    def cached_tokens(self) -> int:
        return self.cached_input_tokens


def _usage_dict(value: LLMUsageV1 | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "prompt_tokens": value.prompt_tokens,
        "completion_tokens": value.completion_tokens,
        "total_tokens": value.total_tokens,
        "prompt_tokens_details": {"cached_tokens": value.cached_input_tokens},
    }


def _content_hash(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LLMAcceptedCandidateV1:
    """Sanitized response stage, safe to persist before local mapping.

    A schema-valid candidate retains only the canonical provider object.  A
    malformed/terminal candidate retains a content digest and safe diagnostic
    metadata, never the rejected response text or supplier payload.
    """

    request: LLMRequestV1
    http_status: int
    finish_reason: str | None
    usage: LLMUsageV1 | None
    stage_json: str
    stage_hash: str
    content_hash: str | None = None
    provider_output: Mapping[str, object] | None = None
    provider_output_json: str | None = None
    provider_output_hash: str | None = None
    safe_error_code: str | None = None
    json_pointers: tuple[str, ...] = ()
    actual_cost_cny: Decimal | None = None
    estimated_cost_cny: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if hashlib.sha256(self.stage_json.encode("utf-8")).hexdigest() != self.stage_hash:
            raise LLMAdapterError(code="llm_stage_hash_invalid")
        if self.content_hash is not None and not isinstance(self.content_hash, str):
            raise LLMAdapterError(code="llm_stage_hash_invalid")
        if self.provider_output is None:
            if self.provider_output_json is not None or self.provider_output_hash is not None:
                raise LLMAdapterError(code="llm_stage_invalid")
        else:
            canonical = _canonical(self.provider_output)
            if canonical != self.provider_output_json:
                raise LLMAdapterError(code="llm_stage_invalid")
            if self.provider_output_hash != hashlib.sha256(canonical.encode("utf-8")).hexdigest():
                raise LLMAdapterError(code="llm_stage_hash_invalid")

    @property
    def output_hash(self) -> str:
        """Hash of the exact sanitized stage JSON persisted by the runtime."""

        return self.stage_hash

    @property
    def accepted_output_json(self) -> str | None:
        return self.provider_output_json

    @property
    def accepted_output_hash(self) -> str | None:
        return self.provider_output_hash

    @property
    def schema_valid(self) -> bool:
        return self.provider_output is not None

    @property
    def stage_record(self) -> dict[str, object]:
        try:
            value = json.loads(self.stage_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LLMAdapterError(code="llm_stage_invalid") from exc
        if not isinstance(value, dict):
            raise LLMAdapterError(code="llm_stage_invalid")
        return value

    @classmethod
    def from_staged_json(
        cls,
        request: LLMRequestV1,
        stage_json: str,
        *,
        stage_hash: str | None = None,
    ) -> LLMAcceptedCandidateV1:
        """Rehydrate a candidate for zero-network local validation."""

        if not isinstance(stage_json, str):
            raise LLMAdapterError(code="llm_stage_invalid")
        try:
            value = json.loads(
                stage_json,
                object_pairs_hook=_no_duplicate_pairs,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LLMAdapterError(code="llm_stage_invalid") from exc
        if not isinstance(value, dict) or _canonical(value) != stage_json:
            raise LLMAdapterError(code="llm_stage_invalid")
        resolved_hash = hashlib.sha256(stage_json.encode("utf-8")).hexdigest()
        if stage_hash is not None and stage_hash != resolved_hash:
            raise LLMAdapterError(code="llm_stage_hash_invalid")
        if value.get("stage_version") != "llm_accepted_stage_v1":
            raise LLMAdapterError(code="llm_stage_invalid")
        usage = _usage(value.get("usage"))
        status = value.get("status")
        finish = value.get("finish_reason")
        http_status = value.get("http_status")
        if isinstance(http_status, bool) or not isinstance(http_status, int):
            raise LLMAdapterError(code="llm_stage_invalid")
        if finish is not None and not isinstance(finish, str):
            raise LLMAdapterError(code="llm_stage_invalid")
        if status == "schema_valid":
            output = value.get("provider_output")
            if not isinstance(output, Mapping):
                raise LLMAdapterError(code="llm_stage_invalid")
            parsed = validate_llm_output(output)
            output_json = _canonical(parsed)
            return cls(
                request=request,
                http_status=http_status,
                finish_reason=finish,
                usage=usage,
                stage_json=stage_json,
                stage_hash=resolved_hash,
                content_hash=value.get("content_hash")
                if isinstance(value.get("content_hash"), str)
                else None,
                provider_output=parsed,
                provider_output_json=output_json,
                provider_output_hash=hashlib.sha256(output_json.encode("utf-8")).hexdigest(),
                estimated_cost_cny=Decimal(str(value.get("estimated_cost_cny", "0"))),
                actual_cost_cny=(
                    Decimal(str(value["actual_cost_cny"]))
                    if value.get("actual_cost_cny") is not None
                    else None
                ),
            )
        if status != "diagnostic":
            raise LLMAdapterError(code="llm_stage_invalid")
        safe_code = value.get("safe_error_code")
        pointers = value.get("json_pointers", [])
        content_hash = value.get("content_hash")
        if (
            not isinstance(safe_code, str)
            or not isinstance(pointers, list)
            or any(not isinstance(pointer, str) for pointer in pointers)
            or (content_hash is not None and not isinstance(content_hash, str))
        ):
            raise LLMAdapterError(code="llm_stage_invalid")
        return cls(
            request=request,
            http_status=http_status,
            finish_reason=finish,
            usage=usage,
            stage_json=stage_json,
            stage_hash=resolved_hash,
            content_hash=content_hash,
            safe_error_code=safe_code,
            json_pointers=tuple(pointers),
            estimated_cost_cny=Decimal(str(value.get("estimated_cost_cny", "0"))),
            actual_cost_cny=(
                Decimal(str(value["actual_cost_cny"]))
                if value.get("actual_cost_cny") is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class LLMValidatedResultV1:
    """ORM-free result for operation/accepted-stage persistence."""

    status: AttemptStatus
    acceptance: AttemptAcceptance
    failure_kind: AttemptFailureKind
    safe_error_code: str | None
    request: LLMRequestV1
    http_status: int | None = None
    finish_reason: str | None = None
    usage: LLMUsageV1 | None = None
    mapped: MappedLLMTurnV1 | None = None
    accepted_candidate: LLMAcceptedCandidateV1 | None = None
    json_pointers: tuple[str, ...] = ()
    estimated_cost_cny: Decimal = Decimal("0")
    actual_cost_cny: Decimal | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded" and self.mapped is not None

    @property
    def result(self) -> MutualLearningTurnResultV1 | None:
        return self.mapped.result if self.mapped is not None else None

    @property
    def validated(self) -> MutualLearningTurnResultV1 | None:
        return self.result

    @property
    def provider_output(self) -> Mapping[str, object] | None:
        if self.mapped is not None:
            return self.mapped.provider_output
        return (
            self.accepted_candidate.provider_output if self.accepted_candidate is not None else None
        )

    @property
    def provider_output_json(self) -> str | None:
        if self.mapped is not None:
            return self.mapped.provider_output_json
        return (
            self.accepted_candidate.provider_output_json
            if self.accepted_candidate is not None
            else None
        )

    @property
    def provider_output_hash(self) -> str | None:
        if self.mapped is not None:
            return self.mapped.provider_output_hash
        return (
            self.accepted_candidate.provider_output_hash
            if self.accepted_candidate is not None
            else None
        )

    @property
    def accepted_stage_json(self) -> str | None:
        return self.accepted_candidate.stage_json if self.accepted_candidate is not None else None

    @property
    def accepted_stage_hash(self) -> str | None:
        return self.accepted_candidate.stage_hash if self.accepted_candidate is not None else None

    @property
    def output_hash(self) -> str | None:
        """Hash of the exact staged JSON, even when mapping later fails."""

        return self.accepted_stage_hash

    @property
    def stage(self) -> LLMAcceptedCandidateV1 | None:
        return self.accepted_candidate

    @property
    def accepted_output_json(self) -> str | None:
        return self.provider_output_json

    @property
    def accepted_output_hash(self) -> str | None:
        return self.provider_output_hash

    @property
    def acceptance_state(self) -> AttemptAcceptance:
        return self.acceptance

    @property
    def transport_classification(self) -> AttemptAcceptance:
        return self.acceptance

    @property
    def failure(self) -> str | None:
        return self.safe_error_code

    @property
    def retry_allowed(self) -> bool:
        return (
            self.request.attempt_no == 1
            and self.acceptance in {"not_sent", "accepted"}
            and self.failure_kind in {"transport_not_sent", "structure_invalid"}
        )

    @property
    def retry_action(self) -> Literal["retry_transport", "retry_structure", "fail_closed"]:
        if self.retry_allowed and self.failure_kind == "transport_not_sent":
            return "retry_transport"
        if self.retry_allowed and self.failure_kind == "structure_invalid":
            return "retry_structure"
        return "fail_closed"

    @property
    def ledger_fields(self) -> dict[str, object]:
        """Safe values matching the accepted-stage/usage ledger contract."""

        request = self.request
        usage = self.usage
        return {
            "provider_operation": LLM_PROVIDER_OPERATION,
            "model_key": request.model_key,
            "prompt_contract_version": request.prompt_contract_version,
            "prompt_hash": request.prompt.request_hash,
            "request_hash": request.request_hash,
            "schema_hash": request.schema_hash,
            "tokenizer_id": request.tokenizer_id,
            "tokenizer_asset_hash": request.tokenizer_asset_hash,
            "rule_set_hash": request.rule_set_hash,
            "persona_spec_hash": request.persona_spec_hash,
            "transcript_hash": request.transcript_hash,
            "receipt_hash": request.receipt_hash,
            "turn_id": request.turn_id,
            "generation_fence": request.generation_fence,
            "policy_hash": request.policy_hash,
            "export_manifest_hash": request.export_manifest_hash,
            "repair_policy_hash": request.repair_policy_hash,
            "build_manifest_hash": request.build_manifest_hash,
            "attempt_no": request.attempt_no,
            "retrieval_reused": request.retrieval_reused,
            "provider_output_json": self.provider_output_json,
            "provider_output_hash": self.provider_output_hash,
            "accepted_stage_json": self.accepted_stage_json,
            "accepted_stage_hash": self.accepted_stage_hash,
            "output_hash": self.output_hash,
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "cached_input_tokens": usage.cached_input_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
            "total_tokens": usage.total_tokens if usage else None,
            "price_card_version": "unused",
            "input_price_per_million": "0",
            "cached_input_price_per_million": "0",
            "output_price_per_million": "0",
            "estimated_cost_cny": format(self.estimated_cost_cny, "f"),
            "actual_cost_cny": (
                format(self.actual_cost_cny, "f") if self.actual_cost_cny is not None else None
            ),
            "safe_error_code": self.safe_error_code,
            "acceptance": self.acceptance,
            "finish_reason": self.finish_reason,
        }


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise LLMAdapterError(code="llm_request_invalid") from exc


class _DuplicateKeyError(ValueError):
    pass


def _no_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError()
        result[key] = value
    return result


def _zero_or_hash(value: object) -> str:
    return str(value) if isinstance(value, str) else ""


def _request_user_payload(prompt: ProviderPromptV1) -> dict[str, object]:
    try:
        value = json.loads(prompt.user_message.content)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LLMAdapterError(code="llm_prompt_json_invalid") from exc
    if not isinstance(value, dict):
        raise LLMAdapterError(code="llm_prompt_json_invalid")
    feedback = value.get("repair_feedback")
    if feedback is not None:
        try:
            value["repair_feedback"] = RepairFeedbackV1.from_value(feedback).as_dict()
        except LLMOutputError as exc:
            raise LLMAdapterError(code="llm_repair_feedback_invalid") from exc
    return value


def _validate_attempt_authorization(
    manifest: LLMOutboundManifestV1,
    *,
    attempt_no: int,
    has_repair_feedback: bool,
    repair_policy_hash: str,
) -> None:
    """Enforce the manifest's closed attempt and repair contract pre-send.

    ``LLMOutboundManifestV1`` validates these invariants at construction, but
    manifests can also be reconstructed from durable rows or untrusted test
    doubles.  The adapter repeats the checks at the last pure boundary so a
    malformed/tampered manifest cannot authorize a network call.
    """

    if (
        isinstance(manifest.max_attempts, bool)
        or not isinstance(manifest.max_attempts, int)
        or manifest.max_attempts not in {1, 2}
        or not isinstance(manifest.field_classes, (tuple, list))
    ):
        raise LLMAdapterError(code="llm_manifest_invalid")
    if attempt_no > manifest.max_attempts:
        raise LLMAdapterError(code="llm_attempt_exceeds_manifest")

    if manifest.max_attempts == 2:
        if manifest.repair_policy_version != LLM_REPAIR_FEEDBACK_POLICY_VERSION:
            raise LLMAdapterError(code="llm_repair_policy_missing")
        if manifest.repair_policy_hash != LLM_REPAIR_FEEDBACK_POLICY_HASH:
            raise LLMAdapterError(code="llm_repair_policy_stale")
        if LLM_REPAIR_FEEDBACK_FIELD_CLASS not in manifest.field_classes:
            raise LLMAdapterError(code="llm_repair_field_missing")
        if repair_policy_hash != LLM_REPAIR_FEEDBACK_POLICY_HASH:
            raise LLMAdapterError(code="llm_repair_policy_stale")
    elif (
        manifest.repair_policy_version is not None
        or manifest.repair_policy_hash is not None
        or LLM_REPAIR_FEEDBACK_FIELD_CLASS in manifest.field_classes
    ):
        raise LLMAdapterError(code="llm_repair_policy_unexpected")

    if has_repair_feedback:
        if attempt_no <= 1:
            raise LLMAdapterError(code="llm_repair_feedback_unexpected")
        if not manifest.repair_feedback_allowed:
            raise LLMAdapterError(code="llm_repair_feedback_not_allowed")
        if repair_policy_hash != LLM_REPAIR_FEEDBACK_POLICY_HASH:
            raise LLMAdapterError(code="llm_repair_policy_stale")


def _make_result(
    request: LLMRequestV1,
    *,
    status: AttemptStatus,
    acceptance: AttemptAcceptance,
    failure_kind: AttemptFailureKind,
    safe_error_code: str | None,
    http_status: int | None = None,
    finish_reason: str | None = None,
    usage: LLMUsageV1 | None = None,
    mapped: MappedLLMTurnV1 | None = None,
    accepted_candidate: LLMAcceptedCandidateV1 | None = None,
    json_pointers: Sequence[str] = (),
    actual_cost_cny: Decimal | None = None,
) -> LLMValidatedResultV1:
    return LLMValidatedResultV1(
        status=status,
        acceptance=acceptance,
        failure_kind=failure_kind,
        safe_error_code=safe_error_code,
        request=request,
        http_status=http_status,
        finish_reason=finish_reason,
        usage=usage,
        mapped=mapped,
        accepted_candidate=accepted_candidate,
        json_pointers=tuple(json_pointers),
        actual_cost_cny=actual_cost_cny,
    )


def _response_parts(response: object) -> tuple[int, object]:
    if isinstance(response, LLMTransportResponse):
        return response.status_code, response.payload
    if isinstance(response, Mapping):
        return 200, response
    status = getattr(response, "status_code", None)
    json_method = getattr(response, "json", None)
    if isinstance(status, int) and callable(json_method):
        try:
            return status, json_method()
        except Exception as exc:
            raise LLMResponseError(code="provider_response_invalid") from exc
    raise LLMResponseError(code="provider_response_invalid")


def _usage(value: object) -> LLMUsageV1 | None:
    if not isinstance(value, Mapping):
        return None
    prompt_value = value.get("prompt_tokens")
    completion_value = value.get("completion_tokens")
    total_value = value.get("total_tokens")
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0
        for item in (prompt_value, completion_value, total_value)
    ):
        return None
    prompt = cast(int, prompt_value)
    completion = cast(int, completion_value)
    total = cast(int, total_value)
    details = value.get("prompt_tokens_details")
    cached = 0
    if details is not None:
        if not isinstance(details, Mapping):
            return None
        cached_value = details.get("cached_tokens")
        if isinstance(cached_value, bool) or not isinstance(cached_value, int) or cached_value < 0:
            return None
        cached = cached_value
    if total != prompt + completion or cached > prompt:
        return None
    return LLMUsageV1(
        prompt_tokens=prompt,
        cached_input_tokens=cached,
        completion_tokens=completion,
        total_tokens=total,
    )


def _has_nonempty(value: object) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


def _stage_candidate(
    request: LLMRequestV1,
    *,
    http_status: int,
    finish_reason: str | None,
    usage: LLMUsageV1 | None,
    content_hash: str | None = None,
    provider_output: Mapping[str, object] | None = None,
    safe_error_code: str | None = None,
    json_pointers: Sequence[str] = (),
    actual_cost_cny: Decimal | None = None,
) -> LLMAcceptedCandidateV1:
    """Create one canonical persisted stage with no rejected raw value."""

    pointers = tuple(sorted(set(str(pointer) for pointer in json_pointers)))[:12]
    if provider_output is not None:
        status = "schema_valid"
        output_json = _canonical(provider_output)
        stage_record: dict[str, object] = {
            "actual_cost_cny": (
                format(actual_cost_cny, "f") if actual_cost_cny is not None else None
            ),
            "content_hash": content_hash,
            "estimated_cost_cny": "0",
            "finish_reason": finish_reason,
            "http_status": http_status,
            "provider_output": json.loads(output_json),
            "stage_version": "llm_accepted_stage_v1",
            "status": status,
            "usage": _usage_dict(usage),
        }
        # ``None`` is omitted from the canonical stage to keep it compact and
        # to avoid presenting a null supplier value as persisted content.
        stage_record = {key: value for key, value in stage_record.items() if value is not None}
        stage_json = _canonical(stage_record)
        return LLMAcceptedCandidateV1(
            request=request,
            http_status=http_status,
            finish_reason=finish_reason,
            usage=usage,
            stage_json=stage_json,
            stage_hash=hashlib.sha256(stage_json.encode("utf-8")).hexdigest(),
            content_hash=content_hash,
            provider_output=provider_output,
            provider_output_json=output_json,
            provider_output_hash=hashlib.sha256(output_json.encode("utf-8")).hexdigest(),
            actual_cost_cny=actual_cost_cny,
            estimated_cost_cny=Decimal("0"),
        )
    stage_record = {
        "content_hash": content_hash,
        "estimated_cost_cny": "0",
        "finish_reason": finish_reason,
        "http_status": http_status,
        "json_pointers": list(pointers),
        "safe_error_code": safe_error_code or "provider_response_invalid",
        "stage_version": "llm_accepted_stage_v1",
        "status": "diagnostic",
        "usage": _usage_dict(usage),
    }
    stage_json = _canonical(stage_record)
    return LLMAcceptedCandidateV1(
        request=request,
        http_status=http_status,
        finish_reason=finish_reason,
        usage=usage,
        stage_json=stage_json,
        stage_hash=hashlib.sha256(stage_json.encode("utf-8")).hexdigest(),
        content_hash=content_hash,
        safe_error_code=safe_error_code or "provider_response_invalid",
        json_pointers=pointers,
        actual_cost_cny=actual_cost_cny,
        estimated_cost_cny=Decimal("0"),
    )


class DashScopeLLMAdapter:
    """Fixed qwen3.7-plus adapter using one explicitly injected transport."""

    key = "dashscope"
    provider = "dashscope"
    model_key = LLM_MODEL_KEY

    def __init__(
        self,
        config: DashScopeLLMConfig,
        transport: LLMTransport | None = None,
        *,
        tokenizer: LLMTokenizerPort | object | None = None,
        identity_tokens: Sequence[str] = (),
        outbound_manifest: LLMOutboundManifestV1 | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or HttpxLLMTransport()
        self.tokenizer = tokenizer if tokenizer is not None else ConservativeLLMTokenizer()
        self.identity_tokens = tuple(identity_tokens)
        self.outbound_manifest = outbound_manifest

    def _validate_tokenizer(self) -> None:
        # Demo V1 removed the supplier-tokenizer authorization gate.  The exact
        # ID and asset hash are still mandatory because both are persisted with
        # every request, so the ledger names the counter behind each estimate.
        tokenizer_id = getattr(self.tokenizer, "tokenizer_id", None)
        asset_hash = getattr(self.tokenizer, "asset_hash", None)
        if (
            not isinstance(tokenizer_id, str)
            or not tokenizer_id.strip()
            or not isinstance(asset_hash, str)
            or not asset_hash.strip()
        ):
            raise LLMAdapterError(code="llm_tokenizer_invalid")
        if not tokenizer_asset_hash_valid(asset_hash):
            raise LLMAdapterError(code="llm_tokenizer_invalid")

    def _tokenizer_identity(self) -> tuple[str, str]:
        tokenizer_id = getattr(self.tokenizer, "tokenizer_id", None)
        asset_hash = getattr(self.tokenizer, "asset_hash", None)
        if not isinstance(tokenizer_id, str) or not isinstance(asset_hash, str):
            raise LLMAdapterError(code="llm_tokenizer_invalid")
        return tokenizer_id, asset_hash

    def build_request(
        self,
        prompt: ProviderPromptV1,
        *,
        generation_fence: str = "",
        policy_hash: str | None = None,
        export_manifest_hash: str = "",
        repair_policy_hash: str | None = None,
        build_manifest_hash: str = "",
        attempt_no: int = 1,
        retrieval_reused: bool = False,
        identity_tokens: Sequence[str] | None = None,
        outbound_manifest: LLMOutboundManifestV1 | None = None,
    ) -> LLMRequestV1:
        """Build and scan the exact request without network I/O."""

        if not isinstance(prompt, ProviderPromptV1):
            raise LLMAdapterError(code="llm_prompt_invalid")
        if (
            isinstance(attempt_no, bool)
            or not isinstance(attempt_no, int)
            or attempt_no not in {1, 2}
        ):
            raise LLMAdapterError(code="llm_attempt_invalid")
        manifest = outbound_manifest or self.outbound_manifest
        if not isinstance(manifest, LLMOutboundManifestV1) or not manifest.field_classes:
            raise LLMAdapterError(code="llm_manifest_required")
        repair_feedback = prompt.request.repair_feedback
        resolved_repair_hash = (
            repair_policy_hash if repair_policy_hash is not None else self.config.repair_policy_hash
        )
        _validate_attempt_authorization(
            manifest,
            attempt_no=attempt_no,
            has_repair_feedback=repair_feedback is not None,
            repair_policy_hash=resolved_repair_hash,
        )
        self._validate_tokenizer()
        # Attempt two is also the proven-not-sent transport retry.  In that
        # case the caller deliberately supplies the unchanged base request;
        # structure repair supplies the optional closed feedback field.
        # Send the supplier-dialect projection.  ``LLM_TURN_OUTPUT_SCHEMA_HASH``
        # still identifies the frozen contract that validates the response.
        schema = provider_wire_output_schema()
        if not isinstance(schema, dict):  # defensive typing for the body below
            raise LLMAdapterError(code="llm_schema_invalid")
        payload = _request_user_payload(prompt)
        user = _canonical(payload)
        system = prompt.system_message.content
        messages = (
            PromptMessageV1(role="system", content=system),
            PromptMessageV1(role="user", content=user),
        )
        try:
            budget = preflight_prompt_budget(
                (system, user),
                request_bytes=len(user.encode("utf-8")),
                requested_output_tokens=LLM_REQUESTED_OUTPUT_TOKEN_CAP,
                input_token_limit=LLM_INPUT_TOKEN_CAP,
                request_bytes_limit=LLM_REQUEST_BYTES_CAP,
                output_token_limit=LLM_REQUESTED_OUTPUT_TOKEN_CAP,
                token_counter=self.tokenizer,
            )
        except (PromptBudgetError, LLMTokenizerError, ValueError) as exc:
            raise LLMAdapterError(code=getattr(exc, "code", "llm_budget_failed")) from exc
        field_classes = manifest.field_classes if manifest is not None else ()
        resolved_identity_tokens = tuple(
            self.identity_tokens if identity_tokens is None else identity_tokens
        )
        try:
            scan_llm_outbound_messages(
                messages,
                identity_tokens=resolved_identity_tokens,
                workspace_id=self.config.workspace_id,
                field_classes=field_classes,
            )
        except LLMOutboundPrivacyError as exc:
            raise LLMAdapterError(code=exc.code) from exc
        resolved_policy_hash = _zero_or_hash(
            policy_hash if policy_hash is not None else self.config.policy_hash
        )
        body: dict[str, object] = {
            "model": self.config.model_key,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "enable_thinking": False,
            "stream": False,
            "temperature": 0.2,
            "top_p": 0.8,
            "n": 1,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "maya_llm_turn_output_v1",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        endpoint = self.config.resolved_endpoint
        tokenizer_id, tokenizer_asset_hash = self._tokenizer_identity()
        hash_input = {
            "method": "POST",
            "endpoint": endpoint,
            "body": body,
            "prompt_contract_version": LLM_PROMPT_CONTRACT_VERSION,
            "schema_hash": LLM_TURN_OUTPUT_SCHEMA_HASH,
            "tokenizer_id": tokenizer_id,
            "tokenizer_asset_hash": tokenizer_asset_hash,
            "rule_set_hash": prompt.request.rule_set_hash,
            "persona_spec_hash": prompt.request.persona_spec_hash,
            "transcript_hash": prompt.request.transcript_hash,
            "receipt_hash": prompt.request.receipt_hash,
            "turn_id": prompt.request.turn_id,
            "generation_fence": generation_fence,
            "policy_hash": resolved_policy_hash,
            "export_manifest_hash": export_manifest_hash,
            "repair_policy_hash": resolved_repair_hash,
            "build_manifest_hash": build_manifest_hash,
        }
        request_hash = hashlib.sha256(_canonical(hash_input).encode("utf-8")).hexdigest()
        return LLMRequestV1(
            endpoint=endpoint,
            method="POST",
            body=body,
            messages=messages,
            prompt=prompt,
            budget=budget,
            request_hash=request_hash,
            prompt_contract_version=LLM_PROMPT_CONTRACT_VERSION,
            schema_hash=LLM_TURN_OUTPUT_SCHEMA_HASH,
            tokenizer_id=tokenizer_id,
            tokenizer_asset_hash=tokenizer_asset_hash,
            rule_set_hash=prompt.request.rule_set_hash,
            persona_spec_hash=prompt.request.persona_spec_hash,
            transcript_hash=prompt.request.transcript_hash,
            receipt_hash=prompt.request.receipt_hash,
            turn_id=prompt.request.turn_id,
            generation_fence=generation_fence,
            policy_hash=resolved_policy_hash,
            export_manifest_hash=export_manifest_hash,
            repair_policy_hash=resolved_repair_hash,
            build_manifest_hash=build_manifest_hash,
            outbound_field_classes=manifest.field_classes,
            identity_tokens=resolved_identity_tokens,
            attempt_no=attempt_no,
            retrieval_reused=retrieval_reused,
        )

    prepare = build_request
    prepare_request = build_request

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def send_accepted(self, request: LLMRequestV1) -> LLMAcceptedCandidateV1:
        """Send one prepared request and stage a sanitized accepted result.

        This method performs no catalog/ref mapping.  It raises only for
        transport outcomes whose acceptance cannot be represented as an HTTP
        candidate; every received HTTP response returns a persistable stage,
        including rejected/terminal/malformed responses.
        """

        if not isinstance(request, LLMRequestV1):
            raise LLMAdapterError(code="llm_request_invalid")
        try:
            scan_llm_outbound_messages(
                request.messages,
                identity_tokens=request.identity_tokens,
                workspace_id=self.config.workspace_id,
                field_classes=request.outbound_field_classes,
            )
        except LLMOutboundPrivacyError as exc:
            raise LLMAdapterError(code=exc.code) from exc
        try:
            response = self.transport.post(
                request.endpoint,
                headers=self._headers(),
                json=request.body,
                timeout=HttpxLLMTransport.timeout(),
            )
        except LLMTransportNotSent:
            raise
        except LLMAcceptanceUnknown:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise LLMTransportNotSent() from exc
        except (
            httpx.WriteError,
            httpx.WriteTimeout,
            httpx.ReadError,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
            httpx.TimeoutException,
            TimeoutError,
            ConnectionError,
            OSError,
            LLMTransportError,
        ) as exc:
            raise LLMAcceptanceUnknown() from exc
        except Exception as exc:
            raise LLMAcceptanceUnknown() from exc
        try:
            status_code, payload = _response_parts(response)
        except LLMResponseError:
            return _stage_candidate(
                request,
                http_status=0,
                finish_reason=None,
                usage=None,
                safe_error_code="provider_response_invalid",
            )
        return self._stage_response(request, status_code, payload)

    def _stage_response(
        self,
        request: LLMRequestV1,
        status_code: int,
        payload: object,
    ) -> LLMAcceptedCandidateV1:
        """Convert one received HTTP response to a safe accepted stage."""

        if status_code != 200:
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason=None,
                usage=_usage(payload.get("usage")) if isinstance(payload, Mapping) else None,
                safe_error_code="llm_http_rejected",
            )
        if not isinstance(payload, Mapping):
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason=None,
                usage=None,
                safe_error_code="provider_response_invalid",
            )
        if payload.get("object") != "chat.completion":
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason=None,
                usage=None,
                safe_error_code="provider_envelope_invalid",
            )
        if payload.get("model") != request.model_key:
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason=None,
                usage=_usage(payload.get("usage")),
                safe_error_code="provider_model_mismatch",
            )
        choices = payload.get("choices")
        if (
            not isinstance(choices, list)
            or len(choices) != 1
            or not isinstance(choices[0], Mapping)
        ):
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason=None,
                usage=_usage(payload.get("usage")),
                safe_error_code="provider_choices_invalid",
            )
        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        finish_text = finish_reason if isinstance(finish_reason, str) else None
        message = choice.get("message")
        if choice.get("index") != 0:
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason=finish_text,
                usage=_usage(payload.get("usage")),
                safe_error_code="provider_choice_index_invalid",
            )
        if not isinstance(message, Mapping) or message.get("role") != "assistant":
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason=finish_text,
                usage=_usage(payload.get("usage")),
                safe_error_code="provider_message_invalid",
            )
        content = message.get("content")
        content_hash = _content_hash(content) if isinstance(content, str) else None
        if _has_nonempty(message.get("refusal")):
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason=finish_text,
                usage=_usage(payload.get("usage")),
                content_hash=content_hash,
                safe_error_code="provider_refusal",
            )
        if _has_nonempty(message.get("reasoning_content")):
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason=finish_text,
                usage=_usage(payload.get("usage")),
                content_hash=content_hash,
                safe_error_code="provider_reasoning_content",
            )
        if _has_nonempty(message.get("tool_calls")):
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason=finish_text,
                usage=_usage(payload.get("usage")),
                content_hash=content_hash,
                safe_error_code="provider_tool_calls",
            )
        if _has_nonempty(message.get("function_call")):
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason=finish_text,
                usage=_usage(payload.get("usage")),
                content_hash=content_hash,
                safe_error_code="provider_function_call",
            )
        usage = _usage(payload.get("usage"))
        if usage is None:
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason=finish_text,
                usage=None,
                content_hash=content_hash,
                safe_error_code="provider_usage_unknown",
            )
        if finish_reason == "length":
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason="length",
                usage=usage,
                content_hash=content_hash,
                safe_error_code="output_truncated",
            )
        if finish_reason != "stop":
            safe_code = {
                "content_filter": "provider_content_filtered",
                "tool_calls": "provider_tool_calls",
                "function_call": "provider_function_call",
                None: "provider_finish_reason_missing",
            }.get(finish_reason, "provider_finish_reason_invalid")
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason=finish_text,
                usage=usage,
                content_hash=content_hash,
                safe_error_code=safe_code,
            )
        if not isinstance(content, str) or not content:
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason="stop",
                usage=usage,
                safe_error_code="provider_content_invalid",
            )
        try:
            parsed = parse_llm_output_json(content)
        except LLMOutputError as exc:
            return _stage_candidate(
                request,
                http_status=status_code,
                finish_reason="stop",
                usage=usage,
                content_hash=content_hash,
                safe_error_code=exc.code,
                json_pointers=exc.json_pointers,
            )
        return _stage_candidate(
            request,
            http_status=status_code,
            finish_reason="stop",
            usage=usage,
            content_hash=content_hash,
            provider_output=parsed,
        )

    def validate_accepted(
        self,
        candidate: LLMAcceptedCandidateV1,
        *,
        question_target_ids: Sequence[str] = (),
    ) -> MappedLLMTurnV1:
        """Map a previously staged schema-valid candidate locally."""

        if not isinstance(candidate, LLMAcceptedCandidateV1):
            raise LLMAdapterError(code="llm_stage_invalid")
        if candidate.provider_output is None:
            raise LLMOutputError(
                code=candidate.safe_error_code or "provider_response_invalid",
                json_pointers=candidate.json_pointers,
            )
        return map_provider_output(
            candidate.provider_output,
            candidate.request.prompt.request,
            question_target_ids=question_target_ids,
        )

    def execute(
        self,
        prompt: ProviderPromptV1,
        *,
        generation_fence: str = "",
        policy_hash: str | None = None,
        export_manifest_hash: str = "",
        repair_policy_hash: str | None = None,
        build_manifest_hash: str = "",
        attempt_no: int = 1,
        retrieval_reused: bool = False,
        identity_tokens: Sequence[str] | None = None,
        outbound_manifest: LLMOutboundManifestV1 | None = None,
        question_target_ids: Sequence[str] = (),
        stage_callback: Callable[[LLMAcceptedCandidateV1], object] | None = None,
    ) -> LLMValidatedResultV1:
        # The per-call identity token set is frozen into ``LLMRequestV1`` by
        # ``build_request``; no mutable adapter state is changed here.
        old_tokens: tuple[str, ...] | None = None
        try:
            request = self.build_request(
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
            try:
                candidate = self.send_accepted(request)
            except LLMTransportNotSent:
                return _make_result(
                    request,
                    status="not_sent",
                    acceptance="not_sent",
                    failure_kind="transport_not_sent",
                    safe_error_code="llm_transport_not_sent",
                )
            except LLMAcceptanceUnknown:
                return _make_result(
                    request,
                    status="acceptance_unknown",
                    acceptance="acceptance_unknown",
                    failure_kind="transport_unknown",
                    safe_error_code="llm_acceptance_unknown",
                )
            if stage_callback is not None:
                stage_callback(candidate)
            if candidate.provider_output is None:
                safe_code = candidate.safe_error_code or "provider_response_invalid"
                if safe_code in {"provider_usage_unknown"}:
                    failure_kind: AttemptFailureKind = "provider_usage_unknown"
                elif safe_code in {"provider_usage_overrun"}:
                    failure_kind = "provider_usage_overrun"
                elif safe_code in {"output_truncated", "json_invalid", "schema_invalid"}:
                    failure_kind = "structure_invalid"
                elif safe_code == "llm_http_rejected":
                    failure_kind = "provider_rejected"
                else:
                    failure_kind = "provider_terminal"
                return _make_result(
                    request,
                    status="failed",
                    acceptance="accepted",
                    failure_kind=failure_kind,
                    safe_error_code=safe_code,
                    http_status=candidate.http_status,
                    finish_reason=candidate.finish_reason,
                    usage=candidate.usage,
                    accepted_candidate=candidate,
                    json_pointers=candidate.json_pointers,
                    actual_cost_cny=candidate.actual_cost_cny,
                )
            try:
                mapped = self.validate_accepted(
                    candidate,
                    question_target_ids=question_target_ids,
                )
            except LLMOutputError as exc:
                return _make_result(
                    request,
                    status="failed",
                    acceptance="accepted",
                    failure_kind="structure_invalid",
                    safe_error_code=exc.code,
                    http_status=candidate.http_status,
                    finish_reason=candidate.finish_reason,
                    usage=candidate.usage,
                    accepted_candidate=candidate,
                    json_pointers=exc.json_pointers,
                    actual_cost_cny=candidate.actual_cost_cny,
                )
            return _make_result(
                request,
                status="succeeded",
                acceptance="accepted",
                failure_kind="none",
                safe_error_code=None,
                http_status=candidate.http_status,
                finish_reason=candidate.finish_reason,
                usage=candidate.usage,
                mapped=mapped,
                accepted_candidate=candidate,
                actual_cost_cny=candidate.actual_cost_cny,
            )
        finally:
            if old_tokens is not None:
                self.identity_tokens = old_tokens

    call = execute
    generate = execute

    def _failed_response(
        self,
        request: LLMRequestV1,
        status_code: int,
        safe_code: str,
        *,
        finish_reason: str | None = None,
        usage: LLMUsageV1 | None = None,
    ) -> LLMValidatedResultV1:
        result = _make_result(
            request,
            status="failed",
            acceptance="accepted",
            failure_kind=(
                "provider_usage_unknown"
                if safe_code == "provider_usage_unknown"
                else "provider_usage_overrun"
                if safe_code == "provider_usage_overrun"
                else "provider_terminal"
            ),
            safe_error_code=safe_code,
            http_status=status_code,
            finish_reason=finish_reason,
            usage=usage,
        )
        return result

    def _failed_response_with_card(
        self,
        request: LLMRequestV1,
        status_code: int,
        safe_code: str,
        *,
        finish_reason: str | None = None,
        usage: LLMUsageV1 | None = None,
    ) -> LLMValidatedResultV1:
        return _make_result(
            request,
            status="failed",
            acceptance="accepted",
            failure_kind="provider_terminal",
            safe_error_code=safe_code,
            http_status=status_code,
            finish_reason=finish_reason,
            usage=usage,
        )

    def generate_turn(
        self,
        prompt: MutualLearningPromptInput | ProviderPromptV1 | SegmentInputSnapshot,
    ) -> MutualLearningTurnResultV1 | SegmentTurnResult:
        """Protocol-compatible façade for the provider-neutral generation service."""

        from app.modules.debates.generation.segments import SegmentInputSnapshot

        if isinstance(prompt, SegmentInputSnapshot):
            return self.generate_segments(prompt)

        if isinstance(prompt, ProviderPromptV1):
            provider_prompt = prompt
        elif isinstance(prompt, MutualLearningPromptInput) and isinstance(
            prompt.participant.persona, (PersonaSpecV1, PersonaProviderViewV1)
        ):
            provider_prompt = build_provider_prompt_from_mutual_input(
                prompt,
                persona=prompt.participant.persona,
                token_counter=self.tokenizer,
            )
        else:
            from .llm import LLMProviderError

            raise LLMProviderError("llm_prompt_invalid")
        result = self.execute(provider_prompt)
        if result.succeeded and result.result is not None:
            return result.result
        # Import lazily to avoid a module cycle: ``llm.py`` re-exports this
        # adapter while its historical Mock error class remains authoritative.
        from .llm import LLMProviderError

        error = LLMProviderError(result.safe_error_code or "llm_generation_failed")
        error.acceptance_state = result.acceptance
        error.failure_kind = result.failure_kind
        cast(Any, error).adapter_result = result
        raise error

    def generate_segments(
        self,
        snapshot: SegmentInputSnapshot,
        *,
        repair_feedback: Mapping[str, object] | None = None,
    ) -> SegmentTurnResult:
        """Delegate explicit v2 output to the sibling segment adapter."""

        from app.providers.llm_segments import SegmentLLMAdapter

        adapter = SegmentLLMAdapter(
            self.config,
            self.transport,
            tokenizer=self.tokenizer,
            identity_tokens=self.identity_tokens,
            outbound_manifest=self.outbound_manifest,
        )
        return adapter.generate_segments(snapshot, repair_feedback=repair_feedback)


# Alternate names used by a runtime worker or tests.
DashScopeLLMProvider = DashScopeLLMAdapter
FixedDashScopeLLMAdapter = DashScopeLLMAdapter
LLMAdapter = DashScopeLLMAdapter
LLMRequest = LLMRequestV1
LLMUsage = LLMUsageV1
ValidatedLLMResult = LLMValidatedResultV1
LLMResponse = LLMTransportResponse


def classify_transport_error(error: object) -> AttemptAcceptance:
    """Classify injected transport failures without reading raw messages."""

    if isinstance(error, LLMTransportNotSent):
        return "not_sent"
    if isinstance(error, LLMAcceptanceUnknown):
        return "acceptance_unknown"
    return "acceptance_unknown"


def classify_transport(error: object) -> AttemptAcceptance:
    return classify_transport_error(error)


__all__ = [
    "AttemptAcceptance",
    "AttemptFailureKind",
    "AttemptStatus",
    "LLMAcceptedCandidateV1",
    "DashScopeLLMAdapter",
    "DashScopeLLMConfig",
    "DashScopeLLMProvider",
    "FixedDashScopeLLMAdapter",
    "LLMAdapter",
    "LLMAdapterError",
    "LLM_ENDPOINT_PATH",
    "LLM_PROVIDER_OPERATION",
    "DEFAULT_DASHSCOPE_LLM_ENDPOINT_PATH",
    "LLMRequest",
    "LLMRequestV1",
    "LLMResponse",
    "LLMResponseError",
    "LLM_REPAIR_FEEDBACK_SCHEMA_HASH",
    "LLM_TURN_OUTPUT_SCHEMA_HASH",
    "REAL_LLM_MODEL",
    "REAL_LLM_REGION",
    "LLMUsage",
    "LLMUsageV1",
    "LLMValidatedResultV1",
    "ValidatedLLMResult",
    "classify_transport",
    "classify_transport_error",
]
