"""Deterministic language boundary for Wave 2 debate topics.

Wave 2 generates authoritative English speech.  A topic therefore has to be
an English/Latin-script topic before it can enter the debate lifecycle.  This
module intentionally performs a small, deterministic script check rather than
calling a language detector or a provider.  It is shared by draft create,
draft update, and start so an old invalid draft cannot reach generation.
"""

from __future__ import annotations

import unicodedata
from typing import Final

from app.modules.debates.generated.latin_script_ranges import is_latin_script_letter

TOPIC_LANGUAGE_ERROR_CODE: Final = "topic_language_invalid"
TOPIC_LANGUAGE_ERROR_MESSAGE: Final = "The debate topic must be written in English."
TOPIC_LANGUAGE_ERROR_DETAILS: Final[dict[str, str]] = {
    "field": "topic",
    "required_language": "en",
    "allowed_script": "Latin",
}


class TopicLanguageError(ValueError):
    """A safe, stable validation error that never includes the topic text."""

    code = TOPIC_LANGUAGE_ERROR_CODE
    message = TOPIC_LANGUAGE_ERROR_MESSAGE

    @property
    def details(self) -> dict[str, str]:
        # Return a copy so callers cannot mutate the shared contract value.
        return dict(TOPIC_LANGUAGE_ERROR_DETAILS)

    def __init__(self) -> None:
        super().__init__(self.message)


def _is_latin_letter(character: str) -> bool:
    """Return whether a Unicode letter belongs to the Latin script.

    The range table is generated from Node 24's
    ``Letter && Script_Extensions=Latin`` predicate.  Keeping the binary
    search in the generated module makes the server and browser use the same
    reviewed Unicode source rather than drifting name/NFKD heuristics.
    """

    return is_latin_script_letter(ord(character))


def _is_latin_mark(character: str) -> bool:
    category = unicodedata.category(character)
    # NFD Latin diacritics are commonly Unicode ``Inherited`` marks rather
    # than marks with an explicit Latin script property.  The adjacency rule
    # in ``validate_english_topic`` is the important safety boundary: a mark
    # is accepted only after a validated Latin letter or another mark in the
    # same grapheme cluster.  ``Me`` enclosing marks are intentionally not
    # accepted as ordinary topic diacritics.
    return category in {"Mn", "Mc"}


def validate_english_topic(value: str) -> str:
    """Validate and return a trimmed English/Latin-script debate topic.

    The check permits Unicode Latin diacritics, numbers, punctuation, and
    Unicode space separators.  It rejects all C0/C1 controls and Unicode
    format controls (including bidi controls), as well as every non-Latin
    letter, symbol, unsafe mark, and non-space separator.  At least one Latin
    letter is required, so a number/punctuation-only value cannot pass as an
    English topic.
    """

    if not isinstance(value, str):
        raise TopicLanguageError()

    # Inspect the original value before trimming: tabs/newlines must not be
    # silently removed and accepted as if they were ordinary spaces.
    has_latin_letter = False
    mark_chain = False
    for character in value:
        # The generated Node-24 table is authoritative even when the Python
        # runtime's Unicode database predates a code point in that table (for
        # example U+A7CB).  Check it before consulting Python categories.
        if _is_latin_letter(character):
            has_latin_letter = True
            mark_chain = True
            continue
        category = unicodedata.category(character)
        if category in {"Cc", "Cf"}:
            raise TopicLanguageError()
        if _is_latin_mark(character):
            # Combining marks are meaningful here only as part of a Latin
            # grapheme.  This rejects isolated marks and marks pasted after
            # a number, punctuation character, or space.
            if not mark_chain:
                raise TopicLanguageError()
            mark_chain = True
            continue
        if category.startswith("N") or category.startswith("P") or category == "Zs":
            mark_chain = False
            continue
        # Symbols, non-Zs separators, unassigned code points, surrogates and
        # non-Latin marks are outside the topic contract.  A non-Latin letter
        # was rejected above before reaching this branch.
        raise TopicLanguageError()

    trimmed = value.strip()
    if not trimmed or not has_latin_letter:
        raise TopicLanguageError()
    return trimmed


def validate_topic(value: str, output_language: str = "en") -> str:
    """Chinese lessons accept Han and Latin text before any pre-generation."""

    if output_language == "en":
        return validate_english_topic(value)
    if output_language != "zh" or not isinstance(value, str):
        raise TopicLanguageError()
    # Replace Han letters solely for script validation; return the authored
    # text, not this projection. Both UI and server use these explicit ranges.
    projected = "".join(
        "A"
        if (
            0x3400 <= ord(char) <= 0x4DBF
            or 0x4E00 <= ord(char) <= 0x9FFF
            or 0xF900 <= ord(char) <= 0xFAFF
            or 0x20000 <= ord(char) <= 0x2FA1F
            or 0x30000 <= ord(char) <= 0x323AF
        )
        else char
        for char in value
    )
    validate_english_topic(projected)
    return value.strip()


__all__ = [
    "TOPIC_LANGUAGE_ERROR_CODE",
    "TOPIC_LANGUAGE_ERROR_DETAILS",
    "TOPIC_LANGUAGE_ERROR_MESSAGE",
    "TopicLanguageError",
    "validate_english_topic",
]
