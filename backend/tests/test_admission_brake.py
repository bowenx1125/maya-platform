"""Fast brake: faster signals than load1 cut the budget within seconds.

2026-10-18: 20 simultaneous assessment turns took a 2 vCPU host to load
10.01 in 29 s; danger only entered at load 7.3 because load1 is a
one-minute average, and admitted turns kept writing. The brake reads a
10 s DB write / pool-wait p95, the write statements running now and host
CPU busy, on every 1 s sample.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.core import adaptive_admission as aa
from app.core.config import Settings


class _Probe:
    def __init__(self) -> None:
        self.now = 0.0
        self.cpu: float | None = 0.2


@pytest.fixture()
def probe() -> Iterator[_Probe]:
    p = _Probe()
    aa.reset_adaptive_admission_state()
    aa.set_signal_readers(
        load=lambda: 0.5, mem=lambda: 4000.0, clock=lambda: p.now, cpu=lambda: p.cpu
    )
    yield p
    aa.set_signal_readers()
    aa.reset_adaptive_admission_state()


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"adaptive_admission_wait_seconds": 1}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _tick(probe: _Probe, s: Settings, seconds: float = 1.0) -> dict[str, object]:
    probe.now += seconds
    return aa.adaptive_admission_snapshot(s)


def _hold_units(units: int) -> None:
    with aa._cond:
        aa._state.in_flight["write"] = units // 2
        aa._state.in_flight_units = units


def test_defaults() -> None:
    s = Settings()  # type: ignore[call-arg]
    assert s.adaptive_admission_brake_db_write_p95_ms == 800
    assert s.adaptive_admission_brake_pool_wait_p95_ms == 250
    assert s.adaptive_admission_brake_writes_in_flight == 10
    assert (s.adaptive_admission_brake_cpu_ratio, s.adaptive_admission_brake_cpu_samples) == (
        0.95,
        3,
    )
    # The danger line is unchanged.
    assert (s.host_load_reject_threshold, s.host_load_resume_threshold) == (6.0, 4.0)


@pytest.mark.parametrize(
    ("reason", "setup"),
    [
        ("brake_db_write_p95", lambda: [aa.record_db_write_ms(900.0) for _ in range(8)]),
        ("brake_pool_wait_p95", lambda: [aa.record_pool_wait_ms(300.0) for _ in range(5)]),
        ("brake_writes_in_flight", lambda: [aa.db_write_started() for _ in range(10)]),
    ],
)
def test_each_brake_cuts_at_once_and_admits_nothing_new(probe: _Probe, reason: str, setup) -> None:  # type: ignore[no-untyped-def]
    s = _settings()
    aa.adaptive_admission_snapshot(s)
    assert aa._state.budget == 72
    _hold_units(30)
    setup()
    snapshot = _tick(probe, s)  # one 1 s sample, inside the 2 s adjust interval
    brake = snapshot["brake"]
    assert brake["active_reason"] == reason  # type: ignore[index]
    assert brake["counts"][reason] == 1  # type: ignore[index]
    # Halved (72 -> 36) and clamped to what already runs (30): nothing new fits.
    assert aa._state.budget == 30
    assert not aa._fits(1, s)


def test_cpu_must_stay_hot_for_three_samples(probe: _Probe) -> None:
    s = _settings()
    aa.adaptive_admission_snapshot(s)
    _hold_units(10)
    probe.cpu = 0.99
    _tick(probe, s)
    _tick(probe, s)
    assert aa._state.brake_reason is None  # a short spike is not a brake
    assert _tick(probe, s)["brake"]["active_reason"] == "brake_cpu"  # type: ignore[index]
    assert aa._state.budget == 10


def test_brake_halves_once_per_cooldown_and_blocks_growth(probe: _Probe) -> None:
    s = _settings()
    aa.adaptive_admission_snapshot(s)
    _hold_units(60)
    for _ in range(10):
        aa.db_write_started()
    _tick(probe, s)
    assert aa._state.budget == 36  # 72 * 0.5
    _tick(probe, s)
    _tick(probe, s)
    assert aa._state.budget == 36  # within the 5 s cooldown: no second halving
    assert aa._state.brake_counts["brake_writes_in_flight"] == 1
    _tick(probe, s, seconds=5.0)
    assert aa._state.budget == 18
    # Healthy again: AIMD grows it back from there.
    for _ in range(10):
        aa.db_write_finished()
    _hold_units(0)
    _tick(probe, s, seconds=2.0)
    assert aa._state.brake_reason is None
    assert aa._state.budget == 22  # +4 below half of max


def test_brake_window_drains_in_ten_seconds(probe: _Probe) -> None:
    s = _settings()
    aa.adaptive_admission_snapshot(s)
    for _ in range(8):
        aa.record_db_write_ms(2_000.0)
    _tick(probe, s)
    assert aa._state.brake_reason == "brake_db_write_p95"
    _tick(probe, s, seconds=11.0)
    assert aa._state.brake_reason is None


def test_a_failed_write_statement_is_not_left_counted(database) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    before = aa.db_writes_in_flight()
    with database.engine.connect() as connection:
        with pytest.raises(OperationalError):
            connection.execute(text("UPDATE no_such_table SET x = 1"))
    assert aa.db_writes_in_flight() == before
