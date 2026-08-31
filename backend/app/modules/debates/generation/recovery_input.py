"""Provider-free, hash-bound input for accepted LLM continuation.

Only server-owned projections are serialized here.  In particular, the
participant projection never includes ``agent_md`` or ``teacher_note`` and a
request's endpoint/body/headers are not part of this contract.  The immutable
accepted stage remains the only durable output/usage record.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal, cast

from app.providers.control import LLM_RECOVERY_INPUT_VERSION, LLMRecoveryInputV1

from .policy import TurnPlan
from .prompt_request import PromptRequestV1
from .types import (
    FinalReadyTurn,
    GenerationContext,
    MutualLearningTurnResultV1,
    ParticipantContext,
    PendingQuestion,
    SnapshotRetrievalReceipt,
)

if TYPE_CHECKING:
    from .runtime import LLMPreparedAttemptV1

def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _read(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _int_value(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, (str, float)):
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default
    return default


def _items(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _receipt_record(value: object) -> dict[str, object]:
    result: dict[str, object] = {}
    for name in (
        "snapshot_id",
        "query_kind",
        "query_hash",
        "threshold_key",
        "rank",
        "score",
        "chunk_id",
        "source_filename",
        "text",
        "evidence_id",
        "source_document_id",
        "source_start_offset",
        "source_end_offset",
        "excerpt",
        "query_id",
    ):
        value_item = _read(value, name)
        if value_item is not None:
            result[name] = value_item
    return result


def _query_record(value: object) -> dict[str, object]:
    query_kind = _read(value, "query_kind")
    query_text = _read(value, "text", _read(value, "query_text"))
    query_hash = _read(value, "query_hash")
    query_id = _read(value, "query_id", None)
    if query_id is None:
        query_id = _read(value, "id", None)
    if query_id is None or not str(query_id):
        query_id = f"query-{str(query_hash)[:16]}"
    return {
        "query_id": str(query_id) if query_id is not None else "",
        "query_kind": str(query_kind),
        "text": str(query_text),
        "query_hash": str(query_hash),
    }


def _participant_record(value: object) -> dict[str, object]:
    result: dict[str, object] = {
        "participant_id": str(_read(value, "participant_id", "")),
        "agent_id": str(_read(value, "agent_id", "")),
        "slot": str(_read(value, "slot", "")),
        "order_index": _int_value(_read(value, "order_index", 0)),
        "snapshot_id": str(_read(value, "snapshot_id", "")),
        "stance_mode": str(_read(value, "stance_mode", "open")),
        "initial_stance": _read(value, "initial_stance"),
        "current_stance": _read(value, "current_stance"),
        "persona_spec_hash": _read(value, "persona_spec_hash"),
    }
    return result


def _predecessor_fence_record(value: object) -> dict[str, object]:
    return {
        "turn_id": str(_read(value, "turn_id", "")),
        "participant_id": str(_read(value, "participant_id", "")),
        "snapshot_id": str(_read(value, "snapshot_id", "")),
        "round_no": _int_value(_read(value, "round_no", 0)),
        "turn_index": _int_value(_read(value, "turn_index", 0)),
        "transcript_hash": str(_read(value, "transcript_hash", "")),
        "cutoff_turn_index": _int_value(_read(value, "cutoff_turn_index", -1), -1),
        "predecessor_turn_ids": [
            str(item) for item in _items(_read(value, "predecessor_turn_ids", ()))
        ],
        "publication_status": str(_read(value, "publication_status", "final_ready")),
    }


def _context_record(context: GenerationContext) -> dict[str, object]:
    # PromptRequest already contains the topic, turn plan, current Persona,
    # pending question and complete public predecessor projection.  Keep only
    # the participant graph fields that are needed to rebuild the validator's
    # owner/snapshot fence; this avoids a second copy of prompt prose.
    return {
        "version": LLM_RECOVERY_INPUT_VERSION,
        "participants": [_participant_record(item) for item in context.participants],
        "predecessor_fences": [
            _predecessor_fence_record(item) for item in context.predecessors
        ],
    }


def _recovery_input_parts(
    value: LLMRecoveryInputV1,
) -> tuple[
    Mapping[str, object],
    Mapping[str, object],
    list[object],
    list[object],
    Mapping[str, object],
]:
    """Decode the provider-owned canonical envelope into local read views."""

    try:
        envelope = json.loads(value.input_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("recovery input JSON is invalid") from exc
    if not isinstance(envelope, Mapping):
        raise ValueError("recovery input envelope is invalid")
    input_value = envelope.get("input")
    if not isinstance(input_value, Mapping):
        raise ValueError("recovery input body is invalid")
    if set(input_value) != {"request", "context", "receipts", "queries", "fence"}:
        raise ValueError("recovery input body is not closed")
    request = input_value.get("request")
    context = input_value.get("context")
    receipts = input_value.get("receipts")
    queries = input_value.get("queries")
    fence = input_value.get("fence")
    if (
        not isinstance(request, Mapping)
        or not isinstance(context, Mapping)
        or not isinstance(receipts, list)
        or not isinstance(queries, list)
        or not isinstance(fence, Mapping)
    ):
        raise ValueError("recovery input body shape is invalid")
    return request, context, receipts, queries, fence


def request_from_recovery_input(value: LLMRecoveryInputV1) -> Mapping[str, object]:
    """Return the canonical PromptRequest payload for local validation."""

    request, _, _, _, _ = _recovery_input_parts(value)
    return request


def build_llm_recovery_input(
    prepared: LLMPreparedAttemptV1,
    context: GenerationContext,
    *,
    stage: object,
) -> LLMRecoveryInputV1:
    """Build the single canonical provider-domain recovery input DTO.

    The envelope deliberately stores one canonical PromptRequest plus the
    small server-owned catalogs needed to rebuild evidence.  Participant
    Persona is already part of that request and is not copied into context.
    """

    request_json = prepared.prompt.request.canonical_json()
    context_value = _context_record(context)
    receipts_value = [_receipt_record(item) for item in prepared.receipts]
    queries_value = [_query_record(item) for item in prepared.queries]
    fence_value = prepared.fence.as_record()
    generation_fence_hash = _read(
        stage,
        "generation_fence",
        _read(prepared, "generation_fence_hash"),
    )
    if not isinstance(generation_fence_hash, str) or not generation_fence_hash:
        generation_fence_hash = hashlib.sha256(_canonical(fence_value).encode("utf-8")).hexdigest()
    identity_value = {
        "request_hash": str(_read(stage, "request_hash", prepared.request_hash)),
        "prompt_hash": str(_read(stage, "prompt_hash", prepared.prompt.request.request_hash)),
        "prompt_contract_version": str(_read(stage, "prompt_contract_version", "")),
        "schema_hash": str(_read(stage, "schema_hash", "")),
        "tokenizer_id": str(_read(stage, "tokenizer_id", "")),
        "tokenizer_hash": str(_read(stage, "tokenizer_hash", "")),
        "rule_set_hash": str(_read(stage, "rule_set_hash", prepared.prompt.request.rule_set_hash)),
        "persona_spec_hash": str(
            _read(stage, "persona_spec_hash", prepared.prompt.request.persona_spec_hash)
        ),
        "transcript_hash": str(
            _read(stage, "transcript_hash", prepared.prompt.request.transcript_hash)
        ),
        "receipt_hash": str(_read(stage, "receipt_hash", prepared.prompt.request.receipt_hash)),
        "policy_hash": str(_read(stage, "policy_hash", prepared.policy_hash)),
        "export_manifest_hash": str(_read(stage, "export_manifest_hash", prepared.manifest_hash)),
        "build_manifest_hash": str(
            _read(stage, "build_manifest_hash", prepared.build_manifest_hash)
        ),
        "repair_policy_hash": _read(
            stage, "repair_policy_hash", prepared.repair_policy_hash or None
        ),
        "generation_fence": generation_fence_hash,
        "model_key": str(_read(stage, "model_key", "qwen3.7-plus-2026-05-26")),
        "debate_id": prepared.debate_id,
        "turn_id": str(_read(stage, "turn_id", prepared.turn_id)),
        "attempt_no": _int_value(_read(stage, "attempt_no", prepared.attempt_no)),
    }
    input_json = _canonical(
        {
            "identity": identity_value,
            "input": {
                "request": json.loads(request_json),
                "context": context_value,
                "receipts": receipts_value,
                "queries": queries_value,
                "fence": fence_value,
            },
        }
    )
    input_hash = hashlib.sha256(input_json.encode("utf-8")).hexdigest()
    return LLMRecoveryInputV1(
        operation_id=str(prepared.operation_id or ""),
        turn_id=prepared.turn_id,
        attempt_no=_int_value(_read(stage, "attempt_no", prepared.attempt_no)),
        input_version=LLM_RECOVERY_INPUT_VERSION,
        input_json=input_json,
        input_hash=input_hash,
    )


__all__ = [
    "LLMRecoveryInputV1",
    "LLM_RECOVERY_INPUT_VERSION",
    "build_llm_recovery_input",
    "request_from_recovery_input",
]


def _receipt_from_record(value: object) -> SnapshotRetrievalReceipt:
    if not isinstance(value, Mapping):
        raise ValueError("recovery receipt shape is invalid")
    return SnapshotRetrievalReceipt(
        snapshot_id=str(value["snapshot_id"]),
        query_kind=str(value["query_kind"]),
        query_hash=str(value["query_hash"]),
        threshold_key=str(value["threshold_key"]),  # type: ignore[arg-type]
        rank=_int_value(value["rank"]),
        score=float(value["score"]),
        chunk_id=str(value["chunk_id"]),
        source_filename=str(value["source_filename"]),
        text=str(value["text"]),
        evidence_id=str(value.get("evidence_id", "")),
        source_document_id=(
            str(value["source_document_id"])
            if value.get("source_document_id") is not None
            else None
        ),
        source_start_offset=(
            _int_value(value["source_start_offset"])
            if value.get("source_start_offset") is not None
            else None
        ),
        source_end_offset=(
            _int_value(value["source_end_offset"])
            if value.get("source_end_offset") is not None
            else None
        ),
        excerpt=str(value["excerpt"]) if value.get("excerpt") is not None else None,
        query_id=str(value["query_id"]) if value.get("query_id") is not None else None,
    )


def context_from_recovery_input(value: LLMRecoveryInputV1) -> GenerationContext:
    """Rehydrate only the provider-safe context projection for local recovery."""

    request_value, payload, _, _, _ = _recovery_input_parts(value)
    prompt_request = PromptRequestV1.model_validate(request_value)

    def participant_from_record(item: object) -> ParticipantContext:
        if not isinstance(item, Mapping):
            raise ValueError("recovery participant shape is invalid")
        if set(item) != {
            "participant_id",
            "agent_id",
            "slot",
            "order_index",
            "snapshot_id",
            "stance_mode",
            "initial_stance",
            "current_stance",
            "persona_spec_hash",
        }:
            raise ValueError("recovery participant shape is not closed")
        return ParticipantContext(
            participant_id=str(item["participant_id"]),
            agent_id=str(item["agent_id"]),
            # This is intentionally a non-authoritative placeholder.  The
            # builder never persists an identity-bearing display name.
            agent_name=f"Participant {str(item.get('slot', ''))}",
            slot=str(item["slot"]),
            order_index=_int_value(item["order_index"]),
            snapshot_id=str(item["snapshot_id"]),
            stance_mode=str(item.get("stance_mode", "open")),  # type: ignore[arg-type]
            initial_stance=cast(
                Literal["support", "oppose", "neutral"] | None,
                str(item["initial_stance"]) if item.get("initial_stance") is not None else None,
            ),
            current_stance=cast(
                Literal["support", "oppose", "neutral"] | None,
                str(item["current_stance"]) if item.get("current_stance") is not None else None,
            ),
            initial_position_summary="",
            current_position_summary="",
            persona=None,
            persona_spec_hash=(
                str(item["persona_spec_hash"])
                if item.get("persona_spec_hash") is not None
                else None
            ),
        )

    participants_value = payload.get("participants")
    predecessor_fences_value = payload.get("predecessor_fences")
    if set(payload) != {"version", "participants", "predecessor_fences"}:
        raise ValueError("recovery participant fence is not closed")
    if payload.get("version") != LLM_RECOVERY_INPUT_VERSION:
        raise ValueError("recovery participant fence version is unsupported")
    if not isinstance(participants_value, list) or not isinstance(
        predecessor_fences_value, list
    ):
        raise ValueError("recovery participant fence is unavailable")
    participants = tuple(participant_from_record(item) for item in participants_value)
    participant = next(
        (
            item
            for item in participants
            if item.participant_id == prompt_request.participant_id
        ),
        None,
    )
    if participant is None:
        raise ValueError("recovery participant is unavailable")
    predecessor_fences: dict[str, Mapping[str, object]] = {}
    expected_fence_keys = {
        "turn_id",
        "participant_id",
        "snapshot_id",
        "round_no",
        "turn_index",
        "transcript_hash",
        "cutoff_turn_index",
        "predecessor_turn_ids",
        "publication_status",
    }
    for item in predecessor_fences_value:
        if not isinstance(item, Mapping) or set(item) != expected_fence_keys:
            raise ValueError("recovery predecessor fence is invalid")
        turn_id = item.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id or turn_id in predecessor_fences:
            raise ValueError("recovery predecessor fence is invalid")
        predecessor_fences[turn_id] = item
    if set(predecessor_fences) != {item.turn_id for item in prompt_request.predecessors}:
        raise ValueError("recovery predecessor fence is incomplete")
    plan = TurnPlan(
        turn_id=prompt_request.turn_id,
        participant_id=prompt_request.participant_id,
        slot=prompt_request.participant_slot,
        order_index=prompt_request.participant_order_index,
        round_no=prompt_request.round_no,
        turn_index=prompt_request.turn_index,
        phase=prompt_request.phase,
        next_participant_id=(
            str(prompt_request.next_participant_id)
            if prompt_request.next_participant_id is not None
            else None
        ),
        is_final=prompt_request.is_final_turn,
        predecessor_ids=tuple(item.turn_id for item in prompt_request.predecessors),
        barrier="round",
        is_final_round=prompt_request.is_final_round,
    )
    predecessors: list[FinalReadyTurn] = []
    for item in prompt_request.predecessors:
        fence = predecessor_fences.get(item.turn_id)
        if fence is None:
            raise ValueError("recovery predecessor fence is unavailable")
        if not isinstance(fence, Mapping):
            raise ValueError("recovery predecessor fence is invalid")
        structured_value: dict[str, object] = {
            "speech": item.speech,
            "key_claims": [claim.model_dump(mode="json") for claim in item.key_claims],
            "engagements": [
                engagement.model_dump(mode="json") for engagement in item.engagements
            ],
            "answered_question_ids": list(item.answered_question_ids),
            "learned_from_others": list(item.learned_from_others),
            "position_summary": item.position_summary,
            "position_update": item.position_update or "unchanged",
            "position_update_reason": item.position_update_reason,
            "remaining_uncertainty": list(item.remaining_uncertainty),
            "unresolved_issue": item.unresolved_issue,
            "question": {
                "type": item.question.type,
                "target_participant_id": item.question.target_participant_id,
                "text": item.question.text,
            },
            "used_evidence_id": list(item.used_evidence_ids),
            "missing_information": list(item.missing_information),
            "unresolved_questions": list(item.unresolved_questions),
            "change_from_opening": item.change_from_opening,
            "final_consensus": list(item.final_consensus),
            "final_disagreements": [
                disagreement.model_dump(mode="json")
                for disagreement in item.final_disagreements
            ],
            "final_recommendation": item.final_recommendation,
        }
        structured = MutualLearningTurnResultV1.model_validate(structured_value)
        snapshot_id = str(fence.get("snapshot_id", participant.snapshot_id))
        predecessor_ids = tuple(
            str(entry) for entry in _items(fence.get("predecessor_turn_ids", ()))
        )
        predecessors.append(
            FinalReadyTurn(
                turn_id=item.turn_id,
                participant_id=item.participant_id,
                snapshot_id=snapshot_id,
                round_no=item.round_no,
                turn_index=item.turn_index,
                speech=item.speech,
                structured=structured,
                retrieval_status="no_match",
                grounding_mode="general_reasoning",
                used_receipts=(),
                predecessor_turn_ids=predecessor_ids,
                cutoff_turn_index=_int_value(fence.get("cutoff_turn_index", -1), -1),
                transcript_hash=str(fence.get("transcript_hash", "")),
                attempt=1,
                publication_status=(
                    "public"
                    if str(fence.get("publication_status")) == "public"
                    else "final_ready"
                ),
                evidence_trace=(),
            )
        )
    pending_value = prompt_request.pending_question
    pending: PendingQuestion | None = None
    if pending_value is not None:
        pending = PendingQuestion(
            question_id=pending_value.question_id,
            source_turn_id=pending_value.source_turn_id,
            source_participant_id=pending_value.source_participant_id,
            target_participant_id=pending_value.target_participant_id,
            text=pending_value.text,
        )
    return GenerationContext(
        debate_id=prompt_request.debate_id,
        topic=prompt_request.topic,
        turn=plan,
        participant=participant,
        participants=participants,
        predecessors=tuple(predecessors),
        pending_question=pending,
    )


def receipts_from_recovery_input(
    value: LLMRecoveryInputV1,
) -> tuple[SnapshotRetrievalReceipt, ...]:
    """Decode the exact server-owned receipt catalog without retrieval I/O."""

    _, _, raw, _, _ = _recovery_input_parts(value)
    return tuple(_receipt_from_record(item) for item in raw)


def queries_from_recovery_input(
    value: LLMRecoveryInputV1,
) -> tuple[Mapping[str, object], ...]:
    """Decode the exact query catalog used for local EvidenceTrace rebuild."""

    _, _, _, raw, _ = _recovery_input_parts(value)
    if any(not isinstance(item, Mapping) for item in raw):
        raise ValueError("recovery query catalog is invalid")
    mappings = [cast(Mapping[str, object], item) for item in raw]
    return tuple(dict(item) for item in mappings)


__all__ += [
    "context_from_recovery_input",
    "queries_from_recovery_input",
    "receipts_from_recovery_input",
]
