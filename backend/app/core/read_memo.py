"""Compute a repeated authorization read once per request, never across requests.

Read breakdown (2026-10-18): one formal answer turn ran 812 SELECTs and only
112 were distinct. The assessment context (conversation provenance, the
shared activity) was rebuilt about 12 times and the Team member check ran
about two dozen times, re-reading the same rows in the many short sessions
one turn opens.

``request_read_memo()`` turns memoizing on for one request (a Team turn, on
its own thread). Inside it ``memoized(db, key, compute)`` keeps a successful
result:

- by default on that Session until its transaction ends (ORM rows stay with
  the Session that loaded them);
- with ``across_sessions=True`` (plain values only: a role, a check that
  passed, a frozen dataclass) for the request until its next model call
  (``forget_request_reads``), so a check still runs once before the first
  model call and once again after each one.

Every commit or rollback empties a Session's own memo. A failure
(``not_found`` and the like) is never stored, so it is raised again on the
next call. Nothing outlives the request. Only reads of rows a Team turn never
changes itself (course roles, Team definitions, frozen Chat members,
publications) go through here; a change another request commits meanwhile is
seen at the next model-call boundary or the next turn.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, cast

from sqlalchemy import event
from sqlalchemy.orm import Session

_REQUEST: ContextVar[dict[tuple[Hashable, ...], Any] | None] = ContextVar(
    "maya_request_read_memo", default=None
)
_INFO_KEY = "maya_request_read_memo"
_TX_KEY = "maya_transaction_role_memo"
_MISS = object()


@contextmanager
def request_read_memo() -> Iterator[None]:
    """Memoize ``memoized`` reads for the rest of this request (this thread)."""

    token = _REQUEST.set({})
    try:
        yield
    finally:
        _REQUEST.reset(token)


def forget_request_reads() -> None:
    """Drop the request-wide copies (after a model call: time has passed)."""

    store = _REQUEST.get()
    if store is not None:
        store.clear()


def memoized[T](
    db: Session,
    key: tuple[Hashable, ...],
    compute: Callable[[], T],
    *,
    across_sessions: bool = False,
    in_transaction: bool = False,
) -> T:
    """``compute()`` once per request (or per transaction of ``db``).

    ``in_transaction=True`` also keeps the value on ``db`` until its
    transaction ends when no request memo is active. Only for role reads
    (course role, group role): production 2026-10-26 ran the same course
    role query up to 30 times in one request. Long-lived sockets and streams
    open a short session per check, so a revoked role is still seen.
    """

    request = _REQUEST.get()
    if request is None and not in_transaction:
        return compute()
    store: dict[tuple[Hashable, ...], Any]
    if request is None:
        # Dropped at the first write of the transaction too, so a role the
        # request itself changes is read again.
        store = db.info.setdefault(_TX_KEY, {})
    elif across_sessions:
        store = request
    else:
        store = db.info.setdefault(_INFO_KEY, {})
    hit = store.get(key, _MISS)
    if hit is not _MISS:
        return cast(T, hit)
    value = compute()
    store[key] = value
    return value


def transaction_memoized[T](db: Session, key: tuple[Hashable, ...], compute: Callable[[], T]) -> T:
    """``compute()`` once until ``db``'s transaction ends or first writes.

    For reads a request repeats on rows it does not change before reading
    again (an Agent version's enabled documents, read once per permission
    check). Any flush or DML in the transaction drops every such value.
    """

    store = db.info.setdefault(_TX_KEY, {})
    hit = store.get(key, _MISS)
    if hit is not _MISS:
        return cast(T, hit)
    value = compute()
    store[key] = value
    return value


def _forget(session: Session, *_args: Any) -> None:
    session.info.pop(_INFO_KEY, None)
    session.info.pop(_TX_KEY, None)


def _forget_on_write(session: Session, *_args: Any) -> None:
    if session.new or session.dirty or session.deleted:
        session.info.pop(_TX_KEY, None)


def _forget_on_dml(state: Any) -> None:
    if state.is_insert or state.is_update or state.is_delete:
        state.session.info.pop(_TX_KEY, None)


# Any end of a transaction (or a savepoint rolled back) drops what was read in it.
event.listen(Session, "after_commit", _forget)
event.listen(Session, "after_rollback", _forget)
event.listen(Session, "after_soft_rollback", _forget)
event.listen(Session, "before_flush", _forget_on_write)
event.listen(Session, "do_orm_execute", _forget_on_dml)


__all__ = ["forget_request_reads", "memoized", "request_read_memo", "transaction_memoized"]
