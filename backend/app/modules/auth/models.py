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
    selected_group_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("groups.id", name="fk_demo_accounts_selected_group", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_demo_account_bindings_user_id", "user_id", unique=True),
        Index("ix_demo_account_bindings_active", "active"),
    )


class LoginIdentityChallenge(Base):
    __tablename__ = "login_identity_challenges"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_fingerprint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_login_identity_challenges_expires_at", "expires_at"),)


class UserCredential(Base):
    """Database-stored credential for a registered or updated account.

    This table is checked before the immutable Demo catalog, so it can hold
    both self-registration credentials and a catalog user's password override.
    ``username`` is duplicated from :class:`~app.core.models.User` so login can
    resolve the credential without loading the public user row first.
    """

    __tablename__ = "user_credentials"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", name="fk_user_credentials_user", ondelete="CASCADE"),
        primary_key=True,
    )
    username: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_user_credentials_username", "username", unique=True),)
