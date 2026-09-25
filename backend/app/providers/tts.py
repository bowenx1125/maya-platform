"""Provider-neutral TTS port and deterministic local WAV adapter."""

from __future__ import annotations

import hashlib
import io
import math
import re
import struct
import wave
from dataclasses import dataclass
from typing import Protocol


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


# Chat replies cite evidence as [S1] or [S1, S2]. Fullwidth brackets are the
# same marker. Debate speech is not supposed to contain these; a speech
# without them is returned unchanged so its audio stays tied to the exact text.
_CITATION_MARKER = re.compile(r"[\[［]\s*S\d+(?:\s*,\s*S\d+)*\s*[\]］]")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([,.;:!?，。、；：！？])")
_DANGLING_COMMA = re.compile(r"[,，、]+(?=[.。!！?？;；:：])")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_MULTI_BREAK = re.compile(r"\n{3,}")
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def spoken_text(value: str) -> str:
    """Text for synthesis. Displayed replies keep citation markers."""

    if not _CITATION_MARKER.search(value):
        return value
    without = _CITATION_MARKER.sub("", value)
    without = _SPACE_BEFORE_PUNCT.sub(r"\1", without)
    without = _DANGLING_COMMA.sub("", without)
    without = _MULTI_SPACE.sub(" ", without)
    lines = [line.strip() for line in without.split("\n")]
    return _MULTI_BREAK.sub("\n\n", "\n".join(lines)).strip()


def reply_uses_chinese(value: str) -> bool:
    """True when the spoken reply contains Han characters."""

    return _HAN.search(value) is not None


@dataclass(frozen=True)
class TTSResult:
    audio_bytes: bytes
    content_type: str = "audio/wav"
    request_id: str | None = None


class TTSProvider(Protocol):
    key: str
    target_model_key: str

    def synthesize(
        self,
        text: str,
        external_voice_id: str,
        *,
        language: str = "en",
    ) -> TTSResult:
        """Synthesize audio for an already-authorized internal voice mapping."""


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
        self.next_error: TTSProviderError | None = None

    def synthesize(
        self,
        text: str,
        external_voice_id: str,
        *,
        language: str = "en",
    ) -> TTSResult:
        del language
        if self.next_error is not None:
            failure = self.next_error
            self.next_error = None
            raise failure
        self.synthesize_calls += 1
        self.last_text = text
        self.last_voice_id = external_voice_id
        return TTSResult(
            audio_bytes=_mock_wav(text, external_voice_id),
            request_id=f"mock-tts-request-{self.synthesize_calls}",
        )
