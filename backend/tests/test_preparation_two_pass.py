"""A charged reply that is staged must be published, exactly once.

A real-provider turn is produced in two passes on purpose: the first accepts
and stages the reply the supplier was paid for, the second publishes it, so a
crash between them cannot lose a charged answer. Nothing was making the second
pass. Every turn it happened to hit stopped one step short of ready — the money
spent, the answer on disk, the turn still pending with no error to show — and
the debate sat at Running or Thinking with nothing a teacher could act on.

These are the rules of the gate that closes it. The dangerous half is the third
test: a second pass on a turn with nothing staged would reach the supplier
again and charge for it twice.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.modules.debates.playback._preparation import PlaybackPreparationMixin


class _Recorder(PlaybackPreparationMixin):
    """Counts passes without touching a database or a provider."""

    def __init__(self, *, ready_after: int | None, staged: bool) -> None:
        self.passes = 0
        self._ready_after = ready_after
        self._staged = staged

    async def _prepare_turn_pass(self, db: Any, debate_id: str, turn_id: str) -> None:
        self.passes += 1

    def _turn_is_ready(self, db: Any, debate_id: str, turn_id: str) -> bool:
        return self._ready_after is not None and self.passes >= self._ready_after

    @staticmethod
    def _has_accepted_llm_stage(db: Any, turn_id: str) -> bool:  # type: ignore[override]
        raise AssertionError("replaced per instance")


def _run(service: _Recorder) -> None:
    staged = service._staged
    service._has_accepted_llm_stage = lambda db, turn_id: staged  # type: ignore[assignment]
    asyncio.run(service.prepare_turn(None, "debate-a", "turn-a"))


def test_a_turn_that_is_already_ready_is_prepared_once() -> None:
    service = _Recorder(ready_after=1, staged=False)
    _run(service)
    assert service.passes == 1


def test_a_staged_reply_gets_the_publishing_pass() -> None:
    """The first pass stages, the second publishes, and the turn is ready."""

    service = _Recorder(ready_after=2, staged=True)
    _run(service)
    assert service.passes == 2


def test_nothing_staged_means_no_second_pass() -> None:
    """The second pass may only ever publish, never generate.

    Without this gate a turn that failed for any other reason would be sent to
    the supplier a second time and charged for twice.
    """

    service = _Recorder(ready_after=None, staged=False)
    _run(service)
    assert service.passes == 1


def test_the_publishing_pass_is_never_repeated() -> None:
    """A turn that stays unready after publishing stops, rather than spinning.

    Two passes is the whole budget: the design has exactly two phases, so a
    third would mean something else is wrong and looping on it would hold the
    debate open forever instead of leaving a state a teacher can act on.
    """

    service = _Recorder(ready_after=None, staged=True)
    _run(service)
    assert service.passes == 2
