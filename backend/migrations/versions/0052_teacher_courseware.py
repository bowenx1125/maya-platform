"""Retain the uploader role without rebuilding referenced courseware rows."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052_teacher_courseware"
down_revision: str | Sequence[str] | None = "0051_chat_memory_entry_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    # Existing source versions and snapshots reference this table. An inline
    # column check avoids dropping/rebuilding their parent under SQLite FK guards.
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "source_owner_role",
            sa.String(16),
            sa.CheckConstraint(
                "source_owner_role IN ('student', 'teacher')",
                name="ck_knowledge_documents_source_owner_role",
            ),
            nullable=False,
            server_default="student",
        ),
    )


def downgrade() -> None:
    _begin()
    if (
        op.get_bind()
        .exec_driver_sql(
            "SELECT 1 FROM knowledge_documents WHERE source_owner_role='teacher' LIMIT 1"
        )
        .first()
    ):
        raise RuntimeError("Cannot discard retained teacher courseware provenance.")
    op.drop_column("knowledge_documents", "source_owner_role")
