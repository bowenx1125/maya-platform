"""Let a deleted chat, Agent or Team leave records and grades in place.

History foreign keys become nullable ``ON DELETE SET NULL``. Assessment
answers stay on the attempt. A chat whose Agent or Team is gone keeps a name
snapshot and ``source_removed_at`` so it can still be opened.

Revision ID: 0078_chat_answer_decouple
Revises: 0077_real_delete_history_links
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.sqlite_fk import (
    dropping_unnamed_foreign_keys,
    preserving_table_triggers,
    unnamed_fk_token,
)
from app.modules.real_delete_checks import (
    ATTEMPT_ABANDON_REASON_CHECK,
    ATTEMPT_QUESTION_SNAPSHOT_CHECK,
    CONVERSATION_ENTRY_CHECK,
    LEARNING_REVISION_EXECUTOR_CHECK,
    LEARNING_TEAM_ORIGIN_CHECK,
)

revision: str = "0078_chat_answer_decouple"
down_revision: str | Sequence[str] | None = "0077_real_delete_history_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk_names(table: str, columns: list[str]) -> list[str]:
    found: list[str] = []
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(table):
        if list(fk.get("constrained_columns") or []) == columns and fk.get("name"):
            found.append(str(fk["name"]))
    return found


def _nullable(table: str, columns: list[str], sqlite_batch: object | None) -> None:
    for column in columns:
        if sqlite_batch is not None:
            sqlite_batch.alter_column(column, existing_type=sa.String(36), nullable=True)  # type: ignore[attr-defined]
        else:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL")


def _add_fk(
    table: str,
    name: str,
    columns: list[str],
    ref: str,
    ref_columns: list[str],
    ondelete: str,
    *,
    sqlite_batch: object | None,
) -> None:
    if sqlite_batch is not None:
        sqlite_batch.create_foreign_key(  # type: ignore[attr-defined]
            name, ref, columns, ref_columns, ondelete=ondelete
        )
        return
    cols = ", ".join(columns)
    refs = ", ".join(ref_columns)
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({cols}) "
        f"REFERENCES {ref} ({refs}) ON DELETE {ondelete}"
    )


def _relink(
    table: str,
    columns: list[str],
    ref: str,
    ref_columns: list[str],
    ondelete: str,
    name: str,
    *,
    make_nullable: list[str] | None = None,
    create: bool = True,
) -> None:
    existing = _fk_names(table, columns)
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        with (
            dropping_unnamed_foreign_keys(),
            preserving_table_triggers(table),
            op.batch_alter_table(table, recreate="always") as batch,
        ):
            batch.drop_constraint(unnamed_fk_token(columns), type_="foreignkey")
            if make_nullable:
                _nullable(table, make_nullable, batch)
            if create:
                _add_fk(table, name, columns, ref, ref_columns, ondelete, sqlite_batch=batch)
        return
    for old in existing:
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "{old}"')
    if make_nullable:
        _nullable(table, make_nullable, None)
    if create:
        _add_fk(table, name, columns, ref, ref_columns, ondelete, sqlite_batch=None)


def _check_names(table: str) -> set[str]:
    return {
        str(item["name"])
        for item in sa.inspect(op.get_bind()).get_check_constraints(table)
        if item.get("name")
    }


def _replace_check(table: str, name: str, sql: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        # The revision source rule shipped as triggers, not a named CHECK.
        present = name in _check_names(table)
        with (
            preserving_table_triggers(table),
            op.batch_alter_table(table, recreate="always") as batch,
        ):
            if present:
                batch.drop_constraint(name, type_="check")
            batch.create_check_constraint(name, sql)
        return
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({sql})")


def _add(table: str, column: sa.Column) -> None:
    names = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
    if column.name not in names:
        op.add_column(table, column)


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        # 0045 enforced this with triggers. The CHECK below is the rule now,
        # including a detached Team whose name survives only as a snapshot.
        op.execute("DROP TRIGGER IF EXISTS ck_learning_assessment_revision_source_insert")
        op.execute("DROP TRIGGER IF EXISTS ck_learning_assessment_revision_source_update")
    _add("agent_conversations", sa.Column("source_removed_at", sa.DateTime(timezone=True)))
    _add("agent_conversations", sa.Column("history_agent_id", sa.String(36)))
    _add("agent_conversations", sa.Column("history_agent_version_id", sa.String(36)))
    _add(
        "agent_conversations",
        sa.Column("history_version_label", sa.Text(), nullable=False, server_default=""),
    )
    _add("agent_conversations", sa.Column("agent_avatar_json", sa.Text()))
    _add("agent_conversations", sa.Column("history_team_id", sa.String(36)))
    _add("agent_conversations", sa.Column("history_team_version_id", sa.String(36)))
    for table in (
        "learning_records",
        "learning_assessment_revisions",
        "assessment_activities",
        "assessment_attempts",
    ):
        _add(table, sa.Column("team_name_snapshot", sa.Text(), nullable=False, server_default=""))
    op.execute(
        "UPDATE agent_conversations SET history_agent_version_id = agent_version_id, "
        "history_agent_id = (SELECT agent_id FROM agent_versions "
        "WHERE agent_versions.id = agent_conversations.agent_version_id) "
        "WHERE entry_kind = 'agent' AND agent_version_id IS NOT NULL "
        "AND history_agent_id IS NULL"
    )
    op.execute(
        "UPDATE agent_conversations SET agent_avatar_json = (SELECT avatar_config_json "
        "FROM agent_versions WHERE agent_versions.id = agent_conversations.agent_version_id) "
        "WHERE entry_kind = 'agent' AND agent_version_id IS NOT NULL "
        "AND agent_avatar_json IS NULL"
    )
    op.execute(
        "UPDATE agent_conversations SET history_team_id = team_id, "
        "history_team_version_id = team_version_id "
        "WHERE team_id IS NOT NULL AND history_team_id IS NULL"
    )
    for table in (
        "assessment_activities",
        "assessment_attempts",
        "learning_records",
        "learning_assessment_revisions",
    ):
        op.execute(
            f"UPDATE {table} SET team_name_snapshot = (SELECT display_name FROM teams "
            f"WHERE teams.id = {table}.team_id) WHERE team_id IS NOT NULL "
            f"AND (team_name_snapshot IS NULL OR team_name_snapshot = '')"
        )

    _replace_check("agent_conversations", "ck_conversations_entry", CONVERSATION_ENTRY_CHECK)
    _replace_check(
        "learning_records", "ck_learning_records_team_origin", LEARNING_TEAM_ORIGIN_CHECK
    )
    _replace_check(
        "learning_assessment_revisions",
        "ck_learning_assessment_revision_team_origin",
        LEARNING_TEAM_ORIGIN_CHECK,
    )
    _replace_check(
        "learning_assessment_revisions",
        "ck_learning_assessment_revision_executor_provenance",
        LEARNING_REVISION_EXECUTOR_CHECK,
    )
    _replace_check(
        "assessment_attempts",
        "ck_assessment_attempt_abandonment_reason_kind",
        ATTEMPT_ABANDON_REASON_CHECK,
    )
    _replace_check(
        "assessment_attempt_questions",
        "ck_assessment_attempt_question_snapshot",
        ATTEMPT_QUESTION_SNAPSHOT_CHECK,
    )

    _relink(
        "agent_conversations",
        ["agent_version_id"],
        "agent_versions",
        ["id"],
        "SET NULL",
        "agent_conversations_agent_version_id_fkey",
    )
    _relink(
        "agent_conversations",
        ["snapshot_id"],
        "knowledge_snapshots",
        ["id"],
        "SET NULL",
        "agent_conversations_snapshot_id_fkey",
    )
    _relink(
        "agent_conversations",
        ["team_id"],
        "teams",
        ["id"],
        "SET NULL",
        "agent_conversations_team_id_fkey",
    )
    _relink(
        "agent_conversations",
        ["publication_id"],
        "course_team_publications",
        ["id"],
        "SET NULL",
        "agent_conversations_publication_id_fkey",
    )
    _relink(
        "agent_conversations",
        ["team_id", "team_version_id"],
        "team_versions",
        ["team_id", "id"],
        "SET NULL",
        "fk_conversations_team_version",
    )
    _relink(
        "conversation_participants",
        ["team_version_id", "team_member_id"],
        "team_version_members",
        ["team_version_id", "id"],
        "SET NULL",
        "conversation_participants_team_version_id_team_member_id_fkey",
        make_nullable=["team_version_id", "team_member_id"],
    )
    _relink(
        "conversation_participants",
        ["invoke_grant_id"],
        "team_member_invoke_grants",
        ["id"],
        "SET NULL",
        "conversation_participants_invoke_grant_id_fkey",
    )
    _relink(
        "learning_records",
        ["conversation_id"],
        "agent_conversations",
        ["id"],
        "SET NULL",
        "fk_learning_records_conversation",
        make_nullable=["conversation_id"],
    )
    _relink(
        "learning_records",
        ["team_id", "team_version_id"],
        "team_versions",
        ["team_id", "id"],
        "SET NULL",
        "fk_learning_records_team_version",
    )
    _relink(
        "learning_assessments",
        ["created_conversation_id"],
        "agent_conversations",
        ["id"],
        "SET NULL",
        "fk_learning_assessments_conversation",
        make_nullable=["created_conversation_id"],
    )
    _relink(
        "learning_assessment_revisions",
        ["conversation_id"],
        "agent_conversations",
        ["id"],
        "SET NULL",
        "fk_learning_assessment_revision_conversation",
        make_nullable=["conversation_id"],
    )
    _relink(
        "learning_assessment_revisions",
        ["team_id", "team_version_id"],
        "team_versions",
        ["team_id", "id"],
        "SET NULL",
        "fk_learning_assessment_revision_team_version",
    )
    _relink(
        "learning_assessment_mutations",
        ["conversation_id"],
        "agent_conversations",
        ["id"],
        "SET NULL",
        "fk_learning_assessment_mutation_conversation",
        make_nullable=["conversation_id"],
    )
    _relink(
        "learning_assessment_resource_grants",
        ["conversation_id"],
        "agent_conversations",
        ["id"],
        "SET NULL",
        "fk_learning_assessment_grant_conversation",
        make_nullable=["conversation_id"],
    )
    _relink(
        "learning_assessment_resource_grants",
        ["agent_version_id"],
        "agent_versions",
        ["id"],
        "SET NULL",
        "fk_learning_assessment_grant_agent_version",
        make_nullable=["agent_version_id"],
    )
    _relink(
        "assessment_activities",
        ["team_id", "team_version_id"],
        "team_versions",
        ["team_id", "id"],
        "SET NULL",
        "fk_assessment_activity_team_version",
        make_nullable=["team_id", "team_version_id"],
    )
    for column, ref, name in (
        ("publication_id", "course_team_publications", "fk_assessment_activity_publication"),
        ("recipe_version_id", "agent_versions", "fk_assessment_activity_recipe_version"),
        (
            "evaluator_agent_version_id",
            "agent_versions",
            "fk_assessment_activity_evaluator_version",
        ),
        ("boundary_agent_version_id", "agent_versions", "fk_assessment_activity_boundary_version"),
    ):
        _relink(
            "assessment_activities",
            [column],
            ref,
            ["id"],
            "SET NULL",
            name,
            make_nullable=[column],
        )
    _relink(
        "assessment_activities",
        ["team_version_id", "evaluator_team_member_id"],
        "team_version_members",
        ["team_version_id", "id"],
        "SET NULL",
        "fk_assessment_activity_evaluator_member",
        make_nullable=["evaluator_team_member_id"],
    )
    _relink(
        "assessment_activities",
        ["team_version_id", "boundary_team_member_id"],
        "team_version_members",
        ["team_version_id", "id"],
        "SET NULL",
        "fk_assessment_activity_boundary_member",
        make_nullable=["boundary_team_member_id"],
    )
    _relink(
        "assessment_activity_questions",
        ["asset_id", "knowledge_set_id"],
        "knowledge_assets",
        ["id", "knowledge_set_id"],
        "SET NULL",
        "fk_assessment_activity_question_asset",
        make_nullable=["asset_id", "knowledge_set_id"],
    )
    _relink(
        "assessment_activity_questions",
        ["question_version_id"],
        "knowledge_asset_versions",
        ["id"],
        "SET NULL",
        "fk_assessment_activity_question_version",
        make_nullable=["question_version_id"],
    )
    _relink(
        "assessment_attempts",
        ["activity_id", "team_id", "recipe_id"],
        "assessment_activities",
        ["id", "team_id", "recipe_id"],
        "RESTRICT",
        "fk_assessment_attempt_activity",
        create=False,
    )
    _relink(
        "assessment_attempts",
        ["activity_id"],
        "assessment_activities",
        ["id"],
        "RESTRICT",
        "fk_assessment_attempt_activity",
    )
    _relink(
        "assessment_attempts",
        ["source_conversation_id"],
        "agent_conversations",
        ["id"],
        "SET NULL",
        "fk_assessment_attempt_conversation",
        make_nullable=["source_conversation_id"],
    )
    _relink(
        "assessment_attempt_questions",
        ["question_version_id"],
        "knowledge_asset_versions",
        ["id"],
        "SET NULL",
        "fk_assessment_attempt_question_version",
    )
    _relink(
        "learning_boundaries",
        ["conversation_id"],
        "agent_conversations",
        ["id"],
        "SET NULL",
        "fk_learning_boundary_conversation",
        make_nullable=["conversation_id"],
    )
    _relink(
        "learning_boundary_revisions",
        ["summarizer_team_member_id"],
        "team_version_members",
        ["id"],
        "SET NULL",
        "fk_learning_boundary_revision_member",
        make_nullable=["summarizer_team_member_id"],
    )
    _relink(
        "learning_boundary_revisions",
        ["summarizer_agent_version_id"],
        "agent_versions",
        ["id"],
        "SET NULL",
        "fk_learning_boundary_revision_agent_version",
        make_nullable=["summarizer_agent_version_id"],
    )
    _relink(
        "conversation_participant_sets",
        ["knowledge_set_id"],
        "knowledge_sets",
        ["id"],
        "CASCADE",
        "conversation_participant_sets_knowledge_set_id_fkey",
    )
    _relink(
        "conversation_shared_sets",
        ["knowledge_set_id"],
        "knowledge_sets",
        ["id"],
        "CASCADE",
        "conversation_shared_sets_knowledge_set_id_fkey",
    )
    _relink(
        "team_version_sets",
        ["knowledge_set_id"],
        "knowledge_sets",
        ["id"],
        "SET NULL",
        "fk_team_version_sets_knowledge_set",
        make_nullable=["knowledge_set_id"],
    )


# 0045 created these. 0078 replaces them with a CHECK, so a downgrade that
# continues through 0045 must put the triggers back and remove that CHECK
# before 0045 drops the columns the CHECK names.
_REVISION_SOURCE_INSERT = (
    "CREATE TRIGGER ck_learning_assessment_revision_source_insert "
    "BEFORE INSERT ON learning_assessment_revisions "
    "WHEN NOT ("
    "(NEW.revision_source='user_authored' AND NEW.attempt_id IS NULL "
    "AND NEW.evaluator_team_member_id IS NULL AND NEW.evaluator_agent_version_id IS NULL "
    "AND NEW.editor_team_member_id IS NULL AND NEW.editor_agent_version_id IS NULL "
    "AND NEW.source_model_call_id IS NULL AND NEW.source_tool_call_id IS NULL) OR "
    "(NEW.revision_source='model_evaluation' AND NEW.attempt_id IS NOT NULL "
    "AND NEW.evaluator_team_member_id IS NOT NULL "
    "AND NEW.evaluator_agent_version_id IS NOT NULL "
    "AND NEW.editor_team_member_id IS NULL AND NEW.editor_agent_version_id IS NULL "
    "AND NEW.source_model_call_id IS NOT NULL AND NEW.source_tool_call_id IS NOT NULL) OR "
    "(NEW.revision_source='practice_agent_edit' AND NEW.attempt_id IS NULL "
    "AND NEW.evaluator_team_member_id IS NULL AND NEW.evaluator_agent_version_id IS NULL "
    "AND NEW.editor_agent_version_id IS NOT NULL "
    "AND ((NEW.origin='single_agent' AND NEW.team_id IS NULL "
    "AND NEW.team_version_id IS NULL AND NEW.editor_team_member_id IS NULL) OR "
    "(NEW.origin IN ('custom_team', 'published_course_team') "
    "AND NEW.team_id IS NOT NULL AND NEW.team_version_id IS NOT NULL "
    "AND NEW.editor_team_member_id IS NOT NULL)) "
    "AND NEW.source_model_call_id IS NOT NULL AND NEW.source_tool_call_id IS NOT NULL)) "
    "BEGIN SELECT RAISE(ABORT, 'invalid assessment revision source'); END"
)
_REVISION_SOURCE_UPDATE = (
    "CREATE TRIGGER ck_learning_assessment_revision_source_update "
    "BEFORE UPDATE OF revision_source, attempt_id, evaluator_team_member_id, "
    "evaluator_agent_version_id, editor_team_member_id, editor_agent_version_id, origin, "
    "team_id, team_version_id, source_model_call_id, source_tool_call_id "
    "ON learning_assessment_revisions "
    "WHEN NOT ("
    "(NEW.revision_source='user_authored' AND NEW.attempt_id IS NULL "
    "AND NEW.evaluator_team_member_id IS NULL AND NEW.evaluator_agent_version_id IS NULL "
    "AND NEW.editor_team_member_id IS NULL AND NEW.editor_agent_version_id IS NULL "
    "AND NEW.source_model_call_id IS NULL AND NEW.source_tool_call_id IS NULL) OR "
    "(NEW.revision_source='model_evaluation' AND NEW.attempt_id IS NOT NULL "
    "AND NEW.evaluator_team_member_id IS NOT NULL "
    "AND NEW.evaluator_agent_version_id IS NOT NULL "
    "AND NEW.editor_team_member_id IS NULL AND NEW.editor_agent_version_id IS NULL "
    "AND NEW.source_model_call_id IS NOT NULL AND NEW.source_tool_call_id IS NOT NULL) OR "
    "(NEW.revision_source='practice_agent_edit' AND NEW.attempt_id IS NULL "
    "AND NEW.evaluator_team_member_id IS NULL AND NEW.evaluator_agent_version_id IS NULL "
    "AND NEW.editor_agent_version_id IS NOT NULL "
    "AND ((NEW.origin='single_agent' AND NEW.team_id IS NULL "
    "AND NEW.team_version_id IS NULL AND NEW.editor_team_member_id IS NULL) OR "
    "(NEW.origin IN ('custom_team', 'published_course_team') "
    "AND NEW.team_id IS NOT NULL AND NEW.team_version_id IS NOT NULL "
    "AND NEW.editor_team_member_id IS NOT NULL)) "
    "AND NEW.source_model_call_id IS NOT NULL AND NEW.source_tool_call_id IS NOT NULL)) "
    "BEGIN SELECT RAISE(ABORT, 'invalid assessment revision source'); END"
)


def downgrade() -> None:
    # Detached history cannot grow its foreign keys back.
    bind = op.get_bind()
    detached = bind.execute(
        sa.text("SELECT count(*) FROM agent_conversations WHERE source_removed_at IS NOT NULL")
    ).scalar()
    if detached:
        raise RuntimeError("0078 is forward-only once an Agent or Team chat was detached")
    if bind.dialect.name != "sqlite":
        # PostgreSQL can drop the added check; the SET NULL links stay, matching
        # 0077. A later 0045 downgrade is SQLite-only.
        op.execute(
            "ALTER TABLE learning_assessment_revisions DROP CONSTRAINT IF EXISTS "
            "ck_learning_assessment_revision_executor_provenance"
        )
        return
    if "ck_learning_assessment_revision_executor_provenance" in _check_names(
        "learning_assessment_revisions"
    ):
        with (
            preserving_table_triggers("learning_assessment_revisions"),
            op.batch_alter_table("learning_assessment_revisions", recreate="always") as batch,
        ):
            batch.drop_constraint(
                "ck_learning_assessment_revision_executor_provenance", type_="check"
            )
    op.execute(_REVISION_SOURCE_INSERT)
    op.execute(_REVISION_SOURCE_UPDATE)
