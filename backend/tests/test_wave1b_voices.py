from __future__ import annotations

import fcntl
import io
import os
import wave
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread

import httpx
import pytest
from alembic import command
from alembic.config import Config
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import (
    IdempotencyRecord,
    VoicePreview,
    VoiceProfile,
    VoiceProviderOperation,
)
from app.modules.voices import service as voice_service
from app.modules.voices.crypto import (
    VoiceEncryptionError,
    decrypt_external_voice_id,
    encrypt_external_voice_id,
)
from app.modules.voices.fallback import FallbackEnrollmentError, enroll_system_fallback
from app.modules.voices.uploads import (
    VoiceUploadDisconnected,
    VoiceUploadTooLarge,
    cleanup_voice_temp_dirs,
    stream_voice_upload,
)
from app.providers import dashscope
from app.providers.audio import (
    AudioProcessError,
    AudioValidationError,
    run_ffmpeg_normalize,
)
from app.providers.tts import TTSProviderError, TTSProviderTimeout, TTSResult
from app.providers.voice import (
    MockVoiceCloneProvider,
    VoiceProviderError,
    VoiceProviderTimeout,
)
from app.seed import seed_demo_data
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from tests.conftest import login

GROUP_A = "66ee37fb-5772-5c8f-bb63-46d1783c53ae"
GROUP_B = "699112be-780b-5ffd-9a87-3762f596c558"


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


def _headers(csrf: str, key: str) -> dict[str, str]:
    return {
        "Origin": "http://testserver",
        "X-CSRF-Token": csrf,
        "Idempotency-Key": key,
    }


def _multipart(file_name: str, content: bytes, *, chunk_size: int = 257) -> tuple[bytes, str]:
    boundary = "maya-test-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="consent_accepted"\r\n\r\n'
        "true\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
        "Content-Type: audio/wav\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, boundary


def _stream_request(
    body: bytes,
    boundary: str,
    *,
    chunk_size: int = 257,
    disconnect_after: int | None = None,
) -> Request:
    chunks = [body[index : index + chunk_size] for index in range(0, len(body), chunk_size)]
    position = 0

    async def receive() -> dict[str, object]:
        nonlocal position
        if disconnect_after is not None and position >= disconnect_after:
            return {"type": "http.disconnect"}
        if position >= len(chunks):
            return {"type": "http.request", "body": b"", "more_body": False}
        value = chunks[position]
        position += 1
        return {
            "type": "http.request",
            "body": value,
            "more_body": position < len(chunks),
        }

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/groups/group/voice-profiles",
        "raw_path": b"/api/v1/groups/group/voice-profiles",
        "query_string": b"",
        "headers": [
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    return Request(scope, receive)


def test_voice_envelope_is_authenticated_and_row_bound() -> None:
    context = {
        "profile_id": "profile-a",
        "scope": "group",
        "group_id": "group-a",
        "provider_key": "mock",
        "target_model_key": "mock-voice-v1",
    }
    first = encrypt_external_voice_id("external-value", b"s" * 32, **context)
    second = encrypt_external_voice_id("external-value", b"s" * 32, **context)
    assert first != second
    assert b"external-value" not in first
    assert decrypt_external_voice_id(first, b"s" * 32, **context) == "external-value"
    with pytest.raises(VoiceEncryptionError):
        decrypt_external_voice_id(
            first,
            b"x" * 32,
            **{**context, "profile_id": "profile-b"},
        )


def test_voice_envelope_rejects_every_tampered_component_and_context_swap() -> None:
    context = {
        "profile_id": "profile-a",
        "scope": "group",
        "group_id": "group-a",
        "provider_key": "mock",
        "target_model_key": "mock-voice-v1",
    }
    envelope = encrypt_external_voice_id("opaque-id", b"s" * 32, **context)
    # version, nonce, ciphertext and authentication tag are all covered.
    for index in (0, 1, 5, len(envelope) - 1):
        tampered = bytearray(envelope)
        tampered[index] ^= 1
        with pytest.raises(VoiceEncryptionError):
            decrypt_external_voice_id(bytes(tampered), b"s" * 32, **context)
    for field, value in (
        ("scope", "system"),
        ("group_id", "group-b"),
        ("provider_key", "dashscope"),
        ("target_model_key", "other-model"),
        ("profile_id", "profile-b"),
    ):
        with pytest.raises(VoiceEncryptionError):
            decrypt_external_voice_id(
                envelope,
                b"s" * 32,
                **{**context, field: value},
            )


def test_voice_enrollment_preview_confirmation_delete_and_cleanup(
    voice_client: tuple[TestClient, Database, Settings],
) -> None:
    client, database, settings = voice_client
    _user, csrf = login(client, "student-bowen-1")
    source = _wav()
    response = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "voice-enroll-test-0001"),
        data={"consent_accepted": "true", "consent_copy_version": "voice-consent-v1"},
        files={"file": ("sample.wav", source, "audio/wav")},
    )
    assert response.status_code == 202, response.text
    profile = response.json()
    assert profile["status"] == "preview_ready"
    assert "provider" not in response.text.lower()
    assert "external" not in response.text.lower()
    with database.session() as session:
        row = session.scalar(select(VoiceProfile).where(VoiceProfile.id == profile["id"]))
        assert row is not None
        assert row.external_id_encrypted is not None
        assert source not in (row.external_id_encrypted or b"")
        op = session.scalar(
            select(VoiceProviderOperation).where(VoiceProviderOperation.profile_id == row.id)
        )
        assert op is not None and op.state == "succeeded"
    assert not list((settings.resolved_data_root / "tmp" / "voice-enrollment").iterdir())

    preview = client.post(
        f"/api/v1/voice-profiles/{profile['id']}/preview",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert preview.status_code == 200, preview.text
    media = client.get(preview.json()["playback_url"])
    assert media.status_code == 200
    assert media.headers["cache-control"].startswith("no-store")

    confirmed = client.post(
        f"/api/v1/voice-profiles/{profile['id']}/confirm",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "ready"
    assert client.get(preview.json()["playback_url"]).status_code == 404

    deleted = client.delete(
        f"/api/v1/voice-profiles/{profile['id']}",
        headers=_headers(csrf, "voice-delete-test-0001"),
    )
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"


def test_agent_draft_avatar_and_voice_binding_tri_state(
    voice_client: tuple[TestClient, Database, Settings],
) -> None:
    client, _database, _settings = voice_client
    _user, csrf = login(client, "student-bowen-1")
    created = client.post(
        f"/api/v1/groups/{GROUP_A}/agents",
        headers=_headers(csrf, "voice-bind-agent-0001"),
        json={"name": "Voice binding Agent", "description": ""},
    )
    assert created.status_code == 201, created.text
    version = created.json()["versions"][0]

    enrolled = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "voice-bind-enroll-0001"),
        data={"consent_accepted": "true"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert enrolled.status_code == 202, enrolled.text
    profile_id = enrolled.json()["id"]
    preview = client.post(
        f"/api/v1/voice-profiles/{profile_id}/preview",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        f"/api/v1/voice-profiles/{profile_id}/confirm",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200

    avatar = {
        "template_id": "maya-warm-scholar",
        "material_theme": "warm_sand",
        "eye_color": "hazel",
        "default_expression": "attentive",
        "expression_strength": "medium",
        "motion_style": "calm",
    }
    bound = client.patch(
        f"/api/v1/agent-versions/{version['id']}",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        json={
            "expected_revision": version["revision"],
            "avatar_config": avatar,
            "voice_profile_id": profile_id,
        },
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["avatar_config"] == avatar
    assert bound.json()["voice_profile_id"] == profile_id
    assert bound.json()["effective_voice_profile_id"] == profile_id
    assert bound.json()["voice_fallback_active"] is False

    # Omitted voice keeps the binding, explicit null clears it. An invalid
    # avatar is rejected without incrementing the authoritative revision.
    prompt_only = client.patch(
        f"/api/v1/agent-versions/{version['id']}",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        json={"expected_revision": bound.json()["revision"], "agent_md": "# unchanged voice"},
    )
    assert prompt_only.status_code == 200
    assert prompt_only.json()["voice_profile_id"] == profile_id
    cleared = client.patch(
        f"/api/v1/agent-versions/{version['id']}",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        json={
            "expected_revision": prompt_only.json()["revision"],
            "voice_profile_id": None,
        },
    )
    assert cleared.status_code == 200
    assert cleared.json()["voice_profile_id"] is None
    assert cleared.json()["effective_voice_profile_id"] is None
    assert cleared.json()["voice_fallback_active"] is True
    invalid_avatar = {**avatar, "template_id": "not-in-catalog"}
    rejected = client.patch(
        f"/api/v1/agent-versions/{version['id']}",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        json={
            "expected_revision": cleared.json()["revision"],
            "avatar_config": invalid_avatar,
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "avatar_missing"
    current = client.get(f"/api/v1/agent-versions/{version['id']}")
    assert current.status_code == 200
    assert current.json()["revision"] == cleared.json()["revision"]


def test_voice_scope_and_upload_validation(
    voice_client: tuple[TestClient, Database, Settings],
) -> None:
    client, _database, settings = voice_client
    _user, csrf = login(client, "student-bowen-1")
    cross_group = client.get(f"/api/v1/groups/{GROUP_B}/voice-profiles")
    assert cross_group.status_code == 404
    invalid = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "voice-invalid-test-0001"),
        data={"consent_accepted": "true"},
        files={"file": ("spoof.mp3", b"not-audio", "audio/mpeg")},
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "audio_invalid"
    assert not list((settings.resolved_data_root / "tmp" / "voice-enrollment").iterdir())


def test_enrollment_generic_provider_error_is_reconciled_before_retry(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database, settings = voice_client
    _user, csrf = login(client, "student-bowen-1")
    provider = MockVoiceCloneProvider()
    provider.next_enroll_error = VoiceProviderError("opaque supplier failure")
    monkeypatch.setattr(voice_service, "voice_provider", lambda _settings: provider)
    key = "voice-ambiguous-error-0001"
    first = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, key),
        data={"consent_accepted": "true"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert first.status_code == 503
    with database.session() as session:
        profile = session.scalar(select(VoiceProfile).order_by(VoiceProfile.created_at.desc()))
        assert profile is not None
        operation = session.scalar(
            select(VoiceProviderOperation).where(
                VoiceProviderOperation.profile_id == profile.id,
            )
        )
        record = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.key == key,
                IdempotencyRecord.operation == "enrollVoice",
            )
        )
        assert operation is not None and operation.state == "outcome_unknown"
        assert record is not None
        recovery_name = profile.recovery_name
        record.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        operation.provider_deadline = datetime.now(UTC) - timedelta(seconds=1)
    provider.set_reconciliation_matches(recovery_name, ("recovered-external-id",))
    second = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, key),
        data={"consent_accepted": "true"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert second.status_code == 202, second.text
    assert second.json()["status"] == "preview_ready"
    assert provider.enroll_calls == 1
    assert provider.exists_calls == 1


def test_stale_provider_worker_cannot_dispatch_or_finish_after_fencing(
    voice_client: tuple[TestClient, Database, Settings],
) -> None:
    _client, database, _settings = voice_client
    timestamp = datetime.now(UTC)
    profile_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    operation_id = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    with database.session() as session:
        session.add(
            VoiceProfile(
                id=profile_id,
                scope="group",
                group_id=GROUP_A,
                display_name="Fence test",
                status="enrolling",
                provider_key="mock",
                target_model_key="mock-voice-v1",
                external_id_encrypted=None,
                recovery_name="maya-voice-fence-test",
                provenance_json="{}",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        session.add(
            VoiceProviderOperation(
                id=operation_id,
                profile_id=profile_id,
                operation_type="enroll",
                profile_scope="group",
                state="prepared",
                attempt=1,
                claim_token="old-worker-token",
                request_hash="a" * 64,
                provider_deadline=timestamp + timedelta(seconds=30),
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    stale_session = database.session_factory()
    owner_session = database.session_factory()
    try:
        stale = stale_session.get(VoiceProviderOperation, operation_id)
        current = owner_session.get(VoiceProviderOperation, operation_id)
        assert stale is not None and current is not None
        assert stale.claim_token == "old-worker-token"
        stale_session.expunge(stale)
        stale_session.rollback()
        voice_service._claim_provider_operation(owner_session, current, "new-worker-token")
        assert stale.claim_token == "old-worker-token"
        with pytest.raises(PlatformError):
            voice_service._dispatch_operation(stale_session, stale)
        with pytest.raises(PlatformError):
            voice_service._finish_operation(stale_session, stale, state="succeeded")
    finally:
        stale_session.close()
        owner_session.close()
    with database.session() as session:
        operation = session.get(VoiceProviderOperation, operation_id)
        assert operation is not None
        assert operation.state == "prepared"
        assert operation.claim_token == "new-worker-token"
        assert operation.request_count == 0


def test_delete_same_idempotency_key_replays_without_second_provider_command(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _database, _settings = voice_client
    _user, csrf = login(client, "student-bowen-1")
    provider = MockVoiceCloneProvider()
    monkeypatch.setattr(voice_service, "voice_provider", lambda _settings: provider)
    monkeypatch.setattr("app.providers.factory.voice_provider", lambda _settings: provider)
    profile = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "voice-delete-replay-enroll"),
        data={"consent_accepted": "true"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    ).json()
    key = "voice-delete-replay-0001"
    first = client.delete(
        f"/api/v1/voice-profiles/{profile['id']}",
        headers=_headers(csrf, key),
    )
    second = client.delete(
        f"/api/v1/voice-profiles/{profile['id']}",
        headers=_headers(csrf, key),
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "deleted"
    assert provider.delete_calls == 1


def test_delete_different_idempotency_key_cannot_cross_active_saga_fence(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database, _settings = voice_client
    _user, csrf = login(client, "student-bowen-1")
    provider = MockVoiceCloneProvider()
    monkeypatch.setattr(voice_service, "voice_provider", lambda _settings: provider)
    monkeypatch.setattr("app.providers.factory.voice_provider", lambda _settings: provider)
    profile = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "voice-delete-fence-enroll"),
        data={"consent_accepted": "true"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    ).json()
    timestamp = datetime.now(UTC)
    with database.session() as session:
        row = session.get(VoiceProfile, profile["id"])
        assert row is not None
        row.status = "deleting"
        session.add(
            VoiceProviderOperation(
                id="12121212-1212-4212-8212-121212121212",
                profile_id=row.id,
                operation_type="delete",
                profile_scope="group",
                state="dispatched",
                attempt=1,
                claim_token="first-delete-worker",
                request_hash="d" * 64,
                provider_deadline=timestamp + timedelta(seconds=30),
                request_count=1,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    blocked = client.delete(
        f"/api/v1/voice-profiles/{profile['id']}",
        headers=_headers(csrf, "voice-delete-fence-second-key"),
    )
    assert blocked.status_code == 503
    assert provider.delete_calls == 0
    with database.session() as session:
        operations = session.scalars(
            select(VoiceProviderOperation).where(
                VoiceProviderOperation.profile_id == profile["id"],
                VoiceProviderOperation.operation_type == "delete",
            )
        ).all()
        assert len(operations) == 1
        session.add(
            VoiceProviderOperation(
                id="13131313-1313-4313-8313-131313131313",
                profile_id=profile["id"],
                operation_type="delete",
                profile_scope="group",
                state="prepared",
                attempt=1,
                claim_token="competing-delete-worker",
                request_hash="e" * 64,
                provider_deadline=timestamp + timedelta(seconds=30),
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_delete_two_live_requests_issue_exactly_one_provider_command(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, database, _settings = app_factory()

    class BlockingDeleteProvider(MockVoiceCloneProvider):
        def __init__(self) -> None:
            super().__init__()
            self.started = Event()
            self.release = Event()

        def delete(self, external_voice_id: str, *, target_model_key: str) -> None:
            self.started.set()
            if not self.release.wait(5):
                raise VoiceProviderTimeout("test release timed out")
            super().delete(external_voice_id, target_model_key=target_model_key)

    provider = BlockingDeleteProvider()
    monkeypatch.setattr(voice_service, "voice_provider", lambda _settings: provider)
    monkeypatch.setattr("app.providers.factory.voice_provider", lambda _settings: provider)
    responses: dict[str, httpx.Response] = {}
    first_done = Event()
    second_done = Event()
    with TestClient(app) as first, TestClient(app) as second:
        _user, first_csrf = login(first, "student-bowen-1")
        _user, second_csrf = login(second, "student-bowen-1")
        profile = first.post(
            f"/api/v1/groups/{GROUP_A}/voice-profiles",
            headers=_headers(first_csrf, "voice-delete-live-enroll"),
            data={"consent_accepted": "true"},
            files={"file": ("sample.wav", _wav(), "audio/wav")},
        ).json()

        def run_delete(
            label: str,
            client: TestClient,
            csrf: str,
            key: str,
            done: Event,
        ) -> None:
            responses[label] = client.delete(
                f"/api/v1/voice-profiles/{profile['id']}",
                headers=_headers(csrf, key),
            )
            done.set()

        first_thread = Thread(
            target=run_delete,
            args=("first", first, first_csrf, "voice-delete-live-first", first_done),
        )
        second_thread = Thread(
            target=run_delete,
            args=("second", second, second_csrf, "voice-delete-live-second", second_done),
        )
        first_thread.start()
        assert provider.started.wait(3)
        second_thread.start()
        second_finished_while_first_was_dispatched = second_done.wait(3)
        provider.release.set()
        first_thread.join(5)
        second_thread.join(5)

    assert second_finished_while_first_was_dispatched
    assert first_done.is_set() and second_done.is_set()
    assert sorted(response.status_code for response in responses.values()) == [200, 503]
    assert provider.delete_calls == 1
    with database.session() as session:
        operations = session.scalars(
            select(VoiceProviderOperation).where(
                VoiceProviderOperation.profile_id == profile["id"],
                VoiceProviderOperation.operation_type == "delete",
            )
        ).all()
        assert len(operations) == 1
        assert operations[0].state == "succeeded"


def test_voice_routes_emit_only_frozen_negative_statuses(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database, _settings = voice_client
    _user, csrf = login(client, "student-bowen-1")
    provider = MockVoiceCloneProvider()
    monkeypatch.setattr(voice_service, "voice_provider", lambda _settings: provider)
    monkeypatch.setattr("app.providers.factory.voice_provider", lambda _settings: provider)
    first = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "voice-frozen-status-enroll"),
        data={"consent_accepted": "true"},
        files={"file": ("first.wav", _wav(), "audio/wav")},
    )
    assert first.status_code == 202
    conflicting_upload = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "voice-frozen-status-enroll"),
        data={"consent_accepted": "true"},
        files={"file": ("different.wav", _wav() + b"different", "audio/wav")},
    )
    assert conflicting_upload.status_code == 422
    assert conflicting_upload.json()["code"] == "idempotency_conflict"

    with database.session() as session:
        profile = session.get(VoiceProfile, first.json()["id"])
        assert profile is not None
        profile.status = "failed"
    unavailable_preview = client.post(
        f"/api/v1/voice-profiles/{first.json()['id']}/preview",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert unavailable_preview.status_code == 404

    second = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "voice-frozen-status-second-enroll"),
        data={"consent_accepted": "true"},
        files={"file": ("second.wav", _wav(), "audio/wav")},
    )
    assert second.status_code == 202
    delete_key = "voice-frozen-status-delete-key"
    deleted = client.delete(
        f"/api/v1/voice-profiles/{second.json()['id']}",
        headers=_headers(csrf, delete_key),
    )
    assert deleted.status_code == 200
    third = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "voice-frozen-status-third-enroll"),
        data={"consent_accepted": "true"},
        files={"file": ("third.wav", _wav(), "audio/wav")},
    )
    assert third.status_code == 202
    delete_key_conflict = client.delete(
        f"/api/v1/voice-profiles/{third.json()['id']}",
        headers=_headers(csrf, delete_key),
    )
    assert delete_key_conflict.status_code == 503


def test_effective_voice_resolver_prefers_ready_custom_and_fails_closed_to_system(
    voice_client: tuple[TestClient, Database, Settings],
) -> None:
    _client, database, settings = voice_client
    timestamp = datetime.now(UTC)
    custom_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    fallback_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    common = {
        "scope": "group",
        "group_id": GROUP_A,
        "provider_key": "mock",
        "target_model_key": "mock-voice-v1",
    }
    with database.session() as session:
        fallback = VoiceProfile(
            id=fallback_id,
            scope="system",
            group_id=None,
            display_name="System English Fallback",
            status="ready",
            provider_key="mock",
            target_model_key="mock-voice-v1",
            external_id_encrypted=None,
            recovery_name="maya-voice-fallback",
            provenance_json="{}",
            created_at=timestamp,
            updated_at=timestamp,
        )
        fallback.external_id_encrypted = encrypt_external_voice_id(
            "system-external", settings.secret_bytes, profile_id=fallback.id,
            scope=fallback.scope, group_id=fallback.group_id,
            provider_key=fallback.provider_key, target_model_key=fallback.target_model_key,
        )
        custom = VoiceProfile(
            id=custom_id,
            display_name="Custom",
            status="ready",
            external_id_encrypted=None,
            recovery_name="maya-voice-custom",
            provenance_json="{}",
            source_filename="sample.wav",
            source_sha256="a" * 64,
            consent_copy_version="voice-consent-v1",
            consent_actor_user_id=None,
            consent_accepted_at=None,
            created_at=timestamp,
            updated_at=timestamp,
            **common,
        )
        custom.external_id_encrypted = encrypt_external_voice_id(
            "custom-external", settings.secret_bytes, profile_id=custom.id,
            scope=custom.scope, group_id=custom.group_id,
            provider_key=custom.provider_key, target_model_key=custom.target_model_key,
        )
        session.add_all([fallback, custom])
    settings.fallback_voice_profile_id = fallback_id
    resolver_session = database.session_factory()
    try:
        effective = voice_service.resolve_effective_voice_profile(
            resolver_session, custom_id, GROUP_A, settings
        )
        assert effective.profile_id == custom_id and not effective.fallback_active
    finally:
        resolver_session.close()


    corrupt_session = database.session_factory()
    try:
        corrupt = corrupt_session.get(VoiceProfile, custom_id)
        assert corrupt is not None
        corrupt.external_id_encrypted = b"tampered"
        corrupt_session.commit()
    finally:
        corrupt_session.close()
    with database.session() as session:
        assert session.get(VoiceProfile, custom_id) is not None
    resolver_session = database.session_factory()
    try:
        effective = voice_service.resolve_effective_voice_profile(
            resolver_session, custom_id, GROUP_A, settings
        )
        assert effective.profile_id == fallback_id and effective.fallback_active
        settings.fallback_voice_profile_id = None
        no_fallback = voice_service.resolve_effective_voice_profile(
            resolver_session, custom_id, GROUP_A, settings
        )
        assert no_fallback.profile_id is None and no_fallback.fallback_active
    finally:
        resolver_session.close()


def test_voice_permissions_are_same_group_students_only(
    voice_client: tuple[TestClient, Database, Settings],
) -> None:
    client, _database, _settings = voice_client
    _user, csrf = login(client, "student-bowen-1")
    create = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "voice-permission-enroll"),
        data={"consent_accepted": "true"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert create.status_code == 202
    profile_id = create.json()["id"]
    assert client.get(f"/api/v1/voice-profiles/{profile_id}").status_code == 200
    assert client.get(f"/api/v1/groups/{GROUP_A}/voice-profiles").status_code == 200

    # The other group and a teacher receive the same not-found response; the
    # profile's existence is not disclosed through list/detail/delete/media.
    other = login(client, "student-kaikai-1")[1]
    assert client.get(f"/api/v1/groups/{GROUP_A}/voice-profiles").status_code == 404
    assert client.get(f"/api/v1/voice-profiles/{profile_id}").status_code == 404
    assert client.delete(
        f"/api/v1/voice-profiles/{profile_id}", headers=_headers(other, "voice-cross-delete")
    ).status_code == 404
    teacher = login(client, "teacher-demo")[1]
    assert client.get(f"/api/v1/groups/{GROUP_A}/voice-profiles").status_code == 404
    assert client.get(f"/api/v1/voice-profiles/{profile_id}").status_code == 404
    assert client.delete(
        f"/api/v1/voice-profiles/{profile_id}", headers=_headers(teacher, "voice-teacher-delete")
    ).status_code == 404
    # Return to the original same-group session to demonstrate it remains
    # authorized after the denied probes.
    login(client, "student-bowen-1")
    assert client.get(f"/api/v1/voice-profiles/{profile_id}").status_code == 200


def test_preview_expiry_revokes_media_and_reclaims_bytes(
    voice_client: tuple[TestClient, Database, Settings],
) -> None:
    client, database, settings = voice_client
    _user, csrf = login(client, "student-bowen-1")
    profile = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "voice-preview-expiry-enroll"),
        data={"consent_accepted": "true"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    ).json()
    preview = client.post(
        f"/api/v1/voice-profiles/{profile['id']}/preview",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert preview.status_code == 200
    media_url = preview.json()["playback_url"]
    preview_id = media_url.split("/")[-2]
    with database.session() as session:
        row = session.scalar(select(VoicePreview).where(VoicePreview.id == preview_id))
        # The URL segment is the preview UUID; keep this explicit so a future
        # URL shape change fails the test instead of silently checking a row.
        if row is None:
            row = session.scalar(select(VoicePreview).where(VoicePreview.id == preview_id))
        assert row is not None and row.relative_path is not None
        relative_path = row.relative_path
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    expired = client.get(media_url)
    assert expired.status_code == 404
    with database.session() as session:
        row = session.scalar(select(VoicePreview).where(VoicePreview.id == preview_id))
        assert row is not None and row.state == "expired" and row.relative_path is None
    assert not (settings.resolved_data_root / relative_path).exists()


def test_supplier_url_rejects_private_hosts_userinfo_redirect_and_queries() -> None:
    with pytest.raises(TTSProviderError):
        dashscope.validate_supplier_url("http://dashscope.aliyuncs.com/result.wav")
    with pytest.raises(TTSProviderError):
        dashscope.validate_supplier_url("https://127.0.0.1/result.wav")
    with pytest.raises(TTSProviderError):
        dashscope.validate_supplier_url("https://user:pass@dashscope.aliyuncs.com/result.wav")
    # Supplier audio URLs are short-lived signed OSS URLs, so query parameters
    # are required and remain server-only. Fragments/userinfo are rejected.
    assert dashscope.validate_supplier_url(
        "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/result.wav?Expires=1"
    ).endswith("?Expires=1")
    with pytest.raises(TTSProviderError):
        dashscope.validate_supplier_url("https://dashscope.aliyuncs.com/result.wav#fragment")
    with pytest.raises(TTSProviderError):
        dashscope.validate_supplier_url("https://dashscope.aliyuncs.com.evil.test/result.wav")
    assert dashscope.validate_supplier_url(
        "https://dashscope.aliyuncs.com/result.wav"
    ).startswith("https://")


class _CaptureDashScopeClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __enter__(self) -> _CaptureDashScopeClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class _CaptureDownloader:
    def __init__(self) -> None:
        self.url: str | None = None

    def download(self, value: str) -> bytes:
        self.url = value
        return _wav(2)


def _provider_response(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        json=payload,
        request=httpx.Request("POST", "https://provider.invalid"),
    )


def test_dashscope_voice_and_tts_adapters_match_current_official_http_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _CaptureDashScopeClient(
        [
            _provider_response(
                {
                    "output": {
                        "voice": "maya123456789012-generated",
                        "target_model": "qwen3-tts-vc-2026-01-22",
                        "fallback_mode": False,
                    },
                    "request_id": "enroll-request",
                }
            ),
            _provider_response(
                {
                    "output": {
                        "voice_list": [
                            {
                                "voice": "maya123456789012-generated",
                                "target_model": "qwen3-tts-vc-2026-01-22",
                            }
                        ]
                    },
                    "request_id": "list-request",
                }
            ),
            _provider_response({"output": {"voice": "maya123456789012-generated"}}),
        ]
    )
    monkeypatch.setattr(dashscope, "_client", lambda: capture)
    config = dashscope.DashScopeConfig(api_key="fixture", workspace_id="workspace123")
    voice = dashscope.DashScopeVoiceCloneProvider(config)
    enrolled = voice.enroll(
        "data:audio/wav;base64,AAAA",
        recovery_name="maya123456789012",
        target_model_key="qwen3-tts-vc-2026-01-22",
        language="en",
    )
    assert enrolled.external_voice_id == "maya123456789012-generated"
    assert enrolled.request_id == "enroll-request"
    exists = voice.exists(
        "maya123456789012", target_model_key="qwen3-tts-vc-2026-01-22"
    )
    assert exists.matches == ("maya123456789012-generated",)
    voice.delete(
        "maya123456789012-generated", target_model_key="qwen3-tts-vc-2026-01-22"
    )
    expected_customization = (
        "https://workspace123.cn-beijing.maas.aliyuncs.com"
        "/api/v1/services/audio/tts/customization"
    )
    assert [call[0] for call in capture.calls] == [expected_customization] * 3
    create_body = capture.calls[0][1]["json"]
    assert isinstance(create_body, dict)
    assert create_body["model"] == "qwen-voice-enrollment"
    assert create_body["input"] == {
        "action": "create",
        "target_model": "qwen3-tts-vc-2026-01-22",
        "preferred_name": "maya123456789012",
        "audio": {"data": "data:audio/wav;base64,AAAA"},
        "language": "en",
    }
    assert capture.calls[1][1]["json"] == {
        "model": "qwen-voice-enrollment",
        "input": {"action": "list", "page_index": 0, "page_size": 100},
    }
    assert capture.calls[2][1]["json"] == {
        "model": "qwen-voice-enrollment",
        "input": {"action": "delete", "voice": "maya123456789012-generated"},
    }

    tts_capture = _CaptureDashScopeClient(
        [
            _provider_response(
                {
                    "output": {
                        "audio": {
                            "url": "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/preview.wav?Expires=1"
                        }
                    },
                    "request_id": "tts-request",
                }
            )
        ]
    )
    monkeypatch.setattr(dashscope, "_client", lambda: tts_capture)
    downloader = _CaptureDownloader()
    tts = dashscope.DashScopeTTSProvider(config, downloader=downloader)
    result = tts.synthesize("A new English sentence.", enrolled.external_voice_id)
    assert result.request_id == "tts-request"
    assert downloader.url and downloader.url.endswith("?Expires=1")
    assert tts_capture.calls[0][0] == (
        "https://dashscope.aliyuncs.com/"
        "api/v1/services/aigc/multimodal-generation/generation"
    )
    assert tts_capture.calls[0][1]["json"] == {
        "model": "qwen3-tts-vc-2026-01-22",
        "input": {
            "text": "A new English sentence.",
            "voice": "maya123456789012-generated",
        },
    }


def test_dashscope_exists_requires_a_complete_paginated_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_page = [
        {"voice": f"unrelated-{index}", "target_model": "qwen3-tts-vc-2026-01-22"}
        for index in range(100)
    ]
    incomplete_capture = _CaptureDashScopeClient(
        [_provider_response({"output": {"voice_list": full_page}}) for _page in range(10)]
    )
    monkeypatch.setattr(dashscope, "_client", lambda: incomplete_capture)
    provider = dashscope.DashScopeVoiceCloneProvider(
        dashscope.DashScopeConfig(api_key="fixture", workspace_id="workspace123")
    )
    incomplete = provider.exists(
        "maya123456789012", target_model_key="qwen3-tts-vc-2026-01-22"
    )
    assert incomplete.matches == ()
    assert incomplete.visibility_known is False
    assert len(incomplete_capture.calls) == 10

    complete_capture = _CaptureDashScopeClient(
        [
            _provider_response(
                {"output": {"voice_list": full_page, "total_count": 201}}
            ),
            _provider_response(
                {"output": {"voice_list": full_page, "total_count": 201}}
            ),
            _provider_response(
                {
                    "output": {
                        "voice_list": [
                            {
                                "voice": "maya123456789012-generated",
                                "target_model": "qwen3-tts-vc-2026-01-22",
                            }
                        ],
                        "total_count": 201,
                    }
                }
            ),
        ]
    )
    monkeypatch.setattr(dashscope, "_client", lambda: complete_capture)
    complete = provider.exists(
        "maya123456789012", target_model_key="qwen3-tts-vc-2026-01-22"
    )
    assert complete.matches == ("maya123456789012-generated",)
    assert complete.visibility_known is True
    assert len(complete_capture.calls) == 3


def test_supplier_downloader_rejects_dns_private_address_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dashscope,
        "_resolved_public_addresses",
        lambda _hostname: (_ for _ in ()).throw(TTSProviderError("private")),
    )
    downloader = dashscope.SupplierAudioDownloader(max_bytes=100)
    with pytest.raises(TTSProviderError):
        downloader.download("https://dashscope.aliyuncs.com/result.wav")


def test_supplier_dns_resolution_has_a_hard_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = Event()

    def blocked_resolution(*_args: object, **_kwargs: object) -> list[object]:
        release.wait(1)
        return []

    monkeypatch.setattr(dashscope.socket, "getaddrinfo", blocked_resolution)
    try:
        with pytest.raises(TTSProviderTimeout):
            dashscope._resolved_public_addresses(
                "dashscope.aliyuncs.com", timeout_seconds=0.01
            )
    finally:
        release.set()


def test_supplier_downloader_uses_only_the_approved_numeric_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dashscope, "_resolved_public_addresses", lambda _hostname: ("1.2.3.4",))
    calls: list[tuple[str, str, str, int]] = []

    def pinned(
        url: str,
        hostname: str,
        address: str,
        *,
        max_bytes: int,
        deadline: float,
    ) -> bytes:
        del deadline
        calls.append((url, hostname, address, max_bytes))
        return b"audio"

    monkeypatch.setattr(dashscope, "_download_from_pinned_address", pinned)
    result = dashscope.SupplierAudioDownloader(max_bytes=100).download(
        "https://dashscope.aliyuncs.com/result.wav?Expires=1"
    )
    assert result == b"audio"
    assert calls == [
        (
            "https://dashscope.aliyuncs.com/result.wav?Expires=1",
            "dashscope.aliyuncs.com",
            "1.2.3.4",
            100,
        )
    ]


def test_pinned_connection_rejects_peer_change_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class RawSocket:
        def settimeout(self, _timeout: float) -> None:
            return None

        def connect(self, destination: tuple[object, ...]) -> None:
            events.append(f"tcp:{destination[0]}")

        def close(self) -> None:
            events.append("raw-close")

    class WrappedSocket:
        def getpeername(self) -> tuple[str, int]:
            return ("10.0.0.2", 443)

        def settimeout(self, _timeout: float) -> None:
            return None

        def close(self) -> None:
            events.append("tls-close")

    class Context:
        def wrap_socket(self, _socket: RawSocket, *, server_hostname: str) -> WrappedSocket:
            events.append(f"tls:{server_hostname}")
            return WrappedSocket()

    monkeypatch.setattr(dashscope.socket, "socket", lambda *_args: RawSocket())
    monkeypatch.setattr(dashscope.ssl, "create_default_context", lambda: Context())
    connection = dashscope._PinnedHTTPSConnection(
        "dashscope.aliyuncs.com", "1.2.3.4", dashscope.time.monotonic() + 60
    )
    with pytest.raises(TTSProviderError):
        connection.connect()
    assert events[:2] == ["tcp:1.2.3.4", "tls:dashscope.aliyuncs.com"]
    assert "tls-close" in events


def test_supplier_downloader_enforces_one_total_deadline_across_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [1_000.0]
    calls: list[str] = []
    monkeypatch.setattr(dashscope.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        dashscope,
        "_resolved_public_addresses",
        lambda _hostname: ("1.2.3.4", "5.6.7.8"),
    )

    def elapsed_failure(
        _url: str,
        _hostname: str,
        address: str,
        *,
        max_bytes: int,
        deadline: float,
    ) -> bytes:
        del max_bytes, deadline
        calls.append(address)
        clock[0] += 61.0
        raise TTSProviderError("first address failed")

    monkeypatch.setattr(dashscope, "_download_from_pinned_address", elapsed_failure)
    with pytest.raises(TTSProviderTimeout):
        dashscope.SupplierAudioDownloader(max_bytes=100).download(
            "https://dashscope.aliyuncs.com/result.wav"
        )
    assert calls == ["1.2.3.4"]


def test_0003_migration_preserves_populated_wave1a_rows(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.sqlite3'}"
    database = Database(database_url, tmp_path)
    migration_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    migration_config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    migration_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(migration_config, "0002_wave1_agents_rag")
    now = datetime.now(UTC)
    with database.session() as session:
        seed_demo_data(session)
    with database.session() as session:
        session.execute(
            text(
                "INSERT INTO agents "
                "(id, group_id, name, description, status, created_at, updated_at) "
                "VALUES (:id, :group_id, :name, :description, :status, :created_at, :updated_at)"
            ),
            {
                "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                "group_id": GROUP_A,
                "name": "Preserved Agent",
                "description": "snapshot row",
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
        )
        session.execute(
            text(
                "INSERT INTO agent_versions "
                "(id, agent_id, version_seq, state, revision, agent_md, avatar_config_json, "
                "voice_profile_id, knowledge_snapshot_id, published_at, created_at, updated_at) "
                "VALUES (:id, :agent_id, 0, 'draft', 7, :agent_md, :avatar, :voice, NULL, "
                "NULL, :created_at, :updated_at)"
            ),
            {
                "id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                "agent_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                "agent_md": "# preserved",
                "avatar": '{"template_id":"wave1-default-head"}',
                "voice": "legacy-voice-reference",
                "created_at": now,
                "updated_at": now,
            },
        )
    with database.engine.connect() as connection:
        before = connection.execute(
            text(
                "SELECT agents.id, group_id, name, description, status, revision, agent_md, "
                "avatar_config_json, voice_profile_id FROM agents "
                "JOIN agent_versions ON agent_versions.agent_id = agents.id"
            )
        ).mappings().all()
    command.upgrade(migration_config, "head")
    command.upgrade(migration_config, "head")
    with database.engine.connect() as connection:
        schema = inspect(connection)
        assert {
            "voice_profiles",
            "voice_provider_operations",
            "voice_previews",
        }.issubset(set(schema.get_table_names()))
        assert {item["name"] for item in schema.get_check_constraints("voice_profiles")} == {
            "ck_voice_profiles_scope",
            "ck_voice_profiles_scope_group",
            "ck_voice_profiles_status",
        }
        assert {
            item["name"] for item in schema.get_check_constraints("voice_provider_operations")
        } == {
            "ck_voice_provider_operations_attempt",
            "ck_voice_provider_operations_counters",
            "ck_voice_provider_operations_scope",
            "ck_voice_provider_operations_state",
            "ck_voice_provider_operations_type",
        }
        assert {item["name"] for item in schema.get_check_constraints("voice_previews")} == {
            "ck_voice_previews_state"
        }
        assert {
            item["name"] for item in schema.get_unique_constraints("voice_profiles")
        } == {"uq_voice_profiles_recovery_name"}
        profile_indexes = {item["name"]: item for item in schema.get_indexes("voice_profiles")}
        assert set(profile_indexes) == {
            "ix_voice_profiles_group_status",
            "uq_voice_profiles_one_system",
        }
        assert profile_indexes["uq_voice_profiles_one_system"]["unique"] == 1
        operation_indexes = {
            item["name"]: item for item in schema.get_indexes("voice_provider_operations")
        }
        assert set(operation_indexes) == {
            "ix_voice_provider_operations_profile",
            "ix_voice_provider_operations_state_deadline",
            "uq_voice_provider_operations_profile_delete",
            "uq_voice_provider_operations_system_enroll_active",
        }
        assert operation_indexes["uq_voice_provider_operations_profile_delete"]["unique"] == 1
        assert (
            operation_indexes["uq_voice_provider_operations_system_enroll_active"]["unique"]
            == 1
        )
        assert {item["name"] for item in schema.get_indexes("voice_previews")} == {
            "ix_voice_previews_expiry",
            "ix_voice_previews_profile_state",
        }
        assert {item["name"] for item in schema.get_foreign_keys("voice_profiles")} == {
            "fk_voice_profiles_consent_actor",
            "fk_voice_profiles_group",
        }
        assert {
            item["name"] for item in schema.get_foreign_keys("voice_provider_operations")
        } == {
            "fk_voice_provider_operations_idempotency",
            "fk_voice_provider_operations_profile",
        }
        assert {item["name"] for item in schema.get_foreign_keys("voice_previews")} == {
            "fk_voice_previews_group",
            "fk_voice_previews_profile",
            "fk_voice_previews_stored_file",
        }
        after = connection.execute(
            text(
                "SELECT agents.id, group_id, name, description, status, revision, agent_md, "
                "avatar_config_json, voice_profile_id FROM agents "
                "JOIN agent_versions ON agent_versions.agent_id = agents.id"
            )
        ).mappings().all()
        assert list(before) == list(after)
        assert connection.execute(text("SELECT COUNT(*) FROM voice_profiles")).scalar_one() == 0
    database.dispose()


def _fallback_settings(tmp_path: Path) -> Settings:
    return Settings(
        maya_env="test",
        session_secret="f" * 32,
        database_url=f"sqlite:///{tmp_path / 'fallback.sqlite3'}",
        data_root=tmp_path / "fallback-data",
    )


class _FlakyFallbackTTS:
    key = "mock"
    target_model_key = "mock-tts-v1"

    def __init__(self) -> None:
        self.calls = 0

    def synthesize(self, text: str, external_voice_id: str, *, language: str = "en") -> TTSResult:
        del text, external_voice_id, language
        self.calls += 1
        if self.calls == 1:
            raise TTSProviderTimeout("transient preview timeout")
        return TTSResult(_wav())


def test_fallback_enroll_and_verify_are_explicit_and_source_is_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _fallback_settings(tmp_path)
    source = tmp_path / "fallback.wav"
    source.write_bytes(_wav())
    source_mode = source.stat().st_mode
    source_bytes = source.read_bytes()
    voice = MockVoiceCloneProvider()
    tts = _FlakyFallbackTTS()
    monkeypatch.setattr("app.modules.voices.fallback.voice_provider", lambda _settings: voice)
    monkeypatch.setattr("app.modules.voices.fallback.tts_provider", lambda _settings: tts)

    profile_id = enroll_system_fallback(settings, source, stage="enroll")
    assert voice.enroll_calls == 1
    assert tts.calls == 0
    with Database(settings.database_url, settings.resolved_data_root).session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None and profile.status == "preview_ready"
        first_operation = session.scalar(
            select(VoiceProviderOperation).where(
                VoiceProviderOperation.profile_id == profile_id,
                VoiceProviderOperation.operation_type == "enroll",
            )
        )
        assert first_operation is not None and first_operation.state == "succeeded"
    # A repeated enroll stage returns the existing mapping and never creates a
    # second platform fallback, even though the source is supplied again.
    assert enroll_system_fallback(settings, source, stage="enroll") == profile_id
    assert voice.enroll_calls == 1
    assert tts.calls == 0

    assert enroll_system_fallback(settings, stage="verify") == profile_id
    assert tts.calls == 2
    with Database(settings.database_url, settings.resolved_data_root).session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None and profile.status == "ready"
        preview_operation = session.scalar(
            select(VoiceProviderOperation).where(
                VoiceProviderOperation.profile_id == profile_id,
                VoiceProviderOperation.operation_type == "tts_preview",
            )
        )
        assert preview_operation is not None
        assert preview_operation.state == "succeeded"
        assert preview_operation.attempt == 2
        assert preview_operation.request_count == 2
        assert preview_operation.charged_request_count == 0
    # A ready verify is idempotent and does not synthesize again.
    assert enroll_system_fallback(settings, stage="verify") == profile_id
    assert tts.calls == 2
    assert source.read_bytes() == source_bytes
    assert source.stat().st_mode == source_mode
    temporary_root = settings.resolved_data_root / "tmp" / "voice-enrollment"
    assert not temporary_root.exists() or not list(temporary_root.iterdir())


def test_fallback_timeout_reconciles_unique_match_but_never_creates_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _fallback_settings(tmp_path)
    source = tmp_path / "fallback.wav"
    source.write_bytes(_wav())
    voice = MockVoiceCloneProvider()
    voice.next_enroll_error = VoiceProviderTimeout("provider timed out")
    monkeypatch.setattr("app.modules.voices.fallback.voice_provider", lambda _settings: voice)
    with pytest.raises(FallbackEnrollmentError):
        enroll_system_fallback(settings, source, stage="enroll")
    with Database(settings.database_url, settings.resolved_data_root).session() as session:
        profile = session.scalar(select(VoiceProfile).where(VoiceProfile.scope == "system"))
        assert profile is not None and profile.status == "outcome_unknown"
        operation = session.scalar(
            select(VoiceProviderOperation).where(
                VoiceProviderOperation.profile_id == profile.id,
                VoiceProviderOperation.operation_type == "enroll",
            )
        )
        assert operation is not None and operation.state == "outcome_unknown"
        recovery_name = profile.recovery_name
    voice.set_reconciliation_matches(recovery_name, ("recovered-fallback-id",))
    assert enroll_system_fallback(settings, source, stage="enroll") == profile.id
    assert voice.enroll_calls == 1
    with Database(settings.database_url, settings.resolved_data_root).session() as session:
        profile = session.get(VoiceProfile, profile.id)
        assert profile is not None and profile.status == "preview_ready"


def test_fallback_ambiguous_recovery_stays_unknown_and_provider_selectors_are_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _fallback_settings(tmp_path)
    source = tmp_path / "fallback.wav"
    source.write_bytes(_wav())
    voice = MockVoiceCloneProvider()
    voice.next_enroll_error = VoiceProviderError("unknown outcome")
    monkeypatch.setattr("app.modules.voices.fallback.voice_provider", lambda _settings: voice)
    with pytest.raises(FallbackEnrollmentError):
        enroll_system_fallback(settings, source, stage="enroll")
    with Database(settings.database_url, settings.resolved_data_root).session() as session:
        profile = session.scalar(select(VoiceProfile).where(VoiceProfile.scope == "system"))
        assert profile is not None
        recovery_name = profile.recovery_name
    voice.set_reconciliation_matches(recovery_name, ("one", "two"))
    with pytest.raises(FallbackEnrollmentError):
        enroll_system_fallback(settings, source, stage="enroll")
    assert voice.enroll_calls == 1
    settings.tts_provider = "dashscope"
    with pytest.raises(FallbackEnrollmentError):
        enroll_system_fallback(settings, source, stage="enroll")
    assert voice.enroll_calls == 1


@pytest.mark.asyncio
async def test_streamed_upload_rejects_over_limit_without_materialising_file(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    content = b"x" * (10 * 1024 * 1024 + 1)
    body, boundary = _multipart("sample.wav", content, chunk_size=64 * 1024)
    request = _stream_request(body, boundary, chunk_size=64 * 1024)
    with pytest.raises(VoiceUploadTooLarge):
        await stream_voice_upload(request, data_root)
    temporary_root = data_root / "tmp" / "voice-enrollment"
    assert not temporary_root.exists() or not list(temporary_root.iterdir())


@pytest.mark.asyncio
async def test_streamed_upload_disconnect_cleans_request_tree(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    body, boundary = _multipart("sample.wav", b"partial-audio" * 1000)
    request = _stream_request(body, boundary, chunk_size=128, disconnect_after=2)
    with pytest.raises(VoiceUploadDisconnected):
        await stream_voice_upload(request, data_root)
    temporary_root = data_root / "tmp" / "voice-enrollment"
    assert not temporary_root.exists() or not list(temporary_root.iterdir())


def test_startup_cleanup_only_removes_aged_uuid_trees(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    root = data_root / "tmp" / "voice-enrollment"
    root.mkdir(parents=True)
    now = 10_000.0
    stale_id = "11111111-1111-4111-8111-111111111111"
    active_id = "22222222-2222-4222-8222-222222222222"
    stale = root / stale_id
    active = root / active_id
    stale.mkdir()
    (stale / "source.upload").write_bytes(b"discard")
    active.mkdir()
    (active / ".active").touch()
    os.utime(active, (now, now))
    os.utime(active / ".active", (now, now))
    (root / "not-a-uuid").mkdir()
    external = tmp_path / "outside"
    external.mkdir()
    (root / "33333333-3333-4333-8333-333333333333").symlink_to(external, target_is_directory=True)
    # The stale tree has no active marker and is older than the threshold.
    os.utime(stale, (now - 2_000, now - 2_000))
    removed = cleanup_voice_temp_dirs(data_root, age_seconds=900, now=now)
    assert stale_id in removed
    assert not stale.exists()
    assert active.exists()
    assert (root / "not-a-uuid").exists()
    assert external.exists() and not list(external.iterdir())


def test_startup_cleanup_never_removes_an_aged_but_locked_active_request(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    root = data_root / "tmp" / "voice-enrollment"
    request_id = "44444444-4444-4444-8444-444444444444"
    request = root / request_id
    request.mkdir(parents=True)
    marker = request / ".active"
    marker.touch()
    lease = marker.open("rb")
    fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        os.utime(request, (1_000.0, 1_000.0))
        os.utime(marker, (1_000.0, 1_000.0))
        assert cleanup_voice_temp_dirs(data_root, age_seconds=900, now=10_000.0) == []
        assert request.exists()
    finally:
        fcntl.flock(lease.fileno(), fcntl.LOCK_UN)
        lease.close()
    assert cleanup_voice_temp_dirs(data_root, age_seconds=900, now=10_000.0) == [request_id]
    assert not request.exists()


def test_ffmpeg_refuses_symlink_output_before_process_start(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"input")
    target = tmp_path / "normalized.wav"
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"must-remain")
    target.symlink_to(outside)
    with pytest.raises(AudioValidationError):
        run_ffmpeg_normalize(source, target)
    assert outside.read_bytes() == b"must-remain"


def test_ffmpeg_timeout_terminates_and_closes_process_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"input")
    target = tmp_path / "normalized.wav"

    class Handle:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class HangingProcess:
        pid = None
        returncode = 0

        def __init__(self) -> None:
            self.stdin = Handle()
            self.stdout = Handle()
            self.stderr = Handle()
            self.terminated = False
            self.killed = False
            self.communicate_calls = 0

        def poll(self) -> int | None:
            return None if not self.terminated and not self.killed else 0

        def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
            del timeout
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                from subprocess import TimeoutExpired

                raise TimeoutExpired("ffmpeg", 0.01)
            return b"", b""

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            self.terminated = True
            return 0

    process = HangingProcess()
    monkeypatch.setattr("app.providers.audio.subprocess.Popen", lambda *args, **kwargs: process)
    with pytest.raises(AudioProcessError):
        run_ffmpeg_normalize(source, target, timeout_seconds=0.01)
    assert process.terminated or process.killed
    assert process.stdin.closed and process.stdout.closed and process.stderr.closed
