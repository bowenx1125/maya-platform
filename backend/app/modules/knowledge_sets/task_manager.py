"""Wake pending durable Knowledge generation intents without provider calls."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from .generation import (
    block_claimed_generation,
    list_pending_generation_runs,
    mark_generation_worker_failure,
)

LOGGER = logging.getLogger(__name__)


class KnowledgeGenerationTaskManager:
    """Small wake layer; persisted Jobs and runs remain the source of truth."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._rewake: set[str] = set()
        self._closed = False

    def bind_running_loop(self) -> None:
        self._loop = asyncio.get_running_loop()

    def wake(self, run_id: str) -> None:
        loop = self._loop
        if self._closed or loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._schedule, run_id)

    def schedule_pending(self) -> None:
        with self.session_factory() as db:
            run_ids = list_pending_generation_runs(db)
        for run_id in run_ids:
            self.wake(run_id)

    def _schedule(self, run_id: str) -> None:
        current = self._tasks.get(run_id)
        if current is not None and not current.done():
            self._rewake.add(run_id)
            return
        task = asyncio.create_task(self._run(run_id), name=f"maya-knowledge-generation-{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _task: self._finished(run_id))

    def _finished(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)
        if self._closed:
            self._rewake.discard(run_id)
            return
        if run_id in self._rewake:
            self._rewake.discard(run_id)
            self._schedule(run_id)

    async def _run(self, run_id: str) -> None:
        work = asyncio.create_task(
            asyncio.to_thread(block_claimed_generation, self.session_factory, run_id)
        )
        try:
            await asyncio.shield(work)
        except asyncio.CancelledError:
            try:
                await work
            except Exception:
                pass
            raise
        except Exception as exc:
            LOGGER.error(
                "Knowledge generation worker stopped run_id=%s error_type=%s",
                run_id,
                type(exc).__name__,
            )
            try:
                await asyncio.to_thread(
                    mark_generation_worker_failure, self.session_factory, run_id
                )
            except Exception as failure:
                LOGGER.error(
                    "Knowledge generation failure could not be recorded run_id=%s error_type=%s",
                    run_id,
                    type(failure).__name__,
                )

    async def close(self) -> None:
        self._closed = True
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


__all__ = ["KnowledgeGenerationTaskManager"]
