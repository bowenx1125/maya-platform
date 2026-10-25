import json
from types import SimpleNamespace

import pytest
from app.modules.debates.source_lineage import receipt_scope_is_valid
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tests.postgres_db import new_database_url


@pytest.fixture
def evidence_origin():
    engine = create_engine(new_database_url(schema=False))
    with Session(engine) as db:
        db.execute(text("CREATE TABLE debates (id TEXT, rule_snapshot_json TEXT)"))
        db.execute(
            text(
                "CREATE TABLE debate_turns (id TEXT, debate_id TEXT, turn_index INTEGER, "
                "generation_status TEXT, preparation_stage TEXT, knowledge_snapshot_id TEXT, "
                "participant_id TEXT, structured_json TEXT, retrieval_receipts_json TEXT)"
            )
        )
        db.execute(
            text(
                "CREATE TABLE turn_sources (turn_id TEXT, participant_id TEXT, snapshot_id TEXT, "
                "chunk_id TEXT, evidence_id TEXT)"
            )
        )
        receipt = {
            "snapshot_id": "knowledge-a",
            "chunk_id": "chunk-a",
            "evidence_id": "evidence-a",
            "text": "The dated record describes a change.",
            "source_filename": "record.md",
            "query_hash": "a" * 64,
            "rank": 1,
        }
        db.execute(
            text("INSERT INTO debates VALUES ('debate', :rule)"),
            {
                "rule": json.dumps({"teaching_protocol": "four_round_v1"}),
            },
        )
        db.execute(
            text(
                "INSERT INTO debate_turns VALUES ('first', 'debate', 0, 'final_ready', 'ready', "
                "'knowledge-a', 'agent-a', :structured, :receipts)"
            ),
            {
                "structured": json.dumps({"segments": [{"source_ids": ["evidence-a"]}]}),
                "receipts": json.dumps([receipt]),
            },
        )
        db.execute(
            text(
                "INSERT INTO turn_sources VALUES "
                "('first','agent-a','knowledge-a','chunk-a','evidence-a')"
            )
        )
        current = SimpleNamespace(
            debate_id="debate",
            knowledge_snapshot_id="knowledge-b",
            turn_index=2,
            predecessor_turn_ids_json='["first"]',
        )
        yield db, current, receipt


def test_another_agents_knowledge_is_not_readable(evidence_origin):
    db, turn, receipt = evidence_origin
    assert not receipt_scope_is_valid(db, turn, receipt)


@pytest.mark.parametrize("state", ["running", "failed", "pending"])
def test_unfinished_origin_is_never_public_evidence(evidence_origin, state):
    db, turn, receipt = evidence_origin
    db.execute(text("UPDATE debate_turns SET generation_status=:state"), {"state": state})
    assert not receipt_scope_is_valid(db, turn, receipt)


def test_legacy_scope_and_cross_debate_barriers_remain(evidence_origin):
    db, turn, receipt = evidence_origin
    db.execute(text("UPDATE debates SET rule_snapshot_json='{}'"))
    assert not receipt_scope_is_valid(db, turn, receipt)
    turn.knowledge_snapshot_id = "knowledge-a"
    assert receipt_scope_is_valid(db, turn, receipt)


def test_other_debate_or_unselected_source_is_not_an_origin(evidence_origin):
    db, turn, receipt = evidence_origin
    db.execute(text("UPDATE debate_turns SET debate_id='other'"))
    assert not receipt_scope_is_valid(db, turn, receipt)
    db.execute(text("UPDATE debate_turns SET debate_id='debate', structured_json='{}'"))
    assert not receipt_scope_is_valid(db, turn, receipt)


def test_public_projection_excludes_discussion_metadata(evidence_origin):
    from app.modules.debates.setup.segment_projection import segment_projection

    db, _turn, _receipt = evidence_origin
    db.execute(
        text("CREATE TABLE llm_recovery_inputs (turn_id TEXT, input_json TEXT, attempt_no INTEGER)")
    )
    speech = "The evidence narrows my claim."
    raw = {
        "schema_version": "segment_turn_v2",
        "segments": [{"text": speech, "source_ids": [], "reply_to": None}],
        "discussion_memory": {
            "position": "A bounded claim",
            "change": "qualified",
            "reason": "One dated case",
            "influence": None,
            "unresolved_question": "Another independent case?",
        },
    }
    result, sources = segment_projection(
        db,
        SimpleNamespace(
            id="response",
            speech=speech,
            structured_json=json.dumps(raw),
            retrieval_receipts_json="[]",
        ),
        SimpleNamespace(version_label="v1"),
    )
    assert result is not None
    assert set(result.model_dump()) == {"schema_version", "segments"}
    assert result.segments[0].text == speech
    assert sources == []


def test_retained_question_is_not_counted_as_public_speech():
    from app.modules.debates.generation.segments import StoredSegment, StoredSegmentTurnResult
    from app.modules.debates.playback.generation_adapter import _prepared_word_count

    speech = "Which dated record supports this claim?"
    result = StoredSegmentTurnResult(
        segments=(StoredSegment(text=speech, source_ids=(), reply_to=None),),
        speech=speech,
        question={"target_agent_id": "agent-b", "text": "Which dated record supports this claim?"},
    )
    final = SimpleNamespace(speech=speech, structured=result)
    assert _prepared_word_count(final, "en") == 6
    assert _prepared_word_count(final, "zh") == len(speech.replace(" ", ""))
