"""A course teacher lists a group's shared voices read-only (owner decision 2026-10-23).

The Agent editor shows the group's Voices. A course teacher may edit a
student's public Agent without entering the group (PR #229), so the list must
answer them too: the group students' ready voices, never manageable by the
teacher. Entering the group changes nothing here. A student of another group
still gets 404.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.core.models import VoiceProfile
from app.seed import BOWEN_ID, COURSE_ID

from tests.conftest import login, make_foreign_group
from tests.test_public_agent_group_edit import _add_user
from tests.test_teacher_open_student_agent import _login_id

GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
VOICES = f"/api/v1/groups/{GROUP_ID}/voice-profiles"


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


def test_course_teacher_lists_group_voices_read_only(client):
    database = client.app.state.database
    ready = _voice(database, "ready")
    _voice(database, "validating")
    other_group_student = _add_user(
        database,
        role="student",
        course_id=COURSE_ID,
        group_id=make_foreign_group(database, COURSE_ID),
    )

    login(client, "bowen")
    own = client.get(VOICES)
    assert own.status_code == 200, own.text
    assert {item["id"]: item["can_manage"] for item in own.json()}[ready] is True

    # Not entered: the teacher still sees the ready voice, read-only.
    client.cookies.clear()
    _, teacher_csrf = login(client, "maya")
    outside = client.get(VOICES)
    assert outside.status_code == 200, outside.text
    assert [(item["id"], item["can_manage"]) for item in outside.json()] == [(ready, False)]

    # Entered (temporary membership): the same single read-only voice.
    joined = client.post(
        f"/api/v1/groups/{GROUP_ID}/membership",
        headers={"Origin": "http://testserver", "X-CSRF-Token": teacher_csrf},
    )
    assert joined.status_code == 200, joined.text
    inside = client.get(VOICES)
    assert inside.status_code == 200, inside.text
    assert [(item["id"], item["can_manage"]) for item in inside.json()] == [(ready, False)]

    # A student of another group is outside this group's Voices.
    _login_id(client, other_group_student)
    assert client.get(VOICES).status_code == 404
