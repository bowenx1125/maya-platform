"""Server-only persistence for stable Demo account ownership.

This table is intentionally separate from the public ``User`` model. It
records which immutable catalog key owns a historical User UUID and the
non-secret material fingerprint used to decide whether sessions must be
revoked. The main window owns the Alembic migration for this table.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class DemoAccountBinding(Base):
    """Durable account-key to User mapping and catalog material state."""

    __tablename__ = "demo_account_bindings"

    account_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", name="fk_demo_account_bindings_user", ondelete="RESTRICT"),
        nullable=False,
    )
    material_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_demo_account_bindings_user_id", "user_id", unique=True),
        Index("ix_demo_account_bindings_active", "active"),
    )
