"""Pure PromptBudgetV1 preflight contracts.

The prompt budget is deliberately independent of an HTTP/provider adapter.  A
caller must be able to reject an oversized request before it has a chance to
touch a network.  Until a supplier-compatible tokenizer is reviewed, the
conservative counter treats every UTF-8 byte as one token.  That can reject a
safe request, but it cannot make an over-limit request look safe.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, cast, runtime_checkable

PROMPT_BUDGET_VERSION = "prompt_budget_v1"
PROMPT_INPUT_TOKEN_LIMIT = 32_000
PROMPT_REQUEST_BYTES_LIMIT = 96 * 1024
PROMPT_OUTPUT_TOKEN_LIMIT = 1_500
PROMPT_MAX_ATTEMPTS = 2

# Friendly aliases used by adapters.  Keeping one source of truth avoids a
# legacy caller accidentally introducing a second set of limits.
MAX_INPUT_TOKENS = PROMPT_INPUT_TOKEN_LIMIT
MAX_REQUEST_BYTES = PROMPT_REQUEST_BYTES_LIMIT
MAX_OUTPUT_TOKENS = PROMPT_OUTPUT_TOKEN_LIMIT
MAX_ATTEMPTS = PROMPT_MAX_ATTEMPTS

CONSERVATIVE_TOKENIZER_ID = "utf8-byte-conservative-v1"
CONSERVATIVE_TOKENIZER_ASSET_HASH = hashlib.sha256(
    CONSERVATIVE_TOKENIZER_ID.encode("ascii")
).hexdigest()

BudgetErrorCode = Literal[
    "prompt_input_tokens_exceeded",
    "prompt_request_bytes_exceeded",
    "prompt_output_tokens_exceeded",
    "prompt_token_counter_unavailable",
    "prompt_budget_invalid",
]


class PromptBudgetError(ValueError):
    """A prompt cannot pass the pre-send budget gate.

    The exception code is safe to persist/display.  The exception message is
    intentionally generic and never includes request text or provider data.
    """

    def __init__(self, message: str, *, code: BudgetErrorCode) -> None:
        super().__init__(message)
        self.code = code


@runtime_checkable
class TokenCounterPort(Protocol):
    """Supplier-compatible, version-pinned local token-counting port."""

    tokenizer_id: str
    asset_hash: str

    def count_tokens(self, text: str) -> int:
        """Count one already-normalized text value without network I/O."""


@dataclass(frozen=True, slots=True)
class ConservativeUtf8TokenCounter:
    """Fail-safe fallback: one model token per UTF-8 byte."""

    tokenizer_id: str = CONSERVATIVE_TOKENIZER_ID
    asset_hash: str = CONSERVATIVE_TOKENIZER_ASSET_HASH

    def count_tokens(self, text: str) -> int:
        if not isinstance(text, str):
            raise PromptBudgetError(
                "The prompt token counter received invalid text.",
                code="prompt_token_counter_unavailable",
            )
        return len(text.encode("utf-8"))

    def count(self, text: str) -> int:
        """Short alias for adapters using the embedding tokenizer port."""

        return self.count_tokens(text)


@dataclass(frozen=True, slots=True)
class PinnedTokenCounter:
    """Adapter around a reviewed local tokenizer and immutable asset hash.

    This object does not load a tokenizer, inspect environment variables, or
    call a provider.  The application may inject a pinned callable once its
    asset has passed the relevant Gate.
    """

    tokenizer_id: str
    asset_hash: str
    counter: Callable[[str], int]

    def __post_init__(self) -> None:
        if not self.tokenizer_id.strip() or not self._valid_asset_hash(self.asset_hash):
            raise ValueError("a pinned prompt tokenizer needs an id and SHA-256 asset hash")
        if not callable(self.counter):
            raise ValueError("a pinned prompt tokenizer needs a callable counter")

    @staticmethod
    def _valid_asset_hash(value: str) -> bool:
        return bool(re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", value))

    def count_tokens(self, text: str) -> int:
        if not isinstance(text, str):
            raise PromptBudgetError(
                "The prompt token counter received invalid text.",
                code="prompt_token_counter_unavailable",
            )
        try:
            value = self.counter(text)
        except Exception as exc:
            raise PromptBudgetError(
                "The pinned prompt token counter is unavailable.",
                code="prompt_token_counter_unavailable",
            ) from exc
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PromptBudgetError(
                "The pinned prompt token counter returned an invalid count.",
                code="prompt_token_counter_unavailable",
            )
        return value

    def count(self, text: str) -> int:
        return self.count_tokens(text)


# Naming aliases keep the port compatible with the W4-EMBED tokenizer seam.
ConservativeTokenCounter = ConservativeUtf8TokenCounter
Utf8ByteTokenCounter = ConservativeUtf8TokenCounter
PinnedTokenCounterV1 = PinnedTokenCounter
PinnedTokenizerV1 = PinnedTokenCounter
Utf8ByteTokenizer = ConservativeUtf8TokenCounter


def _count_with_port(counter: object, text: str) -> int:
    method = getattr(counter, "count_tokens", None)
    if not callable(method):
        method = getattr(counter, "count", None)
    if not callable(method):
        raise PromptBudgetError(
            "The prompt token counter does not implement the pinned port.",
            code="prompt_token_counter_unavailable",
        )
    try:
        value = cast(Callable[[str], object], method)(text)
    except PromptBudgetError:
        raise
    except Exception as exc:
        raise PromptBudgetError(
            "The prompt token counter is unavailable.",
            code="prompt_token_counter_unavailable",
        ) from exc
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PromptBudgetError(
            "The prompt token counter returned an invalid count.",
            code="prompt_token_counter_unavailable",
        )
    return value


def count_prompt_tokens(text: str, counter: TokenCounterPort | object | None = None) -> int:
    """Count text with an explicitly pinned counter or the safe fallback."""

    if counter is None:
        return ConservativeUtf8TokenCounter().count_tokens(text)
    return _count_with_port(counter, text)


def count_tokens_conservatively(text: str) -> int:
    """Count with the conservative UTF-8 fallback."""

    return ConservativeUtf8TokenCounter().count_tokens(text)


@dataclass(frozen=True, slots=True)
class PromptBudgetV1:
    """A pre-send budget estimate and the limits used to produce it."""

    input_tokens: int
    request_bytes: int
    requested_output_tokens: int = PROMPT_OUTPUT_TOKEN_LIMIT
    input_token_limit: int = PROMPT_INPUT_TOKEN_LIMIT
    request_bytes_limit: int = PROMPT_REQUEST_BYTES_LIMIT
    output_token_limit: int = PROMPT_OUTPUT_TOKEN_LIMIT
    max_attempts: int = PROMPT_MAX_ATTEMPTS
    tokenizer_id: str = CONSERVATIVE_TOKENIZER_ID
    tokenizer_asset_hash: str = CONSERVATIVE_TOKENIZER_ASSET_HASH

    def __post_init__(self) -> None:
        values = (
            self.input_tokens,
            self.request_bytes,
            self.requested_output_tokens,
            self.input_token_limit,
            self.request_bytes_limit,
            self.output_token_limit,
            self.max_attempts,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values
        ):
            raise ValueError("prompt budget counts and limits must be non-negative integers")
        if not self.tokenizer_id.strip() or not self.tokenizer_asset_hash.strip():
            raise ValueError("prompt budget tokenizer identity is required")
        if self.max_attempts < 1:
            raise ValueError("prompt budget must allow at least one attempt")

    @property
    def within_limits(self) -> bool:
        return (
            self.input_tokens <= self.input_token_limit
            and self.request_bytes <= self.request_bytes_limit
            and self.requested_output_tokens <= self.output_token_limit
        )

    @property
    def input_token_count(self) -> int:
        return self.input_tokens

    @property
    def canonical_request_bytes(self) -> int:
        return self.request_bytes

    def as_record(self) -> dict[str, object]:
        """Return safe ledger metadata only."""

        return {
            "prompt_budget_version": PROMPT_BUDGET_VERSION,
            "input_tokens": self.input_tokens,
            "request_bytes": self.request_bytes,
            "requested_output_tokens": self.requested_output_tokens,
            "input_token_limit": self.input_token_limit,
            "request_bytes_limit": self.request_bytes_limit,
            "output_token_limit": self.output_token_limit,
            "max_attempts": self.max_attempts,
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_asset_hash": self.tokenizer_asset_hash,
        }

    @classmethod
    def preflight(
        cls,
        messages: Sequence[str | object],
        **kwargs: object,
    ) -> PromptBudgetV1:
        """Classmethod façade for adapters that treat the budget as a builder."""

        return preflight_prompt_budget(messages, **kwargs)  # type: ignore[arg-type]

    @property
    def max_input_tokens(self) -> int:
        return self.input_token_limit

    @property
    def max_request_bytes(self) -> int:
        return self.request_bytes_limit

    @property
    def max_output_tokens(self) -> int:
        return self.output_token_limit

    @property
    def output_tokens(self) -> int:
        return self.requested_output_tokens


def preflight_prompt_budget(
    messages: Sequence[str | object],
    *,
    request_bytes: int | None = None,
    requested_output_tokens: int = PROMPT_OUTPUT_TOKEN_LIMIT,
    token_counter: TokenCounterPort | object | None = None,
    input_token_limit: int = PROMPT_INPUT_TOKEN_LIMIT,
    request_bytes_limit: int = PROMPT_REQUEST_BYTES_LIMIT,
    output_token_limit: int = PROMPT_OUTPUT_TOKEN_LIMIT,
) -> PromptBudgetV1:
    """Count and validate one serialized provider request before send.

    ``messages`` contains message content only.  The framing is fixed by the
    two-message provider DTO; counting both contents is conservative.  The
    byte cap is normally the canonical user JSON length, supplied explicitly
    by the request builder; when omitted it is the UTF-8 size of all content.
    """

    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes, bytearray)):
        raise PromptBudgetError(
            "Prompt messages must be a sequence of text values.",
            code="prompt_budget_invalid",
        )
    contents: list[str] = []
    for message in messages:
        if isinstance(message, str):
            contents.append(message)
            continue
        content = getattr(message, "content", None)
        if not isinstance(content, str):
            raise PromptBudgetError(
                "Prompt messages must contain text values.",
                code="prompt_budget_invalid",
            )
        contents.append(content)
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (
            requested_output_tokens,
            input_token_limit,
            request_bytes_limit,
            output_token_limit,
        )
    ):
        raise PromptBudgetError(
            "Prompt budget limits are invalid.",
            code="prompt_budget_invalid",
        )
    if request_bytes is None:
        request_bytes = sum(len(message.encode("utf-8")) for message in contents)
    if isinstance(request_bytes, bool) or not isinstance(request_bytes, int) or request_bytes < 0:
        raise PromptBudgetError(
            "Prompt request bytes are invalid.",
            code="prompt_budget_invalid",
        )
    tokenizer_id = (
        str(getattr(token_counter, "tokenizer_id", ""))
        if token_counter is not None
        else CONSERVATIVE_TOKENIZER_ID
    )
    tokenizer_asset_hash = (
        str(getattr(token_counter, "asset_hash", ""))
        if token_counter is not None
        else CONSERVATIVE_TOKENIZER_ASSET_HASH
    )
    try:
        input_tokens = sum(count_prompt_tokens(message, token_counter) for message in contents)
    except PromptBudgetError:
        raise
    budget = PromptBudgetV1(
        input_tokens=input_tokens,
        request_bytes=request_bytes,
        requested_output_tokens=requested_output_tokens,
        input_token_limit=input_token_limit,
        request_bytes_limit=request_bytes_limit,
        output_token_limit=output_token_limit,
        tokenizer_id=tokenizer_id or CONSERVATIVE_TOKENIZER_ID,
        tokenizer_asset_hash=tokenizer_asset_hash or CONSERVATIVE_TOKENIZER_ASSET_HASH,
    )
    # The conservative counter returns UTF-8 bytes, not model tokens. Comparing
    # its output to a token limit is a unit error: it made the real ceiling
    # 32,000 bytes rather than the 96 KiB the contract allows, so a debate the
    # product offers - three Agents over four rounds - could not reach its last
    # round even though its prompt was about 6,000 actual tokens. English text
    # is roughly four bytes per token, so a request within the byte allowance is
    # comfortably within the token allowance, and speech is English by rule.
    # A pinned supplier tokenizer reports real tokens and is checked as such.
    # Size ceilings used to reject here. The owner removed token, byte and
    # output quotas: the counted size stays on the budget for the ledger, and
    # it no longer stops a turn.
    return budget


# Alternative function names make the preflight seam easy to discover while
# preserving one implementation.
check_prompt_budget = preflight_prompt_budget
build_prompt_budget = preflight_prompt_budget


__all__ = [
    "CONSERVATIVE_TOKENIZER_ASSET_HASH",
    "CONSERVATIVE_TOKENIZER_ID",
    "ConservativeTokenCounter",
    "ConservativeUtf8TokenCounter",
    "MAX_ATTEMPTS",
    "MAX_INPUT_TOKENS",
    "MAX_OUTPUT_TOKENS",
    "MAX_REQUEST_BYTES",
    "PinnedTokenCounter",
    "PinnedTokenCounterV1",
    "PinnedTokenizerV1",
    "PromptBudgetError",
    "PromptBudgetV1",
    "PROMPT_BUDGET_VERSION",
    "PROMPT_INPUT_TOKEN_LIMIT",
    "PROMPT_MAX_ATTEMPTS",
    "PROMPT_OUTPUT_TOKEN_LIMIT",
    "PROMPT_REQUEST_BYTES_LIMIT",
    "TokenCounterPort",
    "Utf8ByteTokenCounter",
    "Utf8ByteTokenizer",
    "build_prompt_budget",
    "check_prompt_budget",
    "count_prompt_tokens",
    "count_tokens_conservatively",
    "preflight_prompt_budget",
]
