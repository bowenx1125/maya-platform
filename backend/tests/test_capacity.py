"""CPU-bound capacity defaults grow with a bigger server, never shrink."""

from __future__ import annotations

from typing import Any

import pytest
from app.core.capacity import SCALED_CAPS, SCALED_LOADS, capacity_scale
from app.core.config import Settings


def _settings(**values: Any) -> Settings:
    return Settings(
        maya_env="test",
        session_secret="x" * 32,
        database_url="postgresql+psycopg://user:pass@127.0.0.1:5432/capacity",
        **values,
    )


@pytest.mark.parametrize(("cpus", "scale"), [(1, 1.0), (2, 1.0), (4, 2.0), (8, 4.0), (16, 8.0)])
def test_the_multiplier_follows_cores_over_the_baseline(cpus: int, scale: float) -> None:
    assert capacity_scale(cpus=cpus) == scale


def test_a_pinned_scale_wins_and_the_baseline_is_configurable() -> None:
    assert capacity_scale(cpus=16, override=1.0) == 1.0
    assert capacity_scale(cpus=16, baseline_cpus=8) == 2.0


def test_today_s_host_keeps_the_measured_numbers() -> None:
    settings = _settings(capacity_scale=1.0)
    assert settings.host_load_reject_threshold == 6.0
    assert settings.host_load_resume_threshold == 4.0
    assert settings.llm_admission_limit == 8
    assert settings.write_guard_limit == 8
    assert settings.adaptive_admission_max_in_flight == 48


def test_a_four_times_bigger_host_scales_loads_and_caps_but_not_memory_floors() -> None:
    base = _settings(capacity_scale=1.0)
    big = _settings(capacity_scale=4.0)
    for name in SCALED_LOADS:
        assert getattr(big, name) == pytest.approx(getattr(base, name) * 4), name
    for name in SCALED_CAPS:
        assert getattr(big, name) == getattr(base, name) * 4, name
        assert isinstance(getattr(big, name), int), name
    assert big.memory_guard_min_available_mb == base.memory_guard_min_available_mb
    assert big.adaptive_admission_soft_mem_mb == base.adaptive_admission_soft_mem_mb
    # Queue sizes and waits are about people waiting, not CPUs.
    assert big.llm_admission_queue_max == base.llm_admission_queue_max
    assert big.llm_admission_wait_seconds == base.llm_admission_wait_seconds


def test_a_disabled_cap_stays_disabled_and_copies_are_not_scaled_again() -> None:
    big = _settings(capacity_scale=2.0, write_guard_limit=0, llm_admission_limit=5)
    assert big.write_guard_limit == 0
    assert big.llm_admission_limit == 10
    copied = big.model_copy(update={"llm_provider": "mock"})
    assert copied.llm_admission_limit == 10
    assert copied.host_load_reject_threshold == 12.0


def test_an_empty_capacity_scale_from_compose_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAPACITY_SCALE", "")
    settings = _settings()
    assert settings.capacity_scale is None
    assert settings.llm_admission_limit >= 8
