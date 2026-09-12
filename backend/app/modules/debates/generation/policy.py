"""Versioned deterministic turn planning for the mutual-learning rule set."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from .types import ParticipantContext

RULE_SET_ID_MUTUAL_LEARNING = "ordered_multi_expert_mutual_learning_v1"
RULE_SET_ID = RULE_SET_ID_MUTUAL_LEARNING
SUPPORTED_RULE_SET_IDS = frozenset({RULE_SET_ID_MUTUAL_LEARNING})
MIN_PARTICIPANTS = 2
MAX_PARTICIPANTS = 5
SLOTS = ("A", "B", "C", "D", "E")


class TurnPolicyError(ValueError):
    """A deterministic rule-set input cannot be planned."""

    def __init__(self, message: str, *, code: str = "participant_count_invalid") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class TurnPlan:
    """One planned turn in the immutable order snapshot.

    ``turn_id`` is a stable plan identifier (``turn-0`` …) until the setup
    module replaces it with its persisted UUID.  ``predecessor_turn_ids`` is
    always the complete lower-index prefix, never merely the turns that a
    prompt happens to mention.
    """

    turn_id: str
    participant_id: str
    slot: str
    order_index: int
    round_no: int
    turn_index: int
    phase: str
    next_participant_id: str | None
    is_final: bool
    predecessor_ids: tuple[str, ...] = ()
    # Legacy plans expose a lower turn-index prefix.  Mutual-learning plans
    # set this marker and expose only turns from completed earlier rounds.
    barrier: str = "prefix"
    is_final_round: bool = False

    @property
    def predecessor_turn_ids(self) -> tuple[str, ...]:
        return self.predecessor_ids

    @property
    def is_round_two(self) -> bool:
        return self.round_no == 2

    def with_turn_id(self, turn_id: str) -> TurnPlan:
        """Return a persisted-ID view while retaining pure policy fields."""

        if not turn_id:
            raise ValueError("turn_id is required")
        return replace(self, turn_id=turn_id)


class TurnPolicy:
    """The single enabled rule set: ordered multi-expert mutual learning.

    The policy never asks an LLM to choose a speaker.  It takes the teacher's
    click order and delegates to the mutual-learning planner, which owns round
    rotation, stable question routing and the four-round teaching plan.
    """

    rule_set_id = RULE_SET_ID

    def __init__(self, *, rule_set_id: str = RULE_SET_ID) -> None:
        if rule_set_id not in SUPPORTED_RULE_SET_IDS:
            raise TurnPolicyError(
                "The Debate rule set is unavailable.", code="rule_set_unavailable"
            )
        self.rule_set_id = rule_set_id

    def plan(
        self,
        participants: Sequence[ParticipantContext | str],
        *,
        round_count: int,
        teaching_protocol: str | None = None,
    ) -> tuple[TurnPlan, ...]:
        from .mutual_learning_policy import MutualLearningPolicy

        return MutualLearningPolicy().plan(
            participants, round_count=round_count, teaching_protocol=teaching_protocol
        )

    def plan_with_ids(
        self,
        participants: Sequence[ParticipantContext | str],
        turn_ids: Sequence[str],
        *,
        round_count: int,
        teaching_protocol: str | None = None,
    ) -> tuple[TurnPlan, ...]:
        """Plan turns and replace stable placeholders with persisted IDs."""

        from .mutual_learning_policy import MutualLearningPolicy

        return MutualLearningPolicy().plan_with_ids(
            participants,
            turn_ids,
            round_count=round_count,
            teaching_protocol=teaching_protocol,
        )


def expected_prefix(plans: Sequence[TurnPlan], current: TurnPlan) -> tuple[TurnPlan, ...]:
    """Return and verify the full immutable lower-index planned prefix."""

    ordered = tuple(sorted(plans, key=lambda item: item.turn_index))
    if any(item.turn_index != index for index, item in enumerate(ordered)):
        raise TurnPolicyError("Turn plan indexes must be contiguous.")
    if current not in ordered:
        raise TurnPolicyError("Current turn is not in the plan.")
    prefix = tuple(item for item in ordered if item.turn_index < current.turn_index)
    if len(prefix) != current.turn_index:
        raise TurnPolicyError("Current turn predecessor prefix is incomplete.")
    return prefix


__all__ = [
    "MAX_PARTICIPANTS",
    "MIN_PARTICIPANTS",
    "RULE_SET_ID",
    "RULE_SET_ID_MUTUAL_LEARNING",
    "SLOTS",
    "TurnPlan",
    "TurnPolicy",
    "TurnPolicyError",
    "SUPPORTED_RULE_SET_IDS",
    "expected_prefix",
]
