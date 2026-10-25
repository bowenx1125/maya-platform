"""Focused PW3-D SQL fences.

These probes exercise the fresh-writer transactions directly.  They keep the
cross-process guarantees independent from the HTTP/WebSocket composition and
never call a provider.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import Job, StoredFile
from app.modules.debates.models import Debate, DebateParticipant, DebatePlaybackState, DebateTurn
from app.modules.debates.playback.audio import AudioStore
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository
from app.modules.debates.playback.task_manager import TaskManager
from app.modules.interactions.service import InteractionService
from app.modules.reports.service import get_current_report
from app.providers.tts import MockTTSProvider
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import login
from tests.test_wave2_playback import (
    COURSE_ID,
    GROUP_DEMO_ID,
    _insert_published_agent,
    _insert_sql_retained_debate,
    _valid_speech,
    _wav_bytes,
)

TEACHER_ID = "08b9de2d-bb75-5c71-a64b-231b48f9eb25"


def _seed_one_turn(app_factory: Any) -> tuple[Database, Any, str, str]:
    app, database, settings = app_factory()
    with TestClient(app):
        agent_id = _insert_published_agent(
            database,
            group_id=GROUP_DEMO_ID,
            name="PW3 SQL Bowen",
            evidence="Retained classroom evidence with accountable review and user choice.",
        )
        debate_id, turn_id, _file_id, _relative_path = _insert_sql_retained_debate(
            database,
            agent_id=agent_id,
        )
    return database, settings, debate_id, turn_id


def test_transcript_route_rejects_early_finished_incomplete_plan(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        agent_id = _insert_published_agent(
            database,
            group_id=GROUP_DEMO_ID,
            name="PW3 transcript partial",
            evidence="A retained classroom transcript fixture.",
        )
        debate_id, _turn_id, _file_id, _path = _insert_sql_retained_debate(
            database,
            agent_id=agent_id,
        )
        login(client)
        response = client.get(f"/api/v1/debates/{debate_id}/transcript")
        downstream = [
            client.get(f"/api/v1/debates/{debate_id}/interaction"),
            client.get(f"/api/v1/debates/{debate_id}/report"),
        ]

    assert response.status_code == 404
    assert [item.status_code for item in downstream] == [404, 404]


def _add_live_successor(database: Database, debate_id: str, first_turn_id: str) -> str:
    now = datetime.now(UTC)
    successor_id, file_id = str(uuid4()), str(uuid4())
    with database.session() as db:
        debate = db.get(Debate, debate_id)
        first = db.get(DebateTurn, first_turn_id)
        assert debate is not None and first is not None
        participant = db.get(DebateParticipant, first.participant_id)
        assert participant is not None
        store = AudioStore(database.data_root or Path("/tmp"))
        metadata = store.store_bytes(
            course_id=COURSE_ID,
            debate_id=debate_id,
            turn_id=successor_id,
            raw=_wav_bytes(),
        )
        db.add(
            StoredFile(
                id=file_id,
                kind="debate_audio",
                relative_path=metadata.relative_path,
                sha256=metadata.sha256,
                size_bytes=metadata.size_bytes,
                state="active",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            DebateTurn(
                id=successor_id,
                debate_id=debate_id,
                participant_id=participant.id,
                knowledge_snapshot_id=participant.knowledge_snapshot_id,
                round_no=1,
                turn_index=1,
                generation_status="final_ready",
                publication_status="unpublished",
                preparation_stage="ready",
                speech=_valid_speech(),
                structured_json='{"position_summary":"A successor position."}',
                predecessor_turn_ids_json=json.dumps([first_turn_id], separators=(",", ":")),
                transcript_hash="b" * 64,
                cutoff_turn_index=0,
                retrieval_status="no_match",
                grounding_mode="general_reasoning",
                retrieval_receipts_json="[]",
                word_count=80,
                attempt=1,
                audio_file_id=file_id,
                audio_duration_ms=metadata.duration_ms,
                actual_tts_voice_kind="mock_sentinel",
                actual_tts_voice_profile_id=None,
                safe_error_code=None,
                created_at=now,
                updated_at=now,
                public_at=None,
            )
        )
        db.flush()
        db.add(
            Job(
                id=str(uuid4()),
                document_id=None,
                debate_id=debate_id,
                turn_id=successor_id,
                idempotency_key=f"{debate_id}:{successor_id}",
                claim_token=str(uuid4()),
                cancellation_generation=0,
                operation="debate_turn_prepare",
                state="completed",
                safe_error_code=None,
                attempt=1,
                created_at=now,
                updated_at=now,
            )
        )
        debate.status = "running"
        playback = db.scalar(
            select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
        )
        assert playback is not None
        playback.status = "waiting_next"
        playback.mode = "live"
        playback.current_turn_id = first_turn_id
        playback.control_version = 8
        playback.controller_epoch = None
        playback.controller_owner_connection = None
        playback.replay_scope = None
        playback.replay_index = None
        playback.replay_turn_ids_json = "[]"
        playback.pending_action = None
        playback.pending_ticket_hash = None
        playback.pending_media_command_id = None
        playback.audio_duration_ms = 0
    return successor_id


def _set_live_playing(database: Database, debate_id: str, turn_id: str) -> None:
    with database.session() as db:
        db.execute(
            text("UPDATE debates SET status='running', finished_at=NULL WHERE id=:debate_id"),
            {"debate_id": debate_id},
        )
        db.execute(
            text(
                "UPDATE playback_states SET status='playing', mode='live', "
                "current_turn_id=:turn_id, cursor_ms=321, control_version=7, "
                "controller_epoch=NULL, controller_owner_connection=NULL, "
                "pending_action=NULL, pending_ticket_hash=NULL, "
                "pending_media_command_id=NULL, audio_duration_ms=0 "
                "WHERE debate_id=:debate_id"
            ),
            {"debate_id": debate_id, "turn_id": turn_id},
        )


def _set_live_waiting(database: Database, debate_id: str, turn_id: str) -> None:
    with database.session() as db:
        db.execute(
            text("UPDATE debates SET status='running', finished_at=NULL WHERE id=:debate_id"),
            {"debate_id": debate_id},
        )
        db.execute(
            text(
                "UPDATE playback_states SET status='waiting_next', mode='live', "
                "current_turn_id=:turn_id, cursor_ms=321, control_version=7, "
                "controller_epoch=NULL, controller_owner_connection=NULL, "
                "pending_action=NULL, pending_ticket_hash=NULL, "
                "pending_media_command_id=NULL, audio_duration_ms=0 "
                "WHERE debate_id=:debate_id"
            ),
            {"debate_id": debate_id, "turn_id": turn_id},
        )


@pytest.mark.asyncio
async def test_sql_pause_survives_restart_and_continue_revalidates_audio(
    app_factory: Any,
) -> None:
    database, settings, debate_id, turn_id = _seed_one_turn(app_factory)
    _set_live_playing(database, debate_id, turn_id)
    context = SimpleNamespace(user=SimpleNamespace(id=TEACHER_ID))
    tasks = TaskManager()
    service = PlaybackService(
        SqlPlaybackRepository(session_factory=database.session_factory),
        audio_store=AudioStore(settings.resolved_data_root),
        task_manager=tasks,
        session_factory=database.session_factory,
        settings=settings,
    )
    try:
        with database.session() as db:
            paused = await service.pause(
                db,
                debate_id,
                expected_control_version=7,
                context=context,
            )
        assert paused.status == "paused"
        assert paused.cursor_ms == 321

        restarted = PlaybackService(
            SqlPlaybackRepository(session_factory=database.session_factory),
            audio_store=AudioStore(settings.resolved_data_root),
            task_manager=tasks,
            session_factory=database.session_factory,
            settings=settings,
        )
        with database.session() as db:
            assert await restarted.recover_startup(db) == ()
            persisted = db.execute(
                text(
                    "SELECT d.status,ps.status,ps.cursor_ms,ps.control_version "
                    "FROM debates d JOIN playback_states ps ON ps.debate_id=d.id "
                    "WHERE d.id=:debate_id"
                ),
                {"debate_id": debate_id},
            ).one()
            assert persisted == ("running", "paused", 321, 9)
            resumed = await restarted.resume(
                db,
                debate_id,
                expected_control_version=9,
                context=context,
            )
        assert resumed.status == "ready"
        assert resumed.cursor_ms == 0
        assert resumed.control_version == 10
    finally:
        await tasks.close()
        database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "playback_status", ["preparing", "ready", "playing", "paused", "waiting_next"]
)
async def test_sql_full_finish_is_normal_and_retains_generated_turn(
    app_factory: Any,
    playback_status: str,
) -> None:
    database, settings, debate_id, turn_id = _seed_one_turn(app_factory)
    _set_live_waiting(database, debate_id, turn_id)
    with database.session() as db:
        db.execute(
            text("UPDATE playback_states SET status=:status WHERE debate_id=:debate_id"),
            {"status": playback_status, "debate_id": debate_id},
        )
    context = SimpleNamespace(user=SimpleNamespace(id=TEACHER_ID))
    tasks = TaskManager()
    service = PlaybackService(
        SqlPlaybackRepository(session_factory=database.session_factory),
        task_manager=tasks,
        session_factory=database.session_factory,
        settings=settings,
    )
    try:
        with database.session() as db:
            finished = await service.finish(
                db,
                debate_id,
                expected_control_version=7,
                expected_current_turn_id=turn_id,
                context=context,
            )
        assert finished.status == "completed"
        assert finished.control_version == 8
        assert finished.current_turn_id is None
        with database.session() as db:
            assert db.get(Debate, debate_id).status == "debate_finished"
            assert db.get(Debate, debate_id).cancellation_generation == 0
            assert db.get(DebateTurn, turn_id) is not None
    finally:
        await tasks.close()
        database.dispose()


def test_sql_pause_and_finish_race_has_one_fresh_writer_winner(app_factory: Any) -> None:
    database, settings, debate_id, turn_id = _seed_one_turn(app_factory)
    _set_live_playing(database, debate_id, turn_id)
    other_database = Database(database.database_url, settings.resolved_data_root)
    pause_repository = SqlPlaybackRepository(session_factory=database.session_factory)
    finish_repository = SqlPlaybackRepository(session_factory=other_database.session_factory)
    try:

        def pause() -> bool:
            return pause_repository.claim_pause_playback(
                debate_id=debate_id,
                expected_control_version=7,
                cursor_ms=321,
                teacher_user_id=TEACHER_ID,
            )

        def finish() -> dict[str, Any] | None:
            return finish_repository.claim_finish_playback(
                debate_id=debate_id,
                expected_control_version=7,
                expected_current_turn_id=turn_id,
                teacher_user_id=TEACHER_ID,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            pause_result, finish_result = tuple(pool.map(lambda call: call(), (pause, finish)))
        assert bool(pause_result) ^ bool(finish_result)
        with database.session() as db:
            row = db.execute(
                text(
                    "SELECT d.status,ps.status,ps.control_version "
                    "FROM debates d JOIN playback_states ps ON ps.debate_id=d.id "
                    "WHERE d.id=:debate_id"
                ),
                {"debate_id": debate_id},
            ).one()
            assert row[2] == 8
            assert row[:2] in {("running", "paused"), ("debate_finished", "completed")}
    finally:
        other_database.dispose()
        database.dispose()


@pytest.mark.parametrize(
    "rejection",
    [
        "completed",
        "stopped",
        "replay",
        "not_running",
        "stale_version",
        "stale_turn",
        "missing_teacher",
        "student",
        "non_member",
    ],
)
def test_sql_finish_claim_requires_known_live_state_and_fresh_teacher(
    app_factory: Any, rejection: str
) -> None:
    database, _settings, debate_id, turn_id = _seed_one_turn(app_factory)
    _set_live_playing(database, debate_id, turn_id)
    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    try:
        teacher_id: str | None = TEACHER_ID
        with database.session() as db:
            if rejection in {"completed", "stopped"}:
                db.execute(
                    text("UPDATE playback_states SET status=:status WHERE debate_id=:debate_id"),
                    {"status": rejection, "debate_id": debate_id},
                )
            elif rejection == "replay":
                db.execute(
                    text("UPDATE playback_states SET mode='replay' WHERE debate_id=:debate_id"),
                    {"debate_id": debate_id},
                )
            elif rejection == "not_running":
                db.execute(
                    text("UPDATE debates SET status='draft' WHERE id=:debate_id"),
                    {"debate_id": debate_id},
                )
            elif rejection == "student":
                teacher_id = db.scalar(
                    text(
                        "SELECT user_id FROM course_members "
                        "WHERE course_id=:course_id AND role='student' LIMIT 1"
                    ),
                    {"course_id": COURSE_ID},
                )
                assert teacher_id is not None
            elif rejection == "missing_teacher":
                teacher_id = None
            elif rejection == "non_member":
                teacher_id = str(uuid4())
            before = db.execute(
                text(
                    "SELECT d.status,d.cancellation_generation,ps.status,ps.mode,"
                    "ps.control_version,ps.current_turn_id FROM debates d "
                    "JOIN playback_states ps ON ps.debate_id=d.id WHERE d.id=:debate_id"
                ),
                {"debate_id": debate_id},
            ).one()
        # Early End is legal from every named nonterminal live state. The
        # former waiting-only check incorrectly rejected that existing rule.
        assert (
            repository.claim_finish_playback(
                debate_id=debate_id,
                expected_control_version=6 if rejection == "stale_version" else 7,
                expected_current_turn_id=str(uuid4()) if rejection == "stale_turn" else turn_id,
                teacher_user_id=teacher_id,
            )
            is None
        )
        with database.session() as db:
            row = db.execute(
                text(
                    "SELECT d.status,d.cancellation_generation,ps.status,ps.mode,"
                    "ps.control_version,ps.current_turn_id FROM debates d "
                    "JOIN playback_states ps ON ps.debate_id=d.id WHERE d.id=:debate_id"
                ),
                {"debate_id": debate_id},
            ).one()
        assert row == before
    finally:
        database.dispose()


def test_sql_playback_rejects_unknown_finish_state(app_factory: Any) -> None:
    database, _settings, debate_id, turn_id = _seed_one_turn(app_factory)
    _set_live_playing(database, debate_id, turn_id)
    try:
        with pytest.raises(IntegrityError, match="ck_playback_states_status"):
            with database.session() as db:
                db.execute(
                    text("UPDATE playback_states SET status='unknown' WHERE debate_id=:debate_id"),
                    {"debate_id": debate_id},
                )
        with database.session() as db:
            assert db.execute(
                text(
                    "SELECT status,control_version FROM playback_states WHERE debate_id=:debate_id"
                ),
                {"debate_id": debate_id},
            ).one() == ("playing", 7)
    finally:
        database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "playback_status", ["preparing", "ready", "playing", "paused", "waiting_next"]
)
@pytest.mark.parametrize("job_state", ["pending", "running"])
async def test_sql_partial_finish_retains_turns_and_blocks_every_downstream_surface(
    app_factory: Any,
    playback_status: str,
    job_state: str,
) -> None:
    database, settings, debate_id, first_turn_id = _seed_one_turn(app_factory)
    successor_id = _add_live_successor(database, debate_id, first_turn_id)
    with database.session() as db:
        db.execute(
            text("UPDATE playback_states SET status=:status WHERE debate_id=:debate_id"),
            {"status": playback_status, "debate_id": debate_id},
        )
        db.execute(
            text("UPDATE jobs SET state=:state WHERE turn_id=:turn_id"),
            {"state": job_state, "turn_id": successor_id},
        )
    context = SimpleNamespace(user=SimpleNamespace(id=TEACHER_ID))
    tasks = TaskManager()
    service = PlaybackService(
        SqlPlaybackRepository(session_factory=database.session_factory),
        task_manager=tasks,
        session_factory=database.session_factory,
        settings=settings,
    )
    try:
        with database.session() as db:
            partial = await service.finish(
                db,
                debate_id,
                expected_control_version=8,
                expected_current_turn_id=first_turn_id,
                context=context,
            )
        assert partial.status == "stopped"
        assert partial.control_version == 9
        assert partial.current_turn_id is None
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            assert debate is not None and debate.status == "debate_finished"
            assert debate.cancellation_generation == 1
            assert db.scalar(select(Job.state).where(Job.turn_id == successor_id)) == "interrupted"
            assert db.scalar(select(Job.safe_error_code).where(Job.turn_id == successor_id)) == (
                "debate_finished_partial"
            )
            assert (
                len(
                    list(
                        db.scalars(
                            select(DebateTurn).where(DebateTurn.debate_id == debate_id)
                        ).all()
                    )
                )
                == 2
            )
            with pytest.raises(PlatformError) as report_denied:
                get_current_report(db, actor_user_id=TEACHER_ID, debate_id=debate_id)
            assert report_denied.value.code == "not_found"
        with pytest.raises(PlatformError) as interaction_denied:
            InteractionService(
                session_factory=database.session_factory,
                settings=settings,
            ).get_teacher_interaction(
                actor_user_id=TEACHER_ID,
                debate_id=debate_id,
            )
        assert interaction_denied.value.code == "not_found"
        with database.session() as db:
            with pytest.raises(PlatformError) as replay_denied:
                await service.replay_all(
                    db,
                    debate_id,
                    expected_control_version=partial.control_version,
                    context=context,
                )
            assert replay_denied.value.code == "invalid_state"
    finally:
        await tasks.close()
        database.dispose()


@pytest.mark.asyncio
async def test_sql_preparing_finish_without_current_turn_revokes_pending_control(
    app_factory: Any,
) -> None:
    database, settings, debate_id, first_turn_id = _seed_one_turn(app_factory)
    _add_live_successor(database, debate_id, first_turn_id)
    with database.session() as db:
        db.execute(
            text(
                "UPDATE playback_states SET status='preparing', current_turn_id=NULL, "
                "controller_epoch=:epoch, controller_owner_connection='pending-owner', "
                "pending_action='start', pending_ticket_hash='pending-ticket', "
                "pending_media_command_id=:command_id WHERE debate_id=:debate_id"
            ),
            {"debate_id": debate_id, "epoch": str(uuid4()), "command_id": str(uuid4())},
        )
        db.execute(
            text(
                "UPDATE debate_turns SET publication_status='unpublished', public_at=NULL "
                "WHERE debate_id=:debate_id"
            ),
            {"debate_id": debate_id},
        )
    tasks = TaskManager()
    service = PlaybackService(
        SqlPlaybackRepository(session_factory=database.session_factory),
        task_manager=tasks,
        session_factory=database.session_factory,
        settings=settings,
    )
    try:
        with database.session() as db:
            result = await service.finish(
                db,
                debate_id,
                expected_control_version=8,
                context=SimpleNamespace(user=SimpleNamespace(id=TEACHER_ID)),
            )
        assert result.status == "stopped"
        assert result.control_version == 9
        with database.session() as db:
            state = db.scalar(
                select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
            )
            assert state is not None
            assert state.current_turn_id is None
            assert state.controller_epoch is None
            assert state.controller_owner_connection is None
            assert state.pending_action is None
            assert state.pending_ticket_hash is None
            assert state.pending_media_command_id is None
            assert db.get(Debate, debate_id).cancellation_generation == 1
    finally:
        await tasks.close()
        database.dispose()


@pytest.mark.asyncio
async def test_sql_media_prepare_has_one_pending_winner_across_database_instances(
    app_factory: Any,
) -> None:
    database, settings, debate_id, turn_id = _seed_one_turn(app_factory)
    other_database = Database(database.database_url, settings.resolved_data_root)
    try:
        epoch = str(uuid4())
        with database.session() as db:
            db.execute(
                text(
                    "UPDATE playback_states SET status='ready', mode='replay', "
                    "current_turn_id=:turn_id, control_version=8, controller_epoch=:epoch "
                    "WHERE debate_id=:debate_id"
                ),
                {"turn_id": turn_id, "epoch": epoch, "debate_id": debate_id},
            )
            audio = db.execute(
                text(
                    "SELECT sf.relative_path,sf.sha256,sf.size FROM stored_files AS sf "
                    "JOIN debate_turns AS dt ON dt.audio_file_id=sf.id "
                    "WHERE dt.id=:turn_id AND dt.debate_id=:debate_id"
                ),
                {"turn_id": turn_id, "debate_id": debate_id},
            ).one()
        claims = (
            (
                SqlPlaybackRepository(session_factory=database.session_factory),
                str(uuid4()),
                "a" * 64,
            ),
            (
                SqlPlaybackRepository(session_factory=other_database.session_factory),
                str(uuid4()),
                "b" * 64,
            ),
        )

        def claim(item: tuple[SqlPlaybackRepository, str, str]) -> bool:
            repository, command_id, ticket_hash = item
            return repository.claim_media_prepare(
                debate_id=debate_id,
                expected_control_version=8,
                controller_epoch=epoch,
                turn_id=turn_id,
                ticket_hash=ticket_hash,
                command_id=command_id,
                action="replay",
                audio_duration_ms=10,
                expected_audio_relative_path=audio[0],
                expected_audio_sha256=audio[1],
                expected_audio_size_bytes=audio[2],
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(pool.map(claim, claims))
        assert sorted(outcomes) == [False, True]
        with database.session() as db:
            pending = db.execute(
                text(
                    "SELECT pending_action,pending_ticket_hash,pending_media_command_id "
                    "FROM playback_states WHERE debate_id=:debate_id"
                ),
                {"debate_id": debate_id},
            ).one()
            assert pending[0] == "replay"
            assert pending[1] in {"a" * 64, "b" * 64}
            assert pending[2] in {claims[0][1], claims[1][1]}
    finally:
        other_database.dispose()
        database.dispose()


@pytest.mark.asyncio
async def test_sql_reset_and_next_have_one_fresh_writer_winner(app_factory: Any) -> None:
    database, settings, debate_id, first_turn_id = _seed_one_turn(app_factory)
    successor_id = _add_live_successor(database, debate_id, first_turn_id)
    other_database = Database(database.database_url, settings.resolved_data_root)
    try:
        reset_repository = SqlPlaybackRepository(session_factory=database.session_factory)
        next_repository = SqlPlaybackRepository(session_factory=other_database.session_factory)

        def reset() -> dict[str, Any]:
            return reset_repository.claim_operator_reset(
                debate_id=debate_id,
                expected_control_version=8,
            )

        def advance() -> bool:
            return next_repository.claim_next_playback(
                debate_id=debate_id,
                expected_control_version=8,
                expected_current_turn_id=first_turn_id,
                successor_turn_id=successor_id,
                teacher_user_id=TEACHER_ID,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            reset_result, next_result = tuple(pool.map(lambda call: call(), (reset, advance)))
        assert bool(reset_result.get("claimed")) ^ bool(next_result)
        with database.session() as db:
            playback = db.scalar(
                select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
            )
            assert playback is not None
            assert playback.control_version == 9
            if reset_result.get("claimed"):
                assert playback.status == "stopped"
                assert playback.current_turn_id is None
            else:
                assert next_result is True
                assert playback.status == "ready"
                assert playback.current_turn_id == successor_id
    finally:
        other_database.dispose()
        database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("race_point", ("before_claim", "after_claim"))
async def test_sql_media_claim_rolls_back_replay_after_pointer_race(
    app_factory: Any,
    race_point: str,
) -> None:
    database, settings, debate_id, first_turn_id = _seed_one_turn(app_factory)
    successor_id = _add_live_successor(database, debate_id, first_turn_id)
    teacher_context = SimpleNamespace(user=SimpleNamespace(id=TEACHER_ID))
    try:
        with database.session() as db:
            db.execute(
                text("UPDATE debates SET status='debate_finished' WHERE id=:debate_id"),
                {"debate_id": debate_id},
            )
            db.execute(
                text(
                    "UPDATE debate_turns SET publication_status='public', public_at=:now "
                    "WHERE id=:turn_id AND debate_id=:debate_id"
                ),
                {"now": datetime.now(UTC), "turn_id": successor_id, "debate_id": debate_id},
            )
            db.execute(
                text(
                    "UPDATE playback_states SET status='completed', mode='live', "
                    "current_turn_id=NULL, control_version=7 WHERE debate_id=:debate_id"
                ),
                {"debate_id": debate_id},
            )
        repository = SqlPlaybackRepository(session_factory=database.session_factory)
        service = PlaybackService(
            repository,
            audio_store=AudioStore(settings.resolved_data_root),
            task_manager=TaskManager(),
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
                session_hash="race-session",
                connection_id="race-tab",
            )
            epoch = str(controller.controller_epoch)
            first_prepared, _first_result = await service.media_prepare(
                db,
                debate_id,
                command_id=str(uuid4()),
                expected_control_version=controller.control_version,
                epoch=epoch,
                session_hash="race-session",
                turn_id=first_turn_id,
                action="replay",
            )
            first_started = await service.started_ack(
                db,
                debate_id,
                command_id=str(uuid4()),
                expected_control_version=controller.control_version,
                epoch=epoch,
                session_hash="race-session",
                turn_id=first_turn_id,
                action="replay",
            )
            waiting = await service.ended_ack(
                db,
                debate_id,
                command_id=str(uuid4()),
                expected_control_version=first_started.control_version,
                epoch=epoch,
                session_hash="race-session",
                turn_id=first_turn_id,
            )
            ready = await service.next(
                db,
                debate_id,
                expected_control_version=waiting.control_version,
                expected_current_turn_id=first_turn_id,
                context=teacher_context,
            )
            assert ready.status == "ready"
            calls = 0
            original_validate = service._validated_turn_audio

            def move_pointer() -> None:
                with database.session() as concurrent:
                    concurrent.execute(
                        text("UPDATE courses SET current_audio_debate_id=NULL WHERE id=:course_id"),
                        {"course_id": COURSE_ID},
                    )

            def validate_then_move_pointer(*args: Any, **kwargs: Any) -> Any:
                nonlocal calls
                calls += 1
                metadata = original_validate(*args, **kwargs)
                if calls == 2:
                    move_pointer()
                return metadata

            if race_point == "before_claim":
                original_claim = service.repository.claim_media_prepare

                def claim_after_pointer_move(**kwargs: Any) -> bool:
                    move_pointer()
                    return original_claim(**kwargs)

                service.repository.claim_media_prepare = claim_after_pointer_move  # type: ignore[method-assign]
            else:
                service._validated_turn_audio = validate_then_move_pointer  # type: ignore[method-assign]
            with pytest.raises(PlatformError) as raised:
                await service.media_prepare(
                    db,
                    debate_id,
                    command_id=str(uuid4()),
                    expected_control_version=ready.control_version,
                    epoch=epoch,
                    session_hash="race-session",
                    turn_id=successor_id,
                    action="replay",
                )
            assert raised.value.code == "next_not_ready"
            assert calls >= (0 if race_point == "before_claim" else 2)
            assert service.ticket_store.get(first_prepared.token) is None
            assert service.ticket_store.active_count() == 0  # type: ignore[attr-defined]
        with database.session() as db:
            playback = db.scalar(
                select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
            )
            assert playback is not None
            assert (playback.status, playback.mode, playback.current_turn_id) == (
                "waiting_next",
                "replay",
                first_turn_id,
            )
            assert playback.replay_index == 0
            assert playback.pending_action is None
            assert playback.pending_ticket_hash is None
            assert playback.pending_media_command_id is None
            assert playback.audio_duration_ms == 0
        await service.task_manager.close()
    finally:
        database.dispose()


@pytest.mark.asyncio
async def test_sql_replay_queue_survives_database_and_service_restart(app_factory: Any) -> None:
    database, settings, debate_id, first_turn_id = _seed_one_turn(app_factory)
    successor_id = _add_live_successor(database, debate_id, first_turn_id)
    teacher_context = SimpleNamespace(user=SimpleNamespace(id=TEACHER_ID))
    provider = MockTTSProvider()
    first_tasks = TaskManager()
    try:
        with database.session() as db:
            db.execute(
                text("UPDATE debates SET status='debate_finished' WHERE id=:debate_id"),
                {"debate_id": debate_id},
            )
            db.execute(
                text(
                    "UPDATE debate_turns SET publication_status='public', public_at=:now "
                    "WHERE id=:turn_id AND debate_id=:debate_id"
                ),
                {"now": datetime.now(UTC), "turn_id": successor_id, "debate_id": debate_id},
            )
            db.execute(
                text(
                    "UPDATE playback_states SET status='completed', mode='live', "
                    "current_turn_id=NULL, control_version=7 WHERE debate_id=:debate_id"
                ),
                {"debate_id": debate_id},
            )
        repository = SqlPlaybackRepository(session_factory=database.session_factory)
        service = PlaybackService(
            repository,
            audio_store=AudioStore(settings.resolved_data_root, tts_provider=provider),
            task_manager=first_tasks,
            session_factory=database.session_factory,
            settings=settings,
            tts_provider=provider,
        )
        with database.session() as db:
            replay = await service.replay_all(db, debate_id, expected_control_version=7)
            controller = await service.controller_acquire(
                db,
                debate_id,
                command_id=str(uuid4()),
                expected_control_version=replay.control_version,
                session_hash="restart-session",
                connection_id="restart-tab",
            )
            epoch = str(controller.controller_epoch)
            await service.media_prepare(
                db,
                debate_id,
                command_id=str(uuid4()),
                expected_control_version=controller.control_version,
                epoch=epoch,
                session_hash="restart-session",
                turn_id=first_turn_id,
                action="replay",
            )
            started = await service.started_ack(
                db,
                debate_id,
                command_id=str(uuid4()),
                expected_control_version=controller.control_version,
                epoch=epoch,
                session_hash="restart-session",
                turn_id=first_turn_id,
                action="replay",
            )
            waiting = await service.ended_ack(
                db,
                debate_id,
                command_id=str(uuid4()),
                expected_control_version=started.control_version,
                epoch=epoch,
                session_hash="restart-session",
                turn_id=first_turn_id,
            )
        with database.session() as db:
            persisted = db.execute(
                text(
                    "SELECT replay_turn_ids_json,replay_index,current_turn_id,control_version "
                    "FROM playback_states WHERE debate_id=:debate_id"
                ),
                {"debate_id": debate_id},
            ).one()
            assert json.loads(persisted[0]) == [first_turn_id, successor_id]
            assert persisted[1:] == (0, first_turn_id, waiting.control_version)
        await first_tasks.close()
        database.dispose()

        restarted = Database(database.database_url, settings.resolved_data_root)
        try:
            restart_provider = MockTTSProvider()
            restart_tasks = TaskManager()
            restart_repository = SqlPlaybackRepository(session_factory=restarted.session_factory)
            restarted_service = PlaybackService(
                restart_repository,
                audio_store=AudioStore(settings.resolved_data_root, tts_provider=restart_provider),
                task_manager=restart_tasks,
                session_factory=restarted.session_factory,
                settings=settings,
                tts_provider=restart_provider,
            )
            with restarted.session() as db:
                assert await restarted_service.recover_startup(db) == ()
                recovered = db.execute(
                    text(
                        "SELECT replay_turn_ids_json,replay_index,current_turn_id,control_version,"
                        "controller_epoch FROM playback_states WHERE debate_id=:debate_id"
                    ),
                    {"debate_id": debate_id},
                ).one()
                assert json.loads(recovered[0]) == [first_turn_id, successor_id]
                assert recovered[1:4] == (0, first_turn_id, waiting.control_version)
                assert recovered[4] is None
                with pytest.raises(PlatformError) as stale:
                    await restarted_service.media_prepare(
                        db,
                        debate_id,
                        command_id=str(uuid4()),
                        expected_control_version=waiting.control_version,
                        epoch=epoch,
                        session_hash="restart-session",
                        turn_id=first_turn_id,
                        action="replay",
                    )
                assert stale.value.code == "stale_control_version"
                new_controller = await restarted_service.controller_acquire(
                    db,
                    debate_id,
                    command_id=str(uuid4()),
                    expected_control_version=waiting.control_version,
                    session_hash="new-session",
                    connection_id="new-tab",
                )
                advanced = await restarted_service.next(
                    db,
                    debate_id,
                    expected_control_version=new_controller.control_version,
                    expected_current_turn_id=first_turn_id,
                    context=teacher_context,
                )
                assert advanced.status == "ready"
                assert advanced.mode == "replay"
                assert str(advanced.current_turn_id) == successor_id
            assert restart_provider.synthesize_calls == 0
            await restart_tasks.close()
        finally:
            restarted.dispose()
        assert provider.synthesize_calls == 0
    finally:
        database.dispose()


@pytest.mark.asyncio
async def test_sql_reset_writes_one_redacted_audit_row(app_factory: Any) -> None:
    database, _settings, debate_id, turn_id = _seed_one_turn(app_factory)
    try:
        epoch = str(uuid4())
        with database.session() as db:
            db.execute(
                text(
                    "UPDATE playback_states SET status='ready', mode='replay', "
                    "current_turn_id=:turn_id, controller_epoch=:epoch "
                    "WHERE debate_id=:debate_id"
                ),
                {"turn_id": turn_id, "epoch": epoch, "debate_id": debate_id},
            )
        repository = SqlPlaybackRepository(session_factory=database.session_factory)
        result = repository.claim_operator_reset(
            debate_id=debate_id,
            expected_control_version=7,
            actor_kind="operator",
            actor_id=TEACHER_ID,
            request_id=str(uuid4()),
        )
        assert result["claimed"] is True
        with database.session() as db:
            rows = db.execute(
                text(
                    "SELECT event_type,actor_kind,actor_id,course_id,debate_id,request_id,"
                    "details_json FROM audit_logs WHERE debate_id=:debate_id"
                ),
                {"debate_id": debate_id},
            ).all()
            assert len(rows) == 1
            row = rows[0]
            assert row[0:5] == (
                "playback.operator_reset",
                "operator",
                TEACHER_ID,
                COURSE_ID,
                debate_id,
            )
            assert row[5] is not None
            assert json.loads(row[6]) == {
                "control_version": 8,
                "mode": "replay",
                "status": "completed",
            }
            assert all(
                forbidden not in row[6] for forbidden in ("provider", "path", "ticket", "epoch")
            )
    finally:
        database.dispose()


@pytest.mark.asyncio
async def test_sql_reset_rolls_back_state_when_audit_insert_fails(app_factory: Any) -> None:
    database, settings, debate_id, _turn_id = _seed_one_turn(app_factory)
    try:
        with database.session() as db:
            db.execute(
                text(
                    "UPDATE playback_states SET status='ready', mode='replay', "
                    "current_turn_id=:turn_id, controller_epoch=:epoch "
                    "WHERE debate_id=:debate_id"
                ),
                {
                    "turn_id": _turn_id,
                    "epoch": str(uuid4()),
                    "debate_id": debate_id,
                },
            )
            db.execute(text("DROP TABLE audit_logs"))
        repository = SqlPlaybackRepository(session_factory=database.session_factory)
        service = PlaybackService(
            repository,
            session_factory=database.session_factory,
            settings=settings,
        )
        with database.session() as db:
            with pytest.raises(PlatformError) as raised:
                await service.operator_reset(
                    db,
                    debate_id,
                    confirm=True,
                    expected_control_version=7,
                )
        assert raised.value.code == "audit_log_failed"
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            playback = db.scalar(
                select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
            )
            assert debate is not None and debate.status == "debate_finished"
            assert playback is not None
            assert playback.control_version == 7
            assert playback.status == "ready"
    finally:
        database.dispose()


@pytest.mark.asyncio
async def test_sql_replay_next_rollback_cas_returns_successor_to_waiting_gate(
    app_factory: Any,
) -> None:
    database, settings, debate_id, first_turn_id = _seed_one_turn(app_factory)
    successor_id = _add_live_successor(database, debate_id, first_turn_id)
    try:
        with database.session() as db:
            db.execute(
                text("UPDATE debates SET status='debate_finished' WHERE id=:debate_id"),
                {"debate_id": debate_id},
            )
            db.execute(
                text(
                    "UPDATE playback_states SET status='ready', mode='replay', "
                    "current_turn_id=:successor_id, replay_scope='all', replay_index=1, "
                    "replay_turn_ids_json=:queue, control_version=10 "
                    "WHERE debate_id=:debate_id"
                ),
                {
                    "successor_id": successor_id,
                    "queue": json.dumps([first_turn_id, successor_id], separators=(",", ":")),
                    "debate_id": debate_id,
                },
            )
        repository = SqlPlaybackRepository(session_factory=database.session_factory)
        assert repository.rollback_replay_next_playback(
            debate_id=debate_id,
            expected_control_version=10,
            expected_current_turn_id=successor_id,
            expected_replay_index=1,
            previous_turn_id=first_turn_id,
            previous_replay_index=0,
        )
        with database.session() as db:
            playback = db.scalar(
                select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
            )
            assert playback is not None
            assert (playback.status, playback.mode, playback.current_turn_id) == (
                "waiting_next",
                "replay",
                first_turn_id,
            )
            assert playback.replay_index == 0
            assert playback.control_version == 11
            assert playback.pending_action is None
            assert playback.pending_ticket_hash is None
            assert playback.pending_media_command_id is None
            assert playback.audio_duration_ms == 0
    finally:
        database.dispose()


def _add_mutual_round_two_successor(
    database: Database, debate_id: str, first_turn_id: str
) -> tuple[str, str]:
    """Complete round 1 and stage the first round-2 turn of a mutual Debate.

    The round-boundary Next claim compares the successor's visible predecessor
    set against a counted prefix.  Both sides must be scoped to the successor's
    round; scoping the count to the current turn's round makes every mutual
    round boundary permanently unclaimable.
    """

    now = datetime.now(UTC)
    peer_id, successor_id = str(uuid4()), str(uuid4())
    with database.session() as db:
        debate = db.get(Debate, debate_id)
        first = db.get(DebateTurn, first_turn_id)
        assert debate is not None and first is not None
        participant = db.get(DebateParticipant, first.participant_id)
        assert participant is not None
        debate.rule_set_id = "ordered_multi_expert_mutual_learning_v1"
        debate.round_count = 2
        debate.status = "running"
        first.round_no = 1
        first.turn_index = 0
        first.publication_status = "public"
        first.public_at = now
        first.predecessor_turn_ids_json = "[]"
        first.cutoff_turn_index = -1

        store = AudioStore(database.data_root or Path("/tmp"))
        for turn_id, turn_index, round_no, predecessors, cutoff in (
            (peer_id, 1, 1, [], -1),
            (successor_id, 2, 2, [first_turn_id, peer_id], 1),
        ):
            file_id = str(uuid4())
            metadata = store.store_bytes(
                course_id=COURSE_ID,
                debate_id=debate_id,
                turn_id=turn_id,
                raw=_wav_bytes(),
            )
            db.add(
                StoredFile(
                    id=file_id,
                    kind="debate_audio",
                    relative_path=metadata.relative_path,
                    sha256=metadata.sha256,
                    size_bytes=metadata.size_bytes,
                    state="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            db.add(
                DebateTurn(
                    id=turn_id,
                    debate_id=debate_id,
                    participant_id=participant.id,
                    knowledge_snapshot_id=participant.knowledge_snapshot_id,
                    round_no=round_no,
                    turn_index=turn_index,
                    generation_status="final_ready",
                    publication_status="public" if round_no == 1 else "unpublished",
                    preparation_stage="ready",
                    speech=_valid_speech(),
                    structured_json='{"position_summary":"A mutual position."}',
                    predecessor_turn_ids_json=json.dumps(predecessors, separators=(",", ":")),
                    transcript_hash="c" * 64,
                    cutoff_turn_index=cutoff,
                    retrieval_status="no_match",
                    grounding_mode="general_reasoning",
                    retrieval_receipts_json="[]",
                    word_count=80,
                    attempt=1,
                    audio_file_id=file_id,
                    audio_duration_ms=metadata.duration_ms,
                    actual_tts_voice_kind="mock_sentinel",
                    actual_tts_voice_profile_id=None,
                    safe_error_code=None,
                    created_at=now,
                    updated_at=now,
                    public_at=now if round_no == 1 else None,
                )
            )
            db.flush()
            db.add(
                Job(
                    id=str(uuid4()),
                    document_id=None,
                    debate_id=debate_id,
                    turn_id=turn_id,
                    idempotency_key=f"{debate_id}:{turn_id}",
                    claim_token=str(uuid4()),
                    cancellation_generation=0,
                    operation="debate_turn_prepare",
                    state="completed",
                    safe_error_code=None,
                    attempt=1,
                    created_at=now,
                    updated_at=now,
                )
            )
        playback = db.scalar(
            select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
        )
        assert playback is not None
        playback.status = "waiting_next"
        playback.mode = "live"
        playback.current_turn_id = peer_id
        playback.control_version = 8
        playback.controller_epoch = None
        playback.controller_owner_connection = None
        playback.replay_scope = None
        playback.replay_index = None
        playback.pending_action = None
        playback.pending_ticket_hash = None
        playback.pending_media_command_id = None
    return peer_id, successor_id


def test_mutual_learning_next_claim_crosses_a_round_boundary(app_factory: Any) -> None:
    database, _settings, debate_id, first_turn_id = _seed_one_turn(app_factory)
    try:
        peer_id, successor_id = _add_mutual_round_two_successor(database, debate_id, first_turn_id)
        repository = SqlPlaybackRepository(session_factory=database.session_factory)
        claimed = repository.claim_next_playback(
            debate_id=debate_id,
            expected_control_version=8,
            expected_current_turn_id=peer_id,
            successor_turn_id=successor_id,
            teacher_user_id=TEACHER_ID,
        )
        assert claimed is True
        with database.session() as db:
            playback = db.scalar(
                select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
            )
            assert playback is not None
            assert playback.current_turn_id == successor_id
            assert playback.status == "ready"
            assert playback.control_version == 9
    finally:
        database.dispose()


def test_mutual_learning_transcript_turn_omits_round_count(app_factory: Any) -> None:
    """``DebateTurn`` is closed, so the WS-only round_count must not leak in."""

    debate = SimpleNamespace(rule_set_id="ordered_multi_expert_mutual_learning_v1", round_count=2)
    turn = SimpleNamespace(round_no=2)
    ws_payload = PlaybackService._mutual_phase_payload(debate, turn)
    rest_payload = PlaybackService._mutual_phase_only(debate, turn)
    assert ws_payload == {"phase": "final_integration", "round_count": 2}
    assert rest_payload == {"phase": "final_integration"}
