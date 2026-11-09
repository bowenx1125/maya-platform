"""Write guard 8 (required), budget 128, in-flight 48, and a probe that stays answerable."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import anyio
import anyio.to_thread
import pytest
from app.core import adaptive_admission as aa
from app.core import write_guard as wg
from app.core.config import Settings
from app.core.db import (
    POSTGRES_MAX_OVERFLOW,
    POSTGRES_POOL_SIZE,
    resolve_pool_config,
)
from app.core.errors import PlatformError
from app.core.llm_admission import llm_admission_slot
from app.core.write_guard import write_guard_slot
from fastapi.testclient import TestClient


@pytest.fixture()
def healthy() -> Iterator[None]:
    aa.reset_adaptive_admission_state()
    wg.reset_write_guard_state()
    aa.set_signal_readers(load=lambda: 0.5, mem=lambda: 4000.0, clock=lambda: 0.0)
    yield
    aa.set_signal_readers()
    aa.reset_adaptive_admission_state()
    wg.reset_write_guard_state()


def test_capacity_defaults_and_untouched_limits() -> None:
    s = Settings()  # type: ignore[call-arg]
    # #140 sweep (2026-10-18): write, create and LLM backstops are all 8 per
    # process.
    assert s.write_guard_limit == 8
    assert s.create_admission_limit == 8
    assert s.adaptive_admission_max_units == 128
    assert s.adaptive_admission_max_in_flight == 48
    # 20 turns x (write 2 + nested LLM 4) fit the ceiling and the global cap.
    per_turn = s.adaptive_admission_weight_write + s.adaptive_admission_weight_llm
    assert 20 * per_turn <= s.adaptive_admission_max_units
    assert 20 * 2 <= s.adaptive_admission_max_in_flight
    assert s.llm_admission_limit == 8
    # M3 moved the default to 2 (memory protection ≈ CPU cores).
    assert s.auth_hash_concurrency == 2
    # Defaults when env unset (module constants). Env may override at engine build.
    assert (POSTGRES_POOL_SIZE, POSTGRES_MAX_OVERFLOW) == (15, 25)
    assert 2 * (POSTGRES_POOL_SIZE + POSTGRES_MAX_OVERFLOW) <= 200 - 100
    assert resolve_pool_config() == (15, 25, 30.0)


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "adaptive_admission_initial_units": 128,
        "adaptive_admission_wait_seconds": 1,
        "write_guard_wait_seconds": 1,
        "llm_admission_wait_seconds": 1,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_eight_turns_run_and_the_ninth_waits_for_a_slot(healthy: None) -> None:
    """2026-10-18: 20 simultaneous assessment turns with no write cap drove
    the 2 vCPU host to load 10. Turns past 8 wait in the queue, then run."""

    s = _settings(write_guard_wait_seconds=10, adaptive_admission_wait_seconds=10)
    assert s.write_guard_limit == 8
    release = threading.Event()
    started = threading.Barrier(9)
    errors: list[BaseException] = []

    def message() -> None:
        try:
            with write_guard_slot(s), llm_admission_slot(s):
                started.wait(5)
                release.wait(10)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            started.abort()

    threads = [threading.Thread(target=message) for _ in range(8)]
    for thread in threads:
        thread.start()
    ninth_done = threading.Event()

    def ninth() -> None:
        with write_guard_slot(s):
            ninth_done.set()

    late = threading.Thread(target=ninth)
    try:
        started.wait(5)
        assert errors == []
        assert wg._GATE.in_flight == 8
        late.start()
        deadline = time.monotonic() + 5
        while wg._GATE.waiters < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert wg._GATE.waiters == 1  # queued, not refused
        assert not ninth_done.is_set()
    finally:
        release.set()
        for thread in threads:
            thread.join()
    late.join(5)
    assert ninth_done.is_set()
    assert wg._GATE.in_flight == 0
    assert aa._state.in_flight_units == 0


def test_the_forty_ninth_in_flight_request_waits(healthy: None) -> None:
    s = _settings(adaptive_admission_initial_units=500, adaptive_admission_max_units=500)
    release = threading.Event()
    started = threading.Barrier(49)

    def hold() -> None:
        with aa.adaptive_slot("login", s):
            started.wait(5)
            release.wait(10)

    threads = [threading.Thread(target=hold) for _ in range(48)]
    for thread in threads:
        thread.start()
    started.wait(5)
    try:
        with pytest.raises(PlatformError) as caught:
            with aa.adaptive_slot("login", s):
                pass
        assert caught.value.code == "adaptive_admission_busy"
        assert caught.value.details["reason"] == "wait_timeout"
    finally:
        release.set()
        for thread in threads:
            thread.join()


def test_ready_probe_answers_with_the_shared_pool_full(
    healthy: None, app_factory, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    app, _database, _settings_ = app_factory()
    release = threading.Event()
    with TestClient(app) as client:
        limiter = client.portal.call(anyio.to_thread.current_default_thread_limiter)
        assert limiter.total_tokens == 256

        # 48 admitted requests plus queued ones hold every shared worker thread.
        for _ in range(128):
            client.portal.start_task_soon(anyio.to_thread.run_sync, release.wait)
        deadline = time.monotonic() + 5
        while limiter.borrowed_tokens < 128 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert limiter.borrowed_tokens == 128
        result: dict[str, object] = {}

        def probe() -> None:
            started = time.monotonic()
            response = client.get("/health/ready")
            result["status"] = response.status_code
            result["seconds"] = time.monotonic() - started

        worker = threading.Thread(target=probe)
        worker.start()
        worker.join(5)
        release.set()
        worker.join(5)
    assert result.get("status") == 200
    assert float(result["seconds"]) < 2.0  # type: ignore[arg-type]


def test_streamed_work_is_not_capped_by_the_cpu_sized_default_executor(
    app_factory,
) -> None:  # type: ignore[no-untyped-def]
    # Streamed replies and Team runs use asyncio.to_thread. Python's default
    # executor is cpu_count + 4 threads (6 on the 2-vCPU host); 30 must run
    # at once, the way 20 streamed turns plus their polls do.
    import asyncio

    app, _database, _settings_ = app_factory()
    release = threading.Event()
    lock = threading.Lock()
    running = [0]

    def work() -> None:
        with lock:
            running[0] += 1
        release.wait(5)

    with TestClient(app) as client:
        for _ in range(30):
            client.portal.start_task_soon(asyncio.to_thread, work)
        deadline = time.monotonic() + 5
        while running[0] < 30 and time.monotonic() < deadline:
            time.sleep(0.01)
        concurrent = running[0]
        release.set()
    assert concurrent == 30


def test_write_cap_zero_still_disables_the_gate(healthy: None) -> None:
    s = _settings(write_guard_limit=0)
    release = threading.Event()
    started = threading.Barrier(26)

    def turn() -> None:
        with write_guard_slot(s):
            started.wait(5)
            release.wait(10)

    threads = [threading.Thread(target=turn) for _ in range(25)]
    for thread in threads:
        thread.start()
    try:
        started.wait(5)
        assert aa._state.in_flight["write"] == 25
        assert wg._GATE.in_flight == 0
    finally:
        release.set()
        for thread in threads:
            thread.join()


def test_fixed_write_cap_can_be_restored_from_the_environment(
    healthy: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WRITE_GUARD_LIMIT", "1")
    monkeypatch.setenv("CREATE_ADMISSION_LIMIT", "4")
    s = Settings(  # type: ignore[call-arg]
        adaptive_admission_initial_units=128,
        adaptive_admission_wait_seconds=1,
        write_guard_wait_seconds=1,
    )
    assert s.write_guard_limit == 1 and s.create_admission_limit == 4
    with write_guard_slot(s):
        failure: list[str] = []

        def second() -> None:
            try:
                with write_guard_slot(s):
                    pass
            except PlatformError as exc:
                failure.append(exc.code)

        thread = threading.Thread(target=second)
        thread.start()
        thread.join(5)
    assert failure == ["write_pressure"]


def test_postgres_pool_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """POSTGRES_POOL_* env overrides defaults; empty/unset keeps module defaults."""

    monkeypatch.delenv("POSTGRES_POOL_SIZE", raising=False)
    monkeypatch.delenv("POSTGRES_MAX_OVERFLOW", raising=False)
    monkeypatch.delenv("POSTGRES_POOL_TIMEOUT", raising=False)
    assert resolve_pool_config() == (POSTGRES_POOL_SIZE, POSTGRES_MAX_OVERFLOW, 30.0)

    monkeypatch.setenv("POSTGRES_POOL_SIZE", "100")
    monkeypatch.setenv("POSTGRES_MAX_OVERFLOW", "100")
    monkeypatch.setenv("POSTGRES_POOL_TIMEOUT", "10")
    assert resolve_pool_config() == (100, 100, 10.0)

    # Explicit kwargs win over env (used by tests that pin a pool).
    assert resolve_pool_config(pool_size=10, max_overflow=50, pool_timeout=5.0) == (
        10,
        50,
        5.0,
    )
