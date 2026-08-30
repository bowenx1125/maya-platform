"""Focused Wave 3 playback control and partial-finish invariants."""

from __future__ import annotations

import pytest
from app.modules.debates.playback.protocols import (
    MemoryDebate,
    MemoryParticipant,
    MemoryPlaybackRepository,
    MemoryTurn,
)
from app.modules.debates.playback.service import PlaybackService


def _running_debate(
    repository: MemoryPlaybackRepository,
    *,
    complete: bool,
) -> MemoryDebate:
    debate = MemoryDebate(
        status="running",
        participants=[MemoryParticipant(name="A"), MemoryParticipant(name="B")],
    )
    repository.add_debate(debate)
    turns: list[MemoryTurn] = []
    for index, participant in enumerate(debate.participants):
        turns.append(
            MemoryTurn(
                participant_id=participant.id,
                round_no=1,
                turn_index=index,
                generation_status=("final_ready" if complete or index == 0 else "pending"),
                publication_status="public" if complete or index == 0 else "unpublished",
                speech=("A complete classroom speech." if complete or index == 0 else None),
                audio_file_id=(f"audio-{index}" if complete or index == 0 else None),
            )
        )
    debate.turns = turns
    debate.playback.status = "playing"
    debate.playback.current_turn_id = turns[0].id
    return debate


@pytest.mark.asyncio
async def test_pause_resume_is_recoverable_and_defers_resumed_event_until_playing() -> None:
    repository = MemoryPlaybackRepository()
    debate = _running_debate(repository, complete=True)
    service = PlaybackService(repository)

    paused = await service.pause(None, debate.id, expected_control_version=0)
    assert paused.status == "paused"
    assert debate.status == "running"
    assert str(paused.current_turn_id) == debate.turns[0].id

    resumed = await service.resume(
        None,
        debate.id,
        expected_control_version=paused.control_version,
    )
    assert resumed.status == "ready"
    assert debate.status == "running"
    assert [event.event_type for event in service.event_hub.store.events_after(debate.id, 0)] == [
        "playback.paused",
    ]


@pytest.mark.asyncio
async def test_full_finish_keeps_turns_and_enters_normal_finished_flow() -> None:
    repository = MemoryPlaybackRepository()
    debate = _running_debate(repository, complete=True)
    debate.playback.status = "waiting_next"
    service = PlaybackService(repository)

    result = await service.finish(None, debate.id, expected_control_version=0)

    assert result.status == "completed"
    assert debate.status == "debate_finished"
    assert len(debate.turns) == 2
    assert service.event_hub.store.last_sequence(debate.id) == 1


@pytest.mark.asyncio
async def test_early_finish_marks_debate_finished_but_stops_playback() -> None:
    repository = MemoryPlaybackRepository()
    debate = _running_debate(repository, complete=False)
    debate.playback.status = "waiting_next"
    service = PlaybackService(repository)

    result = await service.finish(None, debate.id, expected_control_version=0)

    assert result.status == "stopped"
    assert debate.status == "debate_finished"
    assert debate.cancellation_generation == 1
    assert len(debate.turns) == 2
    assert repository.jobs_interrupted == [(debate.id, "debate_finished_partial")]


@pytest.mark.asyncio
async def test_restart_preserves_explicit_paused_state_even_with_inflight_turn() -> None:
    repository = MemoryPlaybackRepository()
    debate = _running_debate(repository, complete=False)
    debate.turns[1].generation_status = "running"
    debate.playback.status = "paused"
    debate.playback.cursor_ms = 321
    service = PlaybackService(repository)

    affected = await service.recover_startup(None)

    assert debate.id not in affected
    assert debate.status == "running"
    assert debate.playback.status == "paused"
    assert debate.playback.cursor_ms == 321
    assert debate.turns[1].generation_status == "running"
