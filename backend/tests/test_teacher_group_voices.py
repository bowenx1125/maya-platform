"""A course teacher's rights over a group's student voices.

Owner decision (2026-10-23): a course teacher lists the group's voices (they
edit the group's public Agents without entering the group, PR #229).
Owner decision (2026-10-26): that teacher has the student's rights over a
student's group clone: play it, bind it to an Agent and manage it (rename,
confirm, delete), whether or not they entered the group. A teacher of
another course and a student of another group still get 404, and the
owner's own behaviour is unchanged.
"""

from __future__ import annotations

import io
import logging
import wave
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import Agent, AgentVersion, VoiceProfile
from app.modules.voices.service import validate_voice_binding
from app.seed import BOWEN_ID, COURSE_ID, TEACHER_ID

from tests.conftest import login, make_foreign_group
from tests.test_public_agent_group_edit import _add_user
from tests.test_teacher_open_student_agent import _login_id
from tests.test_wave3_agent_metadata import _context

GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
VOICES = f"/api/v1/groups/{GROUP_ID}/voice-profiles"


def _headers(csrf: str, key: str | None = None) -> dict[str, str]:
    headers = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _wav(seconds: int = 10) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24_000)
        stream.writeframes((b"\x00\x01" * 24_000) * seconds)
    return output.getvalue()


def _voice(database, status: str) -> str:
    profile_id = str(uuid4())
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            VoiceProfile(
                id=profile_id,
                scope="group",
                group_id=GROUP_ID,
                display_name=f"Bowen {status}",
                status=status,
                provider_key="test",
                target_model_key="test",
                recovery_name=f"teacher-voices-{uuid4().hex}",
                consent_actor_user_id=BOWEN_ID,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    return profile_id


def _enrolled_ready_voice(client) -> str:
    _, csrf = login(client, "bowen")
    enrolled = client.post(
        VOICES,
        headers=_headers(csrf, f"teacher-voice-enroll-{uuid4()}"),
        data={"consent_accepted": "true"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert enrolled.status_code == 202, enrolled.text
    profile_id = enrolled.json()["id"]
    with client.app.state.database.session() as db:
        db.get(VoiceProfile, profile_id).status = "ready"
    return profile_id


def test_course_teacher_lists_and_manages_group_voices(client):
    database = client.app.state.database
    ready = _voice(database, "ready")
    validating = _voice(database, "validating")
    other_group_student = _add_user(
        database,
        role="student",
        course_id=COURSE_ID,
        group_id=make_foreign_group(database, COURSE_ID),
    )

    login(client, "bowen")
    own = client.get(VOICES)
    assert own.status_code == 200, own.text
    assert {item["id"]: item["can_manage"] for item in own.json()} == {
        ready: True,
        validating: True,
    }

    # Not entered: the teacher sees the students' voices, as the student does,
    # and may manage them.
    client.cookies.clear()
    _, teacher_csrf = login(client, "maya")
    outside = client.get(VOICES)
    assert outside.status_code == 200, outside.text
    assert {item["id"]: item["can_manage"] for item in outside.json()} == {
        ready: True,
        validating: True,
    }

    # Entered (temporary membership): the same.
    joined = client.post(f"/api/v1/groups/{GROUP_ID}/membership", headers=_headers(teacher_csrf))
    assert joined.status_code == 200, joined.text
    inside = client.get(VOICES)
    assert {item["id"]: item["can_manage"] for item in inside.json()} == {
        ready: True,
        validating: True,
    }

    # A student of another group is outside this group's Voices.
    _login_id(client, other_group_student)
    assert client.get(VOICES).status_code == 404


def test_course_teacher_plays_renames_and_deletes_a_students_voice(client, caplog):
    caplog.set_level(logging.INFO, logger="app.modules.voices.service")
    profile_id = _enrolled_ready_voice(client)
    _, owner_csrf = login(client, "bowen")
    owner_preview = client.post(
        f"/api/v1/voice-profiles/{profile_id}/preview", headers=_headers(owner_csrf)
    )
    assert owner_preview.status_code == 200, owner_preview.text
    owner_url = owner_preview.json()["playback_url"]

    client.cookies.clear()
    _, teacher_csrf = login(client, "maya")
    assert client.get(f"/api/v1/voice-profiles/{profile_id}").status_code == 200
    heard = client.post(
        f"/api/v1/voice-profiles/{profile_id}/preview", headers=_headers(teacher_csrf)
    )
    assert heard.status_code == 200, heard.text
    assert client.get(heard.json()["playback_url"]).status_code == 200
    # The student's own preview keeps playing.
    assert client.get(owner_url).status_code == 200

    renamed = client.patch(
        f"/api/v1/voice-profiles/{profile_id}",
        headers=_headers(teacher_csrf),
        json={"source_filename": "renamed by teacher.wav"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["source_filename"] == "renamed by teacher.wav"
    # The log names the teacher as the actor and the student as the owner.
    assert (
        f"voice_managed_by_course_teacher action=rename profile_id={profile_id} "
        f"actor_user_id={TEACHER_ID} owner_user_id={BOWEN_ID}"
    ) in caplog.text

    deleted = client.delete(
        f"/api/v1/voice-profiles/{profile_id}",
        headers=_headers(teacher_csrf, f"teacher-voice-delete-{uuid4()}"),
    )
    assert deleted.status_code in {200, 202}, deleted.text
    assert f"action=delete profile_id={profile_id} actor_user_id={TEACHER_ID}" in caplog.text
    with client.app.state.database.session() as db:
        row = db.get(VoiceProfile, profile_id)
        assert row is None or row.status in {"deleting", "deleted"}


def test_course_teacher_binds_a_students_voice(client):
    profile_id = _enrolled_ready_voice(client)
    database = client.app.state.database
    settings = client.app.state.settings
    _, csrf = login(client, "bowen")
    agent = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(csrf, f"teacher-bind-agent-{uuid4()}"),
        json={"name": "Teacher bind voice", "visibility": "public"},
    )
    assert agent.status_code == 201, agent.text
    version_id = agent.json()["versions"][0]["id"]
    other_teacher = _add_user(database, role="teacher", course_id=str(uuid4()))
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        version.state = "published"
        version.published_visibility = "public"
        db.get(Agent, agent.json()["id"]).current_published_version_id = version_id
        db.flush()
        validate_voice_binding(db, _context(database, TEACHER_ID), version, profile_id, settings)
        with pytest.raises(PlatformError) as caught:
            validate_voice_binding(
                db, _context(database, other_teacher), version, profile_id, settings
            )
        assert caught.value.status_code == 404


def test_other_course_teacher_and_other_group_student_get_404(client):
    profile_id = _enrolled_ready_voice(client)
    _, owner_csrf = login(client, "bowen")
    owner_url = client.post(
        f"/api/v1/voice-profiles/{profile_id}/preview", headers=_headers(owner_csrf)
    ).json()["playback_url"]
    database = client.app.state.database
    outsiders = [
        _add_user(database, role="teacher", course_id=str(uuid4())),
        _add_user(
            database,
            role="student",
            course_id=COURSE_ID,
            group_id=make_foreign_group(database, COURSE_ID),
        ),
    ]
    for outsider in outsiders:
        csrf = _login_id(client, outsider)
        assert client.get(VOICES).status_code == 404
        assert client.get(f"/api/v1/voice-profiles/{profile_id}").status_code == 404
        assert (
            client.post(
                f"/api/v1/voice-profiles/{profile_id}/preview", headers=_headers(csrf)
            ).status_code
            == 404
        )
        assert client.get(owner_url).status_code == 404
        assert (
            client.patch(
                f"/api/v1/voice-profiles/{profile_id}",
                headers=_headers(csrf),
                json={"source_filename": "taken.wav"},
            ).status_code
            == 404
        )
        assert (
            client.delete(
                f"/api/v1/voice-profiles/{profile_id}",
                headers=_headers(csrf, f"outsider-voice-delete-{uuid4()}"),
            ).status_code
            == 404
        )
    with database.session() as db:
        profile = db.get(VoiceProfile, profile_id)
        assert profile.status == "ready" and profile.source_filename != "taken.wav"
