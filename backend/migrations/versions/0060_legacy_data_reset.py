"""Retire every learning resource made before the Agent-owned Brainform.

The owner asked for a clean classroom: old Agents (Laozi, Plato and Socrates
included), Chats, RAG, Teams, Knowledge, Debates, assessment records and Agent
notes leave every list so the full flow can be rebuilt and audited by hand.
Nothing is erased. Each retired row is recorded in ``data_reset_rows`` with
the state it had, and the downgrade puts exactly those rows back. Accounts,
courses, groups and Voices stay as they are; the Demo revives its own fixed
philosophers at startup.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0060_legacy_data_reset"
down_revision: str | Sequence[str] | None = "0059_chat_titles_pins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, soft-delete condition still live, state column recorded or None)
_RETIRED = (
    ("agents", "deleted_at IS NULL", "status"),
    ("agent_conversations", "withdrawn_at IS NULL", None),
    ("agent_conversation_turns", "state = 'pending'", "state"),
    ("assessment_attempts", "status IN ('in_progress', 'paused')", "status"),
    ("knowledge_documents", "workspace_state = 'active'", None),
    ("knowledge_sets", "deleted_at IS NULL", None),
    ("teams", "deleted_at IS NULL", None),
    ("course_team_publications", "state IN ('published', 'retained')", "state"),
    ("debates", "deleted_at IS NULL", None),
    ("agent_account_memories", "deleted_at IS NULL", None),
)


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def _execute(statement: str, **values: object) -> None:
    query = sa.text(statement)
    if "now" in values:
        # Bound as a timezone-aware DateTime so SQLite stores the same text
        # format the ORM writes and reads back.
        query = query.bindparams(sa.bindparam("now", type_=sa.DateTime(timezone=True)))
    op.get_bind().execute(query, values)


def upgrade() -> None:
    _begin()
    op.add_column("debates", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "agent_account_memories",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "data_reset_rows",
        sa.Column("table_name", sa.String(64), nullable=False),
        sa.Column("row_id", sa.String(36), nullable=False),
        sa.Column("previous_state", sa.String(32), nullable=True),
        sa.PrimaryKeyConstraint("table_name", "row_id"),
    )
    for table, live, state_column in _RETIRED:
        previous = state_column if state_column else "NULL"
        _execute(
            f"INSERT INTO data_reset_rows (table_name, row_id, previous_state) "
            f"SELECT '{table}', id, {previous} FROM {table} WHERE {live}"
        )

    now = datetime.now(UTC)
    retired = "id IN (SELECT row_id FROM data_reset_rows WHERE table_name = '{}')".format
    _execute(
        f"UPDATE agents SET deleted_at = :now, status = 'archived', updated_at = :now "
        f"WHERE {retired('agents')}",
        now=now,
    )
    # A pending reply can never land in a withdrawn Chat, as when its owner
    # deletes it.
    _execute(
        "UPDATE agent_conversation_turns SET state = 'failed', "
        f"safe_error_code = 'chat_withdrawn' WHERE {retired('agent_conversation_turns')}"
    )
    _execute(
        "UPDATE agent_conversations SET withdrawn_at = :now, active_request_id = NULL, "
        f"revision = revision + 1 WHERE {retired('agent_conversations')}",
        now=now,
    )
    _execute(
        "UPDATE assessment_attempts SET status = 'abandoned', abandoned_at = :now, "
        "abandonment_reason = 'chat_withdrawn', updated_at = :now, revision = revision + 1 "
        f"WHERE {retired('assessment_attempts')}",
        now=now,
    )
    _execute(
        "UPDATE knowledge_documents SET workspace_state = 'hidden' "
        f"WHERE {retired('knowledge_documents')}"
    )
    for table in ("knowledge_sets", "teams"):
        _execute(
            f"UPDATE {table} SET deleted_at = :now, updated_at = :now WHERE {retired(table)}",
            now=now,
        )
    _execute(
        "UPDATE course_team_publications SET state = 'revoked', revoked_at = :now "
        f"WHERE {retired('course_team_publications')}",
        now=now,
    )
    for table in ("debates", "agent_account_memories"):
        _execute(
            f"UPDATE {table} SET deleted_at = :now WHERE {retired(table)}",
            now=now,
        )


def downgrade() -> None:
    _begin()
    retired = "id IN (SELECT row_id FROM data_reset_rows WHERE table_name = '{}')".format
    previous = (
        "(SELECT previous_state FROM data_reset_rows WHERE table_name = '{}' AND row_id = {}.id)"
    ).format
    _execute(
        f"UPDATE agents SET deleted_at = NULL, status = {previous('agents', 'agents')} "
        f"WHERE {retired('agents')}"
    )
    _execute(
        f"UPDATE agent_conversations SET withdrawn_at = NULL WHERE {retired('agent_conversations')}"
    )
    _execute(
        "UPDATE agent_conversation_turns SET safe_error_code = NULL, "
        f"state = {previous('agent_conversation_turns', 'agent_conversation_turns')} "
        f"WHERE {retired('agent_conversation_turns')}"
    )
    _execute(
        "UPDATE assessment_attempts SET abandoned_at = NULL, abandonment_reason = NULL, "
        f"status = {previous('assessment_attempts', 'assessment_attempts')} "
        f"WHERE {retired('assessment_attempts')}"
    )
    _execute(
        "UPDATE knowledge_documents SET workspace_state = 'active' "
        f"WHERE {retired('knowledge_documents')}"
    )
    for table in ("knowledge_sets", "teams"):
        _execute(f"UPDATE {table} SET deleted_at = NULL WHERE {retired(table)}")
    _execute(
        "UPDATE course_team_publications SET revoked_at = NULL, "
        f"state = {previous('course_team_publications', 'course_team_publications')} "
        f"WHERE {retired('course_team_publications')}"
    )
    op.drop_table("data_reset_rows")
    bind = op.get_bind()
    for table in ("agent_account_memories", "debates"):
        if bind.dialect.name == "sqlite":
            bind.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN deleted_at")
        else:
            op.drop_column(table, "deleted_at")
