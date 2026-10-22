"""Helpers for history links that turn NULL when their source is hard-deleted.

Since real deletion (2026-10-20), history rows keep a nullable link to the
Agent, version, document or voice they came from. Live code paths that need
the source call :func:`live_link`; a deleted source is a clean 409 rather than
a crash deep inside a runtime path.
"""

from __future__ import annotations

from app.core.errors import PlatformError, conflict


def live_link(value: str | None, what: str = "source") -> str:
    if value is None:
        raise source_deleted(what)
    return value


def source_deleted(what: str = "source") -> PlatformError:
    return conflict("source_deleted", f"The {what} this depends on was deleted.")
