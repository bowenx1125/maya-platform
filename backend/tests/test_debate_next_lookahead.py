"""Next waits less: lookahead preparation and controller-only audio prefetch.

Owner decision (2026-10-24): a live lesson prepares up to three turns past
the playing one, the browser downloads the next speech as soon as its audio
is ready, and each Debate serializes only its own work.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.modules.debates.playback.protocols import LIVE_LOOKAHEAD_TURNS

from tests.test_wave2_playback import _memory_ready_service


async def _playing(tmp_path: Path, session: str):  # type: ignore[no-untyped-def]
    service, debate, tasks = await _memory_ready_service(tmp_path)
    await tasks.wait_debate(debate.id)
    first_turn = debate.turns[0]
    controller = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=0,
        session_hash=session,
        connection_id=f"{session}-tab",
    )
    epoch = str(controller.controller_epoch)
    await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=epoch,
        session_hash=session,
        turn_id=first_turn.id,
        action="start",
    )
    playing = await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=epoch,
        session_hash=session,
        turn_id=first_turn.id,
        action="start",
    )
    await tasks.wait_debate(debate.id)
    return service, debate, tasks, epoch, playing


@pytest.mark.asyncio
async def test_a_playing_lesson_prepares_the_lookahead_window(tmp_path: Path) -> None:
    service, debate, tasks, _epoch, _playing_state = await _playing(tmp_path, "look-session")
    ready = [
        turn.turn_index
        for turn in debate.turns
        if turn.generation_status in {"final_ready", "ready", "completed"}
    ]
    window = list(range(0, min(len(debate.turns), 1 + LIVE_LOOKAHEAD_TURNS)))
    assert ready[: len(window)] == window
    assert all(index <= LIVE_LOOKAHEAD_TURNS for index in ready)
    await tasks.close()


@pytest.mark.asyncio
async def test_the_controller_can_prefetch_only_the_ready_next_audio(tmp_path: Path) -> None:
    service, debate, tasks, epoch, playing = await _playing(tmp_path, "prefetch-session")
    first_turn, successor = debate.turns[0], debate.turns[1]
    turn_id, media_url = await service.prefetch_next_audio(
        None,
        debate.id,
        expected_control_version=playing.control_version,
        expected_current_turn_id=first_turn.id,
        epoch=epoch,
        session_hash="prefetch-session",
    )
    assert turn_id == successor.id
    token = media_url.rsplit("media_ticket=", 1)[1]
    authorized = await service.authorize_audio(
        None, debate.id, successor.id, session_hash="prefetch-session", media_ticket=token
    )
    assert authorized.ticket is not None and authorized.ticket.action == "prefetch"
    # Another session, or the same ticket for another turn, gets nothing.
    with pytest.raises(PlatformError):
        await service.authorize_audio(
            None, debate.id, successor.id, session_hash="someone-else", media_ticket=token
        )
    with pytest.raises(PlatformError):
        await service.authorize_audio(
            None, debate.id, debate.turns[2].id, session_hash="prefetch-session", media_ticket=token
        )
    # A stale controller epoch cannot mint one.
    with pytest.raises(PlatformError) as stale:
        await service.prefetch_next_audio(
            None,
            debate.id,
            expected_control_version=playing.control_version,
            expected_current_turn_id=first_turn.id,
            epoch=str(uuid4()),
            session_hash="prefetch-session",
        )
    assert stale.value.code == "stale_control_version"
    await tasks.close()


@pytest.mark.asyncio
async def test_prefetch_refuses_a_next_turn_that_is_not_ready(tmp_path: Path) -> None:
    service, debate, tasks, epoch, playing = await _playing(tmp_path, "notready-session")
    successor = debate.turns[1]
    successor.generation_status = "pending"
    successor.audio_relative_path = None
    with pytest.raises(PlatformError) as refused:
        await service.prefetch_next_audio(
            None,
            debate.id,
            expected_control_version=playing.control_version,
            expected_current_turn_id=debate.turns[0].id,
            epoch=epoch,
            session_hash="notready-session",
        )
    assert refused.value.code == "next_not_ready"
    await tasks.close()


@pytest.mark.asyncio
async def test_one_debate_lock_does_not_hold_another(tmp_path: Path) -> None:
    service, debate, tasks = await _memory_ready_service(tmp_path)
    async with service._debate_lock(debate.id, "test"):
        other_acquired = False
        async with service._debate_lock(str(uuid4()), "test"):
            other_acquired = True
        assert other_acquired
        assert service._debate_lock(debate.id, "test") is not None
    await tasks.close()
