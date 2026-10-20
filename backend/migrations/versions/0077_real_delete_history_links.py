"""Let history outlive the Agent, version, file or voice it came from.

Real deletion (2026-10-20): hard-deleting an Agent version, a RAG file or a
Voice must not fail on, or erase, history that referenced it.

* History/lineage links become nullable ``ON DELETE SET NULL``.
* Pure dependents (a version's file binding, a file's edit history, a voice's
  provider operations, an Agent's account memories) ``CASCADE``.
* Debates own their copies: ``debate_participants`` gains ``agent_md_snapshot``
  and a voice snapshot, backfilled here, and drops the composite FKs that
  pinned it to live ``agent_versions`` rows. The knowledge snapshot link stays
  RESTRICT; pruning never removes a snapshot a Debate uses.

Left RESTRICT on purpose: assessment provenance (activities, grants, boundary
revisions) and ``agent_conversations`` (CHECK requires its version; chat
deletion is #230's migration). Pruning skips versions those rows reference.

The FK work is PostgreSQL-only (SQLite tests build from the models).

Revision ID: 0077_real_delete_history_links
Revises: 0076_agent_editor_audit (#229) <- 0075_answer_guard_state (#225) <- 0074

Migration chain (planned, linear): #225 = 0075_answer_guard_state,
#229 = 0076_agent_editor_audit, this = 0077, chat hard-delete = 0078.
Until #225/#229 land, down_revision falls back to the newest one present, so
this stack runs on its own. Deploy in that order (225 -> 229 -> this).
Create Date: 2026-10-20
"""

from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0077_real_delete_history_links"
_PARENTS = ("0076_agent_editor_audit", "0075_answer_guard_state", "0074_interaction_voter_key")
down_revision: str | Sequence[str] | None = next(
    name for name in _PARENTS if (Path(__file__).parent / f"{name}.py").exists()
)
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
        'provider_key', vp.provider_key,
        'scope', vp.scope,
        'target_model_key', vp.target_model_key,
        'voice_profile_id', vp.id
    )::text,
    voice_external_id_encrypted = vp.external_id_encrypted
FROM voice_profiles AS vp
WHERE vp.id = p.effective_voice_profile_id AND p.voice_snapshot_json IS NULL
"""


def upgrade() -> None:
    op.add_column("debate_participants", sa.Column("agent_md_snapshot", sa.Text(), nullable=True))
    op.add_column("debate_participants", sa.Column("voice_snapshot_json", sa.Text(), nullable=True))
    op.add_column(
        "debate_participants",
        sa.Column("voice_external_id_encrypted", sa.LargeBinary(), nullable=True),
    )
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(_BACKFILL_AGENT_MD)
    op.execute(_BACKFILL_VOICE)

    for name in _DEBATE_COMPOSITES:
        op.execute(f"ALTER TABLE debate_participants DROP CONSTRAINT IF EXISTS {name}")
    op.execute("ALTER TABLE debate_participants ALTER COLUMN agent_id DROP NOT NULL")
    op.execute("ALTER TABLE debate_participants ALTER COLUMN agent_version_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE debate_participants ADD CONSTRAINT fk_debate_participants_agent "
        "FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE debate_participants ADD CONSTRAINT fk_debate_participants_agent_version "
        "FOREIGN KEY (agent_version_id) REFERENCES agent_versions(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE debate_participants ADD CONSTRAINT fk_debate_participants_snapshot "
        "FOREIGN KEY (knowledge_snapshot_id) REFERENCES knowledge_snapshots(id) "
        "ON DELETE RESTRICT"
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
    # Restoring RESTRICT/NOT NULL would fail once rows were really deleted;
    # like 0066 this migration is forward-only on PostgreSQL.
    op.drop_column("debate_participants", "voice_external_id_encrypted")
    op.drop_column("debate_participants", "voice_snapshot_json")
    op.drop_column("debate_participants", "agent_md_snapshot")
