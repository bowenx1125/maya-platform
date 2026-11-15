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
    (
        "如果遇见你不是奇迹，灵魂便不曾言语。"
        "If meeting you was not a miracle, then my soul has never spoken."
    ),
    "不管需要多少年，我都要再见你一面。No matter how many years it takes, I will see you again.",
    (
        "重铸 Mayaform 荣光，吾辈义不容辞！"
        "To restore Mayaform to its former glory is our duty, and we shall not turn away!"
    ),
    "过得了我，再谈未来。Get past me first. Then we can talk about the future.",
    "我是要成为海贼王的男人！海賊王に、俺はなる！",
    "真相永远只有一个！真実はいつもひとつ！",
    (
        "或许是不知梦的缘故，流离之人追逐幻影。"
        "Perhaps because they do not know it is a dream, wandering souls keep chasing illusions."
    ),
    (
        "这一路上我们将不彼此抛弃，不彼此出卖，直到死亡的尽头。"
        "We will neither abandon nor betray each other, not even at the very edge of death."
    ),
    "从这里开始吧。从一开始，不，从零开始！ここから始めましょう。一から、いいえ、ゼロから！",
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


def test_the_nine_lines_are_exactly_as_specified() -> None:
    assert len(EXPECTED_LINES) == 9
    assert voice_preview.VOICE_PREVIEW_LINES == EXPECTED_LINES
    assert voice_preview.VOICE_PREVIEW_LINES[6] == (
        "或许是不知梦的缘故，流离之人追逐幻影。"
        "Perhaps because they do not know it is a dream, wandering souls keep chasing illusions."
    )


def test_previews_rotate_through_nine_lines_in_global_click_order(
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
    # 12 clicks alternating voices: lines 1..9, then wrap to lines 1..3.
    order = [first_voice if index % 3 else second_voice for index in range(12)]
    for profile_id in order:
        response = client.post(
            f"/api/v1/voice-profiles/{profile_id}/preview",
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )
        assert response.status_code == 200, response.text

    assert spoken == [*EXPECTED_LINES, *EXPECTED_LINES[:3]]
    assert provider.synthesize_calls == len(order)


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
