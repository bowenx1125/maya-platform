"""Per-turn chat audio is readable from the WAV header and deleted with the chat."""

from __future__ import annotations

from uuid import uuid4

from app.core.config import Settings
from app.core.db import Database
from app.modules.demo_baseline.service import BASELINE_VERSION_ID, ensure_demo_baseline
from app.modules.knowledge.files import write_atomic
from app.modules.workspace.chat_stream import chat_audio_relative
from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_wave1b_voices import _wav


def _open_chat(client: TestClient, database: Database, settings: Settings) -> tuple[str, str]:
    client.headers["Origin"] = "http://testserver"
    with database.session() as session:
        ensure_demo_baseline(session, settings.resolved_data_root)
    _user, csrf = login(client, "bowen")
    return csrf, settings.resolved_data_root.as_posix()


def _create(client: TestClient, csrf: str) -> str:
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    )
    assert created.status_code == 200, created.text
    return str(created.json()["id"])


def _send(client: TestClient, csrf: str, conversation_id: str, revision: int) -> dict[str, object]:
    request_id = str(uuid4())
    sent = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={"X-CSRF-Token": csrf},
        json={
            "request_id": request_id,
            "expected_revision": revision,
            "message": f"turn {revision}",
        },
    )
    assert sent.status_code == 200, sent.text
    turn = sent.json()["turns"][-1]
    assert turn["id"] == request_id
    return turn


def test_turn_audio_uses_the_wav_header_and_stays_null_without_a_file(
    app_bundle: tuple[object, Database, Settings], client: TestClient
) -> None:
    _app, database, settings = app_bundle
    csrf, _root = _open_chat(client, database, settings)
    conversation_id = _create(client, csrf)
    silent = _send(client, csrf, conversation_id, 0)
    assert silent["audio_url"] is None
    assert silent["audio_duration_ms"] is None

    spoken_id = str(silent["id"])
    raw = _wav(12)
    write_atomic(settings.resolved_data_root, chat_audio_relative(conversation_id, spoken_id), raw)
    loaded = client.get(f"/api/v1/conversations/{conversation_id}")
    assert loaded.status_code == 200, loaded.text
    turn = loaded.json()["turns"][0]
    audio_url = f"/api/v1/conversations/{conversation_id}/audio/{spoken_id}"
    assert turn["audio_url"] == audio_url
    assert turn["audio_duration_ms"] == 12_000
    media = client.get(audio_url)
    assert media.status_code == 200
    assert media.headers["content-type"].startswith("audio/wav")
    assert media.content.startswith(b"RIFF")

    missing = _send(client, csrf, conversation_id, 1)
    assert missing["audio_url"] is None
    assert missing["audio_duration_ms"] is None
    write_atomic(
        settings.resolved_data_root,
        chat_audio_relative(conversation_id, str(missing["id"])),
        b"not-a-wav",
    )
    broken = client.get(f"/api/v1/conversations/{conversation_id}").json()["turns"][1]
    assert broken["audio_url"] is None
    assert broken["audio_duration_ms"] is None
    broken_audio = client.get(f"/api/v1/conversations/{conversation_id}/audio/{missing['id']}")
    assert broken_audio.status_code == 404

    link_turn = _send(client, csrf, conversation_id, 2)
    target = settings.resolved_data_root / "outside-chat-audio.wav"
    target.write_bytes(_wav(1))
    link = settings.resolved_data_root / chat_audio_relative(conversation_id, str(link_turn["id"]))
    link.symlink_to(target)
    linked = client.get(f"/api/v1/conversations/{conversation_id}").json()["turns"][2]
    assert linked["audio_url"] is None
    assert linked["audio_duration_ms"] is None
    hidden = client.get(f"/api/v1/conversations/{conversation_id}/audio/{link_turn['id']}")
    assert hidden.status_code == 404
    assert target.read_bytes() == _wav(1)


def test_delete_conversation_removes_only_its_chat_audio(
    app_bundle: tuple[object, Database, Settings], client: TestClient
) -> None:
    _app, database, settings = app_bundle
    csrf, _root = _open_chat(client, database, settings)
    kept = _create(client, csrf)
    removed = _create(client, csrf)
    kept_turn = _send(client, csrf, kept, 0)
    removed_turn = _send(client, csrf, removed, 0)
    write_atomic(
        settings.resolved_data_root,
        chat_audio_relative(kept, str(kept_turn["id"])),
        _wav(1),
    )
    write_atomic(
        settings.resolved_data_root,
        chat_audio_relative(removed, str(removed_turn["id"])),
        _wav(1),
    )
    secret = settings.resolved_data_root / "chat-audio-secret.wav"
    secret.write_bytes(b"keep-me")
    removed_dir = settings.resolved_data_root / "chat-audio" / removed
    leftover = removed_dir / "note.txt"
    leftover.write_text("not audio", encoding="utf-8")
    linked = removed_dir / "linked.wav"
    linked.symlink_to(secret)

    deleted = client.delete(
        f"/api/v1/conversations/{removed}",
        headers={"X-CSRF-Token": csrf},
    )
    assert deleted.status_code == 204, deleted.text
    assert not (removed_dir / f"{removed_turn['id']}.wav").exists()
    assert linked.is_symlink()
    assert secret.read_bytes() == b"keep-me"
    assert leftover.is_file()
    assert removed_dir.is_dir()
    kept_file = settings.resolved_data_root / chat_audio_relative(kept, str(kept_turn["id"]))
    assert kept_file.is_file()
    assert (
        client.get(f"/api/v1/conversations/{kept}").json()["turns"][0]["audio_duration_ms"] == 1000
    )

    leftover.unlink()
    linked.unlink()
    cleared = client.delete(
        f"/api/v1/conversations/{kept}",
        headers={"X-CSRF-Token": csrf},
    )
    assert cleared.status_code == 204, cleared.text
    assert not (settings.resolved_data_root / "chat-audio" / kept).exists()
    assert secret.is_file()
