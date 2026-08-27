"""Bounded single-process playback preparation task manager."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

Preparation = Callable[[str, str], Awaitable[None]]


@dataclass(frozen=True)
class TaskKey:
    debate_id: str
    turn_id: str


class TaskManager:
    """A small asyncio task registry with deterministic duplicate fencing.

    Uvicorn runs this manager in one backend process.  The manager itself does
    not decide which turns are legal; :class:`PlaybackService` performs the
    current/current+one-next database CAS before enqueueing work.  This class
    only prevents duplicate local asyncio tasks and provides cancellation on
    stop/restart.
    """

    def __init__(self) -> None:
        self._tasks: dict[TaskKey, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def active_keys(self) -> tuple[TaskKey, ...]:
        return tuple(self._tasks)

    async def enqueue(
        self,
        debate_id: str,
        turn_id: str,
        preparation: Preparation,
    ) -> bool:
        """Schedule one preparation if this debate/turn is not already active."""

        if self._closed:
            return False
        key = TaskKey(debate_id, turn_id)
        async with self._lock:
            previous = self._tasks.get(key)
            if previous is not None and not previous.done():
                return False
            task = asyncio.create_task(self._run(key, preparation), name=f"maya-debate-{turn_id}")
            self._tasks[key] = task
            return True

    async def _run(self, key: TaskKey, preparation: Preparation) -> None:
        try:
            await preparation(key.debate_id, key.turn_id)
        except asyncio.CancelledError:
            raise
        finally:
            async with self._lock:
                current = self._tasks.get(key)
                if current is asyncio.current_task():
                    self._tasks.pop(key, None)

    async def cancel_debate(self, debate_id: str) -> None:
        """Cancel all pending local work for one debate."""

        async with self._lock:
            tasks = [task for key, task in self._tasks.items() if key.debate_id == debate_id]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def cancel_turn(self, debate_id: str, turn_id: str) -> None:
        async with self._lock:
            task = self._tasks.get(TaskKey(debate_id, turn_id))
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def wait_debate(self, debate_id: str) -> None:
        """Wait for currently visible work; useful for deterministic tests."""

        while True:
            async with self._lock:
                tasks = [task for key, task in self._tasks.items() if key.debate_id == debate_id]
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)

    async def recover_startup(self, recover: Callable[[], Any]) -> Any:
        """Run the repository's startup fence before accepting new work."""

        if self._closed:
            return None
        result = recover()
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def close(self) -> None:
        self._closed = True
        async with self._lock:
            tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._lock:
            self._tasks.clear()
