"""M2: first prepare job must exist after plan; Postgres insert portable; stub TTS path."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.modules.debates.models import Debate, DebateTurn
from app.modules.debates.playback.generation_adapter import SqlTurnPreparer
from app.modules.debates.playback.sql_repository import (
    _PREPARATION_TIMEOUT_CODE,
    SqlPlaybackRepository,
)
from app.modules.debates.playback.task_manager import TaskManager
from app.providers.llm import MockLLMProvider
from app.providers.tts import MockTTSProvider, TTSProviderUnavailableError
from sqlalchemy import text

from tests.test_wave4_llm_p1_product import _product_service, _seed_running_product_debate


def test_ensure_turn_job_postgres_uses_on_conflict_not_or_ignore() -> None:
    """Capture SQL: Postgres path must never emit INSERT OR IGNORE.

    Prod R3 partial unique:
    ``UNIQUE (operation, idempotency_key) WHERE idempotency_key IS NOT NULL``.
    Conflict target must include that WHERE (bare columns → InvalidColumnReference).
    """

    statements: list[str] = []

    class _Result:
        rowcount = 0

    class _FakeDB:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement, params=None):
            del params
            statements.append(str(statement))
            return _Result()

    debate = SimpleNamespace(id="debate-1", cancellation_generation=0)
    turn = SimpleNamespace(id="turn-1", turn_index=0)
    SqlPlaybackRepository._ensure_turn_job(_FakeDB(), debate, turn)
    assert statements, "expected an INSERT"
    sql = " ".join(statements).upper()
    assert "INSERT OR IGNORE" not in sql
    assert "ON CONFLICT (OPERATION, IDEMPOTENCY_KEY)" in sql
    assert "WHERE IDEMPOTENCY_KEY IS NOT NULL" in sql
    assert "DO NOTHING" in sql



@pytest.mark.asyncio
async def test_ensure_turn_plan_inserts_first_prepare_job(app_factory) -> None:
    """After plan materialisation, head turn must have debate_turn_prepare pending."""

    _, database, settings, debate_id, _turn_id = _seed_running_product_debate(app_factory)
    del settings
    repository = SqlPlaybackRepository()
    with database.session() as db:
        # Reset to draft Preview shape with no jobs (D3 prod shape).
        debate_row = db.get(Debate, debate_id)
        debate_row.status = "draft"
        db.execute(text("DELETE FROM jobs WHERE debate_id=:id"), {"id": debate_id})
        db.execute(
            text(
                "UPDATE debate_turns SET generation_status='pending', "
                "preparation_stage='generation', publication_status='unpublished', "
                "speech=NULL, audio_file_id=NULL, safe_error_code=NULL "
                "WHERE debate_id=:id"
            ),
            {"id": debate_id},
        )
        db.execute(
            text(
                "UPDATE playback_states SET status='preparing', mode='live', "
                "current_turn_id=NULL, control_version=0 WHERE debate_id=:id"
            ),
            {"id": debate_id},
        )
        db.commit()

        sql_debate = repository.get_debate(db, debate_id)
        turns = repository.ensure_turn_plan(db, sql_debate)
        db.commit()
        assert turns
        first = sorted(turns, key=lambda item: int(item.turn_index))[0]
        job = db.execute(
            text(
                "SELECT state, claim_token, safe_error_code, operation "
                "FROM jobs WHERE debate_id=:debate_id AND turn_id=:turn_id"
            ),
            {"debate_id": debate_id, "turn_id": str(first.id)},
        ).one()
        assert tuple(job) == ("pending", None, None, "debate_turn_prepare")
        # Idempotent re-plan must not duplicate the head job.
        repository.ensure_turn_plan(db, sql_debate)
        db.commit()
        count = db.execute(
            text(
                "SELECT COUNT(*) FROM jobs WHERE debate_id=:debate_id "
                "AND operation='debate_turn_prepare'"
            ),
            {"debate_id": debate_id},
        ).scalar()
        assert int(count) == 1
    database.dispose()


@pytest.mark.asyncio
async def test_expire_without_job_materializes_timeout_job_and_retry(app_factory) -> None:
    """D3: timeout with zero jobs still leaves a Retry-compatible failed job."""

    _, database, settings, debate_id, turn_id = _seed_running_product_debate(app_factory)
    del settings
    repository = SqlPlaybackRepository()
    stale = datetime.now(UTC) - timedelta(seconds=120)
    with database.session() as db:
        debate_row = db.get(Debate, debate_id)
        debate_row.status = "draft"
        rule = json.loads(debate_row.rule_snapshot_json)
        rule["turn_protocol"] = "segments_v2"
        debate_row.rule_snapshot_json = json.dumps(rule)
        db.execute(text("DELETE FROM jobs WHERE debate_id=:id"), {"id": debate_id})
        db.execute(
            text(
                "UPDATE debate_turns SET generation_status='pending', "
                "preparation_stage='generation', publication_status='unpublished', "
                "speech=NULL, safe_error_code=NULL, updated_at=:stale "
                "WHERE id=:turn_id"
            ),
            {"turn_id": turn_id, "stale": stale},
        )
        # Keep later turns unfinished but younger so only the head expires first.
        db.execute(
            text(
                "UPDATE debate_turns SET generation_status='pending', "
                "preparation_stage='generation', publication_status='unpublished', "
                "speech=NULL, safe_error_code=NULL, updated_at=:fresh "
                "WHERE debate_id=:debate_id AND id<>:turn_id"
            ),
            {"debate_id": debate_id, "turn_id": turn_id, "fresh": datetime.now(UTC)},
        )
        db.execute(
            text(
                "UPDATE playback_states SET status='preparing', mode='live', "
                "current_turn_id=NULL, control_version=0 WHERE debate_id=:id"
            ),
            {"id": debate_id},
        )
        db.commit()

        assert repository.expire_stale_preparation(db, debate_id=debate_id) == 1
        db.commit()
        job = db.execute(
            text(
                "SELECT state, safe_error_code FROM jobs "
                "WHERE debate_id=:debate_id AND turn_id=:turn_id "
                "AND operation='debate_turn_prepare'"
            ),
            {"debate_id": debate_id, "turn_id": turn_id},
        ).one()
        assert job[0] == "failed"
        assert job[1] == _PREPARATION_TIMEOUT_CODE

        sql_debate = repository.get_debate(db, debate_id)
        turn = next(item for item in repository.turns(db, sql_debate) if str(item.id) == turn_id)
        assert repository.retry_draft_segment_turn(
            db,
            sql_debate,
            turn,
            expected_control_version=0,
            code=_PREPARATION_TIMEOUT_CODE,
        )
        db.commit()
        job2 = db.execute(
            text(
                "SELECT state, safe_error_code, claim_token FROM jobs "
                "WHERE debate_id=:debate_id AND turn_id=:turn_id"
            ),
            {"debate_id": debate_id, "turn_id": turn_id},
        ).one()
        assert job2[0] == "pending"
        assert job2[1] is None
        assert job2[2] is None
    database.dispose()


@pytest.mark.asyncio
async def test_draft_prepare_mock_tts_reaches_final_ready_with_audio(app_factory) -> None:
    _, database, settings, debate_id, turn_id = _seed_running_product_debate(app_factory)
    with database.session() as db:
        db.get(Debate, debate_id).status = "draft"
        turn = db.get(DebateTurn, turn_id)
        turn.generation_status = "pending"
        turn.preparation_stage = "generation"
        turn.publication_status = "unpublished"
        turn.speech = None
        turn.audio_file_id = None
        turn.safe_error_code = None
        db.execute(
            text(
                "UPDATE jobs SET state='pending', claim_token=NULL, safe_error_code=NULL "
                "WHERE turn_id=:turn_id"
            ),
            {"turn_id": turn_id},
        )
        repo = SqlPlaybackRepository()
        sql_debate = repo.get_debate(db, debate_id)
        repo.ensure_turn_jobs(db, sql_debate, repo.turns(db, sql_debate))
        db.commit()

    tasks = TaskManager()
    service = _product_service(
        database,
        settings,
        preparer=SqlTurnPreparer(settings=settings, llm=MockLLMProvider()),
        tts_provider=MockTTSProvider(),
        tasks=tasks,
    )
    try:
        with database.session() as db:
            await service.prepare_turn(db, debate_id, turn_id)
            db.commit()
        with database.session() as db:
            turn = db.get(DebateTurn, turn_id)
            assert turn.generation_status == "final_ready"
            assert turn.speech and turn.speech.strip()
            assert turn.audio_file_id is not None
            assert turn.safe_error_code is None
    finally:
        await tasks.close()
        database.dispose()


@pytest.mark.asyncio
async def test_draft_prepare_tts_unavailable_keeps_speech_and_code(app_factory) -> None:
    _, database, settings, debate_id, turn_id = _seed_running_product_debate(app_factory)
    with database.session() as db:
        db.get(Debate, debate_id).status = "draft"
        turn = db.get(DebateTurn, turn_id)
        turn.generation_status = "pending"
        turn.preparation_stage = "generation"
        turn.publication_status = "unpublished"
        turn.speech = None
        turn.audio_file_id = None
        turn.safe_error_code = None
        db.execute(
            text(
                "UPDATE jobs SET state='pending', claim_token=NULL, safe_error_code=NULL "
                "WHERE turn_id=:turn_id"
            ),
            {"turn_id": turn_id},
        )
        db.commit()

    tts = MockTTSProvider()
    tts.next_error = TTSProviderUnavailableError("provider down")
    tasks = TaskManager()
    service = _product_service(
        database,
        settings,
        preparer=SqlTurnPreparer(settings=settings, llm=MockLLMProvider()),
        tts_provider=tts,
        tasks=tasks,
    )
    try:
        with database.session() as db:
            await service.prepare_turn(db, debate_id, turn_id)
            db.commit()
        with database.session() as db:
            turn = db.get(DebateTurn, turn_id)
            assert turn.generation_status == "final_ready"
            assert turn.speech and turn.speech.strip()
            assert turn.audio_file_id is None
            assert turn.safe_error_code == "tts_provider_unavailable"
    finally:
        await tasks.close()
        database.dispose()


def test_ensure_turn_job_sqlite_keeps_insert_or_ignore() -> None:
    statements: list[str] = []

    class _Result:
        rowcount = 0

    class _FakeDB:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        def execute(self, statement, params=None):
            del params
            statements.append(str(statement))
            return _Result()

    debate = SimpleNamespace(id="debate-1", cancellation_generation=0)
    turn = SimpleNamespace(id="turn-1", turn_index=0)
    SqlPlaybackRepository._ensure_turn_job(_FakeDB(), debate, turn)
    assert statements and "INSERT OR IGNORE INTO jobs" in statements[0]
