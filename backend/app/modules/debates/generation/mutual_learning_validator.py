"""Server-side validator for ordered multi-expert mutual learning turns."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast

from .mutual_learning_policy import pending_question_for_turn, visible_prior_round_turns
from .policy import TurnPlan
from .round_phase import RoundPhase, resolve_round_phase
from .types import (
    FinalReadyTurn,
    MutualLearningTurnResultV1,
    ParticipantContext,
    PendingQuestion,
    PublicSource,
    SnapshotRetrievalReceipt,
    TurnValidationError,
    ValidatedTurn,
)
from .validator import (
    _contains_semantic_text,
    assert_speech_language,
    count_turn_words,
    has_direct_vote_solicitation,
    has_explicit_source_claim,
    truncate_complete_sentences,
)


@dataclass(frozen=True, slots=True)
class MutualLearningValidationResult:
    """Named result for callers that want to distinguish the new validator."""

    result: MutualLearningTurnResultV1
    retrieval_status: Literal["matched", "no_match"]
    grounding_mode: Literal["rag_grounded", "mixed", "general_reasoning"]
    used_receipts: tuple[SnapshotRetrievalReceipt, ...]
    public_sources: tuple[PublicSource, ...]
    word_count: int

    def as_validated_turn(self) -> ValidatedTurn:
        return ValidatedTurn(
            result=self.result,
            retrieval_status=self.retrieval_status,
            grounding_mode=self.grounding_mode,
            used_receipts=self.used_receipts,
            public_sources=self.public_sources,
            word_count=self.word_count,
        )


def _nonblank(value: str | None, label: str) -> None:
    if value is None or not value.strip():
        raise TurnValidationError(
            f"{label} is required for this turn.", json_pointers=(f"/{label}",)
        )


def _strings(values: Sequence[str], label: str) -> None:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise TurnValidationError(
            f"{label} must contain non-empty strings.", json_pointers=(f"/{label}",)
        )


_OPENING_OTHER_EVALUATION_RE = re.compile(
    r"\b(?:agent|expert)\s+[A-E]\b|\bother\s+(?:agent|expert)s?\b|\bconsensus\b",
    re.IGNORECASE,
)


def _visible_predecessors(
    predecessors: Sequence[FinalReadyTurn], plan: TurnPlan
) -> tuple[FinalReadyTurn, ...]:
    visible = tuple(
        cast(FinalReadyTurn, item) for item in visible_prior_round_turns(predecessors, plan)
    )
    expected_ids = tuple(plan.predecessor_turn_ids)
    actual_ids = tuple(item.turn_id for item in visible)
    if expected_ids != actual_ids:
        raise TurnValidationError(
            "The predecessor set does not match the round barrier.", json_pointers=("/engagements",)
        )
    for predecessor in visible:
        if predecessor.publication_status not in {"final_ready", "public"}:
            raise TurnValidationError(
                "A predecessor is not final-ready.", json_pointers=("/engagements",)
            )
    return visible


def _claim_ids(turn: FinalReadyTurn) -> set[str]:
    claims = getattr(turn.structured, "key_claims", ())
    return {
        str(getattr(claim, "claim_id", "")) for claim in claims if getattr(claim, "claim_id", "")
    }


def _all_evidence_ids(result: MutualLearningTurnResultV1) -> tuple[str, ...]:
    values: list[str] = list(result.used_evidence_id)
    for claim in result.key_claims:
        values.extend(claim.used_evidence_ids)
    return tuple(values)


def _validate_claims(
    result: MutualLearningTurnResultV1,
    receipts: Sequence[SnapshotRetrievalReceipt],
) -> tuple[SnapshotRetrievalReceipt, ...]:
    receipt_map = {item.resolved_evidence_id(): item for item in receipts}
    ids = _all_evidence_ids(result)
    if len(result.used_evidence_id) != len(set(result.used_evidence_id)):
        raise TurnValidationError(
            "Top-level evidence IDs must be unique.", json_pointers=("/key_claims",)
        )
    if any(
        len(claim.used_evidence_ids) != len(set(claim.used_evidence_ids))
        for claim in result.key_claims
    ):
        raise TurnValidationError(
            "Evidence IDs must be unique within each claim.", json_pointers=("/key_claims",)
        )
    unknown = [evidence_id for evidence_id in ids if evidence_id not in receipt_map]
    if unknown:
        raise TurnValidationError(
            "A mutual claim references a forged or cross-request receipt.",
            json_pointers=("/key_claims",),
        )
    if result.used_evidence_id:
        claim_ids = tuple(
            evidence_id for claim in result.key_claims for evidence_id in claim.used_evidence_ids
        )
        if tuple(result.used_evidence_id) != tuple(dict.fromkeys(claim_ids)):
            raise TurnValidationError(
                "Top-level evidence IDs do not match claim evidence lineage.",
                json_pointers=("/key_claims",),
            )
    for claim in result.key_claims:
        if claim.claim_type != "value_judgement" and has_explicit_source_claim(claim.claim_text):
            if not claim.used_evidence_ids:
                raise TurnValidationError(
                    "A concrete factual claim needs a current participant receipt.",
                    json_pointers=("/key_claims",),
                )
    return tuple(receipt_map[evidence_id] for evidence_id in dict.fromkeys(ids))


def _validate_engagements(
    result: MutualLearningTurnResultV1,
    *,
    visible: Sequence[FinalReadyTurn],
    participant: ParticipantContext,
) -> None:
    target_map = {turn.turn_id: turn for turn in visible}
    if not result.engagements:
        raise TurnValidationError(
            "Exchange and final turns must engage an earlier-round claim.",
            json_pointers=("/engagements",),
        )
    for engagement in result.engagements:
        target = target_map.get(engagement.target_turn_id)
        if target is None:
            raise TurnValidationError(
                "An engagement must target a visible prior-round turn.",
                json_pointers=("/engagements",),
            )
        if target.participant_id == participant.participant_id:
            raise TurnValidationError(
                "An engagement must target another expert.", json_pointers=("/engagements",)
            )
        if engagement.target_claim_id is not None and engagement.target_claim_id not in _claim_ids(
            target
        ):
            raise TurnValidationError(
                "An engagement targets a missing claim.", json_pointers=("/engagements",)
            )
        _nonblank(engagement.faithful_summary, "engagement.faithful_summary")
        _nonblank(engagement.response_summary, "engagement.response_summary")


def _validate_question(
    result: MutualLearningTurnResultV1,
    *,
    phase: RoundPhase,
    plan: TurnPlan,
    participant: ParticipantContext,
    participants: Sequence[ParticipantContext],
    pending_question: PendingQuestion | None,
) -> None:
    question = result.question
    answered = tuple(result.answered_question_ids)
    if len(answered) != len(set(answered)):
        raise TurnValidationError(
            "answered_question_ids must be unique.", json_pointers=("/answered_required_question",)
        )
    if phase is RoundPhase.OPENING:
        if (
            answered
            or question.type != "none"
            or question.target_participant_id is not None
            or question.text is not None
        ):
            raise TurnValidationError(
                "Opening turns cannot answer or ask a question.",
                json_pointers=("/answered_required_question", "/question"),
            )
        return
    if pending_question is None:
        if answered:
            raise TurnValidationError(
                "There is no pending question for this turn.",
                json_pointers=("/answered_required_question",),
            )
    elif answered != (pending_question.question_id,):
        raise TurnValidationError(
            "The assigned question must be answered exactly once.",
            json_pointers=("/answered_required_question",),
        )
    if phase is RoundPhase.FINAL_INTEGRATION:
        if (
            question.type != "none"
            or question.target_participant_id is not None
            or question.text is not None
        ):
            raise TurnValidationError(
                "Final integration turns cannot ask a question.", json_pointers=("/question",)
            )
        return
    if question.type != "agent":
        raise TurnValidationError(
            "An exchange turn must ask exactly one other expert a question.",
            json_pointers=("/question",),
        )
    if (
        question.target_participant_id is None
        or question.target_participant_id == participant.participant_id
    ):
        raise TurnValidationError(
            "An exchange question needs another expert target.",
            json_pointers=("/question",),
        )
    if participants and question.target_participant_id not in {
        item.participant_id for item in participants
    }:
        raise TurnValidationError(
            "An exchange question targets an unknown expert.",
            json_pointers=("/question",),
        )
    _nonblank(question.text, "question.text")


class MutualLearningValidator:
    """Close the new DTO according to phase, barrier, evidence and queue rules."""

    def __init__(
        self,
        *,
        min_words: int = 80,
        max_words: int = 200,
        language: str = "en",
    ) -> None:
        self.language = language
        if language == "zh":
            from app.modules.debates.output_language import unit_bounds

            min_words, max_words = unit_bounds("zh", min_words, max_words)
        if min_words < 1 or max_words < min_words:
            raise ValueError("invalid turn word bounds")
        self.min_words = min_words
        self.max_words = max_words

    def validate(
        self,
        value: MutualLearningTurnResultV1 | dict[str, object],
        *,
        plan: TurnPlan,
        participant: ParticipantContext,
        participants: Sequence[ParticipantContext] = (),
        receipts: Sequence[SnapshotRetrievalReceipt] = (),
        predecessors: Sequence[FinalReadyTurn] = (),
        pending_question: PendingQuestion | None = None,
    ) -> ValidatedTurn:
        result = MutualLearningTurnResultV1.from_provider(value)
        if plan.barrier != "round":
            raise TurnValidationError("The mutual validator requires a round-barrier plan.")
        if plan.participant_id != participant.participant_id:
            raise TurnValidationError(
                "The turn plan and participant do not match.", json_pointers=("/phase",)
            )
        try:
            phase = resolve_round_phase(plan.round_no, plan.is_final_round)
        except ValueError as exc:
            raise TurnValidationError(
                "The mutual turn phase is invalid.", json_pointers=("/phase",)
            ) from exc
        if phase.value != plan.phase:
            raise TurnValidationError(
                "The turn phase does not match its explicit final marker.",
                json_pointers=("/phase",),
            )
        assert_speech_language(result.speech, self.language)
        if has_direct_vote_solicitation(result.speech):
            raise TurnValidationError(
                "Direct vote solicitation is not allowed.", json_pointers=("/speech",)
            )
        _nonblank(result.speech, "speech")
        _nonblank(result.position_summary, "position_summary")
        _strings(result.remaining_uncertainty, "remaining_uncertainty")
        visible = _visible_predecessors(predecessors, plan)
        expected_pending = pending_question
        derived_pending = pending_question_for_turn(
            visible,
            target_participant_id=participant.participant_id,
            current_round=plan.round_no,
        )
        if expected_pending is None:
            expected_pending = derived_pending
        elif derived_pending is None or expected_pending != derived_pending:
            raise TurnValidationError(
                "The assigned pending question is not the oldest unanswered prior-round question.",
                json_pointers=("/answered_required_question",),
            )
        typed_receipts = tuple(receipts)
        for receipt in typed_receipts:
            if receipt.snapshot_id != participant.snapshot_id:
                raise TurnValidationError(
                    "A receipt belongs to another participant snapshot.",
                    json_pointers=("/key_claims",),
                )
        used_receipts = _validate_claims(result, typed_receipts)
        question_text = result.question.text if result.question.type != "none" else None
        if question_text is not None and not _contains_semantic_text(result.speech, question_text):
            raise TurnValidationError(
                "The question text must appear in speech.",
                json_pointers=("/question", "/speech"),
            )

        if phase is RoundPhase.OPENING:
            if not 2 <= len(result.key_claims) <= 4:
                raise TurnValidationError(
                    "Opening turns require two to four key claims.", json_pointers=("/key_claims",)
                )
            if result.engagements or result.answered_question_ids or result.learned_from_others:
                raise TurnValidationError(
                    "Opening turns must remain independent.",
                    json_pointers=(
                        "/engagements",
                        "/answered_required_question",
                        "/learned_from_others",
                    ),
                )
            if _OPENING_OTHER_EVALUATION_RE.search(result.speech):
                raise TurnValidationError(
                    "Opening turns cannot evaluate or address another expert.",
                    json_pointers=("/speech",),
                )
            if result.position_update != "unchanged":
                raise TurnValidationError(
                    "Opening turns cannot update their position.",
                    json_pointers=("/position_update",),
                )
            _strings(result.missing_information, "missing_information")
            if not result.missing_information:
                raise TurnValidationError(
                    "Opening turns must state missing information.",
                    json_pointers=("/missing_information",),
                )
            if not result.remaining_uncertainty:
                raise TurnValidationError(
                    "Opening turns must state remaining uncertainty.",
                    json_pointers=("/remaining_uncertainty",),
                )
            if (
                result.change_from_opening is not None
                or result.final_consensus
                or result.final_disagreements
                or result.final_recommendation is not None
            ):
                raise TurnValidationError(
                    "Final-only fields are forbidden in opening.",
                    json_pointers=(
                        "/change_from_opening",
                        "/final_consensus",
                        "/final_disagreements",
                        "/final_recommendation",
                    ),
                )
        else:
            if not visible:
                raise TurnValidationError(
                    "Exchange and final turns need an earlier-round turn.",
                    json_pointers=("/engagements",),
                )
            if not result.key_claims:
                raise TurnValidationError(
                    "Mutual turns require at least one key claim.", json_pointers=("/key_claims",)
                )
            _validate_engagements(result, visible=visible, participant=participant)
            _validate_question(
                result,
                phase=phase,
                plan=plan,
                participant=participant,
                participants=participants,
                pending_question=expected_pending,
            )
            _nonblank(result.position_update_reason, "position_update_reason")
            if phase is RoundPhase.FINAL_INTEGRATION:
                if not result.learned_from_others:
                    raise TurnValidationError(
                        "Final integration must record learned_from_others.",
                        json_pointers=("/learned_from_others",),
                    )
                if not result.remaining_uncertainty:
                    raise TurnValidationError(
                        "Final integration must list remaining uncertainty.",
                        json_pointers=("/remaining_uncertainty",),
                    )
                _strings(result.learned_from_others, "learned_from_others")
                _nonblank(result.change_from_opening, "change_from_opening")
                _nonblank(result.final_recommendation, "final_recommendation")
                for disagreement in result.final_disagreements:
                    if disagreement.category not in {
                        "different_persona_or_framework",
                        "different_evidence",
                        "evidence_conflict",
                        "insufficient_information",
                        "value_tradeoff",
                    }:
                        raise TurnValidationError(
                            "Final disagreement category is invalid.",
                            json_pointers=("/final_disagreements",),
                        )
                if result.unresolved_question_ids and set(result.unresolved_question_ids) != set(
                    result.unresolved_questions
                ):
                    raise TurnValidationError(
                        "Unresolved question ID projections differ.",
                        json_pointers=("/unresolved_questions",),
                    )
            else:
                if (
                    phase is RoundPhase.EXCHANGE
                    and not result.remaining_uncertainty
                    and not result.unresolved_issue
                ):
                    raise TurnValidationError(
                        "Exchange turns must state remaining uncertainty or an unresolved issue.",
                        json_pointers=("/remaining_uncertainty", "/unresolved_issue"),
                    )
                if (
                    result.change_from_opening is not None
                    or result.final_consensus
                    or result.final_disagreements
                    or result.final_recommendation is not None
                ):
                    raise TurnValidationError(
                        "Final-only fields are forbidden before integration.",
                        json_pointers=(
                            "/change_from_opening",
                            "/final_consensus",
                            "/final_disagreements",
                            "/final_recommendation",
                        ),
                    )

        if not used_receipts:
            if typed_receipts:
                raise TurnValidationError(
                    "A retrieval hit must be represented by a claim receipt.",
                    # Name the array to fill, not just the field that is wrong:
                    # "/key_claims" alone left a repair attempt guessing which
                    # of several rules about key claims it had broken.
                    json_pointers=("/key_claims/0/used_evidence_refs",),
                )
            if has_explicit_source_claim(result.speech) or any(
                has_explicit_source_claim(claim.claim_text)
                for claim in result.key_claims
                if claim.claim_type != "value_judgement"
            ):
                raise TurnValidationError(
                    "A no-match turn cannot make an explicit source attribution or "
                    "concrete quantity.",
                    json_pointers=("/speech",),
                )
            retrieval_status: Literal["matched", "no_match"] = "no_match"
            grounding_mode: Literal["rag_grounded", "mixed", "general_reasoning"] = (
                "general_reasoning"
            )
            sources: tuple[PublicSource, ...] = ()
        else:
            retrieval_status = "matched"
            grounding_mode = "mixed"
            sources = tuple(
                PublicSource(
                    source_filename=receipt.source_filename,
                    chunk_id=receipt.chunk_id,
                    evidence_id=receipt.resolved_evidence_id(),
                    rank=receipt.rank,
                    score=receipt.score,
                )
                for receipt in used_receipts
            )
        word_count = count_turn_words(result.speech, question_text, self.language)
        if word_count < self.min_words or word_count > self.max_words:
            raise TurnValidationError(
                f"Speech must contain {self.min_words}-{self.max_words} words "
                "including its question.",
                json_pointers=("/speech",),
            )
        return ValidatedTurn(
            result=result,
            retrieval_status=retrieval_status,
            grounding_mode=grounding_mode,
            used_receipts=used_receipts,
            public_sources=sources,
            word_count=word_count,
        )

    def validate_after_sentence_trim(
        self,
        value: MutualLearningTurnResultV1,
        *,
        plan: TurnPlan,
        participant: ParticipantContext,
        participants: Sequence[ParticipantContext] = (),
        receipts: Sequence[SnapshotRetrievalReceipt] = (),
        predecessors: Sequence[FinalReadyTurn] = (),
        pending_question: PendingQuestion | None = None,
    ) -> ValidatedTurn:
        question_text = value.question.text if value.question.type != "none" else None
        trimmed = truncate_complete_sentences(value.speech, max_words=self.max_words)
        if trimmed is None or (
            question_text and not _contains_semantic_text(trimmed, question_text)
        ):
            raise TurnValidationError(
                "No complete-sentence boundary satisfies the word limit.",
                json_pointers=("/speech",),
            )
        return self.validate(
            value.model_copy(update={"speech": trimmed}),
            plan=plan,
            participant=participant,
            participants=participants,
            receipts=receipts,
            predecessors=predecessors,
            pending_question=pending_question,
        )


# Concise adapter name for callers that use the generic validator vocabulary.
MutualTurnValidator = MutualLearningValidator


__all__ = [
    "MutualLearningValidationResult",
    "MutualLearningValidator",
    "MutualTurnValidator",
]
