"""/health/admission shows each per-operation gate's limit, holders and waiters (#140)."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
from app.core import adaptive_admission as aa
from app.core import llm_admission as la
from app.core import write_guard as wg
from app.core.backstops import backstop_usage
from app.core.config import Settings
from app.core.write_guard import write_guard_slot


@pytest.fixture()
def healthy() -> Iterator[None]:
    aa.reset_adaptive_admission_state()
    wg.reset_write_guard_state()
    la.reset_llm_admission_state()
    aa.set_signal_readers(load=lambda: 0.5, mem=lambda: 4000.0, clock=lambda: 0.0)
    yield
    aa.set_signal_readers()
    aa.reset_adaptive_admission_state()
    wg.reset_write_guard_state()
    la.reset_llm_admission_state()


def test_usage_reports_holders_and_waiters(healthy: None) -> None:
    s = Settings(  # type: ignore[call-arg]
        write_guard_limit=2,
        write_guard_wait_seconds=5,
        adaptive_admission_initial_units=128,
        adaptive_admission_wait_seconds=5,
    )
    release = threading.Event()
    held = threading.Barrier(3)

    def hold() -> None:
        with write_guard_slot(s):
            held.wait(5)
            release.wait(10)

    holders = [threading.Thread(target=hold) for _ in range(2)]
    for thread in holders:
        thread.start()
    held.wait(5)
    waiter = threading.Thread(target=lambda: write_guard_slot(s).__enter__())
    waiter.daemon = True
    waiter.start()
    deadline = time.monotonic() + 5
    while wg._GATE.waiters < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        usage = backstop_usage(s)
        assert usage["write_guard"] == {"limit": 2, "enabled": True, "in_flight": 2, "waiters": 1}
        assert usage["llm_admission"]["in_flight"] == 0
        assert set(usage) == {"llm_admission", "write_guard", "create_admission", "auth_hash"}
    finally:
        release.set()
        for thread in holders:
            thread.join()
        waiter.join(5)


def test_health_admission_includes_usage(client) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/health/admission").json()
    usage = body["backstop_usage"]
    assert set(usage) == {"llm_admission", "write_guard", "create_admission", "auth_hash"}
    for gate in usage.values():
        assert set(gate) == {"limit", "enabled", "in_flight", "waiters"}
    assert usage["auth_hash"]["limit"] == 2
