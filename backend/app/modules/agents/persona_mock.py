"""Deterministic contrasting-Persona Mock behavior and comparison helpers.

The Mock is deliberately a teaching acceptance fixture, not a language model.
It changes only the six allowed Persona teaching dimensions.  Topic, stance,
evidence ID order, rule set and output schema are held constant so tests can
attribute the response difference to the confirmed Persona itself.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.agents.persona import (
    PersonaProviderViewV1,
    PersonaSpecV1,
    compile_persona_or_raise,
)
from app.modules.debates.generation.validator import has_explicit_source_claim

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
# The Persona compiler deliberately accepts rich authored fields (up to 240
# characters for style/list items).  Those fields are useful in the provider
# view, but should not be pasted wholesale into a bounded classroom sentence.
# Keep this limit in the Mock projection rather than weakening the Persona
# compiler or turn validator.  The projection uses word boundaries and emits a
# complete, explicitly-labelled sentence for every dimension.
SPEECH_DIMENSION_WORD_LIMIT = 8
# Numeric tokens are intentionally excluded from the speech projection.  The
# authoritative validator treats numbers as concrete factual claims, while a
# Persona style/value is not evidence.  Keeping only alphabetic words avoids
# turning an authored label such as ``method-2`` into an unsupported fact.
_SPEECH_WORD_RE = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*")
TeachingDimension = Literal[
    "tone",
    "value_priority",
    "argument_pattern",
    "concession_style",
    "question_style",
    "debate_strategy",
]
type PersonaInput = PersonaSpecV1 | PersonaProviderViewV1


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
    persona: PersonaInput,
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
    dimensions = teaching_dimensions_for_persona(persona)
    speech_dimensions = bounded_teaching_dimensions_for_persona(persona)
    speech = (
        f"{opening} On {topic.strip()}, {speech_dimensions.value_priority_sentence} "
        f"{speech_dimensions.tone_sentence} "
        f"{speech_dimensions.argument_pattern_sentence} "
        f"{speech_dimensions.concession_style_sentence} "
        f"{speech_dimensions.debate_strategy_sentence} "
        f"{speech_dimensions.question_style_sentence} {grounding}"
    )
    return MockPersonaResponse(
        stance=stance,
        speech=speech,
        position_summary=(
            f"Prioritize {dimensions.value_priority} by applying {dimensions.debate_strategy}."
        ),
        teaching_dimensions=dimensions,
        evidence_ids=ordered_evidence,
        rule_set_id=MOCK_PERSONA_RULE_SET_ID,
        seed=seed,
    )


def teaching_dimensions_for_persona(persona: PersonaInput) -> MockTeachingDimensions:
    """Project exactly the six allowed teaching dimensions for the Mock.

    Identity, cultural context, boundaries, hashes and other audit fields are
    intentionally excluded.  This same projection is used by the direct
    acceptance helper and by the actual ``MockLLMProvider`` path.
    """

    return MockTeachingDimensions(
        tone=persona.speaking_style.tone,
        value_priority=persona.core_values[0],
        argument_pattern=persona.speaking_style.argument_pattern,
        concession_style=persona.speaking_style.concession_style,
        question_style=persona.speaking_style.question_style,
        debate_strategy=persona.debate_strategy[0],
    )


class MockSpeechTeachingDimensions(MockPersonaModel):
    """Bounded, sentence-complete projection used inside Mock speech.

    ``MockTeachingDimensions`` remains the full six-dimension comparison
    projection.  This separate DTO makes the lossy boundary explicit: raw
    Persona values stay available to the structured comparison/UI, while
    generated speech receives only short complete sentences.  No hash,
    identity metadata, or private authored field is added to the speech.
    """

    tone_sentence: str
    value_priority_sentence: str
    argument_pattern_sentence: str
    concession_style_sentence: str
    question_style_sentence: str
    debate_strategy_sentence: str


def bounded_dimension_sentence(label: str, value: str) -> str:
    """Return one bounded, complete sentence for a teaching dimension.

    Short values are preserved verbatim (apart from surrounding whitespace and
    terminal punctuation), so the normal contrasting fixtures remain directly
    observable.  Longer values preserve opening, middle and closing words
    inside one compact sentence rather than cutting at an arbitrary character
    or hiding the internal distinction in a non-classroom field.
    """

    normalized = " ".join(value.split()).strip()
    if not normalized:
        raise ValueError("a teaching dimension cannot be empty")
    words = _SPEECH_WORD_RE.findall(normalized)
    # A valid Persona value may contain punctuation, separators or numerals
    # that do not belong in a source-bearing classroom claim.  Project from a
    # conservative alphabetic token shape so legal authored values cannot
    # overflow the 80-200 word contract or manufacture a numeric citation.
    if words and len(words) <= SPEECH_DIMENSION_WORD_LIMIT and not re.search(r"\d", normalized):
        visible = normalized.rstrip(".!?")
        return _source_neutral_sentence(label, f"My {label} is {visible}.")
    if not words:
        return f"My teaching {label} remains bounded by the authored Persona."

    # Two opening, middle and closing words keep the complete labelled
    # sentence compact while ensuring a long value's internal distinction is
    # visible.  This avoids the old first/last-only collision boundary.
    opening = " ".join(words[:2])
    middle_start = max(0, (len(words) // 2) - 1)
    middle = " ".join(words[middle_start : middle_start + 2])
    closing = " ".join(words[-2:])
    sentence = f'My {label} balances "{opening}" with "{middle}" and "{closing}".'
    return _source_neutral_sentence(label, sentence)


def _source_neutral_sentence(label: str, sentence: str) -> str:
    """Keep arbitrary Persona prose from looking like sourced fact.

    The validator's public source-claim predicate is the single source of
    truth here.  If a legal authored dimension happens to contain an
    attribution, quantity, URL or filename pattern, replace that *rendered
    sentence* with an honest authored-perspective sentence.  This is a
    semantic boundary, not a hand-maintained list of trigger words, and it
    never invents a receipt.
    """

    if has_explicit_source_claim(sentence):
        return f"My {label} reflects a bounded authored perspective."
    return sentence


def bounded_teaching_dimensions_for_persona(
    persona: PersonaInput,
) -> MockSpeechTeachingDimensions:
    """Project the six allowed dimensions into bounded complete sentences."""

    dimensions = teaching_dimensions_for_persona(persona)
    return MockSpeechTeachingDimensions(
        tone_sentence=bounded_dimension_sentence("tone", dimensions.tone),
        value_priority_sentence=bounded_dimension_sentence(
            "value priority", dimensions.value_priority
        ),
        argument_pattern_sentence=bounded_dimension_sentence(
            "argument pattern", dimensions.argument_pattern
        ),
        concession_style_sentence=bounded_dimension_sentence(
            "concession style", dimensions.concession_style
        ),
        question_style_sentence=bounded_dimension_sentence(
            "question style", dimensions.question_style
        ),
        debate_strategy_sentence=bounded_dimension_sentence(
            "debate strategy", dimensions.debate_strategy
        ),
    )


def compare_personas(
    first: PersonaInput,
    second: PersonaInput,
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
    "SPEECH_DIMENSION_WORD_LIMIT",
    "TEACHING_DIMENSIONS",
    "MockPersonaComparison",
    "MockPersonaModel",
    "MockPersonaResponse",
    "MockSpeechTeachingDimensions",
    "MockTeachingDimensions",
    "TeachingDimension",
    "compare_contrasting_personas",
    "compare_persona_responses",
    "compare_personas",
    "contrasting_persona_fixtures",
    "bounded_dimension_sentence",
    "bounded_teaching_dimensions_for_persona",
    "mock_persona_comparison",
    "mock_persona_response",
    "teaching_dimensions_for_persona",
]
