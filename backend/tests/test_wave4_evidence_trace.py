"""Acceptance tests for the Mock-first EvidenceTraceV1 lineage boundary."""

from __future__ import annotations

import pytest
from app.modules.debates.generation import (
    EvidenceTraceClaimV1,
    EvidenceTraceReceiptV1,
    EvidenceTraceValidationError,
    SnapshotRetrievalReceipt,
    SpeechSpanV1,
    TurnSubquery,
    align_mutual_learning_claim_ids,
    build_evidence_trace_bundle,
    build_mutual_learning_evidence_trace,
    derive_exact_speech_span,
    derive_source_locator,
    public_evidence_trace,
    utf16_slice,
)
from app.modules.debates.generation.mutual_learning_policy import MutualLearningPolicy
from app.modules.debates.generation.types import (
    FinalReadyTurn,
    KeyClaimV1,
    MutualLearningTurnResultV1,
    ParticipantContext,
    TurnQuestion,
)


def _receipt(
    evidence_id: str,
    *,
    snapshot_id: str = "snapshot-a",
    query_id: str | None = None,
    query_kind: str | None = None,
    query_text: str | None = None,
) -> EvidenceTraceReceiptV1:
    return EvidenceTraceReceiptV1(
        evidence_id=evidence_id,
        snapshot_id=snapshot_id,
        query_id=query_id,
        query_kind=query_kind,  # type: ignore[arg-type]
        query_text=query_text,
        chunk_id=f"chunk-{evidence_id}",
        source_filename="evidence.md",
        source_locator="md:document-a:chars:0-32",
        excerpt="The immutable evidence excerpt.",
        score=0.91,
        rank=1,
        threshold_key="strict",
    )


def test_utf16_span_is_exact_and_handles_astral_characters() -> None:
    speech = "Opening 😀 claim: communities need care."
    claim = "claim: communities need care."
    span = derive_exact_speech_span(speech, claim)
    assert span == SpeechSpanV1(start_utf16=11, end_utf16=40)
    assert utf16_slice(speech, span.start_utf16, span.end_utf16) == claim


def test_non_exact_and_ambiguous_spans_fail_closed() -> None:
    with pytest.raises(EvidenceTraceValidationError, match="not an exact"):
        derive_exact_speech_span("A short claim.", "A different claim.")
    with pytest.raises(EvidenceTraceValidationError, match="ambiguous"):
        derive_exact_speech_span("Repeated claim. Repeated claim.", "Repeated claim.")
    with pytest.raises(EvidenceTraceValidationError, match="exact speech"):
        build_evidence_trace_bundle(
            "turn-a",
            "A claim is there.",
            [EvidenceTraceClaimV1(claim_text="A claim is here", claim_type="proposal")],
            snapshot_id="snapshot-a",
        )


def test_locator_uses_server_document_and_half_open_code_point_offsets() -> None:
    assert (
        derive_source_locator("document-a", 4, 18, normalized_source="0123source passage")
        == "md:document-a:chars:4-18"
    )
    with pytest.raises(EvidenceTraceValidationError):
        derive_source_locator("../private", 0, 2)
    with pytest.raises(EvidenceTraceValidationError):
        derive_source_locator("document-a", 4, 4)


def test_direct_trace_uses_server_query_and_claim_ids_and_hides_unused_receipts() -> None:
    speech = "The policy covers 20 users. A transparent review is a proposal."
    query = TurnSubquery("viewpoint", "Find policy coverage.")
    used = SnapshotRetrievalReceipt(
        snapshot_id="snapshot-a",
        query_kind="viewpoint",
        query_hash=query.query_hash,
        threshold_key="strict",
        rank=1,
        score=0.9,
        chunk_id="chunk-used",
        source_filename="evidence.md",
        text="The policy covers 20 users.",
        evidence_id="evidence-used",
        source_document_id="document-a",
        source_start_offset=0,
        source_end_offset=27,
    )
    unused = _receipt("evidence-unused")
    bundle = build_evidence_trace_bundle(
        "turn-a",
        speech,
        [
            EvidenceTraceClaimV1(
                claim_text="The policy covers 20 users.",
                claim_type="factual",
                used_evidence_ids=["evidence-used"],
            ),
            EvidenceTraceClaimV1(
                claim_text="A transparent review is a proposal.",
                claim_type="proposal",
            ),
        ],
        [used, unused],
        [query],
        snapshot_id="snapshot-a",
    )
    first, second = bundle.traces
    assert first.support_mode == "direct"
    assert first.query_id == bundle.queries[0].query_id
    assert first.claim_id != ""
    assert first.claim_id != "The policy covers 20 users."
    assert first.speech_span.start_utf16 == 0
    assert second.support_mode == "general_reasoning"
    assert second.evidence_id is None
    assert bundle.unused_evidence_ids == ("evidence-unused",)
    assert bundle.public_sources == ("evidence-used",)
    assert public_evidence_trace(bundle) == bundle.traces


def test_contextual_general_and_no_match_modes_preserve_lineage_boundary() -> None:
    speech = "A transparent review is a proposal."
    receipt = _receipt("evidence-a")
    contextual = build_evidence_trace_bundle(
        "turn-a",
        speech,
        [
            EvidenceTraceClaimV1(
                claim_text=speech,
                claim_type="proposal",
                used_evidence_ids=[receipt.evidence_id],
                support_mode="contextual",
            )
        ],
        [receipt],
        snapshot_id="snapshot-a",
    )
    assert contextual.traces[0].support_mode == "contextual"
    assert contextual.traces[0].evidence_id == receipt.evidence_id

    general = build_evidence_trace_bundle(
        "turn-b",
        speech,
        [EvidenceTraceClaimV1(claim_text=speech, claim_type="proposal")],
        [receipt],
        snapshot_id="snapshot-a",
    )
    assert general.traces[0].support_mode == "general_reasoning"
    assert general.traces[0].source_filename is None
    no_match = build_evidence_trace_bundle(
        "turn-c",
        speech,
        [EvidenceTraceClaimV1(claim_text=speech, claim_type="value_judgement")],
        snapshot_id="snapshot-a",
    )
    assert no_match.traces[0].support_mode == "no_match"
    assert no_match.traces[0].query_id is None


def test_quantities_and_attributions_need_direct_evidence() -> None:
    speech = "According to the study, 20 users changed behavior."
    receipt = _receipt("evidence-a")
    claim = EvidenceTraceClaimV1(claim_text=speech, claim_type="factual")
    with pytest.raises(EvidenceTraceValidationError, match="direct evidence"):
        build_evidence_trace_bundle("turn-a", speech, [claim], [receipt], snapshot_id="snapshot-a")
    with pytest.raises(EvidenceTraceValidationError, match="direct evidence"):
        build_evidence_trace_bundle(
            "turn-a",
            speech,
            [
                claim.model_copy(
                    update={
                        "used_evidence_ids": [receipt.evidence_id],
                        "support_mode": "contextual",
                    }
                )
            ],
            [receipt],
            snapshot_id="snapshot-a",
        )


def test_cross_snapshot_receipt_and_query_are_rejected() -> None:
    query = TurnSubquery("viewpoint", "Find evidence.")
    receipt = SnapshotRetrievalReceipt(
        snapshot_id="snapshot-b",
        query_kind="viewpoint",
        query_hash=query.query_hash,
        threshold_key="strict",
        rank=1,
        score=0.8,
        chunk_id="chunk-b",
        source_filename="other.md",
        text="The claim is supported.",
        evidence_id="evidence-b",
        source_document_id="document-b",
        source_start_offset=0,
        source_end_offset=23,
    )
    with pytest.raises(EvidenceTraceValidationError, match="snapshot"):
        build_evidence_trace_bundle(
            "turn-a",
            "The claim is supported.",
            [
                EvidenceTraceClaimV1(
                    claim_text="The claim is supported.",
                    claim_type="background",
                    used_evidence_ids=["evidence-b"],
                )
            ],
            [receipt],
            [query],
            snapshot_id="snapshot-a",
        )


def test_mutual_result_can_carry_optional_exact_trace_claims_without_provider_ids() -> None:
    participant = ParticipantContext(
        participant_id="participant-a",
        agent_id="agent-a",
        agent_name="Agent A",
        slot="A",
        order_index=0,
        snapshot_id="snapshot-a",
    )
    speech = "A transparent review is a proposal for accountability."
    result = MutualLearningTurnResultV1(
        speech=speech,
        key_claims=[
            KeyClaimV1(
                claim_id="provider-claim",
                claim_text="A proposal.",
                claim_type="proposal",
            )
        ],
        evidence_trace_claims=[
            EvidenceTraceClaimV1(
                claim_text=speech,
                claim_type="proposal",
            )
        ],
        position_summary="A transparent review is a proposal.",
        position_update="unchanged",
        remaining_uncertainty=["Implementation remains uncertain."],
        question=TurnQuestion(type="none"),
    )
    plan = MutualLearningPolicy().plan([participant, "participant-b"], round_count=2)[0]
    turn = FinalReadyTurn(
        turn_id="turn-a",
        participant_id=participant.participant_id,
        snapshot_id=participant.snapshot_id,
        round_no=1,
        turn_index=0,
        speech=speech,
        structured=result,
        retrieval_status="no_match",
        grounding_mode="general_reasoning",
        used_receipts=(),
        predecessor_turn_ids=(),
        cutoff_turn_index=-1,
        transcript_hash="hash",
        attempt=1,
    )
    bundle = build_mutual_learning_evidence_trace(turn)
    assert bundle is not None
    assert bundle.traces[0].claim_id != "provider-claim"
    assert bundle.traces[0].support_mode == "no_match"
    assert plan.phase == "opening"


def test_mutual_key_claims_use_the_same_server_id_as_trace_rows() -> None:
    speech = "A transparent review is a proposal for accountability."
    result = MutualLearningTurnResultV1(
        speech=speech,
        key_claims=[
            KeyClaimV1(
                claim_id="provider-assigned-id",
                claim_text=speech,
                claim_type="proposal",
            )
        ],
        evidence_trace_claims=[EvidenceTraceClaimV1(claim_text=speech, claim_type="proposal")],
        position_summary="A transparent review is a proposal.",
        position_update="unchanged",
        remaining_uncertainty=["Implementation remains uncertain."],
        question=TurnQuestion(type="none"),
    )
    bundle = build_evidence_trace_bundle(
        "turn-a",
        speech,
        result.evidence_trace_claims,
        snapshot_id="snapshot-a",
    )
    aligned = align_mutual_learning_claim_ids(result, bundle)
    assert aligned.key_claims[0].claim_id == bundle.traces[0].claim_id
    assert aligned.key_claims[0].claim_id != "provider-assigned-id"
