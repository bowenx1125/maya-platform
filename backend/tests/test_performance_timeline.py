"""AudioStore checks for the debate performance timeline sibling files."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from app.modules.debates.playback.audio import AudioStore
from app.providers.tts import MockTTSProvider, TTSResult

SPEECH = "首先，我方认为这个论点毫无疑问成立。综上所述，谢谢各位。"


class TimestampedMock(MockTTSProvider):
    """Mock provider that also returns CosyVoice-style word timestamps."""

    def synthesize(
        self,
        text: str,
        external_voice_id: str,
        *,
        language: str = "en",
        target_model_key: str | None = None,
        voice_params: object = None,
    ) -> TTSResult:
        base = super().synthesize(
            text,
            external_voice_id,
            language=language,
            target_model_key=target_model_key,
            voice_params=voice_params,  # type: ignore[arg-type]
        )
        # CosyVoice tokenizes Chinese one character per timestamp entry.
        words = []
        begin_ms = 0.0
        for index, ch in enumerate(text):
            dur = 180.0 if ch.strip() else 60.0
            words.append(
                {
                    "text": ch,
                    "begin_index": index,
                    "end_index": index + 1,
                    "begin_ms": float(begin_ms),
                    "end_ms": begin_ms + dur,
                }
            )
            begin_ms += dur + 30.0
        return TTSResult(
            audio_bytes=base.audio_bytes,
            request_id=base.request_id,
            word_timestamps=tuple(words),
        )


def _ids() -> tuple[str, str, str]:
    return str(uuid4()), str(uuid4()), str(uuid4())


def _compiled(payload: bytes) -> dict[str, object]:
    parsed = json.loads(payload.decode("utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def test_stage_synthesis_compiles_and_stages_timeline(tmp_path: Path) -> None:
    course_id, debate_id, turn_id = _ids()
    store = AudioStore(tmp_path, tts_provider=TimestampedMock())

    staged = store.stage_synthesis(
        course_id=course_id,
        debate_id=debate_id,
        turn_id=turn_id,
        speech=SPEECH,
        voice_token="mock",
    )

    assert staged.performance_relative_path is not None
    staged_json = tmp_path / staged.performance_relative_path
    assert staged_json.is_file()
    compiled = _compiled(staged_json.read_bytes())
    assert compiled["events"]
    assert compiled["visemes"]


def test_promote_moves_timeline_next_to_canonical_wav(tmp_path: Path) -> None:
    course_id, debate_id, turn_id = _ids()
    store = AudioStore(tmp_path, tts_provider=TimestampedMock())

    staged = store.stage_synthesis(
        course_id=course_id,
        debate_id=debate_id,
        turn_id=turn_id,
        speech=SPEECH,
        voice_token="mock",
    )
    store.promote_staged_audio(staged)

    audio = store.read(debate_id, turn_id)
    assert audio is not None
    performance = store.read_performance(debate_id, turn_id)
    assert performance is not None
    compiled = _compiled(performance)
    assert compiled["duration"] > 0
    assert compiled["events"]
    canonical_json = tmp_path / (
        f"courses/{course_id}/current-debate-audio/{debate_id}/{turn_id}.performance.json"
    )
    assert canonical_json.is_file()
    assert not (tmp_path / staged.relative_path).exists()
    assert not (tmp_path / staged.performance_relative_path).exists()


def test_plain_audio_has_no_timeline_anywhere(tmp_path: Path) -> None:
    course_id, debate_id, turn_id = _ids()
    store = AudioStore(tmp_path, tts_provider=MockTTSProvider())

    staged = store.stage_synthesis(
        course_id=course_id,
        debate_id=debate_id,
        turn_id=turn_id,
        speech=SPEECH,
        voice_token="mock",
    )

    assert staged.performance_relative_path is None
    store.promote_staged_audio(staged)
    assert store.read(debate_id, turn_id) is not None
    assert store.read_performance(debate_id, turn_id) is None
    assert not list((tmp_path / "courses").rglob("*.performance.json"))


def test_synthesize_and_store_writes_canonical_timeline(tmp_path: Path) -> None:
    course_id, debate_id, turn_id = _ids()
    store = AudioStore(tmp_path, tts_provider=TimestampedMock())

    store.synthesize_and_store(
        course_id=course_id,
        debate_id=debate_id,
        turn_id=turn_id,
        speech=SPEECH,
        voice_token="mock",
    )

    performance = store.read_performance(debate_id, turn_id)
    assert performance is not None
    assert _compiled(performance)["events"]


def test_discard_staged_audio_removes_timeline_pair(tmp_path: Path) -> None:
    course_id, debate_id, turn_id = _ids()
    store = AudioStore(tmp_path, tts_provider=TimestampedMock())

    staged = store.stage_synthesis(
        course_id=course_id,
        debate_id=debate_id,
        turn_id=turn_id,
        speech=SPEECH,
        voice_token="mock",
    )
    store.discard_staged_audio(staged)

    assert not (tmp_path / staged.relative_path).exists()
    assert not (tmp_path / staged.performance_relative_path).exists()


def test_remove_promoted_audio_if_owned_removes_timeline(tmp_path: Path) -> None:
    course_id, debate_id, turn_id = _ids()
    store = AudioStore(tmp_path, tts_provider=TimestampedMock())

    staged = store.stage_synthesis(
        course_id=course_id,
        debate_id=debate_id,
        turn_id=turn_id,
        speech=SPEECH,
        voice_token="mock",
    )
    store.promote_staged_audio(staged)
    canonical_json = tmp_path / (
        f"courses/{course_id}/current-debate-audio/{debate_id}/{turn_id}.performance.json"
    )
    assert canonical_json.is_file()

    assert store.remove_promoted_audio_if_owned(staged) is True
    assert store.read(debate_id, turn_id) is None
    assert store.read_performance(debate_id, turn_id) is None
    assert not canonical_json.exists()


def test_remove_turn_removes_timeline_with_audio(tmp_path: Path) -> None:
    course_id, debate_id, turn_id = _ids()
    store = AudioStore(tmp_path, tts_provider=TimestampedMock())

    store.synthesize_and_store(
        course_id=course_id,
        debate_id=debate_id,
        turn_id=turn_id,
        speech=SPEECH,
        voice_token="mock",
    )
    canonical_json = tmp_path / (
        f"courses/{course_id}/current-debate-audio/{debate_id}/{turn_id}.performance.json"
    )
    assert canonical_json.is_file()

    store.remove_turn(debate_id, turn_id)

    assert store.read(debate_id, turn_id) is None
    assert store.read_performance(debate_id, turn_id) is None
    assert not canonical_json.exists()


def test_read_performance_requires_audio_metadata(tmp_path: Path) -> None:
    course_id, debate_id, turn_id = _ids()
    store = AudioStore(tmp_path, tts_provider=TimestampedMock())
    store.synthesize_and_store(
        course_id=course_id,
        debate_id=debate_id,
        turn_id=turn_id,
        speech=SPEECH,
        voice_token="mock",
    )
    assert store.read_performance(debate_id, turn_id) is not None
    store.remove_turn(debate_id, turn_id)
    # A leftover JSON without its audio must not be served on its own.
    stray = tmp_path / (
        f"courses/{course_id}/current-debate-audio/{debate_id}/{turn_id}.performance.json"
    )
    stray.write_bytes(b"{}")
    assert store.read_performance(debate_id, turn_id) is None
