"""Preparing timeout exits spinner; Next failure must not advance turns."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.core.db import Database
from app.core.errors import PlatformError
from app.modules.debates.playback.protocols import (
    MemoryDebate,
    MemoryParticipant,
    MemoryPlaybackRepository,
    MemoryTurn,
)
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.sql_repository import (
    _PREPARATION_TIMEOUT_CODE,
    SqlPlaybackRepository,
)
from sqlalchemy import text

from tests.postgres_db import named_url
from tests.test_cleanup_debate_runtime import _add, _seed_runtime_graph, _uid


@pytest.fixture
def timeout_db(tmp_path: Path):
    database = Database(named_url(f"{tmp_path / 'maya.sqlite3'}"), tmp_path)
    database.upgrade_schema()
    ids = _seed_runtime_graph(database, tmp_path)
    ids["job"] = _uid(77)
    stale = datetime.now(UTC) - timedelta(seconds=120)
    with database.session() as db:
        db.execute(
            text(
                "UPDATE debates SET status='draft', revision=0, cancellation_generation=0 "
                "WHERE id=:debate_id"
            ),
            {"debate_id": ids["debate"]},
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
                "UPDATE debate_turns SET generation_status='pending', "
                "preparation_stage='generation', publication_status='unpublished', "
                "speech=NULL, safe_error_code=NULL, updated_at=:stale WHERE id=:turn_id"
            ),
            {"turn_id": ids["turn"], "stale": stale},
        )
        _add(
            db,
            "jobs",
            id=ids["job"],
            document_id=None,
            debate_id=ids["debate"],
            turn_id=ids["turn"],
            idempotency_key="timeout-turn-preparation",
            claim_token=None,
            cancellation_generation=0,
            insight_snapshot_id=None,
            report_revision_id=None,
            operation="debate_turn_prepare",
            state="pending",
            safe_error_code=None,
            attempt=0,
            created_at=stale,
            updated_at=stale,
        )
    try:
        yield database, ids
    finally:
        database.dispose()


def test_expire_stale_preparation_exits_preparing_idempotently(timeout_db) -> None:
    database, ids = timeout_db
    repository = SqlPlaybackRepository()
    with database.session() as db:
        first = repository.expire_stale_preparation(db, debate_id=ids["debate"])
        db.commit()
        assert first == 1
        row = db.execute(
            text("SELECT generation_status, safe_error_code FROM debate_turns WHERE id=:turn_id"),
            {"turn_id": ids["turn"]},
        ).one()
        assert row[0] == "failed"
        assert row[1] == _PREPARATION_TIMEOUT_CODE
        job = db.execute(
            text("SELECT state, safe_error_code FROM jobs WHERE id=:job_id"),
            {"job_id": ids["job"]},
        ).one()
        assert job[0] == "failed"
        assert job[1] == _PREPARATION_TIMEOUT_CODE
        second = repository.expire_stale_preparation(db, debate_id=ids["debate"])
        db.commit()
        assert second == 0


def test_expire_stale_preparation_without_prepare_job(timeout_db) -> None:
    """Stuck draft turn with no debate_turn_prepare job must still exit Preparing."""

    database, ids = timeout_db
    stale = datetime.now(UTC) - timedelta(seconds=120)
    with database.session() as db:
        db.execute(text("DELETE FROM jobs WHERE id=:job_id"), {"job_id": ids["job"]})
        db.execute(
            text(
                "UPDATE debate_turns SET generation_status='pending', "
                "preparation_stage='generation', publication_status='unpublished', "
                "speech=NULL, safe_error_code=NULL, updated_at=:stale WHERE id=:turn_id"
            ),
            {"turn_id": ids["turn"], "stale": stale},
        )
        db.commit()
        repository = SqlPlaybackRepository()
        first = repository.expire_stale_preparation(db, debate_id=ids["debate"])
        db.commit()
        assert first == 1
        row = db.execute(
            text(
                "SELECT generation_status, preparation_stage, safe_error_code "
                "FROM debate_turns WHERE id=:turn_id"
            ),
            {"turn_id": ids["turn"]},
        ).one()
        assert row[0] == "failed"
        assert row[1] == "failed"
        assert row[2] == _PREPARATION_TIMEOUT_CODE
        job = db.execute(
            text(
                "SELECT state, safe_error_code FROM jobs "
                "WHERE debate_id=:debate_id AND turn_id=:turn_id "
                "AND operation='debate_turn_prepare'"
            ),
            {"debate_id": ids["debate"], "turn_id": ids["turn"]},
        ).one()
        assert job[0] == "failed"
        assert job[1] == _PREPARATION_TIMEOUT_CODE
        second = repository.expire_stale_preparation(db, debate_id=ids["debate"])
        db.commit()
        assert second == 0


def test_expire_stale_preparation_fresh_turn_not_expired(timeout_db) -> None:
    database, ids = timeout_db
    fresh = datetime.now(UTC)
    with database.session() as db:
        db.execute(text("DELETE FROM jobs WHERE id=:job_id"), {"job_id": ids["job"]})
        db.execute(
            text(
                "UPDATE debate_turns SET generation_status='pending', "
                "preparation_stage='generation', publication_status='unpublished', "
                "speech=NULL, safe_error_code=NULL, updated_at=:fresh, created_at=:fresh "
                "WHERE id=:turn_id"
            ),
            {"turn_id": ids["turn"], "fresh": fresh},
        )
        db.commit()
        repository = SqlPlaybackRepository()
        assert repository.expire_stale_preparation(db, debate_id=ids["debate"]) == 0
        db.commit()
        row = db.execute(
            text("SELECT generation_status, safe_error_code FROM debate_turns WHERE id=:turn_id"),
            {"turn_id": ids["turn"]},
        ).one()
        assert row[0] == "pending"
        assert row[1] is None


def test_expire_stale_preparation_running_recoverable_without_job(timeout_db) -> None:
    database, ids = timeout_db
    stale = datetime.now(UTC) - timedelta(seconds=120)
    with database.session() as db:
        db.execute(text("DELETE FROM jobs WHERE id=:job_id"), {"job_id": ids["job"]})
        db.execute(
            text("UPDATE debates SET status='running' WHERE id=:debate_id"),
            {"debate_id": ids["debate"]},
        )
        db.execute(
            text(
                "UPDATE debate_turns SET generation_status='pending', "
                "preparation_stage='generation', publication_status='unpublished', "
                "speech=NULL, safe_error_code=NULL, updated_at=:stale WHERE id=:turn_id"
            ),
            {"turn_id": ids["turn"], "stale": stale},
        )
        db.commit()
        repository = SqlPlaybackRepository()
        first = repository.expire_stale_preparation(db, debate_id=ids["debate"])
        db.commit()
        assert first == 1
        row = db.execute(
            text(
                "SELECT generation_status, preparation_stage, safe_error_code "
                "FROM debate_turns WHERE id=:turn_id"
            ),
            {"turn_id": ids["turn"]},
        ).one()
        assert row[0] == "pending"
        assert row[1] == "generation"
        assert row[2] == _PREPARATION_TIMEOUT_CODE
        job = db.execute(
            text(
                "SELECT state, safe_error_code FROM jobs "
                "WHERE debate_id=:debate_id AND turn_id=:turn_id "
                "AND operation='debate_turn_prepare'"
            ),
            {"debate_id": ids["debate"], "turn_id": ids["turn"]},
        ).one()
        assert job[0] == "pending"
        assert job[1] == _PREPARATION_TIMEOUT_CODE
        second = repository.expire_stale_preparation(db, debate_id=ids["debate"])
        db.commit()
        assert second == 0


@pytest.mark.asyncio
async def test_next_not_ready_does_not_advance_turn_or_create_jobs() -> None:
    repository = MemoryPlaybackRepository()
    debate = MemoryDebate(
        status="running",
        participants=[MemoryParticipant(name="A"), MemoryParticipant(name="B")],
    )
    repository.add_debate(debate)
    turns = [
        MemoryTurn(
            participant_id=debate.participants[0].id,
            round_no=1,
            turn_index=0,
            generation_status="final_ready",
            publication_status="public",
            speech="A complete classroom speech for the current turn.",
            audio_file_id="audio-0",
        ),
        MemoryTurn(
            participant_id=debate.participants[1].id,
            round_no=1,
            turn_index=1,
            generation_status="pending",
            publication_status="unpublished",
            speech=None,
            audio_file_id=None,
        ),
    ]
    debate.turns = turns
    debate.playback.status = "waiting_next"
    debate.playback.current_turn_id = turns[0].id
    service = PlaybackService(repository)
    interrupted_before = list(repository.jobs_interrupted)

    with pytest.raises(PlatformError) as raised:
        await service.next(
            None,
            debate.id,
            expected_control_version=0,
            expected_current_turn_id=turns[0].id,
        )

    assert raised.value.code == "next_not_ready"
    assert debate.playback.current_turn_id == turns[0].id
    assert debate.playback.control_version == 0
    assert turns[1].generation_status == "pending"
    assert repository.jobs_interrupted == interrupted_before


@pytest.mark.asyncio
async def test_duplicate_next_while_not_ready_stays_idempotent() -> None:
    repository = MemoryPlaybackRepository()
    debate = MemoryDebate(
        status="running",
        participants=[MemoryParticipant(name="A"), MemoryParticipant(name="B")],
    )
    repository.add_debate(debate)
    current = MemoryTurn(
        participant_id=debate.participants[0].id,
        round_no=1,
        turn_index=0,
        generation_status="final_ready",
        publication_status="public",
        speech="A complete classroom speech for the current turn.",
        audio_file_id="audio-0",
    )
    successor = MemoryTurn(
        participant_id=debate.participants[1].id,
        round_no=1,
        turn_index=1,
        generation_status="running",
        publication_status="unpublished",
    )
    debate.turns = [current, successor]
    debate.playback.status = "waiting_next"
    debate.playback.current_turn_id = current.id
    service = PlaybackService(repository)

    for _ in range(3):
        with pytest.raises(PlatformError) as raised:
            await service.next(
                None,
                debate.id,
                expected_control_version=debate.playback.control_version,
                expected_current_turn_id=current.id,
            )
        assert raised.value.code == "next_not_ready"

    assert debate.playback.current_turn_id == current.id
    assert debate.playback.control_version == 0


def _segments_snapshot(rounds: int) -> str:
    import json

    return json.dumps({"turn_protocol": "segments_v2", "round_count": rounds})


def _clear_final_input(db, debate_id: str) -> None:
    # The seeded graph already froze Final; clear it to model a lesson that
    # has not reached Final yet.
    db.execute(
        text(
            "UPDATE debates SET final_input_json=NULL, final_input_hash=NULL, "
            "final_frozen_at=NULL WHERE id=:debate_id"
        ),
        {"debate_id": debate_id},
    )


@pytest.mark.parametrize("status", ["draft", "running"])
def test_expire_skips_segments_final_round_awaiting_final_input(timeout_db, status) -> None:
    """The final round waits for the teacher's Final; it is not a stuck worker.

    Production showed every warmed four-round draft as "Stalled": once
    rounds 1-3 were ready, the list read expired the round-4 head by age.
    """

    database, ids = timeout_db
    stale = datetime.now(UTC) - timedelta(seconds=600)
    with database.session() as db:
        db.execute(text("DELETE FROM jobs WHERE id=:job_id"), {"job_id": ids["job"]})
        _clear_final_input(db, ids["debate"])
        round_no = db.execute(
            text("SELECT round_no FROM debate_turns WHERE id=:turn_id"),
            {"turn_id": ids["turn"]},
        ).scalar_one()
        db.execute(
            text(
                "UPDATE debates SET status=:status, rule_snapshot_json=:snapshot "
                "WHERE id=:debate_id"
            ),
            {
                "status": status,
                "snapshot": _segments_snapshot(max(int(round_no), 2)),
                "debate_id": ids["debate"],
            },
        )
        db.execute(
            text(
                "UPDATE debate_turns SET round_no=:round_no, generation_status='pending', "
                "preparation_stage='generation', publication_status='unpublished', "
                "speech=NULL, safe_error_code=NULL, updated_at=:stale, created_at=:stale "
                "WHERE id=:turn_id"
            ),
            {"turn_id": ids["turn"], "stale": stale, "round_no": max(int(round_no), 2)},
        )
        db.commit()
        repository = SqlPlaybackRepository()
        assert repository.expire_stale_preparation(db, debate_id=ids["debate"]) == 0
        db.commit()
        row = db.execute(
            text("SELECT generation_status, safe_error_code FROM debate_turns WHERE id=:turn_id"),
            {"turn_id": ids["turn"]},
        ).one()
        assert row[0] == "pending"
        assert row[1] is None
        assert (
            db.execute(
                text(
                    "SELECT COUNT(*) FROM jobs WHERE turn_id=:turn_id "
                    "AND operation='debate_turn_prepare'"
                ),
                {"turn_id": ids["turn"]},
            ).scalar_one()
            == 0
        )

        # Once Final is frozen the round is meant to prepare, so a stuck
        # final turn expires exactly like any other.
        db.execute(
            text("UPDATE debates SET final_input_json='{}' WHERE id=:debate_id"),
            {"debate_id": ids["debate"]},
        )
        db.commit()
        assert repository.expire_stale_preparation(db, debate_id=ids["debate"]) == 1
        db.commit()
        code = db.execute(
            text("SELECT safe_error_code FROM debate_turns WHERE id=:turn_id"),
            {"turn_id": ids["turn"]},
        ).scalar_one()
        assert code == _PREPARATION_TIMEOUT_CODE


def test_expire_still_times_out_segments_earlier_round(timeout_db) -> None:
    database, ids = timeout_db
    stale = datetime.now(UTC) - timedelta(seconds=600)
    with database.session() as db:
        db.execute(text("DELETE FROM jobs WHERE id=:job_id"), {"job_id": ids["job"]})
        _clear_final_input(db, ids["debate"])
        db.execute(
            text("UPDATE debates SET rule_snapshot_json=:snapshot WHERE id=:debate_id"),
            {"snapshot": _segments_snapshot(4), "debate_id": ids["debate"]},
        )
        db.execute(
            text(
                "UPDATE debate_turns SET round_no=1, generation_status='pending', "
                "preparation_stage='generation', publication_status='unpublished', "
                "speech=NULL, safe_error_code=NULL, updated_at=:stale WHERE id=:turn_id"
            ),
            {"turn_id": ids["turn"], "stale": stale},
        )
        db.commit()
        repository = SqlPlaybackRepository()
        assert repository.expire_stale_preparation(db, debate_id=ids["debate"]) == 1
