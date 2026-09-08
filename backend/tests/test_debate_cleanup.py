"""Focused online Debate cleanup tests on a disposable migrated database."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.core.db import Database
from app.core.errors import PlatformError
from app.modules.debates import cleanup
from app.modules.debates import models as _debate_models
from app.modules.debates.models import Debate, DebateTurn, PlaybackState
from sqlalchemy import select, text, update

from tests.test_cleanup_debate_runtime import _add, _hash, _seed_runtime_graph, _uid

del _debate_models


@pytest.fixture
def migrated_database(tmp_path: Path):
    database_path = tmp_path / "maya.sqlite3"
    database = Database(f"sqlite:///{database_path}", tmp_path)
    database.upgrade_schema()
    ids = _seed_runtime_graph(database, tmp_path)
    try:
        yield database, ids, tmp_path
    finally:
        database.dispose()


class _TaskRecorder:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    async def cancel_debate(self, debate_id: str) -> None:
        self.cancelled.append(debate_id)


class _TicketRecorder:
    def __init__(self) -> None:
        self.revoked: list[str] = []

    def revoke_debate(self, debate_id: str) -> None:
        self.revoked.append(debate_id)


def _make_final_ready(db: Database, ids: dict[str, str]) -> tuple[str, str]:
    speech = " ".join(f"validated-{index}" for index in range(80))
    structured = json.dumps(
        {"schema_version": "segment_turn_v2", "segments": [{"text": speech, "source_ids": []}]},
        separators=(",", ":"),
    )
    transcript_hash = _hash("t")
    now = datetime.now(UTC)
    with db.session() as session:
        session.execute(
            update(Debate)
            .where(Debate.id == ids["debate"])
            .values(status="running", revision=1, cancellation_generation=4)
        )
        session.execute(
            update(DebateTurn)
            .where(DebateTurn.id == ids["turn"])
            .values(
                generation_status="final_ready",
                publication_status="public",
                preparation_stage="ready",
                speech=speech,
                structured_json=structured,
                transcript_hash=transcript_hash,
                cutoff_turn_index=0,
                retrieval_status="matched",
                grounding_mode="rag_grounded",
                retrieval_receipts_json="[]",
                evidence_trace_json="[]",
                word_count=80,
                updated_at=now,
                public_at=now,
            )
        )
        session.execute(
            update(PlaybackState)
            .where(PlaybackState.debate_id == ids["debate"])
            .values(
                status="playing",
                mode="live",
                current_turn_id=ids["turn"],
                control_version=1,
            )
        )
        session.execute(
            text("UPDATE jobs SET state='running', safe_error_code=NULL WHERE id=:job_id"),
            {"job_id": ids["job_report"]},
        )
        _add(
            session,
            "jobs",
            id=_uid(77),
            document_id=None,
            debate_id=ids["debate"],
            turn_id=ids["turn"],
            idempotency_key="cleanup-turn-preparation",
            claim_token="cleanup-claim",
            cancellation_generation=4,
            insight_snapshot_id=None,
            report_revision_id=None,
            operation="debate_turn_prepare",
            state="running",
            safe_error_code=None,
            attempt=1,
            created_at=now,
            updated_at=now,
        )
    return speech, structured


def test_delete_voice_preserves_validated_semantics_and_uses_media_fence(
    migrated_database,
):
    database, ids, data_root = migrated_database
    speech, structured = _make_final_ready(database, ids)
    final_input_hash = _hash("2")
    task_manager = _TaskRecorder()
    ticket_store = _TicketRecorder()
    report_task_manager = _TaskRecorder()

    with database.session() as session:
        debate_before = session.get(Debate, ids["debate"])
        assert debate_before is not None
        debate_before_hash = debate_before.final_input_hash
        result = asyncio.run(
            cleanup.delete_voice(
                session,
                actor_user_id=ids["teacher"],
                debate_id=ids["debate"],
                expected_revision=1,
                expected_control_version=1,
                data_root=data_root,
                task_manager=task_manager,
                ticket_store=ticket_store,
                report_task_manager=report_task_manager,
            )
        )

    assert result.revision == 2
    assert result.control_version == 2
    assert result.cancellation_generation == 4
    assert result.regenerable_turn_ids == (ids["turn"],)
    assert result.retained_public_turn_count == 1
    assert task_manager.cancelled == [ids["debate"]]
    assert ticket_store.revoked == [ids["debate"]]
    assert report_task_manager.cancelled == []
    assert not (
        data_root / "courses" / ids["course"] / "current-debate-audio" / ids["debate"]
    ).exists()
    assert not any((data_root / "staging" / "audio-swap").rglob("*.wav"))

    with database.session() as session:
        debate = session.get(Debate, ids["debate"])
        turn = session.get(DebateTurn, ids["turn"])
        playback = session.scalar(
            select(PlaybackState).where(PlaybackState.debate_id == ids["debate"])
        )
        assert debate is not None and turn is not None and playback is not None
        assert debate.final_input_hash == debate_before_hash == final_input_hash
        assert debate.final_input_json == '{"round": 3}'
        assert debate.cancellation_generation == 4
        assert debate.status == "running"
        assert turn.speech == speech
        assert turn.structured_json == structured
        assert turn.publication_status == "public"
        assert turn.generation_status == "final_ready"
        assert turn.transcript_hash == _hash("t")
        assert turn.audio_file_id is None
        assert turn.audio_duration_ms is None
        assert turn.actual_tts_voice_kind is None
        assert playback.status == "paused"
        assert playback.current_turn_id == ids["turn"]
        assert playback.control_version == 2
        assert (
            session.execute(
                text("SELECT count(*) FROM turn_sources WHERE turn_id=:id"), {"id": ids["turn"]}
            ).scalar_one()
            == 1
        )
        assert (
            session.execute(
                text("SELECT count(*) FROM civilization_reports WHERE debate_id=:id"),
                {"id": ids["debate"]},
            ).scalar_one()
            == 1
        )
        assert (
            session.execute(
                text("SELECT count(*) FROM jobs WHERE debate_id=:id AND state='interrupted'"),
                {"id": ids["debate"]},
            ).scalar_one()
            == 1
        )
        assert (
            session.execute(
                text("SELECT state FROM jobs WHERE id=:id"),
                {"id": ids["job_report"]},
            ).scalar_one()
            == "running"
        )
        assert (
            session.execute(
                text("SELECT count(*) FROM stored_files WHERE id=:id"),
                {"id": ids["audio_file"]},
            ).scalar_one()
            == 0
        )
        assert (
            session.execute(
                text("SELECT count(*) FROM stored_files WHERE id=:id"),
                {"id": ids["source_file"]},
            ).scalar_one()
            == 1
        )


def test_delete_voice_requires_teacher_and_both_fences_without_mutation(migrated_database):
    database, ids, data_root = migrated_database
    with database.session() as session:
        with pytest.raises(PlatformError) as unauthorized:
            asyncio.run(
                cleanup.delete_voice(
                    session,
                    actor_user_id=ids["user"],
                    debate_id=ids["debate"],
                    expected_revision=1,
                    expected_control_version=1,
                    data_root=data_root,
                )
            )
        assert unauthorized.value.code == "forbidden"

    with database.session() as session:
        with pytest.raises(PlatformError) as stale:
            asyncio.run(
                cleanup.delete_voice(
                    session,
                    actor_user_id=ids["teacher"],
                    debate_id=ids["debate"],
                    expected_revision=0,
                    expected_control_version=1,
                    data_root=data_root,
                )
            )
        assert stale.value.code == "stale_revision"

    with database.session() as session:
        debate = session.get(Debate, ids["debate"])
        playback = session.scalar(
            select(PlaybackState).where(PlaybackState.debate_id == ids["debate"])
        )
        assert debate is not None and playback is not None
        assert debate.revision == 1
        assert playback.control_version == 1
        assert (
            data_root / "courses" / ids["course"] / "current-debate-audio" / ids["debate"]
        ).exists()


def test_cleanup_idempotency_replays_after_commit_and_rejects_changed_payload(
    migrated_database,
):
    database, ids, data_root = migrated_database
    _make_final_ready(database, ids)
    key = "cleanup-voice-replay-001"
    with database.session() as session:
        first = asyncio.run(
            cleanup.delete_voice(
                session,
                actor_user_id=ids["teacher"],
                debate_id=ids["debate"],
                expected_revision=1,
                expected_control_version=1,
                data_root=data_root,
                idempotency_key=key,
            )
        )
    assert first.deleted_file_count >= 1
    assert first.pending_file_count == 0
    with database.session() as session:
        replay = asyncio.run(
            cleanup.delete_voice(
                session,
                actor_user_id=ids["teacher"],
                debate_id=ids["debate"],
                expected_revision=1,
                expected_control_version=1,
                data_root=data_root,
                idempotency_key=key,
            )
        )
        assert replay == first
        with pytest.raises(PlatformError) as changed:
            asyncio.run(
                cleanup.delete_voice(
                    session,
                    actor_user_id=ids["teacher"],
                    debate_id=ids["debate"],
                    expected_revision=2,
                    expected_control_version=1,
                    data_root=data_root,
                    idempotency_key=key,
                )
            )
        assert changed.value.code == "idempotency_conflict"

    with database.session() as session:
        records = session.execute(
            text(
                "SELECT operation, state FROM idempotency_records "
                "WHERE actor_user_id=:actor AND key=:key"
            ),
            {"actor": ids["teacher"], "key": key},
        ).all()
        assert records == [("deleteVoice", "completed")]


def test_delete_all_idempotency_replays_after_debate_row_is_gone(migrated_database):
    database, ids, data_root = migrated_database
    key = "cleanup-all-replay-001"
    with database.session() as session:
        first = asyncio.run(
            cleanup.delete_all(
                session,
                actor_user_id=ids["teacher"],
                debate_id=ids["debate"],
                expected_revision=1,
                expected_control_version=1,
                data_root=data_root,
                idempotency_key=key,
            )
        )
    assert first.deleted_file_count >= 1
    assert first.pending_file_count == 0
    with database.session() as session:
        replay = asyncio.run(
            cleanup.delete_all(
                session,
                actor_user_id=ids["teacher"],
                debate_id=ids["debate"],
                expected_revision=1,
                expected_control_version=1,
                data_root=data_root,
                idempotency_key=key,
            )
        )
    assert replay == first
    with database.session() as session:
        row = session.execute(
            text(
                "SELECT state, response_json FROM idempotency_records "
                "WHERE actor_user_id=:actor AND operation='deleteAll' AND key=:key"
            ),
            {"actor": ids["teacher"], "key": key},
        ).first()
        assert row is not None and row[0] == "completed"
        assert json.loads(row[1]) == first.to_public_dict()


def test_committed_quarantine_resumes_after_process_crash_before_file_finish(
    migrated_database, monkeypatch
):
    database, ids, data_root = migrated_database
    _make_final_ready(database, ids)
    key = "cleanup-crash-recovery-001"

    def crash_before_finish(_quarantine):
        raise RuntimeError("simulated post-commit crash")

    monkeypatch.setattr(cleanup, "_finish_files", crash_before_finish)
    with database.session() as session:
        with pytest.raises(RuntimeError, match="simulated post-commit crash"):
            asyncio.run(
                cleanup.delete_voice(
                    session,
                    actor_user_id=ids["teacher"],
                    debate_id=ids["debate"],
                    expected_revision=1,
                    expected_control_version=1,
                    data_root=data_root,
                    idempotency_key=key,
                )
            )

    with database.session() as session:
        journal = session.execute(
            text(
                "SELECT state, staging_relative_path, target_relative_path "
                "FROM file_operations WHERE operation_type=:operation"
            ),
            {"operation": cleanup._CLEANUP_VOICE_OPERATION},
        ).first()
        assert journal is not None and journal[0] == "cleanup_required"
        assert journal[1].startswith(".maya-debate-delete-")
        assert journal[2].startswith(journal[1] + "/")

    monkeypatch.undo()
    with database.session() as session:
        resumed = asyncio.run(
            cleanup.delete_voice(
                session,
                actor_user_id=ids["teacher"],
                debate_id=ids["debate"],
                expected_revision=1,
                expected_control_version=1,
                data_root=data_root,
                idempotency_key=key,
            )
        )
    assert resumed.cleanup_status == "complete"
    assert resumed.deleted_file_count >= 1
    with database.session() as session:
        assert (
            session.execute(
                text(
                    "SELECT count(*) FROM file_operations "
                    "WHERE operation_type=:operation AND state='cleanup_required'"
                ),
                {"operation": cleanup._CLEANUP_VOICE_OPERATION},
            ).scalar_one()
            == 0
        )
        assert (
            session.execute(
                text(
                    "SELECT count(*) FROM file_operations "
                    "WHERE operation_type=:operation AND state='recovered'"
                ),
                {"operation": cleanup._CLEANUP_VOICE_OPERATION},
            ).scalar_one()
            >= 1
        )
        assert (
            json.loads(
                session.execute(
                    text(
                        "SELECT response_json FROM idempotency_records "
                        "WHERE operation='deleteVoice' AND key=:key"
                    ),
                    {"key": key},
                ).scalar_one()
            )["cleanup_status"]
            == "complete"
        )


def test_delete_all_removes_only_target_graph_and_restores_recovery_guards(migrated_database):
    database, ids, data_root = migrated_database
    task_manager = _TaskRecorder()
    ticket_store = _TicketRecorder()
    with database.session() as session:
        result = asyncio.run(
            cleanup.delete_all(
                session,
                actor_user_id=ids["teacher"],
                debate_id=ids["debate"],
                expected_revision=1,
                expected_control_version=1,
                data_root=data_root,
                task_manager=task_manager,
                ticket_store=ticket_store,
            )
        )
    assert result.cancellation_generation == 1
    assert result.interrupted_job_count == 0
    assert task_manager.cancelled == [ids["debate"]]
    assert ticket_store.revoked == [ids["debate"]]
    assert result.deleted_rows["debates"] == 1
    assert result.deleted_rows["llm_recovery_inputs"] == 1
    assert result.deleted_rows["provider_operations"] == 1
    assert not (
        data_root / "courses" / ids["course"] / "current-debate-audio" / ids["debate"]
    ).exists()
    assert not any((data_root / "staging" / "audio-swap").rglob("*.wav"))

    with database.session() as session:
        assert session.get(Debate, ids["debate"]) is None
        assert session.execute(text("PRAGMA foreign_key_check")).first() is None
        assert session.execute(text("SELECT count(*) FROM users")).scalar_one() == 2
        assert session.execute(text("SELECT count(*) FROM courses")).scalar_one() == 1
        assert session.execute(text("SELECT count(*) FROM knowledge_snapshots")).scalar_one() == 1
        assert session.execute(text("SELECT count(*) FROM provider_operations")).scalar_one() == 1
        assert (
            session.execute(text("SELECT count(*) FROM provider_scope_budgets")).scalar_one() == 1
        )
        assert (
            session.execute(text("SELECT count(*) FROM embedding_accepted_stages")).scalar_one()
            == 1
        )
        assert session.execute(text("SELECT count(*) FROM audit_logs")).scalar_one() == 1
        assert session.execute(text("SELECT count(*) FROM idempotency_records")).scalar_one() == 1
        assert session.execute(
            text("SELECT acceptance_run_id, call_no FROM provider_operations")
        ).first() == (None, None)
        triggers = {
            row[0]: row[1]
            for row in session.execute(
                text("SELECT name, sql FROM sqlite_master WHERE type='trigger'")
            )
        }
        assert cleanup._RECOVERY_DELETE_TRIGGER in triggers
        assert cleanup._RECOVERY_UPDATE_TRIGGER in triggers
        assert "BEFORE DELETE ON llm_recovery_inputs" in triggers[cleanup._RECOVERY_DELETE_TRIGGER]


def test_delete_all_preserves_other_active_classroom(migrated_database):
    database, ids, data_root = migrated_database
    other_debate_id = _uid(70)
    now = datetime.now(UTC)
    with database.session() as session:
        _add(
            session,
            "debates",
            id=other_debate_id,
            course_id=ids["course"],
            topic="Other active debate",
            rule_set_id="maya_demo_v1",
            rule_snapshot_json="{}",
            output_language="en",
            final_input_json=None,
            final_input_hash=None,
            final_frozen_at=None,
            status="running",
            revision=1,
            last_sequence=0,
            cancellation_generation=0,
            created_by=ids["teacher"],
            created_at=now,
            updated_at=now,
            started_at=now,
            finished_at=None,
        )
        # Another running classroom must not block this scoped deletion.
    with database.session() as session:
        asyncio.run(
            cleanup.delete_all(
                session,
                actor_user_id=ids["teacher"],
                debate_id=ids["debate"],
                expected_revision=1,
                expected_control_version=1,
                data_root=data_root,
            )
        )
        assert session.get(Debate, ids["debate"]) is None
        assert session.get(Debate, other_debate_id).status == "running"
        assert session.execute(text("SELECT count(*) FROM llm_recovery_inputs")).scalar_one() == 0


def test_delete_all_preserves_an_active_shared_provider_operation(migrated_database):
    database, ids, data_root = migrated_database
    with database.session() as session:
        session.execute(
            text("UPDATE provider_operations SET state='sending' WHERE id=:id"),
            {"id": ids["operation_shared"]},
        )
    with database.session() as session:
        asyncio.run(
            cleanup.delete_all(
                session,
                actor_user_id=ids["teacher"],
                debate_id=ids["debate"],
                expected_revision=1,
                expected_control_version=1,
                data_root=data_root,
            )
        )
        assert session.get(Debate, ids["debate"]) is None
        assert (
            session.execute(
                text("SELECT state FROM provider_operations WHERE id=:id"),
                {"id": ids["operation_shared"]},
            ).scalar_one()
            == "sending"
        )


def test_delete_all_refuses_symlinked_runtime_file_without_db_mutation(migrated_database):
    database, ids, data_root = migrated_database
    outside = data_root.parent / "outside.wav"
    outside.write_bytes(b"outside")
    audio_dir = data_root / "courses" / ids["course"] / "current-debate-audio" / ids["debate"]
    (audio_dir / "unsafe.wav").unlink(missing_ok=True)
    (audio_dir / "unsafe.wav").symlink_to(outside)

    with database.session() as session:
        with pytest.raises(cleanup.DebateCleanupError, match="cleanup_path_symlink_refused"):
            asyncio.run(
                cleanup.delete_all(
                    session,
                    actor_user_id=ids["teacher"],
                    debate_id=ids["debate"],
                    expected_revision=1,
                    expected_control_version=1,
                    data_root=data_root,
                )
            )
    assert outside.read_bytes() == b"outside"
    with database.session() as session:
        debate = session.get(Debate, ids["debate"])
        assert debate is not None and debate.revision == 1
        assert session.execute(text("PRAGMA foreign_key_check")).first() is None


@pytest.mark.parametrize("failure", ["partial_files", "runtime_cancel"])
def test_cleanup_retry_reconciles_partial_work_without_double_counting(
    migrated_database, monkeypatch, failure
):
    database, ids, data_root = migrated_database
    expected = []

    def partial_finish(quarantine):
        expected.append(len(quarantine.moved))
        assert len(quarantine.moved) >= 2
        for _, destination in quarantine.moved[:-1]:
            destination.unlink()
        return len(quarantine.moved) - 1, 1

    async def failed_cancel(*_args, **_kwargs):
        raise RuntimeError("simulated cancellation failure")

    if failure == "partial_files":
        monkeypatch.setattr(cleanup, "_finish_files", partial_finish)
    else:
        monkeypatch.setattr(cleanup, "_cancel_runtime", failed_cancel)
    kwargs = dict(
        actor_user_id=ids["teacher"],
        debate_id=ids["debate"],
        expected_revision=1,
        expected_control_version=1,
        data_root=data_root,
        idempotency_key=f"cleanup-reconcile-{failure}",
    )
    with database.session() as db:
        first = asyncio.run(cleanup.delete_voice(db, **kwargs))
    assert first.cleanup_status != "complete"
    monkeypatch.undo()
    with database.session() as db:
        resumed = asyncio.run(cleanup.delete_voice(db, **kwargs))
    assert resumed.cleanup_status == "complete"
    assert resumed.pending_file_count == 0
    assert resumed.deleted_file_count == (expected[0] if expected else first.deleted_file_count)
    with database.session() as db:
        assert asyncio.run(cleanup.delete_voice(db, **kwargs)) == resumed
