"""Pure, immutable accounting helpers for W4-LLM-A.

The price card is server-side audit input.  It is intentionally independent of
SQL and of the HTTP adapter so a runtime worker can snapshot it before making
an attempt and persist its fields through its own repository port.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Final, cast

LLM_MODEL_KEY: Final = "qwen3.7-plus-2026-05-26"
LLM_REGION: Final = "cn-beijing"
LLM_CURRENCY: Final = "CNY"
LLM_INPUT_TOKEN_CAP: Final = 32_000
LLM_REQUESTED_OUTPUT_TOKEN_CAP: Final = 1_500
LLM_RESERVED_OUTPUT_TOKEN_CAP: Final = 1_510
LLM_REQUEST_BYTES_CAP: Final = 96 * 1024
LLM_REQUEST_COST_CAP: Final = Decimal("0.15")
LLM_ATTEMPT_CAP: Final = 2
LLM_SMALL_DEBATE_MAX_ATTEMPTS: Final = 8
LLM_SMALL_DEBATE_MAX_COST: Final = Decimal("1.20")
LLM_FULL_DEBATE_MAX_ATTEMPTS: Final = 20
LLM_FULL_DEBATE_MAX_COST: Final = Decimal("3.00")
REAL_CORE_DEMO_AGENT_COUNT: Final = 2
REAL_CORE_DEMO_ROUND_COUNT: Final = 2
REAL_CORE_DEMO_LLM_MAX_REQUESTS: Final = 4
REAL_CORE_DEMO_LLM_MAX_COST: Final = Decimal("0.60")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MICRO_CNY = Decimal("0.000001")


class LLMPriceCardError(ValueError):
    """A price card or accounting input is not contract-valid."""

    def __init__(self, message: str, *, code: str = "llm_price_card_invalid") -> None:
        super().__init__(message)
        self.code = code


def _decimal(value: Decimal | str | int | float, *, field_name: str) -> Decimal:
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise LLMPriceCardError(
            f"{field_name} is not a Decimal", code="price_card_invalid"
        ) from exc
    if not parsed.is_finite() or parsed < 0:
        raise LLMPriceCardError(
            f"{field_name} is not a non-negative Decimal", code="price_card_invalid"
        )
    return parsed


def ceil_cny(value: Decimal | str | int | float) -> Decimal:
    """Round a non-negative CNY amount upward to six decimal places."""

    parsed = _decimal(value, field_name="amount")
    return parsed.quantize(_MICRO_CNY, rounding=ROUND_CEILING)


@dataclass(frozen=True, slots=True)
class LLMPriceCardV1:
    """Immutable official-rate snapshot used by one or more attempts."""

    version: str = "llm-price-card-v1"
    model_key: str = LLM_MODEL_KEY
    region: str = LLM_REGION
    currency: str = LLM_CURRENCY
    input_price_per_million: Decimal | str = Decimal("0")
    cached_input_price_per_million: Decimal | str = Decimal("0")
    output_price_per_million: Decimal | str = Decimal("0")
    retrieved_at: str = ""
    source_content_sha256: str = "0" * 64

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise LLMPriceCardError("price-card version is required")
        if self.model_key != LLM_MODEL_KEY:
            raise LLMPriceCardError(
                "price-card model is not the fixed model", code="price_card_model_invalid"
            )
        if self.region != LLM_REGION:
            raise LLMPriceCardError(
                "price-card region is not Beijing", code="price_card_region_invalid"
            )
        if self.currency != LLM_CURRENCY:
            raise LLMPriceCardError(
                "price-card currency is not CNY", code="price_card_currency_invalid"
            )
        for name in (
            "input_price_per_million",
            "cached_input_price_per_million",
            "output_price_per_million",
        ):
            object.__setattr__(self, name, _decimal(getattr(self, name), field_name=name))
        if not isinstance(self.retrieved_at, str):
            raise LLMPriceCardError("price-card retrieval time is invalid")
        if not isinstance(self.source_content_sha256, str) or not _SHA256_RE.fullmatch(
            self.source_content_sha256
        ):
            raise LLMPriceCardError("price-card source hash is invalid")

    # Rate aliases make the ledger adapter independent of a naming choice.
    @property
    def input_rate(self) -> Decimal:
        return cast(Decimal, self.input_price_per_million)

    @property
    def cached_input_rate(self) -> Decimal:
        return cast(Decimal, self.cached_input_price_per_million)

    @property
    def output_rate(self) -> Decimal:
        return cast(Decimal, self.output_price_per_million)

    @property
    def source_hash(self) -> str:
        return self.source_content_sha256

    @property
    def reviewed(self) -> bool:
        """Whether this card can authorize a real provider request."""

        if not self.retrieved_at.strip() or set(self.source_content_sha256) == {"0"}:
            return False
        try:
            timestamp = datetime.fromisoformat(self.retrieved_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        return (
            timestamp.tzinfo is not None
            and self.input_rate > 0
            and self.output_rate > 0
            and self.cached_input_rate >= 0
        )

    def assert_reviewed(self) -> None:
        if not self.reviewed:
            raise LLMPriceCardError(
                "a reviewed non-zero price card is required for a real request",
                code="llm_price_card_unreviewed",
            )

    def canonical_dict(self) -> dict[str, str]:
        return {
            "version": self.version,
            "model_key": self.model_key,
            "region": self.region,
            "currency": self.currency,
            "input_price_per_million": format(self.input_rate, "f"),
            "cached_input_price_per_million": format(self.cached_input_rate, "f"),
            "output_price_per_million": format(self.output_rate, "f"),
            "retrieved_at": self.retrieved_at,
            "source_content_sha256": self.source_content_sha256,
        }

    def reservation_cost(
        self,
        *,
        input_cap: int = LLM_INPUT_TOKEN_CAP,
        output_cap: int = LLM_RESERVED_OUTPUT_TOKEN_CAP,
        request_cap: Decimal | str = LLM_REQUEST_COST_CAP,
    ) -> Decimal:
        """Compute and cap-check the conservative pre-send reservation."""

        return reservation_cost(
            input_cap=input_cap,
            output_cap=output_cap,
            input_rate=self.input_rate,
            cached_input_rate=self.cached_input_rate,
            output_rate=self.output_rate,
            request_cap=request_cap,
        )

    def actual_cost(
        self,
        *,
        prompt_tokens: int,
        cached_input_tokens: int = 0,
        completion_tokens: int,
    ) -> Decimal:
        return actual_cost(
            prompt_tokens=prompt_tokens,
            cached_input_tokens=cached_input_tokens,
            completion_tokens=completion_tokens,
            input_rate=self.input_rate,
            cached_input_rate=self.cached_input_rate,
            output_rate=self.output_rate,
        )


@dataclass(frozen=True, slots=True)
class LLMBudgetCapV1:
    """Closed debate-wide cap for the immutable ``llm_debate_turn`` bucket."""

    max_requests: int = LLM_FULL_DEBATE_MAX_ATTEMPTS
    max_cost_cny: Decimal | str = LLM_FULL_DEBATE_MAX_COST

    def __post_init__(self) -> None:
        if isinstance(self.max_requests, bool) or not isinstance(self.max_requests, int):
            raise LLMPriceCardError("budget request cap is invalid")
        if self.max_requests < 1:
            raise LLMPriceCardError("budget request cap is invalid")
        object.__setattr__(
            self, "max_cost_cny", _decimal(self.max_cost_cny, field_name="max_cost_cny")
        )

    @property
    def max_total_tokens(self) -> int:
        return self.max_requests * (LLM_INPUT_TOKEN_CAP + LLM_RESERVED_OUTPUT_TOKEN_CAP)


def reservation_cost(
    *,
    input_cap: int = LLM_INPUT_TOKEN_CAP,
    output_cap: int = LLM_RESERVED_OUTPUT_TOKEN_CAP,
    input_rate: Decimal | str | int | float,
    cached_input_rate: Decimal | str | int | float,
    output_rate: Decimal | str | int | float,
    request_cap: Decimal | str = LLM_REQUEST_COST_CAP,
) -> Decimal:
    """Return the upward-rounded worst-case reservation amount."""

    if (
        isinstance(input_cap, bool)
        or not isinstance(input_cap, int)
        or input_cap < 0
        or isinstance(output_cap, bool)
        or not isinstance(output_cap, int)
        or output_cap < 0
    ):
        raise LLMPriceCardError("reservation token cap is invalid")
    input_price = _decimal(input_rate, field_name="input rate")
    cached_price = _decimal(cached_input_rate, field_name="cached input rate")
    output_price = _decimal(output_rate, field_name="output rate")
    cap = _decimal(request_cap, field_name="request cost cap")
    amount = ceil_cny(
        (Decimal(input_cap) * max(input_price, cached_price) + Decimal(output_cap) * output_price)
        / Decimal(1_000_000)
    )
    if amount > cap:
        raise LLMPriceCardError(
            "the worst-case request cost exceeds the frozen request cap",
            code="llm_request_cost_exceeded",
        )
    return amount


def actual_cost(
    *,
    prompt_tokens: int,
    cached_input_tokens: int = 0,
    completion_tokens: int,
    input_rate: Decimal | str | int | float,
    cached_input_rate: Decimal | str | int | float,
    output_rate: Decimal | str | int | float,
) -> Decimal:
    """Compute the reconciled cost from validated supplier usage."""

    values = (prompt_tokens, cached_input_tokens, completion_tokens)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        raise LLMPriceCardError("actual usage counts are invalid", code="provider_usage_invalid")
    if cached_input_tokens > prompt_tokens:
        raise LLMPriceCardError("cached input exceeds prompt input", code="provider_usage_invalid")
    input_price = _decimal(input_rate, field_name="input rate")
    cached_price = _decimal(cached_input_rate, field_name="cached input rate")
    output_price = _decimal(output_rate, field_name="output rate")
    return ceil_cny(
        (
            Decimal(prompt_tokens - cached_input_tokens) * input_price
            + Decimal(cached_input_tokens) * cached_price
            + Decimal(completion_tokens) * output_price
        )
        / Decimal(1_000_000)
    )


def debate_budget_cap(agent_count: int, *, round_count: int = 2) -> LLMBudgetCapV1:
    """Return the frozen cap for a 2- or 5-Agent, two-round fixture."""

    if isinstance(agent_count, bool) or not isinstance(agent_count, int) or agent_count < 2:
        raise LLMPriceCardError("agent count is invalid")
    if round_count != 2:
        raise LLMPriceCardError("the LLM-A cap is frozen for two rounds")
    if agent_count == 2:
        return LLMBudgetCapV1(LLM_SMALL_DEBATE_MAX_ATTEMPTS, LLM_SMALL_DEBATE_MAX_COST)
    if agent_count == 5:
        return LLMBudgetCapV1(LLM_FULL_DEBATE_MAX_ATTEMPTS, LLM_FULL_DEBATE_MAX_COST)
    raise LLMPriceCardError("debate exceeds the LLM-A Agent cap")


def real_core_demo_budget_cap(
    agent_count: int,
    *,
    round_count: int = REAL_CORE_DEMO_ROUND_COUNT,
) -> LLMBudgetCapV1:
    """Return the one-shot four-turn LLM cap for the Real-Core Demo.

    The Demo fixes two Agents and two rounds.  Its one request per turn rule
    is intentionally separate from the general LLM-A repair budget so a
    production/recovery allowance cannot silently authorize a seventh LLM
    request.
    """

    if agent_count != REAL_CORE_DEMO_AGENT_COUNT or round_count != REAL_CORE_DEMO_ROUND_COUNT:
        raise LLMPriceCardError("Real-Core Demo LLM budget is fixed to two Agents and two rounds")
    return LLMBudgetCapV1(
        max_requests=REAL_CORE_DEMO_LLM_MAX_REQUESTS,
        max_cost_cny=REAL_CORE_DEMO_LLM_MAX_COST,
    )


# Common alternate names used by ledger/runtime callers.
ceil_6 = ceil_cny
reservation_cost_cny = reservation_cost
actual_cost_cny = actual_cost
PriceCardV1 = LLMPriceCardV1


__all__ = [
    "LLM_ATTEMPT_CAP",
    "LLM_CURRENCY",
    "LLM_FULL_DEBATE_MAX_ATTEMPTS",
    "LLM_FULL_DEBATE_MAX_COST",
    "LLM_INPUT_TOKEN_CAP",
    "LLM_MODEL_KEY",
    "LLM_REGION",
    "LLM_REQUESTED_OUTPUT_TOKEN_CAP",
    "LLM_REQUEST_BYTES_CAP",
    "LLM_REQUEST_COST_CAP",
    "LLM_RESERVED_OUTPUT_TOKEN_CAP",
    "LLM_SMALL_DEBATE_MAX_ATTEMPTS",
    "LLM_SMALL_DEBATE_MAX_COST",
    "REAL_CORE_DEMO_AGENT_COUNT",
    "REAL_CORE_DEMO_LLM_MAX_COST",
    "REAL_CORE_DEMO_LLM_MAX_REQUESTS",
    "REAL_CORE_DEMO_ROUND_COUNT",
    "LLMBudgetCapV1",
    "LLMPriceCardError",
    "LLMPriceCardV1",
    "PriceCardV1",
    "actual_cost",
    "actual_cost_cny",
    "ceil_6",
    "ceil_cny",
    "debate_budget_cap",
    "real_core_demo_budget_cap",
    "reservation_cost",
    "reservation_cost_cny",
]
