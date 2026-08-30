"""Provider-neutral translation policy and the deterministic Mock adapter."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from .manifest import MOCK_POLICY_KEY, MOCK_QUALITY_KEY

MOCK_TRANSLATION_POLICY = MOCK_POLICY_KEY
MOCK_TRANSLATION_QUALITY = MOCK_QUALITY_KEY
MOCK_PREFIX = "【测试中文表示，不代表翻译质量】\n"


class TranslationProviderError(RuntimeError):
    """A provider-neutral, safe-to-record translation failure."""


@dataclass(frozen=True, slots=True)
class TranslationInput:
    """One exact source item supplied to a translation provider."""

    content_type: str
    content_id: str
    source_text: str
    source_text_hash: str


@dataclass(frozen=True, slots=True)
class TranslationOutput:
    translated_text: str | None
    safe_error_code: str | None = None


class TranslationProvider(Protocol):
    """Small batch port implemented by Mock now and real providers later."""

    policy_key: str
    quality_key: str

    def translate_batch(self, items: Sequence[TranslationInput]) -> Sequence[TranslationOutput]:
        """Translate each item in order without changing source identity."""


@dataclass
class MockTranslationProvider:
    """Exact test representation; never performs a network call.

    ``failures`` is intentionally a test-only injection queue.  Entries can
    be ``None``/empty for normal output or any string safe error code to
    produce a per-item failure.  The provider keeps no source cache, so cache
    identity remains a backend responsibility.
    """

    failures: Iterable[str | None] = ()
    policy_key: str = field(default=MOCK_TRANSLATION_POLICY, init=False)
    quality_key: str = field(default=MOCK_TRANSLATION_QUALITY, init=False)
    calls: int = field(default=0, init=False)
    call_log: list[tuple[str, ...]] = field(default_factory=list, init=False)
    _failures: deque[str | None] = field(default_factory=deque, init=False, repr=False)

    def __post_init__(self) -> None:
        self._failures.extend(self.failures)

    @property
    def call_count(self) -> int:
        return self.calls

    def fail_next(self, safe_error_code: str = "translation_provider_failed") -> None:
        self._failures.append(safe_error_code)

    def translate_batch(self, items: Sequence[TranslationInput]) -> Sequence[TranslationOutput]:
        self.calls += 1
        self.call_log.append(tuple(item.content_id for item in items))
        outputs: list[TranslationOutput] = []
        for item in items:
            failure = self._failures.popleft() if self._failures else None
            if failure:
                outputs.append(TranslationOutput(None, _safe_error_code(failure)))
            else:
                # Do not strip, normalize, translate, or otherwise mutate the
                # authoritative English source.  This visible sentinel is the
                # teaching/demo boundary and not a quality claim.
                outputs.append(TranslationOutput(MOCK_PREFIX + item.source_text))
        return outputs


def _safe_error_code(value: str) -> str:
    """Keep provider/test failure values within the public safe-code shape."""

    if not value:
        return "translation_provider_failed"
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_-."
    normalized = "_".join(value.casefold().split())
    cleaned = "".join(character for character in normalized if character in allowed)
    return cleaned[:64] or "translation_provider_failed"


def translation_provider(settings: object | None = None) -> TranslationProvider:
    """Select the only Wave 3 provider allowed by the frozen Mock Gate."""

    selector = getattr(settings, "translation_provider", None) if settings is not None else None
    if selector in {None, "", "mock"}:
        return MockTranslationProvider()
    # Real TranslationProvider adapters remain a future independently
    # authorized service Gate; a typo must fail closed rather than silently
    # calling a billed network service.
    raise RuntimeError("Wave 3 translation provider must remain Mock.")


__all__ = [
    "MOCK_PREFIX",
    "MOCK_TRANSLATION_POLICY",
    "MOCK_TRANSLATION_QUALITY",
    "MockTranslationProvider",
    "TranslationInput",
    "TranslationOutput",
    "TranslationProvider",
    "TranslationProviderError",
    "translation_provider",
]
