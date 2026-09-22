"""Bounded audio probing, normalisation and cleanup primitives for M08.

The module deliberately does not accept an extension as proof of an audio
format.  ``ffprobe`` identifies the container/codec and ``ffmpeg`` creates a
small, deterministic PCM16/24 kHz/mono working file.  No command is executed
through a shell and provider responses are never written to disk here.
"""

from __future__ import annotations

import json
import math
import os
import signal
import struct
import subprocess
import wave
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MIN_ENROLLMENT_SECONDS = 10.0
MAX_ENROLLMENT_SECONDS = 20.0
NORMALIZED_SAMPLE_RATE = 24_000
NORMALIZED_CHANNELS = 1
NORMALIZED_SAMPLE_WIDTH = 2
MAX_PREVIEW_BYTES = 20 * 1024 * 1024


class AudioValidationError(ValueError):
    """Raised for an unsupported, malformed or unsafe audio input/output."""


class AudioProcessError(AudioValidationError):
    """Raised when ffmpeg/ffprobe cannot complete within its bounded budget."""


@dataclass(frozen=True)
class ProbeInfo:
    format_names: tuple[str, ...]
    codec_name: str
    duration_seconds: float
    channels: int
    sample_rate: int
    bits_per_sample: int | None


def safe_source_filename(filename: str) -> str:
    """Return a display-only filename and reject path-like input."""

    if not filename or "\x00" in filename or "/" in filename or "\\" in filename:
        raise AudioValidationError("audio_invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in filename):
        raise AudioValidationError("audio_invalid")
    if len(filename) > 255 or filename in {".", ".."}:
        raise AudioValidationError("audio_invalid")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".wav", ".mp3", ".m4a"}:
        raise AudioValidationError("audio_invalid")
    return filename


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _run_probe(path: Path, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    argv = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=format_name,duration:stream=codec_type,codec_name,duration,channels,sample_rate,bits_per_sample",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            shell=False,
            close_fds=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        raise AudioProcessError("audio_invalid") from exc
    if completed.returncode != 0:
        raise AudioValidationError("audio_invalid")
    try:
        parsed = json.loads(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise AudioValidationError("audio_invalid") from exc
    if not isinstance(parsed, dict):
        raise AudioValidationError("audio_invalid")
    return parsed


def probe_audio(path: Path) -> ProbeInfo:
    """Probe one file and require exactly one usable audio stream."""

    if path.is_symlink() or not path.is_file():
        raise AudioValidationError("audio_invalid")
    parsed = _run_probe(path)
    streams = parsed.get("streams")
    if not isinstance(streams, list):
        raise AudioValidationError("audio_invalid")
    audio_streams = [
        item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"
    ]
    if len(audio_streams) != 1:
        raise AudioValidationError("audio_invalid")
    stream = audio_streams[0]
    format_info = parsed.get("format")
    if not isinstance(format_info, dict):
        raise AudioValidationError("audio_invalid")
    raw_names = format_info.get("format_name")
    if not isinstance(raw_names, str):
        raise AudioValidationError("audio_invalid")
    names = tuple(part.strip().lower() for part in raw_names.split(",") if part.strip())
    codec = stream.get("codec_name")
    if not isinstance(codec, str):
        raise AudioValidationError("audio_invalid")
    duration = _number(stream.get("duration"), _number(format_info.get("duration")))
    if duration <= 0:
        raise AudioValidationError("audio_invalid")
    try:
        channels = int(str(stream.get("channels")))
        sample_rate = int(str(stream.get("sample_rate")))
    except (TypeError, ValueError) as exc:
        raise AudioValidationError("audio_invalid") from exc
    raw_bits = stream.get("bits_per_sample")
    try:
        bits = int(raw_bits) if raw_bits is not None else None
    except (TypeError, ValueError):
        bits = None
    return ProbeInfo(names, codec.lower(), duration, channels, sample_rate, bits)


def validate_source_audio(path: Path, filename: str) -> ProbeInfo:
    """Validate the content and enrollment duration of a user upload."""

    safe_name = safe_source_filename(filename)
    info = probe_audio(path)
    suffix = Path(safe_name).suffix.lower()
    accepted = {
        ".wav": "wav" in info.format_names and info.bits_per_sample == 16,
        ".mp3": "mp3" in info.format_names,
        ".m4a": "m4a" in info.format_names and info.codec_name not in {"mjpeg", "png"},
    }
    if not accepted.get(suffix, False):
        raise AudioValidationError("audio_invalid")
    if not MIN_ENROLLMENT_SECONDS <= info.duration_seconds <= MAX_ENROLLMENT_SECONDS:
        raise AudioValidationError("audio_invalid")
    return info


def _terminate_process(process: subprocess.Popen[bytes], *, wait_seconds: float = 2.0) -> None:
    """Terminate a ffmpeg process, escalating once, and always reap it."""

    if process.poll() is not None:
        return
    try:
        if process.pid and os.name != "nt":
            import_module("os").killpg(process.pid, signal.SIGTERM)
        else:  # pragma: no cover - defensive for a custom process double
            process.terminate()
    except (ProcessLookupError, OSError):
        try:
            process.terminate()
        except OSError:
            pass
    try:
        process.wait(timeout=wait_seconds)
    except subprocess.TimeoutExpired:
        try:
            if process.pid and os.name != "nt":
                import_module("os").killpg(process.pid, import_module("signal").SIGKILL)
            else:
                process.kill()
        except (ProcessLookupError, OSError):
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=wait_seconds)
        except subprocess.TimeoutExpired:
            # A final communicate below still reaps normal Popen instances;
            # do not spin indefinitely on a broken process double.
            pass


def run_ffmpeg_normalize(
    source: Path,
    target: Path,
    *,
    timeout_seconds: float = 30.0,
) -> None:
    """Create deterministic signed PCM16/24 kHz/mono WAV output."""

    # ``ffmpeg -y`` follows an existing symlink.  Refuse that target before a
    # process is started so a stale/crash-created link can never redirect
    # output outside the request directory.
    if target.is_symlink():
        raise AudioValidationError("audio_invalid")
    if target.exists() and not target.is_file():
        raise AudioValidationError("audio_invalid")

    argv = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(NORMALIZED_SAMPLE_RATE),
        "-ac",
        str(NORMALIZED_CHANNELS),
        str(target),
    ]
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _terminate_process(process)
            try:
                process.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass
            raise AudioProcessError("audio_invalid") from exc
        del stdout, stderr
        if process.returncode != 0:
            raise AudioValidationError("audio_invalid")
    except (FileNotFoundError, OSError) as exc:
        if process is not None:
            _terminate_process(process)
        raise AudioProcessError("audio_invalid") from exc
    except BaseException:
        # Cancellation must not leave ffmpeg alive or hold the temporary file.
        if process is not None:
            _terminate_process(process)
            try:
                process.communicate(timeout=2.0)
            except (subprocess.TimeoutExpired, OSError):
                pass
        raise
    finally:
        # ``communicate`` closes the standard pipes for CPython's Popen, but a
        # test double (or a different implementation) may not.  Close every
        # handle before the caller removes the request directory.
        if process is not None:
            for name in ("stdin", "stdout", "stderr"):
                handle = getattr(process, name, None)
                close = getattr(handle, "close", None)
                if callable(close):
                    try:
                        close()
                    except OSError:
                        pass
    if target.is_symlink() or not target.is_file() or target.stat().st_size <= 44:
        raise AudioValidationError("audio_invalid")


def read_pcm16_wav(path: Path, *, max_bytes: int = MAX_PREVIEW_BYTES) -> bytes:
    """Read and validate a normalized/preview WAV without an unbounded read."""

    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise AudioValidationError("audio_invalid")
    try:
        raw = path.read_bytes()
        with wave.open(str(path), "rb") as stream:
            if (
                stream.getnchannels() != NORMALIZED_CHANNELS
                or stream.getsampwidth() != NORMALIZED_SAMPLE_WIDTH
                or stream.getframerate() != NORMALIZED_SAMPLE_RATE
            ):
                raise AudioValidationError("audio_invalid")
            frame_count = stream.getnframes()
            if frame_count <= 0:
                raise AudioValidationError("audio_invalid")
            duration = frame_count / float(NORMALIZED_SAMPLE_RATE)
            if duration <= 0 or duration > 60:
                raise AudioValidationError("audio_invalid")
            if len(raw) <= 44:
                raise AudioValidationError("audio_invalid")
            return raw
    except (OSError, EOFError, wave.Error, struct.error) as exc:
        raise AudioValidationError("audio_invalid") from exc


def _validate_pcm16_wav_structure(raw_wav: bytes, expected_data_bytes: int) -> None:
    """Require a complete RIFF/WAVE container with one exact PCM data chunk."""

    if len(raw_wav) < 12 or raw_wav[:4] != b"RIFF" or raw_wav[8:12] != b"WAVE":
        raise AudioValidationError("audio_invalid")
    try:
        riff_size = struct.unpack_from("<I", raw_wav, 4)[0]
    except struct.error as exc:  # pragma: no cover - length is checked above
        raise AudioValidationError("audio_invalid") from exc
    # Bytes outside the RIFF declaration are not part of the WAV and can hide
    # a truncated or otherwise malformed tail.
    if riff_size != len(raw_wav) - 8:
        raise AudioValidationError("audio_invalid")

    offset = 12
    format_chunks = 0
    data_chunks = 0
    while offset < len(raw_wav):
        if len(raw_wav) - offset < 8:
            raise AudioValidationError("audio_invalid")
        chunk_id = raw_wav[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", raw_wav, offset + 4)[0]
        offset += 8
        if chunk_size > len(raw_wav) - offset:
            raise AudioValidationError("audio_invalid")
        if chunk_id == b"fmt ":
            format_chunks += 1
        elif chunk_id == b"data":
            data_chunks += 1
            if data_chunks > 1 or chunk_size != expected_data_bytes:
                raise AudioValidationError("audio_invalid")
        offset += chunk_size
        if chunk_size % 2:
            # RIFF chunks are word aligned; a missing pad byte is a malformed
            # tail even when the preceding bytes happen to decode as audio.
            if offset >= len(raw_wav):
                raise AudioValidationError("audio_invalid")
            offset += 1
    if offset != len(raw_wav) or format_chunks != 1 or data_chunks != 1:
        raise AudioValidationError("audio_invalid")


def audio_quality_metrics(raw_wav: bytes) -> dict[str, float]:
    """Compute bounded technical acceptance metrics for PCM16 WAV bytes."""

    try:
        import io

        with wave.open(io.BytesIO(raw_wav), "rb") as stream:
            if (
                stream.getnchannels() != 1
                or stream.getsampwidth() != 2
                or stream.getframerate() != NORMALIZED_SAMPLE_RATE
            ):
                raise AudioValidationError("audio_invalid")
            declared_frames = stream.getnframes()
            if declared_frames <= 0:
                raise AudioValidationError("audio_invalid")
            frames = stream.readframes(declared_frames)
            expected_data_bytes = declared_frames * NORMALIZED_CHANNELS * NORMALIZED_SAMPLE_WIDTH
            # ``wave`` can open a container whose data chunk declares more
            # bytes than are actually available.  Acceptance requires the
            # read to match the declared frame count exactly, including an
            # even PCM16 byte count.
            if len(frames) != expected_data_bytes or len(frames) % NORMALIZED_SAMPLE_WIDTH:
                raise AudioValidationError("audio_invalid")
            _validate_pcm16_wav_structure(raw_wav, expected_data_bytes)
    except (OSError, EOFError, wave.Error, struct.error) as exc:
        raise AudioValidationError("audio_invalid") from exc
    if len(frames) < NORMALIZED_SAMPLE_WIDTH:
        raise AudioValidationError("audio_invalid")
    sample_count = len(frames) // NORMALIZED_SAMPLE_WIDTH
    samples = struct.unpack(f"<{sample_count}h", frames)
    squared = sum(sample * sample for sample in samples)
    nonzero = sum(sample != 0 for sample in samples)
    clipped = sum(abs(sample) >= 32760 for sample in samples)
    rms = math.sqrt(squared / sample_count)
    return {
        "duration_seconds": sample_count / float(NORMALIZED_SAMPLE_RATE),
        "rms": rms,
        "nonzero_fraction": nonzero / float(sample_count),
        "clipped_fraction": clipped / float(sample_count),
    }


def validate_technical_audio(raw_wav: bytes) -> dict[str, float]:
    metrics = audio_quality_metrics(raw_wav)
    if not 1.0 <= metrics["duration_seconds"] <= 60.0:
        raise AudioValidationError("audio_invalid")
    if metrics["rms"] < 100 or metrics["nonzero_fraction"] < 0.01:
        raise AudioValidationError("audio_invalid")
    if metrics["clipped_fraction"] >= 0.05:
        raise AudioValidationError("audio_invalid")
    return metrics
