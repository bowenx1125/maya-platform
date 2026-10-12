from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class Conversation(Base):
    __tablename__ = "agent_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    agent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=True
    )
    snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_snapshots.id", ondelete="RESTRICT"), nullable=True
    )
    agent_name_snapshot: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    agent_authorization_epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    entry_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="agent", server_default="agent"
    )
    chat_visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="private", server_default="private"
    )
    origin: Mapped[str] = mapped_column(
        String(32), nullable=False, default="single_agent", server_default="single_agent"
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=True
    )
    team_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    team_owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    team_name_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    team_authorization_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publication_id: Mapped[str | None] = mapped_column(
        ForeignKey("course_team_publications.id", ondelete="RESTRICT"), nullable=True
    )
    publication_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    active_request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The owner's own name for the Chat; empty keeps the automatic one.
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("revision >= 0"),
        CheckConstraint("agent_authorization_epoch >= 0"),
        CheckConstraint(
            "chat_visibility IN ('private', 'public')", name="ck_conversations_privacy"
        ),
        CheckConstraint(
            "(entry_kind = 'agent' AND origin = 'single_agent' AND agent_version_id IS NOT NULL "
            "AND team_id IS NULL AND team_version_id IS NULL AND team_owner_user_id IS NULL "
            "AND team_name_snapshot IS NULL AND team_authorization_epoch IS NULL "
            "AND publication_id IS NULL AND publication_epoch IS NULL) OR "
            "(entry_kind IN ('team', 'maya_team') AND agent_version_id IS NULL AND "
            "snapshot_id IS NULL "
            "AND team_id IS NOT NULL AND team_version_id IS NOT NULL AND "
            "team_owner_user_id IS NOT NULL "
            "AND team_name_snapshot IS NOT NULL AND team_authorization_epoch IS NOT NULL "
            "AND team_authorization_epoch >= 0 AND "
            "((entry_kind = 'team' AND origin = 'custom_team' AND publication_id IS"
            " NULL AND publication_epoch IS NULL) OR "
            "(entry_kind = 'maya_team' AND origin = 'published_course_team' AND "
            "publication_id IS NOT NULL "
            "AND publication_epoch IS NOT NULL AND publication_epoch >= 0)))",
            name="ck_conversations_entry",
        ),
        ForeignKeyConstraint(
            ["team_id", "team_version_id"],
            ["team_versions.team_id", "team_versions.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "team_version_id", name="uq_conversations_team_version"),
        Index("ix_conversations_course_privacy", "course_id", "chat_visibility", "user_id"),
    )


class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    team_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    team_member_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"))
    agent_version_id: Mapped[str] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="RESTRICT")
    )
    snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_snapshots.id", ondelete="RESTRICT"), nullable=True
    )
    agent_authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_leader: Mapped[bool] = mapped_column(Boolean, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    avatar_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    invoke_grant_id: Mapped[str | None] = mapped_column(
        ForeignKey("team_member_invoke_grants.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "team_version_id"],
            ["agent_conversations.id", "agent_conversations.team_version_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["team_version_id", "team_member_id"],
            ["team_version_members.team_version_id", "team_version_members.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "position >= 0 AND agent_authorization_epoch >= 0",
            name="ck_conversation_participant_counters",
        ),
        UniqueConstraint("id", "conversation_id", name="uq_conversation_participant_scope"),
        UniqueConstraint(
            "conversation_id", "team_member_id", name="uq_conversation_participant_member"
        ),
        UniqueConstraint(
            "conversation_id", "position", name="uq_conversation_participant_position"
        ),
        Index(
            "uq_conversation_participant_leader",
            "conversation_id",
            unique=True,
            sqlite_where=is_leader.is_(True),
            postgresql_where=is_leader.is_(True),
        ),
    )


class ConversationParticipantSet(Base):
    __tablename__ = "conversation_participant_sets"

    participant_id: Mapped[str] = mapped_column(
        ForeignKey("conversation_participants.id", ondelete="CASCADE"), primary_key=True
    )
    knowledge_set_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_sets.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_conversation_own_set_position"),
        UniqueConstraint("participant_id", "position", name="uq_conversation_own_set_position"),
    )


class ConversationSharedSet(Base):
    __tablename__ = "conversation_shared_sets"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"), primary_key=True
    )
    knowledge_set_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_sets.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_conversation_shared_set_position"),
        UniqueConstraint("conversation_id", "position", name="uq_conversation_shared_set_position"),
    )


class ConversationTurn(Base):
    __tablename__ = "agent_conversation_turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    user_text: Mapped[str] = mapped_column(Text)
    assistant_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    mode: Mapped[str] = mapped_column(String(8))
    state: Mapped[str] = mapped_column(String(24), default="pending")
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    routing_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("mode IN ('real', 'mock')"),
        CheckConstraint(
            "state IN ('pending', 'ready', 'partial', 'failed', 'acceptance_unknown', 'paused')"
        ),
        CheckConstraint(
            "(routing_json IS NULL AND request_hash IS NULL AND claim_token IS NULL) OR "
            "(routing_json IS NOT NULL AND request_hash IS NOT NULL AND length(request_hash)=64 "
            "AND claim_token IS NOT NULL AND assistant_text IS NULL AND sources_json='[]')",
            name="ck_team_turn_unique_reply_storage",
        ),
        UniqueConstraint("id", "conversation_id", name="uq_conversation_turn_scope"),
    )


class TeamTurnResult(Base):
    __tablename__ = "team_turn_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    turn_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    participant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    assistant_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["turn_id", "conversation_id"],
            ["agent_conversation_turns.id", "agent_conversation_turns.conversation_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["participant_id", "conversation_id"],
            ["conversation_participants.id", "conversation_participants.conversation_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("turn_id", "ordinal", name="uq_team_result_ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_team_result_ordinal"),
        CheckConstraint(
            "state IN ('pending', 'running', 'ready', 'failed', 'acceptance_unknown')",
            name="ck_team_result_state",
        ),
        CheckConstraint(
            "(state='ready' AND assistant_text IS NOT NULL "
            "AND length(trim(assistant_text))>0) OR "
            "(state!='ready' AND assistant_text IS NULL)",
            name="ck_team_result_body",
        ),
    )


class TeamProviderCall(Base):
    """An exact SDK dispatch and its durable accepted response, sharing the ledger."""

    __tablename__ = "team_provider_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    result_id: Mapped[str] = mapped_column(
        ForeignKey("team_turn_results.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_id: Mapped[str] = mapped_column(
        ForeignKey("provider_operations.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(
        ForeignKey("provider_export_manifests.manifest_hash", ondelete="RESTRICT"), nullable=False
    )
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_response_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("result_id", "ordinal", name="uq_team_provider_call_ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_team_provider_call_ordinal"),
        CheckConstraint("length(request_hash)=64", name="ck_team_provider_call_request_hash"),
        CheckConstraint(
            "(accepted_response_json IS NULL AND accepted_response_hash IS NULL "
            "AND accepted_at IS NULL) OR (accepted_response_json IS NOT NULL "
            "AND length(accepted_response_hash)=64 AND accepted_at IS NOT NULL)",
            name="ck_team_provider_call_acceptance",
        ),
    )


class TeamProviderStandingGrant(Base):
    """Publisher-approved static resources; contains no student Chat existence or content."""

    __tablename__ = "team_provider_standing_grants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))
    team_version_id: Mapped[str] = mapped_column(
        ForeignKey("team_versions.id", ondelete="RESTRICT")
    )
    publication_id: Mapped[str] = mapped_column(
        ForeignKey("course_team_publications.id", ondelete="RESTRICT")
    )
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"))
    publisher_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    provider_operation: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_hash: Mapped[str] = mapped_column(
        ForeignKey("provider_policy_snapshots.policy_hash", ondelete="RESTRICT"), nullable=False
    )
    resource_manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    resource_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    team_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    publication_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    disclosure_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        Index(
            "uq_team_provider_standing_scope",
            "team_version_id",
            "publication_id",
            "provider_operation",
            "policy_hash",
            "resource_hash",
            "publisher_user_id",
            unique=True,
            sqlite_where=revoked_at.is_(None),
            postgresql_where=revoked_at.is_(None),
        ),
        CheckConstraint(
            "provider_operation IN ('llm_agent_chat','embedding_query')",
            name="ck_team_provider_standing_operation",
        ),
        CheckConstraint("length(resource_hash)=64", name="ck_team_provider_standing_hash"),
        CheckConstraint(
            "team_epoch>=0 AND publication_epoch>=0 AND disclosure_revision>=1",
            name="ck_team_provider_standing_epochs",
        ),
    )


class TeamProviderConsentBinding(Base):
    """Audit the actual confirmer before dispatch, without changing legacy consent rows."""

    __tablename__ = "team_provider_consent_bindings"

    manifest_hash: Mapped[str] = mapped_column(
        ForeignKey("provider_export_manifests.manifest_hash", ondelete="RESTRICT"), primary_key=True
    )
    confirmation_id: Mapped[str] = mapped_column(
        ForeignKey("provider_export_confirmations.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    result_id: Mapped[str] = mapped_column(
        ForeignKey("team_turn_results.id", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    confirmer_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    confirmer_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    standing_grant_id: Mapped[str | None] = mapped_column(
        ForeignKey("team_provider_standing_grants.id", ondelete="RESTRICT"), nullable=True
    )
    team_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    publication_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint(
            "confirmer_kind IN ('custom_owner', 'publisher_teacher', 'published_chat_owner')",
            name="ck_team_provider_consent_kind",
        ),
        CheckConstraint(
            "team_epoch >= 0 AND (publication_epoch IS NULL OR publication_epoch >= 0)",
            name="ck_team_provider_consent_epochs",
        ),
    )


class ChatProviderStandingGrant(Base):
    """Course-level permission for the reviewed Chat disclosure classes."""

    __tablename__ = "chat_provider_standing_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"))
    provider_operation: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_hash: Mapped[str] = mapped_column(
        ForeignKey("provider_policy_snapshots.policy_hash", ondelete="RESTRICT"), nullable=False
    )
    field_classes_json: Mapped[str] = mapped_column(Text, nullable=False)
    field_classes_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "uq_chat_provider_standing_scope",
            "course_id",
            "provider_operation",
            "policy_hash",
            "field_classes_hash",
            "confirmed_by_user_id",
            unique=True,
            sqlite_where=revoked_at.is_(None),
            postgresql_where=revoked_at.is_(None),
        ),
        CheckConstraint(
            "provider_operation IN ('llm_agent_chat', 'embedding_query')",
            name="ck_chat_provider_standing_operation",
        ),
        CheckConstraint("length(field_classes_hash)=64", name="ck_chat_provider_standing_hash"),
    )


class ChatProviderConsentBinding(Base):
    """Bind the exact Chat manifest to its confirmer and optional standing grant."""

    __tablename__ = "chat_provider_consent_bindings"

    manifest_hash: Mapped[str] = mapped_column(
        ForeignKey("provider_export_manifests.manifest_hash", ondelete="RESTRICT"),
        primary_key=True,
    )
    confirmation_id: Mapped[str] = mapped_column(
        ForeignKey("provider_export_confirmations.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="RESTRICT"), nullable=False
    )
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    confirmed_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    standing_grant_id: Mapped[str | None] = mapped_column(
        ForeignKey("chat_provider_standing_grants.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_chat_provider_consent_conversation", "conversation_id"),
        CheckConstraint("length(manifest_hash)=64", name="ck_chat_provider_consent_manifest_hash"),
    )


class ChatMemoryEntryAction(Base):
    """Persist one Brainform Memory navigation intent without dispatching Chat."""

    __tablename__ = "chat_memory_entry_actions"

    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    action_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"))
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="RESTRICT"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('conversation','agent','team','maya_team')",
            name="ck_chat_memory_action_source_kind",
        ),
        Index("ix_chat_memory_action_conversation", "conversation_id"),
    )


class AgentAccountMemory(Base):
    """One account's note for one Agent. Debates never read this table."""

    __tablename__ = "agent_account_memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # A retired note stays for audit but no Agent reads or rewrites it.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "length(body) >= 1 AND length(body) <= 2000",
            name="ck_agent_account_memory_body",
        ),
        Index("ix_agent_account_memory_owner_agent", "owner_user_id", "agent_id"),
    )


class TeamChatEvent(Base):
    __tablename__ = "team_chat_events"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    turn_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversation_turns.id", ondelete="CASCADE"), nullable=False
    )
    result_id: Mapped[str | None] = mapped_column(
        ForeignKey("team_turn_results.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_team_chat_event_sequence"),
        CheckConstraint(
            "kind IN ('turn_started', 'member_result', 'turn_done')", name="ck_team_chat_event_kind"
        ),
    )


class ProviderPreferences(Base):
    # Provider credentials are installation-wide, not readable course content.
    __tablename__ = "provider_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    modes_json: Mapped[str] = mapped_column(Text, default="{}")
    encrypted_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    checks_json: Mapped[str] = mapped_column(Text, default="{}")
    __table_args__ = (CheckConstraint("id = 1 AND revision >= 0"),)


class LivePresence(Base):
    __tablename__ = "classroom_live_presence"

    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    debate_id: Mapped[str] = mapped_column(ForeignKey("debates.id", ondelete="CASCADE"))
    session_hash: Mapped[str] = mapped_column(String(64))
    lease_id: Mapped[str] = mapped_column(String(36))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
