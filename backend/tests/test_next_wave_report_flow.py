"""A completed paragraph classroom spends no report call before the Bench action."""

import hashlib
import json
from uuid import uuid4

import pytest
from app.modules.debates.models import Debate, DebateTurn, TurnSource
from app.modules.reports.models import CivilizationReportRevision
from app.modules.reports.service import process_insight_job, regenerate_report
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from tests.test_wave3_reports import TEACHER_ID, _finalize_interaction


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
