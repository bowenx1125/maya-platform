"""Canonical prompt rendering for the ordered mutual-learning RuleSet."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import cast

from .evidence_trace import EvidenceTraceQueryKind, EvidenceTraceQueryV1, server_query_id
from .mutual_learning_policy import (
    MUTUAL_LEARNING_RULE_SET_ID,
    pending_question_for_turn,
    visible_prior_round_turns,
)
from .retrieval import TurnSubquery
from .round_phase import resolve_round_phase
from .types import (
    FinalReadyTurn,
    GenerationContext,
    MutualLearningPromptInput,
    ParticipantContext,
    SnapshotRetrievalReceipt,
    TurnValidationError,
)

MUTUAL_LEARNING_PLATFORM_RULES = (
    "This is the ordered multi-expert mutual-learning protocol. Apply these platform "
    "rules before any persona text.",
    "Authoritative speech is English only and must remain respectful; never solicit a vote.",
    "Opening is independent: do not engage another Agent, answer a question, evaluate "
    "another Agent, claim consensus, or ask a targeted question.",
    "Exchange answers its assigned pending question when present, faithfully engages a "
    "public claim from an earlier round, rechecks the current Agent's snapshot, updates "
    "its position, records uncertainty, and may ask at most one other Agent for the next "
    "round.",
    "Final integration answers remaining questions, engages an earlier-round claim, "
    "states what was learned, compares opening and final positions, preserves consensus "
    "and disagreement, and gives a recommendation. It asks no question.",
    "The round barrier is strict: only public/final-ready turns from rounds before the "
    "current round are visible. Same-round and future turns are never context.",
    "Evidence is snapshot-scoped. Use only server-assigned receipt IDs from this "
    "request; discussing another Agent's claim never transfers that Agent's evidence.",
    "No receipt means honest general reasoning/no_match. Concrete quantities and named "
    "study, expert, survey, report, or source claims require a current receipt.",
    # The server fails a turn closed when a retrieval hit is never represented
    # by a claim, and that requirement was previously only enforced, never said.
    "When this request supplies retrieval receipts, at least one key claim must cite one "
    "of them in used_evidence_refs, using the 0-based index of that receipt in this "
    "request's evidence catalog. Cite a receipt only where it genuinely supports the "
    "claim; when the request supplies no receipt, leave every used_evidence_refs empty.",
    # The server binds every claim to a span of the turn's own speech, so a
    # paraphrased claim_text fails closed.  The rule was enforced but never
    # stated, which made the first real provider turn reject itself.
    "Every key_claims[].claim_text must be copied verbatim from this turn's own speech: "
    "an exact character-for-character substring of it. Never paraphrase, shorten, "
    "re-punctuate, translate or merge sentences when filling claim_text.",
    # Every key below is required by the closed schema, so a phase-absent value
    # has an exact written form.  The supplier's strict mode enforces shape but
    # not minimum length, and these forms were previously never stated.
    "position_summary and position_update_reason are always non-empty. "
    "change_from_opening, unresolved_issue and final_recommendation use the empty "
    "string '' as the explicit 'not applicable in this phase' value. Every list may be "
    "empty, but a list entry is never an empty string.",
    "The question object has exactly two legal forms. To ask nothing use mode='none' "
    "with target_participant_ref=-1 and text='' (an empty string). To ask, use "
    "mode='ask' with non-empty text that also appears in the speech, and "
    "target_participant_ref as a 0-based index into this request's question targets; "
    "never invent an index.",
    "Opening must return: 2 to 4 key_claims; empty engagements; "
    "answered_required_question=false; empty learned_from_others; "
    "position_update='unchanged'; non-empty missing_information and "
    "remaining_uncertainty; question mode='none'; and the empty string for "
    "change_from_opening and final_recommendation with empty final_consensus and "
    "final_disagreements. Its speech never addresses or evaluates another expert.",
    "Exchange must return at least one key claim and at least one engagement targeting a "
    "visible earlier-round claim by another expert, a non-empty position_update_reason, "
    "and at most one question.",
    "Final integration must return non-empty learned_from_others and "
    "remaining_uncertainty, non-empty change_from_opening and final_recommendation, "
    "question mode='none', and every final_disagreements category from "
    "different_persona_or_framework, different_evidence, evidence_conflict, "
    "insufficient_information or value_tradeoff.",
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _receipt_payload(
    receipt: SnapshotRetrievalReceipt,
    queries: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    query = next(
        (
            item
            for item in queries
            if item.get("query_kind") == receipt.query_kind
            and item.get("query_hash") == receipt.query_hash
        ),
        None,
    )
    return {
        "evidence_id": receipt.resolved_evidence_id(),
        "snapshot_id": receipt.snapshot_id,
        "query_kind": receipt.query_kind,
        "query_hash": receipt.query_hash,
        "threshold_key": receipt.threshold_key,
        "rank": receipt.rank,
        "score": receipt.score,
        "chunk_id": receipt.chunk_id,
        "source_filename": receipt.source_filename,
        "text": receipt.text,
        "query_id": query.get("query_id") if query else receipt.query_id,
    }


def compute_mutual_receipt_hash(receipts: Sequence[SnapshotRetrievalReceipt]) -> str:
    return _hash([_receipt_payload(item) for item in receipts])


def _structured_public_payload(turn: FinalReadyTurn) -> dict[str, object]:
    value = turn.structured
    # Pydantic models expose model_dump; keeping this adapter structural lets
    # replay fixtures use a frozen dictionary without importing an ORM row.
    dumped = value.model_dump(mode="json") if hasattr(value, "model_dump") else {}
    return {
        "turn_id": turn.turn_id,
        "participant_id": turn.participant_id,
        "round_no": turn.round_no,
        "turn_index": turn.turn_index,
        "speech": turn.speech,
        "key_claims": dumped.get("key_claims", []),
        "engagements": dumped.get("engagements", []),
        "answered_question_ids": dumped.get(
            "answered_question_ids",
            [dumped.get("answered_question_id")] if dumped.get("answered_question_id") else [],
        ),
        "learned_from_others": dumped.get("learned_from_others", []),
        "position_summary": dumped.get("position_summary", ""),
        "position_update": dumped.get("position_update", "unchanged"),
        "position_update_reason": dumped.get("position_update_reason"),
        "remaining_uncertainty": dumped.get("remaining_uncertainty", []),
        "unresolved_issue": dumped.get("unresolved_issue"),
        "question": dumped.get("question", {"type": "none"}),
        "used_evidence_id": dumped.get("used_evidence_id", []),
        "missing_information": dumped.get("missing_information", []),
        "unresolved_questions": dumped.get("unresolved_questions", []),
        "change_from_opening": dumped.get("change_from_opening"),
        "final_consensus": dumped.get("final_consensus", []),
        "final_disagreements": dumped.get("final_disagreements", []),
        "final_recommendation": dumped.get("final_recommendation"),
    }


def compute_mutual_transcript_hash(predecessors: Sequence[FinalReadyTurn]) -> str:
    """Hash only public turns from completed earlier rounds."""

    ordered = tuple(
        sorted(predecessors, key=lambda item: (item.round_no, item.turn_index, item.turn_id))
    )
    return _hash([_structured_public_payload(item) for item in ordered])


def _participant_payload(participant: ParticipantContext) -> dict[str, object]:
    # The current Agent's persona is private input.  Other participants are
    # represented by schedule-only data below.
    return {
        "participant_id": participant.participant_id,
        "agent_id": participant.agent_id,
        "agent_name": participant.agent_name,
        "slot": participant.slot,
        "order_index": participant.order_index,
        "snapshot_id": participant.snapshot_id,
        "agent_md": participant.agent_md,
        "stance_mode": participant.stance_mode,
        "initial_stance": participant.initial_stance,
        "current_stance": participant.current_stance,
        "initial_position_summary": participant.initial_position_summary,
        "current_position_summary": participant.current_position_summary,
        "teacher_note": participant.teacher_note,
    }


def _schedule_payload(participant: ParticipantContext) -> dict[str, object]:
    return {
        "participant_id": participant.participant_id,
        "agent_name": participant.agent_name,
        "slot": participant.slot,
        "order_index": participant.order_index,
        "stance_mode": participant.stance_mode,
        "assigned_stance": (
            participant.current_stance or participant.initial_stance
            if participant.stance_mode == "assigned"
            else None
        ),
    }


def make_mutual_learning_prompt_input(
    context: GenerationContext,
    receipts: Sequence[SnapshotRetrievalReceipt] = (),
    queries: Sequence[TurnSubquery] = (),
) -> MutualLearningPromptInput:
    """Build the request using only the resolved prior-round barrier."""

    plan = context.turn
    if plan.barrier != "round":
        raise TurnValidationError("The mutual-learning prompt requires a round barrier plan.")
    try:
        phase = resolve_round_phase(plan.round_no, plan.is_final_round)
    except ValueError as exc:
        raise TurnValidationError("The mutual-learning turn phase is invalid.") from exc
    if phase.value != plan.phase:
        raise TurnValidationError("The turn plan phase does not match its explicit final marker.")
    visible = tuple(
        cast(FinalReadyTurn, item) for item in visible_prior_round_turns(context.predecessors, plan)
    )
    predecessor_ids = tuple(str(item.turn_id) for item in visible)
    planned_ids = tuple(plan.predecessor_turn_ids)
    if planned_ids != predecessor_ids:
        raise TurnValidationError("The prior-round predecessor IDs do not match the plan.")
    for item in visible:
        if getattr(item, "publication_status", "final_ready") not in {"final_ready", "public"}:
            raise TurnValidationError("A prior-round turn is not final-ready.")
    typed_receipts = tuple(receipts)
    for receipt in typed_receipts:
        if receipt.snapshot_id != context.participant.snapshot_id:
            raise TurnValidationError("A receipt belongs to a different participant snapshot.")
    query_rows = tuple(
        EvidenceTraceQueryV1(
            query_id=server_query_id(context.turn.turn_id, index, query),
            query_kind=cast(EvidenceTraceQueryKind, query.query_kind),
            text=query.text,
            query_hash=query.query_hash,
            turn_id=context.turn.turn_id,
            snapshot_id=context.participant.snapshot_id,
        ).model_dump(mode="json")
        for index, query in enumerate(queries)
    )
    transcript_hash = compute_mutual_transcript_hash(visible)
    pending = context.pending_question
    if pending is None:
        pending = pending_question_for_turn(
            visible,
            target_participant_id=context.participant.participant_id,
            current_round=plan.round_no,
        )
    cutoff = max((int(item.turn_index) for item in visible), default=-1)
    return MutualLearningPromptInput(
        debate_id=context.debate_id,
        topic=context.topic,
        rule_set_id=MUTUAL_LEARNING_RULE_SET_ID,
        phase=phase.value,
        turn_plan=plan,
        participant=context.participant,
        participants=context.participants,
        agent_md=context.participant.agent_md,
        stance_mode=context.participant.stance_mode,
        assigned_stance=(context.participant.current_stance or context.participant.initial_stance),
        teacher_note=context.participant.teacher_note,
        current_position_summary=context.participant.effective_position_summary,
        predecessors=visible,
        predecessor_turn_ids=predecessor_ids,
        cutoff_turn_index=cutoff,
        transcript_hash=transcript_hash,
        receipts=typed_receipts,
        queries=query_rows,
        pending_question=pending,
    )


def _payload(prompt: MutualLearningPromptInput) -> dict[str, object]:
    return {
        "prompt_contract_version": "MAYA_MUTUAL_LEARNING_PROMPT_V1",
        "debate_id": prompt.debate_id,
        "topic": prompt.topic,
        "rule_set_id": prompt.rule_set_id,
        "phase": prompt.phase,
        "turn_plan": {
            "turn_id": prompt.turn_plan.turn_id,
            "participant_id": prompt.turn_plan.participant_id,
            "slot": prompt.turn_plan.slot,
            "order_index": prompt.turn_plan.order_index,
            "round_no": prompt.turn_plan.round_no,
            "turn_index": prompt.turn_plan.turn_index,
            "phase": prompt.turn_plan.phase,
            "is_final": prompt.turn_plan.is_final,
            "is_final_round": prompt.turn_plan.is_final_round,
            "predecessor_turn_ids": list(prompt.predecessor_turn_ids),
        },
        "participant": _participant_payload(prompt.participant),
        "participants": [_schedule_payload(item) for item in prompt.participants],
        "stance_mode": prompt.stance_mode,
        "assigned_stance": prompt.assigned_stance,
        "current_position_summary": prompt.current_position_summary,
        "predecessor_turn_ids": list(prompt.predecessor_turn_ids),
        "cutoff_turn_index": prompt.cutoff_turn_index,
        "transcript_hash": prompt.transcript_hash,
        "predecessors": [_structured_public_payload(item) for item in prompt.predecessors],
        "queries": list(prompt.queries),
        "receipts": [_receipt_payload(item, prompt.queries) for item in prompt.receipts],
        "receipt_hash": compute_mutual_receipt_hash(prompt.receipts),
        "pending_question": (
            {
                "question_id": prompt.pending_question.question_id,
                "source_turn_id": prompt.pending_question.source_turn_id,
                "source_participant_id": prompt.pending_question.source_participant_id,
                "target_participant_id": prompt.pending_question.target_participant_id,
                "text": prompt.pending_question.text,
            }
            if prompt.pending_question is not None
            else None
        ),
        # The exact rules are rendered once in the preamble.  Keep only an
        # audit hash in the canonical JSON payload so a request cannot silently
        # duplicate or omit a platform rule block.
        "platform_priority_rules_hash": _hash(list(MUTUAL_LEARNING_PLATFORM_RULES)),
    }


def build_mutual_learning_prompt(prompt: MutualLearningPromptInput) -> str:
    preamble = "\n".join(
        (
            "MAYA_MUTUAL_LEARNING_PROMPT_V1",
            "PLATFORM_PRIORITY_RULES_BEGIN",
            *MUTUAL_LEARNING_PLATFORM_RULES,
            "PLATFORM_PRIORITY_RULES_END",
            "STRUCTURED_TURN_PAYLOAD_BEGIN",
        )
    )
    return preamble + "\n" + _canonical(_payload(prompt))


def mutual_learning_prompt_hash(prompt: MutualLearningPromptInput) -> str:
    return hashlib.sha256(build_mutual_learning_prompt(prompt).encode("utf-8")).hexdigest()


__all__ = [
    "MUTUAL_LEARNING_PLATFORM_RULES",
    "build_mutual_learning_prompt",
    "compute_mutual_receipt_hash",
    "compute_mutual_transcript_hash",
    "make_mutual_learning_prompt_input",
    "mutual_learning_prompt_hash",
]
