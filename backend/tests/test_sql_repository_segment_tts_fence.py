"""Focused SQL fences for retrying cached segment text after TTS failure."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.core.db import Database
from app.modules.debates.playback.protocols import PreparedGenerationFence
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository
from sqlalchemy import text

from tests.test_cleanup_debate_runtime import _seed_runtime_graph, _uid
from tests.test_debate_cleanup import _make_final_ready


@pytest.fixture
def segment_retry_db(tmp_path: Path):
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
                "UPDATE debate_turns SET generation_status='running', "
                "preparation_stage='generation', publication_status='unpublished', "
                "speech=:speech, structured_json=:structured, transcript_hash=:transcript, "
                "predecessor_turn_ids_json='[]', cutoff_turn_index=0, word_count=80 "
                "WHERE id=:turn_id"
            ),
            {
                "speech": speech,
                "structured": structured,
                "transcript": "t" * 64,
                "turn_id": ids["turn"],
            },
        )
        db.execute(
            text(
                "UPDATE jobs SET idempotency_key=:key, claim_token=:claim, "
                "cancellation_generation=4, operation='debate_turn_prepare', state='running', "
                "safe_error_code=NULL WHERE id=:job_id"
            ),
            {
                "key": f"{ids['debate']}:{ids['turn']}",
                "claim": "claim-segment-retry",
                "job_id": ids["job"],
            },
        )
    try:
        yield database, ids, speech, structured
    finally:
        database.dispose()


def _rows(database: Database, ids: dict[str, str]):
    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    session = database.session_factory()
    debate = repository.get_debate(session, ids["debate"])
    assert debate is not None
    turn = next(item for item in repository.turns(session, debate) if item.id == ids["turn"])
    return repository, session, debate, turn


def test_tts_defer_preserves_v2_text_fence_and_matching_retry_claim(segment_retry_db):
    database, ids, speech, structured = segment_retry_db
    repository, session, debate, turn = _rows(database, ids)
    try:
        fence = PreparedGenerationFence((), "t" * 64, 0, 1)
        assert repository.defer_turn_job(
            session, debate, turn, "claim-segment-retry", "tts_timeout"
        )
        saved = session.execute(
            text(
                "SELECT generation_status, preparation_stage, speech, structured_json, "
                "transcript_hash FROM debate_turns WHERE id=:turn_id"
            ),
            {"turn_id": ids["turn"]},
        ).one()
        assert saved == ("pending", "generation", speech, structured, "t" * 64)
        assert session.execute(
            text("SELECT state, safe_error_code FROM jobs WHERE id=:job_id"),
            {"job_id": ids["job"]},
        ).one() == ("pending", "tts_timeout")

        debate = repository.get_debate(session, ids["debate"])
        assert debate is not None
        turn = next(item for item in repository.turns(session, debate) if item.id == ids["turn"])
        assert repository.claim_turn_job(session, debate, turn, cancellation_generation=4) is None
        assert repository.authorize_pending_tts_retry(session, debate, turn, code="tts_timeout")
        claim = repository.claim_turn_job(session, debate, turn, cancellation_generation=4)
        assert claim is not None
        turn = next(item for item in repository.turns(session, debate) if item.id == ids["turn"])
        assert repository.mark_turn_running(
            session,
            turn,
            cancellation_generation=4,
            claim_token=claim,
            fence=fence,
        )
        mismatch = PreparedGenerationFence((), "u" * 64, 0, 1)
        assert repository.defer_turn_job(session, debate, turn, claim, "tts_timeout")
        turn = next(item for item in repository.turns(session, debate) if item.id == ids["turn"])
        assert repository.claim_turn_job(session, debate, turn, cancellation_generation=4) is None
        assert repository.authorize_pending_tts_retry(session, debate, turn, code="tts_timeout")
        retry_claim = repository.claim_turn_job(session, debate, turn, cancellation_generation=4)
        assert retry_claim is not None
        turn = next(item for item in repository.turns(session, debate) if item.id == ids["turn"])
        assert not repository.mark_turn_running(
            session,
            turn,
            cancellation_generation=4,
            claim_token=retry_claim,
            fence=mismatch,
        )
    finally:
        session.close()


def test_startup_keeps_valid_segment_tts_retry_pending(segment_retry_db):
    database, ids, speech, structured = segment_retry_db
    with database.session() as db:
        db.execute(
            text(
                "UPDATE jobs SET state='pending', claim_token=NULL, safe_error_code='tts_timeout' "
                "WHERE id=:job_id"
            ),
            {"job_id": ids["job"]},
        )
        repository = SqlPlaybackRepository(session_factory=database.session_factory)
        assert repository.recover_startup(db) == ()
    with database.session() as db:
        assert db.execute(
            text(
                "SELECT generation_status, preparation_stage, speech, structured_json, "
                "transcript_hash FROM debate_turns WHERE id=:turn_id"
            ),
            {"turn_id": ids["turn"]},
        ).one() == ("pending", "generation", speech, structured, "t" * 64)
        assert db.execute(
            text("SELECT state, safe_error_code FROM jobs WHERE id=:job_id"),
            {"job_id": ids["job"]},
        ).one() == ("pending", "tts_timeout")
        debate = repository.get_debate(db, ids["debate"])
        turn = next(item for item in repository.turns(db, debate) if item.id == ids["turn"])
        assert repository.claim_turn_job(db, debate, turn, cancellation_generation=4) is None


def test_audio_promotion_fence_holds_exact_running_claim(segment_retry_db):
    database, ids, _speech, _structured = segment_retry_db
    repository, session, debate, turn = _rows(database, ids)
    try:
        assert repository.fence_audio_promotion(
            session,
            debate,
            turn,
            "claim-segment-retry",
            4,
        )
        assert not repository.fence_audio_promotion(
            session,
            debate,
            turn,
            "wrong-claim",
            4,
        )
    finally:
        session.rollback()
        session.close()
