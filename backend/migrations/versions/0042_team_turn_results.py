"""Persist each Team member result while retaining one canonical user Turn."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0042_team_turn_results"
down_revision: str | Sequence[str] | None = "0041_team_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_COLUMNS = (
    "id, conversation_id, position, user_text, assistant_text, sources_json, "
    "mode, state, safe_error_code, created_at"
)

_PARENT_SQL = """CREATE TABLE agent_conversation_turns__0042_rebuild (
id VARCHAR(36) NOT NULL,
conversation_id VARCHAR(36) NOT NULL,
position INTEGER NOT NULL,
user_text TEXT NOT NULL,
assistant_text TEXT,
sources_json TEXT NOT NULL,
mode VARCHAR(8) NOT NULL,
state VARCHAR(24) NOT NULL,
safe_error_code VARCHAR(80),
routing_json TEXT,
request_hash VARCHAR(64),
claim_token VARCHAR(36),
created_at DATETIME NOT NULL,
PRIMARY KEY (id),
CHECK (mode IN ('real', 'mock')),
CHECK (state IN ('pending', 'ready', 'partial', 'failed', 'acceptance_unknown',
    'paused')),
CONSTRAINT ck_team_turn_unique_reply_storage CHECK ((routing_json IS NULL AND
    request_hash IS NULL AND claim_token IS NULL) OR (routing_json IS NOT NULL AND
    request_hash IS NOT NULL AND length(request_hash)=64 AND claim_token IS NOT NULL AND
    assistant_text IS NULL AND sources_json='[]')),
CONSTRAINT uq_conversation_turn_scope UNIQUE (id, conversation_id),
FOREIGN KEY(conversation_id) REFERENCES agent_conversations (id) ON DELETE CASCADE
)"""

_LEGACY_SQL = """CREATE TABLE agent_conversation_turns__0042_rebuild (
 id VARCHAR(36) PRIMARY KEY NOT NULL,
 conversation_id VARCHAR(36) NOT NULL REFERENCES agent_conversations(id) ON DELETE CASCADE,
 position INTEGER NOT NULL, user_text TEXT NOT NULL, assistant_text TEXT,
 sources_json TEXT NOT NULL, mode VARCHAR(8) NOT NULL,
 state VARCHAR(24) NOT NULL, safe_error_code VARCHAR(80), created_at DATETIME NOT NULL,
 CHECK (mode IN ('real','mock')),
 CHECK (state IN ('pending','ready','failed','acceptance_unknown'))
)"""

_CHILD_SQL = (
    """CREATE TABLE team_turn_results (
id VARCHAR(36) NOT NULL,
turn_id VARCHAR(36) NOT NULL,
conversation_id VARCHAR(36) NOT NULL,
participant_id VARCHAR(36) NOT NULL,
ordinal INTEGER NOT NULL,
state VARCHAR(24) NOT NULL,
assistant_text TEXT,
sources_json TEXT NOT NULL,
safe_error_code VARCHAR(80),
created_at DATETIME NOT NULL,
completed_at DATETIME,
PRIMARY KEY (id),
FOREIGN KEY(turn_id, conversation_id) REFERENCES agent_conversation_turns (id,
    conversation_id) ON DELETE CASCADE,
FOREIGN KEY(participant_id, conversation_id) REFERENCES conversation_participants (id,
    conversation_id) ON DELETE CASCADE,
CONSTRAINT uq_team_result_participant UNIQUE (turn_id, participant_id),
CONSTRAINT uq_team_result_ordinal UNIQUE (turn_id, ordinal),
CONSTRAINT ck_team_result_ordinal CHECK (ordinal >= 0),
CONSTRAINT ck_team_result_state CHECK (state IN ('pending', 'running', 'ready',
    'failed', 'acceptance_unknown')),
CONSTRAINT ck_team_result_body CHECK ((state='ready' AND assistant_text IS NOT NULL AND
    length(trim(assistant_text))>0) OR (state!='ready' AND assistant_text IS NULL))
)""",
    """CREATE TABLE team_chat_events (
conversation_id VARCHAR(36) NOT NULL,
sequence INTEGER NOT NULL,
turn_id VARCHAR(36) NOT NULL,
result_id VARCHAR(36),
kind VARCHAR(24) NOT NULL,
created_at DATETIME NOT NULL,
PRIMARY KEY (conversation_id, sequence),
CONSTRAINT ck_team_chat_event_sequence CHECK (sequence >= 1),
CONSTRAINT ck_team_chat_event_kind CHECK (kind IN ('turn_started', 'member_result',
    'turn_done')),
FOREIGN KEY(conversation_id) REFERENCES agent_conversations (id) ON DELETE CASCADE,
FOREIGN KEY(turn_id) REFERENCES agent_conversation_turns (id) ON DELETE CASCADE,
FOREIGN KEY(result_id) REFERENCES team_turn_results (id) ON DELETE CASCADE
)""",
)


def _begin() -> set[tuple[object, ...]]:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError("Team turn migration requires the SQLite application database.")
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    if bind.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 0:
        raise RuntimeError("Cannot safely rebuild chat Turns inside an existing transaction.")
    bind.exec_driver_sql("BEGIN IMMEDIATE")
    return {tuple(row) for row in bind.exec_driver_sql("PRAGMA foreign_key_check")}


def _rebuild(create_sql: str) -> None:
    bind = op.get_bind()
    objects = list(
        bind.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE tbl_name='agent_conversation_turns' "
            "AND type IN ('index','trigger') AND sql IS NOT NULL ORDER BY type,name"
        ).scalars()
    )
    bind.exec_driver_sql(create_sql)
    bind.exec_driver_sql(
        f"INSERT INTO agent_conversation_turns__0042_rebuild ({_OLD_COLUMNS}) "
        f"SELECT {_OLD_COLUMNS} FROM agent_conversation_turns"
    )
    for left, right in (
        ("agent_conversation_turns", "agent_conversation_turns__0042_rebuild"),
        ("agent_conversation_turns__0042_rebuild", "agent_conversation_turns"),
    ):
        if (
            bind.exec_driver_sql(
                f"SELECT {_OLD_COLUMNS} FROM {left} EXCEPT SELECT {_OLD_COLUMNS} FROM {right}"
            ).first()
            is not None
        ):
            raise RuntimeError("0042 failed to preserve chat Turn history.")
    bind.exec_driver_sql("DROP TABLE agent_conversation_turns")
    bind.exec_driver_sql(
        "ALTER TABLE agent_conversation_turns__0042_rebuild RENAME TO agent_conversation_turns"
    )
    for statement in objects:
        bind.exec_driver_sql(statement)


def _check(initial: set[tuple[object, ...]]) -> None:
    current = {tuple(row) for row in op.get_bind().exec_driver_sql("PRAGMA foreign_key_check")}
    if current - initial:
        raise RuntimeError("0042 introduced invalid Team result relationships.")


def upgrade() -> None:
    initial = _begin()
    bind = op.get_bind()
    try:
        _rebuild(_PARENT_SQL)
        bind.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_conversation_participant_scope "
            "ON conversation_participants(id, conversation_id)"
        )
        for statement in _CHILD_SQL:
            bind.exec_driver_sql(statement)
        _check(initial)
    except Exception:
        bind.exec_driver_sql("ROLLBACK")
        raise


def downgrade() -> None:
    initial = _begin()
    bind = op.get_bind()
    try:
        if (
            bind.exec_driver_sql(
                "SELECT 1 FROM agent_conversation_turns WHERE routing_json IS NOT NULL LIMIT 1"
            ).first()
            is not None
        ):
            raise RuntimeError("Cannot downgrade saved Team messages or member results.")
        bind.exec_driver_sql("DROP TABLE team_chat_events")
        bind.exec_driver_sql("DROP TABLE team_turn_results")
        bind.exec_driver_sql("DROP INDEX uq_conversation_participant_scope")
        _rebuild(_LEGACY_SQL)
        _check(initial)
    except Exception:
        bind.exec_driver_sql("ROLLBACK")
        raise
