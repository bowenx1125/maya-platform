"""Legacy accounting estimates; no request, token or cost ceiling is enforced.

The output figures below size ledger reservations only. No model request sends
``max_tokens``/``max_completion_tokens``: DashScope then applies the model's own
maximum output (qwen3.8-max: 131,072 tokens), so a reply is never cut at 1,510.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

LLM_MODEL_KEY: Final = "qwen3.8-max-2026-09-02"
LLM_REGION: Final = "cn-beijing"
LLM_CURRENCY: Final = "CNY"
LLM_INPUT_TOKEN_CAP: Final = 32_000
LLM_REQUESTED_OUTPUT_TOKEN_CAP: Final = 1_500
LLM_RESERVED_OUTPUT_TOKEN_CAP: Final = 1_510
LLM_REQUEST_BYTES_CAP: Final = 96 * 1024
LLM_REQUEST_COST_CAP: Final = Decimal("0.15")
LLM_ATTEMPT_CAP: Final = 2
LLM_TURN_MAX_ATTEMPTS: Final = LLM_ATTEMPT_CAP
LLM_TURN_MAX_COST: Final = Decimal("0.30")
LLM_SMALL_DEBATE_MAX_ATTEMPTS: Final = 8
LLM_SMALL_DEBATE_MAX_COST: Final = Decimal("1.20")
LLM_FULL_DEBATE_MAX_ATTEMPTS: Final = 20
LLM_FULL_DEBATE_MAX_COST: Final = Decimal("3.00")
REAL_CORE_DEMO_AGENT_COUNT: Final = 2
REAL_CORE_DEMO_ROUND_COUNT: Final = 2
REAL_CORE_DEMO_LLM_MAX_REQUESTS: Final = 4
REAL_CORE_DEMO_LLM_MAX_COST: Final = Decimal("0.60")


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


def debate_budget_cap(agent_count: int, *, round_count: int = 2) -> LLMBudgetCapV1:
    """Return the worst-case cap for one Debate of this exact shape.

    One turn per Agent per round, at most ``LLM_ATTEMPT_CAP`` attempts each. The
    two frozen fixture values are reproduced exactly by this derivation, which
    is what ``test_debate_budget_cap_matches_the_frozen_fixtures`` pins.
    """

    for name, value, ceiling in (
        ("agent count", agent_count, 5),
        ("round count", round_count, 5),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not 2 <= value <= ceiling:
            raise LLMPriceCardError(f"{name} is invalid")
    turns = agent_count * round_count
    return LLMBudgetCapV1(turns * LLM_TURN_MAX_ATTEMPTS, LLM_TURN_MAX_COST * turns)


def real_core_demo_budget_cap(
    agent_count: int,
    *,
    round_count: int = REAL_CORE_DEMO_ROUND_COUNT,
) -> LLMBudgetCapV1:
    """Return the one-request-per-turn LLM cap for a fully real Demo.

    The one request per turn rule is intentionally separate from the general
    LLM-A repair budget so a production/recovery allowance cannot silently
    authorize an extra LLM request. That rule is unchanged; only the size now
    follows the Debate's own 2-5 Agent x 2-5 round shape. It used to be fixed
    at two Agents and two rounds, so a fully real Demo refused every other
    shape the product lets a teacher create - and blamed the provider policy
    when it did.
    """

    for name, value in (("agent count", agent_count), ("round count", round_count)):
        if isinstance(value, bool) or not isinstance(value, int) or not 2 <= value <= 5:
            raise LLMPriceCardError(f"{name} is invalid")
    turns = agent_count * round_count
    # Fund what the runtime is configured to attempt. This used to allow one
    # request per turn while the runtime allowed two, so the first turn that
    # needed a structure repair borrowed a later turn's allowance and the last
    # turn of the debate failed for want of budget - reliably, on every debate
    # long enough for a repair to occur. A budget that cannot pay for the
    # behaviour it governs is not a safety limit, it is a delayed failure.
    per_request_cost = REAL_CORE_DEMO_LLM_MAX_COST / REAL_CORE_DEMO_LLM_MAX_REQUESTS
    requests = turns * LLM_ATTEMPT_CAP
    return LLMBudgetCapV1(
        max_requests=requests,
        max_cost_cny=per_request_cost * requests,
    )


__all__ = [
    "LLM_ATTEMPT_CAP",
    "LLM_TURN_MAX_ATTEMPTS",
    "LLM_TURN_MAX_COST",
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
    "debate_budget_cap",
    "real_core_demo_budget_cap",
]
