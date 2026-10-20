"""Server push of a course's Live status to student pages (2026-10-20).

Every student tab used to ask ``GET /courses/{id}/live`` every 5 s (80 tabs,
about 16 requests a second). Now a tab opens one WebSocket and is told when
the course goes live or stops. Each backend process runs ONE watcher task,
only while it has subscribers, that reads ``live_presence`` for all its
subscribed courses in one query every ``POLL_SECONDS``. ``live_presence`` is
the shared row both backends write (teacher heartbeats), so a broadcast
started through either backend, and a lease that simply expires, reach every
socket within one poll. Postgres LISTEN/NOTIFY was not used: it cannot see a
lease expiring and needs a dedicated connection per process; one indexed
read every 2 s per process is cheaper than the polling it replaces.

Sockets are capped per process (``MAX_SOCKETS``); a refused tab keeps the
client's slow fallback poll.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from .schemas import LiveSummary

LOGGER = logging.getLogger(__name__)

POLL_SECONDS = 2.0
MAX_SOCKETS = 400

Loader = Callable[[list[str]], dict[str, LiveSummary | None]]


class CourseLiveWatcher:
    def __init__(self, load: Loader, *, poll_seconds: float = POLL_SECONDS) -> None:
        self._load = load
        self.poll_seconds = poll_seconds
        self._subscribers: dict[str, set[asyncio.Queue[LiveSummary | None]]] = defaultdict(set)
        self._last: dict[str, LiveSummary | None] = {}
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self.reads = 0

    def socket_count(self) -> int:
        return sum(len(items) for items in self._subscribers.values())

    async def subscribe(self, course_id: str) -> asyncio.Queue[LiveSummary | None] | None:
        """A queue that receives each change; ``None`` when the process is full."""

        async with self._lock:
            if self.socket_count() >= MAX_SOCKETS:
                return None
            queue: asyncio.Queue[LiveSummary | None] = asyncio.Queue()
            self._subscribers[course_id].add(queue)
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run())
        return queue

    async def unsubscribe(self, course_id: str, queue: asyncio.Queue[Any]) -> None:
        task: asyncio.Task[None] | None = None
        async with self._lock:
            items = self._subscribers.get(course_id)
            if items is not None:
                items.discard(queue)
                if not items:
                    self._subscribers.pop(course_id, None)
                    self._last.pop(course_id, None)
            if not self._subscribers and self._task is not None:
                task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def check_now(self) -> None:
        """One watcher pass (tests and the first read)."""

        courses = list(self._subscribers)
        if not courses:
            return
        self.reads += 1
        current = await asyncio.to_thread(self._load, courses)
        for course_id in courses:
            value = current.get(course_id)
            if course_id in self._last and _same(self._last[course_id], value):
                continue
            self._last[course_id] = value
            for queue in tuple(self._subscribers.get(course_id, ())):
                queue.put_nowait(value)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.poll_seconds)
            try:
                await self.check_now()
            except Exception:
                # The next pass asks again; clients also keep a slow poll.
                LOGGER.warning("Course live watcher read failed", exc_info=True)


def _same(a: LiveSummary | None, b: LiveSummary | None) -> bool:
    if a is None or b is None:
        return a is b
    return a.debate_id == b.debate_id and a.topic == b.topic


def as_message(value: LiveSummary | None) -> dict[str, Any]:
    return {"live": value.model_dump(mode="json") if value is not None else None}
