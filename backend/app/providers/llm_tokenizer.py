"""Supplier-tokenizer ports for the fixed Wave 4 LLM adapter.

The adapter never downloads a tokenizer and never asks the supplier to count
tokens.  A tokenizer is injected by the runtime with an immutable identifier
and asset digest, and both are recorded with every request so the ledger always
states which counter produced an estimate.

Demo V1 deliberately has no supplier-tokenizer authorization gate.  The
conservative UTF-8 counter over-counts rather than under-counts, so it may back
the pre-flight estimate directly.  The bounded acceptance-run ledger, not this
estimate, is what caps how many real requests may occur.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

LLM_TOKENIZER_FALLBACK_ID = "utf8-byte-conservative-v1"
LLM_TOKENIZER_FALLBACK_ASSET_HASH = hashlib.sha256(
    LLM_TOKENIZER_FALLBACK_ID.encode("ascii")
).hexdigest()
# Friendly aliases align the LLM port with the existing embedding tokenizer
# naming without importing the embedding implementation into this boundary.
CONSERVATIVE_LLM_TOKENIZER_ID = LLM_TOKENIZER_FALLBACK_ID
CONSERVATIVE_LLM_TOKENIZER_ASSET_HASH = LLM_TOKENIZER_FALLBACK_ASSET_HASH


class LLMTokenizerError(ValueError):
    """A tokenizer is missing, unavailable or returned an unsafe count."""

    code = "llm_tokenizer_unavailable"


@runtime_checkable
class LLMTokenizerPort(Protocol):
    """The reviewed, supplier-compatible local counting port."""

    tokenizer_id: str
    asset_hash: str

    def count_tokens(self, text: str) -> int:
        """Count one already-normalized text value without I/O."""


@dataclass(frozen=True, slots=True)
class ConservativeLLMTokenizer:
    """Count one UTF-8 byte as one token: a deliberate over-estimate."""

    tokenizer_id: str = LLM_TOKENIZER_FALLBACK_ID
    asset_hash: str = LLM_TOKENIZER_FALLBACK_ASSET_HASH

    def count_tokens(self, text: str) -> int:
        if not isinstance(text, str):
            raise LLMTokenizerError("tokenizer input must be text")
        return len(text.encode("utf-8"))

    def count(self, text: str) -> int:
        return self.count_tokens(text)


@dataclass(frozen=True, slots=True)
class PinnedLLMTokenizer:
    """A pinned tokenizer callable and its immutable asset hash."""

    tokenizer_id: str
    asset_hash: str
    counter: Callable[[str], int]

    def __post_init__(self) -> None:
        if not isinstance(self.tokenizer_id, str) or not self.tokenizer_id.strip():
            raise ValueError("a pinned LLM tokenizer needs an id")
        if not isinstance(self.asset_hash, str) or not self.asset_hash.strip():
            raise ValueError("a pinned LLM tokenizer needs an asset hash")
        if not callable(self.counter):
            raise ValueError("a pinned LLM tokenizer needs a callable counter")

    def count_tokens(self, text: str) -> int:
        if not isinstance(text, str):
            raise LLMTokenizerError("tokenizer input must be text")
        try:
            value = self.counter(text)
        except Exception as exc:
            raise LLMTokenizerError("pinned tokenizer is unavailable") from exc
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LLMTokenizerError("pinned tokenizer returned an invalid count")
        return value

    def count(self, text: str) -> int:
        return self.count_tokens(text)


# Names used by callers which share the PromptBudget/Embedding vocabulary.
LLMTokenizerV1 = PinnedLLMTokenizer
PinnedTokenizerV1 = PinnedLLMTokenizer
Utf8ByteLLMTokenizer = ConservativeLLMTokenizer


def _counter(tokenizer: object) -> Callable[[str], object]:
    method = getattr(tokenizer, "count_tokens", None)
    if not callable(method):
        method = getattr(tokenizer, "count", None)
    if not callable(method):
        raise LLMTokenizerError("tokenizer does not implement the LLM port")
    return cast(Callable[[str], object], method)


def count_llm_tokens(text: str, tokenizer: LLMTokenizerPort | object | None = None) -> int:
    """Count with the injected tokenizer or the conservative fallback."""

    if tokenizer is None:
        return ConservativeLLMTokenizer().count_tokens(text)
    try:
        value = _counter(tokenizer)(text)
    except LLMTokenizerError:
        raise
    except Exception as exc:
        raise LLMTokenizerError("tokenizer is unavailable") from exc
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LLMTokenizerError("tokenizer returned an invalid count")
    return value


def tokenizer_asset_hash_valid(value: object) -> bool:
    """Return whether an asset identity is exactly lowercase SHA-256 hex."""

    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


__all__ = [
    "CONSERVATIVE_LLM_TOKENIZER_ASSET_HASH",
    "CONSERVATIVE_LLM_TOKENIZER_ID",
    "LLM_TOKENIZER_FALLBACK_ASSET_HASH",
    "LLM_TOKENIZER_FALLBACK_ID",
    "LLMTokenizerError",
    "LLMTokenizerPort",
    "LLMTokenizerV1",
    "ConservativeLLMTokenizer",
    "PinnedLLMTokenizer",
    "PinnedTokenizerV1",
    "Utf8ByteLLMTokenizer",
    "count_llm_tokens",
    "tokenizer_asset_hash_valid",
]
