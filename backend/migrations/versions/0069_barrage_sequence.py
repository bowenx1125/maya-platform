"""Per-window barrage sequence counter.

Revision ID: 0069_barrage_sequence
Revises: 0068_attempt_activity_index
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0069_barrage_sequence"
down_revision: str | Sequence[str] | None = "0068_attempt_activity_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BACKFILL = sa.text(
    """
    UPDATE classroom_interaction_windows
    SET barrage_sequence = (
        SELECT COALESCE(MAX(barrage_messages.sequence), 0)
        FROM barrage_messages
        WHERE barrage_messages.window_id = classroom_interaction_windows.id
    )
    """
)


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    bind = op.get_bind()
    # No CHECK on this column. SQLite refuses DROP COLUMN when a table-level
    # CHECK still names the column, and downgrade has to support both the
    # Alembic shape and a create_all database stamped at head.
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql(
            "ALTER TABLE classroom_interaction_windows ADD COLUMN "
            "barrage_sequence INTEGER NOT NULL DEFAULT 0"
        )
    else:
        op.add_column(
            "classroom_interaction_windows",
            sa.Column("barrage_sequence", sa.Integer(), nullable=False, server_default="0"),
        )
    op.execute(_BACKFILL)


def downgrade() -> None:
    _begin()
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql(
            "ALTER TABLE classroom_interaction_windows DROP COLUMN barrage_sequence"
        )
        return
    op.drop_column("classroom_interaction_windows", "barrage_sequence")
