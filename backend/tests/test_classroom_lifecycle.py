"""Disposable SQL/API coverage for Destroy, Rebirth and current-turn recovery."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.core.models import DemoAcceptanceRun, ProviderOperation, StoredFile
from app.modules.debates.models import (
    AuditLog,
    Debate,
    DebateParticipant,
    DebateTurn,
    PlaybackState,
)
from app.modules.debates.playback.audio import AudioStore
from app.modules.debates.setup.rules import canonical_rule_snapshot_json
from app.modules.interactions.models import (
    BarrageMessage,
    ClassroomInteractionWindow,
    Vote,
)
from app.modules.interactions.tokens import issue_token
from app.modules.reports.models import (
    BarrageInsightSnapshot,
    CivilizationReport,
    CivilizationReportCurrentSuccess,
    CivilizationReportRevision,
)
from app.providers.tts import MockTTSProvider
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from tests.conftest import login
from tests.test_text_playback_fallback import _wait
from tests.test_wave2_playback import _headers
from tests.test_wave3_interactions import COURSE_ID, TEACHER_ID, _seed_finished_debate


def _saved_classroom(database, settings):
    debate_id, _ = _seed_finished_debate(database, rounds=4)
    audio = AudioStore(settings.resolved_data_root, tts_provider=MockTTSProvider())
    with database.session() as db:
        debate = db.get(Debate, debate_id)
        debate.rule_set_id = "ordered_multi_expert_mutual_learning_v1"
        debate.rule_snapshot_json = canonical_rule_snapshot_json(
            rule_set_id=debate.rule_set_id,
            round_count=4,
            turn_protocol="segments_v2",
            teaching_protocol="four_round_v1",
        )
        debate.status = "completed"
        debate.final_input_json = "{}"
        debate.final_input_hash = "a" * 64
        for turn in db.scalars(select(DebateTurn).where(DebateTurn.debate_id == debate_id)):
            turn.speech = f"Saved RAG classroom paragraph {turn.turn_index}."
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
            metadata = audio.synthesize_and_store(
                course_id=COURSE_ID,
                debate_id=debate_id,
                turn_id=turn.id,
                speech=turn.speech,
                voice_token="mock",
            )
            file_id = str(uuid4())
            db.add(
                StoredFile(
                    id=file_id,
                    kind="debate_audio",
                    relative_path=metadata.relative_path,
                    sha256=metadata.sha256,
                    size_bytes=metadata.size_bytes,
                    state="active",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            db.flush()
            turn.audio_file_id = file_id
            turn.audio_duration_ms = metadata.duration_ms
    with database.session() as db:
        db.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS debate_final_input_immutable "
                "BEFORE UPDATE ON debates "
                "WHEN OLD.final_input_json IS NOT NULL AND "
                "(NEW.final_input_json IS NOT OLD.final_input_json OR "
                "NEW.final_input_hash IS NOT OLD.final_input_hash OR "
                "NEW.final_frozen_at IS NOT OLD.final_frozen_at) "
                "BEGIN SELECT RAISE(ABORT, 'final_input_immutable'); END"
            )
        )
    return debate_id


def _body(client, debate_id):
    detail = client.get(f"/api/v1/debates/{debate_id}")
    assert detail.status_code == 200, detail.text
    value = detail.json()
    return {
        "expected_revision": value["revision"],
        "expected_control_version": value["playback"]["control_version"],
    }


@pytest.mark.parametrize("mode", ["live", "replay"])
@pytest.mark.parametrize("preview_media", ["audio", "text_fallback", "text_only"])
def test_rebirth_preserves_preview_clears_classroom_and_starts_again(
    app_factory, mode, preview_media
):
    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            _, csrf = login(client)
            with database.session() as db:
                playback = db.scalar(
                    select(PlaybackState).where(PlaybackState.debate_id == debate_id)
                )
                playback.mode = mode
                planned = list(
                    db.scalars(
                        select(DebateTurn)
                        .where(DebateTurn.debate_id == debate_id)
                        .order_by(DebateTurn.turn_index)
                    )
                )
                for turn in planned:
                    if turn.round_no < 4 and preview_media != "audio":
                        turn.audio_file_id = None
                        turn.audio_duration_ms = 0 if preview_media == "text_only" else None
                        turn.safe_error_code = (
                            "tts_voice_unavailable"
                            if preview_media == "text_only"
                            else "tts_timeout"
                        )
                    predecessors = planned[: turn.turn_index] if turn.round_no > 1 else []
                    turn.predecessor_turn_ids_json = json.dumps(
                        [item.id for item in predecessors], separators=(",", ":")
                    )
                    turn.cutoff_turn_index = predecessors[-1].turn_index if predecessors else -1
                before = [
                    (
                        t.id,
                        t.speech,
                        t.structured_json,
                        t.audio_file_id,
                        None if preview_media == "text_only" else t.audio_duration_ms,
                        t.safe_error_code,
                    )
                    for t in db.scalars(
                        select(DebateTurn)
                        .where(DebateTurn.debate_id == debate_id, DebateTurn.round_no < 4)
                        .order_by(DebateTurn.turn_index)
                    )
                ]
                final_ids = set(
                    db.scalars(
                        select(DebateTurn.id).where(
                            DebateTurn.debate_id == debate_id, DebateTurn.round_no == 4
                        )
                    )
                )
                window_id = db.scalar(
                    select(ClassroomInteractionWindow.id).where(
                        ClassroomInteractionWindow.debate_id == debate_id
                    )
                )
                provider_operations_before = list(db.scalars(select(ProviderOperation.id)))
            body = _body(client, debate_id)
            headers = _headers(csrf, **{"Idempotency-Key": str(uuid4())})
            result = client.post(f"/api/v1/debates/{debate_id}/rebirth", json=body, headers=headers)
            assert result.status_code == 200, result.text
            repeated = client.post(
                f"/api/v1/debates/{debate_id}/rebirth", json=body, headers=headers
            )
            assert repeated.status_code == 200, repeated.text
            with database.session() as db:
                after = [
                    (
                        t.id,
                        t.speech,
                        t.structured_json,
                        t.audio_file_id,
                        t.audio_duration_ms,
                        t.safe_error_code,
                    )
                    for t in db.scalars(
                        select(DebateTurn)
                        .where(DebateTurn.debate_id == debate_id, DebateTurn.round_no < 4)
                        .order_by(DebateTurn.turn_index)
                    )
                ]
                assert after == before
                assert list(db.scalars(select(ProviderOperation.id))) == provider_operations_before
                rebuilt = list(
                    db.scalars(
                        select(DebateTurn)
                        .where(DebateTurn.debate_id == debate_id)
                        .order_by(DebateTurn.turn_index)
                    )
                )
                for turn in rebuilt:
                    if turn.round_no == 4:
                        assert json.loads(turn.predecessor_turn_ids_json) == [
                            item.id for item in rebuilt[: turn.turn_index]
                        ]
                        assert turn.cutoff_turn_index == turn.turn_index - 1
                assert db.get(Debate, debate_id).final_input_json is None
                assert (
                    db.scalar(
                        text(
                            "SELECT 1 FROM sqlite_master WHERE name='debate_final_input_immutable'"
                        )
                    )
                    == 1
                )
                assert not set(
                    db.scalars(select(DebateTurn.id).where(DebateTurn.id.in_(final_ids)))
                )
                assert db.get(ClassroomInteractionWindow, window_id) is None
                assert (
                    len(
                        list(
                            db.scalars(
                                select(AuditLog).where(AuditLog.event_type == "debate.rebirth")
                            )
                        )
                    )
                    == 1
                )
            detail = client.get(f"/api/v1/debates/{debate_id}").json()
            assert detail["status"] == "draft"
            assert detail["preview"]["ready"]
            assert detail["public_turns"] == []
            assert not detail["final_input_frozen"]
            rows = client.get(f"/api/v1/courses/{COURSE_ID}/debates").json()
            summary = next(row for row in rows if row["id"] == debate_id)
            assert summary["status"] == "draft"
            assert summary["preview"]["ready"]
            started = client.post(
                f"/api/v1/debates/{debate_id}/start",
                json={
                    "expected_revision": detail["revision"],
                    "expected_current_audio_debate_id": None,
                    "confirm_previous_audio_cleanup": False,
                    "output_language": "en",
                },
                headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
            )
            assert started.status_code == 200, started.text
            if preview_media != "audio":
                detail = _wait(client, debate_id, lambda item: len(item["public_turns"]) == 1)
                assert detail["playback"]["status"] == "waiting_next"
                for count in range(2, 7):
                    state = detail["playback"]
                    assert state["next_turn_ready"]
                    advanced = client.post(
                        f"/api/v1/debates/{debate_id}/next",
                        json={
                            "expected_control_version": state["control_version"],
                            "expected_current_turn_id": state["current_turn_id"],
                        },
                        headers=_headers(csrf),
                    )
                    assert advanced.status_code == 200, advanced.text
                    detail = _wait(
                        client,
                        debate_id,
                        lambda item, count=count: len(item["public_turns"]) == count,
                    )
                    assert detail["playback"]["status"] == "waiting_next"
                assert all(turn["audio_ready"] is False for turn in detail["public_turns"])
                assert not detail["playback"]["next_turn_ready"]
                with database.session() as db:
                    assert (
                        list(db.scalars(select(ProviderOperation.id))) == provider_operations_before
                    )
                    assert (
                        db.scalar(
                            text(
                                "SELECT COUNT(*) FROM debate_events WHERE debate_id=:id "
                                "AND event_type='playback.waiting_next'"
                            ),
                            {"id": debate_id},
                        )
                        == 6
                    )
    finally:
        database.dispose()


def test_rebirth_clears_report_and_unbinds_acceptance_run_without_new_provider_calls(
    app_factory,
):
    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            _, csrf = login(client)
            report_id = str(uuid4())
            revision_id = str(uuid4())
            insight_id = str(uuid4())
            now = datetime.now(UTC)
            with database.session() as db:
                debate = db.get(Debate, debate_id)
                participant = db.scalar(
                    select(DebateParticipant)
                    .where(DebateParticipant.debate_id == debate_id)
                    .order_by(DebateParticipant.order_index)
                )
                window = db.scalar(
                    select(ClassroomInteractionWindow).where(
                        ClassroomInteractionWindow.debate_id == debate_id
                    )
                )
                assert debate is not None
                assert participant is not None
                assert window is not None
                db.add(
                    BarrageInsightSnapshot(
                        id=insight_id,
                        window_id=window.id,
                        debate_id=debate_id,
                        revision_no=1,
                        policy_key="mock_barrage_insight_v1",
                        status="ready",
                        attempt=1,
                        input_hash="1" * 64,
                        included_count=0,
                        filtered_count=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
                db.add(
                    CivilizationReport(
                        id=report_id,
                        debate_id=debate_id,
                        generation_status="ready",
                        latest_attempt_status="ready",
                        policy_key="mock_maya_report_v1",
                        created_at=now,
                        updated_at=now,
                    )
                )
                db.flush()
                db.add(
                    CivilizationReportRevision(
                        id=revision_id,
                        report_id=report_id,
                        debate_id=debate_id,
                        insight_snapshot_id=insight_id,
                        revision_no=1,
                        status="ready",
                        attempt=1,
                        input_manifest_json="{}",
                        input_manifest_hash="2" * 64,
                        english_markdown="A saved report.",
                        word_count=3,
                        trigger="automatic",
                        created_at=now,
                        updated_at=now,
                    )
                )
                db.flush()
                db.add(
                    CivilizationReportCurrentSuccess(
                        report_id=report_id,
                        revision_id=revision_id,
                        debate_id=debate_id,
                        revision_status="ready",
                    )
                )
                run_id = str(uuid4())
                db.add(
                    DemoAcceptanceRun(
                        id=run_id,
                        plan_version="real_core_demo_v2",
                        fixture_hash="3" * 64,
                        baseline_agent_id=participant.agent_id,
                        baseline_version_id=participant.agent_version_id,
                        baseline_snapshot_id=participant.knowledge_snapshot_id,
                        target_agent_id=participant.agent_id,
                        target_version_id=participant.agent_version_id,
                        debate_id=debate_id,
                        report_revision_id=revision_id,
                        state="executed",
                        starting_charged_requests=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
                db.flush()
                provider_operations_before = list(db.scalars(select(ProviderOperation.id)))
                preview_turn_ids_before = list(
                    db.scalars(
                        select(DebateTurn.id)
                        .where(DebateTurn.debate_id == debate_id, DebateTurn.round_no < 4)
                        .order_by(DebateTurn.turn_index)
                    )
                )

            result = client.post(
                f"/api/v1/debates/{debate_id}/rebirth",
                json=_body(client, debate_id),
                headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
            )
            assert result.status_code == 200, result.text

            with database.session() as db:
                assert db.get(CivilizationReport, report_id) is None
                assert db.get(CivilizationReportRevision, revision_id) is None
                assert db.get(CivilizationReportCurrentSuccess, report_id) is None
                assert db.get(BarrageInsightSnapshot, insight_id) is None
                run = db.get(DemoAcceptanceRun, run_id)
                assert run is not None
                assert run.report_revision_id is None
                assert list(db.scalars(select(ProviderOperation.id))) == provider_operations_before
                assert (
                    list(
                        db.scalars(
                            select(DebateTurn.id)
                            .where(DebateTurn.debate_id == debate_id, DebateTurn.round_no < 4)
                            .order_by(DebateTurn.turn_index)
                        )
                    )
                    == preview_turn_ids_before
                )
    finally:
        database.dispose()


def test_rebirth_returns_ready_and_rejects_leftover_collection(app_factory):
    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            _, csrf = login(client)
            now = datetime.now(UTC)
            with database.session() as db:
                window = db.scalar(
                    select(ClassroomInteractionWindow).where(
                        ClassroomInteractionWindow.debate_id == debate_id
                    )
                )
                participant = db.scalar(
                    select(DebateParticipant)
                    .where(DebateParticipant.debate_id == debate_id)
                    .order_by(DebateParticipant.order_index)
                )
                preview_turn = db.scalar(
                    select(DebateTurn)
                    .where(DebateTurn.debate_id == debate_id, DebateTurn.round_no < 4)
                    .order_by(DebateTurn.turn_index)
                )
                assert window is not None
                assert participant is not None
                assert preview_turn is not None
                preview_ids = list(
                    db.scalars(
                        select(DebateTurn.id)
                        .where(DebateTurn.debate_id == debate_id, DebateTurn.round_no < 4)
                        .order_by(DebateTurn.turn_index)
                    )
                )
                preview_speech = preview_turn.speech
                participant_id = participant.id
                window.status = "open"
                window.token_nonce = b"r" * 32
                window.opened_by = TEACHER_ID
                window.opened_at = now
                token = issue_token(window.id, bytes(window.token_nonce), settings.secret_bytes)
                old_window_id = window.id
                db.add(
                    BarrageMessage(
                        id=str(uuid4()),
                        window_id=window.id,
                        debate_id=debate_id,
                        turn_id=preview_turn.id,
                        nickname="Visitor",
                        raw_text="A saved classroom question.",
                        client_submission_id=str(uuid4()),
                        sequence=1,
                        submitted_at=now,
                    )
                )
                db.add(
                    Vote(
                        id=str(uuid4()),
                        window_id=window.id,
                        debate_id=debate_id,
                        participant_id=participant.id,
                        client_submission_id=str(uuid4()),
                        submitted_at=now,
                    )
                )
            result = client.post(
                f"/api/v1/debates/{debate_id}/rebirth",
                json=_body(client, debate_id),
                headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
            )
            assert result.status_code == 200, result.text
            detail = client.get(f"/api/v1/debates/{debate_id}")
            assert detail.status_code == 200, detail.text
            body = detail.json()
            assert body["status"] == "draft"
            assert body["preview"]["ready"] is True
            assert body["playback"]["status"] == "preparing"
            assert body["final_input_frozen"] is False
            assert body["public_turns"] == []
            rows = client.get(f"/api/v1/courses/{COURSE_ID}/debates").json()
            summary = next(row for row in rows if row["id"] == debate_id)
            assert summary["status"] == "draft"
            assert summary["preview"]["ready"] is True
            assert summary["preview"]["prepared_turns"] == summary["preview"]["expected_turns"]
            with database.session() as db:
                debate = db.get(Debate, debate_id)
                assert debate is not None
                assert debate.final_input_json is None
                assert debate.started_at is None
                assert debate.finished_at is None
                preview = list(
                    db.scalars(
                        select(DebateTurn)
                        .where(DebateTurn.debate_id == debate_id, DebateTurn.round_no < 4)
                        .order_by(DebateTurn.turn_index)
                    )
                )
                assert [turn.id for turn in preview] == preview_ids
                assert preview[0].speech == preview_speech
                assert all(turn.generation_status == "final_ready" for turn in preview)
                assert all(turn.publication_status == "unpublished" for turn in preview)
                finals = list(
                    db.scalars(
                        select(DebateTurn).where(
                            DebateTurn.debate_id == debate_id, DebateTurn.round_no == 4
                        )
                    )
                )
                assert finals
                assert all(turn.generation_status == "pending" for turn in finals)
                assert all(turn.publication_status == "unpublished" for turn in finals)
                assert all(not turn.speech for turn in finals)
                assert (
                    db.scalar(
                        select(BarrageMessage.id).where(BarrageMessage.debate_id == debate_id)
                    )
                    is None
                )
                assert db.scalar(select(Vote.id).where(Vote.debate_id == debate_id)) is None
                windows = list(
                    db.scalars(
                        select(ClassroomInteractionWindow).where(
                            ClassroomInteractionWindow.debate_id == debate_id
                        )
                    )
                )
                assert len(windows) == 1
                assert windows[0].id != old_window_id
                assert windows[0].status == "closed"
                assert windows[0].token_nonce is None
            late_barrage = client.post(
                f"/api/v1/classroom-interactions/{token}/barrages",
                json={
                    "nickname": "Visitor",
                    "raw_text": "After rebirth",
                    "client_submission_id": str(uuid4()),
                },
            )
            late_vote = client.post(
                f"/api/v1/classroom-interactions/{token}/votes",
                json={
                    "participant_id": participant_id,
                    "client_submission_id": str(uuid4()),
                },
            )
            assert late_barrage.status_code == 404, late_barrage.text
            assert late_vote.status_code == 404, late_vote.text
    finally:
        database.dispose()


@pytest.mark.parametrize(
    ("generation_status", "speech", "audio_duration_ms", "safe_error_code"),
    [
        ("final_ready", "Saved speech", None, None),
        ("final_ready", "Saved speech", None, "provider_not_sent"),
        ("final_ready", " ", None, "tts_voice_unavailable"),
        ("final_ready", "Saved speech", 100, "tts_voice_unavailable"),
        ("pending", "Saved speech", None, "tts_voice_unavailable"),
    ],
)
def test_rebirth_rejects_unready_preview_without_resetting_classroom(
    app_factory, generation_status, speech, audio_duration_ms, safe_error_code
):
    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            _, csrf = login(client)
            body = _body(client, debate_id)
            with database.session() as db:
                turn = db.scalar(
                    select(DebateTurn)
                    .where(DebateTurn.debate_id == debate_id)
                    .order_by(DebateTurn.turn_index)
                )
                turn.generation_status = generation_status
                turn.speech = speech
                turn.audio_file_id = None
                turn.audio_duration_ms = audio_duration_ms
                turn.safe_error_code = safe_error_code
                final_ids = set(
                    db.scalars(
                        select(DebateTurn.id).where(
                            DebateTurn.debate_id == debate_id, DebateTurn.round_no == 4
                        )
                    )
                )
            result = client.post(
                f"/api/v1/debates/{debate_id}/rebirth",
                json=body,
                headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
            )
            assert result.status_code == 409, result.text
            assert result.json()["code"] == "preview_not_ready"
            with database.session() as db:
                debate = db.get(Debate, debate_id)
                assert debate.status == "completed"
                assert debate.revision == body["expected_revision"]
                assert debate.final_input_json == "{}"
                assert (
                    set(
                        db.scalars(
                            select(DebateTurn.id).where(
                                DebateTurn.debate_id == debate_id, DebateTurn.round_no == 4
                            )
                        )
                    )
                    == final_ids
                )
                assert list(db.scalars(select(ProviderOperation))) == []
                assert not list(
                    db.scalars(select(AuditLog).where(AuditLog.event_type == "debate.rebirth"))
                )
    finally:
        database.dispose()


def test_destroy_a_draft_without_a_playback_row_removes_it_from_list(app_factory):
    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            with database.session() as db:
                db.get(Debate, debate_id).status = "draft"
                db.execute(delete(PlaybackState).where(PlaybackState.debate_id == debate_id))
            _, csrf = login(client)
            removed = client.request(
                "DELETE",
                f"/api/v1/debates/{debate_id}",
                json=_body(client, debate_id),
                headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
            )
            assert removed.status_code == 200, removed.text
            assert client.get(f"/api/v1/debates/{debate_id}").status_code == 404
            rows = client.get(f"/api/v1/courses/{COURSE_ID}/debates").json()
            assert all(row["id"] != debate_id for row in rows)
    finally:
        database.dispose()


def test_remake_saved_turn_restores_ready_without_new_generation(app_factory):
    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            with database.session() as db:
                db.get(Debate, debate_id).status = "running"
                turn = db.scalar(
                    select(DebateTurn)
                    .where(DebateTurn.debate_id == debate_id)
                    .order_by(DebateTurn.turn_index)
                )
                before = (turn.id, turn.speech, turn.audio_file_id)
                state = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
                state.current_turn_id = turn.id
                state.status = "ready"
                state.updated_at = datetime.now(UTC) - timedelta(seconds=30)
            _, csrf = login(client)
            rows = client.get(f"/api/v1/courses/{COURSE_ID}/debates").json()
            assert next(row for row in rows if row["id"] == debate_id)["stall"] is None
            response = client.post(
                f"/api/v1/debates/{debate_id}/remake",
                json=_body(client, debate_id),
                headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
            )
            assert response.status_code == 200, response.text
            with database.session() as db:
                turn = db.get(DebateTurn, before[0])
                assert (turn.id, turn.speech, turn.audio_file_id) == before
                assert db.get(Debate, debate_id).status == "running"
                state = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
                assert state.status == "ready"
                assert list(db.scalars(select(ProviderOperation))) == []
    finally:
        database.dispose()


def test_destroy_running_classroom_ignores_stale_versions(app_factory):
    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            with database.session() as db:
                debate = db.get(Debate, debate_id)
                debate.status = "running"
                debate.revision = 20
                state = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
                state.control_version = 30
                state.status = "playing"
            _, csrf = login(client)
            result = client.request(
                "DELETE",
                f"/api/v1/debates/{debate_id}",
                json={"expected_revision": 0, "expected_control_version": 0},
                headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
            )
            assert result.status_code == 200, result.text
            assert client.get(f"/api/v1/debates/{debate_id}").status_code == 404
    finally:
        database.dispose()


def test_remake_failed_turn_uses_new_identity_and_retains_paid_ledger(app_factory, monkeypatch):
    from unittest.mock import AsyncMock

    from app.modules.debates.playback.router import get_playback_service
    from starlette.requests import Request

    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            with database.session() as db:
                debate = db.get(Debate, debate_id)
                debate.status = "running"
                turn = db.scalar(
                    select(DebateTurn)
                    .where(DebateTurn.debate_id == debate_id)
                    .order_by(DebateTurn.turn_index.desc())
                )
                old_id = turn.id
                turn.generation_status = "failed"
                turn.publication_status = "unpublished"
                turn.speech = turn.structured_json = turn.audio_file_id = None
                state = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
                state.status = "preparing"
                state.current_turn_id = old_id
                operation_id = str(uuid4())
                db.add(
                    ProviderOperation(
                        id=operation_id,
                        scope_id=debate_id,
                        provider_operation="llm_debate_turn",
                        logical_item_id=old_id,
                        attempt_no=1,
                        request_hash="a" * 64,
                        max_tokens=100,
                        max_cost_cny=0.01,
                        policy_hash="b" * 64,
                        export_manifest_hash="c" * 64,
                        state="failed",
                        request_count=1,
                        charged_request_count=1,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
            service = get_playback_service(Request({"type": "http", "app": app}))
            enqueue = AsyncMock(return_value=True)
            monkeypatch.setattr(service, "_enqueue", enqueue)
            _, csrf = login(client)
            body = _body(client, debate_id)
            headers = _headers(csrf, **{"Idempotency-Key": str(uuid4())})
            response = client.post(
                f"/api/v1/debates/{debate_id}/remake", json=body, headers=headers
            )
            assert response.status_code == 200, response.text
            replay = client.post(f"/api/v1/debates/{debate_id}/remake", json=body, headers=headers)
            assert replay.status_code == 200, replay.text
            assert enqueue.await_count == 1
            with database.session() as db:
                assert db.get(DebateTurn, old_id) is None
                assert db.get(ProviderOperation, operation_id).charged_request_count == 1
                turns = list(
                    db.scalars(
                        select(DebateTurn)
                        .where(DebateTurn.debate_id == debate_id)
                        .order_by(DebateTurn.turn_index)
                    )
                )
                assert len(turns) == 8
                assert all(turn.generation_status == "final_ready" for turn in turns[:-1])
                assert turns[-1].generation_status == "pending"
                state = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
                assert state.current_turn_id == turns[-1].id
                assert state.status == "preparing"
                assert db.get(Debate, debate_id).status == "running"
    finally:
        database.dispose()


def test_remake_failed_staged_preview_rebinds_prefix_and_resumes_chain(app_factory, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from app.core.models import LlmAcceptedStage
    from app.modules.debates.playback.router import get_playback_service
    from starlette.requests import Request

    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            with database.session() as db:
                debate = db.get(Debate, debate_id)
                debate.status = "draft"
                turns = list(
                    db.scalars(
                        select(DebateTurn)
                        .where(DebateTurn.debate_id == debate_id)
                        .order_by(DebateTurn.turn_index)
                    )
                )
                target = turns[2]
                old_id = target.id
                for turn in turns[2:]:
                    turn.generation_status = "pending"
                    turn.publication_status = "unpublished"
                    turn.speech = turn.structured_json = turn.audio_file_id = None
                    turn.predecessor_turn_ids_json = json.dumps(
                        [t.id for t in turns[: turn.turn_index]], separators=(",", ":")
                    )
                    turn.cutoff_turn_index = turn.turn_index - 1
                target.generation_status = "failed"
                target.safe_error_code = "question_route_invalid"
                target.transcript_hash = "a" * 64
                expected_prefix = target.predecessor_turn_ids_json
                state = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
                state.status = "preparing"
                state.current_turn_id = None
                operation_id = str(uuid4())
                db.add(
                    ProviderOperation(
                        id=operation_id,
                        provider_operation="llm_debate_turn",
                        scope_id=debate_id,
                        logical_item_id=old_id,
                        attempt_no=1,
                        request_hash="a" * 64,
                        max_tokens=100,
                        max_cost_cny=0.01,
                        policy_hash="b" * 64,
                        export_manifest_hash="c" * 64,
                        state="failed",
                        request_count=1,
                        charged_request_count=1,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
                db.flush()
                hashes = {
                    name: "a" * 64
                    for name in (
                        "request_hash",
                        "prompt_hash",
                        "schema_hash",
                        "tokenizer_hash",
                        "rule_set_hash",
                        "persona_spec_hash",
                        "transcript_hash",
                        "receipt_hash",
                        "policy_hash",
                        "export_manifest_hash",
                        "build_manifest_hash",
                        "output_hash",
                    )
                }
                db.add(
                    LlmAcceptedStage(
                        operation_id=operation_id,
                        turn_id=old_id,
                        attempt_no=1,
                        **hashes,
                        prompt_contract_version="test",
                        tokenizer_id="test",
                        model_key="test",
                        output_json='{"question":null}',
                        prompt_tokens=1,
                        cached_input_tokens=0,
                        completion_tokens=1,
                        total_tokens=2,
                        price_card_version="test",
                        input_price_cny_per_million=0,
                        cached_input_price_cny_per_million=0,
                        output_price_cny_per_million=0,
                        estimated_cost_cny=0,
                        retrieval_reused=False,
                        created_at=datetime.now(UTC),
                    )
                )
            scheduler = SimpleNamespace(resume=Mock(), release=Mock())
            monkeypatch.setattr(app.state, "prewarm_scheduler", scheduler)
            service = get_playback_service(Request({"type": "http", "app": app}))
            enqueue = AsyncMock(return_value=True)
            monkeypatch.setattr(service, "_enqueue", enqueue)
            _, csrf = login(client)
            body = _body(client, debate_id)
            headers = _headers(csrf, **{"Idempotency-Key": str(uuid4())})
            response = client.post(
                f"/api/v1/debates/{debate_id}/remake", json=body, headers=headers
            )
            assert response.status_code == 200, response.text
            replay = client.post(f"/api/v1/debates/{debate_id}/remake", json=body, headers=headers)
            assert replay.status_code == 200
            scheduler.resume.assert_called_once_with(debate_id)
            scheduler.release.assert_not_called()
            enqueue.assert_not_awaited()
            with database.session() as db:
                assert db.get(DebateTurn, old_id) is None
                assert db.get(ProviderOperation, operation_id).charged_request_count == 1
                remaining = list(
                    db.scalars(
                        select(DebateTurn)
                        .where(DebateTurn.debate_id == debate_id)
                        .order_by(DebateTurn.turn_index)
                    )
                )
                replacement = remaining[2]
                assert replacement.predecessor_turn_ids_json == expected_prefix
                assert replacement.cutoff_turn_index == 1
                assert replacement.transcript_hash is None
                assert all(old_id not in t.predecessor_turn_ids_json for t in remaining)
                assert all(replacement.id in t.predecessor_turn_ids_json for t in remaining[3:])
                assert all(t.generation_status == "final_ready" for t in remaining[:2])
    finally:
        database.dispose()


@pytest.mark.asyncio
async def test_remake_resume_reopens_released_preview_and_finishes_remaining_turns():
    import asyncio

    from app.modules.debates.playback.prewarm import PrewarmScheduler

    completed = {"saved"}
    prepared = []
    finished = asyncio.Event()

    def plan(_debate_id):
        return [(turn_id, turn_id in completed) for turn_id in ("saved", "failed", "following")]

    async def prepare(_debate_id, turn_id):
        prepared.append(turn_id)
        completed.add(turn_id)
        if turn_id == "following":
            finished.set()

    scheduler = PrewarmScheduler(plan=plan, prepare=prepare)
    scheduler.bind_running_loop()
    scheduler.release("draft")
    try:
        scheduler.resume("draft")
        await asyncio.wait_for(finished.wait(), timeout=2)
        assert prepared == ["failed", "following"]
    finally:
        await scheduler.close()


@pytest.mark.parametrize(
    "status,mode",
    [("stopped", "live"), ("completed", "live"), ("completed", "replay"), ("failed", "live")],
)
def test_remake_recovers_saved_checkpoint_across_states_and_stale_versions(
    app_factory, status, mode
):
    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            with database.session() as db:
                debate = db.get(Debate, debate_id)
                debate.status = status
                state = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
                last = db.scalar(
                    select(DebateTurn)
                    .where(DebateTurn.debate_id == debate_id)
                    .order_by(DebateTurn.turn_index.desc())
                )
                state.current_turn_id = last.id
                state.status = "stopped" if status == "stopped" else "paused"
                state.mode = mode
                saved = last.speech
            _, csrf = login(client)
            response = client.post(
                f"/api/v1/debates/{debate_id}/remake",
                json={"expected_revision": 0, "expected_control_version": 0},
                headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
            )
            assert response.status_code == 200, response.text
            with database.session() as db:
                state = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
                assert db.get(DebateTurn, state.current_turn_id).speech == saved
                assert state.status == (
                    "completed" if status == "completed" and mode == "live" else "ready"
                )
                assert db.get(Debate, debate_id).status == (
                    "completed" if status == "completed" else "running"
                )
    finally:
        database.dispose()


def test_explicit_final_input_reset_rolls_back_with_its_original_trigger(app_factory):
    from app.modules.debates import cleanup
    from app.modules.debates.rebirth import _write_reset_final_input
    from sqlalchemy.exc import IntegrityError

    app, database, settings = app_factory()
    try:
        with TestClient(app):
            debate_id = _saved_classroom(database, settings)
            with database.session() as db:
                before = db.get(Debate, debate_id).final_input_json
                trigger = db.scalar(
                    text("SELECT sql FROM sqlite_master WHERE name='debate_final_input_immutable'")
                )
                cleanup._begin_immediate(db)
                debate = db.get(Debate, debate_id)
                _write_reset_final_input(db, debate, None, clear_timestamp=True)
                db.rollback()
                assert db.get(Debate, debate_id).final_input_json == before
                assert (
                    db.scalar(
                        text(
                            "SELECT sql FROM sqlite_master "
                            "WHERE name='debate_final_input_immutable'"
                        )
                    )
                    == trigger
                )
                with pytest.raises(IntegrityError, match="final_input_immutable"):
                    db.execute(
                        text("UPDATE debates SET final_input_json=NULL WHERE id=:id"),
                        {"id": debate_id},
                    )
                db.rollback()
    finally:
        database.dispose()


@pytest.mark.asyncio
async def test_global_remake_queues_each_draft_without_stealing_inflight_work():
    import asyncio

    from app.modules.debates.playback.prewarm import PrewarmScheduler

    started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    ready, calls = set(), []

    def plan(debate_id):
        return [(debate_id + "-turn", debate_id in ready)]

    async def prepare(debate_id, _turn_id):
        calls.append(debate_id)
        if debate_id == "a":
            started.set()
            await release.wait()
        ready.add(debate_id)
        if debate_id == "b":
            finished.set()

    scheduler = PrewarmScheduler(plan=plan, prepare=prepare)
    scheduler.bind_running_loop()
    try:
        scheduler.resume("a")
        await asyncio.wait_for(started.wait(), 2)
        scheduler.resume("b")
        scheduler.resume("b")
        await asyncio.sleep(0)
        assert scheduler.owner == "a"
        release.set()
        await asyncio.wait_for(finished.wait(), 2)
        assert calls == ["a", "b"]
    finally:
        release.set()
        await scheduler.close()
