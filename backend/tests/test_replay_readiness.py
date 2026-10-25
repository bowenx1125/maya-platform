"""Replay readiness through the SQL repository and service boundary."""

from __future__ import annotations

import hashlib
import io
import json
import wave
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import Agent, AgentVersion, StoredFile
from app.modules.avatars import DEFAULT_AVATAR_CONFIG
from app.modules.debates.cleanup import delete_voice
from app.modules.debates.models import Debate, DebateParticipant, DebatePlaybackState, DebateTurn
from app.modules.debates.playback.audio import AudioStore
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository
from app.modules.debates.playback.task_manager import TaskManager
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.test_wave2_playback import (
    COURSE_ID,
    GROUP_DEMO_ID,
    _insert_published_agent,
    _valid_speech,
)

TEACHER_ID = "08b9de2d-bb75-5c71-a64b-231b48f9eb25"


def _wav_bytes() -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8_000)
        wav.writeframes(b"\x00\x00" * 80)
    return stream.getvalue()


def _seed_segments_debate(database: Any, agent_ids: tuple[str, str]) -> tuple[str, list[str]]:
    now = datetime.now(UTC)
    debate_id = str(uuid4())
    participant_ids = [str(uuid4()) for _ in agent_ids]
    turn_ids = [str(uuid4()) for _ in range(4)]
    with database.session() as db:
        db.add(
            Debate(
                id=debate_id,
                course_id=COURSE_ID,
                topic="A saved segments replay",
                rule_set_id="ordered_multi_expert_mutual_learning_v1",
                rule_snapshot_json=(
                    '{"round_count":2,"turn_protocol":"segments_v2",'
                    '"retrieval_policy_id":"mock_lexical_anchor_v2"}'
                ),
                output_language="en",
                status="debate_finished",
                revision=0,
                last_sequence=0,
                cancellation_generation=0,
                created_by=TEACHER_ID,
                created_at=now,
                updated_at=now,
                finished_at=now,
            )
        )
        db.flush()
        participants: list[DebateParticipant] = []
        for order_index, (agent_id, participant_id) in enumerate(
            zip(agent_ids, participant_ids, strict=True)
        ):
            agent = db.get(Agent, agent_id)
            version = db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent_id))
            assert agent is not None and version is not None and version.knowledge_snapshot_id
            participant = DebateParticipant(
                id=participant_id,
                debate_id=debate_id,
                course_id=COURSE_ID,
                group_id=GROUP_DEMO_ID,
                agent_id=agent_id,
                agent_version_id=str(version.id),
                knowledge_snapshot_id=str(version.knowledge_snapshot_id),
                slot=chr(65 + order_index),
                order_index=order_index,
                agent_name=str(agent.name),
                version_label="V1.0",
                avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
                requested_voice_profile_id=None,
                effective_voice_kind="mock_sentinel",
                effective_voice_profile_id=None,
                voice_fallback_active=True,
                stance_mode="open",
                initial_stance=None,
                current_stance=None,
                teacher_note="",
                initial_position_summary="",
                current_position_summary="",
                created_at=now,
                updated_at=now,
            )
            participants.append(participant)
            db.add(participant)
        db.flush()
        speech = _valid_speech()
        structured = json.dumps(
            {
                "schema_version": "segment_turn_v2",
                "segments": [{"text": speech, "source_ids": [], "reply_to": None}],
            },
            separators=(",", ":"),
        )
        store = AudioStore(database.data_root or Path("/tmp"))
        for index, turn_id in enumerate(turn_ids):
            participant = participants[index % len(participants)]
            raw = _wav_bytes()
            metadata = store.store_bytes(
                course_id=COURSE_ID,
                debate_id=debate_id,
                turn_id=turn_id,
                raw=raw,
            )
            file_id = str(uuid4())
            db.add(
                StoredFile(
                    id=file_id,
                    kind="debate_audio",
                    relative_path=metadata.relative_path,
                    sha256=hashlib.sha256(raw).hexdigest(),
                    size_bytes=len(raw),
                    state="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            predecessor_ids = turn_ids[: index - (index % 2)] if index >= 2 else []
            db.add(
                DebateTurn(
                    id=turn_id,
                    debate_id=debate_id,
                    participant_id=participant.id,
                    knowledge_snapshot_id=participant.knowledge_snapshot_id,
                    round_no=1 if index < 2 else 2,
                    turn_index=index,
                    generation_status="final_ready",
                    publication_status="public",
                    preparation_stage="ready",
                    speech=speech,
                    structured_json=structured,
                    predecessor_turn_ids_json=json.dumps(predecessor_ids, separators=(",", ":")),
                    transcript_hash="a" * 64,
                    cutoff_turn_index=max(
                        (int(item_index) for item_index in range(index - (index % 2))), default=-1
                    )
                    if index >= 2
                    else -1,
                    retrieval_status="no_match",
                    grounding_mode="general_reasoning",
                    retrieval_receipts_json="[]",
                    evidence_trace_json="[]",
                    word_count=80,
                    attempt=1,
                    audio_file_id=file_id,
                    audio_duration_ms=metadata.duration_ms,
                    actual_tts_voice_kind="mock_sentinel",
                    actual_tts_voice_profile_id=None,
                    safe_error_code=None,
                    created_at=now,
                    updated_at=now,
                    public_at=now,
                )
            )
        db.add(
            DebatePlaybackState(
                id=str(uuid4()),
                debate_id=debate_id,
                status="completed",
                mode="live",
                current_turn_id=None,
                cursor_ms=0,
                control_version=7,
                controller_epoch=None,
                controller_owner_connection=None,
                pending_action=None,
                pending_ticket_hash=None,
                pending_media_command_id=None,
                audio_duration_ms=0,
                server_started_at=None,
                replay_scope=None,
                replay_index=None,
                replay_turn_ids_json="[]",
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
    return debate_id, turn_ids


@pytest.mark.parametrize("tamper", ["valid", "missing", "corrupt"])
def test_rest_replay_readiness_matches_retained_audio_bytes(
    app_factory: Any,
    tamper: str,
) -> None:
    app, database, settings = app_factory()
    with TestClient(app) as client:
        agent_ids = tuple(
            _insert_published_agent(
                database,
                group_id=GROUP_DEMO_ID,
                name=f"REST Replay Agent {index}",
                evidence=f"REST replay evidence {index}.",
            )
            for index in range(2)
        )
        debate_id, turn_ids = _seed_segments_debate(database, agent_ids)
        with database.session() as db:
            playback = db.scalar(
                select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
            )
            successor = db.get(DebateTurn, turn_ids[1])
            assert playback is not None and successor is not None and successor.audio_file_id
            playback.status = "waiting_next"
            playback.mode = "replay"
            playback.current_turn_id = turn_ids[0]
            playback.replay_scope = "all"
            playback.replay_index = 0
            playback.replay_turn_ids_json = json.dumps(turn_ids, separators=(",", ":"))
            playback.control_version = 7
            stored = db.get(StoredFile, successor.audio_file_id)
            assert stored is not None
            audio_path = settings.resolved_data_root / stored.relative_path
            if tamper == "missing":
                audio_path.unlink()
            elif tamper == "corrupt":
                audio_path.write_bytes(b"x" * stored.size_bytes)

        _session, _csrf = login(client)
        response = client.get(f"/api/v1/debates/{debate_id}")
        assert response.status_code == 200, response.text
        assert response.json()["playback"]["next_turn_ready"] == (tamper == "valid")


@pytest.mark.asyncio
async def test_segments_replay_next_is_ready_from_sql_detail_and_ends_cleanly(
    app_factory: Any,
) -> None:
    app, database, settings = app_factory()
    with TestClient(app):
        agent_ids = tuple(
            _insert_published_agent(
                database,
                group_id=GROUP_DEMO_ID,
                name=f"Replay Agent {index}",
                evidence=f"Replay evidence {index}.",
            )
            for index in range(2)
        )
        debate_id, turn_ids = _seed_segments_debate(database, agent_ids)

    tasks = TaskManager()
    prepare_calls = 0
    tts_calls = 0

    def forbidden_preparer(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal prepare_calls
        prepare_calls += 1
        raise AssertionError("Replay must not prepare a turn")

    class ForbiddenTTS:
        def synthesize(self, *_args: Any, **_kwargs: Any) -> Any:
            nonlocal tts_calls
            tts_calls += 1
            raise AssertionError("Replay must not call TTS")

    tts = ForbiddenTTS()
    service = PlaybackService(
        SqlPlaybackRepository(session_factory=database.session_factory),
        audio_store=AudioStore(settings.resolved_data_root, tts_provider=tts),
        task_manager=tasks,
        session_factory=database.session_factory,
        settings=settings,
        tts_provider=tts,
        turn_preparer=forbidden_preparer,
    )
    with database.session() as db:
        db.info["maya_settings"] = settings
        replay = await service.replay_all(db, debate_id, expected_control_version=7)
        acquired = await service.controller_acquire(
            db,
            debate_id,
            command_id=str(uuid4()),
            expected_control_version=replay.control_version,
            session_hash="replay-session",
            connection_id="replay-tab",
        )
        await service.media_prepare(
            db,
            debate_id,
            command_id=str(uuid4()),
            expected_control_version=acquired.control_version,
            epoch=str(acquired.controller_epoch),
            session_hash="replay-session",
            turn_id=turn_ids[0],
            action="replay",
        )
        started = await service.started_ack(
            db,
            debate_id,
            command_id=str(uuid4()),
            expected_control_version=acquired.control_version,
            epoch=str(acquired.controller_epoch),
            session_hash="replay-session",
            turn_id=turn_ids[0],
            action="replay",
        )
        waiting = await service.ended_ack(
            db,
            debate_id,
            command_id=str(uuid4()),
            expected_control_version=started.control_version,
            epoch=str(acquired.controller_epoch),
            session_hash="replay-session",
            turn_id=turn_ids[0],
        )
        assert waiting.status == "waiting_next"
        assert waiting.mode == "replay"
        assert waiting.next_turn_ready is True
        teacher_context = SimpleNamespace(user=SimpleNamespace(id=TEACHER_ID))
        # The public detail is the path the teacher page polls for its button.
        from app.modules.debates.setup.service import get_debate

        detail = get_debate(db, actor_user_id=TEACHER_ID, debate_id=debate_id)
        assert detail.playback.next_turn_ready is True
        advanced = await service.next(
            db,
            debate_id,
            expected_control_version=waiting.control_version,
            expected_current_turn_id=turn_ids[0],
            context=teacher_context,
        )
        assert str(advanced.current_turn_id) == turn_ids[1]
        assert advanced.status == "ready"

        for index in range(1, len(turn_ids)):
            await service.media_prepare(
                db,
                debate_id,
                command_id=str(uuid4()),
                expected_control_version=advanced.control_version,
                epoch=str(acquired.controller_epoch),
                session_hash="replay-session",
                turn_id=turn_ids[index],
                action="replay",
            )
            started = await service.started_ack(
                db,
                debate_id,
                command_id=str(uuid4()),
                expected_control_version=advanced.control_version,
                epoch=str(acquired.controller_epoch),
                session_hash="replay-session",
                turn_id=turn_ids[index],
                action="replay",
            )
            ended = await service.ended_ack(
                db,
                debate_id,
                command_id=str(uuid4()),
                expected_control_version=started.control_version,
                epoch=str(acquired.controller_epoch),
                session_hash="replay-session",
                turn_id=turn_ids[index],
            )
            if index < len(turn_ids) - 1:
                assert ended.status == "waiting_next"
                assert ended.mode == "replay"
                assert ended.next_turn_ready is True
                detail = get_debate(db, actor_user_id=TEACHER_ID, debate_id=debate_id)
                assert detail.playback.next_turn_ready is True
                advanced = await service.next(
                    db,
                    debate_id,
                    expected_control_version=ended.control_version,
                    expected_current_turn_id=turn_ids[index],
                    context=teacher_context,
                )
                assert advanced.status == "ready"
                assert str(advanced.current_turn_id) == turn_ids[index + 1]
            else:
                assert ended.status == "completed"
                assert ended.mode == "live"
                assert ended.current_turn_id is None
                assert ended.next_turn_ready is False

    with database.session() as db:
        final_state = db.scalar(
            select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
        )
        debate = db.get(Debate, debate_id)
        assert final_state is not None and debate is not None
        assert final_state.status == "completed"
        assert final_state.mode == "live"
        assert final_state.current_turn_id is None
        assert final_state.replay_scope is None
        assert final_state.replay_index is None
        assert final_state.replay_turn_ids_json == "[]"
        assert debate.status == "debate_finished"
    assert prepare_calls == 0
    assert tts_calls == 0
    assert tasks.active_keys == ()
    await tasks.close()


@pytest.mark.asyncio
async def test_segments_replay_rejects_missing_successor_audio_while_waiting(
    app_factory: Any,
) -> None:
    app, database, settings = app_factory()
    with TestClient(app):
        agent_ids = tuple(
            _insert_published_agent(
                database,
                group_id=GROUP_DEMO_ID,
                name=f"Missing Audio Agent {index}",
                evidence=f"Missing audio evidence {index}.",
            )
            for index in range(2)
        )
        debate_id, turn_ids = _seed_segments_debate(database, agent_ids)

    tasks = TaskManager()
    service = PlaybackService(
        SqlPlaybackRepository(session_factory=database.session_factory),
        audio_store=AudioStore(settings.resolved_data_root),
        task_manager=tasks,
        session_factory=database.session_factory,
        settings=settings,
    )
    teacher_context = SimpleNamespace(user=SimpleNamespace(id=TEACHER_ID))
    with database.session() as db:
        replay = await service.replay_all(db, debate_id, expected_control_version=7)
        controller = await service.controller_acquire(
            db,
            debate_id,
            command_id=str(uuid4()),
            expected_control_version=replay.control_version,
            session_hash="missing-audio-session",
            connection_id="missing-audio-tab",
        )
        await service.media_prepare(
            db,
            debate_id,
            command_id=str(uuid4()),
            expected_control_version=controller.control_version,
            epoch=str(controller.controller_epoch),
            session_hash="missing-audio-session",
            turn_id=turn_ids[0],
            action="replay",
        )
        started = await service.started_ack(
            db,
            debate_id,
            command_id=str(uuid4()),
            expected_control_version=controller.control_version,
            epoch=str(controller.controller_epoch),
            session_hash="missing-audio-session",
            turn_id=turn_ids[0],
            action="replay",
        )
        waiting = await service.ended_ack(
            db,
            debate_id,
            command_id=str(uuid4()),
            expected_control_version=started.control_version,
            epoch=str(controller.controller_epoch),
            session_hash="missing-audio-session",
            turn_id=turn_ids[0],
        )
        assert waiting.status == "waiting_next"
        successor = db.get(DebateTurn, turn_ids[1])
        assert successor is not None and successor.audio_file_id is not None
        audio_file = db.get(StoredFile, successor.audio_file_id)
        successor.audio_file_id = None
        successor.audio_duration_ms = None
        db.flush()
        if audio_file is not None:
            db.delete(audio_file)
        with pytest.raises(PlatformError) as raised:
            await service.next(
                db,
                debate_id,
                expected_control_version=waiting.control_version,
                expected_current_turn_id=turn_ids[0],
                context=teacher_context,
            )
        assert raised.value.code == "next_not_ready"
        state = db.scalar(
            select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
        )
        assert state is not None
        assert state.status == "waiting_next"
        assert state.mode == "replay"
        assert state.current_turn_id == turn_ids[0]
        assert state.replay_index == 0
    await tasks.close()


@pytest.mark.asyncio
async def test_delete_voice_parks_replay_and_clears_retained_audio(app_factory: Any) -> None:
    app, database, settings = app_factory()
    with TestClient(app):
        agent_ids = tuple(
            _insert_published_agent(
                database,
                group_id=GROUP_DEMO_ID,
                name=f"Cleanup Replay Agent {index}",
                evidence=f"Cleanup replay evidence {index}.",
            )
            for index in range(2)
        )
        debate_id, turn_ids = _seed_segments_debate(database, agent_ids)

    tasks = TaskManager()
    service = PlaybackService(
        SqlPlaybackRepository(session_factory=database.session_factory),
        audio_store=AudioStore(settings.resolved_data_root),
        task_manager=tasks,
        session_factory=database.session_factory,
        settings=settings,
    )
    with database.session() as db:
        replay = await service.replay_all(db, debate_id, expected_control_version=7)
        controller = await service.controller_acquire(
            db,
            debate_id,
            command_id=str(uuid4()),
            expected_control_version=replay.control_version,
            session_hash="cleanup-replay-session",
            connection_id="cleanup-replay-tab",
        )
        await service.media_prepare(
            db,
            debate_id,
            command_id=str(uuid4()),
            expected_control_version=controller.control_version,
            epoch=str(controller.controller_epoch),
            session_hash="cleanup-replay-session",
            turn_id=turn_ids[0],
            action="replay",
        )
        started = await service.started_ack(
            db,
            debate_id,
            command_id=str(uuid4()),
            expected_control_version=controller.control_version,
            epoch=str(controller.controller_epoch),
            session_hash="cleanup-replay-session",
            turn_id=turn_ids[0],
            action="replay",
        )
        waiting = await service.ended_ack(
            db,
            debate_id,
            command_id=str(uuid4()),
            expected_control_version=started.control_version,
            epoch=str(controller.controller_epoch),
            session_hash="cleanup-replay-session",
            turn_id=turn_ids[0],
        )
        assert waiting.status == "waiting_next"
        turns_before_cleanup = list(
            db.scalars(select(DebateTurn).where(DebateTurn.debate_id == debate_id)).all()
        )
        audio_file_ids = [
            str(turn.audio_file_id) for turn in turns_before_cleanup if turn.audio_file_id
        ]
        audio_paths = [
            settings.resolved_data_root / str(stored.relative_path)
            for file_id in audio_file_ids
            if (stored := db.get(StoredFile, file_id)) is not None
        ]
        result = await delete_voice(
            db,
            actor_user_id=TEACHER_ID,
            debate_id=debate_id,
            expected_revision=0,
            expected_control_version=waiting.control_version,
            data_root=settings.resolved_data_root,
            playback_service=service,
            task_manager=tasks,
            ticket_store=service.ticket_store,
        )
        assert result.revision == 1
        assert result.control_version == waiting.control_version + 1
        assert result.cleared_turn_count == 4
        assert len(result.regenerable_turn_ids) == 4
        assert result.deleted_file_count == 4
        assert result.missing_file_count == 0
        assert result.pending_file_count == 0
        assert result.runtime_cancelled is True

    with database.session() as db:
        state = db.scalar(
            select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
        )
        turns = list(db.scalars(select(DebateTurn).where(DebateTurn.debate_id == debate_id)).all())
        assert state is not None
        assert state.status == "paused"
        assert state.mode == "replay"
        assert all(turn.audio_file_id is None for turn in turns)
        assert all(db.get(StoredFile, file_id) is None for file_id in audio_file_ids)
        assert all(not path.exists() for path in audio_paths)
        with pytest.raises(PlatformError) as raised:
            await service.replay_all(
                db,
                debate_id,
                expected_control_version=state.control_version,
            )
        assert raised.value.code == "invalid_state"
    await tasks.close()
