"""One-shot fixed DashScope provider boundary for Real report sections.

This module owns no report persistence and has no retry/recovery policy.  It
prepares the already-closed request from :mod:`real_prompt`, performs at most
one injected transport call, and maps a valid response to the existing closed
``ReportSectionOutput`` DTO.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Final, cast

from app.modules.reports.real_prompt import (
    REPORT_PROMPT_CONTRACT_VERSION,
    ReportWireRequest,
    build_report_request,
)
from app.modules.reports.real_schema import (
    REPORT_SECTION_SCHEMA,
    REPORT_SECTION_SCHEMA_HASH,
    ReportBoundaryError,
    ReportRequest,
    validate_report_sections,
)
from app.modules.reports.schemas import ReportSectionOutput
from app.providers.llm_adapter import DashScopeLLMConfig
from app.providers.llm_price_card import (
    LLM_INPUT_TOKEN_CAP,
    LLM_REQUEST_COST_CAP,
    LLM_RESERVED_OUTPUT_TOKEN_CAP,
    LLMPriceCardError,
    LLMPriceCardV1,
)
from app.providers.llm_transport import (
    HttpxLLMTransport,
    LLMAcceptanceUnknown,
    LLMTransport,
    LLMTransportError,
    LLMTransportNotSent,
)

REAL_REPORT_MODEL: Final = "qwen3.7-plus-2026-05-26"
REAL_REPORT_REGION: Final = "cn-beijing"
REAL_REPORT_SCHEMA_NAME: Final = "maya_real_report_sections_v1"
REAL_REPORT_OUTPUT_TOKEN_CAP: Final = LLM_RESERVED_OUTPUT_TOKEN_CAP
_EXPECTED_ENVELOPE_FIELDS: Final = frozenset({"object", "model", "choices", "usage"})
_EXPECTED_CHOICE_FIELDS: Final = frozenset({"index", "message", "finish_reason"})
_EXPECTED_MESSAGE_FIELDS: Final = frozenset(
    {"role", "content", "refusal", "reasoning_content", "tool_calls", "function_call"}
)
_EXPECTED_USAGE_FIELDS: Final = frozenset(
    {"prompt_tokens", "completion_tokens", "total_tokens", "prompt_tokens_details"}
)


class ReportProviderError(ReportBoundaryError):
    """A safe provider-boundary code that never contains response values."""


RealReportProviderError = ReportProviderError
RealReportAdapterError = ReportProviderError


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash_provider_request(prepared: ReportWireRequest, body: Mapping[str, object]) -> str:
    hash_input = {
        "prompt_contract_version": REPORT_PROMPT_CONTRACT_VERSION,
        "method": "POST",
        "endpoint": prepared.endpoint,
        "body": body,
        "input_hash": prepared.input_hash,
        "schema_hash": REPORT_SECTION_SCHEMA_HASH,
        "tokenizer_id": prepared.tokenizer_id,
        "tokenizer_asset_hash": prepared.tokenizer_asset_hash,
        "policy_hash": prepared.policy_hash,
    }
    return hashlib.sha256(_canonical(hash_input).encode("utf-8")).hexdigest()


def _provider_schema_body(prepared: ReportWireRequest) -> dict[str, object]:
    """Copy the prompt body and apply the Real-report schema name exactly."""

    try:
        body = cast(dict[str, object], json.loads(_canonical(prepared.body)))
        response_format = cast(dict[str, object], body["response_format"])
        schema_wrapper = cast(dict[str, object], response_format["json_schema"])
        schema_wrapper["name"] = REAL_REPORT_SCHEMA_NAME
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ReportProviderError("report_request_shape") from None
    if (
        schema_wrapper.get("strict") is not True
        or schema_wrapper.get("schema") != REPORT_SECTION_SCHEMA
    ):
        raise ReportProviderError("report_schema_invalid")
    if body.get("model") != REAL_REPORT_MODEL or body.get("enable_thinking") is not False:
        raise ReportProviderError("report_resource_invalid")
    return body


def _prepare_provider_request(
    value: ReportRequest | Mapping[str, object],
    *,
    config: DashScopeLLMConfig,
    tokenizer: object | None,
    price_card: LLMPriceCardV1 | None,
    policy_hash: str | None,
) -> ReportWireRequest:
    if tokenizer is None:
        raise ReportProviderError("report_tokenizer_required")
    if price_card is None:
        raise ReportProviderError("report_price_card_required")
    try:
        prepared = build_report_request(
            value,
            config=config,
            tokenizer=tokenizer,
            price_card=price_card,
            policy_hash=policy_hash,
        )
    except ReportBoundaryError as exc:
        raise ReportProviderError(exc.code) from None
    body = _provider_schema_body(prepared)
    return replace(prepared, body=body, request_hash=_hash_provider_request(prepared, body))


def _no_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _response_parts(response: object) -> tuple[int, object]:
    status = getattr(response, "status_code", None)
    json_method = getattr(response, "json", None)
    if isinstance(status, bool) or not isinstance(status, int) or not callable(json_method):
        raise ReportProviderError("report_response_shape")
    try:
        payload = cast(Any, json_method)()
    except Exception:
        raise ReportProviderError("report_response_json") from None
    return status, payload


def _usage(payload: Mapping[str, object]) -> tuple[int, int, int, int]:
    if set(payload) - _EXPECTED_USAGE_FIELDS:
        raise ReportProviderError("report_usage_shape")
    values: list[int] = []
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ReportProviderError("report_usage_invalid")
        values.append(value)
    details = payload.get("prompt_tokens_details")
    cached = 0
    if details is not None:
        if not isinstance(details, Mapping) or set(details) - {"cached_tokens"}:
            raise ReportProviderError("report_usage_shape")
        cached_value = details.get("cached_tokens")
        if (
            isinstance(cached_value, bool)
            or not isinstance(cached_value, int)
            or cached_value < 0
        ):
            raise ReportProviderError("report_usage_invalid")
        cached = cached_value
    prompt_tokens, completion_tokens, total_tokens = values
    if (
        total_tokens != prompt_tokens + completion_tokens
        or prompt_tokens > LLM_INPUT_TOKEN_CAP
        or completion_tokens > REAL_REPORT_OUTPUT_TOKEN_CAP
        or cached > prompt_tokens
    ):
        raise ReportProviderError("report_usage_overrun")
    return prompt_tokens, cached, completion_tokens, total_tokens


def _response_sections(
    payload: object,
    *,
    price_card: LLMPriceCardV1,
    prepared: ReportWireRequest,
) -> ReportSectionOutput:
    if not isinstance(payload, Mapping) or set(payload) != _EXPECTED_ENVELOPE_FIELDS:
        raise ReportProviderError("report_response_shape")
    if payload.get("object") != "chat.completion" or payload.get("model") != REAL_REPORT_MODEL:
        raise ReportProviderError("report_response_resource")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
        raise ReportProviderError("report_choices_shape")
    choice = choices[0]
    if set(choice) != _EXPECTED_CHOICE_FIELDS or choice.get("index") != 0:
        raise ReportProviderError("report_choice_shape")
    if choice.get("finish_reason") != "stop":
        raise ReportProviderError("report_finish_reason")
    message = choice.get("message")
    if not isinstance(message, Mapping) or set(message) - _EXPECTED_MESSAGE_FIELDS:
        raise ReportProviderError("report_message_shape")
    if message.get("role") != "assistant":
        raise ReportProviderError("report_message_role")
    for field in ("refusal", "reasoning_content", "tool_calls", "function_call"):
        if message.get(field) not in (None, "", [], {}):
            raise ReportProviderError("report_message_unsafe")
    content = message.get("content")
    if not isinstance(content, str) or not content:
        raise ReportProviderError("report_content_shape")
    usage_payload = payload.get("usage")
    if not isinstance(usage_payload, Mapping):
        raise ReportProviderError("report_usage_shape")
    prompt_tokens, cached_tokens, completion_tokens, _total_tokens = _usage(usage_payload)
    try:
        actual_cost = price_card.actual_cost(
            prompt_tokens=prompt_tokens,
            cached_input_tokens=cached_tokens,
            completion_tokens=completion_tokens,
        )
        if actual_cost > prepared.estimated_cost_cny or actual_cost > LLM_REQUEST_COST_CAP:
            raise ReportProviderError("report_cost_overrun")
    except LLMPriceCardError:
        raise ReportProviderError("report_usage_invalid") from None
    try:
        value = json.loads(
            content,
            object_pairs_hook=_no_duplicate_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ReportProviderError("report_content_json") from None
    try:
        return validate_report_sections(value)
    except ReportBoundaryError as exc:
        raise ReportProviderError(exc.code) from None


@dataclass(slots=True)
class RealReportProvider:
    """Fixed one-shot report provider with an injectable transport."""

    config: DashScopeLLMConfig
    transport: LLMTransport | None = None
    tokenizer: object | None = None
    price_card: LLMPriceCardV1 | None = None
    policy_hash: str | None = None

    def __post_init__(self) -> None:
        if self.transport is None:
            self.transport = HttpxLLMTransport()

    def build_request(
        self, value: ReportRequest | Mapping[str, object]
    ) -> ReportWireRequest:
        """Build and validate the exact request without network I/O."""

        if not isinstance(self.config, DashScopeLLMConfig):
            raise ReportProviderError("report_config_invalid")
        return _prepare_provider_request(
            value,
            config=self.config,
            tokenizer=self.tokenizer,
            price_card=self.price_card,
            policy_hash=self.policy_hash,
        )

    prepare = build_request
    prepare_request = build_request

    def execute(self, value: ReportRequest | Mapping[str, object]) -> ReportSectionOutput:
        """Make one transport call and return only validated report sections."""

        prepared = self.build_request(value)
        transport = self.transport
        if transport is None:  # pragma: no cover - guarded by __post_init__
            raise ReportProviderError("report_transport_missing")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        try:
            response = transport.post(
                prepared.endpoint,
                headers=headers,
                json=prepared.body,
                timeout=HttpxLLMTransport.timeout(),
            )
        except LLMTransportNotSent:
            raise ReportProviderError("report_transport_not_sent") from None
        except LLMAcceptanceUnknown:
            raise ReportProviderError("report_acceptance_unknown") from None
        except LLMTransportError:
            raise ReportProviderError("report_transport_unknown") from None
        except Exception:
            raise ReportProviderError("report_transport_unknown") from None
        status, payload = _response_parts(response)
        if status != 200:
            raise ReportProviderError("report_http_rejected")
        if self.price_card is None:  # pragma: no cover - build_request rejects first
            raise ReportProviderError("report_price_card_required")
        return _response_sections(payload, price_card=self.price_card, prepared=prepared)

    generate = execute
    complete = execute


DashScopeRealReportProvider = RealReportProvider
RealReportAdapter = RealReportProvider


def generate_report_sections(
    value: ReportRequest | Mapping[str, object],
    *,
    config: DashScopeLLMConfig,
    transport: LLMTransport | None = None,
    tokenizer: object | None = None,
    price_card: LLMPriceCardV1 | None = None,
    policy_hash: str | None = None,
) -> ReportSectionOutput:
    """Functional façade for the one-shot provider boundary."""

    return RealReportProvider(
        config=config,
        transport=transport,
        tokenizer=tokenizer,
        price_card=price_card,
        policy_hash=policy_hash,
    ).execute(value)


__all__ = [
    "DashScopeRealReportProvider",
    "REAL_REPORT_MODEL",
    "REAL_REPORT_OUTPUT_TOKEN_CAP",
    "REAL_REPORT_REGION",
    "REAL_REPORT_SCHEMA_NAME",
    "RealReportAdapter",
    "RealReportProvider",
    "RealReportProviderError",
    "ReportProviderError",
    "generate_report_sections",
]
