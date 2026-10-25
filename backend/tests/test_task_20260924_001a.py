"""TASK-20260924-001A: shared DashScope key, voice binding, and chat SSE."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.models import AgentVersion, Group, VoiceProfile
from app.modules.debates.setup.service import _resolve_agent_version
from app.modules.demo_baseline.service import (
    BASELINE_LAOZI,
    BASELINE_PLATO,
    BASELINE_SOCRATES,
    BASELINE_VERSION_ID,
    ensure_demo_baseline,
)
from app.modules.voices.crypto import decrypt_external_voice_id, encrypt_external_voice_id
from app.modules.voices.schemas import VoiceProfile as VoiceProfileDTO
from app.modules.workspace.chat import store_assistant_text
from app.modules.workspace.chat_stream import sse
from app.modules.workspace.models import Conversation, ConversationTurn
from app.modules.workspace.schemas import ChatSession, ProviderSettings
from app.providers.dashscope import DEFAULT_TARGET_MODEL_KEY
from app.providers.factory import llm_provider, tts_provider, voice_provider
from app.providers.tts import TTSResult
from app.providers.voice import MockVoiceCloneProvider
from app.seed import COURSE_ID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login, post_message
from tests.postgres_db import named_url
from tests.test_wave1b_voices import GROUP_A, _headers, _wav


def _parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        name = "message"
        data = ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = line.split(":", 1)[1].strip()
        payload = json.loads(data)
        assert isinstance(payload, dict)
        events.append((name, payload))
    return events


@pytest.fixture
def voice_app(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
) -> Iterator[tuple[TestClient, Database, Settings]]:
    app, database, settings = app_factory()
    with TestClient(app) as client:
        client.headers["Origin"] = "http://testserver"
        yield client, database, settings


def _ready_profile(client: TestClient, csrf: str, key: str) -> str:
    enrolled = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, key),
        data={"consent_accepted": "true", "consent_copy_version": "voice-consent-v1"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert enrolled.status_code == 202, enrolled.text
    profile_id = enrolled.json()["id"]
    preview = client.post(
        f"/api/v1/voice-profiles/{profile_id}/preview",
        headers={"X-CSRF-Token": csrf},
    )
    assert preview.status_code == 200, preview.text
    return str(profile_id)


def test_dashscope_key_not_in_public_dto(
    tmp_path, voice_app: tuple[TestClient, Database, Settings]
) -> None:
    secret = "fixture-shared-key"
    settings = Settings(
        maya_env="test",
        session_secret="s" * 32,
        database_url=named_url(f"{tmp_path / 'unused.sqlite3'}"),
        data_root=tmp_path,
        llm_provider="dashscope",
        embedding_provider="dashscope",
        report_provider="dashscope",
        tts_provider="dashscope",
        voice_provider="dashscope",
        dashscope_api_key=secret,
        dashscope_workspace_id="workspace123",
        dashscope_region="cn-beijing",
        llm_provider_policy_hash="b" * 64,
        embedding_provider_policy_hash="a" * 64,
        report_provider_policy_hash="c" * 64,
    )
    settings.validate_provider_configuration()
    voice = voice_provider(settings)
    speech = tts_provider(settings)
    model = llm_provider(settings)
    assert voice.config.api_key == speech.config.api_key == model.config.api_key == secret
    assert voice.target_model_key == DEFAULT_TARGET_MODEL_KEY
    assert speech.target_model_key == DEFAULT_TARGET_MODEL_KEY
    assert not hasattr(settings, "dashscope_tts_api_key")
    schemas = json.dumps(
        {
            "provider": ProviderSettings.model_json_schema(),
            "chat": ChatSession.model_json_schema(),
            "voice": VoiceProfileDTO.model_json_schema(),
        }
    )
    assert "api_key" not in schemas
    assert secret not in schemas


def test_enroll_ready_encrypts_external_id(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    client, database, settings = voice_app
    _user, csrf = login(client, "bowen")
    enrolled = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "task-001a-enroll-0001"),
        data={"consent_accepted": "true", "consent_copy_version": "voice-consent-v1"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert enrolled.status_code == 202, enrolled.text
    profile_id = enrolled.json()["id"]
    assert (
        client.post(
            f"/api/v1/voice-profiles/{profile_id}/preview",
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 200
    )
    with database.session() as session:
        row = session.get(VoiceProfile, profile_id)
        assert row is not None
        assert row.status == "ready"
        assert row.external_id_encrypted
        plain = decrypt_external_voice_id(
            row.external_id_encrypted,
            settings.secret_bytes,
            profile_id=row.id,
            scope=row.scope,
            group_id=row.group_id,
            provider_key=row.provider_key,
            target_model_key=row.target_model_key,
        )
    assert plain
    assert plain.encode() not in (row.external_id_encrypted or b"")
    assert plain not in enrolled.text


def test_bind_voice_profile_id_on_agent_version(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    client, database, _settings = voice_app
    _user, csrf = login(client, "bowen")
    created = client.post(
        f"/api/v1/groups/{GROUP_A}/agents",
        headers=_headers(csrf, "task-001a-agent-0001"),
        json={"name": "Stream voice Agent", "description": ""},
    )
    assert created.status_code == 201, created.text
    version = created.json()["versions"][0]
    profile_id = _ready_profile(client, csrf, "task-001a-bind-enroll01")
    bound = client.patch(
        f"/api/v1/agent-versions/{version['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"expected_revision": version["revision"], "voice_profile_id": profile_id},
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["voice_profile_id"] == profile_id
    with database.session() as session:
        row = session.get(AgentVersion, version["id"])
        assert row is not None
        assert row.voice_profile_id == profile_id


class _RecordingTTS:
    key = "mock"
    target_model_key = "mock-tts-v1"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def synthesize(self, text: str, external_voice_id: str, *, language: str = "en") -> TTSResult:
        self.calls.append((text, external_voice_id, language))
        return TTSResult(audio_bytes=_wav(1), content_type="audio/wav", request_id="tts-once")


def _stream(client: TestClient, csrf: str, conversation_id: str, *, message: str, revision: int):
    return client.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers={"X-CSRF-Token": csrf, "Accept": "text/event-stream"},
        json={
            "request_id": str(uuid4()),
            "expected_revision": revision,
            "message": message,
        },
    )


def test_sse_delta_then_text_done_persists_full_text(
    voice_app: tuple[TestClient, Database, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, database, _settings = voice_app
    with database.session() as session:
        ensure_demo_baseline(session, _settings.resolved_data_root)
    _user, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    )
    assert created.status_code == 200, created.text
    conversation_id = created.json()["id"]
    order: list[str] = []
    original_store = store_assistant_text
    original_sse = sse

    def wrapped_store(*args, **kwargs):
        result = original_store(*args, **kwargs)
        order.append("stored")
        return result

    def wrapped_sse(event: str, payload: dict[str, object]) -> bytes:
        order.append(event)
        return original_sse(event, payload)

    monkeypatch.setattr("app.modules.workspace.chat.store_assistant_text", wrapped_store)
    monkeypatch.setattr("app.modules.workspace.chat_stream.sse", wrapped_sse)
    response = _stream(client, csrf, conversation_id, message="What is justice?", revision=0)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    names = [name for name, _payload in events]
    assert names[0] == "delta"
    assert "text_done" in names
    assert names.index("delta") < names.index("text_done")
    deltas = [payload["text"] for name, payload in events if name == "delta"]
    done = next(payload for name, payload in events if name == "text_done")
    full = "".join(str(part) for part in deltas)
    assert full == done["assistant_text"]
    assert done["revision"] == 1
    assert isinstance(done["sources"], list)
    stored_at = order.index("stored")
    assert stored_at == 0
    assert order[stored_at + 1 : -1] == ["delta"] * (len(order) - 2)
    assert order[-1] == "text_done"
    with database.session() as session:
        turn = session.scalar(
            select(ConversationTurn).where(ConversationTurn.conversation_id == conversation_id)
        )
        assert turn is not None
        assert turn.assistant_text == full
        assert turn.state == "ready"


@pytest.mark.parametrize("message", ["Hello", "你好"])
def test_chat_with_bound_voice_is_text_only(
    voice_app: tuple[TestClient, Database, Settings], monkeypatch: pytest.MonkeyPatch, message: str
) -> None:
    client, database, settings = voice_app
    with database.session() as session:
        ensure_demo_baseline(session, settings.resolved_data_root)
    _user, csrf = login(client, "bowen")
    profile_id = _ready_profile(client, csrf, "task-001a-tts-enroll001")
    with database.session() as session:
        version = session.get(AgentVersion, BASELINE_VERSION_ID)
        assert version is not None
        version.voice_profile_id = profile_id
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    )
    assert created.status_code == 200, created.text
    conversation_id = created.json()["id"]
    recorder = _RecordingTTS()
    monkeypatch.setattr("app.providers.tts.MockTTSProvider.synthesize", recorder.synthesize)
    response = _stream(client, csrf, conversation_id, message=message, revision=0)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert {name for name, _ in events} == {"delta", "text_done"}
    assert events[-1][0] == "text_done"
    assert recorder.calls == []
    done = events[-1][1]
    request_id = str(done["request_id"])
    assert not (settings.resolved_data_root / "chat-audio").exists()
    with database.session() as session:
        row = session.get(Conversation, conversation_id)
        turn = session.get(ConversationTurn, request_id)
        assert row is not None and row.active_request_id is None
        assert turn is not None and turn.state == "ready"
        assert turn.assistant_text == done["assistant_text"]
    replay = client.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers={"X-CSRF-Token": csrf, "Accept": "text/event-stream"},
        json={"request_id": request_id, "expected_revision": 1, "message": message},
    )
    assert replay.status_code == 200
    assert _parse_sse(replay.text) == [("text_done", done)]
    assert recorder.calls == []

    # Chats never had a player for stored speech; the old media route is gone.
    media = client.get(f"/api/v1/conversations/{conversation_id}/audio/{request_id}")
    assert media.status_code == 404
    assert recorder.calls == []


def test_chat_rejects_removed_language_field(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    client, database, settings = voice_app
    with database.session() as session:
        ensure_demo_baseline(session, settings.resolved_data_root)
    _user, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    )
    conversation_id = created.json()["id"]
    for lang in ("en", "zh-CN", "fr"):
        response = client.post(
            f"/api/v1/conversations/{conversation_id}/messages:stream",
            headers={"X-CSRF-Token": csrf, "Accept": "text/event-stream"},
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "message": "Hello",
                "lang": lang,
            },
        )
        assert response.status_code == 400, response.text
        assert response.json()["code"] == "malformed_request"
    kept = post_message(
        client,
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={"X-CSRF-Token": csrf},
        json={"request_id": str(uuid4()), "expected_revision": 0, "message": "Still here"},
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["turns"][0]["state"] == "ready"


def test_send_message_stores_assistant_text_once(
    voice_app: tuple[TestClient, Database, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, database, settings = voice_app
    with database.session() as session:
        ensure_demo_baseline(session, settings.resolved_data_root)
    _user, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    )
    conversation_id = created.json()["id"]
    calls: list[str] = []
    original = store_assistant_text

    def wrapped(db, conversation_id, request_id, claim_revision, reply, sources, operation_id):
        calls.append(request_id)
        return original(
            db, conversation_id, request_id, claim_revision, reply, sources, operation_id
        )

    monkeypatch.setattr("app.modules.workspace.chat.store_assistant_text", wrapped)
    request_id = str(uuid4())
    response = post_message(
        client,
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={"X-CSRF-Token": csrf},
        json={"request_id": request_id, "expected_revision": 0, "message": "Once"},
    )
    assert response.status_code == 200, response.text
    assert calls == [request_id]
    assert response.json()["turns"][0]["assistant_text"].endswith("Once")
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        assert turn is not None
        assert turn.state == "ready"
        assert turn.assistant_text == response.json()["turns"][0]["assistant_text"]


def test_replay_sources_json_failure_yields_sse_error(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    client, database, settings = voice_app
    with database.session() as session:
        ensure_demo_baseline(session, settings.resolved_data_root)
    _user, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    )
    conversation_id = created.json()["id"]
    request_id = str(uuid4())
    first = client.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers={"X-CSRF-Token": csrf, "Accept": "text/event-stream"},
        json={
            "request_id": request_id,
            "expected_revision": 0,
            "message": "Remember this",
        },
    )
    assert first.status_code == 200, first.text
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        assert turn is not None
        kept = turn.assistant_text
        turn.sources_json = "{"
    replay = client.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers={"X-CSRF-Token": csrf, "Accept": "text/event-stream"},
        json={
            "request_id": request_id,
            "expected_revision": 1,
            "message": "Remember this",
        },
    )
    assert replay.status_code == 200, replay.text
    events = _parse_sse(replay.text)
    assert events == [
        ("error", {"request_id": request_id, "safe_error_code": "chat_sources_invalid"})
    ]
    with database.session() as session:
        turn = session.get(ConversationTurn, request_id)
        assert turn is not None
        assert turn.assistant_text == kept
        assert turn.state == "ready"


def test_baseline_default_voices_reject_a_bad_map(tmp_path) -> None:
    base = {
        "maya_env": "test",
        "session_secret": "s" * 32,
        "database_url": named_url(f"{tmp_path / 'unused.sqlite3'}"),
        "data_root": tmp_path,
    }
    assert Settings(**base, baseline_default_voices="  ").parsed_baseline_default_voices() == {}
    voice_id = str(uuid4())
    parsed = Settings(
        **base, baseline_default_voices=f"Socrates={voice_id}"
    ).parsed_baseline_default_voices()
    assert parsed == {"socrates": voice_id}
    bad_uuid = Settings(**base, baseline_default_voices="laozi=not-a-uuid")
    with pytest.raises(RuntimeError, match="UUID"):
        bad_uuid.validate_runtime()
    with pytest.raises(RuntimeError, match="BASELINE_DEFAULT_VOICES"):
        Settings(
            **base, baseline_default_voices=f"hermes={voice_id}"
        ).parsed_baseline_default_voices()
    with pytest.raises(RuntimeError, match="BASELINE_DEFAULT_VOICES"):
        Settings(
            **base, baseline_default_voices=f"plato={voice_id},plato={uuid4()}"
        ).parsed_baseline_default_voices()


def _system_profile(database: Database, settings: Settings, external_id: str) -> str:
    profile_id = str(uuid4())
    now = datetime.now(UTC)
    envelope = encrypt_external_voice_id(
        external_id,
        settings.secret_bytes,
        profile_id=profile_id,
        scope="system",
        group_id=None,
        provider_key="mock",
        target_model_key="mock-voice-v1",
    )
    with database.session() as session:
        session.add(
            VoiceProfile(
                id=profile_id,
                scope="system",
                group_id=None,
                display_name="System fallback",
                status="ready",
                provider_key="mock",
                target_model_key="mock-voice-v1",
                external_id_encrypted=envelope,
                recovery_name=f"fallback-{profile_id}",
                provenance_json="{}",
                created_at=now,
                updated_at=now,
            )
        )
    return profile_id


def _foreign_profile(database: Database, settings: Settings, external_id: str) -> str:
    profile_id = str(uuid4())
    group_id = str(uuid4())
    now = datetime.now(UTC)
    envelope = encrypt_external_voice_id(
        external_id,
        settings.secret_bytes,
        profile_id=profile_id,
        scope="group",
        group_id=group_id,
        provider_key="mock",
        target_model_key="mock-voice-v1",
    )
    with database.session() as session:
        session.add(
            Group(
                id=group_id,
                course_id=COURSE_ID,
                name=f"Other {group_id[:8]}",
                created_at=now,
            )
        )
        session.add(
            VoiceProfile(
                id=profile_id,
                scope="group",
                group_id=group_id,
                display_name="Other group voice",
                status="ready",
                provider_key="mock",
                target_model_key="mock-voice-v1",
                external_id_encrypted=envelope,
                recovery_name=f"foreign-{profile_id}",
                provenance_json="{}",
                created_at=now,
                updated_at=now,
            )
        )
    return profile_id


def test_baseline_voices_remain_for_debates_but_chat_ignores_them(
    voice_app: tuple[TestClient, Database, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, database, settings = voice_app
    with database.session() as session:
        ensure_demo_baseline(session, settings.resolved_data_root)
    _user, csrf = login(client, "bowen")
    socrates_voice = _ready_profile(client, csrf, "task-001a-base-socrates1")
    # Upload alone makes a voice selectable; no confirm-by-listening step.
    laozi_uploaded = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "task-001a-base-laozi001"),
        data={"consent_accepted": "true", "consent_copy_version": "voice-consent-v1"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert laozi_uploaded.status_code == 202, laozi_uploaded.text
    assert laozi_uploaded.json()["status"] == "ready"
    laozi_voice = laozi_uploaded.json()["id"]
    fallback_voice = _system_profile(database, settings, "system-fallback-voice")
    foreign_voice = _foreign_profile(database, settings, "foreign-group-voice")
    client.app.state.settings = settings.model_copy(
        update={
            "baseline_default_voices": (f"socrates={socrates_voice},laozi={laozi_voice}"),
            "fallback_voice_profile_id": fallback_voice,
        }
    )
    active = client.app.state.settings
    with database.session() as session:
        socrates = _resolve_agent_version(
            session,
            course_id=COURSE_ID,
            agent_id=BASELINE_SOCRATES.agent_id,
            settings=active,
        )
        plato = _resolve_agent_version(
            session, course_id=COURSE_ID, agent_id=BASELINE_PLATO.agent_id, settings=active
        )
        laozi = _resolve_agent_version(
            session, course_id=COURSE_ID, agent_id=BASELINE_LAOZI.agent_id, settings=active
        )
    assert socrates[5] == socrates_voice
    assert socrates[6] == socrates_voice
    assert socrates[8] is False
    assert plato[5] is None
    assert plato[6] == fallback_voice
    assert plato[8] is True
    assert laozi[5] == laozi_voice
    assert laozi[6] == laozi_voice
    assert laozi[8] is False

    recorder = _RecordingTTS()
    monkeypatch.setattr("app.providers.tts.MockTTSProvider.synthesize", recorder.synthesize)

    def chat(version_id: str) -> None:
        created = client.post(
            "/api/v1/conversations",
            headers={"X-CSRF-Token": csrf},
            json={"version_id": version_id},
        )
        assert created.status_code == 200, created.text
        response = _stream(client, csrf, created.json()["id"], message="Speak", revision=0)
        assert response.status_code == 200, response.text
        events = _parse_sse(response.text)
        assert {name for name, _ in events} == {"delta", "text_done"}
        assert events[-1][0] == "text_done"

    chat(BASELINE_VERSION_ID)
    chat(BASELINE_PLATO.version_id)
    chat(BASELINE_LAOZI.version_id)
    assert recorder.calls == []

    client.app.state.settings = active.model_copy(
        update={"baseline_default_voices": f"socrates={foreign_voice}"}
    )
    chat(BASELINE_VERSION_ID)
    assert recorder.calls == []

    with database.session() as session:
        for version_id in (
            BASELINE_VERSION_ID,
            BASELINE_PLATO.version_id,
            BASELINE_LAOZI.version_id,
        ):
            version = session.get(AgentVersion, version_id)
            assert version is not None
            assert version.voice_profile_id is None
        ensure_demo_baseline(session, settings.resolved_data_root)
        again = session.get(AgentVersion, BASELINE_VERSION_ID)
        assert again is not None
        assert again.voice_profile_id is None


def test_enrolled_voice_row_does_not_store_the_api_key(
    voice_app: tuple[TestClient, Database, Settings],
) -> None:
    client, database, _settings = voice_app
    sentinel = "sentinel-dashscope-key-not-real"
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"dashscope_api_key": sentinel}
    )
    _user, csrf = login(client, "bowen")
    enrolled = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "task-001a-key-absent01"),
        data={"consent_accepted": "true", "consent_copy_version": "voice-consent-v1"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert enrolled.status_code == 202, enrolled.text
    assert sentinel not in enrolled.text
    profile_id = enrolled.json()["id"]
    with database.session() as session:
        row = session.get(VoiceProfile, profile_id)
        assert row is not None
        stored = " ".join(
            str(value or "")
            for value in (
                row.provenance_json,
                row.source_filename,
                row.recovery_name,
                row.provider_key,
                row.target_model_key,
                row.display_name,
                row.consent_copy_version,
            )
        )
        assert sentinel not in stored
        assert sentinel.encode() not in (row.external_id_encrypted or b"")
        assert row.provider_key == "mock"


def test_enrollment_language_follows_the_sample(
    voice_app: tuple[TestClient, Database, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _database, _settings = voice_app
    provider = MockVoiceCloneProvider()
    monkeypatch.setattr("app.modules.voices.service.voice_provider", lambda _settings: provider)
    _user, csrf = login(client, "bowen")
    rejected = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "task-001a-lang-reject01"),
        data={
            "consent_accepted": "true",
            "consent_copy_version": "voice-consent-v1",
            "language": "fr",
        },
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["code"] == "voice_enrollment_failed"
    assert provider.enroll_calls == 0
    enrolled = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "task-001a-lang-zhcn0001"),
        data={
            "consent_accepted": "true",
            "consent_copy_version": "voice-consent-v1",
            "language": "zh-CN",
        },
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert enrolled.status_code == 202, enrolled.text
    assert enrolled.json()["id"]
    assert provider.last_language == "zh"
    omitted = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "task-001a-lang-omit0001"),
        data={"consent_accepted": "true", "consent_copy_version": "voice-consent-v1"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert omitted.status_code == 202, omitted.text
    assert provider.last_language == "en"
    assert provider.enroll_calls == 2
