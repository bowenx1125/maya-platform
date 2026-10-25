"""Teacher Preview and public paragraph projections share exact source lineage."""

from __future__ import annotations

import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import invalid_state
from app.core.models import Job, KnowledgeChunk, SnapshotDocument, StoredFile
from app.core.prefetch import prefetched
from app.modules.debates.final_input import read_final_input
from app.modules.debates.models import Debate, DebateParticipant, DebateTurn
from app.modules.debates.round_count import debate_round_count
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
        reply_texts: dict[str, str] = {}
        if any(segment.reply_to for segment in stored.segments):
            debate = db.get(Debate, turn.debate_id)
            if debate is not None and turn.round_no == debate_round_count(debate):
                frozen = read_final_input(debate)
                if frozen is not None:
                    reply_texts = {item["id"]: item["text"] for item in frozen["barrages"]}
        result = SegmentTurnPublic.model_validate(
            {
                "schema_version": stored.schema_version,
                "segments": [
                    {**item.as_payload(), "reply_text": reply_texts.get(item.reply_to or "")}
                    for item in stored.segments
                ],
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
        recovery = prefetched(
            db,
            "llm_recovery_input",
            turn.id,
            lambda: db.execute(
                text(
                    "SELECT input_json FROM llm_recovery_inputs WHERE turn_id=:turn_id "
                    "ORDER BY attempt_no DESC LIMIT 1"
                ),
                {"turn_id": turn.id},
            ).scalar(),
        )
        if recovery:
            saved = json.loads(recovery)
            queries = (
                saved["queries"]
                if saved.get("protocol") == "segments_v2"
                else saved["input"]["queries"]
            )
            query_texts = {row["query_hash"]: row["text"] for row in queries}
        sources: list[SegmentSourceDetail] = []
        for source_id in used_ids:
            receipt = by_id[source_id]
            chunk = _chunk(db, receipt["chunk_id"])
            if (
                chunk is None
                or not receipt_scope_is_valid(db, turn, receipt)
                or chunk.snapshot_id != receipt["snapshot_id"]
                or chunk.text != receipt["text"]
            ):
                raise ValueError("source snapshot mismatch")
            document = _snapshot_document(db, chunk.snapshot_document_id)
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


def _chunk(db: Session, chunk_id: str) -> KnowledgeChunk | None:
    return prefetched(db, "knowledge_chunk", chunk_id, lambda: db.get(KnowledgeChunk, chunk_id))


def _snapshot_document(db: Session, document_id: str) -> SnapshotDocument | None:
    return prefetched(
        db, "snapshot_document", document_id, lambda: db.get(SnapshotDocument, document_id)
    )


def prefetch_segment_sources(db: Session, turns: list[DebateTurn]) -> None:
    """Batch what ``segment_projection`` reads for these turns (Debate detail).

    The turns' audio files, the latest recovery input per turn, the cited
    chunks and their snapshot documents, each stored for every key asked so a
    missing row stays None.
    """

    from app.core.prefetch import store

    audio_ids = {turn.audio_file_id for turn in turns if turn.audio_file_id}
    if audio_ids:
        # Held here so the per-turn ``db.get(StoredFile, ...)`` calls are
        # identity-map hits for the rest of the transaction.
        store(
            db,
            "stored_file",
            {
                row.id: row
                for row in db.scalars(select(StoredFile).where(StoredFile.id.in_(audio_ids)))
            },
        )
    turn_ids = [turn.id for turn in turns if turn.structured_json]
    if not turn_ids:
        return
    recoveries: dict[str, str | None] = dict.fromkeys(turn_ids)
    for turn_id, input_json in db.execute(
        text(
            "SELECT DISTINCT ON (turn_id) turn_id, input_json FROM llm_recovery_inputs "
            "WHERE turn_id = ANY(:turn_ids) ORDER BY turn_id, attempt_no DESC"
        ),
        {"turn_ids": turn_ids},
    ).all():
        recoveries[turn_id] = input_json
    store(db, "llm_recovery_input", recoveries)
    chunk_ids: set[str] = set()
    for turn in turns:
        try:
            receipts = json.loads(turn.retrieval_receipts_json or "[]")
            chunk_ids.update(str(row["chunk_id"]) for row in receipts if row.get("chunk_id"))
        except (ValueError, TypeError, AttributeError):
            continue
    if not chunk_ids:
        return
    chunks: dict[str, KnowledgeChunk | None] = dict.fromkeys(chunk_ids)
    for chunk in db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(chunk_ids))):
        chunks[chunk.id] = chunk
    store(db, "knowledge_chunk", chunks)
    document_ids = {chunk.snapshot_document_id for chunk in chunks.values() if chunk is not None}
    documents: dict[str, SnapshotDocument | None] = dict.fromkeys(document_ids)
    for document in db.scalars(
        select(SnapshotDocument).where(SnapshotDocument.id.in_(document_ids))
    ):
        documents[document.id] = document
    store(db, "snapshot_document", documents)


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
