"""CosyVoice streaming TTS adapter (word-level timestamps for the 3D stage).

Unlike the qwen3-tts HTTP path, CosyVoice streams over a workspace-scoped
WebSocket and can return per-character timestamps in the same synthesis. The
SDK session is blocking, so the debate pipeline must call synthesize() via
asyncio.to_thread like the other real providers.

The dashscope SDK is an optional dependency: when it is not installed the
provider refuses before any outbound request (tts_provider_unavailable), which
keeps the debate text-only fallback eligible instead of failing the turn.
"""

from __future__ import annotations

import io
import wave
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.providers.audio import AudioValidationError, validate_speech_audio
from app.providers.tts import (
    TTSAudioInvalidError,
    TTSHTTPRejectedError,
    TTSProviderError,
    TTSProviderTimeout,
    TTSProviderUnavailableError,
    TTSResponseInvalidError,
    TTSResult,
    WordTimestamp,
)

COSYVOICE_DEFAULT_MODEL = "cosyvoice-v3-flash"
COSYVOICE_DEFAULT_VOICE = "longanyang"
COSYVOICE_SAMPLE_RATE = 24000  # NORMALIZED_SAMPLE_RATE: acceptance rejects other rates
COSYVOICE_TIMEOUT_SECONDS = 120.0
# Estimated consonant tail between a sentence's last word end and the next
# sentence's first word; the final sentence absorbs the remaining audio.
_SENTENCE_TAIL_MS = 60.0


@dataclass(frozen=True)
class CosyVoiceConfig:
    api_key: str
    workspace_id: str
    region: str
    target_model_key: str = COSYVOICE_DEFAULT_MODEL
    voice: str = COSYVOICE_DEFAULT_VOICE
    sample_rate: int = COSYVOICE_SAMPLE_RATE
    timeout_seconds: float = COSYVOICE_TIMEOUT_SECONDS


class CosyVoiceTTSProvider:
    """Streaming CosyVoice adapter returning WAV bytes plus word timestamps."""

    key = "cosyvoice"

    def __init__(self, config: CosyVoiceConfig) -> None:
        if config.region != "cn-beijing" or not config.api_key or not config.workspace_id:
            raise TTSProviderUnavailableError("cosyvoice provider is not configured")
        self.config = config
        self.target_model_key = config.target_model_key

    def synthesize(
        self,
        text: str,
        external_voice_id: str,
        *,
        language: str = "en",
        target_model_key: str | None = None,
        voice_params: Mapping[str, object] | None = None,
    ) -> TTSResult:
        del language  # CosyVoice detects the language from the text itself.
        del voice_params  # System voices take no per-clone params.
        if not text.strip():
            raise TTSProviderError("empty text")
        model = target_model_key or self.target_model_key
        pcm, sentences = self._run_session(text, model, external_voice_id)
        if not pcm:
            raise TTSResponseInvalidError("cosyvoice returned no audio")
        total_ms = len(pcm) / 2.0 / self.config.sample_rate * 1000.0
        timestamps = tuple(self._absolute_words(sentences, total_ms))
        wav = self._pcm_to_wav(pcm, self.config.sample_rate)
        try:
            validate_speech_audio(wav)
        except AudioValidationError as exc:
            raise TTSAudioInvalidError("cosyvoice audio invalid") from exc
        return TTSResult(
            audio_bytes=wav,
            content_type="audio/wav",
            word_timestamps=timestamps,
        )

    def _run_session(self, text: str, model: str, voice: str) -> tuple[bytes, list[dict[str, Any]]]:
        try:
            import dashscope
        except ImportError as exc:
            raise TTSProviderUnavailableError("cosyvoice sdk unavailable") from exc

        client = dashscope.Client(
            api_key=self.config.api_key,
            workspace=self.config.workspace_id,
            region=self.config.region,
        )
        chunks: list[bytes] = []
        sentences: list[dict[str, Any]] = []
        try:
            with client.audio.tts.connect(
                model=model,
                voice=voice,
                format="pcm",
                sample_rate=self.config.sample_rate,
                parameters={"word_timestamp_enabled": True},
            ) as session:
                session.send_text(text)
                session.flush()
                session.stop()
                for event in session.events():
                    if isinstance(event, (bytes, bytearray)):
                        chunks.append(bytes(event))
                        continue
                    header = event.get("header") or {}
                    payload = event.get("payload") or {}
                    output = payload.get("output") or {}
                    if output.get("type") == "sentence-end":
                        sentence = output.get("sentence") or {}
                        sentences.append({"words": sentence.get("words") or []})
                    if header.get("event") == "task-failed":
                        # Provider messages are not echoed: bounded code only.
                        raise TTSResponseInvalidError("cosyvoice task failed")
        except TTSProviderError:
            raise
        except TimeoutError as exc:
            raise TTSProviderTimeout("cosyvoice request timed out") from exc
        except Exception as exc:
            raise TTSHTTPRejectedError("cosyvoice request failed") from exc
        return b"".join(chunks), sentences

    @staticmethod
    def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
        stream = io.BytesIO()
        with wave.open(stream, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm)
        return stream.getvalue()

    @staticmethod
    def _absolute_words(sentences: list[dict[str, Any]], total_ms: float) -> list[WordTimestamp]:
        """Fold sentence-relative word times into absolute milliseconds."""
        out: list[WordTimestamp] = []
        offset = 0.0
        last_index = len(sentences) - 1
        for index, sentence in enumerate(sentences):
            words = sentence.get("words") or []
            for word in words:
                out.append(
                    {
                        "text": word.get("text"),
                        "begin_index": word.get("begin_index"),
                        "end_index": word.get("end_index"),
                        "begin_ms": min(offset + float(word.get("begin_time") or 0.0), total_ms),
                        "end_ms": min(offset + float(word.get("end_time") or 0.0), total_ms),
                    }
                )
            if index < last_index:
                tail = max((float(w.get("end_time") or 0.0) for w in words), default=0.0)
                offset += tail + _SENTENCE_TAIL_MS
        return out
