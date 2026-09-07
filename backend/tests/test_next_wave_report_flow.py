"""A completed paragraph classroom spends no report call before the Bench action."""

import hashlib
import json
from uuid import uuid4

import pytest
from app.core.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSnapshot, SnapshotDocument
from app.modules.debates.models import Debate, DebateParticipant, DebateTurn, TurnSource
from app.modules.reports import service as reports_service
from app.modules.reports.models import CivilizationReportRevision
from app.modules.reports.service import process_insight_job, regenerate_report
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from tests.test_wave3_reports import TEACHER_ID, _finalize_interaction


def test_segment_report_grading_uses_turn_local_sources_before_chunk_dedup(app_factory):
    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    with TestClient(app):
        debate_id, snapshot_id = _finalize_interaction(database, settings, barrages=())
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            assert debate is not None
            rule = json.loads(debate.rule_snapshot_json)
            rule["turn_protocol"] = "segments_v2"
            debate.rule_snapshot_json = json.dumps(rule)
            participants = db.scalars(
                select(DebateParticipant)
                .where(DebateParticipant.debate_id == debate_id)
                .order_by(DebateParticipant.order_index)
            ).all()
            participant_a = participants[0]
            snapshot = db.get(KnowledgeSnapshot, participant_a.knowledge_snapshot_id)
            assert snapshot is not None
            turns = db.scalars(
                select(DebateTurn)
                .where(DebateTurn.debate_id == debate_id)
                .order_by(DebateTurn.turn_index)
            ).all()
            assert len(turns) == 4
            now = snapshot.created_at
            document_id = str(uuid4())
            snapshot_document_id = str(uuid4())
            chunk_id = str(uuid4())
            db.add(
                KnowledgeDocument(
                    id=document_id,
                    group_id=participant_a.group_id,
                    source_filename="shared.md",
                    stored_file_id=snapshot.stored_file_id,
                    char_count=30,
                    index_status="ready",
                    index_revision=1,
                    workspace_state="active",
                    content_hash="e" * 64,
                    created_at=now,
                    updated_at=now,
                )
            )
            db.add(
                SnapshotDocument(
                    id=snapshot_document_id,
                    snapshot_id=snapshot.id,
                    document_id=document_id,
                    stored_file_id=snapshot.stored_file_id,
                    source_filename="shared.md",
                    char_count=30,
                    order_index=0,
                )
            )
            db.flush()
            db.add(
                KnowledgeChunk(
                    id=chunk_id,
                    snapshot_id=snapshot.id,
                    snapshot_document_id=snapshot_document_id,
                    document_id=document_id,
                    chunk_index=0,
                    chunk_text="The shared record gives one bounded fact.",
                    start_offset=0,
                    end_offset=39,
                    embedding_blob=b"fixture",
                    embedding_dimension=256,
                    embedding_key="mock-sha256-v1",
                )
            )
            db.flush()
            db.execute(
                delete(TurnSource).where(TurnSource.turn_id.in_([turn.id for turn in turns]))
            )
            source_by_turn: dict[str, str] = {}
            for turn in turns:
                if turn.participant_id == participant_a.id and turn.round_no == 1:
                    turn.speech = "The record gives one bounded fact."
                    turn.structured_json = json.dumps(
                        {
                            "schema_version": "segment_turn_v2",
                            "segments": [
                                {
                                    "text": turn.speech,
                                    "source_ids": ["evidence-a-one"],
                                    "reply_to": None,
                                    "support_mode": "direct",
                                }
                            ],
                        }
                    )
                    source_by_turn[turn.id] = "evidence-a-one"
                elif turn.participant_id == participant_a.id:
                    turn.speech = "The shared record gives useful background."
                    turn.structured_json = json.dumps(
                        {
                            "schema_version": "segment_turn_v2",
                            "segments": [
                                {
                                    "text": turn.speech,
                                    "source_ids": ["evidence-a-two"],
                                    "reply_to": None,
                                    "support_mode": "contextual",
                                }
                            ],
                        }
                    )
                    source_by_turn[turn.id] = "evidence-a-two"
                else:
                    turn.speech = "I need more evidence before making a claim."
                    turn.structured_json = json.dumps(
                        {
                            "schema_version": "segment_turn_v2",
                            "segments": [
                                {
                                    "text": turn.speech,
                                    "source_ids": [],
                                    "reply_to": None,
                                    "support_mode": "no_match",
                                }
                            ],
                        }
                    )
                turn.retrieval_status = "matched" if turn.id in source_by_turn else "no_match"
                turn.grounding_mode = (
                    "rag_grounded" if turn.id in source_by_turn else "general_reasoning"
                )
                turn.word_count = len(turn.speech.split())
            for turn_id, evidence_id in source_by_turn.items():
                db.add(
                    TurnSource(
                        id=str(uuid4()),
                        turn_id=turn_id,
                        participant_id=participant_a.id,
                        snapshot_id=snapshot.id,
                        chunk_id=chunk_id,
                        evidence_id=evidence_id,
                        source_filename="shared.md",
                        rank=1,
                        score=0.9,
                        created_at=now,
                    )
                )
            frozen = {
                "version": "final_input_v1",
                "generation": debate.cancellation_generation,
                "language": debate.output_language,
                "barrages": [],
                "message_ids": [],
            }
            debate.final_input_json = json.dumps(frozen)
            debate.final_input_hash = hashlib.sha256(debate.final_input_json.encode()).hexdigest()
        with database.session() as db:
            process_insight_job(db, snapshot_id)
        with database.session() as db:
            context = reports_service._report_context(db, debate_id)
            assert context.score_summary is not None
            scores = {item.slot: item for item in context.score_summary.agents}
            assert scores["A"].total_points == 7
            assert scores["A"].direct_count == 1
            assert scores["A"].contextual_count == 1
            assert scores["B"].no_match_count == 2
            assert len(context.sources) == 1
            assert len(context.manifest.turn_sources) == 1
            first_turn_evidence = context.manifest.turns[0].used_evidence_ids
            second_turn_evidence = context.manifest.turns[2].used_evidence_ids
            assert first_turn_evidence == second_turn_evidence
            assert first_turn_evidence in (["evidence-a-one"], ["evidence-a-two"])


@pytest.mark.parametrize("request_before_insight", [False, True])
def test_report_is_explicit_and_waits_for_local_insight(app_factory, request_before_insight):
    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    try:
        with TestClient(app):
            debate_id, snapshot_id = _finalize_interaction(database, settings, barrages=())
            with database.session() as db:
                debate = db.get(Debate, debate_id)
                rule = json.loads(debate.rule_snapshot_json)
                rule["turn_protocol"] = "segments_v2"
                debate.rule_snapshot_json = json.dumps(rule)
                turns = db.scalars(
                    select(DebateTurn).where(DebateTurn.debate_id == debate_id)
                ).all()
                db.execute(delete(TurnSource).where(TurnSource.turn_id.in_([t.id for t in turns])))
                for turn in turns:
                    turn.structured_json = json.dumps(
                        {
                            "schema_version": "segment_turn_v2",
                            "segments": [{"text": turn.speech, "source_ids": [], "reply_to": None}],
                        }
                    )
                frozen = {
                    "version": "final_input_v1",
                    "generation": debate.cancellation_generation,
                    "language": debate.output_language,
                    "barrages": [],
                    "message_ids": [],
                }
                debate.final_input_json = json.dumps(frozen)
                debate.final_input_hash = hashlib.sha256(
                    debate.final_input_json.encode()
                ).hexdigest()
            key = str(uuid4())
            if request_before_insight:
                with database.session() as db:
                    requested = regenerate_report(
                        db, actor_user_id=TEACHER_ID, debate_id=debate_id, idempotency_key=key
                    )
                    assert requested.generation_status == "generating"
                    assert db.scalar(select(CivilizationReportRevision)) is None
            with database.session() as db:
                process_insight_job(db, snapshot_id)
            if not request_before_insight:
                with database.session() as db:
                    assert db.scalar(select(CivilizationReportRevision)) is None
                    regenerate_report(
                        db, actor_user_id=TEACHER_ID, debate_id=debate_id, idempotency_key=key
                    )
            with database.session() as db:
                rows = db.scalars(select(CivilizationReportRevision)).all()
                assert len(rows) == 1
                assert (
                    json.loads(rows[0].input_manifest_json)["manifest_version"]
                    == "report_input_manifest_v2"
                )
                regenerate_report(
                    db, actor_user_id=TEACHER_ID, debate_id=debate_id, idempotency_key=key
                )
                assert len(db.scalars(select(CivilizationReportRevision)).all()) == 1
    finally:
        database.dispose()
