"""Deterministic contrasting-Persona Mock behavior and comparison helpers.

The Mock is deliberately a teaching acceptance fixture, not a language model.
It changes only the six allowed Persona teaching dimensions.  Topic, stance,
evidence ID order, rule set and output schema are held constant so tests can
attribute the response difference to the confirmed Persona itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.agents.persona import (
    PersonaSpecV1,
    compile_persona_or_raise,
)

MOCK_PERSONA_SCHEMA_VERSION: Literal["persona_mock_response_v1"] = "persona_mock_response_v1"
MOCK_PERSONA_RULE_SET_ID = "persona_mock_teaching_v1"
TEACHING_DIMENSIONS = (
    "tone",
    "value_priority",
    "argument_pattern",
    "concession_style",
    "question_style",
    "debate_strategy",
)
TeachingDimension = Literal[
    "tone",
    "value_priority",
    "argument_pattern",
    "concession_style",
    "question_style",
    "debate_strategy",
]


class MockPersonaModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MockTeachingDimensions(MockPersonaModel):
    tone: str
    value_priority: str
    argument_pattern: str
    concession_style: str
    question_style: str
    debate_strategy: str


class MockPersonaResponse(MockPersonaModel):
    schema_version: Literal["persona_mock_response_v1"] = MOCK_PERSONA_SCHEMA_VERSION
    stance: str = "open"
    speech: str = Field(min_length=1)
    position_summary: str = Field(min_length=1)
    teaching_dimensions: MockTeachingDimensions
    evidence_ids: tuple[str, ...] = ()
    rule_set_id: str = MOCK_PERSONA_RULE_SET_ID
    seed: int

    @property
    def source_order(self) -> tuple[str, ...]:
        """Alias used by comparison screens for the unchanged receipt order."""

        return self.evidence_ids


class MockPersonaComparison(MockPersonaModel):
    first: MockPersonaResponse
    second: MockPersonaResponse
    changed_dimensions: tuple[TeachingDimension, ...]
    evidence_ids_equal: bool
    source_order_equal: bool
    rule_set_equal: bool
    schema_equal: bool

    @property
    def all_invariants_equal(self) -> bool:
        return (
            self.evidence_ids_equal
            and self.source_order_equal
            and self.rule_set_equal
            and self.schema_equal
        )


def mock_persona_response(
    persona: PersonaSpecV1,
    *,
    topic: str,
    evidence_ids: Iterable[str] = (),
    stance: str = "open",
    seed: int = 0,
) -> MockPersonaResponse:
    """Render a stable response whose only variable teaching inputs are Persona fields."""

    if not topic.strip():
        raise ValueError("topic must not be empty")
    if not stance.strip():
        raise ValueError("stance must not be empty")
    ordered_evidence = tuple(evidence_ids)
    dimensions = MockTeachingDimensions(
        tone=persona.speaking_style.tone,
        value_priority=persona.core_values[0],
        argument_pattern=persona.speaking_style.argument_pattern,
        concession_style=persona.speaking_style.concession_style,
        question_style=persona.speaking_style.question_style,
        debate_strategy=persona.debate_strategy[0],
    )
    openings = (
        "I begin by locating the question in its wider context.",
        "I begin by naming the practical choice before us.",
        "I begin by making the underlying responsibility explicit.",
        "I begin by separating what is known from what is valued.",
    )
    opening = openings[abs(seed) % len(openings)]
    grounding = (
        f"I draw on the supplied evidence in its fixed order ({len(ordered_evidence)} item(s))."
        if ordered_evidence
        else "I have no matching evidence, so this is general reasoning."
    )
    speech = (
        f"{opening} My tone is {dimensions.tone}. On {topic.strip()}, I prioritize "
        f"{dimensions.value_priority}. {persona.initial_position} "
        f"I use this argument pattern: {dimensions.argument_pattern}. "
        f"When another view is reasonable, I {dimensions.concession_style}. "
        f"My debate strategy is to {dimensions.debate_strategy}. "
        f"I ask questions in this way: {dimensions.question_style}. {grounding}"
    )
    return MockPersonaResponse(
        stance=stance,
        speech=speech,
        position_summary=persona.initial_position,
        teaching_dimensions=dimensions,
        evidence_ids=ordered_evidence,
        rule_set_id=MOCK_PERSONA_RULE_SET_ID,
        seed=seed,
    )


def compare_personas(
    first: PersonaSpecV1,
    second: PersonaSpecV1,
    *,
    topic: str,
    evidence_ids: Iterable[str] = (),
    stance: str = "open",
    seed: int = 0,
) -> MockPersonaComparison:
    """Compare two Personas with exactly the same non-Persona request inputs."""

    first_response = mock_persona_response(
        first,
        topic=topic,
        evidence_ids=evidence_ids,
        stance=stance,
        seed=seed,
    )
    second_response = mock_persona_response(
        second,
        topic=topic,
        evidence_ids=first_response.evidence_ids,
        stance=first_response.stance,
        seed=seed,
    )
    changed: list[TeachingDimension] = []
    first_dimensions = first_response.teaching_dimensions.model_dump()
    second_dimensions = second_response.teaching_dimensions.model_dump()
    for dimension in TEACHING_DIMENSIONS:
        if first_dimensions[dimension] != second_dimensions[dimension]:
            changed.append(dimension)  # type: ignore[arg-type]
    return MockPersonaComparison(
        first=first_response,
        second=second_response,
        changed_dimensions=tuple(changed),
        evidence_ids_equal=first_response.evidence_ids == second_response.evidence_ids,
        source_order_equal=first_response.source_order == second_response.source_order,
        rule_set_equal=first_response.rule_set_id == second_response.rule_set_id,
        schema_equal=first_response.schema_version == second_response.schema_version,
    )


def contrasting_persona_fixtures() -> tuple[PersonaSpecV1, PersonaSpecV1]:
    """Return two valid deterministic fixtures differing in all six dimensions."""

    first = compile_persona_or_raise(
        """# River Keeper

## Identity

- Role: Watershed steward
- Historical or cultural context: A fictional community keeper of shared water memory.

## Cultural lens

- Intergenerational responsibility

## Core values

- Reciprocity
- Patience

## Initial position

Protect shared resources through careful, long-term stewardship.

## Speaking style

- Tone: Calm and reflective
- Argument pattern: Start with context, then weigh consequences
- Concession style: Acknowledge valid concerns before qualifying them
- Question style: Ask one open question about long-term effects

## Debate strategy

- Connect present choices to future stewardship

## Boundaries

- Do not claim evidence outside the snapshot
""",
        expected_name="River Keeper",
    )
    second = compile_persona_or_raise(
        """# Market Steward

## Identity

- Role: Community market planner
- Historical or cultural context: A fictional town planner balancing exchange and access.

## Cultural lens

- Practical reciprocity

## Core values

- Adaptability
- Opportunity

## Initial position

Prefer workable experiments that widen access while measuring their consequences.

## Speaking style

- Tone: Direct and energetic
- Argument pattern: State the choice, compare options, then propose a test
- Concession style: Name the strongest objection and adapt the proposal
- Question style: Ask a focused question about measurable results

## Debate strategy

- Turn disagreement into a reversible practical experiment

## Boundaries

- Do not present a proposal as a measured fact
""",
        expected_name="Market Steward",
    )
    return first, second


def compare_contrasting_personas(
    *,
    topic: str = "How should a community share a scarce resource?",
    evidence_ids: Iterable[str] = ("receipt-a", "receipt-b"),
    stance: str = "open",
    seed: int = 7,
) -> MockPersonaComparison:
    first, second = contrasting_persona_fixtures()
    return compare_personas(
        first,
        second,
        topic=topic,
        evidence_ids=evidence_ids,
        stance=stance,
        seed=seed,
    )


# Explicit aliases keep call sites readable while preserving one implementation.
mock_persona_comparison = compare_personas
compare_persona_responses = compare_personas


__all__ = [
    "MOCK_PERSONA_RULE_SET_ID",
    "MOCK_PERSONA_SCHEMA_VERSION",
    "TEACHING_DIMENSIONS",
    "MockPersonaComparison",
    "MockPersonaModel",
    "MockPersonaResponse",
    "MockTeachingDimensions",
    "TeachingDimension",
    "compare_contrasting_personas",
    "compare_persona_responses",
    "compare_personas",
    "contrasting_persona_fixtures",
    "mock_persona_comparison",
    "mock_persona_response",
]
