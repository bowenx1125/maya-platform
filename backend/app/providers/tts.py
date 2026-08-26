"""Provider-neutral TTS port and deterministic local WAV adapter."""

from __future__ import annotations

import hashlib
import io
import math
import struct
import wave
from dataclasses import dataclass
from typing import Protocol


class TTSProviderError(RuntimeError):
    """A TTS adapter failure safe to map to a platform error code."""


class TTSProviderTimeout(TTSProviderError):
    """A TTS request exceeded its bounded deadline."""


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
