"""Persistent Team definitions, immutable versions, and course publication grants."""

from __future__ import annotations

from datetime import datetime

from app.core.models import Base
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    course_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ownership_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    metadata_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_version_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "ownership_scope IN ('personal', 'group')", name="ck_teams_ownership_scope"
        ),
        CheckConstraint("visibility IN ('private', 'public')", name="ck_teams_visibility"),
        CheckConstraint(
            "((ownership_scope = 'personal' AND group_id IS NULL) OR "
            "(ownership_scope = 'group' AND group_id IS NOT NULL))",
            name="ck_teams_scope_group",
        ),
        CheckConstraint("length(trim(display_name)) > 0", name="ck_teams_display_name"),
        CheckConstraint(
            "metadata_revision >= 0 AND authorization_epoch >= 0 AND current_version_seq >= 1",
            name="ck_teams_counters",
        ),
        ForeignKeyConstraint(
            ["group_id", "course_id"],
            ["groups.id", "groups.course_id"],
            name="fk_teams_group_course",
            ondelete="CASCADE",
        ),
        Index("ix_teams_course_owner", "course_id", "owner_user_id", "deleted_at"),
        Index("ix_teams_group_visibility", "group_id", "visibility", "deleted_at"),
    )


class TeamVersion(Base):
    __tablename__ = "team_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    version_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("version_seq >= 1", name="ck_team_versions_seq"),
        CheckConstraint("visibility IN ('private', 'public')", name="ck_team_versions_visibility"),
        CheckConstraint("authorization_epoch >= 0", name="ck_team_versions_epoch"),
        UniqueConstraint("team_id", "version_seq", name="uq_team_versions_seq"),
        UniqueConstraint("team_id", "id", name="uq_team_versions_team_id"),
        Index("ix_team_versions_team_created", "team_id", "version_seq"),
    )


class TeamVersionMember(Base):
    __tablename__ = "team_version_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    team_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("team_versions.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    agent_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_leader: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    avatar_config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    own_knowledge_set_snapshots_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    raw_source_fences_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_team_version_members_position"),
        UniqueConstraint("team_version_id", "agent_id", name="uq_team_version_member_agent"),
        UniqueConstraint("team_version_id", "position", name="uq_team_version_member_position"),
        UniqueConstraint("team_version_id", "id", name="uq_team_version_member_version_id"),
        Index("ix_team_version_members_version_order", "team_version_id", "position"),
    )


class TeamVersionSet(Base):
    __tablename__ = "team_version_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    team_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("team_versions.id", ondelete="RESTRICT"), nullable=False
    )
    knowledge_set_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_sets.id", ondelete="SET NULL"), nullable=True
    )
    authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_team_version_sets_position"),
        CheckConstraint("authorization_epoch >= 0", name="ck_team_version_sets_epoch"),
        UniqueConstraint("team_version_id", "knowledge_set_id", name="uq_team_version_set"),
        UniqueConstraint("team_version_id", "position", name="uq_team_version_set_position"),
        Index("ix_team_version_sets_version_order", "team_version_id", "position"),
    )


class CourseTeamPublication(Base):
    __tablename__ = "course_team_publications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )
    team_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    team_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("team_versions.id", ondelete="RESTRICT"), nullable=False
    )
    publisher_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="published")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("authorization_epoch >= 0", name="ck_course_team_publication_epoch"),
        CheckConstraint(
            "state IN ('published', 'retained', 'revoked')",
            name="ck_course_team_publication_state",
        ),
        UniqueConstraint("team_version_id", name="uq_course_team_publication_version"),
        Index("ix_course_team_publications_directory", "course_id", "state", "published_at"),
        Index(
            "uq_course_team_publications_active_team",
            "team_id",
            unique=True,
            sqlite_where=(state == "published"),
            postgresql_where=(state == "published"),
        ),
    )


class TeamMemberInvokeGrant(Base):
    __tablename__ = "team_member_invoke_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publication_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("course_team_publications.id", ondelete="RESTRICT"), nullable=False
    )
    team_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("team_versions.id", ondelete="RESTRICT"), nullable=False
    )
    team_member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("team_version_members.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    agent_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True
    )
    authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("authorization_epoch >= 0", name="ck_team_member_invoke_grant_epoch"),
        UniqueConstraint(
            "publication_id", "team_member_id", name="uq_team_publication_member_grant"
        ),
        Index("ix_team_member_invoke_grants_version", "team_version_id", "agent_version_id"),
    )
