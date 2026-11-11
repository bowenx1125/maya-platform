"""Server-side measure of how much of a Debate paragraph traces to its cited sources.

The model labels its own paragraphs direct / contextual / no_match; that label
is a self-grade. This module measures the text instead: the share of the
paragraph's n-grams (characters for zh, words for en) found in the chunks it
cites, and the longest run it shares with one of them. The result is shown to
teachers only. It never rejects, repairs or changes a speech and does not feed
the Report score.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.modules.debates.generation.four_round import ENGLISH_WORD

GroundingClass = Literal["quoted", "paraphrased", "not_found", "other_language"]

# Calibrated on two production exports (2026-11-10, 2026-11-11 v4; 164 cited
# paragraphs). The control set every cited paragraph against every chunk of the
# other Agents in its Debate (1,807 pairs, same topic, different material).
# 3-grams separate best: 2-grams let same-topic Chinese reach 0.33 coverage,
# 4-grams miss short paraphrased phrases.
GROUNDING_NGRAM = {"zh": 3, "en": 3}
# A run this long copied word for word is a quotation: no control pair shared
# more than 13 Han characters or 7 words with a chunk.
QUOTED_MIN_RUN = {"zh": 15, "en": 8}
# At or above this share of its n-grams found in the cited chunks, a paragraph
# restates its source. 0.55% of control pairs reach it (0.15 let 1.05% through;
# a teacher-facing claim of support should err towards "not found").
PARAPHRASED_MIN_COVERAGE = 0.2
# Shared n-grams cannot exist across languages: a Chinese speech drawn from
# English sources (two of four Agents in the Nov 11 production Debate) scored
# 1% traced and read as unsupported. Sources whose Han share is on the other
# side of this line from the speech's language are reported as unmeasurable.
OTHER_LANGUAGE_HAN_SHARE = 0.2
# A very common n-gram (a repeated phrase in a long chunk) is matched from at
# most this many places, which bounds the longest-run search on any input.
_MAX_POSITIONS_PER_GRAM = 64


@dataclass(frozen=True, slots=True)
class Grounding:
    grounding_class: GroundingClass
    coverage: float
    longest_run: int
    matched_grams: int
    total_grams: int


def grounding_units(text: str, language: str) -> list[str]:
    """Characters (zh) or words (en), normalized so case and width never matter."""

    if language == "zh":
        return [char for char in unicodedata.normalize("NFKC", text).casefold() if char.isalnum()]
    return [word.casefold() for word in ENGLISH_WORD.findall(unicodedata.normalize("NFKC", text))]


def _grams(units: Sequence[str], size: int) -> list[tuple[str, ...]]:
    return [tuple(units[index : index + size]) for index in range(len(units) - size + 1)]


def _longest_run(units: Sequence[str], source: Sequence[str], size: int) -> int:
    positions: dict[tuple[str, ...], list[int]] = {}
    for index, gram in enumerate(_grams(source, size)):
        found = positions.setdefault(gram, [])
        if len(found) < _MAX_POSITIONS_PER_GRAM:
            found.append(index)
    best = 0
    for index, gram in enumerate(_grams(units, size)):
        for start in positions.get(gram, ()):
            length = size
            while (
                index + length < len(units)
                and start + length < len(source)
                and units[index + length] == source[start + length]
            ):
                length += 1
            best = max(best, length)
    return best


def matched_gram_flags(text: str, sources: Sequence[str], language: str) -> list[bool]:
    """For each n-gram of ``text``, whether any cited source contains it."""

    size = GROUNDING_NGRAM["zh" if language == "zh" else "en"]
    seen: set[tuple[str, ...]] = set()
    for source in sources:
        seen.update(_grams(grounding_units(source, language), size))
    return [gram in seen for gram in _grams(grounding_units(text, language), size)]


def sources_in_other_language(sources: Sequence[str], language: str) -> bool:
    letters = [char for source in sources for char in source if char.isalpha()]
    if not letters:
        return False
    han = sum(1 for char in letters if "\u3400" <= char <= "\u9fff") / len(letters)
    return (
        han < OTHER_LANGUAGE_HAN_SHARE if language == "zh" else han > 1 - OTHER_LANGUAGE_HAN_SHARE
    )


def measure_grounding(text: str, sources: Sequence[str], language: str) -> Grounding:
    """Measure one cited paragraph against the full text of the chunks it cites."""

    key = "zh" if language == "zh" else "en"
    size = GROUNDING_NGRAM[key]
    units = grounding_units(text, language)
    if sources_in_other_language(sources, language):
        return Grounding("other_language", 0.0, 0, 0, 0)
    flags = matched_gram_flags(text, sources, language)
    matched = sum(flags)
    coverage = matched / len(flags) if flags else 0.0
    longest = max(
        (
            _longest_run(units, grounding_units(source, language), size)
            for source in sources
            if matched
        ),
        default=0,
    )
    if longest >= QUOTED_MIN_RUN[key]:
        grounding_class: GroundingClass = "quoted"
    elif coverage >= PARAPHRASED_MIN_COVERAGE:
        grounding_class = "paraphrased"
    else:
        grounding_class = "not_found"
    return Grounding(grounding_class, coverage, longest, matched, len(flags))
