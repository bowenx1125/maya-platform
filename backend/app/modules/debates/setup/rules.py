"""Deterministic ordered two-round Debate rule set."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.debates.schemas import (
    RULE_SET_ID,
    RULE_SET_ID_V1,
    RULE_SET_ID_V2,
    DebateRuleSnapshot,
    Slot,
    TurnPlanEntry,
)

type ParticipantId = UUID | str
SLOTS: tuple[Slot, ...] = ("A", "B", "C", "D", "E")


@dataclass(frozen=True)
class RuleViolation(ValueError):
    """Stable business reason raised by the rule planner."""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _as_uuid(value: ParticipantId) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise RuleViolation("participant_id_invalid", "Participant IDs must be UUIDs.") from exc


def normalize_participant_ids(participant_ids: Sequence[ParticipantId]) -> tuple[UUID, ...]:
    """Validate the 2-5 ordered, unique participant selection."""

    count = len(participant_ids)
    if count < 2 or count > 5:
        raise RuleViolation(
            "participant_count_invalid", "Choose between two and five participants."
        )
    normalized = tuple(_as_uuid(value) for value in participant_ids)
    if len(set(normalized)) != len(normalized):
        raise RuleViolation("participant_duplicate", "Each participant can be selected only once.")
    return normalized


def build_turn_plan(
    participant_ids: Sequence[ParticipantId],
    *,
    round_count: int = 2,
) -> tuple[TurnPlanEntry, ...]:
    """Build round-major turns with no model/provider decision points.

    Round one follows A..E.  Round two repeats the same order and assigns the
    next participant question, except the final overall turn, which asks the
    class a reflection question.  Every entry carries the complete planned
    predecessor index prefix for later generation CAS checks.
    """

    if round_count != 2:
        raise RuleViolation("demo_round_count_fixed", "The demo uses exactly two rounds.")
    participants = normalize_participant_ids(participant_ids)
    entries: list[TurnPlanEntry] = []
    participant_count = len(participants)
    for round_no in (1, 2):
        for order_index, participant_id in enumerate(participants):
            turn_index = (round_no - 1) * participant_count + order_index
            question_type = "none"
            question_target: UUID | None = None
            if round_no == 2:
                if turn_index == (participant_count * 2) - 1:
                    question_type = "audience_reflection"
                else:
                    question_type = "agent"
                    question_target = participants[(order_index + 1) % participant_count]
            entries.append(
                TurnPlanEntry(
                    participant_id=participant_id,
                    slot=SLOTS[order_index],
                    order_index=order_index,
                    round_no=round_no,
                    turn_index=turn_index,
                    predecessor_turn_indexes=tuple(range(turn_index)),
                    question_type=question_type,  # type: ignore[arg-type]
                    question_target_participant_id=question_target,
                )
            )
    return tuple(entries)


# The concise alias is convenient for repositories and hidden migration tests.
plan_turns = build_turn_plan


def rule_snapshot(
    *,
    rule_set_id: Literal[
        "ordered_multi_agent_rounds_demo_v1", "ordered_multi_agent_rounds_demo_v2"
    ] = RULE_SET_ID,
) -> DebateRuleSnapshot:
    """Return a fresh immutable copy of the frozen Demo rule values."""

    if rule_set_id == RULE_SET_ID_V1:
        return DebateRuleSnapshot(rule_set_id=RULE_SET_ID_V1, retrieval_policy_id=None)
    if rule_set_id == RULE_SET_ID_V2:
        return DebateRuleSnapshot()
    raise RuleViolation("rule_set_unavailable", "The Debate rule set is unavailable.")


def canonical_rule_snapshot_json(
    *,
    rule_set_id: Literal[
        "ordered_multi_agent_rounds_demo_v1", "ordered_multi_agent_rounds_demo_v2"
    ] = RULE_SET_ID,
) -> str:
    """Serialize the rule snapshot deterministically for a Debate row."""

    payload = rule_snapshot(rule_set_id=rule_set_id).model_dump(mode="json")
    if rule_set_id == RULE_SET_ID_V1:
        # Preserve the byte-shape of the historical v1 canonical snapshot;
        # the retrieval policy field did not exist when those rows were made.
        payload.pop("retrieval_policy_id", None)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )


def assert_plan_shape(
    entries: Sequence[TurnPlanEntry], participant_ids: Sequence[ParticipantId]
) -> None:
    """Check a plan is exactly the deterministic plan for its participant order."""

    expected = build_turn_plan(participant_ids)
    if tuple(entries) != expected:
        raise RuleViolation("turn_plan_invalid", "The Debate turn plan is not deterministic.")


__all__ = [
    "ParticipantId",
    "RuleViolation",
    "SLOTS",
    "assert_plan_shape",
    "build_turn_plan",
    "canonical_rule_snapshot_json",
    "normalize_participant_ids",
    "plan_turns",
    "rule_snapshot",
]
