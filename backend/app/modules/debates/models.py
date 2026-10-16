"""Debate setup and playback persistence models.

The debate tables live in this module instead of the shared core model file so
the Wave 0/1 domain remains usable by isolated tests and migration tooling.
All identifiers are platform UUID strings.  Provider identifiers and raw
provider responses are intentionally absent from these models.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import (
    Agent,
    AgentVersion,
    Base,
    Course,
    FileOperation,
    Group,
    Job,
    KnowledgeChunk,
    KnowledgeSnapshot,
)
from app.core.sqlutil import portable_sql

# These parent keys are required by SQLite before it will accept the exact
# cross-scope foreign keys below.  They are declared here as metadata indexes
# for ``create_all``-based isolated tests; migration 0004 creates the same
# named indexes explicitly for existing databases.
Index("uq_groups_id_course", Group.id, Group.course_id, unique=True)
Index("uq_agents_id_group", Agent.id, Agent.group_id, unique=True)
Index(
    "uq_agent_versions_id_agent_snapshot",
    AgentVersion.id,
    AgentVersion.agent_id,
    AgentVersion.knowledge_snapshot_id,
    unique=True,
)
Index(
    "uq_knowledge_snapshots_id_agent_version",
    KnowledgeSnapshot.id,
    KnowledgeSnapshot.agent_version_id,
    unique=True,
)
Index("uq_knowledge_chunks_id_snapshot", KnowledgeChunk.id, KnowledgeChunk.snapshot_id, unique=True)

# The shared ORM models intentionally stay importable for pre-Wave-2
# ``create_all`` tests.  Once this module is imported, append the same
# nullable relationships that migration 0004 adds to the live tables.
cast(Table, Course.__table__).append_constraint(
    ForeignKeyConstraint(
        ["current_audio_debate_id"],
        ["debates.id"],
        name="fk_courses_current_audio_debate",
        ondelete="RESTRICT",
    )
)
cast(Table, Job.__table__).append_constraint(
    ForeignKeyConstraint(["debate_id"], ["debates.id"], name="fk_jobs_debate", ondelete="CASCADE")
)
cast(Table, Job.__table__).append_constraint(
    ForeignKeyConstraint(["turn_id"], ["debate_turns.id"], name="fk_jobs_turn", ondelete="CASCADE")
)
cast(Table, FileOperation.__table__).append_constraint(
    ForeignKeyConstraint(
        ["old_audio_debate_id"],
        ["debates.id"],
        name="fk_file_operations_old_audio_debate",
        ondelete="RESTRICT",
    )
)
cast(Table, FileOperation.__table__).append_constraint(
    ForeignKeyConstraint(
        ["new_debate_id"],
        ["debates.id"],
        name="fk_file_operations_new_debate",
        ondelete="RESTRICT",
    )
)


class Debate(Base):
    """An immutable-rule debate draft or run owned by one course."""

    __tablename__ = "debates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    background: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    rule_set_id: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    # Chosen before Preview generation; playback cannot change saved speech.
    output_language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    final_input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    final_frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancellation_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A retired Debate keeps its record but leaves the list, its page and Live.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The Demo deliberately does not expose hard duration controls.  Keeping
    # nullable compatibility columns makes the frozen rule snapshot explicit.
    total_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    turn_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["course_id"], ["courses.id"], name="fk_debates_course", ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_debates_creator", ondelete="RESTRICT"
        ),
        UniqueConstraint("id", "course_id", name="uq_debates_id_course"),
        CheckConstraint(
            "status IN ('draft', 'running', 'debate_finished', 'completed', 'failed', 'stopped')",
            name="ck_debates_status",
        ),
        CheckConstraint("revision >= 0", name="ck_debates_revision_nonnegative"),
        CheckConstraint("last_sequence >= 0", name="ck_debates_sequence_nonnegative"),
        CheckConstraint("cancellation_generation >= 0", name="ck_debates_cancellation_nonnegative"),
        CheckConstraint(
            "total_duration_seconds IS NULL", name="ck_debates_total_duration_demo_null"
        ),
        CheckConstraint("turn_duration_seconds IS NULL", name="ck_debates_turn_duration_demo_null"),
        Index("ix_debates_course", "course_id"),
        Index("ix_debates_course_status", "course_id", "status"),
        Index(
            "uq_debates_one_running_per_course",
            "course_id",
            unique=True,
            sqlite_where=(status == "running") & deleted_at.is_(None),
            postgresql_where=(status == "running") & deleted_at.is_(None),
        ),
    )


class DebateParticipant(Base):
    """Frozen Agent/version/snapshot display and voice decision for a debate."""

    __tablename__ = "debate_participants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # NULL for a teacher's personal Agent, which belongs to no group.
    group_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    knowledge_snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    slot: Mapped[str] = mapped_column(String(1), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(240), nullable=False)
    version_label: Mapped[str] = mapped_column(String(32), nullable=False)
    avatar_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    requested_voice_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    effective_voice_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    effective_voice_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    voice_fallback_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stance_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    initial_stance: Mapped[str | None] = mapped_column(String(16), nullable=True)
    current_stance: Mapped[str | None] = mapped_column(String(16), nullable=True)
    teacher_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    initial_position_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    current_position_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["debate_id", "course_id"],
            ["debates.id", "debates.course_id"],
            name="fk_debate_participants_debate_course",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["group_id", "course_id"],
            ["groups.id", "groups.course_id"],
            name="fk_debate_participants_group_course",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agent_id", "group_id"],
            ["agents.id", "agents.group_id"],
            name="fk_debate_participants_agent_group",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agent_version_id", "agent_id", "knowledge_snapshot_id"],
            [
                "agent_versions.id",
                "agent_versions.agent_id",
                "agent_versions.knowledge_snapshot_id",
            ],
            name="fk_debate_participants_version_snapshot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["knowledge_snapshot_id", "agent_version_id"],
            ["knowledge_snapshots.id", "knowledge_snapshots.agent_version_id"],
            name="fk_debate_participants_snapshot_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["requested_voice_profile_id"],
            ["voice_profiles.id"],
            name="fk_debate_participants_requested_voice",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["effective_voice_profile_id"],
            ["voice_profiles.id"],
            name="fk_debate_participants_effective_voice",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("debate_id", "slot", name="uq_debate_participants_debate_slot"),
        UniqueConstraint("debate_id", "order_index", name="uq_debate_participants_debate_order"),
        UniqueConstraint("debate_id", "agent_id", name="uq_debate_participants_debate_agent"),
        UniqueConstraint(
            "debate_id", "agent_version_id", name="uq_debate_participants_debate_version"
        ),
        UniqueConstraint("id", "debate_id", name="uq_debate_participants_id_debate"),
        UniqueConstraint("id", "knowledge_snapshot_id", name="uq_debate_participants_id_snapshot"),
        CheckConstraint("slot IN ('A', 'B', 'C', 'D', 'E')", name="ck_debate_participants_slot"),
        CheckConstraint(
            "order_index >= 0 AND order_index <= 4", name="ck_debate_participants_order"
        ),
        CheckConstraint(
            portable_sql(
                "slot = char(65 + order_index)",
                "slot = chr(65 + order_index)",
            ),
            name="ck_debate_participants_slot_order",
        ),
        CheckConstraint(
            "stance_mode IN ('assigned', 'open')", name="ck_debate_participants_stance_mode"
        ),
        CheckConstraint(
            "(stance_mode = 'assigned' AND initial_stance IN ('support', 'oppose', 'neutral') "
            "AND current_stance IN ('support', 'oppose', 'neutral')) OR "
            "(stance_mode = 'open' AND initial_stance IS NULL AND current_stance IS NULL)",
            name="ck_debate_participants_stance_shape",
        ),
        CheckConstraint(
            "effective_voice_kind IN ('platform_profile', 'mock_sentinel')",
            name="ck_debate_participants_voice_kind",
        ),
        CheckConstraint(
            "(effective_voice_kind = 'mock_sentinel' AND effective_voice_profile_id IS NULL) OR "
            "(effective_voice_kind = 'platform_profile' "
            "AND effective_voice_profile_id IS NOT NULL)",
            name="ck_debate_participants_voice_shape",
        ),
        Index("ix_debate_participants_debate_order", "debate_id", "order_index"),
    )


class DebateTurn(Base):
    """A planned turn and its immutable final-ready generation result."""

    __tablename__ = "debate_turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    participant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    knowledge_snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    publication_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unpublished"
    )
    preparation_stage: Mapped[str] = mapped_column(String(16), nullable=False, default="generation")
    speech: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    predecessor_turn_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    transcript_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cutoff_turn_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retrieval_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    grounding_mode: Mapped[str | None] = mapped_column(String(24), nullable=True)
    retrieval_receipts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    evidence_trace_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    audio_file_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    audio_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_tts_voice_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    actual_tts_voice_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    public_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["participant_id", "debate_id"],
            ["debate_participants.id", "debate_participants.debate_id"],
            name="fk_debate_turns_participant_debate",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["participant_id", "knowledge_snapshot_id"],
            ["debate_participants.id", "debate_participants.knowledge_snapshot_id"],
            name="fk_debate_turns_participant_snapshot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["audio_file_id"],
            ["stored_files.id"],
            name="fk_debate_turns_audio_file",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actual_tts_voice_profile_id"],
            ["voice_profiles.id"],
            name="fk_debate_turns_actual_voice_profile",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("debate_id", "turn_index", name="uq_debate_turns_debate_index"),
        UniqueConstraint("id", "participant_id", name="uq_debate_turns_id_participant"),
        UniqueConstraint("id", "debate_id", name="uq_debate_turns_id_debate"),
        CheckConstraint("round_no >= 1", name="ck_debate_turns_round"),
        CheckConstraint("turn_index >= 0", name="ck_debate_turns_index"),
        CheckConstraint(
            "generation_status IN "
            "('pending', 'running', 'final_ready', 'failed', 'turn_generation_failed')",
            name="ck_debate_turns_generation_status",
        ),
        CheckConstraint(
            "publication_status IN ('unpublished', 'public')",
            name="ck_debate_turns_publication_status",
        ),
        CheckConstraint(
            "preparation_stage IN ('generation', 'tts', 'ready', 'failed')",
            name="ck_debate_turns_preparation_stage",
        ),
        CheckConstraint(
            "retrieval_status IS NULL OR retrieval_status IN ('matched', 'no_match')",
            name="ck_debate_turns_retrieval_status",
        ),
        CheckConstraint(
            "grounding_mode IS NULL OR grounding_mode IN "
            "('rag_grounded', 'mixed', 'general_reasoning')",
            name="ck_debate_turns_grounding_mode",
        ),
        CheckConstraint(
            "word_count IS NULL OR (word_count >= 80 AND word_count <= 200) OR "
            "(json_extract(structured_json, '$.schema_version') = 'segment_turn_v2' "
            "AND word_count >= 0)",
            name="ck_debate_turns_word_count",
        ),
        CheckConstraint(
            "generation_status != 'final_ready' OR "
            "(preparation_stage = 'ready' AND speech IS NOT NULL AND structured_json IS NOT NULL "
            "AND transcript_hash IS NOT NULL AND cutoff_turn_index IS NOT NULL "
            "AND retrieval_status IS NOT NULL AND grounding_mode IS NOT NULL "
            "AND word_count IS NOT NULL AND "
            "((word_count >= 80 AND word_count <= 200) OR "
            "(json_extract(structured_json, '$.schema_version') = 'segment_turn_v2' "
            "AND word_count >= 0)))",
            name="ck_debate_turns_final_ready_shape",
        ),
        CheckConstraint("attempt >= 1 AND attempt <= 2", name="ck_debate_turns_attempt"),
        CheckConstraint(
            "audio_duration_ms IS NULL OR audio_duration_ms >= 0",
            name="ck_debate_turns_audio_duration",
        ),
        CheckConstraint(
            "actual_tts_voice_kind IS NULL OR actual_tts_voice_kind IN "
            "('platform_profile', 'mock_sentinel')",
            name="ck_debate_turns_actual_voice_kind",
        ),
        CheckConstraint(
            "actual_tts_voice_kind IS NULL OR "
            "(actual_tts_voice_kind = 'mock_sentinel' AND actual_tts_voice_profile_id IS NULL) OR "
            "(actual_tts_voice_kind = 'platform_profile' "
            "AND actual_tts_voice_profile_id IS NOT NULL)",
            name="ck_debate_turns_actual_voice_shape",
        ),
        Index("ix_debate_turns_debate_index", "debate_id", "turn_index"),
        Index("ix_debate_turns_participant", "participant_id"),
    )


class TurnSource(Base):
    """A server-selected receipt actually used by a final-ready turn."""

    __tablename__ = "turn_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    turn_id: Mapped[str] = mapped_column(String(36), nullable=False)
    participant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    chunk_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Receipt identities are scoped to a request and may be reused by later
    # turns; the database uniqueness is therefore turn-local, not global.
    evidence_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["turn_id", "participant_id"],
            ["debate_turns.id", "debate_turns.participant_id"],
            name="fk_turn_sources_turn_participant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["chunk_id", "snapshot_id"],
            ["knowledge_chunks.id", "knowledge_chunks.snapshot_id"],
            name="fk_turn_sources_chunk_snapshot",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("turn_id", "chunk_id", name="uq_turn_sources_turn_chunk"),
        UniqueConstraint("turn_id", "evidence_id", name="uq_turn_sources_turn_evidence"),
        CheckConstraint("rank >= 1 AND rank <= 6", name="ck_turn_sources_rank"),
        CheckConstraint("score >= 0.0 AND score <= 1.0", name="ck_turn_sources_score"),
        Index("ix_turn_sources_turn", "turn_id"),
    )


class PositionHistory(Base):
    """An immutable explanation for a participant position update."""

    __tablename__ = "position_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    participant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    turn_id: Mapped[str] = mapped_column(String(36), nullable=False)
    before_summary: Mapped[str] = mapped_column(Text, nullable=False)
    after_summary: Mapped[str] = mapped_column(Text, nullable=False)
    update_type: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    influencing_turn_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    influencing_evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["participant_id"],
            ["debate_participants.id"],
            name="fk_position_history_participant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["turn_id", "participant_id"],
            ["debate_turns.id", "debate_turns.participant_id"],
            name="fk_position_history_turn_participant",
            ondelete="CASCADE",
        ),
        # ``influencing_turn_id`` intentionally has no participant FK: an
        # opponent's turn is a valid influence.  The setup service validates
        # that it belongs to the same Debate; the exact update turn above is
        # the ownership relationship that must be enforced by SQLite.
        CheckConstraint(
            "update_type IN ('unchanged', 'refined', 'partial_concession', 'reframed', 'switched')",
            name="ck_position_history_update_type",
        ),
        Index("ix_position_history_participant", "participant_id", "created_at"),
    )


class PlaybackState(Base):
    """One authoritative live/replay playback state per Debate."""

    __tablename__ = "playback_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="preparing")
    mode: Mapped[str] = mapped_column(String(8), nullable=False, default="live")
    current_turn_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cursor_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    playback_rate: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    control_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    controller_epoch: Mapped[str | None] = mapped_column(String(128), nullable=True)
    controller_owner_connection: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pending_action: Mapped[str | None] = mapped_column(String(8), nullable=True)
    pending_ticket_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_media_command_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    audio_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    server_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replay_scope: Mapped[str | None] = mapped_column(String(8), nullable=True)
    replay_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The whole-replay cursor is persisted so a process restart cannot fall
    # back to an in-memory list and accidentally skip the teacher's Next gate.
    # Migration 0006 adds this nullable compatibility column to existing
    # playback rows; an empty value is treated as an empty queue and rebuilt
    # only from the immutable public prefix by the playback service.
    replay_turn_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["debate_id"], ["debates.id"], name="fk_playback_states_debate", ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["current_turn_id", "debate_id"],
            ["debate_turns.id", "debate_turns.debate_id"],
            name="fk_playback_states_current_turn_debate",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("debate_id", name="uq_playback_states_debate"),
        CheckConstraint(
            "status IN ('preparing', 'ready', 'playing', 'paused', 'waiting_next', "
            "'completed', 'stopped')",
            name="ck_playback_states_status",
        ),
        CheckConstraint(
            "status != 'waiting_next' OR "
            "(current_turn_id IS NOT NULL AND ((mode = 'live' "
            "AND replay_scope IS NULL AND replay_index IS NULL) OR "
            "(mode = 'replay' AND replay_scope = 'all' "
            "AND replay_index IS NOT NULL AND replay_index >= 0)))",
            name="ck_playback_states_waiting_next_mode",
        ),
        CheckConstraint("mode IN ('live', 'replay')", name="ck_playback_states_mode"),
        CheckConstraint(
            "pending_action IS NULL OR pending_action IN ('start', 'resume', 'next', 'replay')",
            name="ck_playback_states_pending_action",
        ),
        CheckConstraint(
            "audio_duration_ms >= 0",
            name="ck_playback_states_audio_duration",
        ),
        CheckConstraint("cursor_ms >= 0", name="ck_playback_states_cursor"),
        CheckConstraint(
            "playback_rate >= 0.95 AND playback_rate <= 1.25",
            name="ck_playback_states_rate",
        ),
        CheckConstraint("control_version >= 0", name="ck_playback_states_control_version"),
        CheckConstraint(
            "replay_scope IS NULL OR replay_scope IN ('turn', 'all')",
            name="ck_playback_states_replay_scope",
        ),
        CheckConstraint(
            "replay_index IS NULL OR replay_index >= 0",
            name="ck_playback_states_replay_index",
        ),
        Index("ix_playback_states_debate_status", "debate_id", "status"),
    )


class DebateEvent(Base):
    """A committed, sequenced, server-authored event envelope."""

    __tablename__ = "debate_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    debate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["debate_id"], ["debates.id"], name="fk_debate_events_debate", ondelete="CASCADE"
        ),
        UniqueConstraint("debate_id", "sequence", name="uq_debate_events_debate_sequence"),
        CheckConstraint("sequence >= 1", name="ck_debate_events_sequence"),
        CheckConstraint("event_version >= 1", name="ck_debate_events_version"),
        Index("ix_debate_events_debate_sequence", "debate_id", "sequence"),
    )


class AuditLog(Base):
    """Generic redacted audit envelope used by operator-only boundaries.

    Audit rows deliberately carry no foreign keys: an audit trail survives
    cleanup of the debated entity and remains usable by later domains.  The
    playback reset writer fills only the event/debate/request identity and a
    small allow-listed ``details_json`` object; provider, path, ticket and
    controller-epoch material never belongs in this table.
    """

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    course_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    debate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "length(trim(event_type)) > 0",
            name="ck_audit_logs_event_type_nonempty",
        ),
        CheckConstraint(
            "length(trim(details_json)) > 0",
            name="ck_audit_logs_details_nonempty",
        ),
        Index("ix_audit_logs_debate_created", "debate_id", "created_at"),
        Index("ix_audit_logs_event_created", "event_type", "created_at"),
    )


# Names used by the business contract and by downstream Wave 2 modules.  The
# aliases keep the SQL table names singular in one place while allowing the
# public domain vocabulary to remain explicit.
DebatePositionHistory = PositionHistory
DebatePlaybackState = PlaybackState


__all__ = [
    "Base",
    "AuditLog",
    "Debate",
    "DebateEvent",
    "DebateParticipant",
    "DebatePlaybackState",
    "DebatePositionHistory",
    "DebateTurn",
    "PlaybackState",
    "PositionHistory",
    "TurnSource",
]
