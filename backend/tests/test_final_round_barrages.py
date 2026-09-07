"""Real SQL transactions bind messages to turns and freeze one final input."""

import json
from uuid import UUID, uuid4

import pytest
from app.core.errors import PlatformError
from app.modules.debates.final_input import read_final_input
from app.modules.debates.models import Debate, DebateTurn, PlaybackState
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository
from app.modules.interactions.schemas import BarrageRequest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.test_wave3_interactions import TEACHER_ID, _seed_finished_debate, _service


@pytest.fixture
def live_final(app_factory):
    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    try:
        with TestClient(app):
            debate_id, _ = _seed_finished_debate(database)
            with database.session() as db:
                debate = db.get(Debate, debate_id)
                snapshot = json.loads(debate.rule_snapshot_json)
                snapshot["turn_protocol"] = "segments_v2"
                debate.rule_snapshot_json = json.dumps(snapshot)
                debate.status = "running"
                turns = db.scalars(
                    select(DebateTurn)
                    .where(DebateTurn.debate_id == debate_id)
                    .order_by(DebateTurn.turn_index)
                ).all()
                turn_ids = [row.id for row in turns]
                for row in turns[2:]:
                    row.generation_status = "pending"
                    row.publication_status = "unpublished"
                    row.speech = None
                playback = db.scalar(
                    select(PlaybackState).where(PlaybackState.debate_id == debate_id)
                )
                playback.current_turn_id = turn_ids[0]
                playback.status = "waiting_next"
            service, _ = _service(database, settings)
            opened = service.open_interaction(
                actor_user_id=TEACHER_ID, debate_id=debate_id, idempotency_key=str(uuid4())
            )
            token = opened.public_url.rsplit("/", 1)[-1]
            yield database, service, debate_id, turn_ids, token
    finally:
        database.dispose()


def _current(database, debate_id, turn_id):
    with database.session() as db:
        playback = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
        playback.current_turn_id = turn_id


def _message(turn_id, text):
    return BarrageRequest(
        nickname="Class visitor",
        raw_text=text,
        client_submission_id=uuid4(),
        turn_id=UUID(turn_id),
    )


@pytest.mark.asyncio
async def test_final_is_enqueued_only_after_freeze_and_resumes_after_restart(live_final):
    database, service, debate_id, turn_ids, _ = live_final
    _current(database, debate_id, turn_ids[1])
    playback = PlaybackService(repository=SqlPlaybackRepository())
    queued = []

    async def capture(debate, turn):
        queued.append(str(turn.id))
        return True

    playback._enqueue = capture
    with database.session() as db:
        await playback.enqueue_frozen_final(db, debate_id)
    assert queued == []
    service.freeze_final(actor_user_id=TEACHER_ID, debate_id=debate_id, expected_control_version=1)
    with database.session() as db:
        await playback.enqueue_frozen_final(db, debate_id)
    assert queued == [turn_ids[2]]
    queued.clear()
    with database.session() as db:
        await playback._resume_running_debates(db)
    assert queued == [turn_ids[2]]
    queued.clear()
    with database.session() as db:
        db.get(DebateTurn, turn_ids[2]).safe_error_code = "acceptance_unknown"
    with database.session() as db:
        await playback.enqueue_frozen_final(db, debate_id)
    assert queued == []


def test_every_pre_final_turn_contributes_to_same_frozen_pool(live_final):
    database, service, debate_id, turn_ids, token = live_final
    first = _message(turn_ids[0], "How does evidence support the first viewpoint?")
    service.submit_barrage(access_token=token, payload=first)
    service.submit_barrage(access_token=token, payload=first)
    with pytest.raises(PlatformError) as error:
        service.submit_barrage(access_token=token, payload=_message(turn_ids[2], "Future turn?"))
    assert error.value.code == "barrage_turn_changed"
    _current(database, debate_id, turn_ids[1])
    service.submit_barrage(
        access_token=token,
        payload=_message(turn_ids[1], "Can the second viewpoint address scarcity?"),
    )
    frozen = service.freeze_final(
        actor_user_id=TEACHER_ID, debate_id=debate_id, expected_control_version=1
    )
    assert (frozen.barrage_count, frozen.cutoff_sequence) == (2, 2)
    with database.session() as db:
        original = db.get(Debate, debate_id).final_input_json
        saved = read_final_input(db.get(Debate, debate_id))
        assert [row["id"] for row in saved["barrages"]] == ["B1", "B2"]
        assert all(set(row) == {"id", "text"} for row in saved["barrages"])
        assert "Class visitor" not in original
    assert (
        service.freeze_final(
            actor_user_id=TEACHER_ID, debate_id=debate_id, expected_control_version=1
        )
        == frozen
    )
    with database.session() as db:
        assert db.get(Debate, debate_id).final_input_json == original
    with pytest.raises(PlatformError) as error:
        service.submit_barrage(access_token=token, payload=_message(turn_ids[1], "Too late?"))
    assert error.value.code == "barrage_collection_closed"
    assert service.public_form(access_token=token).barrage_open is False
    assert service.submit_barrage(access_token=token, payload=first).barrage_submitted


def test_empty_barrage_pool_is_a_valid_final_input(live_final):
    database, service, debate_id, turn_ids, _ = live_final
    _current(database, debate_id, turn_ids[1])
    result = service.freeze_final(
        actor_user_id=TEACHER_ID, debate_id=debate_id, expected_control_version=1
    )
    assert result.barrage_count == 0
    assert result.cutoff_sequence == 0


def test_final_cannot_freeze_before_last_prepared_turn(live_final):
    _, service, debate_id, _, _ = live_final
    with pytest.raises(PlatformError) as error:
        service.freeze_final(
            actor_user_id=TEACHER_ID, debate_id=debate_id, expected_control_version=1
        )
    assert error.value.code == "final_input_not_ready"
