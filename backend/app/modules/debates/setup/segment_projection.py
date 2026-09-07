"""Teacher Preview and public paragraph projections share exact source lineage."""

from __future__ import annotations

import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import invalid_state
from app.core.models import Job, KnowledgeChunk, SnapshotDocument, StoredFile
from app.modules.debates.models import DebateParticipant, DebateTurn
from app.modules.debates.schemas import PreviewTurn, SegmentSourceDetail, SegmentTurnPublic
from app.modules.debates.source_lineage import receipt_scope_is_valid


def segment_projection(
    db: Session, turn: DebateTurn, participant: DebateParticipant
) -> tuple[SegmentTurnPublic | None, list[SegmentSourceDetail]]:
    if not turn.structured_json:
        return None, []
    try:
        raw = json.loads(turn.structured_json)
        if raw.get("schema_version") != "segment_turn_v2":
            return None, []
        from app.modules.debates.generation.segments import load_stored_segment_turn_result

        stored = load_stored_segment_turn_result(raw)
        result = SegmentTurnPublic.model_validate(
            {
                "schema_version": stored.schema_version,
                "segments": [item.as_payload() for item in stored.segments],
            }
        )
        if turn.speech != "\n\n".join(row.text for row in result.segments):
            raise ValueError("paragraph text mismatch")
        receipts = json.loads(turn.retrieval_receipts_json or "[]")
        by_id = {row["evidence_id"]: row for row in receipts}
        used_ids = list(
            dict.fromkeys(source for row in result.segments for source in row.source_ids)
        )
        query_texts: dict[str, str] = {}
        recovery = db.execute(
            text(
                "SELECT input_json FROM llm_recovery_inputs WHERE turn_id=:turn_id "
                "ORDER BY attempt_no DESC LIMIT 1"
            ),
            {"turn_id": turn.id},
        ).first()
        if recovery:
            saved = json.loads(recovery[0])
            queries = (
                saved["queries"]
                if saved.get("protocol") == "segments_v2"
                else saved["input"]["queries"]
            )
            query_texts = {row["query_hash"]: row["text"] for row in queries}
        sources: list[SegmentSourceDetail] = []
        for source_id in used_ids:
            receipt = by_id[source_id]
            chunk = db.get(KnowledgeChunk, receipt["chunk_id"])
            if (
                chunk is None
                or not receipt_scope_is_valid(db, turn, receipt)
                or chunk.snapshot_id != receipt["snapshot_id"]
                or chunk.text != receipt["text"]
            ):
                raise ValueError("source snapshot mismatch")
            document = db.get(SnapshotDocument, chunk.snapshot_document_id)
            if (
                document is None
                or document.snapshot_id != receipt["snapshot_id"]
                or document.source_filename != receipt["source_filename"]
            ):
                raise ValueError("source document mismatch")
            sources.append(
                SegmentSourceDetail(
                    source_id=source_id,
                    source_filename=receipt["source_filename"],
                    excerpt=receipt["text"],
                    query_text=query_texts.get(receipt["query_hash"]),
                    version_label=(
                        participant.version_label
                        if receipt["snapshot_id"] == turn.knowledge_snapshot_id
                        else _source_version_label(db, turn, receipt["snapshot_id"])
                    ),
                )
            )
        return result, sources
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise invalid_state("The saved paragraph sources are invalid.") from exc


def _source_version_label(db: Session, turn: DebateTurn, snapshot_id: str) -> str:
    participant = db.scalar(
        select(DebateParticipant)
        .where(
            DebateParticipant.debate_id == turn.debate_id,
            DebateParticipant.knowledge_snapshot_id == snapshot_id,
        )
        .order_by(DebateParticipant.order_index)
    )
    if participant is None:
        raise ValueError("source snapshot has no classroom participant")
    return participant.version_label


def preview_turn_projection(
    db: Session, turn: DebateTurn, participant: DebateParticipant
) -> PreviewTurn:
    result, sources = segment_projection(db, turn, participant)
    audio = db.get(StoredFile, turn.audio_file_id) if turn.audio_file_id else None
    status, error = turn.generation_status, turn.safe_error_code
    if status == "pending":
        # Older failed warm-ups reset the turn but retained the failed Job.
        # Read that durable outcome so both Preview and its list remain actionable.
        job = db.scalar(
            select(Job).where(
                Job.debate_id == turn.debate_id,
                Job.turn_id == turn.id,
                Job.operation == "debate_turn_prepare",
                Job.state == "failed",
            )
        )
        if job is not None:
            status, error = "failed", job.safe_error_code or "turn_generation_failed"
    return PreviewTurn.model_validate(
        {
            "id": turn.id,
            "participant_id": turn.participant_id,
            "round_no": turn.round_no,
            "turn_index": turn.turn_index,
            "speech": turn.speech or "",
            "generation_status": status,
            "audio_ready": audio is not None and audio.state == "active",
            "safe_error_code": error,
            "segments": result.segments if result else [],
            "sources": sources,
        }
    )
