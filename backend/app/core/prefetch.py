"""Rows a list request loaded in one batch, answered from memory per item.

Production (2026-10-26): the course pages ran one or more queries per Agent
(published-agents 554 statements, chat-agents 343). A list route now loads
what its per-item helpers read (enabled documents, snapshot sources, edit
audits, names, voices) with a few ``IN (...)`` queries and stores the result
here; each helper asks ``prefetched`` first and falls back to its own query
for any key the batch did not cover. Values are exactly what the helper's
query would return, so the answer and its permission rules do not change.

The store lives on the Session and is dropped at every commit or rollback,
like ``read_memo``: nothing outlives the transaction that read it.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping
from typing import Any, cast

from sqlalchemy import event
from sqlalchemy.orm import Session

_INFO_KEY = "maya_prefetch"
_MISS = object()


def store(db: Session, kind: str, values: Mapping[Any, Any]) -> None:
    """Remember a batch: ``values`` must hold every key the batch covered."""

    db.info.setdefault(_INFO_KEY, {}).setdefault(kind, {}).update(values)


def prefetched[T](db: Session, kind: str, key: Hashable, compute: Callable[[], T]) -> T:
    """The batched value for ``key`` if one was stored, else ``compute()``."""

    batch = db.info.get(_INFO_KEY, {}).get(kind)
    if batch is not None:
        hit = batch.get(key, _MISS)
        if hit is not _MISS:
            return cast(T, hit)
    return compute()


def _forget(session: Session, *_args: Any) -> None:
    session.info.pop(_INFO_KEY, None)


event.listen(Session, "after_commit", _forget)
event.listen(Session, "after_rollback", _forget)
event.listen(Session, "after_soft_rollback", _forget)


__all__ = ["prefetched", "store"]
