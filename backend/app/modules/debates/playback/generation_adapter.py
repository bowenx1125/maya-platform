"""SQL adapter from frozen Wave 2 rows to the pure M11 generator.

The adapter is deliberately provider-neutral.  It loads only the selected
participant's immutable AgentVersion and KnowledgeSnapshot, reconstructs the
complete final-ready predecessor prefix, and returns one validated
``PreparedTurn`` for the separate playback/TTS stage.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import AgentVersion, KnowledgeChunk, SnapshotDocument
from app.modules.debates.generation import (
    FinalReadyTurn,
    GenerationContext,
    ParticipantContext,
    SnapshotRetrievalReceipt,
    SnapshotRetriever,
    StructuredTurnResult,
    TurnGenerationService,
    TurnPolicy,
    compute_transcript_hash,
)
from app.modules.debates.generation.mutual_learning_policy import (
    MUTUAL_LEARNING_RULE_SET_ID,
)
from app.modules.debates.generation.types import MutualLearningTurnResultV1
from app.modules.debates.generation.validator import count_turn_words
from app.modules.debates.models import DebateParticipant, DebateTurn
from app.modules.knowledge.mock_lexical import MOCK_LEXICAL_ANCHOR_POLICY_ID
from app.modules.knowledge.vector import MockVectorStore, StoredVectorRow
from app.providers.llm import LLMProvider, llm_provider

from .protocols import PreparedGenerationFence, PreparedSource, PreparedTurn
from .schemas import RetrievalSourceDTO


class SqlSnapshotSearch:
    """Snapshot-scoped search over the existing immutable 256-d Mock vectors."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def search(self, snapshot_id: str, query: str, *, top_k: int = 6) -> tuple[object, ...]:
        rows = self.db.execute(
            select(KnowledgeChunk, SnapshotDocument)
            .join(
                SnapshotDocument,
                SnapshotDocument.id == KnowledgeChunk.snapshot_document_id,
            )
            .where(
                KnowledgeChunk.snapshot_id == snapshot_id,
                SnapshotDocument.snapshot_id == snapshot_id,
            )
            .order_by(SnapshotDocument.order_index, KnowledgeChunk.chunk_index)
        ).all()
        vectors = [
            StoredVectorRow(
                chunk_id=chunk.id,
                source_filename=document.source_filename,
                chunk_text=chunk.chunk_text,
                blob=chunk.embedding_blob,
                dimension=chunk.embedding_dimension,
                key=chunk.embedding_key,
                document_order=document.order_index,
                chunk_index=chunk.chunk_index,
            )
            for chunk, document in rows
        ]
        return tuple(MockVectorStore(vectors).search(query, top_k=top_k))


class SqlTurnPreparer:
    """Build and run one M11 generation context from M10's immutable rows."""

    def __init__(self, *, settings: object | None = None, llm: LLMProvider | None = None) -> None:
        self.settings = settings
        self.llm = llm or llm_provider(settings)

    def __call__(
        self,
        db: Any,
        debate: Any,
        turn: Any,
        *,
        attempt: int,
        cancellation_generation: int,
    ) -> PreparedTurn:
        del cancellation_generation
        if not isinstance(db, Session):
            raise ValueError("SQL turn preparation requires a database Session")
        if attempt != 1:
            raise ValueError("M11 owns the complete attempt 1|2 repair budget")
        debate_id = str(debate.id)
        participant_rows = list(
            db.scalars(
                select(DebateParticipant)
                .where(DebateParticipant.debate_id == debate_id)
                .order_by(DebateParticipant.order_index)
            ).all()
        )
        turn_rows = list(
            db.scalars(
                select(DebateTurn)
                .where(DebateTurn.debate_id == debate_id)
                .order_by(DebateTurn.turn_index)
            ).all()
        )
        current = next((row for row in turn_rows if row.id == str(turn.id)), None)
        if current is None:
            raise ValueError("planned turn is unavailable")
        participants = tuple(self._participant(db, row) for row in participant_rows)
        participant = next(
            (item for item in participants if item.participant_id == current.participant_id),
            None,
        )
        if participant is None:
            raise ValueError("turn participant is unavailable")
        expected_fence = generation_fence(db, debate, current)
        persisted_rule_set_id = str(debate.rule_set_id)
        is_mutual = persisted_rule_set_id == MUTUAL_LEARNING_RULE_SET_ID
        round_count = self._round_count(debate) if is_mutual else 2
        policy = TurnPolicy(rule_set_id=persisted_rule_set_id)
        plans = policy.plan_with_ids(
            participants,
            [row.id for row in turn_rows],
            round_count=round_count,
        )
        plan = plans[current.turn_index]
        predecessor_rows = (
            [row for row in turn_rows if int(row.round_no) < int(current.round_no)]
            if is_mutual
            else turn_rows[: current.turn_index]
        )
        predecessors = tuple(self._final_ready(db, row) for row in predecessor_rows)
        context = GenerationContext(
            debate_id=debate_id,
            topic=str(debate.topic),
            turn=plan,
            participant=participant,
            participants=participants,
            predecessors=predecessors,
        )
        generator = TurnGenerationService(
            SnapshotRetriever(SqlSnapshotSearch(db)),
            self.llm,
            rule_set_id=persisted_rule_set_id,
            mock_retrieval_policy_id=(
                MOCK_LEXICAL_ANCHOR_POLICY_ID
                if getattr(self.settings, "embedding_provider", "mock") == "mock"
                and persisted_rule_set_id == "ordered_multi_agent_rounds_demo_v2"
                else None
            ),
        )
        generated = generator.generate(context)
        final = generated.final_ready
        if (
            final.predecessor_turn_ids != expected_fence.predecessor_turn_ids
            or final.transcript_hash != expected_fence.transcript_hash
            or final.cutoff_turn_index != expected_fence.cutoff_turn_index
        ):
            raise ValueError("generation result does not match the prepared prefix fence")
        sources = tuple(
            RetrievalSourceDTO(
                source_filename=source.source_filename,
                chunk_id=UUID(source.chunk_id),
            )
            for source in final.public_sources
        )
        receipts = tuple(
            PreparedSource(
                snapshot_id=receipt.snapshot_id,
                query_kind=receipt.query_kind,
                query_hash=receipt.query_hash,
                threshold_key=receipt.threshold_key,
                source_filename=receipt.source_filename,
                chunk_id=receipt.chunk_id,
                evidence_id=receipt.resolved_evidence_id(),
                rank=receipt.rank,
                score=receipt.score,
                text=receipt.text,
            )
            for receipt in final.used_receipts
        )
        participant_row = next(
            (row for row in participant_rows if str(row.id) == participant.participant_id), None
        )
        if participant_row is None:
            raise ValueError("turn participant row is unavailable")
        voice_kind = str(getattr(participant_row, "effective_voice_kind", "mock_sentinel"))
        voice_profile_id = getattr(participant_row, "effective_voice_profile_id", None)
        if voice_kind not in {"platform_profile", "mock_sentinel"}:
            raise ValueError("frozen participant voice kind is invalid")
        if voice_kind == "platform_profile" and not voice_profile_id:
            raise ValueError("platform voice kind requires a frozen profile")
        if voice_kind == "mock_sentinel" and voice_profile_id is not None:
            raise ValueError("mock voice kind cannot carry a profile")
        voice_token = str(voice_profile_id) if voice_kind == "platform_profile" else "mock"
        return PreparedTurn(
            speech=final.speech,
            sources=sources,
            retrieval_status=final.retrieval_status,
            grounding_mode=final.grounding_mode,
            structured=final.structured.model_dump(mode="json"),
            voice_token=voice_token,
            actual_voice_kind=voice_kind,
            actual_voice_profile_id=(str(voice_profile_id) if voice_profile_id else None),
            source_receipts=receipts,
            predecessor_turn_ids=final.predecessor_turn_ids,
            transcript_hash=final.transcript_hash,
            cutoff_turn_index=final.cutoff_turn_index,
            word_count=count_turn_words(
                final.speech,
                final.structured.question.text
                if final.structured.question.type != "none"
                else None,
            ),
            generation_attempt=final.attempt,
        )

    @staticmethod
    def _round_count(debate: Any) -> int:
        try:
            snapshot = json.loads(str(debate.rule_snapshot_json))
        except (TypeError, ValueError) as exc:
            raise ValueError("mutual-learning rule snapshot is invalid") from exc
        count = snapshot.get("round_count") if isinstance(snapshot, dict) else None
        if not isinstance(count, int) or isinstance(count, bool) or not 2 <= count <= 5:
            raise ValueError("mutual-learning round count is invalid")
        return count

    @staticmethod
    def generation_fence(
        db: Session,
        debate: Any,
        turn: Any,
        *,
        attempt: int = 1,
        cancellation_generation: int = 0,
    ) -> PreparedGenerationFence:
        """Expose the pre-provider prefix fence through the preparer seam."""

        del cancellation_generation
        if attempt != 1:
            raise ValueError("generation fencing starts at attempt one")
        return generation_fence(db, debate, turn)

    @staticmethod
    def _participant(db: Session, row: DebateParticipant) -> ParticipantContext:
        version = db.get(AgentVersion, row.agent_version_id)
        if version is None or version.state not in {"published", "superseded"}:
            raise ValueError("frozen AgentVersion is unavailable")
        if str(version.knowledge_snapshot_id or "") != str(row.knowledge_snapshot_id):
            raise ValueError("frozen AgentVersion snapshot does not match participant")
        return ParticipantContext(
            participant_id=row.id,
            agent_id=row.agent_id,
            agent_name=row.agent_name,
            slot=row.slot,
            order_index=row.order_index,
            snapshot_id=row.knowledge_snapshot_id,
            agent_md=version.agent_md,
            stance_mode=row.stance_mode,  # type: ignore[arg-type]
            initial_stance=row.initial_stance,  # type: ignore[arg-type]
            current_stance=row.current_stance,  # type: ignore[arg-type]
            initial_position_summary=row.initial_position_summary,
            current_position_summary=row.current_position_summary,
            teacher_note=row.teacher_note,
        )

    @staticmethod
    def _receipt_from_payload(payload: object) -> SnapshotRetrievalReceipt:
        if not isinstance(payload, dict):
            raise ValueError("persisted retrieval receipt is not an object")
        required = {
            "snapshot_id",
            "query_kind",
            "query_hash",
            "threshold_key",
            "source_filename",
            "chunk_id",
            "evidence_id",
            "rank",
            "score",
            "text",
        }
        if set(payload) != required:
            raise ValueError("persisted retrieval receipt shape is not exact")
        try:
            return SnapshotRetrievalReceipt(
                snapshot_id=str(payload["snapshot_id"]),
                query_kind=str(payload["query_kind"]),
                query_hash=str(payload["query_hash"]),
                threshold_key=payload["threshold_key"],
                source_filename=str(payload["source_filename"]),
                chunk_id=str(payload["chunk_id"]),
                evidence_id=str(payload["evidence_id"]),
                rank=int(payload["rank"]),
                score=float(payload["score"]),
                text=str(payload["text"]),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("persisted retrieval receipt is invalid") from exc

    @classmethod
    def _persisted_receipts(
        cls,
        db: Session,
        row: DebateTurn,
        structured: StructuredTurnResult | MutualLearningTurnResultV1,
    ) -> tuple[SnapshotRetrievalReceipt, ...] | None:
        raw = getattr(row, "retrieval_receipts_json", None)
        if raw is None:
            return None
        try:
            payload = json.loads(str(raw))
        except (TypeError, ValueError) as exc:
            raise ValueError("persisted retrieval receipts are not valid JSON") from exc
        if not isinstance(payload, list):
            raise ValueError("persisted retrieval receipts are not a list")
        receipts = tuple(cls._receipt_from_payload(item) for item in payload)
        expected_ids = (
            tuple(structured.used_evidence_id)
            if isinstance(structured, StructuredTurnResult)
            else structured.used_evidence_ids
        )
        actual_ids = tuple(item.resolved_evidence_id() for item in receipts)
        if actual_ids != expected_ids:
            raise ValueError("persisted receipts do not match used evidence IDs")
        for receipt in receipts:
            if receipt.snapshot_id != str(row.knowledge_snapshot_id):
                raise ValueError("persisted receipt crossed the participant snapshot")
            chunk = db.get(KnowledgeChunk, receipt.chunk_id)
            if chunk is None or str(chunk.snapshot_id) != receipt.snapshot_id:
                raise ValueError("persisted receipt chunk crossed its snapshot")
            if str(chunk.chunk_text) != receipt.text:
                raise ValueError("persisted receipt text does not match the immutable chunk")
            document = db.get(SnapshotDocument, chunk.snapshot_document_id)
            if document is None or str(document.snapshot_id) != receipt.snapshot_id:
                raise ValueError("persisted receipt document crossed its snapshot")
            if str(document.source_filename) != receipt.source_filename:
                raise ValueError("persisted receipt filename does not match the snapshot")
        return receipts

    @classmethod
    def _final_ready(cls, db: Session, row: DebateTurn) -> FinalReadyTurn:
        if row.generation_status != "final_ready" or not row.speech or not row.structured_json:
            raise ValueError("the final-ready predecessor prefix is incomplete")
        try:
            structured_value = json.loads(row.structured_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("a predecessor structured result is invalid JSON") from exc
        structured: StructuredTurnResult | MutualLearningTurnResultV1
        if isinstance(structured_value, dict) and "key_claims" in structured_value:
            structured = MutualLearningTurnResultV1.model_validate(structured_value)
        else:
            structured = StructuredTurnResult.model_validate(structured_value)
        persisted = cls._persisted_receipts(db, row, structured)
        if persisted is None:
            raise ValueError("a final-ready predecessor has no exact receipt payload")
        receipts = persisted
        predecessor_ids = _decode_predecessor_ids(row)
        if row.transcript_hash is None or row.cutoff_turn_index is None:
            raise ValueError("a predecessor generation fence is incomplete")
        return FinalReadyTurn(
            turn_id=row.id,
            participant_id=row.participant_id,
            snapshot_id=row.knowledge_snapshot_id,
            round_no=row.round_no,
            turn_index=row.turn_index,
            speech=row.speech,
            structured=structured,
            retrieval_status=row.retrieval_status or "no_match",  # type: ignore[arg-type]
            grounding_mode=row.grounding_mode or "general_reasoning",  # type: ignore[arg-type]
            used_receipts=receipts,
            predecessor_turn_ids=predecessor_ids,
            cutoff_turn_index=row.cutoff_turn_index,
            transcript_hash=row.transcript_hash,
            attempt=row.attempt,  # type: ignore[arg-type]
            publication_status=("public" if row.publication_status == "public" else "final_ready"),
        )


def _decode_predecessor_ids(row: DebateTurn) -> tuple[str, ...]:
    raw = getattr(row, "predecessor_turn_ids_json", "[]")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError("predecessor turn IDs are not valid JSON") from exc
    if not isinstance(payload, list) or not all(isinstance(item, str) and item for item in payload):
        raise ValueError("predecessor turn IDs have an invalid shape")
    return tuple(payload)


def generation_fence(db: Session, debate: Any, turn: Any) -> PreparedGenerationFence:
    """Compute the exact final-ready prefix identity before a provider call.

    This is intentionally a read-only helper.  The caller uses the returned
    IDs/hash/cutoff as the values in its single SQL completion CAS; a later
    predecessor mutation therefore cannot be mistaken for the context that a
    provider actually saw.
    """

    if not isinstance(db, Session):
        raise ValueError("generation fencing requires a database Session")
    debate_id = str(getattr(debate, "id", ""))
    turn_id = str(getattr(turn, "id", ""))
    if not debate_id or not turn_id:
        raise ValueError("generation fencing requires debate and turn IDs")
    rows = list(
        db.scalars(
            select(DebateTurn)
            .where(DebateTurn.debate_id == debate_id)
            .order_by(DebateTurn.turn_index, DebateTurn.id)
        ).all()
    )
    current = next((row for row in rows if str(row.id) == turn_id), None)
    if current is None:
        raise ValueError("planned turn is unavailable")
    if any(row.turn_index != index for index, row in enumerate(rows)):
        raise ValueError("persisted turn plan indexes are not contiguous")
    is_mutual = str(getattr(debate, "rule_set_id", "")) == MUTUAL_LEARNING_RULE_SET_ID
    if is_mutual:
        round_count = SqlTurnPreparer._round_count(debate)
        if int(current.round_no) > round_count:
            raise ValueError("turn round exceeds the frozen mutual-learning plan")
    expected_rows = (
        [row for row in rows if int(row.round_no) < int(current.round_no)]
        if is_mutual
        else rows[: current.turn_index]
    )
    expected_ids = tuple(str(row.id) for row in expected_rows)
    if _decode_predecessor_ids(current) != expected_ids:
        raise ValueError("persisted turn predecessor prefix is not exact")
    predecessors = tuple(SqlTurnPreparer._final_ready(db, row) for row in expected_rows)
    for index, predecessor in enumerate(predecessors):
        if is_mutual:
            expected_predecessors = tuple(
                item.turn_id for item in predecessors if item.round_no < predecessor.round_no
            )
        else:
            expected_predecessors = tuple(item.turn_id for item in predecessors[:index])
        if predecessor.predecessor_turn_ids != expected_predecessors:
            raise ValueError("a predecessor has a stale predecessor prefix")
        expected_cutoff = (
            max(
                (item.turn_index for item in predecessors if item.round_no < predecessor.round_no),
                default=-1,
            )
            if is_mutual
            else index - 1
        )
        if predecessor.cutoff_turn_index != expected_cutoff:
            raise ValueError("a predecessor has a stale cutoff index")
        if is_mutual:
            from app.modules.debates.generation.mutual_learning_prompts import (
                compute_mutual_transcript_hash,
            )

            visible = tuple(item for item in predecessors if item.round_no < predecessor.round_no)
            expected_predecessor_hash = compute_mutual_transcript_hash(visible)
        else:
            expected_predecessor_hash = compute_transcript_hash(predecessors[:index])
        if predecessor.transcript_hash != expected_predecessor_hash:
            raise ValueError("a predecessor has a stale transcript hash")
    if is_mutual:
        from app.modules.debates.generation.mutual_learning_prompts import (
            compute_mutual_transcript_hash,
        )

        transcript_hash = compute_mutual_transcript_hash(predecessors)
    else:
        transcript_hash = compute_transcript_hash(predecessors)
    stored_hash = getattr(current, "transcript_hash", None)
    if stored_hash is not None and str(stored_hash) != transcript_hash:
        raise ValueError("persisted turn transcript hash does not match its prefix")
    stored_cutoff = getattr(current, "cutoff_turn_index", None)
    expected_cutoff = (
        max((int(row.turn_index) for row in expected_rows), default=-1)
        if is_mutual
        else current.turn_index - 1
    )
    if stored_cutoff is not None and int(stored_cutoff) != expected_cutoff:
        raise ValueError("persisted turn cutoff does not match its prefix")
    return PreparedGenerationFence(
        predecessor_turn_ids=expected_ids,
        transcript_hash=transcript_hash,
        cutoff_turn_index=expected_cutoff,
        attempt=1,
    )


__all__ = ["SqlSnapshotSearch", "SqlTurnPreparer", "generation_fence"]
