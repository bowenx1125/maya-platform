"""Real-Core Demo regressions for English-safe Persona and receipt projections."""

from __future__ import annotations

import re

import pytest
from app.modules.agents.persona import PersonaSpeakingStyle, PersonaSpecV1
from app.modules.agents.persona_mock import (
    TEACHING_DIMENSIONS,
    bounded_dimension_sentence,
    bounded_teaching_dimensions_for_persona,
    mock_persona_response,
    position_summary_for_persona,
)
from app.modules.debates.generation import MutualLearningTurnResultV1, count_turn_words

from tests.test_wave4_persona_p1_round2 import (
    _EVIDENCE_TEXT,
    _generate_three_protocol_phases,
    _persona,
)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _with_dimensions(
    persona: PersonaSpecV1,
    *,
    mixed: bool,
) -> PersonaSpecV1:
    marker = "Chinese value 价值" if mixed else "价值优先"
    strategy = "future stewardship 与照护" if mixed else "连接未来照护"
    style = PersonaSpeakingStyle(
        tone="Calm and 沉稳" if mixed else "沉稳而反思",
        argument_pattern="Start with context 然后权衡后果" if mixed else "先说明背景，再权衡后果",
        concession_style=(
            "Acknowledge valid concerns 之后再 уточнить" if mixed else "先承认合理顾虑，再作限定"
        ),
        question_style="Ask one focused question 关于长期影响"
        if mixed
        else "询问一个关于长期影响的问题",
    )
    return persona.model_copy(
        update={
            "core_values": (marker, persona.core_values[1]),
            "speaking_style": style,
            "debate_strategy": (strategy,),
        }
    )


@pytest.mark.parametrize("mixed", (False, True))
def test_cjk_and_mixed_persona_fields_have_fixed_english_speech_fallback(
    mixed: bool,
) -> None:
    persona = _with_dimensions(_persona(), mixed=mixed)
    projection = bounded_teaching_dimensions_for_persona(persona)

    assert all(not _CJK_RE.search(value) for value in projection.model_dump().values())
    assert all(
        value
        == "My teaching " + label.replace("_", " ") + " remains bounded by the authored Persona."
        for label, value in zip(TEACHING_DIMENSIONS, projection.model_dump().values(), strict=True)
    )
    assert position_summary_for_persona(persona) == (
        "Prioritize the authored value priority by applying the authored debate strategy."
    )


@pytest.mark.parametrize("dimension", TEACHING_DIMENSIONS)
def test_each_cjk_teaching_dimension_uses_field_level_fallback(dimension: str) -> None:
    persona = _persona()
    if dimension == "value_priority":
        persona = persona.model_copy(update={"core_values": ("价值", *persona.core_values[1:])})
    elif dimension == "debate_strategy":
        persona = persona.model_copy(update={"debate_strategy": ("连接未来",)})
    else:
        persona = persona.model_copy(
            update={
                "speaking_style": persona.speaking_style.model_copy(update={dimension: "中文风格"})
            }
        )
    projection = bounded_teaching_dimensions_for_persona(persona)
    field = f"{dimension}_sentence"
    assert getattr(projection, field) == (
        "My teaching " + dimension.replace("_", " ") + " remains bounded by the authored Persona."
    )


@pytest.mark.parametrize("mixed", (False, True))
def test_actual_mock_strict_opening_exchange_final_is_english_and_traceable(
    mixed: bool,
) -> None:
    persona = _with_dimensions(_persona(), mixed=mixed)
    results = _generate_three_protocol_phases(persona, evidence_text=_EVIDENCE_TEXT)

    assert len(results) == 3
    for result in results:
        assert isinstance(result.structured, MutualLearningTurnResultV1)
        assert not _CJK_RE.search(result.speech)
        assert not _CJK_RE.search(result.structured.position_summary)
        assert 80 <= count_turn_words(result.speech) <= 200
        assert result.speech.strip().endswith(".")
        assert result.used_receipts
        receipt = result.used_receipts[0]
        assert result.structured.used_evidence_id == [receipt.evidence_id]
        assert result.structured.used_evidence_ids == (receipt.evidence_id,)
        assert result.public_sources[0].source_filename == receipt.source_filename
        assert result.public_sources[0].chunk_id == receipt.chunk_id
        assert result.public_sources[0].evidence_id == receipt.evidence_id
        assert result.public_sources[0].rank == receipt.rank
        assert result.public_sources[0].score == receipt.score
        direct = [row for row in result.evidence_trace if row["evidence_id"] == receipt.evidence_id]
        assert len(direct) == 1
        assert direct[0]["support_mode"] == "direct"
        assert direct[0]["chunk_id"] == receipt.chunk_id
        assert direct[0]["source_filename"] == receipt.source_filename
        assert all(row["turn_id"] == result.turn_id for row in result.evidence_trace)


@pytest.mark.parametrize("phase_index", (0, 1, 2))
def test_cjk_receipt_is_not_quoted_or_translated_in_any_strict_phase(
    phase_index: int,
) -> None:
    results = _generate_three_protocol_phases(
        _persona(),
        evidence_text="社区传统强调照护与共享资源，并记录了当地参与者的经验。",
    )
    result = results[phase_index]
    receipt = result.used_receipts[0]
    assert not _CJK_RE.search(result.speech)
    assert "A matching passage was retrieved from the current snapshot." in result.speech
    assert "社区传统" not in result.speech
    assert result.structured.position_summary
    assert not _CJK_RE.search(result.structured.position_summary)
    assert result.structured.used_evidence_id == [receipt.evidence_id]
    assert result.public_sources[0].chunk_id == receipt.chunk_id
    trace = next(row for row in result.evidence_trace if row["evidence_id"] == receipt.evidence_id)
    assert trace["support_mode"] == "direct"
    assert trace["chunk_id"] == receipt.chunk_id
    assert trace["source_filename"] == receipt.source_filename


def test_direct_mock_persona_response_keeps_raw_dimensions_out_of_position_summary() -> None:
    persona = _with_dimensions(_persona(), mixed=False)
    response = mock_persona_response(
        persona,
        topic="How should a community share a scarce resource?",
        evidence_ids=("receipt-a",),
    )
    assert not _CJK_RE.search(response.position_summary)
    assert response.teaching_dimensions.value_priority == "价值优先"
    assert response.teaching_dimensions.debate_strategy == "连接未来照护"


def test_bounded_dimension_sentence_does_not_translate_or_partially_copy_cjk() -> None:
    value = "先说明背景，再权衡后果"
    sentence = bounded_dimension_sentence("argument pattern", value)
    assert sentence == "My teaching argument pattern remains bounded by the authored Persona."
    assert not _CJK_RE.search(sentence)
