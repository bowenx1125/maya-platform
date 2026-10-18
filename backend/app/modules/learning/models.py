"""Append-only learning facts and immutable Assessment revisions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class LearningRecord(Base):
    __tablename__ = "learning_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    team_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    team_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    chat_visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    activity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    record_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    client_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "record_kind IN ('answer', 'skip', 'hint', 'evidence')",
            name="ck_learning_records_kind",
        ),
        CheckConstraint(
            "origin IN ('single_agent', 'custom_team', 'published_course_team')",
            name="ck_learning_records_origin",
        ),
        CheckConstraint(
            "chat_visibility IN ('private', 'public')",
            name="ck_learning_records_chat_visibility",
        ),
        CheckConstraint(
            "((origin = 'single_agent' AND team_id IS NULL AND team_version_id IS NULL) OR "
            "(origin IN ('custom_team', 'published_course_team') AND team_id IS NOT NULL "
            "AND team_version_id IS NOT NULL))",
            name="ck_learning_records_team_origin",
        ),
        CheckConstraint("length(payload_hash) = 64", name="ck_learning_records_payload_hash"),
        ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_learning_records_actor"
        ),
        ForeignKeyConstraint(
            ["course_id"], ["courses.id"], ondelete="RESTRICT", name="fk_learning_records_course"
        ),
        ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="RESTRICT",
            name="fk_learning_records_conversation",
        ),
        ForeignKeyConstraint(
            ["attempt_id"],
            ["assessment_attempts.id"],
            ondelete="RESTRICT",
            name="fk_learning_records_attempt",
        ),
        ForeignKeyConstraint(
            ["team_id", "team_version_id"],
            ["team_versions.team_id", "team_versions.id"],
            ondelete="RESTRICT",
            name="fk_learning_records_team_version",
        ),
        UniqueConstraint(
            "actor_user_id",
            "conversation_id",
            "client_event_id",
            name="uq_learning_records_event_idempotency",
        ),
        Index("ix_learning_records_actor_conversation", "actor_user_id", "conversation_id"),
        Index(
            "ix_learning_records_course_origin_privacy",
            "course_id",
            "origin",
            "chat_visibility",
        ),
        Index("ix_learning_records_team_version", "team_id", "team_version_id"),
    )


class LearningAssessment(Base):
    __tablename__ = "learning_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_revision_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("current_revision_seq >= 1", name="ck_learning_assessments_revision"),
        ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessments_owner",
        ),
        ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessments_course",
        ),
        ForeignKeyConstraint(
            ["created_conversation_id"],
            ["agent_conversations.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessments_conversation",
        ),
        UniqueConstraint("attempt_id", name="uq_learning_assessments_attempt"),
        Index("ix_learning_assessments_owner_course", "owner_user_id", "course_id"),
    )


class LearningAssessmentRevision(Base):
    __tablename__ = "learning_assessment_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    team_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    team_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    chat_visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    activity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    revision_source: Mapped[str] = mapped_column(
        String(24), nullable=False, default="user_authored"
    )
    evaluator_team_member_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    evaluator_agent_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    editor_team_member_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    editor_agent_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_model_call_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_tool_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("revision_seq >= 1", name="ck_learning_assessment_revision_seq"),
        CheckConstraint(
            "revision_source IN ('user_authored', 'model_evaluation', 'practice_agent_edit')",
            name="ck_learning_assessment_revision_source",
        ),
        CheckConstraint(
            "(revision_source='user_authored' AND attempt_id IS NULL "
            "AND evaluator_team_member_id IS NULL AND evaluator_agent_version_id IS NULL "
            "AND editor_team_member_id IS NULL AND editor_agent_version_id IS NULL "
            "AND source_model_call_id IS NULL AND source_tool_call_id IS NULL) OR "
            "(revision_source='model_evaluation' AND attempt_id IS NOT NULL "
            "AND evaluator_team_member_id IS NOT NULL AND evaluator_agent_version_id IS NOT NULL "
            "AND editor_team_member_id IS NULL AND editor_agent_version_id IS NULL "
            "AND source_model_call_id IS NOT NULL AND source_tool_call_id IS NOT NULL) OR "
            "(revision_source='practice_agent_edit' AND attempt_id IS NULL "
            "AND evaluator_team_member_id IS NULL AND evaluator_agent_version_id IS NULL "
            "AND editor_agent_version_id IS NOT NULL "
            "AND ((origin='single_agent' AND team_id IS NULL AND team_version_id IS NULL "
            "AND editor_team_member_id IS NULL) OR "
            "(origin IN ('custom_team', 'published_course_team') "
            "AND team_id IS NOT NULL AND team_version_id IS NOT NULL "
            "AND editor_team_member_id IS NOT NULL)) "
            "AND source_model_call_id IS NOT NULL AND source_tool_call_id IS NOT NULL)",
            name="ck_learning_assessment_revision_executor_provenance",
        ),
        CheckConstraint(
            "origin IN ('single_agent', 'custom_team', 'published_course_team')",
            name="ck_learning_assessment_revision_origin",
        ),
        CheckConstraint(
            "chat_visibility IN ('private', 'public')",
            name="ck_learning_assessment_revision_chat_visibility",
        ),
        CheckConstraint(
            "((origin = 'single_agent' AND team_id IS NULL AND team_version_id IS NULL) OR "
            "(origin IN ('custom_team', 'published_course_team') AND team_id IS NOT NULL "
            "AND team_version_id IS NOT NULL))",
            name="ck_learning_assessment_revision_team_origin",
        ),
        CheckConstraint("length(content_hash) = 64", name="ck_learning_assessment_revision_hash"),
        ForeignKeyConstraint(
            ["assessment_id"],
            ["learning_assessments.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_revision_head",
        ),
        ForeignKeyConstraint(
            ["assessment_id", "previous_revision_id"],
            ["learning_assessment_revisions.assessment_id", "learning_assessment_revisions.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_revision_previous",
        ),
        ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_revision_actor",
        ),
        ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_revision_course",
        ),
        ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_revision_conversation",
        ),
        ForeignKeyConstraint(
            ["team_id", "team_version_id"],
            ["team_versions.team_id", "team_versions.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_revision_team_version",
        ),
        UniqueConstraint(
            "assessment_id", "revision_seq", name="uq_learning_assessment_revision_seq"
        ),
        UniqueConstraint("assessment_id", "id", name="uq_learning_assessment_revision_scoped_id"),
        Index("ix_learning_assessment_revision_history", "assessment_id", "revision_seq"),
    )


class LearningAssessmentMutation(Base):
    __tablename__ = "learning_assessment_mutations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    client_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation: Mapped[str] = mapped_column(String(8), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "operation IN ('create', 'edit')", name="ck_learning_assessment_mutation_op"
        ),
        CheckConstraint("length(request_hash) = 64", name="ck_learning_assessment_mutation_hash"),
        ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_mutation_actor",
        ),
        ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_mutation_conversation",
        ),
        ForeignKeyConstraint(
            ["assessment_id"],
            ["learning_assessments.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_mutation_assessment",
        ),
        ForeignKeyConstraint(
            ["assessment_id", "revision_id"],
            ["learning_assessment_revisions.assessment_id", "learning_assessment_revisions.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_mutation_revision",
        ),
        UniqueConstraint(
            "actor_user_id",
            "conversation_id",
            "client_event_id",
            name="uq_learning_assessment_mutation_idempotency",
        ),
        Index("ix_learning_assessment_mutation_assessment", "assessment_id", "created_at"),
    )


class LearningAssessmentResourceGrant(Base):
    """A persisted, single-resource Agent edit grant for non-formal Assessments."""

    __tablename__ = "learning_assessment_resource_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    participant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    team_member_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(8), nullable=False, default="edit")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("operation = 'edit'", name="ck_learning_assessment_grant_operation"),
        CheckConstraint(
            "agent_authorization_epoch >= 0", name="ck_learning_assessment_grant_epoch"
        ),
        CheckConstraint(
            "(participant_id IS NULL AND team_member_id IS NULL) OR "
            "(participant_id IS NOT NULL AND team_member_id IS NOT NULL)",
            name="ck_learning_assessment_grant_participant_pair",
        ),
        ForeignKeyConstraint(
            ["assessment_id"],
            ["learning_assessments.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_grant_assessment",
        ),
        ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_grant_owner",
        ),
        ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_grant_course",
        ),
        ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_grant_conversation",
        ),
        ForeignKeyConstraint(
            ["participant_id", "conversation_id"],
            ["conversation_participants.id", "conversation_participants.conversation_id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_grant_participant",
        ),
        ForeignKeyConstraint(
            ["team_member_id"],
            ["team_version_members.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_grant_team_member",
        ),
        ForeignKeyConstraint(
            ["agent_version_id"],
            ["agent_versions.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_grant_agent_version",
        ),
        UniqueConstraint(
            "assessment_id", "participant_id", "operation", name="uq_learning_assessment_grant"
        ),
        UniqueConstraint(
            "assessment_id",
            "agent_version_id",
            "operation",
            name="uq_learning_assessment_grant_version",
        ),
        Index("ix_learning_assessment_grant_conversation", "conversation_id", "revoked_at"),
    )


class AssessmentActivity(Base):
    """A server-selected Question snapshot bound to one published Team recipe."""

    __tablename__ = "assessment_activities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), nullable=False)
    team_id: Mapped[str] = mapped_column(String(36), nullable=False)
    team_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    publication_id: Mapped[str] = mapped_column(String(36), nullable=False)
    recipe_id: Mapped[str] = mapped_column(String(120), nullable=False)
    recipe_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    evaluator_team_member_id: Mapped[str] = mapped_column(String(36), nullable=False)
    evaluator_agent_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    boundary_team_member_id: Mapped[str] = mapped_column(String(36), nullable=False)
    boundary_agent_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    publisher_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    questions_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    question_selection_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("length(trim(recipe_id)) > 0", name="ck_assessment_activity_recipe"),
        CheckConstraint("length(questions_hash) = 64", name="ck_assessment_activity_hash"),
        CheckConstraint(
            "question_selection_revision >= 1",
            name="ck_assessment_activity_question_selection_revision",
        ),
        ForeignKeyConstraint(
            ["course_id"], ["courses.id"], ondelete="RESTRICT", name="fk_assessment_activity_course"
        ),
        ForeignKeyConstraint(
            ["team_id", "team_version_id"],
            ["team_versions.team_id", "team_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_team_version",
        ),
        ForeignKeyConstraint(
            ["publication_id"],
            ["course_team_publications.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_publication",
        ),
        ForeignKeyConstraint(
            ["recipe_version_id"],
            ["agent_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_recipe_version",
        ),
        ForeignKeyConstraint(
            ["team_version_id", "evaluator_team_member_id"],
            ["team_version_members.team_version_id", "team_version_members.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_evaluator_member",
        ),
        ForeignKeyConstraint(
            ["team_version_id", "boundary_team_member_id"],
            ["team_version_members.team_version_id", "team_version_members.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_boundary_member",
        ),
        ForeignKeyConstraint(
            ["evaluator_agent_version_id"],
            ["agent_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_evaluator_version",
        ),
        ForeignKeyConstraint(
            ["boundary_agent_version_id"],
            ["agent_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_boundary_version",
        ),
        ForeignKeyConstraint(
            ["publisher_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_publisher",
        ),
        UniqueConstraint(
            "publication_id",
            "recipe_id",
            "recipe_version_id",
            name="uq_assessment_activity_recipe_publication",
        ),
        UniqueConstraint("id", "publication_id", name="uq_assessment_activity_publication_scope"),
        UniqueConstraint("id", "team_id", "recipe_id", name="uq_assessment_activity_recipe_scope"),
        Index("ix_assessment_activities_course_publication", "course_id", "publication_id"),
    )


class AssessmentActivityQuestion(Base):
    """An authorized Question candidate; content freezes only when presented."""

    __tablename__ = "assessment_activity_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    activity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    selection_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    knowledge_set_id: Mapped[str] = mapped_column(String(36), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    question_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    required: Mapped[bool] = mapped_column(nullable=False, default=True)

    __table_args__ = (
        CheckConstraint(
            "selection_revision >= 1", name="ck_assessment_activity_question_selection_revision"
        ),
        CheckConstraint("ordinal >= 0", name="ck_assessment_activity_question_ordinal"),
        CheckConstraint("authorization_epoch >= 0", name="ck_assessment_activity_question_epoch"),
        ForeignKeyConstraint(
            ["activity_id"],
            ["assessment_activities.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_question_activity",
        ),
        ForeignKeyConstraint(
            ["asset_id", "knowledge_set_id"],
            ["knowledge_assets.id", "knowledge_assets.knowledge_set_id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_question_asset",
        ),
        UniqueConstraint(
            "activity_id",
            "selection_revision",
            "ordinal",
            name="uq_assessment_activity_question_revision_order",
        ),
        UniqueConstraint(
            "activity_id",
            "selection_revision",
            "asset_id",
            name="uq_assessment_activity_question_revision_asset",
        ),
        UniqueConstraint("id", "activity_id", name="uq_assessment_activity_question_scope"),
        ForeignKeyConstraint(
            ["question_version_id"],
            ["knowledge_asset_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_question_version",
        ),
        Index(
            "ix_assessment_activity_questions_activity",
            "activity_id",
            "selection_revision",
            "required",
            "ordinal",
        ),
    )


class AssessmentAttempt(Base):
    """One durable learner attempt, independent of its Chat messages and runs."""

    __tablename__ = "assessment_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    activity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    team_id: Mapped[str] = mapped_column(String(36), nullable=False)
    recipe_id: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    chat_visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question_selection_revision: Mapped[int] = mapped_column(
        Integer,
        CheckConstraint(
            "question_selection_revision >= 1",
            name="ck_assessment_attempt_question_selection_revision",
        ),
        nullable=False,
        default=1,
        server_default="1",
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    abandoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    abandonment_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The student's name when the attempt began, beside the account id.
    actor_display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Set when the learner ends early; no further follow-up round may be added.
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "chat_visibility IN ('private', 'public')", name="ck_assessment_attempt_visibility"
        ),
        CheckConstraint(
            "status IN ('in_progress', 'paused', 'completed', 'abandoned')",
            name="ck_assessment_attempt_status",
        ),
        CheckConstraint("revision >= 0", name="ck_assessment_attempt_revision"),
        CheckConstraint("length(trim(recipe_id)) > 0", name="ck_assessment_attempt_recipe"),
        CheckConstraint(
            "(status='completed' AND completed_at IS NOT NULL AND abandoned_at IS NULL) OR "
            "(status='abandoned' AND abandoned_at IS NOT NULL AND completed_at IS NULL) OR "
            "(status IN ('in_progress', 'paused') AND completed_at IS NULL "
            "AND abandoned_at IS NULL)",
            name="ck_assessment_attempt_terminal_state",
        ),
        CheckConstraint(
            "(abandonment_reason IS NULL) OR status='abandoned'",
            name="ck_assessment_attempt_abandonment_reason",
        ),
        CheckConstraint(
            "abandonment_reason IS NULL OR abandonment_reason IN "
            "('user_redo', 'user_abandoned', 'chat_withdrawn')",
            name="ck_assessment_attempt_abandonment_reason_kind",
        ),
        ForeignKeyConstraint(
            ["activity_id", "team_id", "recipe_id"],
            [
                "assessment_activities.id",
                "assessment_activities.team_id",
                "assessment_activities.recipe_id",
            ],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_activity",
        ),
        ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_assessment_attempt_actor"
        ),
        ForeignKeyConstraint(
            ["source_conversation_id"],
            ["agent_conversations.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_conversation",
        ),
        UniqueConstraint("id", "activity_id", name="uq_assessment_attempt_activity_scope"),
        # The teacher's Record reads each activity's attempts in start order.
        Index("ix_assessment_attempts_activity_started", "activity_id", "started_at"),
        Index(
            "ix_assessment_attempts_actor_activity",
            "actor_user_id",
            "team_id",
            "recipe_id",
            "status",
        ),
        Index(
            "uq_assessment_attempt_active_per_actor_recipe",
            "actor_user_id",
            "team_id",
            "recipe_id",
            unique=True,
            sqlite_where=(status.in_(("in_progress", "paused"))),
            postgresql_where=(status.in_(("in_progress", "paused"))),
        ),
    )


class AssessmentAttemptQuestion(Base):
    """A Question/Rubric version pinned at its first actual presentation."""

    __tablename__ = "assessment_attempt_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(36), nullable=False)
    activity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    activity_question_id: Mapped[str] = mapped_column(String(36), nullable=False)
    question_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    required: Mapped[bool] = mapped_column(nullable=False, default=True)
    content_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_presented")
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
    presented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_answer_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_assessment_attempt_question_ordinal"),
        CheckConstraint(
            "status IN ('not_presented', 'presented', 'resolved')",
            name="ck_assessment_attempt_question_status",
        ),
        CheckConstraint(
            "(status='not_presented' AND presented_at IS NULL AND question_version_id IS NULL "
            "AND content_json IS NULL AND content_hash IS NULL) OR "
            "(status IN ('presented', 'resolved') AND presented_at IS NOT NULL "
            "AND question_version_id IS NOT NULL AND content_json IS NOT NULL "
            "AND length(content_hash)=64)",
            name="ck_assessment_attempt_question_snapshot",
        ),
        CheckConstraint(
            "(status='resolved' AND resolution IN ('answered', 'skipped') "
            "AND resolved_at IS NOT NULL) OR "
            "(status!='resolved' AND resolution IS NULL AND resolved_at IS NULL)",
            name="ck_assessment_attempt_question_resolution",
        ),
        CheckConstraint(
            "(resolution='answered' AND effective_answer_record_id IS NOT NULL) OR "
            "(resolution IS NULL OR resolution='skipped') OR status!='resolved'",
            name="ck_assessment_attempt_question_effective_answer",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "activity_id"],
            ["assessment_attempts.id", "assessment_attempts.activity_id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_question_attempt",
        ),
        ForeignKeyConstraint(
            ["activity_question_id", "activity_id"],
            ["assessment_activity_questions.id", "assessment_activity_questions.activity_id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_question_activity_question",
        ),
        ForeignKeyConstraint(
            ["question_version_id"],
            ["knowledge_asset_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_question_version",
        ),
        ForeignKeyConstraint(
            ["effective_answer_record_id"],
            ["learning_records.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_question_effective_answer",
        ),
        UniqueConstraint("attempt_id", "ordinal", name="uq_assessment_attempt_question_order"),
        UniqueConstraint(
            "attempt_id", "activity_question_id", name="uq_assessment_attempt_question_once"
        ),
        UniqueConstraint("id", "attempt_id", name="uq_assessment_attempt_question_scope"),
        Index("ix_assessment_attempt_questions_attempt_status", "attempt_id", "status", "ordinal"),
    )


class AssessmentAttemptEvent(Base):
    """Idempotent append-only answer and lifecycle event with real source links."""

    __tablename__ = "assessment_attempt_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(36), nullable=False)
    activity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    client_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    classification: Mapped[str | None] = mapped_column(String(40), nullable=True)
    question_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    learning_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    replacement_attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "event_kind IN ('start', 'answer', 'skip', 'pause', 'resume', 'complete', "
            "'restart', "
            "'abandon', 'withdraw')",
            name="ck_assessment_attempt_event_kind",
        ),
        CheckConstraint(
            "classification IS NULL OR classification IN "
            "('start_request', 'restart_request', 'answer_only', "
            "'answer_with_restricted_request', 'skip_request', "
            "'pause_request', 'resume_request', 'complete_request', 'redo_request', "
            "'abandon_request', 'progress_request', 'answers_request', 'restricted_request', "
            "'off_topic')",
            name="ck_assessment_attempt_event_classification",
        ),
        CheckConstraint("length(request_hash) = 64", name="ck_assessment_attempt_event_hash"),
        CheckConstraint(
            "(event_kind IN ('answer', 'skip') AND question_id IS NOT NULL) OR "
            "(event_kind NOT IN ('answer', 'skip') AND question_id IS NULL)",
            name="ck_assessment_attempt_event_question",
        ),
        CheckConstraint(
            "(event_kind IN ('answer', 'skip') AND learning_record_id IS NOT NULL) OR "
            "(event_kind NOT IN ('answer', 'skip') AND learning_record_id IS NULL)",
            name="ck_assessment_attempt_event_learning_record",
        ),
        CheckConstraint(
            "(event_kind='abandon' AND classification='redo_request' "
            "AND replacement_attempt_id IS NOT NULL) OR "
            "(event_kind='abandon' AND classification='abandon_request' "
            "AND replacement_attempt_id IS NULL) OR "
            "(event_kind!='abandon' AND replacement_attempt_id IS NULL)",
            name="ck_assessment_attempt_event_replacement",
        ),
        ForeignKeyConstraint(
            ["attempt_id"],
            ["assessment_attempts.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_event_attempt",
        ),
        ForeignKeyConstraint(
            ["activity_id"],
            ["assessment_activities.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_event_activity",
        ),
        ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_event_actor",
        ),
        ForeignKeyConstraint(
            ["question_id", "attempt_id"],
            ["assessment_attempt_questions.id", "assessment_attempt_questions.attempt_id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_event_question",
        ),
        ForeignKeyConstraint(
            ["learning_record_id"],
            ["learning_records.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_event_learning_record",
        ),
        ForeignKeyConstraint(
            ["replacement_attempt_id"],
            ["assessment_attempts.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_event_replacement",
        ),
        UniqueConstraint(
            "activity_id",
            "actor_user_id",
            "client_event_id",
            name="uq_assessment_attempt_event_idempotency",
        ),
        Index("ix_assessment_attempt_events_attempt", "attempt_id", "created_at"),
    )


class AssessmentCourseReport(Base):
    """Teacher-owned pointer to immutable formal assessment report revisions."""

    __tablename__ = "assessment_course_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(36), nullable=False)
    activity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    current_revision_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("current_revision_seq >= 1", name="ck_assessment_course_report_revision"),
        ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_course",
        ),
        ForeignKeyConstraint(
            ["activity_id"],
            ["assessment_activities.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_activity",
        ),
        ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_owner",
        ),
        UniqueConstraint("course_id", "activity_id", name="uq_assessment_course_report_activity"),
        UniqueConstraint(
            "id", "course_id", "activity_id", name="uq_assessment_course_report_scope"
        ),
        Index("ix_assessment_course_reports_owner", "owner_user_id", "course_id"),
    )


class AssessmentCourseReportRevision(Base):
    """Immutable report content and the exact eligible source manifest."""

    __tablename__ = "assessment_course_report_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(36), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), nullable=False)
    activity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    client_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("revision_seq >= 1", name="ck_assessment_course_report_revision_seq"),
        CheckConstraint(
            "length(request_hash) = 64", name="ck_assessment_course_report_request_hash"
        ),
        CheckConstraint("length(source_hash) = 64", name="ck_assessment_course_report_source_hash"),
        ForeignKeyConstraint(
            ["report_id", "course_id", "activity_id"],
            [
                "assessment_course_reports.id",
                "assessment_course_reports.course_id",
                "assessment_course_reports.activity_id",
            ],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_revision_report",
        ),
        ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_revision_actor",
        ),
        PrimaryKeyConstraint("id"),
        UniqueConstraint(
            "report_id", "revision_seq", name="uq_assessment_course_report_revision_seq"
        ),
        UniqueConstraint("report_id", "id", name="uq_assessment_course_report_revision_scope"),
        UniqueConstraint(
            "actor_user_id",
            "client_event_id",
            name="uq_assessment_course_report_request_idempotency",
        ),
        Index(
            "ix_assessment_course_report_revision_activity",
            "course_id",
            "activity_id",
            "revision_seq",
        ),
    )


class AssessmentCourseReportEvidence(Base):
    """One Public formal attempt included in a persisted report revision."""

    __tablename__ = "assessment_course_report_evidence"

    report_revision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["report_revision_id"],
            ["assessment_course_report_revisions.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_evidence_revision",
        ),
        ForeignKeyConstraint(
            ["attempt_id"],
            ["assessment_attempts.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_evidence_attempt",
        ),
        Index("ix_assessment_course_report_evidence_attempt", "attempt_id"),
    )


class AssessmentCourseReportMutation(Base):
    """Idempotent teacher action receipt for creating one report revision."""

    __tablename__ = "assessment_course_report_mutations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    client_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    report_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "length(request_hash) = 64", name="ck_assessment_course_report_mutation_hash"
        ),
        ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_mutation_actor",
        ),
        ForeignKeyConstraint(
            ["report_id"],
            ["assessment_course_reports.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_mutation_report",
        ),
        ForeignKeyConstraint(
            ["report_id", "revision_id"],
            [
                "assessment_course_report_revisions.report_id",
                "assessment_course_report_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_mutation_revision",
        ),
        UniqueConstraint(
            "actor_user_id",
            "client_event_id",
            name="uq_assessment_course_report_mutation_idempotency",
        ),
        Index("ix_assessment_course_report_mutations_report", "report_id", "created_at"),
    )


class LearningBoundary(Base):
    """One learner-owned Boundary summary container for a formal attempt."""

    __tablename__ = "learning_boundaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(36), nullable=False)
    activity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    current_revision_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("current_revision_seq >= 0", name="ck_learning_boundary_revision_seq"),
        ForeignKeyConstraint(
            ["attempt_id"],
            ["assessment_attempts.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_attempt",
        ),
        ForeignKeyConstraint(
            ["activity_id"],
            ["assessment_activities.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_activity",
        ),
        ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_owner",
        ),
        ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_course",
        ),
        ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_conversation",
        ),
        UniqueConstraint("attempt_id", name="uq_learning_boundary_attempt"),
        UniqueConstraint("id", "attempt_id", name="uq_learning_boundary_attempt_scope"),
        Index("ix_learning_boundaries_owner_course", "owner_user_id", "course_id"),
    )


class LearningBoundaryRevision(Base):
    """Immutable Boundary summary authored by the activity's server-bound executor."""

    __tablename__ = "learning_boundary_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    boundary_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    summarizer_team_member_id: Mapped[str] = mapped_column(String(36), nullable=False)
    summarizer_agent_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_model_call_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_tool_call_id: Mapped[str] = mapped_column(String(120), nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("revision_seq >= 1", name="ck_learning_boundary_revision_number"),
        CheckConstraint("length(content_hash) = 64", name="ck_learning_boundary_revision_hash"),
        ForeignKeyConstraint(
            ["boundary_id", "attempt_id"],
            ["learning_boundaries.id", "learning_boundaries.attempt_id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_revision_boundary",
        ),
        ForeignKeyConstraint(
            ["boundary_id", "previous_revision_id"],
            ["learning_boundary_revisions.boundary_id", "learning_boundary_revisions.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_revision_previous",
        ),
        ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_revision_actor",
        ),
        ForeignKeyConstraint(
            ["summarizer_team_member_id"],
            ["team_version_members.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_revision_member",
        ),
        ForeignKeyConstraint(
            ["summarizer_agent_version_id"],
            ["agent_versions.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_revision_agent_version",
        ),
        UniqueConstraint(
            "boundary_id", "revision_seq", name="uq_learning_boundary_revision_number"
        ),
        UniqueConstraint("boundary_id", "id", name="uq_learning_boundary_revision_scoped_id"),
        UniqueConstraint("id", "attempt_id", name="uq_learning_boundary_revision_attempt_scope"),
        UniqueConstraint("source_tool_call_id", name="uq_learning_boundary_tool_call"),
        Index("ix_learning_boundary_revision_history", "boundary_id", "revision_seq"),
    )


class LearningBoundaryEvidence(Base):
    """Specific same-attempt answer or evaluator revision supporting a Boundary."""

    __tablename__ = "learning_boundary_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    boundary_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(36), nullable=False)
    learning_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    assessment_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(learning_record_id IS NOT NULL AND assessment_revision_id IS NULL) OR "
            "(learning_record_id IS NULL AND assessment_revision_id IS NOT NULL)",
            name="ck_learning_boundary_evidence_source",
        ),
        ForeignKeyConstraint(
            ["boundary_revision_id", "attempt_id"],
            ["learning_boundary_revisions.id", "learning_boundary_revisions.attempt_id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_evidence_revision",
        ),
        ForeignKeyConstraint(
            ["learning_record_id"],
            ["learning_records.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_evidence_learning_record",
        ),
        ForeignKeyConstraint(
            ["assessment_revision_id"],
            ["learning_assessment_revisions.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_evidence_assessment_revision",
        ),
        UniqueConstraint(
            "boundary_revision_id",
            "learning_record_id",
            name="uq_learning_boundary_evidence_record",
        ),
        UniqueConstraint(
            "boundary_revision_id",
            "assessment_revision_id",
            name="uq_learning_boundary_evidence_assessment",
        ),
        Index("ix_learning_boundary_evidence_attempt", "attempt_id"),
    )


__all__ = [
    "AssessmentActivity",
    "AssessmentActivityQuestion",
    "AssessmentAttempt",
    "AssessmentAttemptEvent",
    "AssessmentAttemptQuestion",
    "AssessmentCourseReport",
    "AssessmentCourseReportEvidence",
    "AssessmentCourseReportMutation",
    "AssessmentCourseReportRevision",
    "LearningAssessment",
    "LearningAssessmentMutation",
    "LearningAssessmentRevision",
    "LearningAssessmentResourceGrant",
    "LearningBoundary",
    "LearningBoundaryEvidence",
    "LearningBoundaryRevision",
    "LearningRecord",
]
