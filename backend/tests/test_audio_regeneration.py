"""SQL product checks for cached segment audio regeneration."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from app.core.db import Database
from app.modules.debates import cleanup
from app.modules.debates.playback.audio import AudioStore
from app.modules.debates.playback.audio_regeneration import (
    AUDIO_REGENERATION_OPERATION,
    AudioRegenerationService,
    SqlAudioRegenerationRepository,
)
from app.modules.debates.playback.protocols import ResolvedTurnVoice
from app.providers.tts import MockTTSProvider, TTSHTTPRejectedError
from sqlalchemy import text

from tests.test_cleanup_debate_runtime import _seed_runtime_graph
from tests.test_debate_cleanup import _make_final_ready


class _Tasks:
    async def cancel_debate(self, _debate_id: str) -> None:
        return None


class _Tickets:
    def revoke_debate(self, _debate_id: str) -> None:
        return None


class _LanguageMock(MockTTSProvider):
    def __init__(self) -> None:
        super().__init__()
        self.languages: list[str] = []

    def synthesize(self, text: str, external_voice_id: str, *, language: str = "en"):
        self.languages.append(language)
        return super().synthesize(text, external_voice_id, language=language)


@pytest.fixture
def retained_turn(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'maya.sqlite3'}", tmp_path)
    database.upgrade_schema()
    ids = _seed_runtime_graph(database, tmp_path)
    speech, structured = _make_final_ready(database, ids)
    structured_value = json.loads(structured)
    for segment in structured_value["segments"]:
        segment["reply_to"] = None
    structured = json.dumps(structured_value, separators=(",", ":"))
    with database.session() as db:
        db.execute(
            text("UPDATE debate_turns SET structured_json=:structured WHERE id=:turn_id"),
            {"structured": structured, "turn_id": ids["turn"]},
        )
    try:
        yield database, ids, tmp_path, speech, structured
    finally:
        database.dispose()


def _delete_voice(database: Database, ids: dict[str, str], data_root: Path):
    with database.session() as db:
        return asyncio.run(
            cleanup.delete_voice(
                db,
                actor_user_id=ids["teacher"],
                debate_id=ids["debate"],
                expected_revision=1,
                expected_control_version=1,
                data_root=data_root,
                task_manager=_Tasks(),
                ticket_store=_Tickets(),
                report_task_manager=_Tasks(),
                idempotency_key="delete-voice-audio-regeneration",
            )
        )


def test_delete_voice_then_regenerates_cached_segments_without_llm(retained_turn):
    database, ids, data_root, speech, structured = retained_turn
    deleted = _delete_voice(database, ids, data_root)
    provider = _LanguageMock()
    session = database.session_factory()
    try:
        result = AudioRegenerationService(
            session,
            audio_store=AudioStore(data_root, tts_provider=provider),
            voice_resolver=lambda _cached: ResolvedTurnVoice("mock_sentinel", None, "mock"),
        ).regenerate_turn_audio(ids["debate"], ids["turn"], deleted.revision, "regen-voice-0001")
    finally:
        session.close()

    assert result.status == "completed"
    assert result.audio_ready
    assert provider.synthesize_calls == 1
    assert provider.languages == ["en"]
    with database.session() as db:
        turn = db.execute(
            text(
                "SELECT speech, structured_json, publication_status, audio_file_id "
                "FROM debate_turns WHERE id=:turn_id"
            ),
            {"turn_id": ids["turn"]},
        ).one()
        assert turn[0] == speech
        assert turn[1] == structured
        assert turn[2] == "public"
        assert turn[3] is not None
        job = db.execute(
            text("SELECT state, operation FROM jobs WHERE id=:operation_id"),
            {"operation_id": result.operation_id},
        ).one()
        assert job == ("completed", AUDIO_REGENERATION_OPERATION)
        journal = db.execute(
            text("SELECT state FROM file_operations WHERE request_id=:operation_id"),
            {"operation_id": result.operation_id},
        ).scalar_one()
        assert journal == "committed"


def test_tts_failure_retains_cached_text_and_does_not_fail_debate(retained_turn):
    database, ids, data_root, speech, structured = retained_turn
    deleted = _delete_voice(database, ids, data_root)
    provider = MockTTSProvider()
    provider.next_error = TTSHTTPRejectedError()
    session = database.session_factory()
    try:
        result = AudioRegenerationService(
            session,
            audio_store=AudioStore(data_root, tts_provider=provider),
            voice_resolver=lambda _cached: ResolvedTurnVoice("mock_sentinel", None, "mock"),
        ).regenerate_turn_audio(ids["debate"], ids["turn"], deleted.revision, "regen-fail-0001")
    finally:
        session.close()

    assert result.status == "failed"
    assert result.safe_error_code == "tts_http_rejected"
    assert provider.synthesize_calls == 0
    assert not list((data_root / "staging" / "debate-turn-tts").rglob("*.wav"))
    with database.session() as db:
        row = db.execute(
            text(
                "SELECT d.status, t.speech, t.structured_json, t.audio_file_id, "
                "j.state, j.safe_error_code, f.state FROM debates d "
                "JOIN debate_turns t ON t.debate_id=d.id "
                "JOIN jobs j ON j.turn_id=t.id AND j.operation=:operation "
                "JOIN file_operations f ON f.request_id=j.id WHERE t.id=:turn_id"
            ),
            {"operation": AUDIO_REGENERATION_OPERATION, "turn_id": ids["turn"]},
        ).one()
        assert row == (
            "running",
            speech,
            structured,
            None,
            "failed",
            "tts_http_rejected",
            "recovered",
        )


def test_revision_loss_cleans_only_this_operation_stage(retained_turn):
    database, ids, data_root, _speech, _structured = retained_turn
    deleted = _delete_voice(database, ids, data_root)
    provider = MockTTSProvider()
    sibling_store = AudioStore(data_root, tts_provider=provider)
    sibling = sibling_store.stage_synthesis(
        course_id=ids["course"],
        debate_id=ids["debate"],
        turn_id=ids["turn"],
        speech="sibling stage",
        voice_token="mock",
        operation_id="00000000-0000-4000-8000-000000000099",
    )
    session = database.session_factory()

    def cancel(claim) -> None:
        session.execute(
            text("UPDATE debates SET revision=revision+1 WHERE id=:debate_id"),
            {"debate_id": claim.debate_id},
        )
        session.commit()

    try:
        result = AudioRegenerationService(
            session,
            audio_store=AudioStore(data_root, tts_provider=provider),
            voice_resolver=lambda _cached: ResolvedTurnVoice("mock_sentinel", None, "mock"),
            before_promotion=cancel,
        ).regenerate_turn_audio(ids["debate"], ids["turn"], deleted.revision, "regen-cas-0001")
    finally:
        session.close()

    assert result.status == "stale"
    with database.session() as db:
        own_stage = db.execute(
            text("SELECT source_relative_path FROM file_operations WHERE request_id=:operation_id"),
            {"operation_id": result.operation_id},
        ).scalar_one()
    assert not (data_root / str(own_stage)).exists()
    # The sibling was deliberately created before constructing the service;
    # the service must only remove its own operation path.
    assert (data_root / sibling.relative_path).exists()
    assert not list(
        (data_root / "courses" / ids["course"] / "current-debate-audio" / ids["debate"]).glob(
            "*.wav"
        )
    )


def test_regeneration_uses_debate_language(retained_turn):
    database, ids, data_root, _speech, _structured = retained_turn
    with database.session() as db:
        db.execute(
            text("UPDATE debates SET output_language='zh' WHERE id=:debate_id"),
            {"debate_id": ids["debate"]},
        )
    deleted = _delete_voice(database, ids, data_root)
    provider = _LanguageMock()
    session = database.session_factory()
    try:
        result = AudioRegenerationService(
            session,
            audio_store=AudioStore(data_root, tts_provider=provider),
            voice_resolver=lambda _cached: ResolvedTurnVoice("mock_sentinel", None, "mock"),
        ).regenerate_turn_audio(ids["debate"], ids["turn"], deleted.revision, "regen-zh-0001")
    finally:
        session.close()
    assert result.status == "completed"
    assert provider.languages == ["zh"]


def test_startup_promotes_durable_stage_without_another_tts_call(retained_turn):
    database, ids, data_root, _speech, _structured = retained_turn
    deleted = _delete_voice(database, ids, data_root)
    provider = MockTTSProvider()
    repository = SqlAudioRegenerationRepository()
    session = database.session_factory()
    try:
        cached = repository.load_cached_turn(session, ids["debate"], ids["turn"])
        claim = repository.claim(
            session,
            cached,
            expected_revision=deleted.revision,
            idempotency_key="regen-restart-0001",
        )
        assert claim is not None
        store = AudioStore(data_root, tts_provider=provider)
        staged = store.stage_synthesis(
            course_id=ids["course"],
            debate_id=ids["debate"],
            turn_id=ids["turn"],
            speech=cached.speech,
            voice_token="mock",
            operation_id=claim.file_operation_id,
        )
        assert repository.mark_staged(session, claim, staged)
    finally:
        session.close()

    class _NoCall(MockTTSProvider):
        def synthesize(self, *args, **kwargs):
            raise AssertionError("startup recovery must not call TTS")

    restart_session = database.session_factory()
    try:
        results = AudioRegenerationService(
            restart_session,
            audio_store=AudioStore(data_root, tts_provider=_NoCall()),
            voice_resolver=lambda _cached: ResolvedTurnVoice("mock_sentinel", None, "mock"),
            repository=repository,
        ).resume_startup()
    finally:
        restart_session.close()

    assert [item.status for item in results] == ["completed"]
    with database.session() as db:
        assert (
            db.execute(
                text("SELECT state FROM jobs WHERE id=:id"), {"id": claim.operation_id}
            ).scalar_one()
            == "completed"
        )
        assert (
            db.execute(
                text("SELECT state FROM file_operations WHERE id=:id"),
                {"id": claim.file_operation_id},
            ).scalar_one()
            == "committed"
        )


def test_startup_recovers_after_filesystem_promotion_before_journal_update(retained_turn):
    database, ids, data_root, _speech, _structured = retained_turn
    deleted = _delete_voice(database, ids, data_root)
    provider = MockTTSProvider()
    repository = SqlAudioRegenerationRepository()
    session = database.session_factory()
    try:
        cached = repository.load_cached_turn(session, ids["debate"], ids["turn"])
        claim = repository.claim(
            session,
            cached,
            expected_revision=deleted.revision,
            idempotency_key="regen-promoted-restart-0001",
        )
        assert claim is not None
        store = AudioStore(data_root, tts_provider=provider)
        staged = store.stage_synthesis(
            course_id=ids["course"],
            debate_id=ids["debate"],
            turn_id=ids["turn"],
            speech=cached.speech,
            voice_token="mock",
            operation_id=claim.file_operation_id,
        )
        assert repository.mark_staged(session, claim, staged)
        store.promote_staged_audio(staged)
    finally:
        session.close()

    restart_session = database.session_factory()
    try:
        results = AudioRegenerationService(
            restart_session,
            audio_store=AudioStore(data_root, tts_provider=MockTTSProvider()),
            voice_resolver=lambda _cached: ResolvedTurnVoice("mock_sentinel", None, "mock"),
            repository=repository,
        ).resume_startup()
    finally:
        restart_session.close()

    assert [item.status for item in results] == ["completed"]
    with database.session() as db:
        assert (
            db.execute(
                text("SELECT state FROM jobs WHERE id=:id"), {"id": claim.operation_id}
            ).scalar_one()
            == "completed"
        )
        assert (
            db.execute(
                text("SELECT state FROM file_operations WHERE id=:id"),
                {"id": claim.file_operation_id},
            ).scalar_one()
            == "committed"
        )


def test_startup_discards_only_exact_interrupted_preparation_stage(retained_turn):
    from uuid import uuid4

    from app.modules.debates.playback.audio_regeneration import discard_unjournaled_audio_stages

    database, ids, data_root, speech, _ = retained_turn
    store = AudioStore(data_root)
    claim = str(uuid4())
    with database.session() as db:
        course_id = db.execute(
            text("SELECT course_id FROM debates WHERE id=:id"), {"id": ids["debate"]}
        ).scalar_one()
        from datetime import UTC, datetime

        from app.core.models import Job

        now = datetime.now(UTC)
        db.add(
            Job(
                id=str(uuid4()),
                debate_id=ids["debate"],
                turn_id=ids["turn"],
                operation="debate_turn_prepare",
                state="running",
                attempt=1,
                claim_token=claim,
                created_at=now,
                updated_at=now,
            )
        )
    own = store.stage_synthesis(
        course_id=course_id,
        debate_id=ids["debate"],
        turn_id=ids["turn"],
        speech=speech,
        voice_token="mock",
        operation_id=claim,
    )
    unrelated = store.stage_synthesis(
        course_id=course_id,
        debate_id=ids["debate"],
        turn_id=ids["turn"],
        speech=speech,
        voice_token="mock",
    )
    with database.session() as db:
        assert discard_unjournaled_audio_stages(db, store) == 1
    assert not (data_root / own.relative_path).exists()
    assert (data_root / unrelated.relative_path).is_file()
