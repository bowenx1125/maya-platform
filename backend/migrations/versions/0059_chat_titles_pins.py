"""Let an owner rename a Chat and pin it to the top of their history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0059_chat_titles_pins"
down_revision: str | Sequence[str] | None = "0058_card_rooms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    # Both stay empty for existing Chats, which keep their automatic names.
    op.add_column("agent_conversations", sa.Column("title", sa.Text(), nullable=True))
    op.add_column(
        "agent_conversations",
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    _begin()
    bind = op.get_bind()
    for column in ("pinned_at", "title"):
        if bind.dialect.name == "sqlite":
            bind.exec_driver_sql(f"ALTER TABLE agent_conversations DROP COLUMN {column}")
        else:
            op.drop_column("agent_conversations", column)
