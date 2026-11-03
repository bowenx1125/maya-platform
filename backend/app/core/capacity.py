"""How big this server is, so CPU-bound capacity defaults grow with it.

The admission thresholds and concurrency caps in config.py were measured on
the 2-vCPU production host (load 6 is the danger line there; 8 model calls
and 8 chat turns per backend were the best #140 sweep). On a bigger host the
same numbers would leave most of it idle, so the CPU-bound ones are
multiplied by ``cores / CAPACITY_BASELINE_CPUS``. The multiplier never goes
below 1: a host no smaller than the baseline keeps today's numbers exactly.

Memory floors are not scaled: the operating system needs the same headroom
on any size of machine, and a bigger one simply sits further above them.
``CAPACITY_SCALE`` pins the multiplier (1 turns scaling off).
"""

from __future__ import annotations

import os

BASELINE_CPUS = 2

# Load averages, compared with the host's 1-minute load (host-wide).
SCALED_LOADS: tuple[str, ...] = (
    "host_load_reject_threshold",
    "host_load_resume_threshold",
    "adaptive_admission_soft_load",
    "adaptive_admission_hold_load",
)
# Per-process concurrency caps and admission budgets. 0 still means "off".
SCALED_CAPS: tuple[str, ...] = (
    "llm_admission_limit",
    "write_guard_limit",
    "create_admission_limit",
    "auth_hash_concurrency",
    "debate_interaction_gate_limit",
    "adaptive_admission_max_in_flight",
    "adaptive_admission_max_units",
    "adaptive_admission_initial_units",
)


def available_cpus() -> int:
    """CPUs this process may run on (the host's, since load is host-wide)."""

    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):  # pragma: no cover - non-Linux
        return max(1, os.cpu_count() or 1)


def capacity_scale(
    *, baseline_cpus: int = BASELINE_CPUS, override: float | None = None, cpus: int | None = None
) -> float:
    """The multiplier for CPU-bound defaults on this host."""

    if override is not None:
        return float(override)
    host = available_cpus() if cpus is None else cpus
    return max(1.0, host / max(1, baseline_cpus))


def scaled_values(values: dict[str, float | int], scale: float) -> dict[str, float | int]:
    """``values`` (loads and caps) multiplied by ``scale``; caps stay integers."""

    if scale == 1.0:
        return dict(values)
    out: dict[str, float | int] = {}
    for name, value in values.items():
        if name in SCALED_LOADS:
            out[name] = round(float(value) * scale, 2)
        elif name in SCALED_CAPS:
            out[name] = int(round(int(value) * scale))
        else:
            out[name] = value
    return out
