"""A student moved to another group takes their cloned voice out of the old one.

Owner decision (2026-10-18, #158): the student's group clones in the group
they leave are deleted, locally and at the supplier, and the old groupmates'
Agents fall back to the default voice. Both ways of moving are covered: the
teacher's roster edit and the student changing their own group.
"""

from __future__ import annotations

import io
import wave
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.models import Group, VoiceProfile, VoiceProviderOperation
from app.modules.voices import service as voice_service
from app.providers.voice import MockVoiceCloneProvider, VoiceProviderError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.test_auth_self_registration import register

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
PASSWORD = "correct-horse-1"


def _wav(seconds: int = 10) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24_000)
        stream.writeframes((b"\x00\x01" * 24_000) * seconds)
    return output.getvalue()


def _headers(csrf: str, key: str | None = None) -> dict[str, str]:
    headers = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
    if key:
        headers["Idempotency-Key"] = key
    return headers


@pytest.fixture
def classroom(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[FastAPI, Database, MockVoiceCloneProvider]]:
    app, database, _settings = app_factory()
    provider = MockVoiceCloneProvider()
    monkeypatch.setattr(voice_service, "voice_provider", lambda _settings: provider)
    monkeypatch.setattr("app.providers.factory.voice_provider", lambda _settings: provider)
    with TestClient(app):
        yield app, database, provider


def _student(app: FastAPI, username: str, group_name: str) -> tuple[TestClient, str, str]:
    client = TestClient(app)
    registered = register(client, username=username, password=PASSWORD, group_name=group_name)
    assert registered.status_code == 201, registered.text
    body = registered.json()
    return client, str(body["user"]["id"]), str(body["csrf_token"])


def _group_id(database: Database, name: str) -> str:
    with database.session() as session:
        group_id = session.scalar(select(Group.id).where(Group.name == name))
        assert group_id is not None
        return str(group_id)


def _borrowed_voice(
    app: FastAPI, database: Database
) -> tuple[TestClient, str, str, TestClient, str, str]:
    """An owner's ready clone, bound to a groupmate's Agent."""

    owner, owner_id, owner_csrf = _student(app, "voiceowner", "Team Aurora")
    mate, _mate_id, mate_csrf = _student(app, "voicemate", "Team Aurora")
    _student(app, "othergroup", "Team Borealis")  # so the target group exists
    group_id = _group_id(database, "Team Aurora")
    enrolled = owner.post(
        f"/api/v1/groups/{group_id}/voice-profiles",
        headers=_headers(owner_csrf, "move-voice-enroll-0001"),
        data={"consent_accepted": "true"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert enrolled.status_code == 202, enrolled.text
    profile_id = str(enrolled.json()["id"])
    with database.session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None
        profile.status = "ready"
    agent = mate.post(
        f"/api/v1/groups/{group_id}/agents",
        headers=_headers(mate_csrf, "move-voice-agent-0001"),
        json={"name": "Borrowed voice", "description": ""},
    )
    assert agent.status_code == 201, agent.text
    draft = agent.json()["versions"][0]
    bound = mate.patch(
        f"/api/v1/agent-versions/{draft['id']}",
        headers=_headers(mate_csrf),
        json={"expected_revision": draft["revision"], "voice_profile_id": profile_id},
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["effective_voice_profile_id"] == profile_id
    return owner, owner_id, owner_csrf, mate, str(agent.json()["id"]), profile_id


def _move(app: FastAPI, how: str, owner: TestClient, owner_id: str, owner_csrf: str) -> Any:
    if how == "teacher":
        with TestClient(app) as teacher:
            _payload, csrf = login(teacher)
            return teacher.patch(
                f"/api/v1/courses/{COURSE_ID}/members/{owner_id}",
                headers=_headers(csrf),
                json={"group_name": "Team Borealis"},
            )
    return owner.patch(
        "/api/v1/auth/me", headers=_headers(owner_csrf), json={"group_name": "Team Borealis"}
    )


def _delete_state(database: Database, profile_id: str) -> tuple[str, str | None]:
    with database.session() as session:
        profile = session.get(VoiceProfile, profile_id)
        operation = session.scalar(
            select(VoiceProviderOperation).where(
                VoiceProviderOperation.profile_id == profile_id,
                VoiceProviderOperation.operation_type == "delete",
            )
        )
        assert profile is not None
        return profile.status, operation.state if operation is not None else None


@pytest.mark.parametrize("how", ["teacher", "self"])
def test_moving_a_student_deletes_their_old_group_clone_everywhere(
    classroom: tuple[FastAPI, Database, MockVoiceCloneProvider], how: str
) -> None:
    app, database, provider = classroom
    owner, owner_id, owner_csrf, mate, agent_id, profile_id = _borrowed_voice(app, database)
    assert len(provider._voices) == 1

    moved = _move(app, how, owner, owner_id, owner_csrf)

    assert moved.status_code == 200, moved.text
    assert _delete_state(database, profile_id) == ("deleted", "succeeded")
    assert provider._voices == {}
    detail = mate.get(f"/api/v1/agents/{agent_id}").json()["versions"][0]
    assert detail["effective_voice_profile_id"] != profile_id
    assert detail["voice_fallback_active"] is True


def test_supplier_failure_never_blocks_the_move(
    classroom: tuple[FastAPI, Database, MockVoiceCloneProvider],
) -> None:
    app, database, provider = classroom
    owner, owner_id, owner_csrf, mate, agent_id, profile_id = _borrowed_voice(app, database)
    provider.next_delete_error = VoiceProviderError("supplier down")

    moved = _move(app, "teacher", owner, owner_id, owner_csrf)

    assert moved.status_code == 200, moved.text
    # The card is gone and the old group falls back; the supplier delete is
    # recorded as unconfirmed for later cleanup.
    assert _delete_state(database, profile_id) == ("deleted", "outcome_unknown")
    detail = mate.get(f"/api/v1/agents/{agent_id}").json()["versions"][0]
    assert detail["voice_fallback_active"] is True


def test_moving_within_the_same_group_keeps_the_voice(
    classroom: tuple[FastAPI, Database, MockVoiceCloneProvider],
) -> None:
    app, database, provider = classroom
    owner, owner_id, _owner_csrf, mate, agent_id, profile_id = _borrowed_voice(app, database)
    with TestClient(app) as teacher:
        _payload, csrf = login(teacher)
        same = teacher.patch(
            f"/api/v1/courses/{COURSE_ID}/members/{owner_id}",
            headers=_headers(csrf),
            json={"group_name": "team aurora"},
        )
    assert same.status_code == 200, same.text
    assert _delete_state(database, profile_id) == ("ready", None)
    assert len(provider._voices) == 1
    detail = mate.get(f"/api/v1/agents/{agent_id}").json()["versions"][0]
    assert detail["effective_voice_profile_id"] == profile_id
