"""Draft-only Preview retry fences for the segment preparation protocol."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import LlmAcceptedStage, LlmRecoveryInput, ProviderOperation
from app.main import create_app
from app.modules.debates.models import DebateTurn
from app.modules.debates.playback.audio import AudioStore
from app.modules.debates.playback.protocols import (
    PreparedGenerationFence,
    PreparedTurn,
    ResolvedTurnVoice,
)
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository
from app.modules.debates.playback.task_manager import TaskManager
from app.providers.tts import MockTTSProvider, TTSProviderTimeout
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.postgres_db import named_url
from tests.test_cleanup_debate_runtime import _seed_runtime_graph, _uid
from tests.test_debate_cleanup import _make_final_ready


@pytest.fixture
def draft_retry_db(tmp_path: Path):
    database = Database(named_url(f"{tmp_path / 'maya.sqlite3'}"), tmp_path)
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


@pytest.fixture
def draft_retry_with_prefix(draft_retry_db):
    database, ids, _speech, _structured = draft_retry_db
    ids = {**ids, "prefix": _uid(999)}
    with database.session() as db:
        failed = db.get(DebateTurn, ids["turn"])
        prefix = {
            column.name: getattr(failed, column.name) for column in DebateTurn.__table__.columns
        }
        failed.turn_index = 1
        failed.audio_file_id = None
        failed.audio_duration_ms = None
        failed.safe_error_code = "provider_not_sent"
        db.flush()
        prefix.update(
            id=ids["prefix"],
            turn_index=0,
            generation_status="final_ready",
            preparation_stage="ready",
            publication_status="unpublished",
            public_at=None,
            predecessor_turn_ids_json="[]",
            cutoff_turn_index=-1,
            safe_error_code="tts_timeout",
            audio_file_id=None,
            audio_duration_ms=None,
            actual_tts_voice_kind=None,
            actual_tts_voice_profile_id=None,
        )
        db.add(DebateTurn(**prefix))
        db.execute(
            text("UPDATE jobs SET safe_error_code='provider_not_sent' WHERE id=:job_id"),
            {"job_id": ids["job"]},
        )
    return database, ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prefix_kind", "provider_code", "rejection"),
    [
        ("text", "provider_not_sent", None),
        ("text", "provider_confirmation_required", None),
        ("audio", "provider_not_sent", None),
        ("audio", "provider_confirmation_required", None),
        ("unknown_tts", "provider_not_sent", "invalid_state"),
        ("unknown_acceptance", "provider_not_sent", "invalid_state"),
        ("missing_error", "provider_not_sent", "invalid_state"),
        ("empty_speech", "provider_not_sent", "invalid_state"),
        ("blank_speech", "provider_not_sent", "invalid_state"),
        ("pending", "provider_not_sent", "invalid_state"),
        ("retry_prefix", "provider_not_sent", None),  # M2: text-fallback prefix may Retry TTS
        ("stale_version", "provider_not_sent", "stale_control_version"),
        ("student", "provider_not_sent", "forbidden"),
        ("running_job", "provider_not_sent", "stale_control_version"),
    ],
)
async def test_draft_retry_respects_prepared_prefix_and_control_fences(
    draft_retry_with_prefix, monkeypatch, prefix_kind, provider_code, rejection
):
    database, ids = draft_retry_with_prefix
    with database.session() as db:
        prefix = db.get(DebateTurn, ids["prefix"])
        if prefix_kind == "audio":
            prefix.audio_file_id = ids["audio_file"]
            prefix.audio_duration_ms = 1000
            prefix.actual_tts_voice_kind = "mock_sentinel"
            prefix.safe_error_code = None
        elif prefix_kind in {"unknown_tts", "unknown_acceptance", "missing_error"}:
            prefix.safe_error_code = {
                "unknown_tts": "tts_unreviewed",
                "unknown_acceptance": "acceptance_unknown",
                "missing_error": None,
            }[prefix_kind]
        elif prefix_kind in {"empty_speech", "blank_speech"}:
            prefix.speech = "" if prefix_kind == "empty_speech" else " \n "
        elif prefix_kind == "pending":
            prefix.generation_status = "pending"
            prefix.preparation_stage = "generation"
        db.get(DebateTurn, ids["turn"]).safe_error_code = provider_code
        db.execute(
            text("UPDATE jobs SET safe_error_code=:code, state=:state WHERE id=:job_id"),
            {
                "code": provider_code,
                "state": "running" if prefix_kind == "running_job" else "failed",
                "job_id": ids["job"],
            },
        )

    def snapshot():
        with database.session() as db:
            return {
                table: [
                    dict(row)
                    for row in db.execute(
                        text(f"SELECT * FROM {table} WHERE debate_id=:debate_id ORDER BY id"),
                        {"debate_id": ids["debate"]},
                    ).mappings()
                ]
                for table in ("debate_turns", "jobs", "playback_states", "debate_events")
            }

    before = snapshot()
    service = _service(database, database.data_root)
    enqueued: list[str] = []

    async def record_enqueue(_debate, turn):
        enqueued.append(str(turn.id))
        return True

    monkeypatch.setattr(service, "_enqueue", record_enqueue)
    arguments = {
        "turn_id": ids["prefix"] if prefix_kind == "retry_prefix" else ids["turn"],
        "expected_control_version": 1 if prefix_kind == "stale_version" else 0,
        "context": (
            SimpleNamespace(user=SimpleNamespace(id=ids["user"]))
            if prefix_kind == "student"
            else _teacher(ids)
        ),
    }
    try:
        if rejection is not None:
            with pytest.raises(PlatformError) as failure:
                with database.session() as db:
                    await service.retry_preparation(db, ids["debate"], **arguments)
            assert failure.value.code == rejection
            assert snapshot() == before
            assert enqueued == []
            return
        with database.session() as db:
            state = await service.retry_preparation(db, ids["debate"], **arguments)
        after = snapshot()
        assert (state.status, state.mode, state.current_turn_id, state.control_version) == (
            "preparing",
            "live",
            None,
            1,
        )
        if prefix_kind == "retry_prefix":
            # M2: Retry on a text-fallback prefix requeues that prefix for TTS.
            assert enqueued == [ids["prefix"]]
            prefix_after = next(row for row in after["debate_turns"] if row["id"] == ids["prefix"])
            assert (prefix_after["generation_status"], prefix_after["safe_error_code"]) == (
                "pending",
                None,
            )
            later = next(row for row in after["debate_turns"] if row["id"] == ids["turn"])
            assert later["safe_error_code"] == provider_code
        else:
            assert enqueued == [ids["turn"]]
            assert next(row for row in after["debate_turns"] if row["id"] == ids["prefix"]) == next(
                row for row in before["debate_turns"] if row["id"] == ids["prefix"]
            )
            target = next(row for row in after["debate_turns"] if row["id"] == ids["turn"])
            assert (target["generation_status"], target["safe_error_code"]) == ("pending", None)
            job = next(row for row in after["jobs"] if row["id"] == ids["job"])
            assert (job["state"], job["safe_error_code"], job["claim_token"]) == (
                "pending",
                None,
                None,
            )
        assert all(row["publication_status"] == "unpublished" for row in after["debate_turns"])
        assert after["debate_events"] == before["debate_events"]
    finally:
        await service.task_manager.close()


def test_final_ready_preview_prefix_cannot_have_null_speech(draft_retry_with_prefix):
    database, ids = draft_retry_with_prefix
    with pytest.raises(IntegrityError, match="ck_debate_turns_final_ready_shape"):
        with database.session() as db:
            db.execute(
                text("UPDATE debate_turns SET speech=NULL WHERE id=:turn_id"),
                {"turn_id": ids["prefix"]},
            )
    with database.session() as db:
        assert db.get(DebateTurn, ids["prefix"]).speech is not None


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
@pytest.mark.parametrize(
    "code",
    [
        "tts_voice_unavailable",
        "tts_provider_unavailable",
        "tts_timeout",
    ],
)
async def test_draft_retry_requeues_final_ready_text_fallback_tts(
    draft_retry_db,
    monkeypatch,
    code,
):
    """Preview soft-fail (final_ready + tts_* + speech, job completed) must Retry TTS."""

    database, ids, speech, structured = draft_retry_db
    with database.session() as db:
        db.execute(
            text(
                "UPDATE debate_turns SET generation_status='final_ready', "
                "preparation_stage='ready', publication_status='unpublished', "
                "audio_file_id=NULL, audio_duration_ms=NULL, "
                "safe_error_code=:code WHERE id=:turn_id"
            ),
            {"code": code, "turn_id": ids["turn"]},
        )
        db.execute(
            text(
                "UPDATE jobs SET state='completed', claim_token=NULL, "
                "safe_error_code=NULL WHERE id=:job_id"
            ),
            {"job_id": ids["job"]},
        )
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
            assert state.current_turn_id is None
            assert state.control_version == 1
        with database.session() as db:
            assert db.execute(
                text(
                    "SELECT generation_status, preparation_stage, speech, "
                    "transcript_hash, safe_error_code FROM debate_turns WHERE id=:turn_id"
                ),
                {"turn_id": ids["turn"]},
            ).one() == ("pending", "generation", speech, "t" * 64, None)
            assert db.execute(
                text("SELECT state, safe_error_code, claim_token FROM jobs WHERE id=:job_id"),
                {"job_id": ids["job"]},
            ).one() == ("pending", None, None)
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
                cancellation_generation=0,
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


@pytest.fixture
def pending_draft_runtime(draft_retry_db, monkeypatch):
    database, ids, speech, structured = draft_retry_db
    with database.session() as db:
        db.execute(
            text(
                "UPDATE debate_turns SET generation_status='pending', "
                "round_no=1, "
                "preparation_stage='generation', safe_error_code=NULL, speech=NULL, "
                "structured_json=NULL, transcript_hash=NULL, audio_file_id=NULL, "
                "audio_duration_ms=NULL WHERE id=:turn_id"
            ),
            {"turn_id": ids["turn"]},
        )
        db.execute(
            text(
                "UPDATE jobs SET state='pending', safe_error_code=NULL, "
                "idempotency_key=:key WHERE id=:job_id"
            ),
            {"job_id": ids["job"], "key": f"{ids['debate']}:{ids['turn']}"},
        )
    settings = Settings(
        maya_env="test",
        session_secret="x" * 32,
        database_url=database.database_url,
        data_root=database.data_root,
        llm_provider="mock",
        embedding_provider="mock",
        tts_provider="mock",
        voice_provider="mock",
    )
    app = create_app(settings=settings, database=database, initialize_database=False)
    with database.session() as db:
        assert (
            db.execute(
                text(
                    "SELECT COUNT(*) FROM jobs WHERE turn_id=:turn_id "
                    "AND operation='debate_turn_prepare'"
                ),
                {"turn_id": ids["turn"]},
            ).scalar_one()
            == 1
        )
    service = app.state.playback_service
    monkeypatch.setattr(
        service,
        "_resolve_voice",
        lambda *_args: ResolvedTurnVoice("mock_sentinel", None, "mock"),
    )
    return app, database, ids, speech, structured


def _claim_rows(database, ids):
    with database.session() as db:
        return {
            table: [
                dict(row)
                for row in db.execute(
                    text(f"SELECT * FROM {table} WHERE debate_id=:debate_id ORDER BY id"),
                    {"debate_id": ids["debate"]},
                ).mappings()
            ]
            for table in ("debate_turns", "jobs", "playback_states", "debate_events")
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("phase", "cancel_owner"),
    [("preparer", False), ("tts", False), ("preparer", True), ("tts", True), ("legacy_tts", True)],
)
async def test_draft_claim_is_released_only_by_its_finished_owner(
    pending_draft_runtime, phase, cancel_owner
):
    app, database, ids, speech, structured = pending_draft_runtime
    service = app.state.playback_service
    if phase == "legacy_tts":
        with database.session() as db:
            db.execute(
                text("UPDATE debates SET rule_snapshot_json=:rule WHERE id=:debate_id"),
                {"rule": json.dumps({"round_count": 2}), "debate_id": ids["debate"]},
            )
    entered, release, finished = Event(), Event(), Event()
    calls = 0

    def barrier():
        entered.set()
        assert release.wait(timeout=5)
        finished.set()

    class Preparer:
        def generation_fence(self, *_args, **_kwargs):
            return PreparedGenerationFence((), "t" * 64, 0)

        def __call__(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            if phase == "preparer":
                barrier()
            return PreparedTurn(
                speech=speech,
                structured=json.loads(structured),
                transcript_hash="t" * 64,
                cutoff_turn_index=0,
                word_count=80,
            )

    class TTS(MockTTSProvider):
        def synthesize(self, *_args, **_kwargs):
            if phase in {"tts", "legacy_tts"}:
                barrier()
            raise TTSProviderTimeout()

    service.turn_preparer = Preparer()
    service.audio_store.tts_provider = TTS()
    try:
        assert await service.task_manager.enqueue(ids["debate"], ids["turn"], service._prepare_task)
        owner = next(iter(service.task_manager._tasks.values()))
        reached_barrier = await asyncio.to_thread(entered.wait, 3)
        if owner.done():
            assert owner.exception() is None
        assert reached_barrier
        before = _claim_rows(database, ids)
        before_job = next(row for row in before["jobs"] if row["id"] == ids["job"])
        assert before_job["state"] == "running" and before_job["claim_token"]
        if cancel_owner:
            owner.cancel()
            await asyncio.sleep(0)
            assert not owner.done()
            assert _claim_rows(database, ids) == before
            owner.cancel()
            await asyncio.sleep(0)
            assert not owner.done()
            assert _claim_rows(database, ids) == before
        else:
            await app.state.prewarm_scheduler._prepare(ids["debate"], ids["turn"])
            assert _claim_rows(database, ids) == before
            assert calls == 1
        release.set()
        await asyncio.gather(owner, return_exceptions=True)
        assert finished.is_set()
        after = _claim_rows(database, ids)
        turn = next(row for row in after["debate_turns"] if row["id"] == ids["turn"])
        job = next(row for row in after["jobs"] if row["id"] == ids["job"])
        assert calls == 1
        assert after["playback_states"] == before["playback_states"]
        assert after["debate_events"] == before["debate_events"]
        if cancel_owner:
            assert owner.cancelled()
            assert job["claim_token"] is None
            assert (turn["generation_status"], job["state"]) == ("pending", "pending")
            if phase == "tts":
                original = next(row for row in before["debate_turns"] if row["id"] == ids["turn"])
                for field in (
                    "speech",
                    "structured_json",
                    "transcript_hash",
                    "predecessor_turn_ids_json",
                    "cutoff_turn_index",
                    "retrieval_receipts_json",
                    "evidence_trace_json",
                ):
                    assert turn[field] == original[field]
                assert turn["speech"] == speech and turn["transcript_hash"] == "t" * 64
            else:
                assert turn["speech"] is None and turn["transcript_hash"] is None
        else:
            assert owner.exception() is None
            assert (turn["generation_status"], job["state"]) == ("final_ready", "completed")
            assert job["claim_token"] == before_job["claim_token"]
            await app.state.prewarm_scheduler._prepare(ids["debate"], ids["turn"])
            assert _claim_rows(database, ids) == after
            assert calls == 1
    finally:
        release.set()
        await service.task_manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ValueError, asyncio.CancelledError, None])
async def test_owned_job_is_released_if_preparation_exits_before_mark_running(
    pending_draft_runtime, monkeypatch, failure
):
    app, database, ids, _speech, _structured = pending_draft_runtime
    service = app.state.playback_service

    async def fail_after_claim(db, *_args, **_kwargs):
        db.commit()
        if failure is not None:
            raise failure()
        return PreparedGenerationFence((), "t" * 64, 0)

    monkeypatch.setattr(service, "_generation_fence", fail_after_claim)
    if failure is None:
        monkeypatch.setattr(
            service.repository, "mark_turn_prewarming", lambda *_args, **_kwargs: False
        )
    try:
        if failure is None:
            await service._prepare_task(ids["debate"], ids["turn"])
        else:
            with pytest.raises(failure):
                await service._prepare_task(ids["debate"], ids["turn"])
        rows = _claim_rows(database, ids)
        turn = next(row for row in rows["debate_turns"] if row["id"] == ids["turn"])
        job = next(row for row in rows["jobs"] if row["id"] == ids["job"])
        assert (turn["generation_status"], job["state"], job["claim_token"]) == (
            "pending",
            "pending",
            None,
        )
    finally:
        await service.task_manager.close()


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize(
    "condition",
    [
        "owned",
        "pending_turn",
        "stale_token",
        "missing_token",
        "expected_generation",
        "job_generation",
        "debate_generation",
        "wrong_operation",
        "wrong_debate",
        "settled_job",
        "failed_turn",
        "final_ready",
        "live_debate",
        "turn_unknown",
        "job_unknown",
        "sending",
        "acceptance_unknown",
        "accepted_complete",
        "accepted_missing_stage",
        "accepted_missing_input",
        "accepted_wrong_attempt",
    ],
)
def test_prewarm_release_requires_current_owner_and_recoverable_ledger(
    draft_retry_db, cached, condition
):
    database, ids, speech, structured = draft_retry_db
    repository = SqlPlaybackRepository()
    token = "owned-claim"
    generation = 0
    with database.session() as db:
        db.execute(
            text(
                "UPDATE debate_turns SET generation_status=:status, "
                "preparation_stage='generation', "
                "safe_error_code=NULL, speech=:speech, structured_json=:structured "
                "WHERE id=:turn_id"
            ),
            {
                "status": "pending" if condition == "pending_turn" else "running",
                "speech": speech if cached else None,
                "structured": structured if cached else None,
                "turn_id": ids["turn"],
            },
        )
        db.execute(
            text(
                "UPDATE jobs SET state='running', claim_token=:token, safe_error_code=NULL "
                "WHERE id=:job_id"
            ),
            {"job_id": ids["job"], "token": token},
        )
        changes = {
            "job_generation": "UPDATE jobs SET cancellation_generation=1 WHERE id=:job",
            "debate_generation": "UPDATE debates SET cancellation_generation=1 WHERE id=:debate",
            "wrong_operation": "UPDATE jobs SET operation='report_prepare' WHERE id=:job",
            "settled_job": "UPDATE jobs SET state='completed' WHERE id=:job",
            "failed_turn": "UPDATE debate_turns SET generation_status='failed' WHERE id=:turn",
            "live_debate": "UPDATE debates SET status='running' WHERE id=:debate",
            "turn_unknown": (
                "UPDATE debate_turns SET safe_error_code='acceptance_unknown' WHERE id=:turn"
            ),
            "job_unknown": "UPDATE jobs SET safe_error_code='acceptance_unknown' WHERE id=:job",
        }
        if condition in changes:
            db.execute(text(changes[condition]), ids)
        if condition == "final_ready":
            db.execute(
                text(
                    "UPDATE debate_turns SET generation_status='final_ready', "
                    "preparation_stage='ready', speech=:speech, "
                    "structured_json=:structured WHERE id=:turn"
                ),
                {**ids, "speech": speech, "structured": structured},
            )
        if condition in {
            "sending",
            "acceptance_unknown",
            "accepted_complete",
            "accepted_missing_stage",
        }:
            db.execute(
                text("UPDATE provider_operations SET state=:state WHERE id=:operation"),
                {
                    **ids,
                    "state": "accepted" if condition.startswith("accepted_") else condition,
                },
            )
        if condition == "accepted_missing_stage":
            db.execute(text("DELETE FROM llm_accepted_stages WHERE operation_id=:operation"), ids)
        if condition in {"accepted_missing_input", "accepted_wrong_attempt"}:
            # Recovery inputs are immutable. Build a separate incomplete attempt
            # instead of weakening the database's update/delete protection.
            for model in (ProviderOperation, LlmAcceptedStage, LlmRecoveryInput):
                if model is LlmRecoveryInput and condition == "accepted_missing_input":
                    continue
                original = db.get(model, ids["operation"])
                values = {
                    column.name: getattr(original, column.name)
                    for column in model.__table__.columns
                }
                values["attempt_no"] = 2
                if model is ProviderOperation:
                    values.update(id=_uid(998), state="accepted", call_no=3)
                    if condition == "accepted_wrong_attempt":
                        values["attempt_no"] = 3
                else:
                    values["operation_id"] = _uid(998)
                db.add(model(**values))
                db.flush()
        if condition == "stale_token":
            token = "stale-claim"
        elif condition == "missing_token":
            token = None
        elif condition == "expected_generation":
            generation = 1

    def snapshot():
        with database.session() as db:
            return {
                table: [dict(row) for row in db.execute(text(f"SELECT * FROM {table}")).mappings()]
                for table in (
                    "debate_turns",
                    "jobs",
                    "playback_states",
                    "debate_events",
                    "provider_operations",
                    "llm_accepted_stages",
                    "llm_recovery_inputs",
                )
            }

    before = snapshot()
    expected = condition in {"owned", "pending_turn", "accepted_complete"}
    with database.session() as db:
        turn = repository.turns(db, repository.get_debate(db, ids["debate"]))[0]
        if condition == "wrong_debate":
            turn.debate_id = _uid(999)
        assert (
            repository.reset_prewarm_turn(
                db, turn, claim_token=token, cancellation_generation=generation
            )
            is expected
        )
    after = snapshot()
    if not expected:
        assert after == before
        return
    original_turn = next(row for row in before["debate_turns"] if row["id"] == ids["turn"])
    turn = next(row for row in after["debate_turns"] if row["id"] == ids["turn"])
    original_job = next(row for row in before["jobs"] if row["id"] == ids["job"])
    job = next(row for row in after["jobs"] if row["id"] == ids["job"])
    assert turn == {
        **original_turn,
        "generation_status": "pending",
        "preparation_stage": "generation",
        "transcript_hash": "t" * 64 if cached else None,
        "updated_at": turn["updated_at"],
    }
    assert job == {
        **original_job,
        "state": "pending",
        "claim_token": None,
        "updated_at": job["updated_at"],
    }
    after["debate_turns"] = before["debate_turns"]
    after["jobs"] = [original_job if row["id"] == ids["job"] else row for row in after["jobs"]]
    assert after == before


@pytest.mark.parametrize("cached", [False, True])
def test_prewarm_release_rolls_back_turn_when_job_update_loses_claim(
    draft_retry_db, monkeypatch, cached
):
    database, ids, _speech, _structured = draft_retry_db
    repository = SqlPlaybackRepository()
    with database.session() as db:
        db.execute(
            text(
                "UPDATE debate_turns SET generation_status='running', safe_error_code=NULL, "
                "speech=CASE WHEN :cached THEN speech ELSE NULL END, "
                "structured_json=CASE WHEN :cached THEN structured_json ELSE NULL END "
                "WHERE id=:turn_id"
            ),
            {"turn_id": ids["turn"], "cached": cached},
        )
        db.execute(
            text(
                "UPDATE jobs SET state='running', claim_token='owned', safe_error_code=NULL "
                "WHERE id=:job_id"
            ),
            {"job_id": ids["job"]},
        )
    before = _claim_rows(database, ids)
    with database.session() as db:
        turn = repository.turns(db, repository.get_debate(db, ids["debate"]))[0]
        execute = db.execute

        def lose_job_update(statement, *args, **kwargs):
            if str(statement).startswith("UPDATE jobs SET state='pending'"):
                return SimpleNamespace(rowcount=0)
            return execute(statement, *args, **kwargs)

        monkeypatch.setattr(db, "execute", lose_job_update)
        assert not repository.reset_prewarm_turn(
            db, turn, claim_token="owned", cancellation_generation=0
        )
    assert _claim_rows(database, ids) == before
