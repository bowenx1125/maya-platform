"""Disposable SQL/API coverage for Destroy, Rebirth and current-turn recovery."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
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


@pytest.mark.parametrize("mode", ["live", "replay"])
def test_rebirth_preserves_preview_clears_classroom_and_starts_again(app_factory, mode):
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
                    if turn.round_no == 4:
                        turn.predecessor_turn_ids_json = json.dumps(
                            [item.id for item in planned[: turn.turn_index]], separators=(",", ":")
                        )
                        turn.cutoff_turn_index = turn.turn_index - 1
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
