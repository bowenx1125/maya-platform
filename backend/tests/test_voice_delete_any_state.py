"""A voice card can always be deleted, and a slow enrollment keeps its voice.

Covers the production failures behind "outcome unknown" voices: enrollment
outliving its 10 s idempotency lease, the supplier id being dropped when that
happened, and delete refusing outcome_unknown / in-progress voices.
"""

from __future__ import annotations

import io
import wave
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.models import IdempotencyRecord, VoiceProfile, VoiceProviderOperation
from app.modules.knowledge import services as knowledge_services
from app.modules.voices import service as voice_service
from app.providers.voice import (
    MockVoiceCloneProvider,
    VoiceEnrollmentResult,
    VoiceProviderError,
    VoiceProviderTimeout,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login

GROUP_A = "7813f937-902c-5534-bfb2-ad773a43aeda"


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
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, "Idempotency-Key": key}


def _use(monkeypatch: pytest.MonkeyPatch, provider: MockVoiceCloneProvider) -> None:
    monkeypatch.setattr(voice_service, "voice_provider", lambda _settings: provider)
    monkeypatch.setattr("app.providers.factory.voice_provider", lambda _settings: provider)


def _enroll(client: TestClient, csrf: str, key: str) -> Any:
    return client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, key),
        data={"consent_accepted": "true"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )


def _delete(client: TestClient, csrf: str, profile_id: str, key: str) -> Any:
    return client.delete(f"/api/v1/voice-profiles/{profile_id}", headers=_headers(csrf, key))


def _delete_operation(database: Database, profile_id: str) -> VoiceProviderOperation | None:
    with database.session() as session:
        operation = session.scalar(
            select(VoiceProviderOperation).where(
                VoiceProviderOperation.profile_id == profile_id,
                VoiceProviderOperation.operation_type == "delete",
            )
        )
        if operation is not None:
            session.expunge(operation)
        return operation


def _status(database: Database, profile_id: str) -> str:
    with database.session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None
        return profile.status


def _lose_enrollment_outcome(database: Database, profile_id: str) -> str:
    """Make a created voice look like production's outcome_unknown cards."""

    with database.session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None
        profile.status = "outcome_unknown"
        profile.safe_error_code = "provider_unavailable"
        profile.external_id_encrypted = None
        operation = session.scalar(
            select(VoiceProviderOperation).where(
                VoiceProviderOperation.profile_id == profile_id,
                VoiceProviderOperation.operation_type == "enroll",
            )
        )
        assert operation is not None
        operation.state = "outcome_unknown"
        return profile.recovery_name


# --- delete works in every status -------------------------------------------


@pytest.mark.parametrize(
    "status",
    ["enrolling", "preview_ready", "ready", "failed", "outcome_unknown", "deleting"],
)
def test_every_voice_status_can_be_deleted(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    client, database, _settings = voice_client
    _user, csrf = login(client, "bowen")
    provider = MockVoiceCloneProvider()
    _use(monkeypatch, provider)
    created = _enroll(client, csrf, f"enroll-any-{status}-0001")
    assert created.status_code == 202, created.text
    profile_id = created.json()["id"]
    with database.session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None
        profile.status = status

    deleted = _delete(client, csrf, profile_id, f"delete-any-{status}-0001")

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "deleted"
    assert _status(database, profile_id) == "deleted"
    listed = client.get(f"/api/v1/groups/{GROUP_A}/voice-profiles").json()
    # The list keeps deleted rows for audit; the UI hides them.
    assert all(item["status"] == "deleted" for item in listed if item["id"] == profile_id)
    # The stored supplier id is deleted remotely, once.
    assert provider.delete_calls == 1
    operation = _delete_operation(database, profile_id)
    assert operation is not None and operation.state == "succeeded"


def test_outcome_unknown_voice_is_found_by_recovery_name_and_deleted(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database, _settings = voice_client
    _user, csrf = login(client, "bowen")
    provider = MockVoiceCloneProvider()
    _use(monkeypatch, provider)
    profile_id = _enroll(client, csrf, "enroll-unknown-lookup-01").json()["id"]
    recovery_name = _lose_enrollment_outcome(database, profile_id)
    provider.set_reconciliation_matches(recovery_name, ("supplier-voice-1",))
    deleted_ids: list[str] = []
    original_delete = provider.delete

    def capture_delete(external_voice_id: str, *, target_model_key: str) -> None:
        deleted_ids.append(external_voice_id)
        original_delete(external_voice_id, target_model_key=target_model_key)

    monkeypatch.setattr(provider, "delete", capture_delete)

    deleted = _delete(client, csrf, profile_id, "delete-unknown-lookup-01")

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "deleted"
    assert provider.exists_calls == 1
    assert deleted_ids == ["supplier-voice-1"]
    operation = _delete_operation(database, profile_id)
    assert operation is not None and operation.state == "succeeded"


def test_outcome_unknown_voice_with_nothing_at_the_supplier_just_goes(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database, _settings = voice_client
    _user, csrf = login(client, "bowen")
    provider = MockVoiceCloneProvider()
    _use(monkeypatch, provider)
    profile_id = _enroll(client, csrf, "enroll-unknown-empty-01").json()["id"]
    recovery_name = _lose_enrollment_outcome(database, profile_id)
    provider.set_reconciliation_matches(recovery_name, ())

    deleted = _delete(client, csrf, profile_id, "delete-unknown-empty-01")

    assert deleted.status_code == 200, deleted.text
    assert provider.exists_calls == 1
    assert provider.delete_calls == 0
    assert _status(database, profile_id) == "deleted"


def test_ambiguous_recovery_name_matches_delete_no_supplier_voice(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#141: two supplier voices share the recovery name; neither is deleted."""

    client, database, _settings = voice_client
    _user, csrf = login(client, "bowen")
    provider = MockVoiceCloneProvider()
    _use(monkeypatch, provider)
    profile_id = _enroll(client, csrf, "enroll-unknown-ambiguous").json()["id"]
    recovery_name = _lose_enrollment_outcome(database, profile_id)
    provider.set_reconciliation_matches(recovery_name, ("supplier-voice-a", "supplier-voice-b"))

    deleted = _delete(client, csrf, profile_id, "delete-unknown-ambiguous")

    assert deleted.status_code == 200, deleted.text
    assert _status(database, profile_id) == "deleted"
    assert provider.delete_calls == 0
    operation = _delete_operation(database, profile_id)
    assert operation is not None and operation.state == "outcome_unknown"


@pytest.mark.parametrize("failure", ["exists", "delete"])
def test_supplier_failure_still_deletes_the_card_and_a_later_delete_finishes_cleanup(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    client, database, _settings = voice_client
    _user, csrf = login(client, "bowen")
    provider = MockVoiceCloneProvider()
    _use(monkeypatch, provider)
    profile_id = _enroll(client, csrf, f"enroll-supplier-down-{failure}").json()["id"]
    recovery_name = _lose_enrollment_outcome(database, profile_id)
    provider.set_reconciliation_matches(recovery_name, ("supplier-voice-2",))
    if failure == "exists":
        provider.next_exists_error = VoiceProviderTimeout("supplier timed out")
    else:
        provider.next_delete_error = VoiceProviderError("supplier failed")

    first = _delete(client, csrf, profile_id, f"delete-supplier-down-{failure}-1")

    assert first.status_code == 200, first.text
    assert first.json()["status"] == "deleted"
    assert _status(database, profile_id) == "deleted"
    operation = _delete_operation(database, profile_id)
    assert operation is not None and operation.state == "outcome_unknown"

    # The supplier is back: a second delete (new key) finishes the cleanup.
    second = _delete(client, csrf, profile_id, f"delete-supplier-down-{failure}-2")
    assert second.status_code == 200, second.text
    operation = _delete_operation(database, profile_id)
    assert operation is not None and operation.state == "succeeded"


def test_refused_voice_is_deleted_without_any_supplier_call(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database, _settings = voice_client
    _user, csrf = login(client, "bowen")
    provider = MockVoiceCloneProvider()
    _use(monkeypatch, provider)
    profile_id = _enroll(client, csrf, "enroll-refused-local-01").json()["id"]
    with database.session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None
        profile.status = "failed"
        profile.safe_error_code = "voice_clone_refused"
        profile.external_id_encrypted = None
        operation = session.scalar(
            select(VoiceProviderOperation).where(VoiceProviderOperation.profile_id == profile_id)
        )
        assert operation is not None
        operation.state = "failed"
        operation.request_count = 0

    deleted = _delete(client, csrf, profile_id, "delete-refused-local-01")

    assert deleted.status_code == 200, deleted.text
    assert provider.exists_calls == 0
    assert provider.delete_calls == 0


def test_repeat_delete_of_a_deleted_voice_is_idempotent(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _database, _settings = voice_client
    _user, csrf = login(client, "bowen")
    provider = MockVoiceCloneProvider()
    _use(monkeypatch, provider)
    profile_id = _enroll(client, csrf, "enroll-repeat-delete-01").json()["id"]
    assert _delete(client, csrf, profile_id, "delete-repeat-0001").status_code == 200
    again = _delete(client, csrf, profile_id, "delete-repeat-0002")
    assert again.status_code == 200
    assert again.json()["status"] == "deleted"
    assert provider.delete_calls == 1


# --- slow enrollment ---------------------------------------------------------


class _SlowProvider(MockVoiceCloneProvider):
    """Shifts the idempotency clock forward as a slow supplier call would."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, seconds: int) -> None:
        super().__init__()
        self._monkeypatch = monkeypatch
        self._seconds = seconds

    def enroll(self, audio_data_uri: str, **kwargs: Any) -> VoiceEnrollmentResult:
        result = super().enroll(audio_data_uri, **kwargs)
        later = datetime.now(UTC) + timedelta(seconds=self._seconds)
        self._monkeypatch.setattr(knowledge_services, "now_utc", lambda: later)
        return result


def test_enrollment_longer_than_the_default_lease_is_created(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database, settings = voice_client
    _user, csrf = login(client, "bowen")
    # 15 s: longer than the 10 s claim lease, typical of upload + create +
    # review on qwen-audio-3.1-tts-flash.
    provider = _SlowProvider(monkeypatch, 15)
    _use(monkeypatch, provider)

    created = _enroll(client, csrf, "enroll-slow-supplier-01")

    assert created.status_code == 202, created.text
    assert created.json()["status"] == "preview_ready"
    with database.session() as session:
        profile = session.get(VoiceProfile, created.json()["id"])
        assert profile is not None and profile.external_id_encrypted
        record = session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.key == "enroll-slow-supplier-01")
        )
        assert record is not None and record.state == "completed"


def test_enrollment_that_loses_its_claim_still_keeps_the_supplier_voice(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database, _settings = voice_client
    _user, csrf = login(client, "bowen")
    # Even past the renewed lease the supplier voice exists: keep its id and
    # treat it as created instead of outcome_unknown.
    provider = _SlowProvider(monkeypatch, 600)
    _use(monkeypatch, provider)

    created = _enroll(client, csrf, "enroll-lost-claim-0001")

    assert created.status_code == 202, created.text
    assert created.json()["status"] == "preview_ready"
    with database.session() as session:
        profile = session.get(VoiceProfile, created.json()["id"])
        assert profile is not None
        assert profile.status == "preview_ready"
        assert profile.external_id_encrypted


def test_voice_deleted_during_enrollment_stays_deleted_and_is_removed_remotely(
    voice_client: tuple[TestClient, Database, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database, _settings = voice_client
    _user, csrf = login(client, "bowen")

    class DeleteDuringEnroll(MockVoiceCloneProvider):
        def enroll(self, audio_data_uri: str, **kwargs: Any) -> VoiceEnrollmentResult:
            result = super().enroll(audio_data_uri, **kwargs)
            with database.session() as session:
                profile = session.scalar(
                    select(VoiceProfile).where(
                        VoiceProfile.recovery_name == kwargs["recovery_name"]
                    )
                )
                assert profile is not None
                profile.status = "deleted"
            return result

    provider = DeleteDuringEnroll()
    _use(monkeypatch, provider)

    created = _enroll(client, csrf, "enroll-deleted-midway-01")

    assert created.status_code == 202, created.text
    assert created.json()["status"] == "deleted"
    assert provider.delete_calls == 1
    listed = client.get(f"/api/v1/groups/{GROUP_A}/voice-profiles").json()
    assert all(item["status"] == "deleted" for item in listed if item["id"] == created.json()["id"])
