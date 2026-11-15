from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import AgentVersion, VoiceProfile
from app.modules.debates.playback._preparation import PlaybackPreparationMixin
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository, SqlRow
from app.modules.voices.crypto import encrypt_external_voice_id
from app.seed import BOWEN_ID
from sqlalchemy import text

from tests import test_wave2_setup as debate_fixtures
from tests.conftest import login
from tests.test_wave2_setup import (
    COURSE_ID,
    GROUP_DEMO_ID,
    _insert_published_agent,
    headers,
)

debate_app = debate_fixtures.debate_app


def test_real_speech_without_fallback_does_not_block_debate_creation(debate_app: Any) -> None:
    app, database, client = debate_app
    app.state.settings.tts_provider = "dashscope"
    app.state.settings.voice_provider = "dashscope"
    first, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="First")
    second, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="Second")
    _, csrf = login(client)
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "speech-no-fallback-draft"}),
        json={
            "topic": "How should people learn together?",
            "participants": [
                {"agent_id": first, "stance_mode": "open"},
                {"agent_id": second, "stance_mode": "open"},
            ],
            "round_count": 4,
            "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
            "round_unit_caps": [200, 200, 200, 200],
        },
    )
    assert response.status_code == 201, response.text
    assert all(p["voice_fallback_active"] for p in response.json()["participants"])
    assert all(p["effective_voice_profile_id"] is None for p in response.json()["participants"])


def test_real_voice_resolution_decrypts_custom_and_falls_back_without_fake_audio(
    debate_app: Any,
) -> None:
    app, database, _ = debate_app
    settings = app.state.settings.model_copy(update={"tts_provider": "dashscope"})
    custom_id, fallback_id = str(uuid4()), str(uuid4())
    settings.fallback_voice_profile_id = fallback_id
    with database.session() as db:
        for profile_id, scope, group_id, external in (
            (custom_id, "group", GROUP_DEMO_ID, "fixture-custom-external"),
            (fallback_id, "system", None, "fixture-fallback-external"),
        ):
            db.add(
                VoiceProfile(
                    id=profile_id,
                    scope=scope,
                    group_id=group_id,
                    display_name="Test voice",
                    status="ready",
                    provider_key="dashscope",
                    target_model_key="fixture-model",
                    external_id_encrypted=encrypt_external_voice_id(
                        external,
                        settings.secret_bytes,
                        profile_id=profile_id,
                        scope=scope,
                        group_id=group_id,
                        provider_key="dashscope",
                        target_model_key="fixture-model",
                    ),
                    recovery_name=f"test-{profile_id}",
                    provenance_json="{}",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
    participant = SqlRow(
        {"effective_voice_kind": "platform_profile", "effective_voice_profile_id": custom_id}
    )
    # Owner decision (2026-10-24): a Debate speaks only from its own voice
    # snapshot. Without one, the live Voice row is not read; the configured
    # system fallback speaks, and without that the turn is text only.
    with database.session() as db:
        fallback = SqlPlaybackRepository.resolve_effective_voice(db, participant, settings)
        assert (fallback.profile_id, fallback.voice_token) == (
            fallback_id,
            "fixture-fallback-external",
        )
        db.get(VoiceProfile, fallback_id).status = "deleted"
    with database.session() as db:
        missing = SqlPlaybackRepository.resolve_effective_voice(db, participant, settings)
        assert missing.profile_id is None
        assert missing.voice_token == ""
        assert participant.effective_voice_profile_id == custom_id


def test_debate_setup_drops_a_clone_whose_owner_left_the_group(debate_app: Any) -> None:
    """#141: Debate setup freezes a group clone only while its owner is a groupmate."""

    app, database, client = debate_app
    settings = app.state.settings
    settings.fallback_voice_profile_id = None
    voice_id = str(uuid4())
    first, first_version, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="A")
    second, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="B")
    with database.session() as db:
        db.add(
            VoiceProfile(
                id=voice_id,
                scope="group",
                group_id=GROUP_DEMO_ID,
                display_name="Bowen's clone",
                status="ready",
                provider_key="mock",
                target_model_key="mock-voice-v1",
                external_id_encrypted=encrypt_external_voice_id(
                    "bowen-external",
                    settings.secret_bytes,
                    profile_id=voice_id,
                    scope="group",
                    group_id=GROUP_DEMO_ID,
                    provider_key="mock",
                    target_model_key="mock-voice-v1",
                ),
                recovery_name=f"test-{voice_id}",
                provenance_json="{}",
                consent_actor_user_id=BOWEN_ID,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        version = db.get(AgentVersion, first_version)
        assert version is not None
        version.voice_profile_id = voice_id
    _, csrf = login(client)

    def first_voice(key: str) -> dict[str, Any]:
        response = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=headers(csrf, **{"Idempotency-Key": key}),
            json={
                "topic": "How should people learn together?",
                "participants": [
                    {"agent_id": first, "stance_mode": "open"},
                    {"agent_id": second, "stance_mode": "open"},
                ],
                "round_count": 4,
                "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
                "round_unit_caps": [200, 200, 200, 200],
            },
        )
        assert response.status_code == 201, response.text
        participant: dict[str, Any] = response.json()["participants"][0]
        return participant

    before = first_voice("left-owner-debate-before")
    assert before["effective_voice_profile_id"] == voice_id
    assert before["voice_fallback_active"] is False

    with database.session() as db:
        db.execute(
            text("DELETE FROM group_members WHERE group_id = :g AND user_id = :u"),
            {"g": GROUP_DEMO_ID, "u": BOWEN_ID},
        )
    after = first_voice("left-owner-debate-after")
    assert after["effective_voice_profile_id"] != voice_id
    assert after["voice_fallback_active"] is True


def test_playback_provider_gate_allows_configured_real_speech_only() -> None:
    service = SimpleNamespace(
        settings=SimpleNamespace(
            embedding_provider="dashscope", tts_provider="dashscope", voice_provider="dashscope"
        ),
        tts_provider=SimpleNamespace(key="dashscope"),
    )
    PlaybackPreparationMixin._provider_allowed(service)
    service.settings.voice_provider = "unsupported"
    with pytest.raises(PlatformError):
        PlaybackPreparationMixin._provider_allowed(service)
