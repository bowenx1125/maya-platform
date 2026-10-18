"""Preview sample lines rotate in global generation order."""

from __future__ import annotations

import io
import wave
from collections.abc import Callable, Iterator
from threading import Barrier, Thread

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.models import VoicePreviewCounter
from app.modules.voices import preview as voice_preview
from app.modules.voices import service as voice_service
from app.providers.tts import MockTTSProvider, TTSResult
from app.providers.voice import MockVoiceCloneProvider
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import login

GROUP_A = "7813f937-902c-5534-bfb2-ad773a43aeda"

EXPECTED_LINES = (
    "龙脉长歌是罗登家族搜集大量考古数据后，杜撰的神明爱情歌剧。"
    "The first act describes the birth of Helius from the fires of Ignis.",
    "他为烛龙授命，于虚空看望群山，漂泊亿万年为孤独折磨。"
    "One day, he was drawn in by a mysterious voice.",
    "有歌的地方，你就会找到我。"
    "Terra, one of the gods, gazed at Helius from afar, hoping to save him with her song.",
    "终于乙皇为她降世，彼此相恋。Together they established the Myrian Empire.",
    "由于后土的歌声使龙脉不灭，众道不死，破坏了烛龙的法则。"
    "In fear of divine retribution, six gods rebelled, "
    "sacrificing Terra to Ignis and sparking the holy war.",
    "我记得艾妲看完后，始终呢喃着后土死前对乙皇的话语。"
    "Should we find each other in the next life, let us live on a planet of our own.",
    "若来世再遇，就找一个无人的行星生活。"
    "I will plant flowers among the valleys, and sing for you into old age and death.",
    "而我只记得艾妲的侧脸。At the end of the story, Helius slays the gods who killed Terra.",
    "他试图用龙脉生长的花卉让后土复活，然而烛龙却警告他。"
    "If Terra were resurrected, the fires of heaven would destroy Thousand Peaks.",
    "乙皇不允，反将爱人的尸首藏于大荒，目送后土于虚空离去。"
    "His last words before sending his lover into the void were these.",
    "花开有时，来世再遇。"
    "The heavens erupted and Helius was blown away by wind storms, scattered among the stars.",
    "如果遇见你不是奇迹，灵魂便不曾言语。"
    "If meeting you wasn't a miracle, then the souls have never whispered.",
)


@pytest.fixture
def voice_client(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
) -> Iterator[tuple[TestClient, Database, Settings]]:
    app, database, settings = app_factory()
    with TestClient(app) as client:
        yield client, database, settings


def _wav(seconds: int = 10) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24_000)
        stream.writeframes((b"\x00\x01" * 24_000) * seconds)
    return output.getvalue()


def _enroll(client: TestClient, csrf: str, key: str) -> str:
    response = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf, "Idempotency-Key": key},
        data={"consent_accepted": "true"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


def test_the_twelve_lines_are_exactly_as_specified() -> None:
    assert len(EXPECTED_LINES) == 12
    assert voice_preview.VOICE_PREVIEW_LINES == EXPECTED_LINES
    assert voice_preview.VOICE_PREVIEW_LINES[6] == (
        "若来世再遇，就找一个无人的行星生活。"
        "I will plant flowers among the valleys, and sing for you into old age and death."
    )


def test_previews_rotate_through_twelve_lines_in_global_click_order(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _database, _settings = voice_client
    _user, csrf = login(client, "bowen")
    monkeypatch.setattr(voice_service, "voice_provider", lambda _settings: MockVoiceCloneProvider())
    # Two different voices: the rotation is global, not per voice.
    first_voice = _enroll(client, csrf, "rotation-enroll-voice-1")
    second_voice = _enroll(client, csrf, "rotation-enroll-voice-2")
    provider = MockTTSProvider()
    spoken: list[str] = []
    synthesize = provider.synthesize

    def capture(
        text: str, voice_id: str, *, language: str = "en", target_model_key: str | None = None
    ) -> TTSResult:
        spoken.append(text)
        return synthesize(text, voice_id, language=language, target_model_key=target_model_key)

    monkeypatch.setattr(provider, "synthesize", capture)
    monkeypatch.setattr(voice_preview, "tts_provider", lambda _settings: provider)
    # 14 clicks alternating voices: lines 1..12, then wrap to lines 1 and 2.
    order = [first_voice if index % 3 else second_voice for index in range(14)]
    for profile_id in order:
        response = client.post(
            f"/api/v1/voice-profiles/{profile_id}/preview",
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )
        assert response.status_code == 200, response.text

    assert spoken == [*EXPECTED_LINES, EXPECTED_LINES[0], EXPECTED_LINES[1]]


def test_counter_is_persisted_and_atomic_under_concurrent_clicks(
    voice_client: tuple[TestClient, Database, Settings],
) -> None:
    _client, database, _settings = voice_client
    with database.session() as session:
        assert voice_preview.next_preview_line(session) == EXPECTED_LINES[0]
    workers = 8
    barrier = Barrier(workers)
    picked: list[str] = []

    def click() -> None:
        with database.session() as session:
            barrier.wait()
            picked.append(voice_preview.next_preview_line(session))

    threads = [Thread(target=click) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    with database.session() as session:
        counter = session.get(VoicePreviewCounter, "global")
        assert counter is not None and counter.value == 1 + workers
    # Clicks 2..9 each get a distinct line (2..9): no click is lost or doubled.
    assert sorted(picked) == sorted(
        EXPECTED_LINES[index % len(EXPECTED_LINES)] for index in range(1, 1 + workers)
    )
