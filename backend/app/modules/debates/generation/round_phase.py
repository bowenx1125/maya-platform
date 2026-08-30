"""Round phase resolution for the versioned mutual-learning protocol.

The legacy Demo rule set intentionally keeps its two-round vocabulary.  This
module is the small, rule-set-specific resolver used by the new protocol.  It
does not own a maximum number of rounds; product code validates the bounded
Demo value before asking it to resolve a phase.
"""

from __future__ import annotations

from enum import StrEnum


class RoundPhase(StrEnum):
    """The three closed phases of a mutual-learning session."""

    OPENING = "opening"
    EXCHANGE = "exchange"
    FINAL_INTEGRATION = "final_integration"

    # Lower-case aliases make the wire vocabulary convenient for callers
    # while keeping the conventional upper-case enum members available to
    # Python code.  Enum aliases do not add a fourth phase.
    opening = OPENING
    exchange = EXCHANGE
    final_integration = FINAL_INTEGRATION


class RoundPhaseError(ValueError):
    """A round/phase input cannot describe a valid protocol state."""

    def __init__(self, message: str, *, code: str = "round_phase_invalid") -> None:
        super().__init__(message)
        self.code = code


def resolve_round_phase(round_no: int, is_final_round: bool) -> RoundPhase:
    """Resolve a phase from the explicit round number and final marker.

    The first round is always independent opening work.  Once the opening has
    completed, the explicit final marker chooses integration; every other
    positive round is an exchange.  In particular, this function does not
    infer a final phase from a particular round number.
    """

    if not isinstance(round_no, int) or isinstance(round_no, bool) or round_no < 1:
        raise RoundPhaseError("round_no must be a positive integer.", code="round_invalid")
    if not isinstance(is_final_round, bool):
        raise RoundPhaseError("is_final_round must be a boolean.", code="round_phase_invalid")
    if round_no == 1:
        if is_final_round:
            raise RoundPhaseError(
                "The opening round cannot be marked as final in a multi-round session.",
                code="round_phase_invalid",
            )
        return RoundPhase.OPENING
    if bool(is_final_round):
        return RoundPhase.FINAL_INTEGRATION
    return RoundPhase.EXCHANGE


def validate_round_count(round_count: int, *, minimum: int = 2, maximum: int = 5) -> int:
    """Validate the product-level bounded round count without changing semantics."""

    if (
        not isinstance(round_count, int)
        or isinstance(round_count, bool)
        or round_count < minimum
        or round_count > maximum
    ):
        raise RoundPhaseError(
            f"round_count must be between {minimum} and {maximum}.",
            code="mutual_learning_round_count_invalid",
        )
    return round_count


def phase_for_round(round_no: int, round_count: int) -> RoundPhase:
    """Resolve a configured plan's phase using its explicit final marker."""

    count = validate_round_count(round_count)
    if not isinstance(round_no, int) or isinstance(round_no, bool) or not 1 <= round_no <= count:
        raise RoundPhaseError("round_no is outside the configured plan.", code="round_invalid")
    return resolve_round_phase(round_no, round_no == count)


# Explicitly named alias for adapters that resolve a configured plan.  The
# two-argument resolver above remains the canonical protocol boundary.
resolve_round_phase_for_count = phase_for_round


# Friendly aliases used by adapters and tests without making the resolver's
# canonical name ambiguous.
resolve_phase = resolve_round_phase
resolve_configured_phase = phase_for_round


__all__ = [
    "RoundPhase",
    "RoundPhaseError",
    "phase_for_round",
    "resolve_configured_phase",
    "resolve_phase",
    "resolve_round_phase",
    "resolve_round_phase_for_count",
    "validate_round_count",
]
