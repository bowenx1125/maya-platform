"""Shared login admission queue.

Password checks are expensive and a classroom sign-in spike used to surface as
an unhandled database error, which the client renders as a capability outage.
Excess sign-ins wait in a table every replica can see. The response code is
``auth_login_queued``, never ``provider_unavailable``.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, delete, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.models import Base
from app.core.sqlutil import begin_immediate

_LOCK_KEY = "maya-login-admission"


class AuthLoginAdmission(Base):
    """One waiting or in-progress sign-in. No username, address, or secret."""

    __tablename__ = "auth_login_admissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "state IN ('waiting', 'admitted')",
            name="ck_auth_login_admissions_state",
        ),
        Index("ix_auth_login_admissions_state_expires", "state", "expires_at"),
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """SQLite returns naive timestamps. Comparisons must use one clock."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _queued(
    position: int,
    retry_after: int,
    ticket: str | None,
    *,
    queue_length: int | None = None,
    limit: int = 1,
    ticket_seconds: int | None = None,
) -> PlatformError:
    """Build the 429 the sign-in page renders as a progress bar.

    ``position`` counts people ahead (0 = next). ``queue_length`` is everyone
    waiting, including this ticket. ``estimated_wait_seconds`` is a rough
    figure: every retry interval roughly ``limit`` sign-ins finish.
    """

    details: dict[str, int | str] = {
        "position": position,
        "retry_after_seconds": retry_after,
        "queue_length": max(queue_length if queue_length is not None else position + 1, 1),
        "estimated_wait_seconds": max(
            retry_after, math.ceil((position + 1) / max(limit, 1)) * retry_after
        ),
    }
    if ticket is not None:
        details["ticket"] = ticket
        if ticket_seconds is not None:
            details["ticket_expires_in_seconds"] = ticket_seconds
    return PlatformError(
        "auth_login_queued",
        "Waiting to enter. Stay on this page; your place in line is kept.",
        429,
        details,
    )


def _expire(db: Session, now: datetime) -> None:
    db.execute(delete(AuthLoginAdmission).where(AuthLoginAdmission.expires_at <= now))


def _active_count(db: Session, now: datetime) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(AuthLoginAdmission)
        .where(
            AuthLoginAdmission.state == "admitted",
            AuthLoginAdmission.expires_at > now,
        )
    )
    return int(count or 0)


def _ahead(db: Session, row: AuthLoginAdmission, now: datetime) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(AuthLoginAdmission)
        .where(
            AuthLoginAdmission.state == "waiting",
            AuthLoginAdmission.expires_at > now,
            AuthLoginAdmission.id != row.id,
            (AuthLoginAdmission.created_at < row.created_at)
            | (
                (AuthLoginAdmission.created_at == row.created_at) & (AuthLoginAdmission.id < row.id)
            ),
        )
    )
    return int(count or 0)


def _waiting_count(db: Session, now: datetime) -> int:
    count = db.scalar(
        select(func.count())
        .select_from(AuthLoginAdmission)
        .where(
            AuthLoginAdmission.state == "waiting",
            AuthLoginAdmission.expires_at > now,
        )
    )
    return int(count or 0)


def _refresh(row: AuthLoginAdmission, now: datetime, settings: Settings) -> None:
    row.expires_at = now + timedelta(seconds=_lease_seconds(row.state, settings))


def _lease_seconds(state: str, settings: Settings) -> int:
    """Admitted slots use the short lease; waiting tickets the longer one."""

    if state == "waiting":
        return settings.auth_login_queue_ticket_seconds
    return settings.auth_login_admission_lease_seconds


def acquire_login_admission(
    db: Session,
    settings: Settings,
    ticket: str | None,
) -> str | None:
    """Reserve a sign-in slot or raise ``auth_login_queued``.

    A returned id is an admitted slot the caller must release. ``None`` means
    admission is disabled and the caller should continue.
    """

    limit = settings.auth_login_admission_limit
    if limit <= 0:
        return None
    begin_immediate(db, lock_key=_LOCK_KEY)
    now = _now()
    _expire(db, now)
    retry_after = settings.auth_login_queue_retry_seconds
    ticket_seconds = settings.auth_login_queue_ticket_seconds

    def queued(row: AuthLoginAdmission, position: int) -> PlatformError:
        return _queued(
            position,
            retry_after,
            row.id,
            queue_length=_waiting_count(db, now),
            limit=limit,
            ticket_seconds=ticket_seconds,
        )

    if ticket:
        row = db.get(AuthLoginAdmission, ticket)
        if row is not None and _as_utc(row.expires_at) > now and row.state == "waiting":
            # First come, first served: a ticket enters only when everyone
            # ahead of it can also fit in the free slots.
            free = limit - _active_count(db, now)
            position = _ahead(db, row, now)
            if position < free:
                row.state = "admitted"
                _refresh(row, now, settings)
                db.commit()
                return row.id
            _refresh(row, now, settings)
            error = queued(row, position)
            db.commit()
            raise error
        if row is not None and _as_utc(row.expires_at) > now and row.state == "admitted":
            _refresh(row, now, settings)
            db.commit()
            return row.id
    # A newcomer may skip the line only when nobody is waiting in it.
    waiting_now = _waiting_count(db, now)
    if waiting_now == 0 and _active_count(db, now) < limit:
        admitted = AuthLoginAdmission(
            id=str(uuid4()),
            state="admitted",
            created_at=now,
            expires_at=now + timedelta(seconds=settings.auth_login_admission_lease_seconds),
        )
        db.add(admitted)
        db.commit()
        return admitted.id
    if waiting_now >= settings.auth_login_queue_max:
        db.commit()
        raise _queued(
            settings.auth_login_queue_max,
            retry_after,
            None,
            queue_length=waiting_now,
            limit=limit,
        )
    waiting = AuthLoginAdmission(
        id=str(uuid4()),
        state="waiting",
        created_at=now,
        expires_at=now + timedelta(seconds=ticket_seconds),
    )
    db.add(waiting)
    db.flush()
    position = _ahead(db, waiting, now)
    error = queued(waiting, position)
    db.commit()
    raise error


def release_login_admission(db: Session, admission_id: str | None) -> None:
    """Free an admitted slot. Waiting tickets are left for the client to retry.

    The caller must not be inside a transaction: SQLite cannot take a second
    writer lock, and this commit must survive a later rollback of the sign-in.
    """

    if not admission_id:
        return
    if db.in_transaction():
        db.rollback()
    begin_immediate(db, lock_key=_LOCK_KEY)
    db.execute(delete(AuthLoginAdmission).where(AuthLoginAdmission.id == admission_id))
    db.commit()


def ticket_from_header(value: str | None) -> str | None:
    """Accept only a UUID ticket. Anything else is ignored, not an error."""

    if value is None:
        return None
    candidate = value.strip()
    try:
        parsed = UUID(candidate)
    except ValueError:
        return None
    return str(parsed)


def login_database_overloaded(exc: BaseException) -> bool:
    """True when sign-in should wait instead of reporting a capability outage."""

    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "database is locked",
            "database is busy",
            "sqlite_busy",
            "too many clients",
            "deadlock detected",
        )
    )
