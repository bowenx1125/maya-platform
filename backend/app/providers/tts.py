"""Provider-neutral TTS port and deterministic local WAV adapter."""

from __future__ import annotations

import hashlib
import io
import math
import struct
import wave
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, TypedDict

TTS_UNAVAILABLE_CODES = frozenset(
    {
        "tts_voice_unavailable",
        "tts_provider_unavailable",
        "tts_timeout",
        "tts_http_rejected",
        "tts_response_invalid",
        "tts_result_url_rejected",
        "tts_result_dns_failed",
        "tts_result_download_failed",
        "tts_audio_invalid",
    }
)


class TTSProviderError(RuntimeError):
    """A TTS adapter failure carrying a bounded internal classification."""

    safe_code = "tts_response_invalid"

    def __init__(
        self, message: str = "TTS provider error", *, safe_code: str | None = None
    ) -> None:
        super().__init__(message)
        self.safe_code = safe_code or type(self).safe_code


class TTSProviderTimeout(TTSProviderError):
    """A TTS request exceeded its bounded deadline."""

    safe_code = "tts_timeout"


class TTSVoiceUnavailableError(TTSProviderError):
    """No authorized ready voice is available for the accepted text."""

    safe_code = "tts_voice_unavailable"


class TTSProviderUnavailableError(TTSProviderError):
    """The selected speech provider is blocked before any outbound request."""

    safe_code = "tts_provider_unavailable"


class TTSHTTPRejectedError(TTSProviderError):
    """The TTS HTTP request was rejected or could not be completed."""

    safe_code = "tts_http_rejected"


class TTSResponseInvalidError(TTSProviderError):
    """The TTS response did not match the expected provider schema."""

    safe_code = "tts_response_invalid"


class TTSResultURLRejectedError(TTSProviderError):
    """The provider result URL failed the bounded allowlist checks."""

    safe_code = "tts_result_url_rejected"


class TTSResultDNSFailedError(TTSProviderError):
    """The provider result host could not be resolved safely."""

    safe_code = "tts_result_dns_failed"


class TTSResultDownloadError(TTSProviderError):
    """The provider result object could not be downloaded safely."""

    safe_code = "tts_result_download_failed"


class TTSAudioInvalidError(TTSProviderError):
    """The downloaded provider bytes failed technical audio validation."""

    safe_code = "tts_audio_invalid"


@dataclass(frozen=True)
class TTSResult:
    audio_bytes: bytes
    content_type: str = "audio/wav"
    request_id: str | None = None
    # CosyVoice-only: character-level timestamps over the returned audio, used
    # by the debate performance compiler for gesture anchoring and lip visemes.
    word_timestamps: tuple[WordTimestamp, ...] | None = None


class WordTimestamp(TypedDict):
    text: str | None
    begin_index: int | None
    end_index: int | None
    begin_ms: float
    end_ms: float


# Only pre-request refusals may degrade to the fallback provider. A failure
# after the supplier may have started synthesis (timeout, invalid audio) was
# potentially charged and is never auto-retried.
FALLBACK_BEFORE_REQUEST_CODES = frozenset({"tts_provider_unavailable", "tts_voice_unavailable"})


class FallbackTTSProvider:
    """Debate TTS that degrades from CosyVoice to qwen3 on pre-request refusals."""

    def __init__(self, primary: TTSProvider, fallback: TTSProvider) -> None:
        self._primary = primary
        self._fallback = fallback
        self.key = primary.key
        self.target_model_key = primary.target_model_key

    def synthesize(
        self,
        text: str,
        external_voice_id: str,
        *,
        language: str = "en",
        target_model_key: str | None = None,
        voice_params: Mapping[str, object] | None = None,
    ) -> TTSResult:
        try:
            return self._primary.synthesize(
                text,
                external_voice_id,
                language=language,
                target_model_key=target_model_key,
                voice_params=voice_params,
            )
        except TTSProviderError as exc:
            if exc.safe_code not in FALLBACK_BEFORE_REQUEST_CODES:
                raise
        return self._fallback.synthesize(
            text,
            external_voice_id,
            language=language,
            target_model_key=target_model_key,
            voice_params=voice_params,
        )


class TTSProvider(Protocol):
    key: str
    target_model_key: str

    def synthesize(
        self,
        text: str,
        external_voice_id: str,
        *,
        language: str = "en",
        target_model_key: str | None = None,
        voice_params: Mapping[str, object] | None = None,
    ) -> TTSResult:
        """Synthesize audio for an already-authorized internal voice mapping.

        ``voice_params`` (rate, instruction, seed) apply to cloned voices only;
        a provider drops them for models that do not take them.
        """


def _mock_wav(text: str, external_voice_id: str) -> bytes:
    """Create a short non-empty PCM16 WAV deterministically from text/voice."""

    digest = hashlib.sha256(f"{external_voice_id}\0{text}".encode()).digest()
    # At least one second keeps technical fallback acceptance meaningful while
    # remaining small enough for previews and unit tests.
    frames = 24_000
    base_frequency = 200 + digest[0] % 180
    amplitude = 4_000 + digest[1] % 2_000
    payload = bytearray()
    for index in range(frames):
        sample = int(amplitude * math.sin(2.0 * math.pi * base_frequency * index / 24_000.0))
        payload.extend(struct.pack("<h", sample))
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24_000)
        wav.writeframes(bytes(payload))
    return stream.getvalue()


class MockTTSProvider:
    """Local Mock that produces valid PCM16/24 kHz/mono WAV bytes."""

    key = "mock"
    target_model_key = "mock-tts-v1"

    def __init__(self) -> None:
        self.synthesize_calls = 0
        self.last_text: str | None = None
        self.last_voice_id: str | None = None
        self.last_voice_params: dict[str, object] | None = None
        self.next_error: TTSProviderError | None = None

    def synthesize(
        self,
        text: str,
        external_voice_id: str,
        *,
        language: str = "en",
        target_model_key: str | None = None,
        voice_params: Mapping[str, object] | None = None,
    ) -> TTSResult:
        del language, target_model_key
        if self.next_error is not None:
            failure = self.next_error
            self.next_error = None
            raise failure
        self.synthesize_calls += 1
        self.last_text = text
        self.last_voice_id = external_voice_id
        self.last_voice_params = dict(voice_params) if voice_params else None
        return TTSResult(
            audio_bytes=_mock_wav(text, external_voice_id),
            request_id=f"mock-tts-request-{self.synthesize_calls}",
        )
