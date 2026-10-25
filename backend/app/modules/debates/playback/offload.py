"""Run playback work, and its synchronous SQL, off the server's event loop (PR C).

Playback routes and WebSocket commands are coroutines whose bodies are mostly
synchronous SQLAlchemy calls. On the event loop each query stalled every other
request and socket of the process (a Next waited behind a snapshot build).
``run_offloaded`` runs such a coroutine to completion on a worker thread with
its own short-lived loop. The few things that belong to the server loop
(publishing to WebSocket subscribers, background preparation tasks, socket
callbacks) go back to it through ``on_main`` / ``spawn_on_main``; called on the
server loop itself, both are plain awaits, so direct callers (tests, startup,
background tasks) behave exactly as before.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

_state = threading.local()


def _main_loop() -> asyncio.AbstractEventLoop | None:
    return getattr(_state, "main_loop", None)


def offloaded_now() -> bool:
    """True inside ``run_offloaded`` (on its worker thread)."""

    return _main_loop() is not None


async def run_offloaded[T](work: Callable[[], Awaitable[T]]) -> T:
    """Run ``work()`` on a worker thread and return (or raise) its result.

    Context variables (request timing, read memo, request id) are copied in,
    as ``asyncio.to_thread`` does. If the caller is cancelled (a client went
    away), the work still finishes so no state change is left half done.
    """

    main = asyncio.get_running_loop()

    async def wrapped() -> T:
        return await work()

    def run() -> T:
        _state.main_loop = main
        try:
            return asyncio.run(wrapped())
        finally:
            _state.main_loop = None

    return await asyncio.shield(asyncio.ensure_future(asyncio.to_thread(run)))


async def on_main[T](awaitable: Coroutine[Any, Any, T]) -> T:
    """Await ``awaitable`` on the server loop."""

    main = _main_loop()
    if main is None:
        return await awaitable
    return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(awaitable, main))


def spawn_on_main(awaitable: Coroutine[Any, Any, Any]) -> None:
    """Start ``awaitable`` on the server loop without waiting for it."""

    main = _main_loop()
    if main is None:
        asyncio.get_running_loop().create_task(awaitable)
        return
    asyncio.run_coroutine_threadsafe(awaitable, main)
