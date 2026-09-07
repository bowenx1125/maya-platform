"""Pure planning, visibility and question-queue rules for mutual learning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, cast

from .policy import MAX_PARTICIPANTS, MIN_PARTICIPANTS, SLOTS, TurnPlan, TurnPolicyError
from .round_phase import RoundPhase, phase_for_round, validate_round_count
from .types import FinalReadyTurn, ParticipantContext, PendingQuestion

MUTUAL_LEARNING_RULE_SET_ID = "ordered_multi_expert_mutual_learning_v1"
MUTUAL_RULE_SET_ID = MUTUAL_LEARNING_RULE_SET_ID
MUTUAL_LEARNING_MIN_ROUNDS = 2
MUTUAL_LEARNING_MAX_ROUNDS = 5


def _normalize_participants(
    participants: Sequence[ParticipantContext | str],
) -> tuple[ParticipantContext, ...]:
    result: list[ParticipantContext] = []
    for item in participants:
        if isinstance(item, ParticipantContext):
            result.append(item)
            continue
        if not isinstance(item, str) or not item:
            raise TurnPolicyError("Each participant needs a non-empty ID.")
        result.append(
            ParticipantContext(
                participant_id=item,
                agent_id=item,
                agent_name=item,
                slot="",
                order_index=0,
                snapshot_id=f"snapshot:{item}",
            )
        )
    return tuple(result)


class MutualLearningPolicy:
    """Plan frozen historical rounds or the explicitly marked four-stage lesson.

    Historical plans retain click order and earlier-round context. The teaching
    plan rotates speaking order while keeping identity and question routing
    stable, with independent opening turns and sequential discussion context.
    """

    rule_set_id = MUTUAL_LEARNING_RULE_SET_ID
    min_rounds = MUTUAL_LEARNING_MIN_ROUNDS
    max_rounds = MUTUAL_LEARNING_MAX_ROUNDS

    def __init__(self, *, rule_set_id: str = MUTUAL_LEARNING_RULE_SET_ID) -> None:
        if rule_set_id != MUTUAL_LEARNING_RULE_SET_ID:
            raise TurnPolicyError(
                "The mutual-learning rule set is unavailable.", code="rule_set_unavailable"
            )
        self.rule_set_id = rule_set_id

    @staticmethod
    def _round_count(round_count: int) -> int:
        try:
            return validate_round_count(
                round_count,
                minimum=MUTUAL_LEARNING_MIN_ROUNDS,
                maximum=MUTUAL_LEARNING_MAX_ROUNDS,
            )
        except ValueError as exc:
            raise TurnPolicyError(str(exc), code="mutual_learning_round_count_invalid") from exc

    def plan(
        self,
        participants: Sequence[ParticipantContext | str],
        *,
        round_count: int = MUTUAL_LEARNING_MIN_ROUNDS,
        teaching_protocol: str | None = None,
    ) -> tuple[TurnPlan, ...]:
        count_rounds = self._round_count(round_count)
        four_round = teaching_protocol == "four_round_v1"
        if teaching_protocol not in {None, "four_round_v1"} or (four_round and count_rounds != 4):
            raise TurnPolicyError("The teaching protocol requires exactly four rounds.")
        normalized = _normalize_participants(participants)
        if not MIN_PARTICIPANTS <= len(normalized) <= MAX_PARTICIPANTS:
            raise TurnPolicyError(
                "A mutual-learning debate requires between two and five participants.",
                code="participant_count_invalid",
            )
        ids = [item.participant_id for item in normalized]
        if len(ids) != len(set(ids)):
            raise TurnPolicyError(
                "A participant may appear only once in the click order.",
                code="participant_duplicate",
            )

        plans: list[TurnPlan] = []
        for round_no in range(1, count_rounds + 1):
            phase = phase_for_round(round_no, count_rounds)
            final_round = phase is RoundPhase.FINAL_INTEGRATION
            offset = (round_no - 1) % len(normalized) if four_round else 0
            speaking_order = tuple(range(offset, len(normalized))) + tuple(range(offset))
            for speaking_index, order_index in enumerate(speaking_order):
                participant = normalized[order_index]
                turn_index = len(plans)
                # Routing follows stable click-order identities, even when
                # generation order rotates. Everyone therefore receives one
                # discussion question before the response round begins.
                next_participant_id = (
                    normalized[(order_index + 1) % len(normalized)].participant_id
                    if phase is RoundPhase.EXCHANGE and (not four_round or round_no == 2)
                    else None
                )
                plans.append(
                    TurnPlan(
                        turn_id=f"turn-{turn_index}",
                        participant_id=participant.participant_id,
                        slot=(participant.slot or SLOTS[order_index]),
                        order_index=order_index,
                        round_no=round_no,
                        turn_index=turn_index,
                        phase=phase.value,
                        next_participant_id=next_participant_id,
                        is_final=(final_round and speaking_index == len(normalized) - 1),
                        # This is intentionally empty for opening turns and
                        # never falls back to a lower-index same-round prefix.
                        predecessor_ids=tuple(
                            f"turn-{index}"
                            for index in range(
                                turn_index
                                if four_round and round_no > 1
                                else (round_no - 1) * len(normalized)
                            )
                        ),
                        barrier="prefix" if four_round and round_no > 1 else "round",
                        is_final_round=final_round,
                    )
                )
        return tuple(plans)

    def plan_with_ids(
        self,
        participants: Sequence[ParticipantContext | str],
        turn_ids: Sequence[str],
        *,
        round_count: int = MUTUAL_LEARNING_MIN_ROUNDS,
        teaching_protocol: str | None = None,
    ) -> tuple[TurnPlan, ...]:
        plans = self.plan(
            participants, round_count=round_count, teaching_protocol=teaching_protocol
        )
        if len(plans) != len(turn_ids) or any(not value for value in turn_ids):
            raise TurnPolicyError("The persisted turn ID list does not match the plan.")
        return tuple(
            replace(
                plan,
                turn_id=turn_ids[index],
                predecessor_ids=tuple(turn_ids[: len(plan.predecessor_ids)]),
            )
            for index, plan in enumerate(plans)
        )


def _round_value(turn: object) -> int:
    raw_value = (
        turn.get("round_no") if isinstance(turn, Mapping) else getattr(turn, "round_no", None)
    )
    try:
        value = int(cast(Any, raw_value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise TurnPolicyError("A turn has no valid round number.", code="round_invalid") from exc
    return value


def visible_prior_round_turns(
    turns: Sequence[FinalReadyTurn | object],
    current: TurnPlan | object,
) -> tuple[FinalReadyTurn | object, ...]:
    """Return only final-ready/public turns from completed earlier rounds.

    Storage order and A-E order are irrelevant to this barrier.  Same-round
    and future turns are intentionally discarded from the returned context.
    """

    current_round = _round_value(current)
    visible = [
        turn
        for turn in turns
        if _round_value(turn) < current_round
        and _value(turn, "publication_status", "final_ready") in {"final_ready", "public"}
    ]
    return tuple(
        sorted(
            visible,
            key=lambda item: (
                _int_value(item, "turn_index"),
                str(_value(item, "turn_id", "")),
            ),
        )
    )


def visible_turn_ids(
    turns: Sequence[FinalReadyTurn | object],
    current: TurnPlan | object,
) -> tuple[str, ...]:
    return tuple(
        str(_value(turn, "turn_id", "")) for turn in visible_prior_round_turns(turns, current)
    )


def _value(item: object, name: str, default: object = None) -> object:
    """Read a field from either a DTO/object or a JSON-shaped mapping."""

    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _int_value(item: object, name: str, default: int = 0) -> int:
    """Coerce a JSON/object field for deterministic ordering."""

    try:
        return int(cast(Any, _value(item, name, default)))
    except (TypeError, ValueError):
        return default


def _question_from_turn(turn: object) -> PendingQuestion | None:
    structured = _value(turn, "structured")
    question = (
        structured.get("question")
        if isinstance(structured, Mapping)
        else _value(structured, "question")
    )
    question_type = (
        question.get("type") if isinstance(question, Mapping) else _value(question, "type")
    )
    if question is None or question_type != "agent":
        return None
    target = (
        question.get("target_participant_id")
        if isinstance(question, Mapping)
        else _value(question, "target_participant_id")
    )
    text = question.get("text") if isinstance(question, Mapping) else _value(question, "text")
    source_id = str(_value(turn, "turn_id", ""))
    source_participant = str(_value(turn, "participant_id", ""))
    if not target or not text or not source_id or not source_participant:
        return None
    return PendingQuestion(
        question_id=str(_value(turn, "question_id") or f"{source_id}:question"),
        source_turn_id=source_id,
        source_participant_id=source_participant,
        target_participant_id=str(target),
        text=str(text),
    )


def _answered_question_ids(turn: object) -> set[str]:
    structured = _value(turn, "structured")
    values = (
        structured.get("answered_question_ids")
        if isinstance(structured, Mapping)
        else _value(structured, "answered_question_ids")
    )
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
        return {str(value) for value in values if value}
    value = (
        structured.get("answered_question_id")
        if isinstance(structured, Mapping)
        else _value(structured, "answered_question_id")
    )
    return {str(value)} if value else set()


def pending_questions(
    turns: Sequence[FinalReadyTurn | object],
    *,
    target_participant_id: str,
    before_round: int | None = None,
) -> tuple[PendingQuestion, ...]:
    """Derive immutable unanswered questions for the next round's queue."""

    ordered = sorted(
        (
            turn
            for turn in turns
            if _value(turn, "publication_status", "final_ready") in {"final_ready", "public"}
            and (before_round is None or _round_value(turn) < before_round)
        ),
        key=lambda item: (
            _int_value(item, "round_no"),
            _int_value(item, "turn_index"),
            str(_value(item, "turn_id", "")),
        ),
    )
    questions = [
        question
        for question in (_question_from_turn(turn) for turn in ordered)
        if question is not None and question.target_participant_id == target_participant_id
    ]
    answered = {question_id for turn in ordered for question_id in _answered_question_ids(turn)}
    return tuple(question for question in questions if question.question_id not in answered)


def pending_question_for_turn(
    turns: Sequence[FinalReadyTurn | object],
    *,
    target_participant_id: str,
    current_round: int,
) -> PendingQuestion | None:
    """Choose the oldest unanswered question, at most one per turn."""

    values = pending_questions(
        turns,
        target_participant_id=target_participant_id,
        before_round=current_round,
    )
    return values[0] if values else None


def final_unresolved_questions(
    turns: Sequence[FinalReadyTurn | object],
    *,
    participant_ids: Sequence[str],
    final_round: int,
) -> tuple[PendingQuestion, ...]:
    """Return questions still unanswered at the final integration boundary."""

    values: list[PendingQuestion] = []
    for participant_id in participant_ids:
        values.extend(
            pending_questions(
                turns,
                target_participant_id=participant_id,
                before_round=final_round,
            )
        )
    unique: dict[str, PendingQuestion] = {item.question_id: item for item in values}
    return tuple(unique[item] for item in sorted(unique))


# Alternate names keep adapters readable while one implementation owns the
# barrier and queue semantics.
MutualLearningTurnPolicy = MutualLearningPolicy
prior_round_turns = visible_prior_round_turns
get_pending_question = pending_question_for_turn


__all__ = [
    "MUTUAL_LEARNING_MAX_ROUNDS",
    "MUTUAL_LEARNING_MIN_ROUNDS",
    "MUTUAL_LEARNING_RULE_SET_ID",
    "MUTUAL_RULE_SET_ID",
    "MutualLearningPolicy",
    "MutualLearningTurnPolicy",
    "final_unresolved_questions",
    "get_pending_question",
    "pending_question_for_turn",
    "pending_questions",
    "prior_round_turns",
    "visible_prior_round_turns",
    "visible_turn_ids",
]
