"""Add chat_type (agent or team) without dropping or guessing rows.

The column is added nullable, then filled only for rows that already satisfy
ck_conversations_entry: entry_kind and the agent or team binding agree,
including a chat whose source was removed and kept as history ids. A published
Maya Team (entry_kind maya_team) is a team chat. A row that does not satisfy
the check stays null and is counted in the migration log; the NOT NULL
constraint is added only when that count is zero. Other columns are not
rewritten.

Revision ID: 0081_conversation_chat_type
Revises: 0080_drop_playback_rate
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic.runtime.migration import log
from app.modules.real_delete_checks import (
    CHAT_TYPE_CHECK,
    CHAT_TYPE_CHECK_ALLOWING_UNKNOWN,
    CONVERSATION_ENTRY_CHECK,
)

revision: str = "0081_conversation_chat_type"
down_revision: str | Sequence[str] | None = "0080_drop_playback_rate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_conversations",
        sa.Column("chat_type", sa.String(length=16), nullable=True),
    )
    # Only a row whose stored kind matches its agent or team binding is filled.
    # Anything else stays null rather than being assigned a kind.
    op.execute(
        sa.text(
            "UPDATE agent_conversations SET chat_type = CASE "
            "WHEN entry_kind = 'agent' THEN 'agent' "
            "WHEN entry_kind IN ('team', 'maya_team') THEN 'team' "
            "ELSE NULL END "
            f"WHERE chat_type IS NULL AND ({CONVERSATION_ENTRY_CHECK})"
        )
    )
    unknown = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM agent_conversations WHERE chat_type IS NULL"))
        .scalar_one()
    )
    # Count only: no ids, names or message text.
    log.warning("agent_conversations chat_type unclassified: %s", unknown)
    if unknown == 0:
        op.create_check_constraint(
            "ck_conversations_chat_type", "agent_conversations", CHAT_TYPE_CHECK
        )
        op.alter_column("agent_conversations", "chat_type", nullable=False)
        return
    op.create_check_constraint(
        "ck_conversations_chat_type",
        "agent_conversations",
        CHAT_TYPE_CHECK_ALLOWING_UNKNOWN,
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "ALTER TABLE agent_conversations DROP CONSTRAINT IF EXISTS ck_conversations_chat_type"
        )
    )
    op.drop_column("agent_conversations", "chat_type")
