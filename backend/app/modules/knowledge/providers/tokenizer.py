"""Pinned token-counting port and the fail-safe UTF-8 fallback.

The supplier tokenizer is intentionally a port, not an implementation detail
of an HTTP adapter.  Until a reviewed tokenizer asset is available the only
safe estimate is one token per UTF-8 byte.  This estimate can reject valid
requests, but it cannot under-count a long unbroken input before network I/O.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

CONSERVATIVE_TOKENIZER_ID = "utf8-byte-conservative-v1"
CONSERVATIVE_TOKENIZER_ASSET_HASH = hashlib.sha256(
    CONSERVATIVE_TOKENIZER_ID.encode("ascii")
).hexdigest()


class TokenizerError(ValueError):
    """A token counter is unavailable or returned an unsafe count."""


@runtime_checkable
class PinnedTokenizer(Protocol):
    """Supplier-compatible, version-pinned token-counting port.

    ``asset_hash`` is persisted with a build manifest.  A caller must not
    silently swap implementations under an existing hash.
    """

    tokenizer_id: str
    asset_hash: str

    def count_tokens(self, text: str) -> int:
        """Return the count for one already-normalized UTF-8 string."""


@dataclass(frozen=True, slots=True)
class PinnedTokenizerV1:
    """Adapter for a reviewed tokenizer callable and its immutable asset hash."""

    tokenizer_id: str
    asset_hash: str
    counter: Callable[[str], int]

    def __post_init__(self) -> None:
        if not self.tokenizer_id.strip() or not self.asset_hash.strip():
            raise ValueError("a pinned tokenizer needs an id and asset hash")

    def count_tokens(self, text: str) -> int:
        if not isinstance(text, str):
            raise TokenizerError("tokenizer input must be text")
        try:
            value = self.counter(text)
        except Exception as exc:
            raise TokenizerError("pinned tokenizer is unavailable") from exc
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TokenizerError("pinned tokenizer returned an invalid count")
        return value

    # A short alias makes the port convenient for packing callers while the
    # explicit method remains the frozen contract name.
    def count(self, text: str) -> int:
        return self.count_tokens(text)


@dataclass(frozen=True, slots=True)
class Utf8ByteTokenizer:
    """Conservative fallback used when no reviewed tokenizer is authorized."""

    tokenizer_id: str = CONSERVATIVE_TOKENIZER_ID
    asset_hash: str = CONSERVATIVE_TOKENIZER_ASSET_HASH
    authorized: bool = False

    def count_tokens(self, text: str) -> int:
        if not isinstance(text, str):
            raise TokenizerError("tokenizer input must be text")
        return len(text.encode("utf-8"))

    def count(self, text: str) -> int:
        return self.count_tokens(text)


# Descriptive aliases used by integration code and tests.
ConservativeUtf8Tokenizer = Utf8ByteTokenizer
Utf8ByteConservativeTokenizer = Utf8ByteTokenizer


def count_tokens_conservatively(text: str) -> int:
    """Count UTF-8 bytes without ever consulting a provider or model."""

    return Utf8ByteTokenizer().count_tokens(text)


def _counter(tokenizer: object) -> Callable[[str], int]:
    method = getattr(tokenizer, "count_tokens", None)
    if not callable(method):
        method = getattr(tokenizer, "count", None)
    if not callable(method):
        raise TokenizerError("tokenizer does not implement the pinned port")
    return cast(Callable[[str], int], method)


def count_tokens(text: str, tokenizer: PinnedTokenizer | object | None = None) -> int:
    """Count with a pinned tokenizer or use the conservative fallback.

    The fallback is selected only when no tokenizer is supplied.  A supplied
    but broken tokenizer fails closed instead of silently changing the build's
    token accounting policy.
    """

    if tokenizer is None:
        return count_tokens_conservatively(text)
    value = _counter(tokenizer)(text)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TokenizerError("tokenizer returned an invalid count")
    return value


__all__ = [
    "CONSERVATIVE_TOKENIZER_ASSET_HASH",
    "CONSERVATIVE_TOKENIZER_ID",
    "ConservativeUtf8Tokenizer",
    "PinnedTokenizer",
    "PinnedTokenizerV1",
    "TokenizerError",
    "Utf8ByteConservativeTokenizer",
    "Utf8ByteTokenizer",
    "count_tokens",
    "count_tokens_conservatively",
]
