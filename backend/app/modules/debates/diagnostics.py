"""Teacher-only per-Agent diagnostics for one Debate, computed from stored rows.

Everything here is read from what a Debate already keeps: the frozen Agent.md
and knowledge snapshot of each participant, and each generated turn's speech,
paragraphs, retrieval receipts and attempt. Nothing is written and no provider
is called, so it works the same for a Debate created before this read existed.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import invalid_state, not_found
from app.core.models import KnowledgeChunk, SnapshotDocument
from app.modules.debates.generation.four_round import (
    ROUND_WEIGHTS,
    TEACHING_PROTOCOL,
    speech_units,
    turn_unit_cap,
)
from app.modules.debates.generation.segments import (
    SegmentProtocolError,
    load_stored_segment_turn_result,
    self_repetition_ratio,
)
from app.modules.debates.generation_params import uses_code_contract
from app.modules.debates.grounding import GroundingClass, matched_gram_flags, measure_grounding
from app.modules.debates.models import Debate, DebateParticipant, DebateTurn
from app.modules.debates.output_language import debate_output_language
from app.modules.debates.round_count import debate_teaching_protocol
from app.modules.debates.setup.service import require_teacher_course
from app.modules.debates.teaching_rules import (
    DEFAULT_TARGET_MINUTES,
    frozen_llm_settings,
    frozen_speech_length,
)

_GENERATED = ("final_ready", "ready", "completed")


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RetrievedChunkDiagnostic(_Closed):
    chunk_id: str
    source_filename: str
    rank: int
    score: float
    chunk_chars: int
    cited: bool


class ParagraphDiagnostic(_Closed):
    units: int
    cited_sources: int
    self_label: Literal["direct", "contextual", "no_match"] | None
    grounding_class: GroundingClass | None
    coverage: float | None
    longest_run: int | None


class RoundDiagnostic(_Closed):
    turn_id: str
    round_no: int
    turn_index: int
    speech_units: int
    unit_cap: int | None
    repaired: bool
    retrieved: list[RetrievedChunkDiagnostic]
    paragraphs: list[ParagraphDiagnostic] | None
    traced_share: float | None
    repeats_earlier_share: float | None


class GroundingCounts(_Closed):
    quoted: int
    paraphrased: int
    not_found: int
    other_language: int


class AgentDiagnostic(_Closed):
    participant_id: str
    agent_name: str
    slot: str
    agent_md_chars: int | None
    knowledge_documents: int
    knowledge_chunks: int
    retrievals: int
    distinct_chunks: int
    cited_chunks: int
    traced_share: float | None
    grounding_counts: GroundingCounts
    rounds: list[RoundDiagnostic]


class DebateDiagnostics(_Closed):
    debate_id: str
    output_language: Literal["zh", "en"]
    unit: Literal["han_chars", "words"]
    length_capped: bool
    agents: list[AgentDiagnostic]


def _receipts(turn: DebateTurn) -> list[Mapping[str, Any]]:
    rows = json.loads(turn.retrieval_receipts_json or "[]")
    if not isinstance(rows, list):
        raise ValueError("receipts are not a list")
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or not isinstance(row.get("evidence_id"), str)
            or not isinstance(row.get("chunk_id"), str)
            or not isinstance(row.get("source_filename"), str)
            or not isinstance(row.get("text"), str)
            or isinstance(row.get("rank"), bool)
            or not isinstance(row.get("rank"), int)
            or isinstance(row.get("score"), bool)
            or not isinstance(row.get("score"), (int, float))
        ):
            raise ValueError("receipt shape is invalid")
    return rows


def _segments(turn: DebateTurn) -> list[Any] | None:
    """Stored v2 paragraphs, or None for a turn saved before paragraphs existed."""

    if not turn.structured_json:
        return None
    raw = json.loads(turn.structured_json)
    if not isinstance(raw, Mapping) or raw.get("schema_version") != "segment_turn_v2":
        return None
    return list(load_stored_segment_turn_result(raw).segments)


def _share(matched: int, total: int) -> float | None:
    return round(matched / total, 4) if total else None


def _unit_cap(
    debate: Debate, language: Literal["zh", "en"], participants: int, round_no: int
) -> int | None:
    """The task.max_units this turn was sent, recomputed the way segments.py did."""

    if (
        debate_teaching_protocol(debate) != TEACHING_PROTOCOL
        or not uses_code_contract(frozen_llm_settings(debate.rule_snapshot_json))
        or round_no not in ROUND_WEIGHTS
    ):
        return None
    minutes, voice_rate = frozen_speech_length(debate.rule_snapshot_json)
    return turn_unit_cap(
        language,
        minutes=minutes or DEFAULT_TARGET_MINUTES,
        voice_rate=voice_rate,
        participants=participants,
        round_number=round_no,
    )


def _round(
    turn: DebateTurn,
    *,
    debate: Debate,
    language: Literal["zh", "en"],
    participants: int,
    earlier: Sequence[str],
    grounding_counts: Counter[GroundingClass],
) -> tuple[RoundDiagnostic, int, int, list[str], set[str]]:
    speech = turn.speech or ""
    receipts = _receipts(turn)
    by_id = {str(row["evidence_id"]): row for row in receipts}
    segments = _segments(turn)
    cited_ids = {source for segment in segments or () for source in segment.source_ids}
    if any(source not in by_id for source in cited_ids):
        raise ValueError("a paragraph cites a source the turn did not retrieve")
    paragraphs: list[ParagraphDiagnostic] | None = None
    matched_total = gram_total = 0
    if segments is not None:
        paragraphs = []
        for segment in segments:
            sources = [str(by_id[source]["text"]) for source in segment.source_ids]
            if sources:
                measured = measure_grounding(segment.text, sources, language)
                grounding_counts[measured.grounding_class] += 1
                matched_total += measured.matched_grams
                # An unmeasurable paragraph adds nothing to either side of the share.
                gram_total += measured.total_grams
            else:
                measured = None
                gram_total += len(matched_gram_flags(segment.text, (), language))
            paragraphs.append(
                ParagraphDiagnostic(
                    units=speech_units(segment.text, language),
                    cited_sources=len(sources),
                    self_label=segment.support_mode,
                    grounding_class=measured.grounding_class if measured else None,
                    coverage=round(measured.coverage, 4)
                    if measured and measured.grounding_class != "other_language"
                    else None,
                    longest_run=measured.longest_run
                    if measured and measured.grounding_class != "other_language"
                    else None,
                )
            )
    retrieved = [
        RetrievedChunkDiagnostic(
            chunk_id=str(row["chunk_id"]),
            source_filename=str(row["source_filename"]),
            rank=int(row["rank"]),
            score=round(float(row["score"]), 4),
            chunk_chars=len(str(row["text"])),
            cited=str(row["evidence_id"]) in cited_ids,
        )
        for row in receipts
    ]
    diagnostic = RoundDiagnostic(
        turn_id=turn.id,
        round_no=turn.round_no,
        turn_index=turn.turn_index,
        speech_units=speech_units(speech, language),
        unit_cap=_unit_cap(debate, language, participants, turn.round_no),
        repaired=turn.attempt > 1,
        retrieved=retrieved,
        paragraphs=paragraphs,
        traced_share=_share(matched_total, gram_total) if segments is not None else None,
        repeats_earlier_share=(
            round(self_repetition_ratio(speech, earlier, language), 4) if earlier else None
        ),
    )
    chunk_ids = [str(row["chunk_id"]) for row in receipts]
    cited_chunks = {str(by_id[source]["chunk_id"]) for source in cited_ids}
    return diagnostic, matched_total, gram_total, chunk_ids, cited_chunks


def debate_diagnostics(db: Session, *, actor_user_id: str, debate_id: str) -> DebateDiagnostics:
    debate = db.get(Debate, debate_id)
    if debate is None or debate.deleted_at is not None:
        raise not_found()
    require_teacher_course(db, actor_user_id, debate.course_id)
    language = debate_output_language(debate)
    participants = db.scalars(
        select(DebateParticipant)
        .where(DebateParticipant.debate_id == debate.id)
        .order_by(DebateParticipant.order_index)
    ).all()
    turns = db.scalars(
        select(DebateTurn)
        .where(
            DebateTurn.debate_id == debate.id,
            DebateTurn.generation_status.in_(_GENERATED),
        )
        .order_by(DebateTurn.turn_index)
    ).all()
    snapshot_ids = {item.knowledge_snapshot_id for item in participants}
    documents: dict[str, int] = {
        str(snapshot_id): int(count)
        for snapshot_id, count in db.execute(
            select(SnapshotDocument.snapshot_id, func.count())
            .where(SnapshotDocument.snapshot_id.in_(snapshot_ids))
            .group_by(SnapshotDocument.snapshot_id)
        ).all()
    }
    chunks: dict[str, int] = {
        str(snapshot_id): int(count)
        for snapshot_id, count in db.execute(
            select(KnowledgeChunk.snapshot_id, func.count())
            .where(KnowledgeChunk.snapshot_id.in_(snapshot_ids))
            .group_by(KnowledgeChunk.snapshot_id)
        ).all()
    }
    agents: list[AgentDiagnostic] = []
    try:
        for participant in participants:
            rounds: list[RoundDiagnostic] = []
            speeches: list[str] = []
            retrieved_ids: list[str] = []
            cited_ids: set[str] = set()
            matched = total = 0
            counts: Counter[GroundingClass] = Counter()
            for turn in turns:
                if turn.participant_id != participant.id or not (turn.speech or "").strip():
                    continue
                diagnostic, turn_matched, turn_total, chunk_ids, cited = _round(
                    turn,
                    debate=debate,
                    language=language,
                    participants=len(participants),
                    earlier=speeches,
                    grounding_counts=counts,
                )
                rounds.append(diagnostic)
                speeches.append(turn.speech or "")
                retrieved_ids.extend(chunk_ids)
                cited_ids |= cited
                matched += turn_matched
                total += turn_total
            agents.append(
                AgentDiagnostic(
                    participant_id=participant.id,
                    agent_name=participant.agent_name,
                    slot=participant.slot,
                    agent_md_chars=(
                        len(participant.agent_md_snapshot)
                        if participant.agent_md_snapshot is not None
                        else None
                    ),
                    knowledge_documents=int(documents.get(participant.knowledge_snapshot_id, 0)),
                    knowledge_chunks=int(chunks.get(participant.knowledge_snapshot_id, 0)),
                    retrievals=len(retrieved_ids),
                    distinct_chunks=len(set(retrieved_ids)),
                    cited_chunks=len(cited_ids),
                    traced_share=(
                        _share(matched, total)
                        if any(item.paragraphs is not None for item in rounds)
                        else None
                    ),
                    grounding_counts=GroundingCounts(
                        quoted=counts["quoted"],
                        paraphrased=counts["paraphrased"],
                        not_found=counts["not_found"],
                        other_language=counts["other_language"],
                    ),
                    rounds=rounds,
                )
            )
    except (ValueError, TypeError, KeyError, SegmentProtocolError) as exc:
        raise invalid_state("The saved turn sources are invalid.") from exc
    return DebateDiagnostics(
        debate_id=debate.id,
        output_language=language,
        unit="han_chars" if language == "zh" else "words",
        length_capped=any(item.unit_cap is not None for agent in agents for item in agent.rounds),
        agents=agents,
    )
