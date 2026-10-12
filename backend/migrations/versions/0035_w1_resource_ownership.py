"""Add owner-scoped workspace resources and nullable single-chat knowledge.

Legacy group resources remain public and owner-unknown. SQLite parent tables
are rebuilt without renaming their live names, so existing child foreign keys
continue to reference the same tables while foreign-key checks are suspended.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_w1_resource_ownership"
down_revision: str | Sequence[str] | None = "0034_authored_content_unbounded"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AGENTS = "agents"
_DOCUMENTS = "knowledge_documents"
_CONVERSATIONS = "agent_conversations"

_REBUILDS = {
    _AGENTS: (
        "agents__0035_rebuild",
        """CREATE TABLE agents__0035_rebuild (
            id VARCHAR(36) NOT NULL,
            group_id VARCHAR(36),
            name VARCHAR(240) NOT NULL,
            description TEXT DEFAULT '' NOT NULL,
            status VARCHAR(16) DEFAULT 'active' NOT NULL,
            current_published_version_id VARCHAR(36),
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            metadata_revision INTEGER NOT NULL DEFAULT 0,
            deleted_at DATETIME,
            owner_user_id VARCHAR(36),
            course_id VARCHAR(36) NOT NULL,
            ownership_scope VARCHAR(16) NOT NULL DEFAULT 'group',
            visibility VARCHAR(16) NOT NULL DEFAULT 'public',
            authorization_epoch INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (id),
            CONSTRAINT ck_agents_status CHECK (status IN ('active', 'archived')),
            CONSTRAINT ck_agents_owner_scope CHECK (
                (ownership_scope = 'group' AND group_id IS NOT NULL)
                OR (ownership_scope = 'personal' AND group_id IS NULL AND owner_user_id IS NOT NULL)
            ),
            CONSTRAINT ck_agents_visibility CHECK (visibility IN ('private', 'public')),
            CONSTRAINT ck_agents_owner_visibility CHECK (
                owner_user_id IS NOT NULL
                OR (ownership_scope = 'group' AND visibility = 'public')
            ),
            CONSTRAINT ck_agents_authorization_epoch CHECK (authorization_epoch >= 0),
            FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE RESTRICT,
            FOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE CASCADE,
            FOREIGN KEY(group_id, course_id) REFERENCES groups (id, course_id) ON DELETE CASCADE
        )""",
        """INSERT INTO agents__0035_rebuild (
            id, group_id, name, description, status, current_published_version_id,
            created_at, updated_at, metadata_revision, deleted_at, owner_user_id,
            course_id, ownership_scope, visibility, authorization_epoch
        )
        SELECT agents.id, agents.group_id, agents.name, agents.description, agents.status,
            agents.current_published_version_id, agents.created_at, agents.updated_at,
            agents.metadata_revision, agents.deleted_at, NULL, groups.course_id,
            'group', 'public', 0
        FROM agents JOIN groups ON groups.id = agents.group_id""",
    ),
    _DOCUMENTS: (
        "knowledge_documents__0035_rebuild",
        """CREATE TABLE knowledge_documents__0035_rebuild (
            id VARCHAR(36) NOT NULL,
            group_id VARCHAR(36),
            source_filename VARCHAR(255) NOT NULL,
            stored_file_id VARCHAR(36) NOT NULL,
            char_count INTEGER NOT NULL,
            index_status VARCHAR(16) DEFAULT 'pending' NOT NULL,
            index_revision INTEGER DEFAULT '0' NOT NULL,
            workspace_state VARCHAR(16) DEFAULT 'active' NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            safe_error_code VARCHAR(64),
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            owner_user_id VARCHAR(36),
            course_id VARCHAR(36) NOT NULL,
            ownership_scope VARCHAR(16) NOT NULL DEFAULT 'group',
            visibility VARCHAR(16) NOT NULL DEFAULT 'public',
            authorization_epoch INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (id),
            CONSTRAINT ck_knowledge_documents_char_count CHECK (char_count >= 1),
            CONSTRAINT ck_knowledge_documents_index_revision CHECK (index_revision >= 0),
            CONSTRAINT ck_knowledge_documents_index_status CHECK (
                index_status IN ('pending', 'indexing', 'ready', 'failed')
            ),
            CONSTRAINT ck_knowledge_documents_workspace_state CHECK (
                workspace_state IN ('active', 'hidden')
            ),
            CONSTRAINT ck_knowledge_documents_owner_scope CHECK (
                (ownership_scope = 'group' AND group_id IS NOT NULL)
                OR (ownership_scope = 'personal' AND group_id IS NULL AND owner_user_id IS NOT NULL)
            ),
            CONSTRAINT ck_knowledge_documents_visibility CHECK (
                visibility IN ('private', 'public')
            ),
            CONSTRAINT ck_knowledge_documents_owner_visibility CHECK (
                owner_user_id IS NOT NULL
                OR (ownership_scope = 'group' AND visibility = 'public')
            ),
            CONSTRAINT ck_knowledge_documents_authorization_epoch CHECK (
                authorization_epoch >= 0
            ),
            FOREIGN KEY(stored_file_id) REFERENCES stored_files (id) ON DELETE RESTRICT,
            FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE RESTRICT,
            FOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE CASCADE,
            FOREIGN KEY(group_id, course_id) REFERENCES groups (id, course_id) ON DELETE CASCADE
        )""",
        """INSERT INTO knowledge_documents__0035_rebuild (
            id, group_id, source_filename, stored_file_id, char_count, index_status,
            index_revision, workspace_state, content_hash, safe_error_code, created_at,
            updated_at, owner_user_id, course_id, ownership_scope, visibility,
            authorization_epoch
        )
        SELECT knowledge_documents.id, knowledge_documents.group_id,
            knowledge_documents.source_filename, knowledge_documents.stored_file_id,
            knowledge_documents.char_count, knowledge_documents.index_status,
            knowledge_documents.index_revision, knowledge_documents.workspace_state,
            knowledge_documents.content_hash, knowledge_documents.safe_error_code,
            knowledge_documents.created_at, knowledge_documents.updated_at, NULL,
            groups.course_id, 'group', 'public', 0
        FROM knowledge_documents JOIN groups ON groups.id = knowledge_documents.group_id""",
    ),
    _CONVERSATIONS: (
        "agent_conversations__0035_rebuild",
        """CREATE TABLE agent_conversations__0035_rebuild (
            id VARCHAR(36) NOT NULL,
            user_id VARCHAR(36) NOT NULL,
            course_id VARCHAR(36) NOT NULL,
            agent_version_id VARCHAR(36) NOT NULL,
            snapshot_id VARCHAR(36),
            revision INTEGER NOT NULL,
            active_request_id VARCHAR(36),
            created_at DATETIME NOT NULL,
            agent_name_snapshot TEXT NOT NULL DEFAULT '',
            agent_authorization_epoch INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (id),
            CONSTRAINT ck_agent_conversations_revision CHECK (revision >= 0),
            CONSTRAINT ck_agent_conversations_authorization_epoch CHECK (
                agent_authorization_epoch >= 0
            ),
            FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE CASCADE,
            FOREIGN KEY(agent_version_id) REFERENCES agent_versions (id) ON DELETE RESTRICT,
            FOREIGN KEY(snapshot_id) REFERENCES knowledge_snapshots (id) ON DELETE RESTRICT
        )""",
        """INSERT INTO agent_conversations__0035_rebuild (
            id, user_id, course_id, agent_version_id, snapshot_id, revision,
            active_request_id, created_at, agent_name_snapshot, agent_authorization_epoch
        )
        SELECT conversations.id, conversations.user_id, conversations.course_id,
            conversations.agent_version_id, conversations.snapshot_id, conversations.revision,
            conversations.active_request_id, conversations.created_at, agents.name, 0
        FROM agent_conversations AS conversations
        JOIN agent_versions ON agent_versions.id=conversations.agent_version_id
        JOIN agents ON agents.id=agent_versions.agent_id""",
    ),
}


def _quoted(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sqlite_rebuild_all() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    began = False
    completed = False
    try:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        began = True
        initial_violations = {
            tuple(row) for row in connection.exec_driver_sql("PRAGMA foreign_key_check")
        }
        captured: dict[str, tuple[int, list[str]]] = {}
        for table, (_temporary, _create_sql, _insert_sql) in _REBUILDS.items():
            original_count = connection.exec_driver_sql(
                f"SELECT count(*) FROM {_quoted(table)}"
            ).scalar_one()
            objects = (
                connection.exec_driver_sql(
                    "SELECT sql FROM sqlite_master "
                    "WHERE tbl_name=? AND type IN ('index','trigger') "
                    "AND sql IS NOT NULL ORDER BY type,name",
                    (table,),
                )
                .scalars()
                .all()
            )
            captured[table] = (int(original_count), [str(value) for value in objects])
            if table in {_AGENTS, _DOCUMENTS}:
                dangling = connection.exec_driver_sql(
                    f"SELECT 1 FROM {_quoted(table)} AS resource "
                    "LEFT JOIN groups ON groups.id=resource.group_id "
                    "WHERE groups.id IS NULL LIMIT 1"
                ).first()
                if dangling is not None:
                    raise RuntimeError(f"Cannot assign a course to an orphan {table} row.")

        for table, (temporary, create_sql, insert_sql) in _REBUILDS.items():
            connection.exec_driver_sql(create_sql)
            connection.exec_driver_sql(insert_sql)
            copied_count = connection.exec_driver_sql(
                f"SELECT count(*) FROM {_quoted(temporary)}"
            ).scalar_one()
            if copied_count != captured[table][0]:
                raise RuntimeError(f"0035 failed to preserve every {table} row.")

        for table in _REBUILDS:
            temporary = _REBUILDS[table][0]
            connection.exec_driver_sql(f"DROP TABLE {_quoted(table)}")
            connection.exec_driver_sql(
                f"ALTER TABLE {_quoted(temporary)} RENAME TO {_quoted(table)}"
            )

        for _table, (_count, schema_objects) in captured.items():
            for statement in schema_objects:
                connection.exec_driver_sql(statement)

        connection.exec_driver_sql(
            "CREATE INDEX ix_agents_owner_course_scope "
            "ON agents (owner_user_id, course_id, ownership_scope, status)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_agents_course_visibility ON agents (course_id, visibility, status)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_documents_owner_course_state "
            "ON knowledge_documents (owner_user_id, course_id, workspace_state)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_knowledge_documents_course_visibility "
            "ON knowledge_documents (course_id, visibility, workspace_state)"
        )
        connection.exec_driver_sql(
            "ALTER TABLE agent_versions ADD COLUMN published_visibility VARCHAR(16) "
            "CHECK (published_visibility IS NULL OR "
            "published_visibility IN ('private', 'public'))"
        )
        connection.exec_driver_sql(
            "UPDATE agent_versions SET published_visibility='public' "
            "WHERE state IN ('published', 'superseded')"
        )
        connection.exec_driver_sql(
            "ALTER TABLE agent_versions ADD COLUMN authorization_epoch INTEGER "
            "NOT NULL DEFAULT 0 CHECK (authorization_epoch >= 0)"
        )
        connection.exec_driver_sql(
            "ALTER TABLE agent_versions ADD COLUMN draft_visibility VARCHAR(16) "
            "NOT NULL DEFAULT 'private'"
        )
        connection.exec_driver_sql(
            "ALTER TABLE snapshot_documents ADD COLUMN source_authorization_epoch INTEGER "
            "NOT NULL DEFAULT 0 CHECK (source_authorization_epoch >= 0)"
        )

        violations = {tuple(row) for row in connection.exec_driver_sql("PRAGMA foreign_key_check")}
        if violations - initial_violations:
            raise RuntimeError(
                f"0035 introduced foreign-key violations: {violations - initial_violations}"
            )
        completed = True
    finally:
        if began and not completed:
            connection.exec_driver_sql("ROLLBACK")


def _add_columns_non_sqlite() -> None:
    op.add_column(_AGENTS, sa.Column("owner_user_id", sa.String(36), nullable=True))
    op.add_column(_AGENTS, sa.Column("course_id", sa.String(36), nullable=True))
    op.add_column(
        _AGENTS,
        sa.Column("ownership_scope", sa.String(16), nullable=False, server_default="group"),
    )
    op.add_column(
        _AGENTS,
        sa.Column("visibility", sa.String(16), nullable=False, server_default="public"),
    )
    op.add_column(
        _AGENTS,
        sa.Column("authorization_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE agents SET course_id=(SELECT groups.course_id FROM groups "
        "WHERE groups.id=agents.group_id)"
    )
    op.alter_column(_AGENTS, "group_id", existing_type=sa.String(36), nullable=True)
    op.alter_column(_AGENTS, "course_id", existing_type=sa.String(36), nullable=False)

    op.add_column(_DOCUMENTS, sa.Column("owner_user_id", sa.String(36), nullable=True))
    op.add_column(_DOCUMENTS, sa.Column("course_id", sa.String(36), nullable=True))
    op.add_column(
        _DOCUMENTS,
        sa.Column("ownership_scope", sa.String(16), nullable=False, server_default="group"),
    )
    op.add_column(
        _DOCUMENTS,
        sa.Column("visibility", sa.String(16), nullable=False, server_default="public"),
    )
    op.add_column(
        _DOCUMENTS,
        sa.Column("authorization_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE knowledge_documents SET course_id=(SELECT groups.course_id FROM groups "
        "WHERE groups.id=knowledge_documents.group_id)"
    )
    op.alter_column(_DOCUMENTS, "group_id", existing_type=sa.String(36), nullable=True)
    op.alter_column(_DOCUMENTS, "course_id", existing_type=sa.String(36), nullable=False)

    op.add_column(
        _CONVERSATIONS,
        sa.Column("agent_authorization_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        _CONVERSATIONS,
        sa.Column("agent_name_snapshot", sa.Text(), nullable=False, server_default=""),
    )
    op.execute(
        "UPDATE agent_conversations SET agent_name_snapshot=(SELECT agents.name "
        "FROM agent_versions JOIN agents ON agents.id=agent_versions.agent_id "
        "WHERE agent_versions.id=agent_conversations.agent_version_id)"
    )
    op.alter_column(_CONVERSATIONS, "snapshot_id", existing_type=sa.String(36), nullable=True)
    op.add_column("agent_versions", sa.Column("published_visibility", sa.String(16), nullable=True))
    op.add_column(
        "agent_versions",
        sa.Column("authorization_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_versions",
        sa.Column(
            "draft_visibility",
            sa.String(16),
            nullable=False,
            server_default="private",
        ),
    )
    op.add_column(
        "snapshot_documents",
        sa.Column("source_authorization_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE agent_versions SET published_visibility='public' "
        "WHERE state IN ('published', 'superseded')"
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _sqlite_rebuild_all()
    else:
        _add_columns_non_sqlite()
    op.execute(
        "UPDATE agent_versions SET draft_visibility='public' "
        "WHERE state='draft' AND agent_id IN "
        "(SELECT id FROM agents WHERE visibility='public')"
    )
    op.execute(
        "UPDATE agent_versions SET draft_visibility='private' "
        "WHERE state='draft' AND EXISTS ("
        "SELECT 1 FROM agent_version_documents avd "
        "JOIN knowledge_documents kd ON kd.id=avd.document_id "
        "WHERE avd.agent_version_id=agent_versions.id "
        "AND avd.enabled=1 AND kd.visibility!='public')"
    )


def downgrade() -> None:
    bind = op.get_bind()
    nonrepresentable = bind.execute(
        sa.text(
            "SELECT 1 FROM agents WHERE group_id IS NULL OR owner_user_id IS NOT NULL "
            "OR visibility != 'public' LIMIT 1"
        )
    ).first()
    if nonrepresentable is not None:
        raise RuntimeError("Cannot downgrade while owner-scoped Agents exist.")
    nonrepresentable = bind.execute(
        sa.text(
            "SELECT 1 FROM knowledge_documents WHERE group_id IS NULL "
            "OR owner_user_id IS NOT NULL OR visibility != 'public' LIMIT 1"
        )
    ).first()
    if nonrepresentable is not None:
        raise RuntimeError("Cannot downgrade while owner-scoped sources exist.")
    if bind.execute(
        sa.text("SELECT 1 FROM agent_conversations WHERE snapshot_id IS NULL LIMIT 1")
    ).first():
        raise RuntimeError("Cannot downgrade while no-RAG conversations exist.")
    raise RuntimeError("0035 downgrade is intentionally unsupported; restore a verified backup.")
