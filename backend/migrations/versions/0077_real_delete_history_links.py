"""Let history outlive the Agent, version, file or voice it came from.

Real deletion (2026-10-20): hard-deleting an Agent version, a RAG file or a
Voice must not fail on, or erase, history that referenced it.

* History/lineage links become nullable ``ON DELETE SET NULL``.
* Pure dependents (a version's file binding, a file's edit history, a voice's
  provider operations, an Agent's account memories) ``CASCADE``.
* Debates own their copies: ``debate_participants`` gains ``agent_md_snapshot``
  and a voice snapshot, backfilled here, and drops the composite FKs that
  pinned it to live ``agent_versions`` rows. ``knowledge_snapshots.owner_debate_id``
  marks a deep copy (files, documents, chunks). The participant FK stays
  RESTRICT on that copy only; the original snapshot is not referenced, so
  Brainform can delete RAG, Knowledge and Voices without touching a Debate.

Left RESTRICT in this revision: assessment provenance and
``agent_conversations``. 0078 makes those nullable. SQLite rebuilds the same
foreign keys as PostgreSQL; triggers on a rebuilt table are restored.

Revision ID: 0077_real_delete_history_links
Revises: 0076_agent_editor_audit (#229) <- 0075_answer_guard_state (#225) <- 0074

Migration chain (planned, linear): #225 = 0075_answer_guard_state,
#229 = 0076_agent_editor_audit, this = 0077, chat hard-delete = 0078.
0076 is on main. Chat hard-delete follows as 0078.
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.sqlite_fk import (
    dropping_unnamed_foreign_keys,
    preserving_table_triggers,
    unnamed_fk_token,
)

revision: str = "0077_real_delete_history_links"
down_revision: str | Sequence[str] | None = "0076_agent_editor_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, constraint, column, ref_table, ondelete, make_nullable)
_RELINKS: tuple[tuple[str, str, str, str, str, bool], ...] = (
    (
        "knowledge_snapshots",
        "knowledge_snapshots_agent_version_id_fkey",
        "agent_version_id",
        "agent_versions",
        "SET NULL",
        True,
    ),
    (
        "snapshot_documents",
        "snapshot_documents_document_id_fkey",
        "document_id",
        "knowledge_documents",
        "SET NULL",
        True,
    ),
    (
        "knowledge_chunks",
        "knowledge_chunks_document_id_fkey",
        "document_id",
        "knowledge_documents",
        "SET NULL",
        True,
    ),
    (
        "agent_version_documents",
        "agent_version_documents_document_id_fkey",
        "document_id",
        "knowledge_documents",
        "CASCADE",
        False,
    ),
    (
        "knowledge_document_versions",
        "knowledge_document_versions_document_id_fkey",
        "document_id",
        "knowledge_documents",
        "CASCADE",
        False,
    ),
    (
        "knowledge_set_sources",
        "knowledge_set_sources_document_id_fkey",
        "document_id",
        "knowledge_documents",
        "SET NULL",
        True,
    ),
    (
        "knowledge_asset_version_sources",
        "knowledge_asset_version_sources_document_id_fkey",
        "document_id",
        "knowledge_documents",
        "SET NULL",
        True,
    ),
    (
        "knowledge_generation_source_receipts",
        "knowledge_generation_source_receipts_document_id_fkey",
        "document_id",
        "knowledge_documents",
        "SET NULL",
        True,
    ),
    (
        "knowledge_asset_versions",
        "knowledge_asset_versions_generator_agent_version_id_fkey",
        "generator_agent_version_id",
        "agent_versions",
        "SET NULL",
        True,
    ),
    (
        "knowledge_set_markdown_versions",
        "knowledge_set_markdown_versions_generator_agent_version_id_fkey",
        "generator_agent_version_id",
        "agent_versions",
        "SET NULL",
        True,
    ),
    (
        "knowledge_generation_runs",
        "knowledge_generation_runs_agent_id_fkey",
        "agent_id",
        "agents",
        "SET NULL",
        True,
    ),
    (
        "knowledge_generation_runs",
        "knowledge_generation_runs_agent_version_id_fkey",
        "agent_version_id",
        "agent_versions",
        "SET NULL",
        True,
    ),
    (
        "runtime_model_call_stages",
        "runtime_model_call_stages_executor_agent_version_id_fkey",
        "executor_agent_version_id",
        "agent_versions",
        "SET NULL",
        True,
    ),
    (
        "team_version_members",
        "team_version_members_agent_id_fkey",
        "agent_id",
        "agents",
        "SET NULL",
        True,
    ),
    (
        "team_version_members",
        "team_version_members_agent_version_id_fkey",
        "agent_version_id",
        "agent_versions",
        "SET NULL",
        True,
    ),
    (
        "team_member_invoke_grants",
        "team_member_invoke_grants_agent_id_fkey",
        "agent_id",
        "agents",
        "SET NULL",
        True,
    ),
    (
        "team_member_invoke_grants",
        "team_member_invoke_grants_agent_version_id_fkey",
        "agent_version_id",
        "agent_versions",
        "SET NULL",
        True,
    ),
    (
        "conversation_participants",
        "conversation_participants_agent_id_fkey",
        "agent_id",
        "agents",
        "SET NULL",
        True,
    ),
    (
        "conversation_participants",
        "conversation_participants_agent_version_id_fkey",
        "agent_version_id",
        "agent_versions",
        "SET NULL",
        True,
    ),
    (
        "conversation_participants",
        "conversation_participants_snapshot_id_fkey",
        "snapshot_id",
        "knowledge_snapshots",
        "SET NULL",
        True,
    ),
    (
        "agent_account_memories",
        "agent_account_memories_agent_id_fkey",
        "agent_id",
        "agents",
        "CASCADE",
        False,
    ),
    (
        "voice_provider_operations",
        "fk_voice_provider_operations_profile",
        "profile_id",
        "voice_profiles",
        "CASCADE",
        False,
    ),
    (
        "debate_participants",
        "fk_debate_participants_requested_voice",
        "requested_voice_profile_id",
        "voice_profiles",
        "SET NULL",
        True,
    ),
    (
        "debate_participants",
        "fk_debate_participants_effective_voice",
        "effective_voice_profile_id",
        "voice_profiles",
        "SET NULL",
        True,
    ),
    (
        "debate_turns",
        "fk_debate_turns_actual_voice_profile",
        "actual_tts_voice_profile_id",
        "voice_profiles",
        "SET NULL",
        True,
    ),
)

_DEBATE_COMPOSITES = (
    "fk_debate_participants_agent_group",
    "fk_debate_participants_version_snapshot",
    "fk_debate_participants_snapshot_version",
)

_BACKFILL_AGENT_MD = """
UPDATE debate_participants AS p
SET agent_md_snapshot = v.agent_md
FROM agent_versions AS v
WHERE v.id = p.agent_version_id AND p.agent_md_snapshot IS NULL
"""

_BACKFILL_VOICE = """
UPDATE debate_participants AS p
SET voice_snapshot_json = json_build_object(
        'display_name', vp.display_name,
        'group_id', vp.group_id,
        'provider_key', vp.provider_key,
        'scope', vp.scope,
        'target_model_key', vp.target_model_key,
        'voice_profile_id', vp.id
    )::text,
    voice_external_id_encrypted = vp.external_id_encrypted
FROM voice_profiles AS vp
WHERE vp.id = p.effective_voice_profile_id AND p.voice_snapshot_json IS NULL
"""


_BACKFILL_PERSONA_HASH = """
UPDATE debate_participants AS p
SET persona_spec_hash_snapshot = v.persona_spec_hash
FROM agent_versions AS v
WHERE v.id = p.agent_version_id AND p.persona_spec_hash_snapshot IS NULL
"""


def _sqlite_fk_name(table: str, column: str) -> str | None:
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(table):
        if fk.get("constrained_columns") == [column] and fk.get("name"):
            return str(fk["name"])
    return None


def _drop_barrage_scope_triggers() -> None:
    # These triggers live on barrage_messages and name debate_turns. SQLite
    # refuses to rename debate_turns while they still point at it.
    for name in ("barrage_turn_scope_insert", "barrage_turn_scope_update"):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))


def _create_barrage_scope_triggers() -> None:
    op.execute(
        sa.text(
            "CREATE TRIGGER barrage_turn_scope_insert BEFORE INSERT ON barrage_messages "
            "WHEN NEW.turn_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM debate_turns WHERE id=NEW.turn_id AND debate_id=NEW.debate_id) "
            "BEGIN SELECT RAISE(ABORT, 'barrage_turn_scope'); END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER barrage_turn_scope_update BEFORE UPDATE ON barrage_messages "
            "WHEN NEW.turn_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM debate_turns WHERE id=NEW.turn_id AND debate_id=NEW.debate_id) "
            "BEGIN SELECT RAISE(ABORT, 'barrage_turn_scope'); END"
        )
    )


def _relink_sqlite() -> None:
    """SQLite demo upgrades build from these migrations, not from the models."""

    _drop_barrage_scope_triggers()
    try:
        _relink_sqlite_tables()
    finally:
        _create_barrage_scope_triggers()


def _relink_sqlite_tables() -> None:
    with dropping_unnamed_foreign_keys():
        _relink_sqlite_tables_inner()


def _named_fks(table: str) -> set[str]:
    return {
        str(fk["name"])
        for fk in sa.inspect(op.get_bind()).get_foreign_keys(table)
        if fk.get("name")
    }


def _relink_sqlite_tables_inner() -> None:
    # Downgrade leaves the dropped composites gone, so a later upgrade must
    # accept a table that already has the replacement foreign keys.
    participant_fks = _named_fks("debate_participants")
    with (
        preserving_table_triggers("debate_participants"),
        op.batch_alter_table("debate_participants", recreate="always") as batch,
    ):
        for name in _DEBATE_COMPOSITES:
            if name in participant_fks:
                batch.drop_constraint(name, type_="foreignkey")
        batch.alter_column("agent_id", existing_type=sa.String(36), nullable=True)
        batch.alter_column("agent_version_id", existing_type=sa.String(36), nullable=True)
        if "fk_debate_participants_agent" not in participant_fks:
            batch.create_foreign_key(
                "fk_debate_participants_agent",
                "agents",
                ["agent_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "fk_debate_participants_agent_version" not in participant_fks:
            batch.create_foreign_key(
                "fk_debate_participants_agent_version",
                "agent_versions",
                ["agent_version_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "fk_debate_participants_snapshot" not in participant_fks:
            batch.create_foreign_key(
                "fk_debate_participants_snapshot",
                "knowledge_snapshots",
                ["knowledge_snapshot_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        batch.drop_constraint("ck_debate_participants_voice_shape", type_="check")
        batch.create_check_constraint(
            "ck_debate_participants_voice_shape",
            "(effective_voice_kind = 'mock_sentinel' AND effective_voice_profile_id IS NULL) OR "
            "(effective_voice_kind = 'platform_profile' AND "
            "(effective_voice_profile_id IS NOT NULL OR voice_snapshot_json IS NOT NULL))",
        )
    voice_name = _sqlite_fk_name("debate_turns", "actual_tts_voice_profile_id")
    with (
        preserving_table_triggers("debate_turns"),
        op.batch_alter_table("debate_turns", recreate="always") as batch,
    ):
        batch.drop_constraint("ck_debate_turns_actual_voice_shape", type_="check")
        batch.create_check_constraint(
            "ck_debate_turns_actual_voice_shape",
            "actual_tts_voice_kind IS NULL OR "
            "(actual_tts_voice_kind = 'mock_sentinel' AND actual_tts_voice_profile_id IS NULL) OR "
            "actual_tts_voice_kind = 'platform_profile'",
        )
        batch.drop_constraint("fk_debate_turns_participant_snapshot", type_="foreignkey")
        batch.create_foreign_key(
            "fk_debate_turns_participant_snapshot",
            "debate_participants",
            ["participant_id", "knowledge_snapshot_id"],
            ["id", "knowledge_snapshot_id"],
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        )
        if voice_name:
            batch.drop_constraint(voice_name, type_="foreignkey")
        batch.create_foreign_key(
            "fk_debate_turns_actual_voice_profile",
            "voice_profiles",
            ["actual_tts_voice_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )
    for table, constraint, column, ref_table, ondelete, nullable in _RELINKS:
        if table == "debate_turns" and column == "actual_tts_voice_profile_id":
            continue
        with (
            preserving_table_triggers(table),
            op.batch_alter_table(table, recreate="always") as batch,
        ):
            batch.drop_constraint(unnamed_fk_token([column]), type_="foreignkey")
            if nullable:
                batch.alter_column(column, existing_type=sa.String(36), nullable=True)
            batch.create_foreign_key(constraint, ref_table, [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("debate_participants")}
    for column in (
        sa.Column("agent_md_snapshot", sa.Text(), nullable=True),
        sa.Column("voice_snapshot_json", sa.Text(), nullable=True),
        sa.Column("voice_external_id_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("persona_spec_hash_snapshot", sa.String(length=64), nullable=True),
    ):
        # A SQLite downgrade keeps these (its CHECKs name them); re-upgrade
        # must then not add them twice.
        if column.name not in existing:
            op.add_column("debate_participants", column)
    with op.batch_alter_table("voice_profiles") as batch:
        batch.add_column(sa.Column("sample_file_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("sample_language", sa.String(length=16), nullable=True))
        batch.create_foreign_key(
            "fk_voice_profiles_sample",
            "stored_files",
            ["sample_file_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_table(
        "debate_voice_clones",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("source_voice_profile_id", sa.String(length=36), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider_key", sa.String(length=32), nullable=False),
        sa.Column("target_model_key", sa.String(length=120), nullable=False),
        sa.Column(
            "sample_file_id",
            sa.String(length=36),
            sa.ForeignKey(
                "stored_files.id", ondelete="RESTRICT", name="fk_debate_voice_clones_sample"
            ),
            nullable=True,
        ),
        sa.Column("sample_language", sa.String(length=16), nullable=True),
        sa.Column("recovery_name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("external_id_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("provider_voice_hash", sa.String(length=64), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("safe_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "debate_id", "source_voice_profile_id", name="uq_debate_voice_clones_debate_voice"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'failed', 'no_sample')",
            name="ck_debate_voice_clones_status",
        ),
        sa.CheckConstraint(
            "origin IN ('create', 'backfill')", name="ck_debate_voice_clones_origin"
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_debate_voice_clones_attempts"),
    )
    op.create_index("ix_debate_voice_clones_status", "debate_voice_clones", ["status"])
    op.create_index(
        "ix_debate_voice_clones_voice_hash", "debate_voice_clones", ["provider_voice_hash"]
    )
    op.add_column(
        "knowledge_snapshots",
        sa.Column("owner_debate_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_knowledge_snapshots_owner_debate", "knowledge_snapshots", ["owner_debate_id"]
    )
    op.create_table(
        "debate_knowledge_copies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("participant_id", sa.String(length=36), nullable=False),
        sa.Column("source_knowledge_set_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "participant_id",
            "source_knowledge_set_id",
            name="uq_debate_knowledge_copies_participant_set",
        ),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_debate_knowledge_copies_hash"),
    )
    op.create_index("ix_debate_knowledge_copies_debate", "debate_knowledge_copies", ["debate_id"])
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        _relink_sqlite()
        return
    op.execute(_BACKFILL_AGENT_MD)
    op.execute(_BACKFILL_VOICE)
    op.execute(_BACKFILL_PERSONA_HASH)

    for name in _DEBATE_COMPOSITES:
        op.execute(f"ALTER TABLE debate_participants DROP CONSTRAINT IF EXISTS {name}")
    op.execute("ALTER TABLE debate_participants ALTER COLUMN agent_id DROP NOT NULL")
    op.execute("ALTER TABLE debate_participants ALTER COLUMN agent_version_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE debate_participants DROP CONSTRAINT IF EXISTS fk_debate_participants_agent"
    )
    op.execute(
        "ALTER TABLE debate_participants ADD CONSTRAINT fk_debate_participants_agent "
        "FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE debate_participants "
        "DROP CONSTRAINT IF EXISTS fk_debate_participants_agent_version"
    )
    op.execute(
        "ALTER TABLE debate_participants ADD CONSTRAINT fk_debate_participants_agent_version "
        "FOREIGN KEY (agent_version_id) REFERENCES agent_versions(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE debate_participants DROP CONSTRAINT IF EXISTS fk_debate_participants_snapshot"
    )
    op.execute(
        "ALTER TABLE debate_participants ADD CONSTRAINT fk_debate_participants_snapshot "
        "FOREIGN KEY (knowledge_snapshot_id) REFERENCES knowledge_snapshots(id) "
        "ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE debate_turns DROP CONSTRAINT IF EXISTS fk_debate_turns_participant_snapshot"
    )
    op.execute(
        "ALTER TABLE debate_turns ADD CONSTRAINT fk_debate_turns_participant_snapshot "
        "FOREIGN KEY (participant_id, knowledge_snapshot_id) "
        "REFERENCES debate_participants (id, knowledge_snapshot_id) "
        "ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED"
    )

    for table, constraint, column, ref_table, ondelete, nullable in _RELINKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
        if nullable:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} FOREIGN KEY ({column}) "
            f"REFERENCES {ref_table}(id) ON DELETE {ondelete}"
        )

    # A deleted voice leaves the platform_profile decision with only its copy.
    op.execute(
        "ALTER TABLE debate_participants DROP CONSTRAINT IF EXISTS "
        "ck_debate_participants_voice_shape"
    )
    op.execute(
        "ALTER TABLE debate_participants ADD CONSTRAINT ck_debate_participants_voice_shape "
        "CHECK ((effective_voice_kind = 'mock_sentinel' AND effective_voice_profile_id IS NULL) "
        "OR (effective_voice_kind = 'platform_profile' AND "
        "(effective_voice_profile_id IS NOT NULL OR voice_snapshot_json IS NOT NULL)))"
    )
    op.execute(
        "ALTER TABLE debate_turns DROP CONSTRAINT IF EXISTS ck_debate_turns_actual_voice_shape"
    )
    op.execute(
        "ALTER TABLE debate_turns ADD CONSTRAINT ck_debate_turns_actual_voice_shape "
        "CHECK (actual_tts_voice_kind IS NULL OR "
        "(actual_tts_voice_kind = 'mock_sentinel' AND actual_tts_voice_profile_id IS NULL) "
        "OR actual_tts_voice_kind = 'platform_profile')"
    )


def downgrade() -> None:
    op.drop_index("ix_debate_knowledge_copies_debate", table_name="debate_knowledge_copies")
    op.drop_table("debate_knowledge_copies")
    op.drop_index("ix_knowledge_snapshots_owner_debate", table_name="knowledge_snapshots")
    op.drop_column("knowledge_snapshots", "owner_debate_id")
    op.drop_index("ix_debate_voice_clones_voice_hash", table_name="debate_voice_clones")
    op.drop_index("ix_debate_voice_clones_status", table_name="debate_voice_clones")
    op.drop_table("debate_voice_clones")
    with op.batch_alter_table("voice_profiles") as batch:
        batch.drop_constraint("fk_voice_profiles_sample", type_="foreignkey")
        batch.drop_column("sample_language")
        batch.drop_column("sample_file_id")
    # Restoring RESTRICT/NOT NULL would fail once rows were really deleted;
    # like 0066 this migration is forward-only on PostgreSQL.
    if op.get_bind().dialect.name == "sqlite":
        # SQLite cannot drop a column a CHECK names; extra NULL columns are inert.
        return
    for column in (
        "persona_spec_hash_snapshot",
        "voice_external_id_encrypted",
        "voice_snapshot_json",
        "agent_md_snapshot",
    ):
        op.drop_column("debate_participants", column)
