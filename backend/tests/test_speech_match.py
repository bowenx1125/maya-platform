"""A claim must be something the speaker said; presentation is not the test."""

from __future__ import annotations

import pytest
from app.modules.debates.generation.speech_match import (
    find_claim_span,
    speech_contains_claim,
)

SPEECH = (
    "A city owes its river care—always.  The river's banks hold what we\n"
    "put behind them. We can subtract a rule instead of adding one… slowly."
)


@pytest.mark.parametrize(
    "claim",
    [
        pytest.param("A city owes its river care—always.", id="exact"),
        pytest.param("A city owes its river care-always.", id="hyphen-for-em-dash"),
        pytest.param("The river’s banks hold what we put behind them.", id="curly-apostrophe"),
        pytest.param("The river's banks hold what we  put   behind them.", id="extra-spaces"),
        pytest.param("A CITY OWES ITS RIVER CARE—ALWAYS.", id="case"),
        pytest.param(
            "We can subtract a rule instead of adding one... slowly.", id="dotted-ellipsis"
        ),
    ],
)
def test_presentation_never_costs_a_turn(claim: str) -> None:
    """Each of these is the same sentence, and each used to be rejected."""

    assert speech_contains_claim(SPEECH, claim)


@pytest.mark.parametrize(
    "claim",
    [
        pytest.param("A city owes its river nothing.", id="different-word"),
        pytest.param("A city owes care.", id="words-removed"),
        pytest.param("Its river a city owes care always.", id="reordered"),
        pytest.param("A town owes its river care—always.", id="synonym"),
        pytest.param("", id="empty"),
    ],
)
def test_a_different_sentence_is_still_rejected(claim: str) -> None:
    """Forgiving presentation must not become forgiving paraphrase.

    The whole point of the rule is that a report never cites a sentence nobody
    spoke, so anything that changes, drops or reorders a word still fails.
    """

    assert not speech_contains_claim(SPEECH, claim)


def test_a_repeated_sentence_resolves_to_its_first_occurrence() -> None:
    speech = "Care is owed. Care is owed."
    assert find_claim_span(speech, "Care is owed.") == (0, 13)


def test_offsets_point_into_the_original_speech() -> None:
    """The trace highlights the claim inside the speech, so offsets must be real."""

    span = find_claim_span(SPEECH, "The river’s banks hold what we put behind them.")
    assert span is not None
    start, end = span
    # Sliced out of the untouched speech, not out of a normalised copy.
    assert SPEECH[start:end].startswith("The river's banks")
    assert SPEECH[start:end].endswith("behind them.")


def test_a_claim_longer_than_the_speech_cannot_match() -> None:
    assert find_claim_span("Short.", "Short. And a great deal more besides.") is None
