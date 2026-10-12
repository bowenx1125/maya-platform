"""Add append-only learning facts and immutable Assessment revisions."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043_learning_evidence"
down_revision: str | Sequence[str] | None = "0042_team_turn_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("BEGIN IMMEDIATE")

    op.create_table(
        "learning_records",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("team_id", sa.String(36), nullable=True),
        sa.Column("team_version_id", sa.String(36), nullable=True),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("chat_visibility", sa.String(16), nullable=False),
        sa.Column("activity_id", sa.String(36), nullable=True),
        sa.Column("record_kind", sa.String(16), nullable=False),
        sa.Column("client_event_id", sa.String(36), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "record_kind IN ('answer', 'skip', 'hint', 'evidence')",
            name="ck_learning_records_kind",
        ),
        sa.CheckConstraint(
            "origin IN ('single_agent', 'custom_team', 'published_course_team')",
            name="ck_learning_records_origin",
        ),
        sa.CheckConstraint(
            "chat_visibility IN ('private', 'public')",
            name="ck_learning_records_chat_visibility",
        ),
        sa.CheckConstraint(
            "((origin = 'single_agent' AND team_id IS NULL AND team_version_id IS NULL) OR "
            "(origin IN ('custom_team', 'published_course_team') AND team_id IS NOT NULL "
            "AND team_version_id IS NOT NULL))",
            name="ck_learning_records_team_origin",
        ),
        sa.CheckConstraint("length(payload_hash) = 64", name="ck_learning_records_payload_hash"),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_learning_records_actor"
        ),
        sa.ForeignKeyConstraint(
            ["course_id"], ["courses.id"], ondelete="RESTRICT", name="fk_learning_records_course"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="RESTRICT",
            name="fk_learning_records_conversation",
        ),
        sa.ForeignKeyConstraint(
            ["team_id", "team_version_id"],
            ["team_versions.team_id", "team_versions.id"],
            ondelete="RESTRICT",
            name="fk_learning_records_team_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_user_id",
            "conversation_id",
            "client_event_id",
            name="uq_learning_records_event_idempotency",
        ),
    )
    op.create_index(
        "ix_learning_records_actor_conversation",
        "learning_records",
        ["actor_user_id", "conversation_id"],
    )
    op.create_index(
        "ix_learning_records_course_origin_privacy",
        "learning_records",
        ["course_id", "origin", "chat_visibility"],
    )
    op.create_index(
        "ix_learning_records_team_version",
        "learning_records",
        ["team_id", "team_version_id"],
    )

    op.create_table(
        "learning_assessments",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("created_conversation_id", sa.String(36), nullable=False),
        sa.Column("current_revision_seq", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("current_revision_seq >= 1", name="ck_learning_assessments_revision"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessments_owner",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessments_course",
        ),
        sa.ForeignKeyConstraint(
            ["created_conversation_id"],
            ["agent_conversations.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessments_conversation",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_learning_assessments_owner_course",
        "learning_assessments",
        ["owner_user_id", "course_id"],
    )

    op.create_table(
        "learning_assessment_revisions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("revision_seq", sa.Integer(), nullable=False),
        sa.Column("previous_revision_id", sa.String(36), nullable=True),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("team_id", sa.String(36), nullable=True),
        sa.Column("team_version_id", sa.String(36), nullable=True),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("chat_visibility", sa.String(16), nullable=False),
        sa.Column("activity_id", sa.String(36), nullable=True),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision_seq >= 1", name="ck_learning_assessment_revision_seq"),
        sa.CheckConstraint(
            "origin IN ('single_agent', 'custom_team', 'published_course_team')",
            name="ck_learning_assessment_revision_origin",
        ),
        sa.CheckConstraint(
            "chat_visibility IN ('private', 'public')",
            name="ck_learning_assessment_revision_chat_visibility",
        ),
        sa.CheckConstraint(
            "((origin = 'single_agent' AND team_id IS NULL AND team_version_id IS NULL) OR "
            "(origin IN ('custom_team', 'published_course_team') AND team_id IS NOT NULL "
            "AND team_version_id IS NOT NULL))",
            name="ck_learning_assessment_revision_team_origin",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64", name="ck_learning_assessment_revision_hash"
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["learning_assessments.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_revision_head",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id", "previous_revision_id"],
            ["learning_assessment_revisions.assessment_id", "learning_assessment_revisions.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_revision_previous",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_revision_actor",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_revision_course",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_revision_conversation",
        ),
        sa.ForeignKeyConstraint(
            ["team_id", "team_version_id"],
            ["team_versions.team_id", "team_versions.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_revision_team_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assessment_id", "revision_seq", name="uq_learning_assessment_revision_seq"
        ),
        sa.UniqueConstraint(
            "assessment_id", "id", name="uq_learning_assessment_revision_scoped_id"
        ),
    )
    op.create_index(
        "ix_learning_assessment_revision_history",
        "learning_assessment_revisions",
        ["assessment_id", "revision_seq"],
    )

    op.create_table(
        "learning_assessment_mutations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("client_event_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(8), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "operation IN ('create', 'edit')", name="ck_learning_assessment_mutation_op"
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64", name="ck_learning_assessment_mutation_hash"
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_mutation_actor",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_mutation_conversation",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["learning_assessments.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_mutation_assessment",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id", "revision_id"],
            ["learning_assessment_revisions.assessment_id", "learning_assessment_revisions.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_mutation_revision",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_user_id",
            "conversation_id",
            "client_event_id",
            name="uq_learning_assessment_mutation_idempotency",
        ),
    )
    op.create_index(
        "ix_learning_assessment_mutation_assessment",
        "learning_assessment_mutations",
        ["assessment_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError("Learning evidence downgrade requires the SQLite application database.")
    # Keep the row guard, destructive DDL and Alembic's head update in one
    # transaction. A failed head write must restore all four tables.
    bind.exec_driver_sql("BEGIN IMMEDIATE")
    for table in (
        "learning_records",
        "learning_assessments",
        "learning_assessment_revisions",
        "learning_assessment_mutations",
    ):
        if bind.exec_driver_sql(f"SELECT 1 FROM {table} LIMIT 1").first() is not None:
            raise RuntimeError("Cannot downgrade saved learning evidence or Assessments.")
    op.drop_index(
        "ix_learning_assessment_mutation_assessment",
        table_name="learning_assessment_mutations",
    )
    op.drop_table("learning_assessment_mutations")
    op.drop_index(
        "ix_learning_assessment_revision_history",
        table_name="learning_assessment_revisions",
    )
    op.drop_table("learning_assessment_revisions")
    op.drop_index("ix_learning_assessments_owner_course", table_name="learning_assessments")
    op.drop_table("learning_assessments")
    op.drop_index("ix_learning_records_team_version", table_name="learning_records")
    op.drop_index("ix_learning_records_course_origin_privacy", table_name="learning_records")
    op.drop_index("ix_learning_records_actor_conversation", table_name="learning_records")
    op.drop_table("learning_records")
