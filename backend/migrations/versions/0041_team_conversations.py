"""Freeze Team Chat identities without duplicating existing Single turn facts."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0041_team_conversations"
down_revision: str | Sequence[str] | None = "0040_teams_publication_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_COLUMNS = (
    "id, user_id, course_id, agent_version_id, snapshot_id, revision, "
    "active_request_id, created_at, agent_name_snapshot, agent_authorization_epoch"
)

_PARENT_SQL = """CREATE TABLE agent_conversations__0041_rebuild (
	id VARCHAR(36) NOT NULL,
	user_id VARCHAR(36) NOT NULL,
	course_id VARCHAR(36) NOT NULL,
	agent_version_id VARCHAR(36),
	snapshot_id VARCHAR(36),
	agent_name_snapshot TEXT NOT NULL DEFAULT '',
	agent_authorization_epoch INTEGER NOT NULL DEFAULT 0,
	entry_kind VARCHAR(16) DEFAULT 'agent' NOT NULL,
	chat_visibility VARCHAR(16) DEFAULT 'private' NOT NULL,
	origin VARCHAR(32) DEFAULT 'single_agent' NOT NULL,
	team_id VARCHAR(36),
	team_version_id VARCHAR(36),
	team_owner_user_id VARCHAR(36),
	team_name_snapshot TEXT,
	team_authorization_epoch INTEGER,
	publication_id VARCHAR(36),
	publication_epoch INTEGER,
	revision INTEGER NOT NULL,
	active_request_id VARCHAR(36),
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CHECK (revision >= 0),
	CHECK (agent_authorization_epoch >= 0),
	CONSTRAINT ck_conversations_privacy CHECK (chat_visibility IN ('private', 'public')),
CONSTRAINT ck_conversations_entry CHECK ((entry_kind = 'agent' AND origin =
    'single_agent' AND agent_version_id IS NOT NULL AND team_id IS NULL AND
    team_version_id IS NULL AND team_owner_user_id IS NULL AND team_name_snapshot IS
    NULL AND team_authorization_epoch IS NULL AND publication_id IS NULL AND
    publication_epoch IS NULL) OR (entry_kind IN ('team', 'maya_team') AND
    agent_version_id IS NULL AND snapshot_id IS NULL AND team_id IS NOT NULL AND
    team_version_id IS NOT NULL AND team_owner_user_id IS NOT NULL AND
    team_name_snapshot IS NOT NULL AND team_authorization_epoch IS NOT NULL AND
    team_authorization_epoch >= 0 AND ((entry_kind = 'team' AND origin = 'custom_team'
    AND publication_id IS NULL AND publication_epoch IS NULL) OR (entry_kind =
    'maya_team' AND origin = 'published_course_team' AND publication_id IS NOT NULL AND
    publication_epoch IS NOT NULL AND publication_epoch >= 0)))),
FOREIGN KEY(team_id, team_version_id) REFERENCES team_versions (team_id, id) ON DELETE
    RESTRICT,
	CONSTRAINT uq_conversations_team_version UNIQUE (id, team_version_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE CASCADE,
	FOREIGN KEY(agent_version_id) REFERENCES agent_versions (id) ON DELETE RESTRICT,
	FOREIGN KEY(snapshot_id) REFERENCES knowledge_snapshots (id) ON DELETE RESTRICT,
	FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE RESTRICT,
	FOREIGN KEY(team_owner_user_id) REFERENCES users (id) ON DELETE RESTRICT,
	FOREIGN KEY(publication_id) REFERENCES course_team_publications (id) ON DELETE RESTRICT
)"""

_LEGACY_SQL = """CREATE TABLE agent_conversations__0041_rebuild (
 id VARCHAR(36) NOT NULL PRIMARY KEY,
 user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 course_id VARCHAR(36) NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
 agent_version_id VARCHAR(36) NOT NULL REFERENCES agent_versions(id) ON DELETE RESTRICT,
 snapshot_id VARCHAR(36) REFERENCES knowledge_snapshots(id) ON DELETE RESTRICT,
 revision INTEGER NOT NULL CHECK (revision >= 0),
 active_request_id VARCHAR(36), created_at DATETIME NOT NULL,
 agent_name_snapshot TEXT NOT NULL DEFAULT '',
 agent_authorization_epoch INTEGER NOT NULL DEFAULT 0 CHECK (agent_authorization_epoch >= 0)
)"""

_CHILD_SQL = (
    """CREATE TABLE conversation_participants (
	id VARCHAR(36) NOT NULL,
	conversation_id VARCHAR(36) NOT NULL,
	team_version_id VARCHAR(36) NOT NULL,
	team_member_id VARCHAR(36) NOT NULL,
	agent_id VARCHAR(36) NOT NULL,
	agent_version_id VARCHAR(36) NOT NULL,
	snapshot_id VARCHAR(36),
	agent_authorization_epoch INTEGER NOT NULL,
	position INTEGER NOT NULL,
	is_leader BOOLEAN NOT NULL,
	display_name TEXT NOT NULL,
	avatar_config_json TEXT NOT NULL,
	invoke_grant_id VARCHAR(36),
	PRIMARY KEY (id),
FOREIGN KEY(conversation_id, team_version_id) REFERENCES agent_conversations (id,
    team_version_id) ON DELETE CASCADE,
FOREIGN KEY(team_version_id, team_member_id) REFERENCES team_version_members
    (team_version_id, id) ON DELETE RESTRICT,
CONSTRAINT ck_conversation_participant_counters CHECK (position >= 0 AND
    agent_authorization_epoch >= 0),
	CONSTRAINT uq_conversation_participant_member UNIQUE (conversation_id, team_member_id),
	CONSTRAINT uq_conversation_participant_position UNIQUE (conversation_id, position),
	FOREIGN KEY(agent_id) REFERENCES agents (id) ON DELETE RESTRICT,
	FOREIGN KEY(agent_version_id) REFERENCES agent_versions (id) ON DELETE RESTRICT,
	FOREIGN KEY(snapshot_id) REFERENCES knowledge_snapshots (id) ON DELETE RESTRICT,
	FOREIGN KEY(invoke_grant_id) REFERENCES team_member_invoke_grants (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE conversation_participant_sets (
	participant_id VARCHAR(36) NOT NULL,
	knowledge_set_id VARCHAR(36) NOT NULL,
	position INTEGER NOT NULL,
	PRIMARY KEY (participant_id, knowledge_set_id),
	CONSTRAINT ck_conversation_own_set_position CHECK (position >= 0),
	CONSTRAINT uq_conversation_own_set_position UNIQUE (participant_id, position),
	FOREIGN KEY(participant_id) REFERENCES conversation_participants (id) ON DELETE CASCADE,
	FOREIGN KEY(knowledge_set_id) REFERENCES knowledge_sets (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE conversation_shared_sets (
	conversation_id VARCHAR(36) NOT NULL,
	knowledge_set_id VARCHAR(36) NOT NULL,
	position INTEGER NOT NULL,
	PRIMARY KEY (conversation_id, knowledge_set_id),
	CONSTRAINT ck_conversation_shared_set_position CHECK (position >= 0),
	CONSTRAINT uq_conversation_shared_set_position UNIQUE (conversation_id, position),
	FOREIGN KEY(conversation_id) REFERENCES agent_conversations (id) ON DELETE CASCADE,
	FOREIGN KEY(knowledge_set_id) REFERENCES knowledge_sets (id) ON DELETE RESTRICT
)""",
)

_CHILD_INDEX_SQL = (
    "CREATE UNIQUE INDEX uq_conversation_participant_leader "
    "ON conversation_participants (conversation_id) WHERE is_leader IS 1",
)


def _rebuild_parent(create_sql: str) -> None:
    bind = op.get_bind()
    objects = list(
        bind.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE tbl_name='agent_conversations' "
            "AND type IN ('index','trigger') AND sql IS NOT NULL "
            "AND name != 'ix_conversations_course_privacy' ORDER BY type,name"
        ).scalars()
    )
    bind.exec_driver_sql(create_sql)
    bind.exec_driver_sql(
        f"INSERT INTO agent_conversations__0041_rebuild ({_OLD_COLUMNS}) "
        f"SELECT {_OLD_COLUMNS} FROM agent_conversations"
    )
    for left, right in (
        ("agent_conversations", "agent_conversations__0041_rebuild"),
        ("agent_conversations__0041_rebuild", "agent_conversations"),
    ):
        if (
            bind.exec_driver_sql(
                f"SELECT {_OLD_COLUMNS} FROM {left} EXCEPT SELECT {_OLD_COLUMNS} FROM {right}"
            ).first()
            is not None
        ):
            raise RuntimeError("0041 failed to preserve Single conversation data.")
    bind.exec_driver_sql("DROP TABLE agent_conversations")
    bind.exec_driver_sql(
        "ALTER TABLE agent_conversations__0041_rebuild RENAME TO agent_conversations"
    )
    for statement in objects:
        bind.exec_driver_sql(statement)


def _begin() -> set[tuple[object, ...]]:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError("Team conversation migration requires the SQLite application database.")
    # Parent rebuilding must not cascade-delete the existing Turn history.
    # migrations/env.py restores enforcement after the enclosing transaction.
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    if bind.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 0:
        raise RuntimeError("Cannot safely rebuild conversations inside an existing transaction.")
    bind.exec_driver_sql("BEGIN IMMEDIATE")
    return {tuple(row) for row in bind.exec_driver_sql("PRAGMA foreign_key_check")}


def _check_foreign_keys(initial: set[tuple[object, ...]]) -> None:
    current = {tuple(row) for row in op.get_bind().exec_driver_sql("PRAGMA foreign_key_check")}
    if current - initial:
        raise RuntimeError("0041 introduced invalid conversation relationships.")


def upgrade() -> None:
    initial = _begin()
    bind = op.get_bind()
    try:
        _rebuild_parent(_PARENT_SQL)
        bind.exec_driver_sql(
            "CREATE INDEX ix_conversations_course_privacy "
            "ON agent_conversations (course_id, chat_visibility, user_id)"
        )
        for statement in (*_CHILD_SQL, *_CHILD_INDEX_SQL):
            bind.exec_driver_sql(statement)
        _check_foreign_keys(initial)
    except Exception:
        bind.exec_driver_sql("ROLLBACK")
        raise


def downgrade() -> None:
    initial = _begin()
    bind = op.get_bind()
    try:
        if (
            bind.exec_driver_sql(
                "SELECT 1 FROM agent_conversations "
                "WHERE entry_kind != 'agent' OR chat_visibility != 'private' LIMIT 1"
            ).first()
            is not None
        ):
            raise RuntimeError("Cannot downgrade saved Team or Public conversations.")
        for table in (
            "conversation_participant_sets",
            "conversation_shared_sets",
            "conversation_participants",
        ):
            bind.exec_driver_sql(f"DROP TABLE {table}")
        _rebuild_parent(_LEGACY_SQL)
        _check_foreign_keys(initial)
    except Exception:
        bind.exec_driver_sql("ROLLBACK")
        raise
