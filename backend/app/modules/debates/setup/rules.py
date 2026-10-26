"""Deterministic versioned Debate plans and immutable rule snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.debates.generation.mutual_learning_policy import MutualLearningPolicy
from app.modules.debates.generation.policy import TurnPolicyError
from app.modules.debates.schemas import (
    RULE_SET_ID,
    RULE_SET_ID_MUTUAL_LEARNING,
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
    rule_set_id: str = RULE_SET_ID,
    teaching_protocol: str | None = None,
) -> tuple[TurnPlanEntry, ...]:
    """Adapt the mutual-learning plan to the persisted UUID turn DTOs.

    No model or provider decides anything here.  Every entry carries the
    complete planned predecessor index prefix for later generation CAS checks.
    """

    if rule_set_id == RULE_SET_ID_MUTUAL_LEARNING:
        participants = normalize_participant_ids(participant_ids)
        # The generation policy is the single owner of phase and barrier
        # semantics.  Setup only adapts its ordered entries to UUID DTOs.
        try:
            plan = MutualLearningPolicy().plan(
                [str(item) for item in participants],
                round_count=round_count,
                teaching_protocol=teaching_protocol,
            )
        except TurnPolicyError as exc:
            # Setup speaks RuleViolation so the router keeps returning a stable
            # business code instead of leaking a planner exception as a 500.
            raise RuleViolation(exc.code, str(exc)) from exc
        return tuple(
            TurnPlanEntry(
                participant_id=UUID(entry.participant_id),
                slot=entry.slot,  # type: ignore[arg-type]
                order_index=entry.order_index,
                round_no=entry.round_no,
                turn_index=entry.turn_index,
                predecessor_turn_indexes=tuple(range(len(entry.predecessor_ids))),
                question_type=("agent" if entry.next_participant_id is not None else "none"),
                question_target_participant_id=(
                    UUID(entry.next_participant_id)
                    if entry.next_participant_id is not None
                    else None
                ),
                phase=entry.phase,  # type: ignore[arg-type]
                is_final_round=entry.is_final_round,
            )
            for entry in plan
        )
    raise RuleViolation("rule_set_unavailable", "The Debate rule set is unavailable.")


# The concise alias is convenient for repositories and hidden migration tests.
plan_turns = build_turn_plan


def rule_snapshot(
    *,
    rule_set_id: Literal["ordered_multi_expert_mutual_learning_v1"] = RULE_SET_ID,
    round_count: int = 2,
) -> DebateRuleSnapshot:
    """Return a fresh immutable copy of the frozen Demo rule values."""

    if rule_set_id == RULE_SET_ID_MUTUAL_LEARNING:
        try:
            return DebateRuleSnapshot(
                rule_set_id=RULE_SET_ID_MUTUAL_LEARNING,
                retrieval_policy_id="mock_lexical_anchor_v2",
                round_count=round_count,
            )
        except ValueError as exc:
            raise RuleViolation("mutual_learning_round_count_invalid", str(exc)) from exc
    raise RuleViolation("rule_set_unavailable", "The Debate rule set is unavailable.")


def canonical_rule_snapshot_json(
    *,
    rule_set_id: Literal["ordered_multi_expert_mutual_learning_v1"] = RULE_SET_ID,
    round_count: int = 2,
    turn_protocol: Literal["segments_v2"] | None = "segments_v2",
    teaching_protocol: Literal["four_round_v1"] | None = None,
    frozen_teaching: Mapping[str, object] | None = None,
) -> str:
    """Serialize the rule snapshot deterministically for a Debate row."""

    payload = rule_snapshot(rule_set_id=rule_set_id, round_count=round_count).model_dump(
        mode="json"
    )
    payload.pop("turn_protocol", None)
    payload.pop("teaching_protocol", None)
    if turn_protocol is not None:
        if rule_set_id != RULE_SET_ID_MUTUAL_LEARNING:
            raise RuleViolation("rule_set_unavailable", "Segments require mutual learning.")
        payload["turn_protocol"] = turn_protocol
    if teaching_protocol is not None:
        if turn_protocol != "segments_v2" or round_count != 4:
            raise RuleViolation(
                "teaching_protocol_invalid", "Teaching requires four segment rounds."
            )
        payload["teaching_protocol"] = teaching_protocol
    if teaching_protocol is not None:
        from app.modules.debates.teaching_rules import freeze_teaching_rules

        payload.update(frozen_teaching if frozen_teaching is not None else freeze_teaching_rules())
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
    "RULE_SET_ID_MUTUAL_LEARNING",
    "SLOTS",
    "assert_plan_shape",
    "build_turn_plan",
    "canonical_rule_snapshot_json",
    "normalize_participant_ids",
    "plan_turns",
    "rule_snapshot",
]
