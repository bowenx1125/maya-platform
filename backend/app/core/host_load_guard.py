"""Reject new heavy work when the host 1-minute load average is too high.

MayaLoad's n=40 create spike pushed 2-vCPU load past 13 before LLM / write
admission returned busy. This guard reads ``/proc/loadavg`` (host load is
visible inside production backend containers) and refuses *new* LLM, write,
and create admissions when the 1-minute average is at or above a reject
threshold. Work already past the entry point keeps running.

Hysteresis mirrors memory_guard: once pressure latches, new work stays
rejected until load falls to a lower resume threshold (default reject ≥ 6.0,
resume ≤ 4.0).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.errors import PlatformError

LoadAvgReader = Callable[[], float | None]

_DEFAULT_LOADAVG = Path("/proc/loadavg")
# Tests and operators can replace the reader without patching Path.open.
_reader: LoadAvgReader | None = None
# Process-local sticky flag: once load climbs to the reject floor, keep
# refusing until it drops to the resume threshold.
_under_pressure: bool = False


def set_load_avg_reader(reader: LoadAvgReader | None) -> None:
    """Override or clear the loadavg probe (tests only)."""

    global _reader
    _reader = reader


def reset_host_load_guard_state() -> None:
    """Clear the sticky pressure latch (tests only)."""

    global _under_pressure
    _under_pressure = False


def read_load_avg_1m(loadavg_path: Path | str = _DEFAULT_LOADAVG) -> float | None:
    """Return the 1-minute load average, or None when the file is unreadable."""

    try:
        text = Path(loadavg_path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    first = text.split()[0]
    try:
        value = float(first)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def _active_reader() -> LoadAvgReader:
    if _reader is not None:
        return _reader
    return read_load_avg_1m


def host_load_pressure_error(
    *,
    load_1m: float,
    reject_threshold: float,
    retry_after_seconds: int,
) -> PlatformError:
    """Build the 503 clients should treat as a short, retryable pause."""

    return PlatformError(
        "host_load_pressure",
        "The server is under high load. Wait a moment and try again.",
        503,
        {
            "retryable": True,
            "retry_after_seconds": max(1, retry_after_seconds),
            "load_1m": load_1m,
            "load_reject_threshold": reject_threshold,
        },
    )


def ensure_host_load_ok(settings: Settings | None = None) -> None:
    """Raise ``host_load_pressure`` when host 1m load is under sticky pressure.

    * Not under pressure: reject (and latch) when ``load >= reject``.
    * Under pressure: keep rejecting until ``load <= resume``, then clear.
    * When ``resume >= reject``, hysteresis is off (resume equals reject).
    * Reject threshold ``<= 0`` disables the guard entirely.
    * A missing or unreadable ``/proc/loadavg`` fails open so a broken probe
      cannot take every heavy path offline.
    """

    global _under_pressure

    runtime = settings if settings is not None else get_settings()
    reject = float(runtime.host_load_reject_threshold)
    if reject <= 0:
        return
    resume = float(runtime.host_load_resume_threshold)
    if resume >= reject:
        resume = reject
    load = _active_reader()()
    if load is None:
        return

    if not _under_pressure:
        if load >= reject:
            _under_pressure = True
            raise host_load_pressure_error(
                load_1m=load,
                reject_threshold=reject,
                retry_after_seconds=int(runtime.host_load_retry_seconds),
            )
        return

    if load <= resume:
        _under_pressure = False
        return

    raise host_load_pressure_error(
        load_1m=load,
        reject_threshold=reject,
        retry_after_seconds=int(runtime.host_load_retry_seconds),
    )


__all__ = [
    "ensure_host_load_ok",
    "host_load_pressure_error",
    "read_load_avg_1m",
    "reset_host_load_guard_state",
    "set_load_avg_reader",
]
