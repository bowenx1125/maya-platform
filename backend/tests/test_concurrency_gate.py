"""Process-local concurrency gate: admit, queue wait, cap, disable."""

from __future__ import annotations

import threading
import time

import pytest
from app.core.concurrency_gate import ConcurrencyGate, GateRejected


def test_admit_under_limit() -> None:
    gate = ConcurrencyGate()
    with gate.hold(limit=2, queue_max=4, wait_seconds=1.0):
        assert gate.in_flight == 1
        with gate.hold(limit=2, queue_max=4, wait_seconds=1.0):
            assert gate.in_flight == 2
    assert gate.in_flight == 0


def test_disabled_when_limit_zero() -> None:
    gate = ConcurrencyGate()
    with gate.hold(limit=0, queue_max=0, wait_seconds=0.0):
        assert gate.in_flight == 0


def test_queue_full_rejects_immediately() -> None:
    gate = ConcurrencyGate()
    entered = threading.Event()
    release = threading.Event()

    def hold_slot() -> None:
        with gate.hold(limit=1, queue_max=1, wait_seconds=5.0):
            entered.set()
            release.wait(timeout=5.0)

    holder = threading.Thread(target=hold_slot)
    holder.start()
    assert entered.wait(timeout=2.0)

    waiter_started = threading.Event()
    waiter_blocked = threading.Event()

    def wait_one() -> None:
        waiter_started.set()
        with gate.hold(limit=1, queue_max=1, wait_seconds=5.0):
            waiter_blocked.set()

    waiter = threading.Thread(target=wait_one)
    waiter.start()
    assert waiter_started.wait(timeout=2.0)
    time.sleep(0.05)  # let waiter register

    with pytest.raises(GateRejected) as raised:
        with gate.hold(limit=1, queue_max=1, wait_seconds=0.1):
            pass
    assert raised.value.reason == "queue_full"

    release.set()
    holder.join(timeout=2.0)
    waiter.join(timeout=2.0)
    assert waiter_blocked.is_set()
    assert gate.in_flight == 0


def test_waiter_proceeds_when_slot_frees() -> None:
    gate = ConcurrencyGate()
    release = threading.Event()
    waiter_got_slot = threading.Event()

    def hold_slot() -> None:
        with gate.hold(limit=1, queue_max=4, wait_seconds=5.0):
            release.wait(timeout=5.0)

    holder = threading.Thread(target=hold_slot)
    holder.start()
    time.sleep(0.05)

    def wait_then_hold() -> None:
        with gate.hold(limit=1, queue_max=4, wait_seconds=5.0):
            waiter_got_slot.set()

    waiter = threading.Thread(target=wait_then_hold)
    waiter.start()
    time.sleep(0.05)
    assert not waiter_got_slot.is_set()
    release.set()
    waiter.join(timeout=2.0)
    holder.join(timeout=2.0)
    assert waiter_got_slot.is_set()
    assert gate.in_flight == 0


def test_wait_timeout_rejects() -> None:
    gate = ConcurrencyGate()
    release = threading.Event()

    def hold_slot() -> None:
        with gate.hold(limit=1, queue_max=4, wait_seconds=5.0):
            release.wait(timeout=5.0)

    holder = threading.Thread(target=hold_slot)
    holder.start()
    time.sleep(0.05)

    with pytest.raises(GateRejected) as raised:
        with gate.hold(limit=1, queue_max=4, wait_seconds=0.05):
            pass
    assert raised.value.reason == "wait_timeout"

    release.set()
    holder.join(timeout=2.0)


def test_reset_clears_counters() -> None:
    gate = ConcurrencyGate()
    # Simulate a leaked counter then reset (tests only).
    with gate._lock:  # noqa: SLF001
        gate._in_flight = 3
        gate._waiters = 2
    gate.reset()
    assert gate.in_flight == 0
    assert gate.waiters == 0
