from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.models import GroupMember, VoiceProfile, VoiceProviderOperation
from app.modules.voices import service as voice_service
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, inspect, select

from tests.conftest import login

GROUP_A = "7813f937-902c-5534-bfb2-ad773a43aeda"


@pytest.fixture
def rename_client(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
) -> Iterator[tuple[TestClient, Database, str, str]]:
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        user, csrf = login(client, "bowen")
        profile_id = str(uuid4())
        timestamp = datetime.now(UTC)
        with database.session() as session:
            session.add(
                VoiceProfile(
                    id=profile_id,
                    scope="group",
                    group_id=GROUP_A,
                    display_name="Original voice",
                    status="ready",
                    provider_key="mock",
                    target_model_key="mock-voice-v1",
                    external_id_encrypted=b"retained-encrypted-mapping",
                    recovery_name=f"rename-{profile_id}",
                    provenance_json="{}",
                    source_filename="original.wav",
                    source_sha256="a" * 64,
                    consent_copy_version="voice-consent-v1",
                    consent_actor_user_id=user["user"]["id"],
                    consent_accepted_at=timestamp,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        yield client, database, profile_id, csrf


def _headers(csrf: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf}


@pytest.mark.parametrize(
    "status",
    [
        "validating",
        "enrolling",
        "preview_ready",
        "ready",
        "deleting",
        "outcome_unknown",
        "failed",
        "deleted",
    ],
)
def test_rename_persists_without_changing_voice_state_or_provider_mapping(
    rename_client: tuple[TestClient, Database, str, str],
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    client, database, profile_id, csrf = rename_client

    def unexpected_provider(*args: object, **kwargs: object) -> None:
        pytest.fail("Renaming must not call a voice provider.")

    monkeypatch.setattr(voice_service, "voice_provider", unexpected_provider)
    with database.session() as session:
        row = session.get(VoiceProfile, profile_id)
        assert row is not None
        row.status = status
        before = {column.key: getattr(row, column.key) for column in inspect(VoiceProfile).columns}
        operation_count = session.scalar(select(func.count()).select_from(VoiceProviderOperation))
    for _ in range(2):
        response = client.patch(
            f"/api/v1/voice-profiles/{profile_id}",
            headers=_headers(csrf),
            json={"source_filename": "  哲学声音 🎙.wav  "},
        )
        assert response.status_code == 200, response.text
        assert response.json()["source_filename"] == "哲学声音 🎙.wav"
        assert response.json()["status"] == status
        assert "external" not in response.text
    assert client.get(f"/api/v1/voice-profiles/{profile_id}").json()["source_filename"] == (
        "哲学声音 🎙.wav"
    )
    profiles = client.get(f"/api/v1/groups/{GROUP_A}/voice-profiles").json()
    assert (
        next(profile for profile in profiles if profile["id"] == profile_id)["source_filename"]
        == "哲学声音 🎙.wav"
    )
    with database.session() as session:
        row = session.get(VoiceProfile, profile_id)
        assert row is not None
        for key, value in before.items():
            if key not in {"source_filename", "updated_at"}:
                assert getattr(row, key) == value, key
        assert (
            session.scalar(select(func.count()).select_from(VoiceProviderOperation))
            == operation_count
        )


@pytest.mark.parametrize(
    "name", ["", "   ", ".", "..", "../a.wav", "a/b", "a\\b", "a\x00b", "a\nb", "a" * 256]
)
def test_rename_rejects_invalid_names_without_mutation(
    rename_client: tuple[TestClient, Database, str, str], name: str
) -> None:
    client, database, profile_id, csrf = rename_client
    response = client.patch(
        f"/api/v1/voice-profiles/{profile_id}",
        headers=_headers(csrf),
        json={"source_filename": name},
    )
    assert response.status_code == 400, response.text
    with database.session() as session:
        row = session.get(VoiceProfile, profile_id)
        assert row is not None and row.source_filename == "original.wav"


def test_rename_requires_owner_and_current_workspace_membership(
    rename_client: tuple[TestClient, Database, str, str],
) -> None:
    client, database, profile_id, _csrf = rename_client
    csrf = login(client, "kaikai")[1]
    response = client.patch(
        f"/api/v1/voice-profiles/{profile_id}",
        headers=_headers(csrf),
        json={"source_filename": "other.wav"},
    )
    assert response.status_code == 404, response.text
    owner, csrf = login(client, "bowen")
    with database.session() as session:
        session.execute(delete(GroupMember).where(GroupMember.user_id == owner["user"]["id"]))
    response = client.patch(
        f"/api/v1/voice-profiles/{profile_id}",
        headers=_headers(csrf),
        json={"source_filename": "other.wav"},
    )
    assert response.status_code == 404, response.text
    with database.session() as session:
        row = session.get(VoiceProfile, profile_id)
        assert row is not None and row.source_filename == "original.wav"


def test_rename_requires_csrf_and_authentication(
    rename_client: tuple[TestClient, Database, str, str],
) -> None:
    client, database, profile_id, _csrf = rename_client
    url = f"/api/v1/voice-profiles/{profile_id}"
    response = client.patch(url, headers=_headers("x" * 32), json={"source_filename": "bad.wav"})
    assert response.status_code == 403, response.text
    client.cookies.clear()
    response = client.patch(url, headers=_headers("x" * 32), json={"source_filename": "bad.wav"})
    assert response.status_code == 401, response.text
    with database.session() as session:
        row = session.get(VoiceProfile, profile_id)
        assert row is not None and row.source_filename == "original.wav"
