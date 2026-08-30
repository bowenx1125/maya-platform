"""Versioned deterministic turn planning for the Demo debate rule set."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from .types import ParticipantContext

RULE_SET_ID_V1 = "ordered_multi_agent_rounds_demo_v1"
RULE_SET_ID_V2 = "ordered_multi_agent_rounds_demo_v2"
RULE_SET_ID_MUTUAL_LEARNING = "ordered_multi_expert_mutual_learning_v1"
# Generation callers stay v1-compatible unless the persisted Debate row is
# passed explicitly.  New draft creation uses v2 in the setup module.
RULE_SET_ID = RULE_SET_ID_V1
SUPPORTED_LEGACY_RULE_SET_IDS = frozenset({RULE_SET_ID_V1, RULE_SET_ID_V2})
SUPPORTED_RULE_SET_IDS = frozenset({*SUPPORTED_LEGACY_RULE_SET_IDS, RULE_SET_ID_MUTUAL_LEARNING})
ROUND_COUNT = 2
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
        if self.barrier == "round":
            return self.predecessor_ids
        return self.predecessor_ids or tuple(f"turn-{index}" for index in range(self.turn_index))

    @property
    def is_round_two(self) -> bool:
        return self.round_no == 2

    def with_turn_id(self, turn_id: str) -> TurnPlan:
        """Return a persisted-ID view while retaining pure policy fields."""

        if not turn_id:
            raise ValueError("turn_id is required")
        return replace(self, turn_id=turn_id)


class TurnPolicy:
    """The only Demo rule set enabled in Wave 2.

    The policy never asks an LLM to choose a speaker.  It takes the teacher's
    click order and emits one round-one pass followed by one round-two pass.
    """

    rule_set_id = RULE_SET_ID
    round_count = ROUND_COUNT

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
        round_count: int = ROUND_COUNT,
    ) -> tuple[TurnPlan, ...]:
        if self.rule_set_id == RULE_SET_ID_MUTUAL_LEARNING:
            from .mutual_learning_policy import MutualLearningPolicy

            return MutualLearningPolicy().plan(participants, round_count=round_count)
        normalized = self._normalize_participants(participants)
        if round_count != ROUND_COUNT:
            raise TurnPolicyError(
                "The Demo debate rule set has exactly two rounds.",
                code="demo_round_count_fixed",
            )
        if not MIN_PARTICIPANTS <= len(normalized) <= MAX_PARTICIPANTS:
            raise TurnPolicyError(
                "A Demo debate requires between two and five participants.",
                code="participant_count_invalid",
            )
        ids = [participant.participant_id for participant in normalized]
        if len(ids) != len(set(ids)):
            raise TurnPolicyError(
                "A participant may appear only once in the click order.",
                code="participant_duplicate",
            )

        plans: list[TurnPlan] = []
        count = len(normalized)
        for round_no in range(1, ROUND_COUNT + 1):
            phase = "opening" if round_no == 1 else "rebuttal"
            for order_index, participant in enumerate(normalized):
                turn_index = len(plans)
                next_id = (
                    normalized[order_index + 1].participant_id
                    if round_no == 2 and order_index + 1 < count
                    else None
                )
                plans.append(
                    TurnPlan(
                        turn_id=f"turn-{turn_index}",
                        participant_id=participant.participant_id,
                        slot=SLOTS[order_index],
                        order_index=order_index,
                        round_no=round_no,
                        turn_index=turn_index,
                        phase=phase,
                        next_participant_id=next_id,
                        is_final=round_no == ROUND_COUNT and order_index == count - 1,
                    )
                )
        return tuple(plans)

    def plan_with_ids(
        self,
        participants: Sequence[ParticipantContext | str],
        turn_ids: Sequence[str],
        *,
        round_count: int = ROUND_COUNT,
    ) -> tuple[TurnPlan, ...]:
        """Plan turns and replace stable placeholders with persisted IDs."""

        if self.rule_set_id == RULE_SET_ID_MUTUAL_LEARNING:
            from .mutual_learning_policy import MutualLearningPolicy

            return MutualLearningPolicy().plan_with_ids(
                participants, turn_ids, round_count=round_count
            )

        plans = self.plan(participants, round_count=round_count)
        if len(plans) != len(turn_ids) or any(not value for value in turn_ids):
            raise TurnPolicyError("The persisted turn ID list does not match the plan.")
        return tuple(
            replace(
                plan,
                turn_id=turn_ids[index],
                predecessor_ids=tuple(turn_ids[:index]),
            )
            for index, plan in enumerate(plans)
        )

    @staticmethod
    def _normalize_participants(
        participants: Sequence[ParticipantContext | str],
    ) -> tuple[ParticipantContext, ...]:
        output: list[ParticipantContext] = []
        for item in participants:
            if isinstance(item, ParticipantContext):
                output.append(item)
                continue
            if not isinstance(item, str) or not item:
                raise TurnPolicyError("Each participant needs a non-empty ID.")
            output.append(
                ParticipantContext(
                    participant_id=item,
                    agent_id=item,
                    agent_name=item,
                    slot="",
                    order_index=0,
                    snapshot_id=f"snapshot:{item}",
                )
            )
        return tuple(output)


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
    "ROUND_COUNT",
    "RULE_SET_ID",
    "RULE_SET_ID_V1",
    "RULE_SET_ID_V2",
    "RULE_SET_ID_MUTUAL_LEARNING",
    "SLOTS",
    "TurnPlan",
    "TurnPolicy",
    "TurnPolicyError",
    "SUPPORTED_LEGACY_RULE_SET_IDS",
    "SUPPORTED_RULE_SET_IDS",
    "expected_prefix",
]
