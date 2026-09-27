"""Text completion still uses durable publication fences when TTS has no voice."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from app.modules.debates.playback.protocols import (
    MemoryPlaybackRepository,
    MemoryTurn,
    PreparedTurn,
)
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository
from sqlalchemy import text

from tests.test_sql_repository_segment_tts_fence import segment_retry_db as segment_retry_db


def _prepared(speech: str, structured: str) -> PreparedTurn:
    return PreparedTurn(
        speech=speech,
        structured=json.loads(structured),
        transcript_hash="t" * 64,
        predecessor_turn_ids=(),
        cutoff_turn_index=0,
        generation_attempt=1,
    )


def _write_ready(db, database, ids, prepared, **overrides):
    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    debate = repository.get_debate(db, ids["debate"])
    assert debate is not None
    turn = next(item for item in repository.turns(db, debate) if item.id == ids["turn"])
    arguments = {
        "generation": 4,
        "attempt": 1,
        "claim_token": "claim-segment-retry",
        "debate_status": "running",
        **overrides,
    }
    return repository.mark_turn_ready(db, turn, prepared, None, **arguments)


@pytest.mark.parametrize("debate_status", ["running", "draft"])
def test_no_voice_completes_text_and_job_without_creating_audio(segment_retry_db, debate_status):
    database, ids, speech, structured = segment_retry_db
    with database.session() as db:
        db.execute(
            text("UPDATE debates SET status=:status WHERE id=:id"),
            {"status": debate_status, "id": ids["debate"]},
        )
        audio_count = db.execute(text("SELECT count(*) FROM stored_files")).scalar_one()
        assert _write_ready(
            db, database, ids, _prepared(speech, structured), debate_status=debate_status
        )
    with database.session() as db:
        row = db.execute(
            text(
                "SELECT generation_status, preparation_stage, publication_status, speech, "
                "structured_json, audio_file_id, audio_duration_ms, safe_error_code "
                "FROM debate_turns WHERE id=:id"
            ),
            {"id": ids["turn"]},
        ).one()
        assert row[:4] == ("final_ready", "ready", "unpublished", speech)
        assert json.loads(row[4]) == json.loads(structured)
        assert row[5:] == (None, 0, "tts_voice_unavailable")
        assert db.execute(text("SELECT count(*) FROM stored_files")).scalar_one() == audio_count
        assert (
            db.execute(text("SELECT state FROM jobs WHERE id=:id"), {"id": ids["job"]}).scalar_one()
            == "completed"
        )
        repository = SqlPlaybackRepository(session_factory=database.session_factory)
        debate = repository.get_debate(db, ids["debate"])
        turn = repository.turns(db, debate)[0]
        assert repository.publish_turn(db, turn)


@pytest.mark.parametrize(
    "mismatch", ["claim", "generation", "status", "transcript", "prefix", "cutoff", "job-attempt"]
)
def test_no_audio_cannot_bypass_generation_or_claim_fences(segment_retry_db, mismatch):
    database, ids, speech, structured = segment_retry_db
    prepared = _prepared(speech, structured)
    overrides = {}
    with database.session() as db:
        if mismatch == "claim":
            overrides["claim_token"] = "stale-claim"
        elif mismatch == "generation":
            overrides["generation"] = 3
        elif mismatch == "status":
            overrides["debate_status"] = "draft"
        elif mismatch == "transcript":
            prepared = replace(prepared, transcript_hash="u" * 64)
        elif mismatch == "prefix":
            prepared = replace(prepared, predecessor_turn_ids=("other",))
        elif mismatch == "cutoff":
            prepared = replace(prepared, cutoff_turn_index=1)
        else:
            db.execute(text("UPDATE jobs SET attempt=2 WHERE id=:id"), {"id": ids["job"]})
        assert not _write_ready(db, database, ids, prepared, **overrides)
        assert (
            db.execute(
                text("SELECT generation_status FROM debate_turns WHERE id=:id"), {"id": ids["turn"]}
            ).scalar_one()
            == "running"
        )
        assert (
            db.execute(text("SELECT state FROM jobs WHERE id=:id"), {"id": ids["job"]}).scalar_one()
            == "running"
        )


def test_no_audio_publication_error_rolls_back_turn_and_completed_job(segment_retry_db):
    database, ids, speech, structured = segment_retry_db
    prepared = replace(
        _prepared(speech, structured),
        llm_publication=SimpleNamespace(operation_id="", turn_id=ids["turn"]),
    )
    with pytest.raises(RuntimeError, match="publication operation identity"):
        with database.session() as db:
            _write_ready(db, database, ids, prepared)
    with database.session() as db:
        row = db.execute(
            text("SELECT generation_status, audio_file_id FROM debate_turns WHERE id=:id"),
            {"id": ids["turn"]},
        ).one()
        assert row == ("running", ids["audio_file"])
        assert (
            db.execute(text("SELECT state FROM jobs WHERE id=:id"), {"id": ids["job"]}).scalar_one()
            == "running"
        )


def test_memory_repository_retains_text_with_no_audio():
    repository = MemoryPlaybackRepository()
    turn = MemoryTurn(generation_status="running", audio_file_id="old-file", audio_duration_ms=42)
    prepared = PreparedTurn(
        speech="Readable content", structured={"segments": [{"text": "Readable content"}]}
    )
    assert repository.mark_turn_ready(None, turn, prepared, None, generation=0, attempt=1)
    assert turn.speech == prepared.speech
    assert turn.structured == dict(prepared.structured)
    assert turn.generation_status == "final_ready"
    assert turn.audio_file_id is None
    assert turn.audio_duration_ms == 0
    assert turn.failed_code == "tts_voice_unavailable"


@pytest.mark.parametrize("mismatch", [None, "epoch", "version", "generation", "marker", "pending"])
def test_text_playback_claim_keeps_controller_and_completed_job_fences(segment_retry_db, mismatch):
    database, ids, speech, structured = segment_retry_db
    with database.session() as db:
        assert _write_ready(db, database, ids, _prepared(speech, structured))
        db.execute(
            text(
                "UPDATE playback_states SET status='ready', controller_epoch='epoch', "
                "control_version=1, pending_action=NULL, pending_ticket_hash=NULL, "
                "pending_media_command_id=NULL "
                "WHERE debate_id=:id"
            ),
            {"id": ids["debate"]},
        )
        if mismatch == "generation":
            db.execute(
                text("UPDATE debates SET cancellation_generation=5 WHERE id=:id"),
                {"id": ids["debate"]},
            )
        if mismatch == "marker":
            db.execute(
                text("UPDATE debate_turns SET safe_error_code=NULL WHERE id=:id"),
                {"id": ids["turn"]},
            )
        if mismatch == "pending":
            db.execute(
                text("UPDATE playback_states SET pending_action='start' WHERE debate_id=:id"),
                {"id": ids["debate"]},
            )
        repository = SqlPlaybackRepository(session_factory=database.session_factory)
        claimed = repository.claim_text_playback(
            db,
            debate_id=ids["debate"],
            turn_id=ids["turn"],
            expected_control_version=0 if mismatch == "version" else 1,
            controller_epoch="stale" if mismatch == "epoch" else "epoch",
        )
        assert claimed is (mismatch is None)
        assert db.execute(
            text("SELECT status FROM playback_states WHERE debate_id=:id"), {"id": ids["debate"]}
        ).scalar_one() == ("waiting_next" if mismatch is None else "ready")
