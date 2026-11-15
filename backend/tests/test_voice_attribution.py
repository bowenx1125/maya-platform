"""Voice album attribution follows voice read access and Agent visibility."""

from datetime import UTC, datetime
from uuid import uuid4

from app.core.models import Agent, AgentVersion, VoiceProfile
from app.modules.voices.service import voice_profile_dto
from app.seed import BOWEN_ID, COURSE_ID, TEACHER_ID

from tests.conftest import login, make_foreign_group
from tests.test_public_agent_group_edit import _add_user
from tests.test_teacher_group_voices import GROUP_ID, VOICES, _headers, _voice
from tests.test_teacher_open_student_agent import _login_id


def _bind(client, database, csrf, profile_id, *, personal=False, visibility="public"):
    path = f"courses/{COURSE_ID}/workspace-agents" if personal else f"groups/{GROUP_ID}/agents"
    created = client.post(
        f"/api/v1/{path}",
        headers=_headers(csrf, f"voice-attribution-{uuid4()}"),
        json={"name": f"Voice Agent {visibility}", "visibility": visibility},
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    version_id = created.json()["versions"][0]["id"]
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        version.voice_profile_id = profile_id
        version.state = "published"
        version.published_visibility = visibility
        db.get(Agent, agent_id).current_published_version_id = version_id
    return {"agent_id": agent_id, "name": created.json()["name"]}


def test_group_voice_attribution_for_owner_peer_and_course_teacher(client, database):
    login(client, "bowen")
    profile_id = _voice(database, "ready")
    pending_id = _voice(database, "validating")
    _, csrf = login(client, "bowen")
    public = _bind(client, database, csrf, profile_id)
    private = _bind(client, database, csrf, profile_id, visibility="private")
    usage = f"/api/v1/voice-profiles/{profile_id}/affected-agents"

    for viewer, expected, manageable in [
        ("bowen", [public, private], True),
        ("kaikai", [public], False),
        ("maya", [public], True),
    ]:
        client.cookies.clear()
        login(client, viewer)
        listed = client.get(VOICES)
        assert listed.status_code == 200, listed.text
        profile = next(row for row in listed.json() if row["id"] == profile_id)
        assert profile["owner_username"] == "bowen"
        assert profile["can_manage"] is manageable
        response = client.get(usage)
        assert response.status_code == 200, response.text
        assert sorted(response.json(), key=lambda row: row["agent_id"]) == sorted(
            expected, key=lambda row: row["agent_id"]
        )
        if viewer == "kaikai":
            assert (
                client.get(f"/api/v1/voice-profiles/{pending_id}/affected-agents").status_code
                == 404
            )
            assert (
                client.patch(
                    f"/api/v1/voice-profiles/{profile_id}",
                    headers=_headers(login(client, viewer)[1]),
                    json={"source_filename": "forbidden.wav"},
                ).status_code
                == 404
            )

    _, csrf = login(client, "maya")
    renamed = client.patch(
        f"/api/v1/voice-profiles/{profile_id}",
        headers=_headers(csrf),
        json={"source_filename": "renamed.wav"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["owner_username"] == "bowen"
    assert client.get(f"/api/v1/voice-profiles/{profile_id}").json()["owner_username"] == "bowen"

    outsiders = [
        _add_user(database, role="teacher", course_id=str(uuid4())),
        _add_user(
            database,
            role="student",
            group_id=make_foreign_group(database, COURSE_ID),
        ),
    ]
    for outsider in outsiders:
        _login_id(client, outsider)
        assert client.get(VOICES).status_code == 404
        assert client.get(usage).status_code == 404


def test_personal_voice_attribution_and_private_agent_usage(client, database):
    _, csrf = login(client, "maya")
    profile_id = str(uuid4())
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            VoiceProfile(
                id=profile_id,
                scope="personal",
                display_name="Teacher voice",
                status="ready",
                provider_key="mock",
                target_model_key="mock",
                recovery_name=f"attribution-{uuid4()}",
                consent_actor_user_id=TEACHER_ID,
                created_at=now,
                updated_at=now,
            )
        )
    agent = _bind(client, database, csrf, profile_id, personal=True, visibility="private")
    listed = client.get(f"/api/v1/courses/{COURSE_ID}/voice-profiles")
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["owner_username"] == "maya"
    usage = f"/api/v1/voice-profiles/{profile_id}/affected-agents"
    assert client.get(usage).json() == [agent]
    login(client, "bowen")
    assert client.get(usage).status_code == 404


def test_voice_without_an_owner_never_invents_a_maker(client, database):
    login(client, "bowen")
    profile_id = _voice(database, "ready")
    with database.session() as db:
        profile = db.get(VoiceProfile, profile_id)
        assert profile.consent_actor_user_id == BOWEN_ID
        profile.consent_actor_user_id = None
        assert voice_profile_dto(db, profile).owner_username is None
    assert client.get(VOICES).json() == []
    assert client.get(f"/api/v1/voice-profiles/{profile_id}/affected-agents").status_code == 404
