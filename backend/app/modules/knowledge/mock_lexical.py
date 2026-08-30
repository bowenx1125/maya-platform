"""Versioned lexical relevance gate for deterministic Mock retrieval only.

The feature-hashed Mock embedding is useful for exercising the vector and
receipt pipeline, but hash collisions are not semantic evidence.  This module
adds a small, frozen lexical anchor before Mock vector thresholds are applied.
It is deliberately independent from real Embedding/Vector provider ports.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MOCK_LEXICAL_ANCHOR_POLICY_ID = "mock_lexical_anchor_v2"

# Keep this set literal and versioned with the policy.  Changes alter retrieval
# outcomes and therefore require a new policy ID rather than an in-place edit.
MOCK_LEXICAL_STOP_WORDS_V2 = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "might",
        "must",
        "of",
        "on",
        "or",
        "our",
        "should",
        "than",
        "that",
        "the",
        "their",
        "them",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "whether",
        "which",
        "who",
        "why",
        "will",
        "with",
        "without",
        "would",
        "you",
        "your",
    }
)

_LATIN_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")
_HTTP_URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)


def frozen_latin_tokens_v2(text: str) -> frozenset[str]:
    """Return normalized meaningful Latin tokens for the v2 Mock policy.

    HTTP(S) destinations are removed before tokenization: words that happen to
    occur only in a citation URL slug are provenance, not evidence that the
    chunk discusses the classroom topic.  NFKD plus combining-mark removal
    makes ordinary Latin diacritics compare with their ASCII spellings.  Curly
    apostrophes are normalized, English possessive ``'s`` is removed,
    numeric-only terms and the frozen stop-word set are excluded, and
    duplicates collapse into a set.  This is a simple deterministic
    teaching-demo tokenizer, not a language detector.
    """

    without_urls = _HTTP_URL_RE.sub(" ", text)
    normalized = unicodedata.normalize("NFKD", without_urls.casefold().replace("\u2019", "'"))
    ascii_latin = "".join(
        char for char in normalized if ord(char) < 128 and unicodedata.category(char) != "Mn"
    )
    tokens: set[str] = set()
    for match in _LATIN_TOKEN_RE.finditer(ascii_latin):
        token = match.group(0)
        if token.endswith("'s") and len(token) > 2:
            token = token[:-2]
        if (
            token
            and any("a" <= char <= "z" for char in token)
            and token not in MOCK_LEXICAL_STOP_WORDS_V2
        ):
            tokens.add(token)
    return frozenset(tokens)


@dataclass(frozen=True, slots=True)
class MockLexicalAnchorV2:
    """An authoritative topic token set applied to each candidate chunk."""

    topic_tokens: frozenset[str]

    @classmethod
    def from_topic(cls, topic: str) -> MockLexicalAnchorV2:
        return cls(frozen_latin_tokens_v2(topic))

    @property
    def required_overlap(self) -> int:
        if len(self.topic_tokens) >= 2:
            return 2
        return len(self.topic_tokens)

    def accepts(self, candidate_text: str) -> bool:
        required = self.required_overlap
        if required == 0:
            return False
        candidate_tokens = frozen_latin_tokens_v2(candidate_text)
        return len(self.topic_tokens.intersection(candidate_tokens)) >= required


__all__ = [
    "MOCK_LEXICAL_ANCHOR_POLICY_ID",
    "MOCK_LEXICAL_STOP_WORDS_V2",
    "MockLexicalAnchorV2",
    "frozen_latin_tokens_v2",
]
