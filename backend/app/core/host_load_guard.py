"""Host 1-minute loadavg probe for the unified pressure signal.

``/proc/loadavg`` is host-wide inside the production backend containers, so
both replicas read the same value. The reject/resume latch (6.0 / 4.0) lives
in ``adaptive_admission`` together with the memory floor so the two cannot
disagree, and pressure now *suspends* new work instead of rejecting it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

LoadAvgReader = Callable[[], float | None]

_DEFAULT_LOADAVG = Path("/proc/loadavg")
# Tests and operators can replace the reader without patching Path.open.
_reader: LoadAvgReader | None = None


def set_load_avg_reader(reader: LoadAvgReader | None) -> None:
    """Override or clear the loadavg probe (tests only)."""

    global _reader
    _reader = reader


def reset_host_load_guard_state() -> None:
    """Clear the unified pressure latch (tests only)."""

    from app.core.adaptive_admission import reset_adaptive_admission_state

    reset_adaptive_admission_state()


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


def active_reader() -> LoadAvgReader:
    if _reader is not None:
        return _reader
    return read_load_avg_1m


__all__ = [
    "read_load_avg_1m",
    "reset_host_load_guard_state",
    "set_load_avg_reader",
]
