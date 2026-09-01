"""Application log configuration shared by startup and the migration step."""

from __future__ import annotations

import logging
import sys


def configure_application_logging() -> None:
    """Give application loggers a stdout handler exactly once.

    Uvicorn configures only its own loggers, so the root logger has no handler
    and every application warning is silently dropped inside the container.
    Safe failure codes then leave no trace at all, which is what made a real
    provider turn undiagnosable.

    This is also called again after Alembic runs: ``fileConfig`` rebuilds the
    root logger from ``alembic.ini``, dropping this handler and forcing the
    root level back to ``WARN``. Nothing here changes what may be logged; the
    call sites remain responsible for keeping provider and student data out.
    """

    root = logging.getLogger()
    if not any(getattr(handler, "_maya_stdout", False) for handler in root.handlers):
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
        handler._maya_stdout = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
