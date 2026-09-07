"""Draft-only Preview retry fences for the segment preparation protocol."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.db import Database
from app.modules.debates.playback.audio import AudioStore
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository
from app.modules.debates.playback.task_manager import TaskManager
from sqlalchemy import text

from tests.test_cleanup_debate_runtime import _seed_runtime_graph, _uid
from tests.test_debate_cleanup import _make_final_ready


@pytest.fixture
def draft_retry_db(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'maya.sqlite3'}", tmp_path)
    database.upgrade_schema()
    ids = _seed_runtime_graph(database, tmp_path)
    ids["job"] = _uid(77)
    speech, structured = _make_final_ready(database, ids)
    value = json.loads(structured)
    for segment in value["segments"]:
        segment["reply_to"] = None
    structured = json.dumps(value, separators=(",", ":"))
    with database.session() as db:
        db.execute(
            text(
                "UPDATE debates SET status='draft', revision=0, cancellation_generation=0, "
                "rule_snapshot_json=:rule WHERE id=:debate_id"
            ),
            {
                "debate_id": ids["debate"],
                "rule": json.dumps(
                    {
                        "round_count": 2,
                        "turn_protocol": "segments_v2",
                    },
                    separators=(",", ":"),
                ),
            },
        )
        db.execute(
            text(
                "UPDATE playback_states SET status='preparing', mode='live', "
                "current_turn_id=NULL, control_version=0 WHERE debate_id=:debate_id"
            ),
            {"debate_id": ids["debate"]},
        )
        db.execute(
            text(
                "UPDATE debate_turns SET generation_status='failed', "
                "preparation_stage='failed', publication_status='unpublished', "
                "speech=:speech, structured_json=:structured, transcript_hash=:transcript, "
                "predecessor_turn_ids_json='[]', cutoff_turn_index=0, word_count=80, "
                "safe_error_code=:code WHERE id=:turn_id"
            ),
            {
                "speech": speech,
                "structured": structured,
                "transcript": "t" * 64,
                "code": "tts_timeout",
                "turn_id": ids["turn"],
            },
        )
        db.execute(
            text(
                "UPDATE jobs SET state='failed', claim_token=NULL, "
                "cancellation_generation=0, operation='debate_turn_prepare', "
                "safe_error_code='tts_timeout' WHERE id=:job_id"
            ),
            {"job_id": ids["job"]},
        )
    try:
        yield database, ids, speech, structured
    finally:
        database.dispose()


def _service(database: Database, data_root: Path) -> PlaybackService:
    return PlaybackService(
        SqlPlaybackRepository(session_factory=database.session_factory),
        audio_store=AudioStore(data_root),
        task_manager=TaskManager(),
        session_factory=database.session_factory,
    )


def _teacher(ids: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=ids["teacher"]))


def test_pending_turn_with_failed_job_projects_actionable_preview_and_list(draft_retry_db):
    from app.core.models import Job
    from app.modules.debates.models import DebateParticipant, DebateTurn
    from app.modules.debates.setup.segment_projection import preview_turn_projection
    from app.modules.debates.setup.service import list_debates

    database, ids, _, _ = draft_retry_db
    with database.session() as db:
        turn = db.get(DebateTurn, ids["turn"])
        turn.generation_status, turn.safe_error_code = "pending", None
        turn.structured_json = None
        participant = db.get(DebateParticipant, turn.participant_id)
        job = db.get(Job, ids["job"])
        db.flush()
        preview = preview_turn_projection(db, turn, participant)
        assert (preview.generation_status, preview.safe_error_code) == ("failed", "tts_timeout")
        summary = next(
            row
            for row in list_debates(db, actor_user_id=ids["teacher"], course_id=ids["course"])
            if str(row.id) == ids["debate"]
        )
        assert summary.stall is not None
        assert summary.stall.safe_error_code == "tts_timeout"
        # An explicit retry replaces the durable failure; it must stop appearing
        # as failed as soon as the Job is queued again.
        job.state, job.safe_error_code = "pending", None
        db.flush()
        assert preview_turn_projection(db, turn, participant).generation_status == "pending"
        summary = next(
            row
            for row in list_debates(db, actor_user_id=ids["teacher"], course_id=ids["course"])
            if str(row.id) == ids["debate"]
        )
        assert summary.stall is None


@pytest.mark.asyncio
async def test_draft_segment_retry_requeues_cached_tts_without_playback_or_provider(
    draft_retry_db,
    monkeypatch,
):
    database, ids, speech, structured = draft_retry_db
    service = _service(database, database.data_root)
    enqueued: list[tuple[str, str]] = []

    async def record_enqueue(debate, turn):
        enqueued.append((str(debate.id), str(turn.id)))
        return True

    monkeypatch.setattr(service, "_enqueue", record_enqueue)
    try:
        with database.session() as db:
            state = await service.retry_preparation(
                db,
                ids["debate"],
                turn_id=ids["turn"],
                expected_control_version=0,
                context=_teacher(ids),
            )
            assert state.status == "preparing"
            assert state.mode == "live"
            assert state.current_turn_id is None
            assert state.control_version == 1
        with database.session() as db:
            assert db.execute(
                text(
                    "SELECT generation_status, preparation_stage, speech, structured_json, "
                    "transcript_hash, safe_error_code FROM debate_turns WHERE id=:turn_id"
                ),
                {"turn_id": ids["turn"]},
            ).one() == ("pending", "generation", speech, structured, "t" * 64, None)
            assert db.execute(
                text("SELECT state, safe_error_code FROM jobs WHERE id=:job_id"),
                {"job_id": ids["job"]},
            ).one() == ("pending", None)
            assert db.execute(
                text(
                    "SELECT status, current_turn_id, control_version "
                    "FROM playback_states WHERE debate_id=:debate_id"
                ),
                {"debate_id": ids["debate"]},
            ).one() == ("preparing", None, 1)
        assert enqueued == [(ids["debate"], ids["turn"])]
    finally:
        await service.task_manager.close()


@pytest.mark.asyncio
async def test_draft_segment_retry_idempotency_replays_without_second_enqueue(
    draft_retry_db,
    monkeypatch,
):
    database, ids, _speech, _structured = draft_retry_db
    service = _service(database, database.data_root)
    enqueued: list[tuple[str, str]] = []

    async def record_enqueue(debate, turn):
        enqueued.append((str(debate.id), str(turn.id)))
        return True

    monkeypatch.setattr(service, "_enqueue", record_enqueue)
    key = "draft-segment-retry-001"
    try:
        with database.session() as db:
            first = await service.retry_preparation(
                db,
                ids["debate"],
                turn_id=ids["turn"],
                expected_control_version=0,
                context=_teacher(ids),
                idempotency_key=key,
            )
        with database.session() as db:
            replay = await service.retry_preparation(
                db,
                ids["debate"],
                turn_id=ids["turn"],
                expected_control_version=0,
                context=_teacher(ids),
                idempotency_key=key,
            )
        assert first.control_version == replay.control_version == 1
        assert enqueued == [(ids["debate"], ids["turn"])]
    finally:
        await service.task_manager.close()


def test_draft_retry_rejects_stale_control_and_unknown_or_ambiguous_failure(draft_retry_db):
    database, ids, _speech, _structured = draft_retry_db
    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    try:
        with database.session() as db:
            debate = repository.get_debate(db, ids["debate"])
            assert debate is not None
            turn = next(
                item for item in repository.turns(db, debate) if str(item.id) == ids["turn"]
            )
            assert not repository.retry_draft_segment_turn(
                db,
                debate,
                turn,
                expected_control_version=1,
                code="tts_timeout",
            )
            assert not repository.retry_draft_segment_turn(
                db,
                debate,
                turn,
                expected_control_version=0,
                code="acceptance_unknown",
            )
            assert not repository.retry_draft_segment_turn(
                db,
                debate,
                turn,
                expected_control_version=0,
                code="tts_outcome_unknown",
            )
    finally:
        database.dispose()


def test_draft_retry_cannot_skip_next_unprepared_preview_turn(draft_retry_db):
    database, ids, _speech, _structured = draft_retry_db
    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    try:
        with database.session() as db:
            debate = repository.get_debate(db, ids["debate"])
            assert debate is not None
            turns = repository.turns(db, debate)
            assert len(turns) == 1
            # A later turn ID is not in this Preview plan, so the helper must
            # refuse it even though its control version is otherwise current.
            fake_turn = turns[0]
            fake_turn.id = _uid(999)
            assert not repository.retry_draft_segment_turn(
                db,
                debate,
                fake_turn,
                expected_control_version=0,
                code="tts_timeout",
            )
    finally:
        database.dispose()


def test_release_claim_preserves_cached_segment_fence(draft_retry_db):
    database, ids, speech, structured = draft_retry_db
    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    try:
        with database.session() as db:
            db.execute(
                text(
                    "UPDATE debate_turns SET generation_status='running', "
                    "preparation_stage='generation', safe_error_code='tts_timeout' "
                    "WHERE id=:turn_id"
                ),
                {"turn_id": ids["turn"]},
            )
            db.execute(
                text(
                    "UPDATE jobs SET state='running', claim_token='release-claim' WHERE id=:job_id"
                ),
                {"job_id": ids["job"]},
            )
            debate = repository.get_debate(db, ids["debate"])
            assert debate is not None
            turn = next(
                item for item in repository.turns(db, debate) if str(item.id) == ids["turn"]
            )
            assert repository.reset_prewarm_turn(
                db,
                turn,
                claim_token="release-claim",
            )
            assert db.execute(
                text(
                    "SELECT generation_status, speech, structured_json, transcript_hash "
                    "FROM debate_turns WHERE id=:turn_id"
                ),
                {"turn_id": ids["turn"]},
            ).one() == ("pending", speech, structured, "t" * 64)
    finally:
        database.dispose()
