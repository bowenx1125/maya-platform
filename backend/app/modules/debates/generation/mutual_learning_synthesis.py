"""Deterministic public synthesis for completed mutual-learning turns."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from .types import (
    MutualLearningDisagreementV1,
    MutualLearningEvidenceConflictV1,
    MutualLearningPositionChangeV1,
    MutualLearningSynthesisV1,
    MutualLearningTurnResultV1,
)


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _structured(turn: object) -> MutualLearningTurnResultV1 | None:
    value = (
        turn.get("structured", turn)
        if isinstance(turn, Mapping)
        else getattr(turn, "structured", turn)
    )
    if isinstance(value, MutualLearningTurnResultV1):
        return value
    try:
        return MutualLearningTurnResultV1.model_validate(value)
    except Exception:
        return None


def _public(turn: object) -> bool:
    status = (
        turn.get("publication_status", "public")
        if isinstance(turn, Mapping)
        else getattr(turn, "publication_status", "public")
    )
    return status in {"public", "final_ready"}


def _field(turn: object, name: str, default: object = None) -> object:
    if isinstance(turn, Mapping):
        return turn.get(name, default)
    return getattr(turn, name, default)


def synthesize_mutual_learning(
    turns: Sequence[object],
    *,
    topic: str = "",
) -> MutualLearningSynthesisV1:
    """Derive a stable synthesis from final-integration public fields only.

    The function deliberately does not inspect ``ParticipantContext`` or any
    receipt text.  Evidence lineage is represented only by claim IDs already
    made public in a validated structured turn.
    """

    final_turns: list[tuple[object, MutualLearningTurnResultV1]] = []
    for turn in turns:
        if not _public(turn):
            continue
        value = _structured(turn)
        if value is None or _field(turn, "phase") not in {None, "final_integration"}:
            # Persisted FinalReadyTurn stores the phase on its plan rather than
            # directly on the turn.  A validated final result is recognized by
            # its final-only fields when this metadata is absent.
            if value is None or value.final_recommendation is None:
                continue
        if value is not None and value.final_recommendation is not None:
            final_turns.append((turn, value))
    if not final_turns:
        raise ValueError("mutual-learning synthesis requires final integration turns")

    consensus = _unique(claim for _, result in final_turns for claim in result.final_consensus)
    disagreements: list[MutualLearningDisagreementV1] = []
    disagreement_keys: set[tuple[str, str]] = set()
    for _, result in final_turns:
        for item in result.final_disagreements:
            disagreement_key = (item.category, item.summary)
            if disagreement_key not in disagreement_keys:
                disagreement_keys.add(disagreement_key)
                disagreements.append(item)

    position_changes: list[MutualLearningPositionChangeV1] = []
    position_keys: set[tuple[str, str]] = set()
    for turn, result in final_turns:
        change = (result.change_from_opening or "").strip()
        if not change:
            continue
        participant_id = str(_field(turn, "participant_id", ""))
        position_key = (participant_id, change)
        if position_key not in position_keys:
            position_keys.add(position_key)
            position_changes.append(
                MutualLearningPositionChangeV1(
                    participant_id=participant_id or "unknown", change=change
                )
            )

    evidence_conflicts: list[MutualLearningEvidenceConflictV1] = []
    evidence_keys: set[tuple[str, tuple[str, ...]]] = set()
    for item in disagreements:
        if item.category != "evidence_conflict":
            continue
        evidence_key = (item.summary, tuple(item.claim_ids))
        if evidence_key not in evidence_keys:
            evidence_keys.add(evidence_key)
            evidence_conflicts.append(
                MutualLearningEvidenceConflictV1(summary=item.summary, claim_ids=item.claim_ids)
            )

    uncertainty = _unique(
        uncertainty for _, result in final_turns for uncertainty in result.remaining_uncertainty
    )
    complementary = _unique(
        learned for _, result in final_turns for learned in result.learned_from_others
    )
    recommendations = _unique(result.final_recommendation or "" for _, result in final_turns)
    if len(recommendations) == 1:
        direct_answer = recommendations[0]
    else:
        # This is a transparent aggregation statement, not a majority vote or
        # a new factual claim.  It preserves each expert's recommendation.
        direct_answer = (
            "No single recommendation was forced; the final expert recommendations remain: "
            + "; ".join(recommendations)
        )
    if topic:
        # Keep the topic out of generated claims; it is only a deterministic
        # fallback context when an empty recommendation is ever encountered.
        direct_answer = direct_answer.strip()
    return MutualLearningSynthesisV1(
        direct_answer=direct_answer,
        consensus=consensus,
        complementary_views=complementary,
        remaining_disagreements=disagreements,
        position_changes=position_changes,
        evidence_conflicts=evidence_conflicts,
        remaining_uncertainty=uncertainty,
        recommended_next_steps=recommendations,
    )


def build_mutual_learning_synthesis(
    turns: Sequence[object],
    *,
    topic: str = "",
) -> MutualLearningSynthesisV1:
    return synthesize_mutual_learning(turns, topic=topic)


MutualLearningSynthesizer = synthesize_mutual_learning


__all__ = [
    "MutualLearningSynthesizer",
    "build_mutual_learning_synthesis",
    "synthesize_mutual_learning",
]
