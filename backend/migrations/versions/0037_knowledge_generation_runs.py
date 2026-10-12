"""Add durable Knowledge preparation runs for the existing Jobs ledger."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_knowledge_generation_runs"
down_revision: str | Sequence[str] | None = "0036_knowledge_sets_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # Keep the DDL and Alembic head write in the same physical transaction.
        bind.exec_driver_sql("BEGIN IMMEDIATE")

    op.create_table(
        "knowledge_generation_runs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("input_key", sa.String(64), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("agent_version_id", sa.String(36), nullable=False),
        sa.Column("knowledge_set_id", sa.String(36), nullable=False),
        sa.Column("provider_operation_id", sa.String(36), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=True),
        sa.Column("agent_md_hash", sa.String(64), nullable=False),
        sa.Column("agent_authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("set_authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("source_manifest_json", sa.Text(), nullable=False),
        sa.Column("source_manifest_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("safe_error_code", sa.String(64), nullable=True),
        sa.Column("claim_token", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(input_key) = 64", name="ck_knowledge_generation_input_key"),
        sa.CheckConstraint("length(agent_md_hash) = 64", name="ck_knowledge_generation_agent_hash"),
        sa.CheckConstraint(
            "request_hash IS NULL OR length(request_hash) = 64",
            name="ck_knowledge_generation_request_hash",
        ),
        sa.CheckConstraint(
            "agent_authorization_epoch >= 0 AND set_authorization_epoch >= 0",
            name="ck_knowledge_generation_epochs",
        ),
        sa.CheckConstraint(
            "length(source_manifest_hash) = 64",
            name="ck_knowledge_generation_source_hash",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'running', 'blocked', 'completed', 'failed', 'interrupted')",
            name="ck_knowledge_generation_state",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["knowledge_set_id"], ["knowledge_sets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["provider_operation_id"], ["provider_operations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_knowledge_generation_job"),
        sa.UniqueConstraint("input_key", name="uq_knowledge_generation_input_key"),
    )
    op.create_index(
        "ix_knowledge_generation_owner_created",
        "knowledge_generation_runs",
        ["owner_user_id", "created_at"],
    )
    op.create_index(
        "ix_knowledge_generation_state_lease",
        "knowledge_generation_runs",
        ["state", "lease_expires_at"],
    )
    op.create_index(
        "ix_knowledge_generation_agent",
        "knowledge_generation_runs",
        ["agent_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    if (
        bind.exec_driver_sql("SELECT 1 FROM knowledge_generation_runs LIMIT 1").first() is not None
        or bind.exec_driver_sql(
            "SELECT 1 FROM jobs WHERE operation = 'knowledge_set.generate' LIMIT 1"
        ).first()
        is not None
    ):
        raise RuntimeError("Knowledge generation history exists; refusing to discard it.")
    op.drop_table("knowledge_generation_runs")
