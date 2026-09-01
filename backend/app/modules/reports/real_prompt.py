"""Canonical two-message prompt builder for the fixed Real report provider."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from app.modules.debates.generation.prompt_budget import (
    PromptBudgetError,
    PromptBudgetV1,
    preflight_prompt_budget,
)
from app.providers.llm_adapter import DashScopeLLMConfig, LLMAdapterError
from app.providers.llm_price_card import (
    LLM_INPUT_TOKEN_CAP,
    LLM_REQUEST_BYTES_CAP,
    LLM_REQUEST_COST_CAP,
    LLM_REQUESTED_OUTPUT_TOKEN_CAP,
    LLM_RESERVED_OUTPUT_TOKEN_CAP,
    LLMPriceCardError,
    LLMPriceCardV1,
)
from app.providers.llm_tokenizer import (
    LLMTokenizerError,
    tokenizer_asset_hash_valid,
)

from .real_schema import (
    REPORT_SCHEMA_NAME,
    REPORT_SECTION_SCHEMA,
    REPORT_SECTION_SCHEMA_HASH,
    ReportBoundaryError,
    ReportRequest,
    validate_report_request,
)

REPORT_PROMPT_CONTRACT_VERSION: Final = "real_report_prompt_v1"
REPORT_REQUESTED_OUTPUT_TOKENS: Final = LLM_REQUESTED_OUTPUT_TOKEN_CAP
REPORT_REQUEST_COST_LIMIT: Final[Decimal] = LLM_REQUEST_COST_CAP
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

REPORT_SYSTEM_PROMPT: Final = (
    "You write Maya's civilization mutual-learning report sections. Return one JSON "
    "object with exactly the six requested string fields and no other fields. Write "
    "concise English prose only. Do not emit Markdown headings, citation tokens, "
    "evidence IDs, vote totals, winners, rankings, or provider/private details. "
    "The server will add headings, evidence citations, and aggregate counts later. "
    "Use only the public report material in the user message; do not infer identities "
    "or add sources."
)


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class ReportMessage:
    role: Literal["system", "user"]
    content: str


@dataclass(frozen=True, slots=True)
class ReportWireRequest:
    """Prepared request metadata; the API key is deliberately absent."""

    endpoint: str
    method: Literal["POST"]
    body: Mapping[str, object]
    messages: tuple[ReportMessage, ReportMessage]
    report: ReportRequest
    budget: PromptBudgetV1
    request_hash: str
    input_hash: str
    schema_hash: str
    tokenizer_id: str
    tokenizer_asset_hash: str
    policy_hash: str
    estimated_cost_cny: Decimal

    @property
    def user_message(self) -> ReportMessage:
        return self.messages[1]

    @property
    def system_message(self) -> ReportMessage:
        return self.messages[0]

    @property
    def prompt_hash(self) -> str:
        return self.request_hash


def _safe_policy_hash(value: str | None, config: DashScopeLLMConfig) -> str:
    resolved = config.policy_hash if value is None else value
    if resolved == "":
        return ""
    if not isinstance(resolved, str) or _HASH_RE.fullmatch(resolved) is None:
        raise ReportBoundaryError("report_policy_hash")
    return resolved


def _tokenizer_identity(tokenizer: object) -> tuple[str, str]:
    # Demo V1 removed the supplier-tokenizer authorization gate; the exact ID
    # and asset hash below stay mandatory so the Report request records them.
    tokenizer_id = getattr(tokenizer, "tokenizer_id", None)
    asset_hash = getattr(tokenizer, "asset_hash", None)
    if (
        not isinstance(tokenizer_id, str)
        or not tokenizer_id.strip()
        or not isinstance(asset_hash, str)
        or _HASH_RE.fullmatch(asset_hash) is None
        or not tokenizer_asset_hash_valid(asset_hash)
    ):
        raise ReportBoundaryError("report_tokenizer_invalid")
    return tokenizer_id, asset_hash


def build_report_request(
    value: ReportRequest | Mapping[str, object],
    *,
    config: DashScopeLLMConfig,
    tokenizer: object,
    price_card: LLMPriceCardV1,
    policy_hash: str | None = None,
) -> ReportWireRequest:
    """Build the exact report request without performing network I/O."""

    report = validate_report_request(value)
    if not isinstance(config, DashScopeLLMConfig):
        raise ReportBoundaryError("report_config_invalid")
    try:
        endpoint = config.resolved_endpoint
    except LLMAdapterError:
        raise ReportBoundaryError("report_endpoint_invalid") from None
    if config.model_key != "qwen3.7-plus-2026-05-26" or config.region != "cn-beijing":
        raise ReportBoundaryError("report_resource_invalid")
    tokenizer_id, tokenizer_asset_hash = _tokenizer_identity(tokenizer)
    if not isinstance(price_card, LLMPriceCardV1):
        raise ReportBoundaryError("report_price_card_invalid")
    try:
        price_card.assert_reviewed()
        estimated_cost = price_card.reservation_cost(
            input_cap=LLM_INPUT_TOKEN_CAP,
            output_cap=LLM_RESERVED_OUTPUT_TOKEN_CAP,
            request_cap=REPORT_REQUEST_COST_LIMIT,
        )
    except LLMPriceCardError as exc:
        raise ReportBoundaryError(getattr(exc, "code", "report_price_card_invalid")) from None
    resolved_policy_hash = _safe_policy_hash(policy_hash, config)
    user = report.canonical_json()
    system = REPORT_SYSTEM_PROMPT
    try:
        budget = preflight_prompt_budget(
            (system, user),
            request_bytes=len(user.encode("utf-8")),
            requested_output_tokens=REPORT_REQUESTED_OUTPUT_TOKENS,
            input_token_limit=LLM_INPUT_TOKEN_CAP,
            request_bytes_limit=LLM_REQUEST_BYTES_CAP,
            output_token_limit=REPORT_REQUESTED_OUTPUT_TOKENS,
            token_counter=tokenizer,
        )
    except (PromptBudgetError, LLMTokenizerError, ValueError) as exc:
        raise ReportBoundaryError(getattr(exc, "code", "report_budget_invalid")) from None

    schema = json.loads(_canonical(REPORT_SECTION_SCHEMA))
    body: dict[str, object] = {
        "model": "qwen3.7-plus-2026-05-26",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "enable_thinking": False,
        "stream": False,
        "temperature": 0.2,
        "top_p": 0.8,
        "max_completion_tokens": REPORT_REQUESTED_OUTPUT_TOKENS,
        "n": 1,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": REPORT_SCHEMA_NAME,
                "strict": True,
                "schema": schema,
            },
        },
    }
    hash_input = {
        "prompt_contract_version": REPORT_PROMPT_CONTRACT_VERSION,
        "method": "POST",
        "endpoint": endpoint,
        "body": body,
        "input_hash": report.input_hash(),
        "schema_hash": REPORT_SECTION_SCHEMA_HASH,
        "tokenizer_id": tokenizer_id,
        "tokenizer_asset_hash": tokenizer_asset_hash,
        "policy_hash": resolved_policy_hash,
        "price_card": price_card.canonical_dict(),
    }
    request_hash = hashlib.sha256(_canonical(hash_input).encode("utf-8")).hexdigest()
    messages = (
        ReportMessage(role="system", content=system),
        ReportMessage(role="user", content=user),
    )
    return ReportWireRequest(
        endpoint=endpoint,
        method="POST",
        body=body,
        messages=messages,
        report=report,
        budget=budget,
        request_hash=request_hash,
        input_hash=report.input_hash(),
        schema_hash=REPORT_SECTION_SCHEMA_HASH,
        tokenizer_id=tokenizer_id,
        tokenizer_asset_hash=tokenizer_asset_hash,
        policy_hash=resolved_policy_hash,
        estimated_cost_cny=estimated_cost,
    )


# Alternate names for the future report worker's prepare seam.
prepare_report_request = build_report_request
RealReportWireRequest = ReportWireRequest


__all__ = [
    "REPORT_PROMPT_CONTRACT_VERSION",
    "REPORT_REQUEST_COST_LIMIT",
    "REPORT_REQUESTED_OUTPUT_TOKENS",
    "REPORT_SYSTEM_PROMPT",
    "RealReportWireRequest",
    "ReportMessage",
    "ReportWireRequest",
    "build_report_request",
    "prepare_report_request",
]
