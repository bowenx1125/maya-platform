"""Qwen VC result WAVs carry streaming placeholder sizes; repair only that shape."""

from __future__ import annotations

import io
import struct
import wave

import pytest
from app.providers.audio import AudioValidationError, validate_technical_audio
from app.providers.dashscope import _finalize_streamed_wav

# Observed on qwen3-tts-vc-2026-01-22: both size fields sit just under 2**31,
# and the RIFF field is the data field plus the canonical header span.
_DATA_PLACEHOLDER = 0x7FFFFF9B
_RIFF_PLACEHOLDER = 0x7FFFFFBF


def _wav(seconds: float = 1.5) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24_000)
        frames = int(24_000 * seconds)
        tone = b"".join(
            struct.pack("<h", 3000 if index % 40 < 20 else -3000) for index in range(frames)
        )
        stream.writeframes(tone)
    return buffer.getvalue()


def _with_placeholders(raw: bytes) -> bytes:
    fixed = bytearray(raw)
    offset = 12
    data_at: int | None = None
    while len(fixed) - offset >= 8:
        chunk_id = bytes(fixed[offset : offset + 4])
        chunk_size = int.from_bytes(fixed[offset + 4 : offset + 8], "little")
        if chunk_id == b"data":
            data_at = offset
            break
        offset += 8 + chunk_size + (chunk_size % 2)
    if data_at is None:
        raise AssertionError("fixture has no data chunk")
    fixed[4:8] = (data_at + _DATA_PLACEHOLDER).to_bytes(4, "little")
    fixed[data_at + 4 : data_at + 8] = _DATA_PLACEHOLDER.to_bytes(4, "little")
    return bytes(fixed)


def _streamed(raw: bytes) -> bytes:
    """The canonical 44-byte header shape observed from the supplier."""

    streamed = _with_placeholders(raw)
    assert streamed[4:8] == _RIFF_PLACEHOLDER.to_bytes(4, "little")
    assert streamed[40:44] == _DATA_PLACEHOLDER.to_bytes(4, "little")
    return streamed


def test_streamed_placeholder_sizes_are_repaired() -> None:
    raw = _wav()
    streamed = _streamed(raw)
    with pytest.raises(AudioValidationError):
        validate_technical_audio(streamed)
    repaired = _finalize_streamed_wav(streamed)
    assert repaired == raw
    assert validate_technical_audio(repaired)["duration_seconds"] == pytest.approx(1.5)


def test_placeholder_after_an_extra_chunk_is_repaired() -> None:
    raw = bytearray(_wav())
    # A LIST chunk before data moves the data size field off the canonical offset.
    raw[36:36] = b"LIST" + (4).to_bytes(4, "little") + b"TEST"
    raw[4:8] = (len(raw) - 8).to_bytes(4, "little")
    with_list = bytes(raw)
    repaired = _finalize_streamed_wav(_with_placeholders(with_list))
    assert repaired == with_list
    assert validate_technical_audio(repaired)["duration_seconds"] == pytest.approx(1.5)


def test_complete_truncated_or_non_wav_input_is_unchanged() -> None:
    raw = _wav()
    assert _finalize_streamed_wav(raw) is raw
    truncated = raw[:-80]
    assert _finalize_streamed_wav(truncated) is truncated
    with pytest.raises(AudioValidationError):
        validate_technical_audio(truncated)
    data_only = bytearray(raw)
    data_only[40:44] = _DATA_PLACEHOLDER.to_bytes(4, "little")
    assert _finalize_streamed_wav(bytes(data_only)) == bytes(data_only)
    assert _finalize_streamed_wav(b"not a wav") == b"not a wav"
