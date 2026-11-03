"""A high load average counts only while the CPU is busy too (2026-11-03).

Load average also counts tasks waiting on disk and other containers on the
host, and it trails a minute behind. With 60 students polling, load sat at
4.7-5.9 while the CPU still had room, and the latch held the whole class.
The danger latch, the soft-load shrink and the hold band now need host CPU
busy (smoothed over ~5 s) at or above ADAPTIVE_ADMISSION_LOAD_CPU_CONFIRM_RATIO.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.core import adaptive_admission as aa
from app.core.config import Settings


class _Probe:
    def __init__(self) -> None:
        self.now = 0.0
        self.load = 9.0
        self.cpu: float | None = 0.3


@pytest.fixture()
def probe() -> Iterator[_Probe]:
    p = _Probe()
    aa.reset_adaptive_admission_state()
    aa.set_signal_readers(
        load=lambda: p.load, mem=lambda: 4000.0, clock=lambda: p.now, cpu=lambda: p.cpu
    )
    yield p
    aa.set_signal_readers()
    aa.reset_adaptive_admission_state()


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "adaptive_admission_wait_seconds": 1,
        "host_load_reject_threshold": 6.0,
        "host_load_resume_threshold": 4.0,
        # The brake is a separate signal; keep it out of these scenarios.
        "adaptive_admission_brake_cpu_ratio": 0,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _run(probe: _Probe, s: Settings, seconds: int) -> None:
    for _ in range(seconds):
        probe.now += 1.0
        aa.adaptive_admission_snapshot(s)


def test_default_confirm_ratio() -> None:
    assert Settings().adaptive_admission_load_cpu_confirm_ratio == 0.8  # type: ignore[call-arg]


def test_high_load_with_a_cool_cpu_keeps_admitting(probe: _Probe) -> None:
    s = _settings()
    _run(probe, s, 10)
    assert not aa._state.danger
    assert aa._state.shrink_counts["load"] == 0
    assert aa._state.budget > float(s.adaptive_admission_initial_units)


def test_high_load_with_a_busy_cpu_trips_the_latch(probe: _Probe) -> None:
    probe.cpu = 1.0
    s = _settings()
    _run(probe, s, 3)
    assert aa._state.danger
    assert aa._state.danger_reason == "load"


def test_the_latch_releases_once_the_cpu_cools(probe: _Probe) -> None:
    probe.cpu = 1.0
    s = _settings(adaptive_admission_danger_max_hold_seconds=0)
    _run(probe, s, 3)
    assert aa._state.danger
    # Load is still 9 (a one-minute average), but the work is done.
    probe.cpu = 0.1
    _run(probe, s, 15)
    assert not aa._state.danger
    assert aa._state.danger_releases == 1


def test_one_busy_tick_does_not_confirm(probe: _Probe) -> None:
    s = _settings()
    _run(probe, s, 5)
    probe.cpu = 1.0
    _run(probe, s, 1)
    assert not aa._state.danger


@pytest.mark.parametrize("case", ["confirm_off", "cpu_unreadable"])
def test_load_alone_still_trips_without_a_cpu_reading(probe: _Probe, case: str) -> None:
    overrides: dict[str, object] = {}
    if case == "confirm_off":
        overrides["adaptive_admission_load_cpu_confirm_ratio"] = 0
    else:
        probe.cpu = None
    s = _settings(**overrides)
    _run(probe, s, 2)
    assert aa._state.danger
    snapshot = aa.adaptive_admission_snapshot(s)
    assert "cpu_busy_avg" in snapshot["brake"]  # type: ignore[operator]
