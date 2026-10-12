"""Create immutable Teams, course publication and invoke-only grants."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040_teams_publication_grants"
down_revision: str | Sequence[str] | None = "0039_knowledge_generation_materialization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # Keep all new DDL and Alembic's head update inside one real SQLite
        # transaction so a failed migration is exactly retryable.
        bind.exec_driver_sql("BEGIN IMMEDIATE")

    op.create_table(
        "teams",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("group_id", sa.String(length=36), nullable=True),
        sa.Column("ownership_scope", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("metadata_revision", sa.Integer(), nullable=False),
        sa.Column("authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("current_version_seq", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ownership_scope IN ('personal', 'group')", name="ck_teams_ownership_scope"
        ),
        sa.CheckConstraint("visibility IN ('private', 'public')", name="ck_teams_visibility"),
        sa.CheckConstraint(
            "((ownership_scope = 'personal' AND group_id IS NULL) OR "
            "(ownership_scope = 'group' AND group_id IS NOT NULL))",
            name="ck_teams_scope_group",
        ),
        sa.CheckConstraint("length(trim(display_name)) > 0", name="ck_teams_display_name"),
        sa.CheckConstraint(
            "metadata_revision >= 0 AND authorization_epoch >= 0 AND current_version_seq >= 1",
            name="ck_teams_counters",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["group_id", "course_id"],
            ["groups.id", "groups.course_id"],
            name="fk_teams_group_course",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_teams_course_owner", "teams", ["course_id", "owner_user_id", "deleted_at"])
    op.create_index("ix_teams_group_visibility", "teams", ["group_id", "visibility", "deleted_at"])

    op.create_table(
        "team_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("team_id", sa.String(length=36), nullable=False),
        sa.Column("version_seq", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version_seq >= 1", name="ck_team_versions_seq"),
        sa.CheckConstraint(
            "visibility IN ('private', 'public')", name="ck_team_versions_visibility"
        ),
        sa.CheckConstraint("authorization_epoch >= 0", name="ck_team_versions_epoch"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "version_seq", name="uq_team_versions_seq"),
        sa.UniqueConstraint("team_id", "id", name="uq_team_versions_team_id"),
    )
    op.create_index("ix_team_versions_team_created", "team_versions", ["team_id", "version_seq"])

    op.create_table(
        "team_version_members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("team_version_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("agent_version_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_leader", sa.Boolean(), nullable=False),
        sa.Column("display_name", sa.String(length=240), nullable=False),
        sa.Column("avatar_config_json", sa.Text(), nullable=False),
        sa.Column(
            "own_knowledge_set_snapshots_json", sa.Text(), nullable=False, server_default="[]"
        ),
        sa.Column("raw_source_fences_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_team_version_members_position"),
        sa.ForeignKeyConstraint(["team_version_id"], ["team_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_version_id", "agent_id", name="uq_team_version_member_agent"),
        sa.UniqueConstraint("team_version_id", "position", name="uq_team_version_member_position"),
        sa.UniqueConstraint("team_version_id", "id", name="uq_team_version_member_version_id"),
    )
    op.create_index(
        "ix_team_version_members_version_order",
        "team_version_members",
        ["team_version_id", "position"],
    )

    op.create_table(
        "team_version_sets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("team_version_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_set_id", sa.String(length=36), nullable=False),
        sa.Column("authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_team_version_sets_position"),
        sa.CheckConstraint("authorization_epoch >= 0", name="ck_team_version_sets_epoch"),
        sa.ForeignKeyConstraint(["team_version_id"], ["team_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["knowledge_set_id"], ["knowledge_sets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_version_id", "knowledge_set_id", name="uq_team_version_set"),
        sa.UniqueConstraint("team_version_id", "position", name="uq_team_version_set_position"),
    )
    op.create_index(
        "ix_team_version_sets_version_order", "team_version_sets", ["team_version_id", "position"]
    )

    op.create_table(
        "course_team_publications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("team_id", sa.String(length=36), nullable=False),
        sa.Column("team_version_id", sa.String(length=36), nullable=False),
        sa.Column("publisher_user_id", sa.String(length=36), nullable=False),
        sa.Column("authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="published"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("authorization_epoch >= 0", name="ck_course_team_publication_epoch"),
        sa.CheckConstraint(
            "state IN ('published', 'retained', 'revoked')",
            name="ck_course_team_publication_state",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["team_version_id"], ["team_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["publisher_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_version_id", name="uq_course_team_publication_version"),
    )
    op.create_index(
        "ix_course_team_publications_directory",
        "course_team_publications",
        ["course_id", "state", "published_at"],
    )
    op.create_index(
        "uq_course_team_publications_active_team",
        "course_team_publications",
        ["team_id"],
        unique=True,
        sqlite_where=sa.text("state = 'published'"),
        postgresql_where=sa.text("state = 'published'"),
    )

    op.create_table(
        "team_member_invoke_grants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("publication_id", sa.String(length=36), nullable=False),
        sa.Column("team_version_id", sa.String(length=36), nullable=False),
        sa.Column("team_member_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("agent_version_id", sa.String(length=36), nullable=False),
        sa.Column("authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("authorization_epoch >= 0", name="ck_team_member_invoke_grant_epoch"),
        sa.ForeignKeyConstraint(
            ["publication_id"], ["course_team_publications.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["team_version_id"], ["team_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["team_member_id"], ["team_version_members.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "publication_id", "team_member_id", name="uq_team_publication_member_grant"
        ),
    )
    op.create_index(
        "ix_team_member_invoke_grants_version",
        "team_member_invoke_grants",
        ["team_version_id", "agent_version_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    for table_name in (
        "team_member_invoke_grants",
        "course_team_publications",
        "team_version_sets",
        "team_version_members",
        "team_versions",
        "teams",
    ):
        if bind.execute(sa.text(f"SELECT 1 FROM {table_name} LIMIT 1")).first() is not None:
            raise RuntimeError("Team history exists; refusing to discard Team data.")
    op.drop_index("ix_team_member_invoke_grants_version", table_name="team_member_invoke_grants")
    op.drop_table("team_member_invoke_grants")
    op.drop_index("uq_course_team_publications_active_team", table_name="course_team_publications")
    op.drop_index("ix_course_team_publications_directory", table_name="course_team_publications")
    op.drop_table("course_team_publications")
    op.drop_index("ix_team_version_sets_version_order", table_name="team_version_sets")
    op.drop_table("team_version_sets")
    op.drop_index("ix_team_version_members_version_order", table_name="team_version_members")
    op.drop_table("team_version_members")
    op.drop_index("ix_team_versions_team_created", table_name="team_versions")
    op.drop_table("team_versions")
    op.drop_index("ix_teams_group_visibility", table_name="teams")
    op.drop_index("ix_teams_course_owner", table_name="teams")
    op.drop_table("teams")
