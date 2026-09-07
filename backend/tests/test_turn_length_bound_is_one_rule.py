"""The per-turn length bound must exist in exactly one place.

It used to exist in three: the generation validator's default arguments, the
sentence of the prompt that states the rule, and a second literal pair inside
the playback layer. Widening the first two and missing the third meant a speech
the validator had accepted was rejected after generation — and rejected with a
bare `ValueError` carrying no safe code, so the turn simply stopped, no status
changed, and the lesson waited on a failure nobody could see.

These tests fail if the bound is ever written down twice again.
"""

from __future__ import annotations

import inspect

from app.modules.debates.generation.mutual_learning_prompts import (
    MUTUAL_LEARNING_PLATFORM_RULES,
)
from app.modules.debates.generation.mutual_learning_validator import (
    MutualLearningValidator,
)
from app.modules.debates.output_language import TURN_MAX_WORDS, TURN_MIN_WORDS
from app.modules.debates.playback._preparation import PlaybackPreparationMixin


def test_the_validator_defaults_to_the_shared_bound() -> None:
    validator = MutualLearningValidator()
    assert (validator.min_words, validator.max_words) == (
        TURN_MIN_WORDS,
        TURN_MAX_WORDS,
    )


def test_the_prompt_states_the_bound_it_is_measured_against() -> None:
    """A rule the server enforces and the prompt misstates is unanswerable."""

    stated = [rule for rule in MUTUAL_LEARNING_PLATFORM_RULES if "REQUIREMENT 2" in rule]
    assert len(stated) == 1
    assert f"{TURN_MIN_WORDS}-{TURN_MAX_WORDS} words" in stated[0]


def test_playback_does_not_carry_its_own_copy_of_the_bound() -> None:
    """The check after generation reads the constant rather than literals.

    Source inspection rather than behaviour, because the failure this guards
    against is invisible at runtime: the two bounds agree until someone widens
    one, and then a valid turn dies in a layer that never states a rule.
    """

    source = inspect.getsource(PlaybackPreparationMixin._validate_prepared)
    assert "TURN_MIN_WORDS" in source and "TURN_MAX_WORDS" in source
    assert "80, 200" not in source
    assert "unit_bounds(language, TURN_MIN_WORDS, TURN_MAX_WORDS)" in source


def test_a_length_failure_after_generation_carries_a_safe_code() -> None:
    """An uncoded failure here is the same as no failure at all.

    The turn stops either way, but without a code nothing tells a teacher why,
    the stall badge has nothing to show, and the debate reads as still running.
    """

    source = inspect.getsource(PlaybackPreparationMixin._validate_prepared)
    assert "raise ValueError" not in source
    assert "TurnValidationError" in source
    assert "turn_length_invalid" in source
