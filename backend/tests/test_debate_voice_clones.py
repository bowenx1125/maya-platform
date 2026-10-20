"""Debates speak with their own independent voice clone (2026-10-20)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.models import AgentVersion, StoredFile, VoiceProfile
from app.modules.debates.models import DebateParticipant, DebateVoiceClone
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository, SqlRow
from app.modules.debates.voice_clones import sweep_debate_voice_clones
from app.modules.knowledge.files import write_atomic
from app.providers.voice import VoiceEnrollmentResult
from app.seed import BOWEN_ID
from sqlalchemy import select

from tests import test_wave2_setup as debate_fixtures
from tests.conftest import login
from tests.test_wave2_setup import COURSE_ID, GROUP_DEMO_ID, _insert_published_agent, headers

debate_app = debate_fixtures.debate_app


@dataclass
class FakeCloneProvider:
    key: str = "mock"
    target_model_key: str = "mock-voice-v1"
    fail_first: int = 0
    enrolled: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    def enroll(self, audio_data_uri: str, **kwargs: Any) -> VoiceEnrollmentResult:
        assert audio_data_uri.startswith("data:audio/wav;base64,")
        if self.fail_first > 0:
            self.fail_first -= 1
            raise RuntimeError("provider busy")
        external = f"clone-{kwargs['recovery_name']}"
        self.enrolled.append(external)
        return VoiceEnrollmentResult(external_voice_id=external)

    def exists(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    def delete(self, external_voice_id: str, *, target_model_key: str) -> None:
        self.deleted.append(external_voice_id)


def _voice_with_sample(database: Any, settings: Any) -> str:
    voice_id, file_id = str(uuid4()), str(uuid4())
    relative = f"voice-samples/{voice_id}.wav"
    digest, size = write_atomic(settings.resolved_data_root, relative, b"RIFF-sample")
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            StoredFile(
                id=file_id,
                kind="voice_sample",
                relative_path=relative,
                sha256=digest,
                size_bytes=size,
                state="active",
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(
            VoiceProfile(
                id=voice_id,
                scope="group",
                group_id=GROUP_DEMO_ID,
                display_name="Bowen",
                status="ready",
                provider_key="mock",
                target_model_key="mock-voice-v1",
                recovery_name=f"t{voice_id[:8]}",
                provenance_json="{}",
                consent_actor_user_id=BOWEN_ID,
                sample_file_id=file_id,
                sample_language="en",
                created_at=now,
                updated_at=now,
            )
        )
    return voice_id


def _create_voiced_debate(database: Any, client: Any, voice_id: str) -> str:
    first, first_version, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="A")
    second, _, _ = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="B")
    with database.session() as db:
        version = db.get(AgentVersion, first_version)
        assert version is not None
        version.voice_profile_id = voice_id
    _, csrf = login(client)
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": f"voice-clone-{uuid4()}"}),
        json={
            "topic": "How should people learn together?",
            "participants": [
                {"agent_id": first, "stance_mode": "open"},
                {"agent_id": second, "stance_mode": "open"},
            ],
            "round_count": 4,
            "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["participants"][0]["effective_voice_profile_id"] == voice_id
    return str(response.json()["id"])


def test_debate_gets_its_own_clone_that_survives_voice_delete(debate_app: Any) -> None:
    app, database, client = debate_app
    settings = app.state.settings
    settings.fallback_voice_profile_id = None
    voice_id = _voice_with_sample(database, settings)
    debate_id = _create_voiced_debate(database, client, voice_id)
    provider = FakeCloneProvider(fail_first=1)
    with database.session() as db:
        clone = db.scalars(
            select(DebateVoiceClone).where(DebateVoiceClone.debate_id == debate_id)
        ).one()
        assert (clone.status, clone.source_voice_profile_id) == ("pending", voice_id)
        # A provider failure retries on the next sweep; creation never failed.
        assert (
            sweep_debate_voice_clones(
                db, data_root=settings.resolved_data_root, settings=settings, provider=provider
            )["pending"]
            == 1
        )
        sweep_debate_voice_clones(
            db, data_root=settings.resolved_data_root, settings=settings, provider=provider
        )
        db.refresh(clone)
        assert clone.status == "ready" and clone.attempts == 2
        participant = db.scalars(
            select(DebateParticipant).where(
                DebateParticipant.debate_id == debate_id, DebateParticipant.order_index == 0
            )
        ).one()
        snapshot = json.loads(participant.voice_snapshot_json or "{}")
        assert snapshot["voice_profile_id"] == voice_id
        # Hard-delete the platform Voice: the Debate's own row keeps going.
        db.delete(db.get(VoiceProfile, voice_id))
        db.commit()
        db.refresh(participant)
        assert participant.effective_voice_profile_id is None
        row = SqlRow(
            {
                "debate_id": debate_id,
                "effective_voice_kind": "platform_profile",
                "effective_voice_profile_id": None,
                "voice_snapshot_json": participant.voice_snapshot_json,
            }
        )
        real = settings.model_copy(update={"tts_provider": "dashscope"})
        voice = SqlPlaybackRepository.resolve_effective_voice(db, row, real)
        assert voice.voice_token == provider.enrolled[0]
        assert voice.kind == "platform_profile" and voice.profile_id is None
    assert provider.deleted == []


def test_clone_is_deleted_only_with_its_debate(debate_app: Any) -> None:
    app, database, client = debate_app
    settings = app.state.settings
    settings.fallback_voice_profile_id = None
    voice_id = _voice_with_sample(database, settings)
    debate_id = _create_voiced_debate(database, client, voice_id)
    provider = FakeCloneProvider()
    with database.session() as db:
        kwargs: dict[str, Any] = {
            "data_root": settings.resolved_data_root,
            "settings": settings,
            "provider": provider,
        }
        sweep_debate_voice_clones(db, **kwargs)
        sweep_debate_voice_clones(db, **kwargs)
        assert provider.deleted == []
        clone = db.scalars(
            select(DebateVoiceClone).where(DebateVoiceClone.debate_id == debate_id)
        ).one()
        clone.debate_id = str(uuid4())  # as if the Debate row were deleted
        db.commit()
        assert sweep_debate_voice_clones(db, **kwargs)["deleted"] == 1
        assert provider.deleted == provider.enrolled
        assert db.scalars(select(DebateVoiceClone)).all() == []


def test_voice_without_sample_is_counted_not_enrolled(debate_app: Any) -> None:
    app, database, client = debate_app
    settings = app.state.settings
    settings.fallback_voice_profile_id = None
    voice_id = _voice_with_sample(database, settings)
    with database.session() as db:
        db.get(VoiceProfile, voice_id).sample_file_id = None
    debate_id = _create_voiced_debate(database, client, voice_id)
    provider = FakeCloneProvider()
    with database.session() as db:
        sweep_debate_voice_clones(
            db, data_root=settings.resolved_data_root, settings=settings, provider=provider
        )
        clone = db.scalars(
            select(DebateVoiceClone).where(DebateVoiceClone.debate_id == debate_id)
        ).one()
        assert clone.status == "no_sample"
    assert provider.enrolled == []
