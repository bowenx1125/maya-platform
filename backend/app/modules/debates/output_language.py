"""The one place a Debate's output language is read.

A Debate is generated in one language, chosen when the teacher starts it. The
choice is not the browser's interface language: switching the UI afterwards
translates the chrome, never the lesson. It cannot change mid-debate either,
and that is a product decision rather than a technical limit — each turn's
prompt carries the speeches before it, turns are prepared ahead of the teacher,
and the evidence chain records queries embedded in the language they were
written in. Switching at turn five of twelve would leave a bilingual record
whose evidence no longer matches its speech.

Everything that needs to know reads it here, so a new rule about language
cannot disagree with an old one.
"""

from __future__ import annotations

import re
from typing import Any, Literal

OutputLanguage = Literal["en", "zh"]

DEFAULT_OUTPUT_LANGUAGE: OutputLanguage = "en"
SUPPORTED_OUTPUT_LANGUAGES: frozenset[str] = frozenset({"en", "zh"})

# Han characters, the same range the speech validators already recognise.
CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")

# A Latin word and a Han character are not the same unit of meaning, so the
# per-turn bound cannot be one number. These are the Chinese equivalents of
# the 80-200 word English bound: a Han character carries roughly as much as a
# short English word, and a turn that reads for about the same length runs to
# a few hundred characters.
CHINESE_MIN_UNITS = 150
CHINESE_MAX_UNITS = 400


def debate_output_language(debate: Any) -> OutputLanguage:
    """Which language this Debate speaks, defaulting to English."""

    value = getattr(debate, "output_language", None)
    if isinstance(value, str) and value in SUPPORTED_OUTPUT_LANGUAGES:
        return "zh" if value == "zh" else "en"
    return DEFAULT_OUTPUT_LANGUAGE


def speech_units(value: str, language: OutputLanguage) -> int:
    """Count a speech in the unit its language is bounded by."""

    if language == "zh":
        return len(CJK_RE.findall(value))
    from app.modules.debates.generation.validator import WORD_RE

    return len(WORD_RE.findall(value))


def unit_bounds(language: OutputLanguage, min_words: int, max_words: int) -> tuple[int, int]:
    """The per-turn bound for this language."""

    if language == "zh":
        return CHINESE_MIN_UNITS, CHINESE_MAX_UNITS
    return min_words, max_words


__all__ = [
    "CHINESE_MAX_UNITS",
    "CHINESE_MIN_UNITS",
    "CJK_RE",
    "DEFAULT_OUTPUT_LANGUAGE",
    "SUPPORTED_OUTPUT_LANGUAGES",
    "OutputLanguage",
    "debate_output_language",
    "speech_units",
    "unit_bounds",
]
