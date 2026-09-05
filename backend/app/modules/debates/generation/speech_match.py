"""Find a claim inside the speech it was taken from.

The rule this serves is "a key claim must be something the speaker actually
said", and that rule is worth keeping: the evidence trace highlights the claim
inside the speech, and a report that cites a sentence nobody spoke is exactly
what this platform exists to prevent.

The rule used to be enforced with a byte-exact ``in``. That rejected turns for
reasons that had nothing to do with truth -- a curly apostrophe where the
speech had a straight one, a line break inside a sentence, two spaces after a
full stop -- and it rejected a claim the speaker had simply said twice. This
module forgives presentation and nothing else: every word, in order, with the
same punctuation marks. It searches the original string so the returned offsets
still point into the real speech.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Characters a provider swaps for their typographic cousins without changing a
# word of what was said. Keyed by every variant, not just the canonical one:
# NFKC leaves a curly apostrophe alone, so the speech and the claim can each
# carry a different member of the same class.
_QUOTE_SINGLE = "['\u2018\u2019\u02bc\u00b4`]"
_QUOTE_DOUBLE = '["\u201c\u201d\u201e]'
_DASH = "[-\u2010\u2011\u2012\u2013\u2014\u2015]"
_ELLIPSIS = "(?:\\.\\.\\.|\u2026)"

_CHARACTER_CLASSES: dict[str, str] = {}
for _variants, _pattern in (
    ("'\u2018\u2019\u02bc\u00b4`", _QUOTE_SINGLE),
    ('"\u201c\u201d\u201e', _QUOTE_DOUBLE),
    ("-\u2010\u2011\u2012\u2013\u2014\u2015", _DASH),
):
    for _variant in _variants:
        _CHARACTER_CLASSES[_variant] = _pattern


def _pattern_source(claim_text: str) -> str:
    normalized = unicodedata.normalize("NFKC", claim_text).strip()
    parts: list[str] = []
    index = 0
    while index < len(normalized):
        character = normalized[index]
        if character.isspace():
            # Any run of whitespace matches any other, including a newline the
            # provider put in the middle of a sentence.
            while index < len(normalized) and normalized[index].isspace():
                index += 1
            parts.append(r"\s+")
            continue
        if normalized.startswith("...", index):
            parts.append(_ELLIPSIS)
            index += 3
            continue
        if character == "\u2026":
            parts.append(_ELLIPSIS)
            index += 1
            continue
        parts.append(_CHARACTER_CLASSES.get(character) or re.escape(character))
        index += 1
    return "".join(parts)


@lru_cache(maxsize=512)
def _compiled(claim_text: str) -> re.Pattern[str] | None:
    source = _pattern_source(claim_text)
    if not source:
        return None
    try:
        return re.compile(source, re.IGNORECASE)
    except re.error:
        return None


def find_claim_span(speech: str, claim_text: str) -> tuple[int, int] | None:
    """Return the first occurrence of ``claim_text`` in ``speech``, or None.

    Exact containment is tried first because it is both the common case and the
    cheapest. The tolerant pass runs only when that fails, and a speaker who
    repeated themselves gets the first occurrence rather than a rejected turn.
    """

    if not isinstance(speech, str) or not isinstance(claim_text, str):
        return None
    if not speech or not claim_text.strip():
        return None
    exact = speech.find(claim_text)
    if exact >= 0:
        return exact, exact + len(claim_text)
    pattern = _compiled(claim_text)
    if pattern is None:
        return None
    match = pattern.search(speech)
    return (match.start(), match.end()) if match else None


def speech_contains_claim(speech: str, claim_text: str) -> bool:
    return find_claim_span(speech, claim_text) is not None
