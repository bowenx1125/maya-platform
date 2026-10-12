"""Intentional text-only live turns never need media tickets or audio acknowledgements."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.modules.debates.playback.protocols import (
    MemoryDebate,
    MemoryParticipant,
    MemoryPlaybackRepository,
)
from app.modules.debates.playback.service import PlaybackService


def _service():
    repository = MemoryPlaybackRepository()
    debate = repository.add_debate(
        MemoryDebate(
            topic="Should learning welcome different perspectives?",
            round_count=4,
            participants=[
                MemoryParticipant(slot="A", order_index=0),
                MemoryParticipant(slot="B", order_index=1),
            ],
        )
    )
    debate.rule_snapshot_json = json.dumps(
        {"turn_protocol": "segments_v2", "teaching_protocol": "four_round_v1", "round_count": 4}
    )
    turns = repository.ensure_turn_plan(None, debate)
    for turn in turns:
        earlier = [
            item
            for item in turns
            if item.turn_index < turn.turn_index
            and (turn.round_no > 1 or item.round_no < turn.round_no)
        ]
        turn.generation_status = "final_ready"
        turn.preparation_stage = "ready"
        turn.speech = f"Readable prepared turn {turn.turn_index}."
        turn.audio_duration_ms = 0
        turn.failed_code = "tts_voice_unavailable"
        turn.predecessor_turn_ids = tuple(item.id for item in earlier)
        turn.cutoff_turn_index = turn.turn_index - 1 if turn.round_no > 1 else -1
        turn.transcript_hash = "t" * 64
    return PlaybackService(repository), repository, debate


@pytest.mark.asyncio
async def test_text_only_start_manual_next_and_final_completion_without_audio():
    service, _repository, debate = _service()
    state = await service.start(
        None,
        debate.id,
        expected_revision=0,
        expected_current_audio_debate_id=None,
        confirm_previous_audio_cleanup=False,
    )
    await service.task_manager.wait_debate(debate.id)
    state = service._state(None, debate)
    assert state.status == "ready"
    controller = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=state.control_version,
        session_hash="session",
        connection_id="tab",
    )
    epoch = str(controller.controller_epoch)
    for index, turn in enumerate(debate.turns):
        if turn.round_no == 4:
            debate.final_input_json = "{}"
        if index:
            state = await service.next(
                None,
                debate.id,
                expected_control_version=debate.playback.control_version,
                expected_current_turn_id=debate.turns[index - 1].id,
            )
            assert str(state.current_turn_id) == turn.id
        command_id = str(uuid4())
        kwargs = dict(
            command_id=command_id,
            expected_control_version=debate.playback.control_version,
            epoch=epoch,
            session_hash="session",
            turn_id=turn.id,
            action="start" if index == 0 else "next",
        )
        media, result = await service.media_prepare(None, debate.id, **kwargs)
        assert media is None and result.text_only and result.media_url is None
        assert turn.publication_status == "public"
        assert debate.playback.pending_ticket_hash is None
        assert all(item.publication_status == "unpublished" for item in debate.turns[index + 1 :])
        if index + 1 < len(debate.turns):
            assert debate.playback.status == "waiting_next"
            assert service._state_dto(debate.playback, None, debate).next_turn_ready
            before = service.event_hub.store.last_sequence(debate.id)
            assert (await service.media_prepare(None, debate.id, **kwargs))[1] == result
            assert service.event_hub.store.last_sequence(debate.id) == before
    assert debate.status == "debate_finished"
    assert debate.playback.status == "completed"
    assert debate.playback.controller_epoch is None
    assert debate.playback.controller_session_hash is None
    events = service.event_hub.store.events_after(debate.id, 0)
    started = [event for event in events if event.event_type == "playback.started"]
    assert len(started) == 8
    assert all(
        event.payload["playback_url"] is None and event.payload["audio_ready"] is False
        for event in started
    )
    assert [event.event_type for event in events[-2:]] == ["playback.started", "playback.completed"]
    assert events[-1].payload["turn_id"] == debate.turns[-1].id
    assert len([event for event in events if event.event_type == "playback.waiting_next"]) == 7


@pytest.mark.asyncio
async def test_missing_audio_without_explicit_marker_does_not_pass_preview_gate():
    service, _repository, debate = _service()
    debate.turns[0].failed_code = None
    with pytest.raises(PlatformError) as error:
        await service.start(
            None,
            debate.id,
            expected_revision=0,
            expected_current_audio_debate_id=None,
            confirm_previous_audio_cleanup=False,
        )
    assert error.value.code == "preview_not_ready"
    assert debate.status == "draft"


@pytest.mark.asyncio
async def test_text_only_rejects_stale_controller_and_private_predecessor():
    service, _repository, debate = _service()
    debate.status = "running"
    debate.playback.status = "ready"
    debate.playback.current_turn_id = debate.turns[2].id
    controller = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=0,
        session_hash="session",
        connection_id="tab",
    )
    for epoch, expected_code in [
        (str(uuid4()), "stale_control_version"),
        (str(controller.controller_epoch), "invalid_state"),
    ]:
        with pytest.raises(PlatformError) as error:
            await service.media_prepare(
                None,
                debate.id,
                command_id=str(uuid4()),
                expected_control_version=controller.control_version,
                epoch=epoch,
                session_hash="session",
                turn_id=debate.turns[2].id,
                action="next",
            )
        assert error.value.code == expected_code
    assert all(item.publication_status == "unpublished" for item in debate.turns)


def test_text_media_result_requires_consistent_explicit_mode():
    from datetime import UTC, datetime

    from app.modules.debates.playback.schemas import MediaPreparedResult
    from pydantic import ValidationError

    debate_id, turn_id = uuid4(), uuid4()
    fields = {
        "message_id": uuid4(),
        "debate_id": debate_id,
        "occurred_at": datetime.now(UTC),
        "command_id": uuid4(),
        "controller_epoch": uuid4(),
        "turn_id": turn_id,
        "expires_at": datetime.now(UTC),
        "media_url": None,
    }
    assert MediaPreparedResult(**fields, text_only=True).text_only
    for text_flag in ({}, {"text_only": False}):
        with pytest.raises(ValidationError):
            MediaPreparedResult(**fields, **text_flag)
    fields["media_url"] = f"/api/v1/debates/{debate_id}/audio/{turn_id}?media_ticket={'a' * 43}"
    assert not MediaPreparedResult(**fields).text_only
    with pytest.raises(ValidationError):
        MediaPreparedResult(**fields, text_only=True)


@pytest.mark.asyncio
async def test_text_only_gap_is_not_mistaken_for_last_turn():
    service, _repository, debate = _service()
    debate.status = "running"
    debate.turns.pop(1)
    debate.playback.status = "ready"
    debate.playback.current_turn_id = debate.turns[0].id
    controller = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=0,
        session_hash="session",
        connection_id="tab",
    )
    before = service.event_hub.store.last_sequence(debate.id)
    with pytest.raises(PlatformError) as error:
        await service.media_prepare(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=controller.control_version,
            epoch=str(controller.controller_epoch),
            session_hash="session",
            turn_id=debate.turns[0].id,
            action="start",
        )
    assert error.value.code == "invalid_state"
    assert debate.status == "running"
    assert debate.playback.status == "ready"
    assert all(turn.publication_status == "unpublished" for turn in debate.turns)
    assert service.event_hub.store.last_sequence(debate.id) == before
