"""Disposable SQL/API coverage for Destroy, Rebirth and current-turn recovery."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.models import ProviderOperation, StoredFile
from app.modules.debates.models import AuditLog, Debate, DebateTurn, PlaybackState
from app.modules.debates.playback.audio import AudioStore
from app.modules.debates.setup.rules import canonical_rule_snapshot_json
from app.modules.interactions.models import ClassroomInteractionWindow
from app.providers.tts import MockTTSProvider
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from tests.conftest import login
from tests.test_wave2_playback import _headers
from tests.test_wave3_interactions import COURSE_ID, _seed_finished_debate


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
    return debate_id


def _body(client, debate_id):
    detail = client.get(f"/api/v1/debates/{debate_id}")
    assert detail.status_code == 200, detail.text
    value = detail.json()
    return {
        "expected_revision": value["revision"],
        "expected_control_version": value["playback"]["control_version"],
    }


def test_rebirth_preserves_preview_clears_classroom_and_starts_again(app_factory):
    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            _, csrf = login(client)
            with database.session() as db:
                before = [
                    (t.id, t.speech, t.structured_json, t.audio_file_id)
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
                    (t.id, t.speech, t.structured_json, t.audio_file_id)
                    for t in db.scalars(
                        select(DebateTurn)
                        .where(DebateTurn.debate_id == debate_id, DebateTurn.round_no < 4)
                        .order_by(DebateTurn.turn_index)
                    )
                ]
                assert after == before
                assert db.get(Debate, debate_id).final_input_json is None
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
            assert next(row for row in rows if row["id"] == debate_id)["stall"] is not None
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
