"""Login admission table (retained) and DB-overload detection.

Sign-in now waits in the unified pressure queue (``adaptive_admission``,
class ``login``). The ``auth_login_admissions`` table stays mapped only so
existing migrations and the SQLite importer keep a stable schema; nothing
admits through it any more.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base

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


def login_database_overloaded(exc: BaseException) -> bool:
    """True when sign-in should wait instead of reporting a capability outage."""

    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "too many clients",
            "deadlock detected",
        )
    )
