"""Provider-neutral voice-cloning port and the deterministic Mock adapter."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from typing import Protocol


class VoiceProviderError(RuntimeError):
    """A provider failure whose message is never copied to a public response."""


class VoiceProviderTimeout(VoiceProviderError):
    """A provider request exceeded its bounded deadline."""


class VoiceProviderAmbiguous(VoiceProviderError):
    """A request may have been charged but its outcome is not yet visible."""


class VoiceCloneRefusedError(VoiceProviderError):
    """A deterministic refusal to clone, raised before any network I/O.

    The refusal is known locally (for example the flash model key), so it can
    never be ambiguous and must not be retried or re-routed to another
    provider.
    """


@dataclass(frozen=True)
class VoiceEnrollmentResult:
    """Internal result returned by a voice enrollment adapter."""

    external_voice_id: str
    request_id: str | None = None
    input_bytes: int = 0
    output_bytes: int = 0
    charged: bool = True
    degraded: bool = False


@dataclass(frozen=True)
class VoiceExistenceResult:
    """Provider-side reconciliation result for one deterministic name."""

    matches: tuple[str, ...]
    visibility_known: bool = True

    @property
    def match_count(self) -> int:
        return len(self.matches)


class VoiceCloneProvider(Protocol):
    """The only voice operations business services may depend on."""

    key: str
    target_model_key: str

    def enroll(
        self,
        audio_data_uri: str,
        *,
        recovery_name: str,
        target_model_key: str,
        language: str = "en",
        transcript: str | None = None,
    ) -> VoiceEnrollmentResult:
        """Create one external voice from an in-memory normalized audio URI."""

    def exists(
        self,
        recovery_name: str,
        *,
        target_model_key: str,
    ) -> VoiceExistenceResult:
        """List/reconcile provider resources matching a recovery name."""

    def delete(self, external_voice_id: str, *, target_model_key: str) -> None:
        """Delete one previously mapped external voice."""


class MockVoiceCloneProvider:
    """Deterministic in-process provider used by tests and local Demo."""

    key = "mock"
    target_model_key = "mock-voice-v1"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._voices: dict[str, str] = {}
        self._forced_matches: dict[str, tuple[str, ...]] = {}
        self.enroll_calls = 0
        self.exists_calls = 0
        self.delete_calls = 0
        self.last_language = "en"
        self.next_enroll_error: VoiceProviderError | None = None
        self.next_exists_error: VoiceProviderError | None = None
        self.next_delete_error: VoiceProviderError | None = None

    def enroll(
        self,
        audio_data_uri: str,
        *,
        recovery_name: str,
        target_model_key: str,
        language: str = "en",
        transcript: str | None = None,
    ) -> VoiceEnrollmentResult:
        self.last_language = language
        del transcript
        with self._lock:
            self.enroll_calls += 1
            failure = self.next_enroll_error
            self.next_enroll_error = None
            if failure is not None:
                raise failure
            if recovery_name not in self._voices:
                digest = hashlib.sha256(audio_data_uri.encode("utf-8")).hexdigest()[:32]
                self._voices[recovery_name] = f"mock-voice-{digest}"
            return VoiceEnrollmentResult(
                external_voice_id=self._voices[recovery_name],
                request_id=f"mock-request-{self.enroll_calls}",
                input_bytes=len(audio_data_uri.encode("utf-8")),
                charged=True,
            )

    def exists(
        self,
        recovery_name: str,
        *,
        target_model_key: str,
    ) -> VoiceExistenceResult:
        del target_model_key
        with self._lock:
            self.exists_calls += 1
            failure = self.next_exists_error
            self.next_exists_error = None
            if failure is not None:
                raise failure
            if recovery_name in self._forced_matches:
                return VoiceExistenceResult(self._forced_matches[recovery_name])
            value = self._voices.get(recovery_name)
            return VoiceExistenceResult((value,) if value else ())

    def delete(self, external_voice_id: str, *, target_model_key: str) -> None:
        del target_model_key
        with self._lock:
            self.delete_calls += 1
            failure = self.next_delete_error
            self.next_delete_error = None
            if failure is not None:
                raise failure
            for recovery_name, value in tuple(self._voices.items()):
                if value == external_voice_id:
                    del self._voices[recovery_name]

    def set_reconciliation_matches(self, recovery_name: str, matches: tuple[str, ...]) -> None:
        with self._lock:
            self._forced_matches[recovery_name] = matches

    def clear_reconciliation_matches(self, recovery_name: str) -> None:
        with self._lock:
            self._forced_matches.pop(recovery_name, None)
