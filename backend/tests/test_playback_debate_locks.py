"""One playback writer per Debate across threads and replicas (PR C)."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from app.modules.debates.playback.locks import DebateLocks
from sqlalchemy import create_engine

from tests.postgres_db import new_database_url


def _engine():  # type: ignore[no-untyped-def]
    return create_engine(new_database_url(schema=False), future=True)


def test_two_replicas_never_hold_the_same_debate_together() -> None:
    engine = _engine()
    one, two = DebateLocks(engine), DebateLocks(engine)
    assert one.shared and two.shared
    inside = 0
    overlap = False
    guard = threading.Lock()

    def writer(locks: DebateLocks) -> None:
        nonlocal inside, overlap
        for _ in range(5):
            release = locks.acquire_blocking("debate-a")
            try:
                with guard:
                    inside += 1
                    overlap = overlap or inside > 1
                time.sleep(0.01)
                with guard:
                    inside -= 1
            finally:
                release()

    threads = [threading.Thread(target=writer, args=(locks,)) for locks in (one, two, one)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not overlap
    one.dispose()
    two.dispose()
    engine.dispose()


def test_different_debates_do_not_wait_for_each_other() -> None:
    engine = _engine()
    one, two = DebateLocks(engine), DebateLocks(engine)
    release_a = one.acquire_blocking("debate-a")
    started = time.monotonic()
    release_b = two.acquire_blocking("debate-b")
    assert time.monotonic() - started < 1
    release_b()
    release_a()
    one.dispose()
    two.dispose()
    engine.dispose()


@pytest.mark.asyncio
async def test_a_cancelled_wait_still_releases_the_lock_it_later_gets() -> None:
    engine = _engine()
    first, second = DebateLocks(engine), DebateLocks(engine)
    held = await first.acquire("debate-a")
    waiter = asyncio.create_task(second.acquire("debate-a"))
    await asyncio.sleep(0.1)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await first.release(held)
    # The cancelled waiter got the lock after all and gave it straight back.
    again = await asyncio.wait_for(first.acquire("debate-a"), timeout=5)
    await first.release(again)
    first.dispose()
    second.dispose()
    engine.dispose()


@pytest.mark.asyncio
async def test_without_postgres_the_lock_still_serializes_threads() -> None:
    locks = DebateLocks()
    assert not locks.shared
    release = await locks.acquire("debate-a")
    waiter = asyncio.create_task(locks.acquire("debate-a"))
    await asyncio.sleep(0.05)
    assert not waiter.done()
    await locks.release(release)
    await locks.release(await asyncio.wait_for(waiter, timeout=5))
