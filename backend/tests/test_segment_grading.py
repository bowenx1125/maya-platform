"""Focused checks for paragraph support-mode grading and compatibility."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.modules.debates.generation.segment_grading import (
    SegmentGradingError,
    aggregate_agent_scores,
    grade_segment,
    summarize_segments,
)
from app.modules.debates.generation.segments import (
    SegmentProtocolError,
    build_segment_system_prompt,
    load_stored_segment_turn_result,
    validate_segment_output,
)
from app.modules.reports.real_prompt import REPORT_SYSTEM_PROMPT_V2
from app.modules.reports.real_schema import ReportRequestV2
from app.modules.reports.schemas import ReportAgentScore, ReportInputManifestV2, ReportScoreSummary
from app.providers.llm import MockLLMProvider
from app.providers.llm_segments import (
    SegmentLLMRequestV2,
    SegmentMessageV2,
    load_segment_request_v2,
)

from tests.test_segments_protocol import _snapshot


def test_three_classroom_grades_sum_to_seven_and_keep_counts() -> None:
    summary = summarize_segments(
        (
            {"text": "direct", "source_ids": ["S1"], "support_mode": "direct"},
            {"text": "context", "source_ids": ["S2"], "support_mode": "contextual"},
            {"text": "none", "source_ids": [], "support_mode": "no_match"},
        ),
        valid_source_ids={"S1", "S2"},
    )
    assert summary.total_points == 7
    assert summary.direct_count == 1
    assert summary.contextual_count == 1
    assert summary.no_match_count == 1
    assert summary.ungraded_count == 0


def test_segment_prompt_states_mode_definitions_and_legacy_omission_rule() -> None:
    prompt = build_segment_system_prompt("en", phase="exchange")
    assert "Every new paragraph must explicitly include support_mode" in prompt
    assert "directly supports" in prompt
    assert "relevant background but does not directly answer" in prompt
    assert "Every new paragraph must include support_mode" in prompt


@pytest.mark.parametrize("mode", [None, [], {}, True, 7])
def test_provider_mode_types_fail_with_safe_code(mode: object) -> None:
    with pytest.raises(SegmentProtocolError) as error:
        validate_segment_output(
            {
                "segments": [
                    {
                        "text": "A paragraph.",
                        "source_ids": [],
                        "reply_to": None,
                        "support_mode": mode,
                    }
                ]
            },
            _snapshot(),
        )
    assert error.value.code == "support_mode_invalid"


def test_missing_mode_is_ungraded_even_without_sources() -> None:
    result = grade_segment({"text": "legacy", "source_ids": []})
    assert result.grade == "ungraded"
    assert result.points == 0
    assert summarize_segments(({"text": "legacy", "source_ids": ["S1"]},)).ungraded_count == 1


def test_mock_segment_output_marks_source_quote_direct_and_unsourced_reply_no_match() -> None:
    snapshot = _snapshot(round_number=3, barrages=({"id": "B1", "text": "Question?"},))
    output = MockLLMProvider().generate_segments(snapshot)
    segments = output["segments"]
    assert isinstance(segments, list)
    assert segments[0]["support_mode"] == "direct"
    assert segments[0]["source_ids"] == ["S1"]
    assert segments[1]["support_mode"] == "no_match"
    assert segments[1]["source_ids"] == []
    assert segments[1]["reply_to"] == "B1"


@pytest.mark.parametrize(
    ("value", "code"),
    (
        (
            {"text": "missing citation", "source_ids": [], "support_mode": "direct"},
            "support_mode_source_mismatch",
        ),
        (
            {"text": "missing citation", "source_ids": [], "support_mode": "contextual"},
            "support_mode_source_mismatch",
        ),
        (
            {"text": "wrong citation", "source_ids": ["S1"], "support_mode": "no_match"},
            "support_mode_source_mismatch",
        ),
        (
            {"text": "unknown source", "source_ids": ["S9"], "support_mode": "direct"},
            "source_reference_invalid",
        ),
    ),
)
def test_mode_source_consistency_fails_closed(value: dict[str, object], code: str) -> None:
    with pytest.raises(SegmentGradingError) as error:
        grade_segment(value, valid_source_ids={"S1"})
    assert error.value.code == code


def test_agent_aggregation_deduplicates_exact_replay_and_rejects_conflicting_duplicate() -> None:
    turns = [
        {
            "turn_id": "turn-a",
            "participant_id": "participant-a",
            "segments": [
                {"text": "direct", "source_ids": ["E1"], "support_mode": "direct"},
                {"text": "none", "source_ids": [], "support_mode": "no_match"},
            ],
        },
        {
            "turn_id": "turn-a",
            "participant_id": "participant-a",
            "segments": [
                {"text": "direct", "source_ids": ["E1"], "support_mode": "direct"},
                {"text": "none", "source_ids": [], "support_mode": "no_match"},
            ],
        },
    ]
    scores = aggregate_agent_scores(turns, valid_source_ids_by_turn={"turn-a": {"E1"}})
    assert len(scores) == 1
    assert scores[0].total_points == 5
    assert scores[0].direct_count == 1
    assert scores[0].no_match_count == 1

    with pytest.raises(SegmentGradingError) as error:
        aggregate_agent_scores(
            [
                *turns,
                {
                    "turn_id": "turn-a",
                    "participant_id": "participant-a",
                    "segments": [{"text": "changed", "source_ids": [], "support_mode": "no_match"}],
                },
            ],
            valid_source_ids_by_turn={"turn-a": {"E1"}},
        )
    assert error.value.code == "duplicate_turn_conflict"


def test_old_stored_payload_bytes_are_unchanged_and_new_mode_round_trips() -> None:
    legacy = {
        "schema_version": "segment_turn_v2",
        "segments": [{"text": "legacy", "source_ids": ["evidence-1"], "reply_to": None}],
    }
    loaded_legacy = load_stored_segment_turn_result(legacy)
    assert loaded_legacy.as_payload() == legacy
    assert "support_mode" not in loaded_legacy.lineage[0].as_payload()

    nullable_legacy = {
        "schema_version": "segment_turn_v2",
        "segments": [{"text": "legacy", "source_ids": [], "reply_to": None, "support_mode": None}],
    }
    loaded_nullable = load_stored_segment_turn_result(nullable_legacy)
    assert loaded_nullable.as_payload() == {
        "schema_version": "segment_turn_v2",
        "segments": [{"text": "legacy", "source_ids": [], "reply_to": None}],
    }

    graded = {
        "schema_version": "segment_turn_v2",
        "segments": [
            {
                "text": "supported",
                "source_ids": ["evidence-1"],
                "reply_to": None,
                "support_mode": "contextual",
            }
        ],
        "lineage": [
            {
                "segment_index": 0,
                "text": "supported",
                "start_offset": 0,
                "end_offset": 9,
                "source_ids": ["evidence-1"],
                "reply_to": None,
                "support_mode": "contextual",
            }
        ],
    }
    loaded_graded = load_stored_segment_turn_result(graded)
    assert loaded_graded.as_payload(include_lineage=True) == graded
    assert loaded_graded.lineage[0].support_mode == "contextual"


def test_old_frozen_request_keeps_its_schema_hash_for_recovery() -> None:
    snapshot = _snapshot()
    old_hash = "16e0854ed073e8fd71df30af59803ca2c5c0920a257ba5d5b0878414bf32a2b0"
    message = SegmentMessageV2(role="user", content=snapshot.to_user_json())
    request = SegmentLLMRequestV2(
        snapshot=snapshot,
        endpoint="https://offline.invalid/segments",
        method="POST",
        body={"legacy": True},
        messages=(message, message),
        budget=SimpleNamespace(),
        request_hash="a" * 64,
        schema_hash=old_hash,
        prompt_hash=snapshot.input_hash,
        debate_id="debate-1",
        turn_id="turn-1",
        generation_fence="fence",
        policy_hash="b" * 64,
        export_manifest_hash="c" * 64,
        build_manifest_hash="d" * 64,
    )
    loaded = load_segment_request_v2(request.frozen_payload())
    assert loaded.schema_hash == old_hash


def test_v2_report_score_summary_is_closed_and_legacy_manifest_hash_has_no_empty_field() -> None:
    from uuid import uuid4

    participants = [
        {
            "participant_id": uuid4(),
            "slot": "A",
            "order_index": 0,
            "agent_name": "A",
            "stance_mode": "open",
            "initial_stance": None,
            "current_stance": None,
        },
        {
            "participant_id": uuid4(),
            "slot": "B",
            "order_index": 1,
            "agent_name": "B",
            "stance_mode": "open",
            "initial_stance": None,
            "current_stance": None,
        },
    ]
    base = {
        "debate_id": uuid4(),
        "topic": "A responsible classroom question",
        "participants": participants,
        "turns": [],
        "turn_sources": [],
        "votes": [],
        "insight": {
            "snapshot_id": uuid4(),
            "revision": 1,
            "included_count": 0,
            "filtered_count": 0,
            "items": [],
        },
        "classroom_barrages": [],
        "replies": [],
    }
    legacy = ReportInputManifestV2.model_validate(base)
    assert "score_summary" not in legacy.canonical_payload()
    assert legacy.canonical_json() == ReportInputManifestV2.model_validate(base).canonical_json()

    score = ReportScoreSummary(
        agents=[
            ReportAgentScore(
                slot="A",
                direct_count=1,
                contextual_count=1,
                no_match_count=0,
                ungraded_count=0,
                total_points=7,
            ),
            ReportAgentScore(
                slot="B",
                direct_count=0,
                contextual_count=0,
                no_match_count=1,
                ungraded_count=0,
                total_points=0,
            ),
        ],
        direct_count=1,
        contextual_count=1,
        no_match_count=1,
        ungraded_count=0,
        total_points=7,
    )
    graded = ReportInputManifestV2.model_validate({**base, "score_summary": score.model_dump()})
    assert graded.score_summary is not None
    assert graded.score_summary.total_points == 7
    assert graded.canonical_payload()["score_summary"]["total_points"] == 7


def test_real_v2_request_carries_score_summary_without_private_fields() -> None:
    score = ReportScoreSummary(
        agents=[
            ReportAgentScore(
                slot="A",
                direct_count=1,
                contextual_count=0,
                no_match_count=0,
                ungraded_count=0,
                total_points=5,
            ),
            ReportAgentScore(
                slot="B",
                direct_count=0,
                contextual_count=1,
                no_match_count=0,
                ungraded_count=0,
                total_points=2,
            ),
        ],
        direct_count=1,
        contextual_count=1,
        no_match_count=0,
        ungraded_count=0,
        total_points=7,
    )
    request = ReportRequestV2.model_validate(
        {
            "topic": "A classroom question",
            "participants": [{"slot": "A", "agent_name": "A"}, {"slot": "B", "agent_name": "B"}],
            "speeches": [
                {
                    "slot": "A",
                    "round_no": 1,
                    "turn_index": 0,
                    "speech": "The record gives a bounded answer.",
                    "used_evidence_ids": ["E1"],
                }
            ],
            "sources": [{"evidence_id": "E1", "excerpt": "A bounded public record."}],
            "votes": [],
            "insights": [],
            "classroom_barrages": [],
            "replies": [],
            "score_summary": score.model_dump(),
        }
    )
    assert request.score_summary is not None
    assert request.canonical_payload()["score_summary"]["total_points"] == 7
    assert "score_summary" in request.canonical_json()
    assert "private" not in request.canonical_json().lower()
    assert "score_summary" not in REPORT_SYSTEM_PROMPT_V2
