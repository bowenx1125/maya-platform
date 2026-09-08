"""Reset a completed classroom while retaining its paid Preview and cost ledger."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.errors import conflict
from app.core.models import DemoAcceptanceRun, FileReference, Job, StoredFile
from app.modules.debates import cleanup as cleanup
from app.modules.debates.models import AuditLog, DebateParticipant, DebateTurn
from app.modules.debates.round_count import debate_round_count
from app.modules.interactions.service import create_closed_window


async def rebirth_debate(
    db: Session,
    *,
    actor_user_id: str,
    debate_id: str,
    expected_revision: int,
    expected_control_version: int,
    idempotency_key: str,
    data_root: Path,
    playback_service: Any = None,
    report_task_manager: Any = None,
) -> cleanup.DeleteAllResult:
    cleanup._begin_immediate(db)
    quarantine = None
    try:
        claim = cleanup._claim_cleanup_idempotency(
            db,
            operation="rebirthDebate",
            actor_user_id=actor_user_id,
            debate_id=debate_id,
            expected_revision=expected_revision,
            expected_control_version=expected_control_version,
            key=idempotency_key,
        )
        if claim.replay is not None:
            db.commit()
            return claim.replay  # type: ignore[return-value]
        debate = cleanup._load_debate(db, debate_id, actor_user_id)
        playback = cleanup._load_playback(db, debate_id)
        if debate.status not in {"completed", "debate_finished"} or playback.mode != "live":
            raise conflict("invalid_state", "Only a completed classroom can be reborn.")
        root = cleanup._safe_root(data_root)
        graph = cleanup._build_graph(db, debate, root, collect_files=False)
        if db.scalar(
            select(Job.id)
            .where(
                Job.debate_id == debate_id,
                Job.state.in_(("pending", "running")),
            )
            .limit(1)
        ):
            raise conflict("cleanup_deferred", "A classroom operation is still active.")
        turns = list(
            db.scalars(
                select(DebateTurn)
                .where(
                    DebateTurn.debate_id == debate_id,
                )
                .order_by(DebateTurn.turn_index)
            )
        )
        final_round = debate_round_count(debate)
        preview = [turn for turn in turns if turn.round_no < final_round]
        finals = [turn for turn in turns if turn.round_no == final_round]
        if (
            not preview
            or not finals
            or any(
                turn.generation_status != "final_ready" or not turn.audio_file_id
                for turn in preview
            )
        ):
            raise conflict("preview_not_ready", "Saved Preview audio is required for Rebirth.")
        final_ids = {turn.id for turn in finals}
        owners = final_ids | graph.report_ids | graph.revision_ids | graph.insight_ids
        refs = list(db.scalars(select(FileReference).where(FileReference.owner_id.in_(owners))))
        file_ids = {ref.stored_file_id for ref in refs} | {
            turn.audio_file_id for turn in finals if turn.audio_file_id
        }
        # Shared file references and Preview audio always survive.
        preview_files = {turn.audio_file_id for turn in preview}
        shared = set(
            db.scalars(
                select(FileReference.stored_file_id).where(
                    FileReference.stored_file_id.in_(file_ids),
                    FileReference.owner_id.not_in(owners),
                )
            )
        )
        removable_files = file_ids - preview_files - shared
        files = cleanup._DebateGraph(debate_id, debate.course_id)
        for stored in db.scalars(select(StoredFile).where(StoredFile.id.in_(removable_files))):
            cleanup._collect_file_path(files, root, stored.relative_path, directory=False)
        quarantine = cleanup._stage_files(files, root)
        cleanup._journal_quarantine(
            db,
            quarantine,
            operation_type=cleanup._CLEANUP_ALL_OPERATION,
            debate_id=debate_id,
            idempotency_record_id=None,
        )
        revision, version, generation = cleanup._fence_debate(
            db,
            debate,
            playback,
            expected_revision=expected_revision,
            expected_control_version=expected_control_version,
            delete_all=True,
        )
        counts: dict[str, int] = {}

        def remove(table: str, column: str, values: set[str]) -> None:
            counts[table] = cleanup._delete_rows(db, table, column, values)

        # Retain immutable cost operations, but discard output/recovery payloads
        # for the old final so they can never be replayed into a fresh classroom.
        recovery_ids = cleanup._children(db, "llm_recovery_inputs", "turn_id", "turn_id", final_ids)
        if recovery_ids:
            triggers = cleanup._capture_recovery_triggers(db)
            cleanup._drop_recovery_triggers(db, triggers)
            remove("llm_recovery_inputs", "turn_id", final_ids)
            cleanup._restore_recovery_triggers(db, triggers)
        remove("llm_accepted_stages", "turn_id", final_ids)
        manifests = cleanup._children(db, "provider_export_manifests", "id", "turn_id", final_ids)
        remove("provider_export_confirmations", "manifest_id", manifests)
        remove("provider_export_manifests", "id", manifests)
        remove("jobs", "debate_id", {debate_id})
        for table in (
            "interaction_final_barrages",
            "interaction_final_vote_counts",
            "barrage_insight_assignments",
            "barrage_insight_items",
            "civilization_report_current_success",
            "civilization_report_revisions",
            "civilization_reports",
            "barrage_insight_snapshots",
            "votes",
            "barrage_messages",
            "classroom_interaction_windows",
        ):
            if table == "civilization_report_revisions":
                db.execute(
                    update(DemoAcceptanceRun)
                    .where(
                        DemoAcceptanceRun.report_revision_id.in_(graph.revision_ids),
                    )
                    .values(report_revision_id=None)
                )
            remove(table, "debate_id", {debate_id})
        remove("turn_sources", "turn_id", final_ids)
        remove("position_history", "turn_id", final_ids)
        remove("file_references", "id", {ref.id for ref in refs})
        replacements = [
            dict(
                id=str(uuid4()),
                debate_id=debate_id,
                participant_id=turn.participant_id,
                knowledge_snapshot_id=turn.knowledge_snapshot_id,
                round_no=turn.round_no,
                turn_index=turn.turn_index,
                generation_status="pending",
                publication_status="unpublished",
                preparation_stage="generation",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            for turn in finals
        ]
        remove("debate_turns", "id", final_ids)
        db.add_all(DebateTurn(**values) for values in replacements)
        remove("stored_files", "id", removable_files)
        remove("debate_events", "debate_id", {debate_id})
        # Cached first-three-round speech, sources, memory and audio remain exact.
        db.execute(
            update(DebateTurn)
            .where(DebateTurn.debate_id == debate_id)
            .values(
                publication_status="unpublished",
                public_at=None,
            )
        )
        db.execute(
            update(DebateParticipant)
            .where(DebateParticipant.debate_id == debate_id)
            .values(
                current_stance=DebateParticipant.initial_stance,
                current_position_summary=DebateParticipant.initial_position_summary,
            )
        )
        debate.status = "draft"
        debate.final_input_json = None
        debate.final_input_hash = None
        debate.final_frozen_at = None
        debate.started_at = debate.finished_at = None
        debate.last_sequence = 0
        create_closed_window(db, debate)
        playback.status = "preparing"
        db.add(
            AuditLog(
                id=str(uuid4()),
                event_type="debate.rebirth",
                actor_kind="teacher",
                actor_id=actor_user_id,
                course_id=debate.course_id,
                debate_id=debate_id,
                details_json='{"retained_preview":true,"new_final_authorized":true}',
                created_at=datetime.now(UTC),
            )
        )
        db.flush()
        if db.execute(text("PRAGMA foreign_key_check")).first() is not None:
            raise cleanup.DebateCleanupError("foreign_key_violations_after")
        result = cleanup.DeleteAllResult(
            debate_id=debate_id,
            revision=revision,
            control_version=version,
            cancellation_generation=generation,
            interrupted_job_count=0,
            deleted_rows=counts,
            deleted_file_count=0,
            missing_file_count=quarantine.missing_count,
            pending_file_count=0,
            runtime_cancelled=True,
        )
        cleanup._persist_cleanup_receipt(db, claim.record, result)
        db.commit()
    except Exception:
        db.rollback()
        if quarantine is not None:
            cleanup._restore_files(quarantine)
        raise
    await cleanup._cancel_runtime(
        debate_id, playback_service=playback_service, report_task_manager=report_task_manager
    )
    _, pending = cleanup._finish_files(quarantine)
    cleanup._mark_cleanup_journal_recovered(db, quarantine, file_pending=pending)
    return result


async def remake_debate(
    db: Session,
    *,
    actor_user_id: str,
    debate_id: str,
    expected_revision: int,
    expected_control_version: int,
    idempotency_key: str,
    data_root: Path,
    playback_service: Any = None,
    report_task_manager: Any = None,
) -> cleanup.DeleteAllResult:
    from app.core.models import LlmAcceptedStage, ProviderOperation

    cleanup._begin_immediate(db)
    target = None
    enqueue = False
    audio_repair = False
    try:
        claim = cleanup._claim_cleanup_idempotency(
            db,
            operation="remakeDebate",
            actor_user_id=actor_user_id,
            debate_id=debate_id,
            expected_revision=expected_revision,
            expected_control_version=expected_control_version,
            key=idempotency_key,
        )
        if claim.replay is not None:
            db.commit()
            return claim.replay  # type: ignore[return-value]
        debate = cleanup._load_debate(db, debate_id, actor_user_id)
        if debate.status not in {"draft", "running", "failed"}:
            raise conflict("invalid_state", "This classroom has no recoverable turn.")
        playback = cleanup._load_playback(db, debate_id)
        if playback.mode != "live":
            raise conflict("invalid_state", "Retained replay cannot generate a turn.")
        turns = list(
            db.scalars(
                select(DebateTurn)
                .where(
                    DebateTurn.debate_id == debate_id,
                )
                .order_by(DebateTurn.turn_index)
            )
        )
        current = next((t for t in turns if t.id == playback.current_turn_id), None)
        candidates = (
            turns
            if debate.status == "draft"
            else [
                t
                for t in turns
                if current is not None
                and t.turn_index
                in {
                    current.turn_index,
                    current.turn_index + 1,
                }
            ]
        )
        target = (
            current
            if current is not None
            and playback.status in {"ready", "playing", "paused"}
            and current.generation_status == "final_ready"
            else next((t for t in candidates if t.generation_status != "final_ready"), current)
        )
        if target is None:
            raise conflict("invalid_state", "There is no stalled turn to recover.")
        operations = list(
            db.scalars(
                select(ProviderOperation).where(
                    ProviderOperation.logical_item_id == target.id,
                )
            )
        )
        if any(op.state in {"sending", "acceptance_unknown"} for op in operations):
            raise conflict("provider_reconciliation_required", "The prior request is not settled.")
        if target.generation_status == "running" and db.scalar(
            select(Job.id)
            .where(
                Job.turn_id == target.id,
                Job.state == "running",
            )
            .limit(1)
        ):
            raise conflict("preparation_in_progress", "The turn is still being prepared.")
        revision, version, generation = cleanup._fence_debate(
            db,
            debate,
            playback,
            expected_revision=expected_revision,
            expected_control_version=expected_control_version,
            delete_all=False,
            advance_revision=False,
        )
        fresh = False
        if target.generation_status != "final_ready":
            if any(
                t.turn_index > target.turn_index and t.generation_status == "final_ready"
                for t in turns
            ):
                raise conflict("invalid_state", "Later saved turns depend on this result.")
            accepted = db.scalar(
                select(LlmAcceptedStage.operation_id)
                .where(
                    LlmAcceptedStage.turn_id == target.id,
                )
                .limit(1)
            )
            cached_text = bool(target.speech and target.structured_json)
            if (
                not accepted
                and not cached_text
                and any(op.charged_request_count for op in operations)
            ):
                # Explicit Remake starts a new bounded turn identity. The old
                # cost operations stay in the ledger and cannot be retried.
                old_id = target.id
                recovery_ids = cleanup._children(
                    db, "llm_recovery_inputs", "turn_id", "turn_id", {old_id}
                )
                if recovery_ids:
                    triggers = cleanup._capture_recovery_triggers(db)
                    cleanup._drop_recovery_triggers(db, triggers)
                    cleanup._delete_rows(db, "llm_recovery_inputs", "turn_id", {old_id})
                    cleanup._restore_recovery_triggers(db, triggers)
                manifests = cleanup._children(
                    db, "provider_export_manifests", "id", "turn_id", {old_id}
                )
                cleanup._delete_rows(db, "provider_export_confirmations", "manifest_id", manifests)
                cleanup._delete_rows(db, "provider_export_manifests", "id", manifests)
                cleanup._delete_rows(db, "jobs", "turn_id", {old_id})
                cleanup._delete_rows(db, "turn_sources", "turn_id", {old_id})
                cleanup._delete_rows(db, "position_history", "turn_id", {old_id})
                if playback.current_turn_id == old_id:
                    playback.current_turn_id = None
                    db.flush()
                replacement = DebateTurn(
                    id=str(uuid4()),
                    debate_id=debate_id,
                    participant_id=target.participant_id,
                    knowledge_snapshot_id=target.knowledge_snapshot_id,
                    round_no=target.round_no,
                    turn_index=target.turn_index,
                    generation_status="pending",
                    publication_status="unpublished",
                    preparation_stage="generation",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                db.delete(target)
                db.flush()
                db.add(replacement)
                target = replacement
                fresh = True
            else:
                cleanup._delete_rows(db, "jobs", "turn_id", {target.id})
                target.generation_status = "pending"
                target.safe_error_code = None
            enqueue = True
        else:
            # Saved text needs only a fresh media handshake, or cached TTS.
            audio_repair = not bool(target.audio_file_id) or (
                playback_service is not None
                and playback_service._validated_turn_audio(db, debate, target) is None
            )
            enqueue = audio_repair
            if enqueue:
                cleanup._delete_rows(db, "jobs", "turn_id", {target.id})
        if debate.status != "draft":
            debate.status = "running"
            if (
                current is None
                or current.id == target.id
                or current.generation_status != "final_ready"
            ):
                playback.current_turn_id = target.id
                playback.status = "preparing" if enqueue else "ready"
            elif target.turn_index > current.turn_index:
                playback.status = "waiting_next"
            else:
                playback.status = "ready"
            playback.cursor_ms = 0
        else:
            playback.status = "preparing"
            playback.current_turn_id = None
        db.add(
            AuditLog(
                id=str(uuid4()),
                event_type="debate.remake",
                actor_kind="teacher",
                actor_id=actor_user_id,
                course_id=debate.course_id,
                debate_id=debate_id,
                details_json='{"regenerated":true}' if fresh else '{"regenerated":false}',
                created_at=datetime.now(UTC),
            )
        )
        result = cleanup.DeleteAllResult(
            debate_id=debate_id,
            revision=revision,
            control_version=version,
            cancellation_generation=generation,
            interrupted_job_count=0,
            deleted_rows={},
            deleted_file_count=0,
            missing_file_count=0,
            pending_file_count=0,
            runtime_cancelled=True,
        )
        cleanup._persist_cleanup_receipt(db, claim.record, result)
        db.commit()
    except Exception:
        db.rollback()
        raise
    if playback_service is not None:
        playback_service.ticket_store.revoke_debate(debate_id)
        playback_service._clear_media_results(debate_id)
        if audio_repair:
            from app.modules.debates.playback.audio_regeneration import regenerate_turn_audio

            def restore_audio() -> Any:
                return regenerate_turn_audio(
                    db,
                    debate_id,
                    target.id,
                    revision,
                    "remake-audio:" + idempotency_key,
                    playback_service=playback_service,
                    voice_resolver=lambda cached: playback_service._resolve_voice(
                        db,
                        db.get(DebateParticipant, cached.participant_id),
                    ),
                )

            restored = await asyncio.to_thread(restore_audio)
            enqueue = restored.audio_ready
        if enqueue:
            await playback_service._enqueue(debate, target)
    return result
