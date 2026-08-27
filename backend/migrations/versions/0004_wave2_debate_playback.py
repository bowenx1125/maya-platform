"""Wave 2 Debate setup, immutable turn plan and playback state.

The migration is intentionally additive.  Existing Wave 0/1 rows are copied
by SQLite's batch ALTER only when a new nullable column or a restrictive
foreign key is required; no existing voice, agent or knowledge value is
rewritten.  The typed audio-swap columns are nullable for the old journal
rows and are populated before a Debate start performs any filesystem rename.

Revision ID: 0004_wave2_debate_playback
Revises: 0003_wave1b_avatar_voice
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_wave2_debate_playback"
down_revision = "0003_wave1b_avatar_voice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "debates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("topic", sa.Text, nullable=False),
        sa.Column("rule_set_id", sa.String(100), nullable=False),
        sa.Column("rule_snapshot_json", sa.Text, nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_sequence", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cancellation_generation", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_duration_seconds", sa.Integer, nullable=True),
        sa.Column("turn_duration_seconds", sa.Integer, nullable=True),
        sa.ForeignKeyConstraint(
            ["course_id"], ["courses.id"], name="fk_debates_course", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_debates_creator", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("id", "course_id", name="uq_debates_id_course"),
        sa.CheckConstraint(
            "status IN ('draft', 'running', 'debate_finished', 'completed', 'failed', 'stopped')",
            name="ck_debates_status",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_debates_revision_nonnegative"),
        sa.CheckConstraint("last_sequence >= 0", name="ck_debates_sequence_nonnegative"),
        sa.CheckConstraint(
            "cancellation_generation >= 0", name="ck_debates_cancellation_nonnegative"
        ),
        sa.CheckConstraint(
            "total_duration_seconds IS NULL", name="ck_debates_total_duration_demo_null"
        ),
        sa.CheckConstraint(
            "turn_duration_seconds IS NULL", name="ck_debates_turn_duration_demo_null"
        ),
    )
    op.create_index("ix_debates_course", "debates", ["course_id"], unique=False)
    op.create_index("ix_debates_course_status", "debates", ["course_id", "status"], unique=False)
    op.create_index(
        "uq_debates_one_running_per_course",
        "debates",
        ["course_id"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )

    # SQLite requires a unique parent key for every composite relationship.
    # These indexes are additive identity keys; the original primary keys and
    # Wave 0/1 uniqueness constraints remain unchanged.
    op.create_index("uq_groups_id_course", "groups", ["id", "course_id"], unique=True)
    op.create_index("uq_agents_id_group", "agents", ["id", "group_id"], unique=True)
    op.create_index(
        "uq_agent_versions_id_agent_snapshot",
        "agent_versions",
        ["id", "agent_id", "knowledge_snapshot_id"],
        unique=True,
    )
    op.create_index(
        "uq_knowledge_snapshots_id_agent_version",
        "knowledge_snapshots",
        ["id", "agent_version_id"],
        unique=True,
    )
    op.create_index(
        "uq_knowledge_chunks_id_snapshot",
        "knowledge_chunks",
        ["id", "snapshot_id"],
        unique=True,
    )

    op.create_table(
        "debate_participants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("debate_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("group_id", sa.String(36), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("agent_version_id", sa.String(36), nullable=False),
        sa.Column("knowledge_snapshot_id", sa.String(36), nullable=False),
        sa.Column("slot", sa.String(1), nullable=False),
        sa.Column("order_index", sa.Integer, nullable=False),
        sa.Column("agent_name", sa.String(240), nullable=False),
        sa.Column("version_label", sa.String(32), nullable=False),
        sa.Column("avatar_config_json", sa.Text, nullable=False),
        sa.Column("requested_voice_profile_id", sa.String(36), nullable=True),
        sa.Column("effective_voice_kind", sa.String(24), nullable=False),
        sa.Column("effective_voice_profile_id", sa.String(36), nullable=True),
        sa.Column("voice_fallback_active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("stance_mode", sa.String(16), nullable=False),
        sa.Column("initial_stance", sa.String(16), nullable=True),
        sa.Column("current_stance", sa.String(16), nullable=True),
        sa.Column("teacher_note", sa.Text, nullable=False, server_default=""),
        sa.Column("initial_position_summary", sa.Text, nullable=False, server_default=""),
        sa.Column("current_position_summary", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["debate_id", "course_id"],
            ["debates.id", "debates.course_id"],
            name="fk_debate_participants_debate_course",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "course_id"],
            ["groups.id", "groups.course_id"],
            name="fk_debate_participants_group_course",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "group_id"],
            ["agents.id", "agents.group_id"],
            name="fk_debate_participants_agent_group",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id", "agent_id", "knowledge_snapshot_id"],
            [
                "agent_versions.id",
                "agent_versions.agent_id",
                "agent_versions.knowledge_snapshot_id",
            ],
            name="fk_debate_participants_version_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_snapshot_id", "agent_version_id"],
            ["knowledge_snapshots.id", "knowledge_snapshots.agent_version_id"],
            name="fk_debate_participants_snapshot_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_voice_profile_id"],
            ["voice_profiles.id"],
            name="fk_debate_participants_requested_voice",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["effective_voice_profile_id"],
            ["voice_profiles.id"],
            name="fk_debate_participants_effective_voice",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("debate_id", "slot", name="uq_debate_participants_debate_slot"),
        sa.UniqueConstraint("debate_id", "order_index", name="uq_debate_participants_debate_order"),
        sa.UniqueConstraint("debate_id", "agent_id", name="uq_debate_participants_debate_agent"),
        sa.UniqueConstraint(
            "debate_id", "agent_version_id", name="uq_debate_participants_debate_version"
        ),
        sa.UniqueConstraint("id", "debate_id", name="uq_debate_participants_id_debate"),
        sa.UniqueConstraint(
            "id", "knowledge_snapshot_id", name="uq_debate_participants_id_snapshot"
        ),
        sa.CheckConstraint("slot IN ('A', 'B', 'C', 'D', 'E')", name="ck_debate_participants_slot"),
        sa.CheckConstraint(
            "order_index >= 0 AND order_index <= 4", name="ck_debate_participants_order"
        ),
        sa.CheckConstraint(
            "slot = char(65 + order_index)", name="ck_debate_participants_slot_order"
        ),
        sa.CheckConstraint(
            "stance_mode IN ('assigned', 'open')", name="ck_debate_participants_stance_mode"
        ),
        sa.CheckConstraint(
            "(stance_mode = 'assigned' AND initial_stance IN ('support', 'oppose', 'neutral') "
            "AND current_stance IN ('support', 'oppose', 'neutral')) OR "
            "(stance_mode = 'open' AND initial_stance IS NULL AND current_stance IS NULL)",
            name="ck_debate_participants_stance_shape",
        ),
        sa.CheckConstraint(
            "effective_voice_kind IN ('platform_profile', 'mock_sentinel')",
            name="ck_debate_participants_voice_kind",
        ),
        sa.CheckConstraint(
            "(effective_voice_kind = 'mock_sentinel' AND effective_voice_profile_id IS NULL) OR "
            "(effective_voice_kind = 'platform_profile' "
            "AND effective_voice_profile_id IS NOT NULL)",
            name="ck_debate_participants_voice_shape",
        ),
    )
    op.create_index(
        "ix_debate_participants_debate_order",
        "debate_participants",
        ["debate_id", "order_index"],
        unique=False,
    )

    op.create_table(
        "debate_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("debate_id", sa.String(36), nullable=False),
        sa.Column("participant_id", sa.String(36), nullable=False),
        sa.Column("knowledge_snapshot_id", sa.String(36), nullable=False),
        sa.Column("round_no", sa.Integer, nullable=False),
        sa.Column("turn_index", sa.Integer, nullable=False),
        sa.Column("generation_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "publication_status", sa.String(16), nullable=False, server_default="unpublished"
        ),
        sa.Column("preparation_stage", sa.String(16), nullable=False, server_default="generation"),
        sa.Column("speech", sa.Text, nullable=True),
        sa.Column("structured_json", sa.Text, nullable=True),
        sa.Column("predecessor_turn_ids_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("transcript_hash", sa.String(64), nullable=True),
        sa.Column("cutoff_turn_index", sa.Integer, nullable=True),
        sa.Column("retrieval_status", sa.String(16), nullable=True),
        sa.Column("grounding_mode", sa.String(24), nullable=True),
        sa.Column("retrieval_receipts_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("word_count", sa.Integer, nullable=True),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        sa.Column("audio_file_id", sa.String(36), nullable=True),
        sa.Column("audio_duration_ms", sa.Integer, nullable=True),
        sa.Column("actual_tts_voice_kind", sa.String(24), nullable=True),
        sa.Column("actual_tts_voice_profile_id", sa.String(36), nullable=True),
        sa.Column("safe_error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("public_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["participant_id", "debate_id"],
            ["debate_participants.id", "debate_participants.debate_id"],
            name="fk_debate_turns_participant_debate",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id", "knowledge_snapshot_id"],
            ["debate_participants.id", "debate_participants.knowledge_snapshot_id"],
            name="fk_debate_turns_participant_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["audio_file_id"],
            ["stored_files.id"],
            name="fk_debate_turns_audio_file",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actual_tts_voice_profile_id"],
            ["voice_profiles.id"],
            name="fk_debate_turns_actual_voice_profile",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("debate_id", "turn_index", name="uq_debate_turns_debate_index"),
        sa.UniqueConstraint("id", "participant_id", name="uq_debate_turns_id_participant"),
        sa.UniqueConstraint("id", "debate_id", name="uq_debate_turns_id_debate"),
        sa.CheckConstraint("round_no >= 1 AND round_no <= 2", name="ck_debate_turns_round"),
        sa.CheckConstraint("turn_index >= 0", name="ck_debate_turns_index"),
        sa.CheckConstraint(
            "generation_status IN "
            "('pending', 'running', 'final_ready', 'failed', 'turn_generation_failed')",
            name="ck_debate_turns_generation_status",
        ),
        sa.CheckConstraint(
            "publication_status IN ('unpublished', 'public')",
            name="ck_debate_turns_publication_status",
        ),
        sa.CheckConstraint(
            "preparation_stage IN ('generation', 'tts', 'ready', 'failed')",
            name="ck_debate_turns_preparation_stage",
        ),
        sa.CheckConstraint(
            "retrieval_status IS NULL OR retrieval_status IN ('matched', 'no_match')",
            name="ck_debate_turns_retrieval_status",
        ),
        sa.CheckConstraint(
            "grounding_mode IS NULL OR grounding_mode IN "
            "('rag_grounded', 'mixed', 'general_reasoning')",
            name="ck_debate_turns_grounding_mode",
        ),
        sa.CheckConstraint(
            "word_count IS NULL OR (word_count >= 80 AND word_count <= 200)",
            name="ck_debate_turns_word_count",
        ),
        sa.CheckConstraint(
            "generation_status != 'final_ready' OR "
            "(preparation_stage = 'ready' AND speech IS NOT NULL AND structured_json IS NOT NULL "
            "AND transcript_hash IS NOT NULL AND cutoff_turn_index IS NOT NULL "
            "AND retrieval_status IS NOT NULL AND grounding_mode IS NOT NULL "
            "AND word_count IS NOT NULL AND word_count >= 80 AND word_count <= 200)",
            name="ck_debate_turns_final_ready_shape",
        ),
        sa.CheckConstraint("attempt >= 1 AND attempt <= 2", name="ck_debate_turns_attempt"),
        sa.CheckConstraint(
            "audio_duration_ms IS NULL OR audio_duration_ms >= 0",
            name="ck_debate_turns_audio_duration",
        ),
        sa.CheckConstraint(
            "actual_tts_voice_kind IS NULL OR "
            "actual_tts_voice_kind IN ('platform_profile', 'mock_sentinel')",
            name="ck_debate_turns_actual_voice_kind",
        ),
        sa.CheckConstraint(
            "actual_tts_voice_kind IS NULL OR "
            "(actual_tts_voice_kind = 'mock_sentinel' AND actual_tts_voice_profile_id IS NULL) OR "
            "(actual_tts_voice_kind = 'platform_profile' "
            "AND actual_tts_voice_profile_id IS NOT NULL)",
            name="ck_debate_turns_actual_voice_shape",
        ),
    )
    op.create_index("ix_debate_turns_debate_index", "debate_turns", ["debate_id", "turn_index"])
    op.create_index("ix_debate_turns_participant", "debate_turns", ["participant_id"])
    op.create_table(
        "turn_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("turn_id", sa.String(36), nullable=False),
        sa.Column("participant_id", sa.String(36), nullable=False),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("chunk_id", sa.String(36), nullable=False),
        sa.Column("evidence_id", sa.String(128), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["turn_id", "participant_id"],
            ["debate_turns.id", "debate_turns.participant_id"],
            name="fk_turn_sources_turn_participant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id", "snapshot_id"],
            ["debate_participants.id", "debate_participants.knowledge_snapshot_id"],
            name="fk_turn_sources_participant_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id", "snapshot_id"],
            ["knowledge_chunks.id", "knowledge_chunks.snapshot_id"],
            name="fk_turn_sources_chunk_snapshot",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("turn_id", "chunk_id", name="uq_turn_sources_turn_chunk"),
        sa.UniqueConstraint("turn_id", "evidence_id", name="uq_turn_sources_turn_evidence"),
        sa.CheckConstraint("rank >= 1 AND rank <= 6", name="ck_turn_sources_rank"),
        sa.CheckConstraint("score >= 0.0 AND score <= 1.0", name="ck_turn_sources_score"),
    )
    op.create_index("ix_turn_sources_turn", "turn_sources", ["turn_id"])

    op.create_table(
        "position_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("participant_id", sa.String(36), nullable=False),
        sa.Column("turn_id", sa.String(36), nullable=False),
        sa.Column("before_summary", sa.Text, nullable=False),
        sa.Column("after_summary", sa.Text, nullable=False),
        sa.Column("update_type", sa.String(24), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("influencing_turn_id", sa.String(36), nullable=True),
        sa.Column("influencing_evidence_ids_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["turn_id", "participant_id"],
            ["debate_turns.id", "debate_turns.participant_id"],
            name="fk_position_history_turn_participant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["debate_participants.id"],
            name="fk_position_history_participant",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "update_type IN ('unchanged', 'refined', 'partial_concession', 'reframed', 'switched')",
            name="ck_position_history_update_type",
        ),
    )
    op.create_index(
        "ix_position_history_participant",
        "position_history",
        ["participant_id", "created_at"],
    )

    op.create_table(
        "playback_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("debate_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="preparing"),
        sa.Column("mode", sa.String(8), nullable=False, server_default="live"),
        sa.Column("current_turn_id", sa.String(36), nullable=True),
        sa.Column("cursor_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("playback_rate", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("control_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("controller_epoch", sa.String(128), nullable=True),
        sa.Column("controller_owner_connection", sa.String(128), nullable=True),
        sa.Column("server_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replay_scope", sa.String(8), nullable=True),
        sa.Column("replay_index", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["debate_id"], ["debates.id"], name="fk_playback_states_debate", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["current_turn_id", "debate_id"],
            ["debate_turns.id", "debate_turns.debate_id"],
            name="fk_playback_states_current_turn_debate",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("debate_id", name="uq_playback_states_debate"),
        sa.CheckConstraint(
            "status IN ('preparing', 'ready', 'playing', 'paused', 'completed', 'stopped')",
            name="ck_playback_states_status",
        ),
        sa.CheckConstraint("mode IN ('live', 'replay')", name="ck_playback_states_mode"),
        sa.CheckConstraint("cursor_ms >= 0", name="ck_playback_states_cursor"),
        sa.CheckConstraint(
            "playback_rate >= 0.95 AND playback_rate <= 1.25",
            name="ck_playback_states_rate",
        ),
        sa.CheckConstraint("control_version >= 0", name="ck_playback_states_control_version"),
        sa.CheckConstraint(
            "replay_scope IS NULL OR replay_scope IN ('turn', 'all')",
            name="ck_playback_states_replay_scope",
        ),
        sa.CheckConstraint(
            "replay_index IS NULL OR replay_index >= 0",
            name="ck_playback_states_replay_index",
        ),
    )
    op.create_index("ix_playback_states_debate_status", "playback_states", ["debate_id", "status"])

    op.create_table(
        "debate_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("debate_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("event_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["debate_id"], ["debates.id"], name="fk_debate_events_debate", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("debate_id", "sequence", name="uq_debate_events_debate_sequence"),
        sa.CheckConstraint("sequence >= 1", name="ck_debate_events_sequence"),
        sa.CheckConstraint("event_version >= 1", name="ck_debate_events_version"),
    )
    op.create_index("ix_debate_events_debate_sequence", "debate_events", ["debate_id", "sequence"])

    # Existing tables are altered only after all referenced Debate parents are
    # available.  Batch mode recreates SQLite tables while preserving every
    # existing row and named Wave 0/1 constraint.
    # ``courses`` is already referenced by groups/course_members, while the
    # new Debate table references courses in the opposite direction.  SQLite
    # cannot drop/recreate a parent table with foreign_keys enabled, so this
    # narrowly scoped metadata rebuild temporarily disables enforcement.  No
    # rows are changed and the pragma is restored before migration return.
    bind = op.get_bind()
    sqlite_fk_disabled = bind.dialect.name == "sqlite"
    if sqlite_fk_disabled:
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    with op.batch_alter_table("courses", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_courses_current_audio_debate",
            "debates",
            ["current_audio_debate_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    if sqlite_fk_disabled:
        bind.exec_driver_sql("PRAGMA foreign_keys=ON")

    with op.batch_alter_table("jobs", recreate="always") as batch:
        batch.add_column(sa.Column("debate_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("turn_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("idempotency_key", sa.String(255), nullable=True))
        batch.add_column(sa.Column("claim_token", sa.String(64), nullable=True))
        batch.add_column(sa.Column("cancellation_generation", sa.Integer, nullable=True))
        batch.create_foreign_key(
            "fk_jobs_debate", "debates", ["debate_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_foreign_key(
            "fk_jobs_turn", "debate_turns", ["turn_id"], ["id"], ondelete="CASCADE"
        )
    op.create_index("ix_jobs_debate", "jobs", ["debate_id"], unique=False)
    op.create_index("ix_jobs_turn", "jobs", ["turn_id"], unique=False)
    op.create_index(
        "uq_jobs_operation_idempotency_key",
        "jobs",
        ["operation", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )

    with op.batch_alter_table("file_operations", recreate="always") as batch:
        batch.add_column(sa.Column("old_audio_debate_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("staging_relative_path", sa.String(500), nullable=True))
        batch.add_column(sa.Column("new_debate_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("expected_old_debate_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_file_operations_old_audio_debate",
            "debates",
            ["old_audio_debate_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_file_operations_new_debate",
            "debates",
            ["new_debate_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    op.drop_index("uq_jobs_operation_idempotency_key", table_name="jobs")
    op.drop_index("ix_jobs_turn", table_name="jobs")
    op.drop_index("ix_jobs_debate", table_name="jobs")
    with op.batch_alter_table("jobs", recreate="always") as batch:
        batch.drop_constraint("fk_jobs_turn", type_="foreignkey")
        batch.drop_constraint("fk_jobs_debate", type_="foreignkey")
        batch.drop_column("cancellation_generation")
        batch.drop_column("claim_token")
        batch.drop_column("idempotency_key")
        batch.drop_column("turn_id")
        batch.drop_column("debate_id")

    with op.batch_alter_table("file_operations", recreate="always") as batch:
        batch.drop_constraint("fk_file_operations_new_debate", type_="foreignkey")
        batch.drop_constraint("fk_file_operations_old_audio_debate", type_="foreignkey")
        batch.drop_column("expected_old_debate_id")
        batch.drop_column("new_debate_id")
        batch.drop_column("staging_relative_path")
        batch.drop_column("old_audio_debate_id")

    with op.batch_alter_table("courses", recreate="always") as batch:
        batch.drop_constraint("fk_courses_current_audio_debate", type_="foreignkey")

    op.drop_index("ix_debate_events_debate_sequence", table_name="debate_events")
    op.drop_table("debate_events")
    op.drop_index("ix_playback_states_debate_status", table_name="playback_states")
    op.drop_table("playback_states")
    op.drop_index("ix_position_history_participant", table_name="position_history")
    op.drop_table("position_history")
    op.drop_index("ix_turn_sources_turn", table_name="turn_sources")
    op.drop_table("turn_sources")
    op.drop_index("ix_debate_turns_participant", table_name="debate_turns")
    op.drop_index("ix_debate_turns_debate_index", table_name="debate_turns")
    op.drop_table("debate_turns")
    op.drop_index("ix_debate_participants_debate_order", table_name="debate_participants")
    op.drop_table("debate_participants")
    op.drop_index("uq_knowledge_chunks_id_snapshot", table_name="knowledge_chunks")
    op.drop_index("uq_knowledge_snapshots_id_agent_version", table_name="knowledge_snapshots")
    op.drop_index("uq_agent_versions_id_agent_snapshot", table_name="agent_versions")
    op.drop_index("uq_agents_id_group", table_name="agents")
    op.drop_index("uq_groups_id_course", table_name="groups")
    op.drop_index("uq_debates_one_running_per_course", table_name="debates")
    op.drop_index("ix_debates_course_status", table_name="debates")
    op.drop_index("ix_debates_course", table_name="debates")
    op.drop_table("debates")
