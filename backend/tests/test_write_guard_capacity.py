"""Write guard 20, budget 128, in-flight 48, and a probe that stays answerable."""

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
from app.core.db import POSTGRES_MAX_OVERFLOW, POSTGRES_POOL_SIZE
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
    assert s.write_guard_limit == 20
    assert s.adaptive_admission_max_units == 128
    assert s.adaptive_admission_max_in_flight == 48
    # 20 turns x (write 2 + nested LLM 4) fit the ceiling and the global cap.
    per_turn = s.adaptive_admission_weight_write + s.adaptive_admission_weight_llm
    assert 20 * per_turn <= s.adaptive_admission_max_units
    assert 20 * 2 <= s.adaptive_admission_max_in_flight
    # Explicitly unchanged.
    assert s.auth_hash_concurrency == 3
    assert s.llm_admission_limit == 20
    assert (POSTGRES_POOL_SIZE, POSTGRES_MAX_OVERFLOW) == (15, 25)
    assert 2 * (POSTGRES_POOL_SIZE + POSTGRES_MAX_OVERFLOW) <= 200 - 100


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "adaptive_admission_initial_units": 128,
        "adaptive_admission_wait_seconds": 1,
        "write_guard_wait_seconds": 1,
        "llm_admission_wait_seconds": 1,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_twenty_concurrent_messages_are_all_admitted(healthy: None) -> None:
    s = _settings()
    release = threading.Event()
    started = threading.Barrier(21)
    errors: list[BaseException] = []

    def message() -> None:
        try:
            with write_guard_slot(s), llm_admission_slot(s):
                started.wait(5)
                release.wait(10)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            started.abort()

    threads = [threading.Thread(target=message) for _ in range(20)]
    for thread in threads:
        thread.start()
    try:
        started.wait(5)
        assert errors == []
        assert aa._state.in_flight["write"] == 20
        assert aa._state.in_flight["llm"] == 20
        assert aa._state.in_flight_units == 120
        assert wg._GATE.in_flight == 20
    finally:
        release.set()
        for thread in threads:
            thread.join()
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
        assert limiter.total_tokens == 128

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
