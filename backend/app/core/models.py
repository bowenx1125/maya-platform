"""Minimal Wave 0 SQLAlchemy model set.

Only identity, session, course and group rows are present here.  Later domain
tables belong to later waves and are intentionally absent from this baseline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative metadata for the Wave 0 migration."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    sessions: Mapped[list[SessionRecord]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    course_memberships: Mapped[list[CourseMember]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    group_memberships: Mapped[list[GroupMember]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("ix_users_status", "status"),)


class SessionRecord(Base):
    __tablename__ = "sessions"

    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")

    __table_args__ = (
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_expires_at", "expires_at"),
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    # Debate is a later-wave table; this pointer intentionally has no FK in
    # the minimal migration and is managed by the later domain migration.
    current_audio_debate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    memberships: Mapped[list[CourseMember]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
    )
    groups: Mapped[list[Group]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("ix_courses_code", "code", unique=True),)


class CourseMember(Base):
    __tablename__ = "course_members"

    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    course: Mapped[Course] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="course_memberships")

    __table_args__ = (
        CheckConstraint("role IN ('teacher', 'student')", name="ck_course_members_role"),
        Index("ix_course_members_user_id", "user_id"),
    )


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    course: Mapped[Course] = relationship(back_populates="groups")
    memberships: Mapped[list[GroupMember]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("course_id", "name", name="uq_groups_course_name"),
        Index("ix_groups_course_id", "course_id"),
    )


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    group: Mapped[Group] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="group_memberships")

    __table_args__ = (
        CheckConstraint("role IN ('leader', 'admin', 'member')", name="ck_group_members_role"),
        Index("ix_group_members_user_id", "user_id"),
    )


# Keep a small helper available to fingerprint/serialization code without
# exposing ORM internals in route modules.
def model_dict(instance: Any, *fields: str) -> dict[str, Any]:
    return {field: getattr(instance, field) for field in fields}
