"""Warm a draft Debate's turns before the teacher starts it.

A lesson used to begin with the room watching a spinner: the first turn was
only requested when Start was pressed, and every later turn only when the
previous one finished. The work is the same work either way, so it happens
while the draft sits in the list instead.

Three rules shape it, and they are the product's rules rather than the
scheduler's convenience:

* **One at a time.** Warming two drafts at once halves the bandwidth of both,
  and the teacher is only ever about to run one of them. Opening another debate
  hands ownership to it and the previous draft yields.
* **Yield is not stop.** A yielding draft finishes the turn it is on, keeps
  every turn it has already produced, and can be picked up again exactly where
  it left off. Nothing already paid for is discarded.
* **End is terminal.** A debate that has been ended never warms again, however
  many turns it is missing.

Turns are prepared strictly in order, through the same preparation path a
running lesson uses, writing the same rows. When the teacher starts the debate,
`_turn_ready` skips what is already there and the lesson simply begins.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

LOGGER = logging.getLogger(__name__)

Prepare = Callable[[str, str], Awaitable[None]]
Plan = Callable[[str], list[tuple[str, bool]]]


class PrewarmScheduler:
    """Runs one draft Debate's turns ahead of its lesson."""

    def __init__(self, *, plan: Plan, prepare: Prepare) -> None:
        # ``plan`` returns this Debate's turns in order as (turn_id, ready).
        self._plan = plan
        self._prepare = prepare
        self._loop: asyncio.AbstractEventLoop | None = None
        self._owner: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._ended: set[str] = set()
        self._stalled: set[str] = set()
        self._closed = False
        self._resume_queue: list[str] = []

    @property
    def owner(self) -> str | None:
        """The Debate currently warming, if any."""

        return self._owner

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def bind_running_loop(self) -> None:
        self._loop = asyncio.get_running_loop()

    def disable(self) -> None:
        """Never warm anything. Used where background writes are not wanted."""

        self._closed = True

    def focus(self, debate_id: str) -> None:
        """Give this Debate the bandwidth; whatever held it yields."""

        loop = self._loop
        if self._closed or loop is None or loop.is_closed():
            LOGGER.warning(
                "prewarm_focus_skip debate_id=%s reason=%s",
                debate_id,
                "closed" if self._closed else "loop_unbound",
            )
            return
        if debate_id in self._ended:
            LOGGER.info("prewarm_focus_skip debate_id=%s reason=ended", debate_id)
            return
        loop.call_soon_threadsafe(self._focus, debate_id)

    def resume(self, debate_id: str) -> None:
        """An explicit Remake reopens a draft and resumes its whole Preview."""
        self._ended.discard(debate_id)
        loop = self._loop
        if self._closed or loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._resume, debate_id)

    def _resume(self, debate_id: str) -> None:
        if self._task is not None and not self._task.done() and self._owner != debate_id:
            if debate_id not in self._resume_queue:
                self._resume_queue.append(debate_id)
            return
        self._focus(debate_id)

    def release(self, debate_id: str) -> None:
        """This Debate is over: never warm it again."""

        self._ended.add(debate_id)
        self._resume_queue = [item for item in self._resume_queue if item != debate_id]
        loop = self._loop
        if self._closed or loop is None or loop.is_closed():
            return
        if self._owner == debate_id:
            loop.call_soon_threadsafe(self._focus, None)

    def _focus(self, debate_id: str | None) -> None:
        self._resume_queue = [item for item in self._resume_queue if item != debate_id]
        # A debate whose turn already failed does not take the warmer away
        # from another debate. It waits until that one yields.
        if (
            debate_id is not None
            and debate_id in self._stalled
            and self._owner not in {None, debate_id}
        ):
            if debate_id not in self._resume_queue:
                self._resume_queue.append(debate_id)
            return
        if self._owner == debate_id and self._task is not None and not self._task.done():
            return
        self._owner = debate_id
        # The running chain checks ownership between turns, so it stops on its
        # own at the next boundary rather than being cancelled mid-provider
        # call. Cancelling there would throw away a request already paid for.
        if debate_id is None:
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(debate_id), name=f"maya-prewarm-{debate_id}")

    async def _run(self, debate_id: str) -> None:
        try:
            while not self._closed:
                owner = self._owner
                if owner is None or owner in self._ended:
                    return
                try:
                    # The plan reads and may materialise turn rows, which is
                    # blocking SQL. Run directly it would sit on the event loop
                    # and deadlock against the very request that just asked for
                    # this warm-up: that request still holds the writer lock,
                    # and nothing can release it while the loop is blocked.
                    plan = await asyncio.to_thread(self._plan, owner)
                    pending = [turn_id for turn_id, ready in plan if not ready]
                except Exception:
                    LOGGER.exception("Could not read the pre-warm plan for %s", owner)
                    return
                if not pending:
                    # Fully warm. Another draft may take the bandwidth now.
                    return
                target = pending[0]
                await self._prepare(owner, target)
                # A turn that did not advance is not retried in a loop: a
                # refused claim or a failed generation would otherwise spin
                # against the provider for as long as the draft existed.
                if any(
                    turn_id == target and not ready
                    for turn_id, ready in await asyncio.to_thread(self._plan, owner)
                ):
                    # This draft cannot advance. Leave the warmer for whichever
                    # debate was opened after it, instead of holding the slot.
                    self._stalled.add(owner)
                    if self._owner == owner:
                        self._owner = None
                    LOGGER.info("Pre-warm stopped for %s: turn %s did not advance", owner, target)
                    return
                self._stalled.discard(owner)
                # Ownership is re-read here, at the turn boundary, so a debate
                # the teacher has since opened takes over without this one
                # losing the turn it just produced.
                if self._owner != owner:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Pre-warm stopped for debate %s", debate_id)
        finally:
            # Every exit from the loop above releases the bandwidth, not only
            # the ownership-change one: a draft that finished warming, one
            # whose turn did not advance, and one that raised all used to
            # return without handing the slot on. Whatever the teacher has
            # since opened then waited forever, and nothing warmed at all.
            self._task = None
            if not self._closed and self._owner is not None and self._owner != debate_id:
                self._focus(self._owner)
            elif not self._closed and self._resume_queue:
                nxt = next(
                    (item for item in self._resume_queue if item not in self._stalled),
                    None,
                )
                if nxt is None:
                    nxt = self._resume_queue.pop(0)
                else:
                    self._resume_queue.remove(nxt)
                self._focus(nxt)

    async def close(self) -> None:
        self._closed = True
        self._resume_queue.clear()
        task = self._task
        self._task = None
        self._owner = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


def prewarm_progress(turns: list[Any], expected: int) -> tuple[int, int]:
    """How much of a Debate's plan is already generated.

    The denominator is the plan the RuleSet actually produced, not a fixed
    shape: this is read the same way for two Agents over two rounds and five
    over five.
    """

    ready = sum(
        1
        for turn in turns
        if str(getattr(turn, "generation_status", "")) in {"final_ready", "ready", "completed"}
    )
    return ready, max(expected, 0)


__all__ = ["PrewarmScheduler", "prewarm_progress"]
