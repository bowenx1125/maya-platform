"""Focused PW3-D playback invariants.

The broad Wave 2 suite retains historical controls for regression evidence;
these tests pin the pre-Wave 3 public semantics: whole replay is teacher-paced,
never generates, and is cleared only after its final retained turn or reset.
"""

from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.modules.debates.playback.audio import AudioStore
from app.modules.debates.playback.protocols import (
    MemoryDebate,
    MemoryParticipant,
    MemoryPlaybackRepository,
    MemoryTurn,
    PreparedTurn,
)
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.task_manager import TaskManager


def _wav_bytes() -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8_000)
        wav_file.writeframes(b"\x00\x00" * 80)
    return stream.getvalue()


def _speech() -> str:
    return "word " * 80


async def _replay_fixture(
    tmp_path: Path,
) -> tuple[
    PlaybackService,
    MemoryPlaybackRepository,
    MemoryDebate,
    str,
    str,
]:
    repository = MemoryPlaybackRepository()
    debate = MemoryDebate(
        id=str(uuid4()),
        course_id=str(uuid4()),
        status="completed",
        participants=[
            MemoryParticipant(id=str(uuid4()), slot="A", order_index=0, name="A"),
            MemoryParticipant(id=str(uuid4()), slot="B", order_index=1, name="B"),
        ],
    )
    store = AudioStore(tmp_path)
    for index, participant in enumerate(debate.participants):
        turn_id = str(uuid4())
        metadata = store.store_bytes(
            course_id=debate.course_id,
            debate_id=debate.id,
            turn_id=turn_id,
            raw=_wav_bytes(),
        )
        debate.turns.append(
            MemoryTurn(
                id=turn_id,
                participant_id=participant.id,
                round_no=1,
                turn_index=index,
                generation_status="final_ready",
                publication_status="public",
                speech=_speech(),
                audio_duration_ms=metadata.duration_ms,
                audio_file_id=metadata.relative_path,
                audio_size_bytes=metadata.size_bytes,
                audio_sha256=metadata.sha256,
                audio_relative_path=metadata.relative_path,
            )
        )
    repository.add_debate(debate)
    repository.course_audio[debate.course_id] = debate.id
    service = PlaybackService(
        repository,
        audio_store=AudioStore(tmp_path),
        task_manager=TaskManager(),
        turn_preparer=lambda *_args, **_kwargs: PreparedTurn(speech=_speech()),
    )
    return service, repository, debate, debate.turns[0].id, debate.turns[1].id


async def _start_replay(
    service: PlaybackService,
    debate: MemoryDebate,
    first_turn_id: str,
    *,
    play: bool = True,
) -> tuple[str, int]:
    state = await service.replay_all(None, debate.id, expected_control_version=0)
    controller = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=state.control_version,
        session_hash="session",
        connection_id="tab",
    )
    if not play:
        return str(controller.controller_epoch), controller.control_version
    await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=str(controller.controller_epoch),
        session_hash="session",
        turn_id=first_turn_id,
        action="replay",
    )
    await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=str(controller.controller_epoch),
        session_hash="session",
        turn_id=first_turn_id,
        action="replay",
    )
    return str(controller.controller_epoch), controller.control_version


@pytest.mark.asyncio
async def test_whole_replay_waits_for_next_and_never_prepares_successor(
    tmp_path: Path,
) -> None:
    service, repository, debate, first_id, second_id = await _replay_fixture(tmp_path)
    epoch, control_version = await _start_replay(service, debate, first_id)
    events = await service.event_hub.subscribe(debate.id)
    first_end = await service.ended_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=control_version,
        epoch=epoch,
        session_hash="session",
        turn_id=first_id,
    )

    assert first_end.status == "waiting_next"
    assert first_end.mode == "replay"
    assert str(first_end.current_turn_id) == first_id
    assert first_end.next_turn_ready is True
    assert repository.playback_state(None, debate).replay_index == 0
    assert repository.playback_state(None, debate).current_turn_id == first_id
    assert service.task_manager.active_keys == ()
    waiting_event = events.get_nowait()
    assert waiting_event.event_type == "playback.waiting_next"
    assert waiting_event.payload == {
        "mode": "replay",
        "completed_turn_id": first_id,
        "control_version": first_end.control_version,
        "next_turn_ready": True,
    }

    advanced = await service.next(
        None,
        debate.id,
        expected_control_version=first_end.control_version,
        expected_current_turn_id=first_id,
    )
    assert advanced.status == "ready"
    assert advanced.mode == "replay"
    assert str(advanced.current_turn_id) == second_id
    assert advanced.next_turn_ready is False
    # No provider/preparation task is created by replay Next itself.
    assert service.task_manager.active_keys == ()
    await service.event_hub.unsubscribe(debate.id, events)


@pytest.mark.asyncio
async def test_final_replay_end_clears_controller_queue_and_cursor(
    tmp_path: Path,
) -> None:
    service, repository, debate, first_id, second_id = await _replay_fixture(tmp_path)
    epoch, control_version = await _start_replay(service, debate, first_id)
    first_end = await service.ended_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=control_version,
        epoch=epoch,
        session_hash="session",
        turn_id=first_id,
    )
    second_ready = await service.next(
        None,
        debate.id,
        expected_control_version=first_end.control_version,
        expected_current_turn_id=first_id,
    )
    await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=second_ready.control_version,
        epoch=epoch,
        session_hash="session",
        turn_id=second_id,
        action="replay",
    )
    await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=second_ready.control_version,
        epoch=epoch,
        session_hash="session",
        turn_id=second_id,
        action="replay",
    )
    events = await service.event_hub.subscribe(debate.id)
    completed = await service.ended_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=second_ready.control_version,
        epoch=epoch,
        session_hash="session",
        turn_id=second_id,
    )

    assert completed.status == "completed"
    assert completed.mode == "live"
    assert completed.current_turn_id is None
    state = repository.playback_state(None, debate)
    assert state.controller_epoch is None
    assert state.replay_turn_ids == []
    assert state.replay_index is None
    assert state.cursor_ms == 0
    assert (
        service.ticket_store.find(
            session_hash="session",
            controller_epoch=epoch,
            debate_id=debate.id,
            turn_id=second_id,
            action="replay",
            started=False,
        )
        is None
    )
    completed_event = events.get_nowait()
    assert completed_event.event_type == "replay.completed"
    assert completed_event.payload == {
        "scope": "all",
        "turn_id": second_id,
        "control_version": completed.control_version,
    }
    revoked = service.take_revocation(epoch)
    assert revoked is not None
    assert revoked["reason"] == "debate_terminal"
    await service.event_hub.unsubscribe(debate.id, events)


@pytest.mark.asyncio
async def test_replay_readiness_rechecks_retained_file_before_next(tmp_path: Path) -> None:
    service, repository, debate, first_id, _second_id = await _replay_fixture(tmp_path)
    epoch, control_version = await _start_replay(service, debate, first_id)
    first_end = await service.ended_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=control_version,
        epoch=epoch,
        session_hash="session",
        turn_id=first_id,
    )
    successor = debate.turns[1]
    assert successor.audio_file_id is not None
    repository.audio_file_states[successor.audio_file_id] = "deleted"

    with pytest.raises(PlatformError) as raised:
        await service.next(
            None,
            debate.id,
            expected_control_version=first_end.control_version,
            expected_current_turn_id=first_id,
        )
    assert raised.value.code == "next_not_ready"
    state = repository.playback_state(None, debate)
    assert state.status == "waiting_next"
    assert state.current_turn_id == first_id
    assert state.replay_index == 0


@pytest.mark.asyncio
async def test_replay_readiness_rechecks_current_course_pointer(tmp_path: Path) -> None:
    service, repository, debate, first_id, _second_id = await _replay_fixture(tmp_path)
    epoch, control_version = await _start_replay(service, debate, first_id)
    first_end = await service.ended_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=control_version,
        epoch=epoch,
        session_hash="session",
        turn_id=first_id,
    )
    repository.course_audio[debate.course_id] = str(uuid4())

    with pytest.raises(PlatformError) as raised:
        await service.next(
            None,
            debate.id,
            expected_control_version=first_end.control_version,
            expected_current_turn_id=first_id,
        )
    assert raised.value.code == "next_not_ready"
    state = repository.playback_state(None, debate)
    assert state.status == "waiting_next"
    assert state.current_turn_id == first_id
    assert state.replay_index == 0


@pytest.mark.asyncio
async def test_restart_preserves_replay_gate_but_fences_old_controller(
    tmp_path: Path,
) -> None:
    service, repository, debate, first_id, _second_id = await _replay_fixture(tmp_path)
    epoch, control_version = await _start_replay(service, debate, first_id)
    waiting = await service.ended_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=control_version,
        epoch=epoch,
        session_hash="session",
        turn_id=first_id,
    )

    affected = await service.recover_startup(None)

    assert affected == ()
    recovered = repository.playback_state(None, debate)
    assert recovered.status == "waiting_next"
    assert recovered.mode == "replay"
    assert recovered.current_turn_id == first_id
    assert recovered.replay_index == 0
    assert recovered.controller_epoch is None
    assert service.task_manager.active_keys == ()

    with pytest.raises(PlatformError) as raised:
        await service.media_prepare(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=waiting.control_version,
            epoch=epoch,
            session_hash="session",
            turn_id=first_id,
            action="replay",
        )
    assert raised.value.code == "stale_control_version"


@pytest.mark.asyncio
async def test_media_prepare_single_pending_hash_and_strict_ack_authorization(
    tmp_path: Path,
) -> None:
    service, repository, debate, first_id, _second_id = await _replay_fixture(tmp_path)
    epoch, control_version = await _start_replay(service, debate, first_id, play=False)
    command_id = str(uuid4())
    first, first_result = await service.media_prepare(
        None,
        debate.id,
        command_id=command_id,
        expected_control_version=control_version,
        epoch=epoch,
        session_hash="session",
        turn_id=first_id,
        action="replay",
    )
    repeated, repeated_result = await service.media_prepare(
        None,
        debate.id,
        command_id=command_id,
        expected_control_version=control_version,
        epoch=epoch,
        session_hash="session",
        turn_id=first_id,
        action="replay",
    )
    assert repeated.token == first.token
    assert repeated_result.media_url == first_result.media_url
    assert len(service.ticket_store._tickets) == 1

    with pytest.raises(PlatformError) as duplicate:
        await service.media_prepare(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=control_version,
            epoch=epoch,
            session_hash="session",
            turn_id=first_id,
            action="replay",
        )
    assert duplicate.value.code == "duplicate_command"
    state = repository.playback_state(None, debate)
    assert state.pending_ticket_hash == first.binding.token_hash
    assert state.pending_media_command_id == command_id

    state.pending_ticket_hash = "f" * 64
    with pytest.raises(PlatformError) as wrong_hash:
        await service.started_ack(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=control_version,
            epoch=epoch,
            session_hash="session",
            turn_id=first_id,
            action="replay",
        )
    assert wrong_hash.value.code == "invalid_state"
    state.pending_ticket_hash = first.binding.token_hash
    await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=control_version,
        epoch=epoch,
        session_hash="session",
        turn_id=first_id,
        action="replay",
    )
    authorization = await service.authorize_audio(
        None,
        debate.id,
        first_id,
        session_hash="session",
        media_ticket=first.token,
    )
    assert authorization.ticket is not None
    state.pending_ticket_hash = "0" * 64
    with pytest.raises(PlatformError) as authorization_rejected:
        await service.authorize_audio(
            None,
            debate.id,
            first_id,
            session_hash="session",
            media_ticket=first.token,
        )
    assert authorization_rejected.value.code == "forbidden"


@pytest.mark.asyncio
async def test_restart_clears_pending_media_claim_and_old_ticket(
    tmp_path: Path,
) -> None:
    service, repository, debate, first_id, _second_id = await _replay_fixture(tmp_path)
    epoch, control_version = await _start_replay(service, debate, first_id, play=False)
    prepared, _result = await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=control_version,
        epoch=epoch,
        session_hash="session",
        turn_id=first_id,
        action="replay",
    )
    await service.recover_startup(None)
    state = repository.playback_state(None, debate)
    assert state.status == "ready"
    assert state.mode == "replay"
    assert state.current_turn_id == first_id
    assert state.pending_action is None
    assert state.pending_ticket_hash is None
    assert state.pending_media_command_id is None
    assert state.audio_duration_ms == 0
    assert service.ticket_store.get(prepared.token) is None


@pytest.mark.asyncio
async def test_operator_reset_and_next_have_one_cas_winner(tmp_path: Path) -> None:
    service, _repository, debate, first_id, _second_id = await _replay_fixture(tmp_path)
    epoch, control_version = await _start_replay(service, debate, first_id)
    waiting = await service.ended_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=control_version,
        epoch=epoch,
        session_hash="session",
        turn_id=first_id,
    )
    expected = waiting.control_version

    async def do_next() -> str:
        try:
            await service.next(
                None,
                debate.id,
                expected_control_version=expected,
                expected_current_turn_id=first_id,
            )
            return "next"
        except PlatformError as exc:
            assert exc.code == "stale_control_version"
            return "stale"

    async def do_reset() -> str:
        try:
            await service.operator_reset(
                None,
                debate.id,
                confirm=True,
                expected_control_version=expected,
            )
            return "reset"
        except PlatformError as exc:
            assert exc.code == "stale_control_version"
            return "stale"

    outcomes = await asyncio.gather(do_next(), do_reset())
    assert sorted(outcomes) == ["next", "stale"] or sorted(outcomes) == ["reset", "stale"]
