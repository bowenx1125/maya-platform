"""Production segment salvage: over-length and empty-segment-in-question must not stall debates."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest
from app.modules.debates.generation.four_round import over_length_limit, speech_units
from app.modules.debates.generation.segments import (
    SEGMENT_OUTPUT_SALVAGED,
    SegmentProtocolError,
    salvage_segment_output,
    validate_segment_output,
)
from app.modules.debates.generation.segments_runtime import SegmentLLMRuntime
from app.modules.debates.generation_params import (
    RULESET_CONTRACT_V5,
    STRUCTURED_SEGMENT_TEMPERATURE_MAX,
    structured_segment_request_fields,
)
from app.providers.control import InMemoryProviderOperationRepository, ProviderScopeBudgetV1

from tests.test_debate_prompt_v4 import PARAMS, _output, _snapshot, _v4_context
from tests.test_four_round_provider import OfflineAdapter, opening_context, snapshot


def _v5_snapshot(*, round_no: int = 2, language: str = "zh", cap: int = 95):
    frozen = {
        "contract_version": RULESET_CONTRACT_V5,
        "params": {**PARAMS, "temperature": 1.8, "max_tokens": 33510},
        "round_unit_caps": [115, 95, 95, 115],
        "over_length_ratio": "3/2",
        "repair_feedback_version": "repair_feedback_v2",
    }
    context = replace(
        _v4_context(round_no, language, frozen_llm=frozen),
        round_unit_caps=(115, 95, 95, 115),
    )
    snap = _snapshot(context)
    assert snap.task is not None
    assert snap.task["max_units"] == cap or round_no != 2
    return snap


def test_over_length_han_speech_is_force_fitted_after_repair_budget() -> None:
    """~311 Han chars vs cap 95 / hard 142: final attempt trims, never fails."""

    snapshot = _v5_snapshot()
    cap = int(snapshot.task["max_units"])  # type: ignore[index]
    hard = over_length_limit(cap, Fraction(3, 2))
    long = "这是一段远远超过上限的反驳发言内容，用来模拟生产环境中模型一次写出三百多字的情况。" * 8
    assert speech_units(long, "zh") > hard
    with pytest.raises(SegmentProtocolError) as first:
        validate_segment_output(_output(long), snapshot)
    assert first.value.code == "segment_over_length"
    accepted = validate_segment_output(_output(long), snapshot, repairable=False)
    assert accepted.speech.strip()
    assert speech_units(accepted.speech, "zh") <= hard
    assert accepted.salvage_warning == SEGMENT_OUTPUT_SALVAGED


def test_empty_segment_with_question_text_is_moved_into_speech() -> None:
    """Repair put the speech in question and left segments[0].text empty."""

    snapshot = _v5_snapshot()
    speech = (
        "我认为开场发言忽略了课堂注意力的代价。"
        "证据显示分心会降低练习质量。"
        "因此我不同意那个开场立场。"
        "EGG Sample，你如何回应注意力方面的证据？"
    )
    malformed = {
        "segments": [
            {
                "text": "",
                "source_ids": [],
                "reply_to": None,
                "support_mode": "no_match",
            }
        ],
        "question": {
            "target_agent_id": snapshot.discussion["question_target_id"],  # type: ignore[index]
            "text": speech,
        },
        "discussion_memory": None,
    }
    with pytest.raises(SegmentProtocolError) as first:
        # First attempt still asks for a rewrite when soft rules fail; empty
        # text after normalize may pass or hit length — either way salvage works.
        validate_segment_output({"segments": []}, snapshot)
    assert first.value.code == "segment_count_invalid"
    accepted = salvage_segment_output(malformed, snapshot)
    assert accepted.speech.strip()
    assert "注意力" in accepted.speech
    assert accepted.salvage_warning == SEGMENT_OUTPUT_SALVAGED
    assert accepted.question is not None


def test_runtime_salvages_failed_second_attempt_and_succeeds() -> None:
    """Attempt 2 empty segments used to fail the turn; now salvage continues."""

    frozen = snapshot()
    provider = OfflineAdapter([{"segments": []}, {"segments": []}])
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=4,
            max_total_tokens=200_000,
            max_cost_cny=5,
            budget_bucket="llm_debate_turn",
        )
    )
    runtime = SegmentLLMRuntime(ledger=ledger, adapter=provider)
    prepared = runtime.prepare(
        frozen,
        debate_id="debate-1",
        turn_id="turn-1",
        policy_hash="a" * 64,
        manifest_hash="b" * 64,
        build_manifest_hash="c" * 64,
    )
    result = runtime.run(prepared, context=opening_context(), confirmed=True)
    assert result.status == "succeeded"
    assert result.final_ready is not None
    assert result.final_ready.speech.strip()
    assert result.safe_error_code == SEGMENT_OUTPUT_SALVAGED
    assert len(provider.requests) == 2


def test_structured_request_clamps_hot_temperature_and_huge_max_tokens() -> None:
    fields = structured_segment_request_fields(
        {"temperature": 1.8, "max_tokens": 33510, "top_p": 0.8},
        unit_cap=95,
    )
    assert fields["temperature"] == STRUCTURED_SEGMENT_TEMPERATURE_MAX
    assert fields["max_tokens"] <= 2048
    assert fields["max_tokens"] >= 256


def test_salvage_keeps_usable_speech_when_provider_returns_only_question() -> None:
    snapshot = _v5_snapshot(round_no=2, language="en", cap=95)
    # Round-2 en snapshot may use a different computed cap; read it.
    cap = int(snapshot.task["max_units"])  # type: ignore[index]
    hard = over_length_limit(cap, Fraction(3, 2))
    body = " ".join(["word"] * (hard + 40))
    question = "Would you still defend that opening claim?"
    malformed = {
        "segments": [
            {
                "text": "   ",
                "source_ids": [],
                "reply_to": None,
                "support_mode": "no_match",
            }
        ],
        "question": {
            "target_agent_id": snapshot.discussion["question_target_id"],  # type: ignore[index]
            "text": f"{body} {question}",
        },
        "discussion_memory": None,
    }
    accepted = salvage_segment_output(malformed, snapshot)
    assert speech_units(accepted.speech, "en") <= hard
    assert accepted.speech.strip()
    assert accepted.salvage_warning == SEGMENT_OUTPUT_SALVAGED
