"""Debate speeches as MP3: an in-memory copy of validated WAV bytes (PR C)."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import wave
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.modules.debates.playback.audio import (
    AUDIO_CACHE_MAX_AGE_SECONDS,
    AudioStore,
    CompressedAudio,
    Mp3Transcoder,
    playback_transcoder,
)
from app.modules.debates.playback.service import PlaybackService
from app.providers.tts import MockTTSProvider


def _wav(frames: int = 800, tone: int = 0) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8_000)
        wav.writeframes(bytes([tone & 0xFF, 0]) * frames)
    return stream.getvalue()


class CountingTranscoder(Mp3Transcoder):
    """Deterministic stand-in for ffmpeg: the 'MP3' is a tagged digest."""

    def __init__(self, *, max_bytes: int = 1024 * 1024) -> None:
        super().__init__(executable="fake-ffmpeg", max_bytes=max_bytes)
        self.encoded: list[str] = []
        self.fail = False

    def encode(self, wav_sha256: str, raw: bytes) -> CompressedAudio | None:
        found = self.cached(wav_sha256)
        if found is not None:
            return found
        if self.fail:
            return None
        self.encoded.append(wav_sha256)
        body = b"ID3" + hashlib.sha256(raw).digest() * 4
        encoded = CompressedAudio(body=body, sha256=hashlib.sha256(body).hexdigest())
        self._store(wav_sha256, encoded)
        return encoded


def _store(tmp_path: Path, transcoder: Mp3Transcoder | None) -> tuple[AudioStore, str, str]:
    store = AudioStore(tmp_path, tts_provider=MockTTSProvider(), transcoder=transcoder)
    course_id, debate_id, turn_id = (str(uuid4()) for _ in range(3))
    store.store_bytes(course_id=course_id, debate_id=debate_id, turn_id=turn_id, raw=_wav())
    return store, debate_id, turn_id


def test_mp3_is_encoded_once_and_served_from_memory_with_its_own_etag(tmp_path: Path) -> None:
    transcoder = CountingTranscoder()
    store, debate_id, turn_id = _store(tmp_path, transcoder)

    first = store.response(debate_id, turn_id, audio_format="mp3")
    again = store.response(debate_id, turn_id, audio_format="mp3")

    assert first.status_code == 200
    assert first.media_type == "audio/mpeg"
    assert first.body.startswith(b"ID3")
    assert first.etag == f'"{hashlib.sha256(first.body).hexdigest()}"'
    assert again.body == first.body
    assert len(transcoder.encoded) == 1
    assert first.headers["Cache-Control"] == f"private, max-age={AUDIO_CACHE_MAX_AGE_SECONDS}"
    assert "Pragma" not in first.headers

    partial = store.response(debate_id, turn_id, audio_format="mp3", range_header="bytes=0-9")
    assert partial.status_code == 206
    assert partial.body == first.body[:10]
    assert partial.headers["Content-Range"] == f"bytes 0-9/{len(first.body)}"
    assert partial.media_type == "audio/mpeg"


def test_wav_stays_the_default_and_is_unchanged(tmp_path: Path) -> None:
    store, debate_id, turn_id = _store(tmp_path, CountingTranscoder())
    response = store.response(debate_id, turn_id)
    assert response.media_type == "audio/wav"
    assert response.body == _wav()
    assert response.etag == f'"{hashlib.sha256(_wav()).hexdigest()}"'


def test_if_none_match_answers_304_without_a_body(tmp_path: Path) -> None:
    store, debate_id, turn_id = _store(tmp_path, CountingTranscoder())
    full = store.response(debate_id, turn_id, audio_format="mp3")
    cached = store.response(debate_id, turn_id, audio_format="mp3", if_none_match=full.etag)
    assert cached.status_code == 304
    assert cached.body == b""
    assert cached.headers["ETag"] == full.etag
    assert "Content-Length" not in cached.headers
    other = store.response(debate_id, turn_id, if_none_match=full.etag)
    assert other.status_code == 200  # the WAV has a different validator


def test_a_failed_encode_falls_back_to_the_wav(tmp_path: Path) -> None:
    transcoder = CountingTranscoder()
    transcoder.fail = True
    store, debate_id, turn_id = _store(tmp_path, transcoder)
    response = store.response(debate_id, turn_id, audio_format="mp3")
    assert response.status_code == 200
    assert response.media_type == "audio/wav"
    assert response.body == _wav()


def test_removing_a_speech_evicts_its_copy(tmp_path: Path) -> None:
    transcoder = CountingTranscoder()
    store, debate_id, turn_id = _store(tmp_path, transcoder)
    store.response(debate_id, turn_id, audio_format="mp3")
    wav_sha = transcoder.encoded[0]
    assert transcoder.cached(wav_sha) is not None

    store.remove_turn(debate_id, turn_id)
    assert transcoder.cached(wav_sha) is None
    with pytest.raises(FileNotFoundError):
        store.response(debate_id, turn_id, audio_format="mp3")


def test_removing_a_debate_evicts_every_copy(tmp_path: Path) -> None:
    transcoder = CountingTranscoder()
    store, debate_id, turn_id = _store(tmp_path, transcoder)
    store.response(debate_id, turn_id, audio_format="mp3")
    store.remove_debate(debate_id)
    assert all(transcoder.cached(sha) is None for sha in transcoder.encoded)


def test_a_changed_wav_is_validated_again_before_any_copy_is_served(tmp_path: Path) -> None:
    transcoder = CountingTranscoder()
    store, debate_id, turn_id = _store(tmp_path, transcoder)
    store.response(debate_id, turn_id, audio_format="mp3")
    metadata = store.metadata(debate_id, turn_id)
    assert metadata is not None
    path = store.path_for(metadata.relative_path)
    raw = path.read_bytes()
    path.write_bytes(raw[:44] + bytes([raw[44] ^ 1]) + raw[45:])
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    # The tampered bytes no longer match the durable digest: nothing is served.
    with pytest.raises(FileNotFoundError):
        store.response(debate_id, turn_id, audio_format="mp3")


def test_a_replaced_speech_gets_a_new_copy(tmp_path: Path) -> None:
    transcoder = CountingTranscoder()
    store, debate_id, turn_id = _store(tmp_path, transcoder)
    first = store.response(debate_id, turn_id, audio_format="mp3")
    metadata = store.metadata(debate_id, turn_id)
    assert metadata is not None
    store.store_bytes(
        course_id=metadata.course_id, debate_id=debate_id, turn_id=turn_id, raw=_wav(tone=7)
    )
    second = store.response(debate_id, turn_id, audio_format="mp3")
    assert second.body != first.body
    assert len(transcoder.encoded) == 2
    assert transcoder.cached(transcoder.encoded[0]) is None


def test_the_cache_drops_the_least_recently_used_copy(tmp_path: Path) -> None:
    transcoder = CountingTranscoder(max_bytes=200)
    a = CompressedAudio(body=b"a" * 120, sha256="a")
    b = CompressedAudio(body=b"b" * 120, sha256="b")
    transcoder._store("one", a)
    transcoder._store("two", b)
    assert transcoder.cached("one") is None
    assert transcoder.cached("two") == b


def test_mp3_is_off_unless_configured_and_ffmpeg_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    assert playback_transcoder(SimpleNamespace(debate_audio_mp3=False)) is None
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert playback_transcoder(SimpleNamespace(debate_audio_mp3=True)) is None
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    assert isinstance(playback_transcoder(SimpleNamespace(debate_audio_mp3=True)), Mp3Transcoder)
    assert (
        AudioStore(Path("/nonexistent"), transcoder=Mp3Transcoder(executable="")).compressed
        is False
    )


def test_media_urls_ask_for_mp3_only_when_the_store_can_encode(tmp_path: Path) -> None:
    debate_id, turn_id, token = str(uuid4()), str(uuid4()), "t" * 43
    plain = SimpleNamespace(audio_store=AudioStore(tmp_path))
    compressed = SimpleNamespace(audio_store=AudioStore(tmp_path, transcoder=CountingTranscoder()))
    base = f"/api/v1/debates/{debate_id}/audio/{turn_id}?media_ticket={token}"
    assert PlaybackService._media_url(plain, debate_id, turn_id, token) == base  # type: ignore[arg-type]
    assert (
        PlaybackService._media_url(compressed, debate_id, turn_id, token)  # type: ignore[arg-type]
        == f"{base}&format=mp3"
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_ffmpeg_produces_a_much_smaller_mp3(tmp_path: Path) -> None:
    transcoder = Mp3Transcoder()
    store = AudioStore(tmp_path, transcoder=transcoder)
    course_id, debate_id, turn_id = (str(uuid4()) for _ in range(3))
    raw = _wav(frames=8_000 * 3, tone=40)
    store.store_bytes(course_id=course_id, debate_id=debate_id, turn_id=turn_id, raw=raw)
    response = store.response(debate_id, turn_id, audio_format="mp3")
    assert response.media_type == "audio/mpeg"
    assert response.body[:3] == b"ID3" or response.body[:2] in {b"\xff\xfb", b"\xff\xf3"}
    assert len(response.body) < len(raw)
