"""Third-pass Persona Mock collision and source-neutrality regressions."""

from __future__ import annotations

import pytest
from app.modules.agents.persona import PersonaSpecV1, persona_spec_hash
from app.modules.agents.persona_mock import (
    TEACHING_DIMENSIONS,
    bounded_teaching_dimensions_for_persona,
)
from app.modules.debates.generation import (
    FinalReadyTurn,
    GenerationContext,
    KeyClaimV1,
    MutualLearningPolicy,
    MutualLearningTurnResultV1,
    ParticipantContext,
    ProviderPromptV1,
    SnapshotRetrievalReceipt,
    TurnQuestion,
    build_provider_prompt,
    count_turn_words,
    has_explicit_source_claim,
)
from app.providers.llm import MockLLMProvider

from tests.test_wave4_persona_p1_round2 import (
    _EVIDENCE_TEXT,
    _generate_three_protocol_phases,
    _persona,
)

_DIMENSION_FIELDS = TEACHING_DIMENSIONS


def _collision_value(marker: str) -> str:
    """Long value with identical edges and an intentionally varied center."""

    return (
        "shared opening descriptor alpha beta "
        f"{marker} gamma delta "
        "shared closing descriptor omega"
    )


def _with_dimension(persona: PersonaSpecV1, field: str, value: str) -> PersonaSpecV1:
    if field == "value_priority":
        return persona.model_copy(update={"core_values": (value, *persona.core_values[1:])})
    if field == "debate_strategy":
        return persona.model_copy(
            update={"debate_strategy": (value, *persona.debate_strategy[1:])}
        )
    if field in {"tone", "argument_pattern", "concession_style", "question_style"}:
        style = persona.speaking_style.model_copy(update={field: value})
        return persona.model_copy(update={"speaking_style": style})
    raise AssertionError(f"unknown teaching dimension: {field}")


def _participants(persona: PersonaSpecV1) -> tuple[ParticipantContext, ...]:
    other = _persona()
    return tuple(
        ParticipantContext(
            participant_id=f"participant-{index}",
            agent_id=f"agent-{index}",
            agent_name=f"Expert {index}",
            slot=chr(65 + index),
            order_index=index,
            snapshot_id="snapshot-shared",
            persona=current,
            persona_spec_hash=persona_spec_hash(current),
        )
        for index, current in enumerate((persona, other))
    )


def _predecessor(
    *,
    turn_id: str,
    participant_id: str,
    round_no: int,
    turn_index: int,
) -> FinalReadyTurn:
    speech = (
        f"Earlier public speech {turn_id} identifies a responsible proposal. "
        "It leaves local effects and practical safeguards open for review."
    )
    structured = MutualLearningTurnResultV1(
        speech=speech,
        key_claims=[
            KeyClaimV1(
                claim_id=f"{turn_id}:claim",
                claim_text="Earlier public speech identifies a responsible proposal.",
                claim_type="proposal",
            )
        ],
        position_summary="A responsible public position.",
        remaining_uncertainty=["Local effects remain uncertain."],
        question=TurnQuestion(type="none"),
    )
    return FinalReadyTurn(
        turn_id=turn_id,
        participant_id=participant_id,
        snapshot_id="snapshot-shared",
        round_no=round_no,
        turn_index=turn_index,
        speech=speech,
        structured=structured,
        retrieval_status="no_match",
        grounding_mode="general_reasoning",
        used_receipts=(),
        predecessor_turn_ids=(),
        cutoff_turn_index=-1,
        transcript_hash="prior",
        attempt=1,
    )


def _prompt_for_phase(
    persona: PersonaSpecV1,
    *,
    phase_index: int,
) -> ProviderPromptV1:
    people = _participants(persona)
    plans = MutualLearningPolicy().plan(people, round_count=3)
    if phase_index == 0:
        predecessors: tuple[FinalReadyTurn, ...] = ()
    elif phase_index == 2:
        predecessors = (
            _predecessor(
                turn_id="turn-0", participant_id="participant-0", round_no=1, turn_index=0
            ),
            _predecessor(
                turn_id="turn-1", participant_id="participant-1", round_no=1, turn_index=1
            ),
        )
    else:
        predecessors = tuple(
            _predecessor(
                turn_id=f"turn-{index}",
                participant_id=f"participant-{index % 2}",
                round_no=1 if index < 2 else 2,
                turn_index=index,
            )
            for index in range(4)
        )
    return build_provider_prompt(
        GenerationContext(
            debate_id="collision-debate",
            topic="How should a community share a scarce resource?",
            turn=plans[phase_index],
            participant=people[0],
            participants=people,
            predecessors=predecessors,
        ),
        persona=persona,
        receipts=(
            SnapshotRetrievalReceipt(
                snapshot_id="snapshot-shared",
                query_kind="viewpoint",
                query_hash="query-hash",
                threshold_key="strict",
                rank=1,
                score=1.0,
                chunk_id="chunk-shared",
                source_filename="assigned-evidence.md",
                text=_EVIDENCE_TEXT,
                evidence_id="receipt-shared",
            ),
        ),
        queries=(),
    )


@pytest.mark.parametrize("dimension", _DIMENSION_FIELDS)
@pytest.mark.parametrize("phase_index", (0, 2, 4))
def test_middle_only_dimension_changes_reach_actual_provider_mock(
    dimension: str,
    phase_index: int,
) -> None:
    first = _with_dimension(_persona(), dimension, _collision_value("middle cedar"))
    second = _with_dimension(_persona(), dimension, _collision_value("middle market"))
    first_prompt = _prompt_for_phase(first, phase_index=phase_index)
    second_prompt = _prompt_for_phase(second, phase_index=phase_index)
    first_result = MockLLMProvider().generate_turn(first_prompt)
    second_result = MockLLMProvider().generate_turn(second_prompt)

    assert isinstance(first_result, MutualLearningTurnResultV1)
    assert isinstance(second_result, MutualLearningTurnResultV1)
    assert first_result.speech != second_result.speech
    assert first_result.model_dump() != second_result.model_dump()
    assert first_result.evidence_trace_claims
    assert second_result.evidence_trace_claims
    assert first_result.speech.endswith(".")
    assert second_result.speech.endswith(".")
    assert 80 <= count_turn_words(first_result.speech) <= 190
    assert 80 <= count_turn_words(second_result.speech) <= 190
    first_projection = bounded_teaching_dimensions_for_persona(first)
    second_projection = bounded_teaching_dimensions_for_persona(second)
    assert first_projection.model_dump()[f"{dimension}_sentence"] != second_projection.model_dump()[
        f"{dimension}_sentence"
    ]
    assert first_projection.model_dump()[f"{dimension}_sentence"] in first_result.speech
    assert second_projection.model_dump()[f"{dimension}_sentence"] in second_result.speech
    assert first_result.used_evidence_id == second_result.used_evidence_id == ["receipt-shared"]
    assert first_prompt.request.rule_set_id == second_prompt.request.rule_set_id
    assert first_prompt.request.output_schema_id == second_prompt.request.output_schema_id
    assert first_prompt.request.evidence_catalog == second_prompt.request.evidence_catalog


_SOURCE_NEUTRAL_VALUES = (
    "according to this account",
    "A study reported the result",
    "An expert found the result",
    "A survey showed the result",
    "Research indicates the result",
    "two out of ten people",
    "two hundred users",
    "a dozen users",
    "42 percent",
    "https://example.com/report.pdf",
    "assigned-source.md",
    "source: report.pdf",
    "several reports showed the result",
    "This evidence says the result",
    "Based on the research data",
    "The assigned source is relevant",
)


@pytest.mark.parametrize("dimension", _DIMENSION_FIELDS)
@pytest.mark.parametrize("source_value", _SOURCE_NEUTRAL_VALUES)
def test_current_validator_source_patterns_are_neutralized_in_all_phases(
    dimension: str,
    source_value: str,
) -> None:
    candidate = f"My tone is {source_value}."
    assert has_explicit_source_claim(candidate), source_value
    persona = _with_dimension(_persona(), dimension, source_value)
    projection = bounded_teaching_dimensions_for_persona(persona)
    for sentence in projection.model_dump().values():
        assert isinstance(sentence, str)
        assert not has_explicit_source_claim(sentence)
    results = _generate_three_protocol_phases(persona)
    for result in results:
        assert 80 <= count_turn_words(result.speech) <= 190
        assert result.speech.strip().endswith(".")
        assert result.evidence_trace
        assert not has_explicit_source_claim(result.speech)
        assert isinstance(result.structured, MutualLearningTurnResultV1)
        assert result.structured.speech == result.speech
        assert result.structured.used_evidence_ids == (result.used_receipts[0].evidence_id,)
        assert all(
            not has_explicit_source_claim(row["claim_text"]) for row in result.evidence_trace
        )
