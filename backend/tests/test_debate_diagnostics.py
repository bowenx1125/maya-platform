"""The teacher-only per-Agent Debate diagnostics read, end to end on Mock providers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from app.modules.debates.generation.four_round import turn_unit_cap
from app.modules.debates.generation_params import RULESET_CONTRACT_V4
from app.modules.debates.models import Debate, DebateParticipant, DebateTurn
from app.modules.debates.teaching_rules import frozen_speech_length
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.test_wave2_playback import COURSE_ID, GROUP_DEMO_ID, _headers, _insert_published_agent

TOPIC = "Should schools teach with classroom debates?"
ALPHA_EVIDENCE = (
    "Classroom debates make students state a claim, give a reason and answer a challenge. "
    "Teachers report that students who debate weekly revise their own position more often."
)
BETA_EVIDENCE = (
    "Debates can reward confident speakers over careful ones. Quiet students need written "
    "preparation time before they speak in front of the class."
)


def _create_previewed_debate(app, database) -> tuple[TestClient, str, str]:
    client = TestClient(app)
    client.__enter__()
    alpha = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Diagnostics Alpha", evidence=ALPHA_EVIDENCE
    )
    beta = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Diagnostics Beta", evidence=BETA_EVIDENCE
    )
    _session, csrf = login(client)
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=_headers(csrf, **{"Idempotency-Key": f"diagnostics-create-{uuid4()}"}),
        json={
            "topic": TOPIC,
            "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
            "participants": [
                {"agent_id": alpha, "stance_mode": "assigned", "assigned_stance": "support"},
                {"agent_id": beta, "stance_mode": "assigned", "assigned_stance": "oppose"},
            ],
            "round_count": 4,
            "output_language": "en",
            "round_unit_caps": [200, 200, 200, 200]
        },
    )
    assert response.status_code == 201, response.text
    debate_id = response.json()["id"]
    scheduler = app.state.prewarm_scheduler
    for preview_id, ready in scheduler._plan(debate_id):
        if not ready:
            assert client.portal is not None
            client.portal.call(scheduler._prepare, debate_id, preview_id)
    return client, csrf, debate_id


def _first_turn(database, debate_id: str) -> DebateTurn:
    with database.session() as db:
        turn = db.scalar(
            select(DebateTurn)
            .where(DebateTurn.debate_id == debate_id)
            .order_by(DebateTurn.turn_index)
        )
        assert turn is not None
        db.expunge(turn)
        return turn


def _rewrite_first_turn(database, debate_id: str, *, quote: str, attempt: int = 1) -> str:
    """Give the first turn a known two-paragraph speech citing its own chunk."""

    turn = _first_turn(database, debate_id)
    with database.session() as db:
        row = db.get(DebateTurn, turn.id)
        receipts = json.loads(row.retrieval_receipts_json)
        assert receipts, "the Mock preview retrieved the Agent's chunk"
        cited = receipts[0]["evidence_id"]
        segments = [
            {"text": quote, "source_ids": [cited], "reply_to": None, "support_mode": "direct"},
            {
                "text": "My own view adds a reason no source gives here.",
                "source_ids": [],
                "reply_to": None,
                "support_mode": "no_match",
            },
        ]
        row.speech = "\n\n".join(item["text"] for item in segments)
        row.structured_json = json.dumps(
            {"schema_version": "segment_turn_v2", "segments": segments}
        )
        row.attempt = attempt
        row.updated_at = datetime.now(UTC)
        db.commit()
        return row.id


def test_teacher_reads_per_agent_diagnostics_for_a_v4_debate(app_factory) -> None:
    app, database, _settings = app_factory()
    client, _csrf, debate_id = _create_previewed_debate(app, database)
    try:
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            snapshot = json.loads(debate.rule_snapshot_json)
            snapshot["contract_version"] = RULESET_CONTRACT_V4
            snapshot["target_minutes"] = 5
            snapshot.pop("round_unit_caps", None)
            snapshot.pop("over_length_ratio", None)
            snapshot.pop("repair_feedback_version", None)
            debate.rule_snapshot_json = json.dumps(snapshot)
            db.commit()
        turn_id = _rewrite_first_turn(
            database,
            debate_id,
            quote=(
                "Students who debate weekly revise their own position more often, "
                "as teachers report."
            ),
            attempt=2,
        )
        response = client.get(f"/api/v1/debates/{debate_id}/diagnostics")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["debate_id"] == debate_id
        assert body["unit"] == "words" and body["output_language"] == "en"
        assert body["length_capped"] is True
        assert [agent["agent_name"] for agent in body["agents"]] == [
            "Diagnostics Alpha",
            "Diagnostics Beta",
        ]
        alpha = body["agents"][0]
        with database.session() as db:
            participant = db.scalar(
                select(DebateParticipant).where(
                    DebateParticipant.debate_id == debate_id,
                    DebateParticipant.order_index == 0,
                )
            )
            assert participant is not None
            assert alpha["agent_md_chars"] == len(participant.agent_md_snapshot or "")
        assert alpha["knowledge_documents"] == 1
        assert alpha["knowledge_chunks"] == 1
        # One chunk in the snapshot: every retrieval returns that same chunk.
        assert alpha["distinct_chunks"] == 1
        assert alpha["retrievals"] >= len(alpha["rounds"])
        first = alpha["rounds"][0]
        assert first["turn_id"] == turn_id
        assert first["round_no"] == 1
        assert first["repaired"] is True
        with database.session() as db:
            minutes, rate = frozen_speech_length(db.get(Debate, debate_id).rule_snapshot_json)
        assert minutes is not None
        assert first["unit_cap"] == turn_unit_cap(
            "en", minutes=minutes, voice_rate=rate, participants=2, round_number=1
        )
        assert first["speech_units"] > 0
        assert first["repeats_earlier_share"] is None
        assert first["retrieved"][0]["cited"] is True
        assert first["retrieved"][0]["chunk_chars"] == len(ALPHA_EVIDENCE)
        assert first["retrieved"][0]["source_filename"] == "diagnostics alpha-evidence.md"
        quoted, own = first["paragraphs"]
        assert (quoted["self_label"], quoted["grounding_class"]) == ("direct", "quoted")
        assert quoted["cited_sources"] == 1 and quoted["coverage"] > 0.5
        assert (own["self_label"], own["grounding_class"], own["coverage"]) == (
            "no_match",
            None,
            None,
        )
        assert 0 < first["traced_share"] < 1
        assert alpha["grounding_counts"]["quoted"] >= 1
        later = alpha["rounds"][1:]
        assert later and all(item["repeats_earlier_share"] is not None for item in later)
        assert [item["round_no"] for item in alpha["rounds"]] == sorted(
            item["round_no"] for item in alpha["rounds"]
        )
    finally:
        client.__exit__(None, None, None)
        database.dispose()


def test_a_pre_v4_debate_has_no_cap_and_unchanged_rows(app_factory) -> None:
    app, database, _settings = app_factory()
    client, _csrf, debate_id = _create_previewed_debate(app, database)
    try:
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            snapshot = json.loads(debate.rule_snapshot_json)
            snapshot["contract_version"] = "ruleset_contract_v3"
            snapshot.pop("target_minutes", None)
            debate.rule_snapshot_json = json.dumps(snapshot)
            turns = db.scalars(select(DebateTurn).where(DebateTurn.debate_id == debate_id)).all()
            before = {
                row.id: (row.speech, row.structured_json, row.retrieval_receipts_json)
                for row in turns
            }
            db.commit()
        response = client.get(f"/api/v1/debates/{debate_id}/diagnostics")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["length_capped"] is False
        rounds = [item for agent in body["agents"] for item in agent["rounds"]]
        assert rounds and all(item["unit_cap"] is None for item in rounds)
        with database.session() as db:
            turns = db.scalars(select(DebateTurn).where(DebateTurn.debate_id == debate_id)).all()
            assert {
                row.id: (row.speech, row.structured_json, row.retrieval_receipts_json)
                for row in turns
            } == before
    finally:
        client.__exit__(None, None, None)
        database.dispose()


def test_a_turn_saved_before_paragraphs_existed_reports_no_grounding(app_factory) -> None:
    app, database, _settings = app_factory()
    client, _csrf, debate_id = _create_previewed_debate(app, database)
    try:
        turn = _first_turn(database, debate_id)
        with database.session() as db:
            row = db.get(DebateTurn, turn.id)
            row.structured_json = json.dumps({"claims": []})
            db.commit()
        body = client.get(f"/api/v1/debates/{debate_id}/diagnostics").json()
        first = body["agents"][0]["rounds"][0]
        assert first["paragraphs"] is None and first["traced_share"] is None
        assert all(item["cited"] is False for item in first["retrieved"])
    finally:
        client.__exit__(None, None, None)
        database.dispose()


def test_only_the_course_teacher_reads_diagnostics(app_factory) -> None:
    app, database, _settings = app_factory()
    client, csrf, debate_id = _create_previewed_debate(app, database)
    try:
        assert client.get(f"/api/v1/debates/{uuid4()}/diagnostics").status_code == 404
        client.post("/api/v1/auth/logout", headers=_headers(csrf))
        assert client.get(f"/api/v1/debates/{debate_id}/diagnostics").status_code == 401
        for student in ("bowen", "kaikai"):
            login(client, student)
            response = client.get(f"/api/v1/debates/{debate_id}/diagnostics")
            assert response.status_code in {403, 404}, response.text
            assert "agents" not in response.json()
        login(client)
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            debate.deleted_at = datetime.now(UTC)
            db.commit()
        assert client.get(f"/api/v1/debates/{debate_id}/diagnostics").status_code == 404
    finally:
        client.__exit__(None, None, None)
        database.dispose()


def test_a_citation_without_a_stored_receipt_fails_closed(app_factory) -> None:
    app, database, _settings = app_factory()
    client, _csrf, debate_id = _create_previewed_debate(app, database)
    try:
        turn = _first_turn(database, debate_id)
        with database.session() as db:
            row = db.get(DebateTurn, turn.id)
            row.structured_json = json.dumps(
                {
                    "schema_version": "segment_turn_v2",
                    "segments": [
                        {"text": row.speech, "source_ids": ["evidence-missing"], "reply_to": None}
                    ],
                }
            )
            db.commit()
        response = client.get(f"/api/v1/debates/{debate_id}/diagnostics")
        assert response.status_code == 409
        assert response.json()["code"] == "invalid_state"
    finally:
        client.__exit__(None, None, None)
        database.dispose()
