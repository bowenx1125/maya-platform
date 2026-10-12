"""Persist pinned assessment activities, resumable attempts and attempt answers."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045_assessment_attempts"
down_revision: str | Sequence[str] | None = "0044_team_provider_stage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        # SQLite DDL and Alembic's revision write must succeed or roll back together.
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    op.create_table(
        "assessment_activities",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("team_id", sa.String(36), nullable=False),
        sa.Column("team_version_id", sa.String(36), nullable=False),
        sa.Column("publication_id", sa.String(36), nullable=False),
        sa.Column("recipe_id", sa.String(120), nullable=False),
        sa.Column("recipe_version_id", sa.String(36), nullable=False),
        sa.Column("evaluator_team_member_id", sa.String(36), nullable=False),
        sa.Column("evaluator_agent_version_id", sa.String(36), nullable=False),
        sa.Column("boundary_team_member_id", sa.String(36), nullable=False),
        sa.Column("boundary_agent_version_id", sa.String(36), nullable=False),
        sa.Column("publisher_user_id", sa.String(36), nullable=False),
        sa.Column("questions_hash", sa.String(64), nullable=False),
        sa.Column(
            "question_selection_revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(recipe_id)) > 0", name="ck_assessment_activity_recipe"),
        sa.CheckConstraint("length(questions_hash) = 64", name="ck_assessment_activity_hash"),
        sa.CheckConstraint(
            "question_selection_revision >= 1",
            name="ck_assessment_activity_question_selection_revision",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"], ["courses.id"], ondelete="RESTRICT", name="fk_assessment_activity_course"
        ),
        sa.ForeignKeyConstraint(
            ["team_id", "team_version_id"],
            ["team_versions.team_id", "team_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_team_version",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["course_team_publications.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_publication",
        ),
        sa.ForeignKeyConstraint(
            ["recipe_version_id"],
            ["agent_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_recipe_version",
        ),
        sa.ForeignKeyConstraint(
            ["team_version_id", "evaluator_team_member_id"],
            ["team_version_members.team_version_id", "team_version_members.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_evaluator_member",
        ),
        sa.ForeignKeyConstraint(
            ["team_version_id", "boundary_team_member_id"],
            ["team_version_members.team_version_id", "team_version_members.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_boundary_member",
        ),
        sa.ForeignKeyConstraint(
            ["evaluator_agent_version_id"],
            ["agent_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_evaluator_version",
        ),
        sa.ForeignKeyConstraint(
            ["boundary_agent_version_id"],
            ["agent_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_boundary_version",
        ),
        sa.ForeignKeyConstraint(
            ["publisher_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_publisher",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "publication_id",
            "recipe_id",
            "recipe_version_id",
            name="uq_assessment_activity_recipe_publication",
        ),
        sa.UniqueConstraint(
            "id", "publication_id", name="uq_assessment_activity_publication_scope"
        ),
        sa.UniqueConstraint(
            "id", "team_id", "recipe_id", name="uq_assessment_activity_recipe_scope"
        ),
    )
    op.create_index(
        "ix_assessment_activities_course_publication",
        "assessment_activities",
        ["course_id", "publication_id"],
    )

    op.create_table(
        "assessment_activity_questions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("activity_id", sa.String(36), nullable=False),
        sa.Column("selection_revision", sa.Integer(), nullable=False),
        sa.Column("knowledge_set_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("question_version_id", sa.String(36), nullable=False),
        sa.Column("authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint(
            "selection_revision >= 1",
            name="ck_assessment_activity_question_selection_revision",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_assessment_activity_question_ordinal"),
        sa.CheckConstraint(
            "authorization_epoch >= 0", name="ck_assessment_activity_question_epoch"
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["assessment_activities.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_question_activity",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "knowledge_set_id"],
            ["knowledge_assets.id", "knowledge_assets.knowledge_set_id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_question_asset",
        ),
        sa.ForeignKeyConstraint(
            ["question_version_id"],
            ["knowledge_asset_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessment_activity_question_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "activity_id",
            "selection_revision",
            "ordinal",
            name="uq_assessment_activity_question_revision_order",
        ),
        sa.UniqueConstraint(
            "activity_id",
            "selection_revision",
            "asset_id",
            name="uq_assessment_activity_question_revision_asset",
        ),
        sa.UniqueConstraint("id", "activity_id", name="uq_assessment_activity_question_scope"),
    )
    op.create_index(
        "ix_assessment_activity_questions_activity",
        "assessment_activity_questions",
        ["activity_id", "selection_revision", "required", "ordinal"],
    )

    op.create_table(
        "assessment_attempts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("activity_id", sa.String(36), nullable=False),
        sa.Column("team_id", sa.String(36), nullable=False),
        sa.Column("recipe_id", sa.String(120), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("source_conversation_id", sa.String(36), nullable=False),
        sa.Column("chat_visibility", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("abandoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("abandonment_reason", sa.String(32), nullable=True),
        sa.CheckConstraint(
            "chat_visibility IN ('private', 'public')", name="ck_assessment_attempt_visibility"
        ),
        sa.CheckConstraint(
            "status IN ('in_progress', 'paused', 'completed', 'abandoned')",
            name="ck_assessment_attempt_status",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_assessment_attempt_revision"),
        sa.CheckConstraint("length(trim(recipe_id)) > 0", name="ck_assessment_attempt_recipe"),
        sa.CheckConstraint(
            "(status='completed' AND completed_at IS NOT NULL AND abandoned_at IS NULL) OR "
            "(status='abandoned' AND abandoned_at IS NOT NULL AND completed_at IS NULL) OR "
            "(status IN ('in_progress', 'paused') AND completed_at IS NULL "
            "AND abandoned_at IS NULL)",
            name="ck_assessment_attempt_terminal_state",
        ),
        sa.CheckConstraint(
            "(abandonment_reason IS NULL) OR status='abandoned'",
            name="ck_assessment_attempt_abandonment_reason",
        ),
        sa.CheckConstraint(
            "abandonment_reason IS NULL OR abandonment_reason IN "
            "('user_redo', 'user_abandoned', 'chat_withdrawn')",
            name="ck_assessment_attempt_abandonment_reason_kind",
        ),
        sa.ForeignKeyConstraint(
            ["activity_id", "team_id", "recipe_id"],
            [
                "assessment_activities.id",
                "assessment_activities.team_id",
                "assessment_activities.recipe_id",
            ],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_activity",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_assessment_attempt_actor"
        ),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"],
            ["agent_conversations.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_conversation",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "activity_id", name="uq_assessment_attempt_activity_scope"),
    )
    op.create_index(
        "ix_assessment_attempts_actor_activity",
        "assessment_attempts",
        ["actor_user_id", "team_id", "recipe_id", "status"],
    )
    op.create_index(
        "uq_assessment_attempt_active_per_actor_recipe",
        "assessment_attempts",
        ["actor_user_id", "team_id", "recipe_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('in_progress', 'paused')"),
        postgresql_where=sa.text("status IN ('in_progress', 'paused')"),
    )

    op.add_column("learning_assessments", sa.Column("attempt_id", sa.String(36), nullable=True))
    op.create_index(
        "uq_learning_assessments_attempt",
        "learning_assessments",
        ["attempt_id"],
        unique=True,
        sqlite_where=sa.text("attempt_id IS NOT NULL"),
        postgresql_where=sa.text("attempt_id IS NOT NULL"),
    )

    # SQLite cannot ADD a REFERENCES column directly. Rebuild this populated
    # table before creating the attempt child tables that point back to it.
    with op.batch_alter_table("learning_records", recreate="always") as batch:
        batch.add_column(sa.Column("attempt_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_learning_records_attempt",
            "assessment_attempts",
            ["attempt_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index("ix_learning_records_attempt", "learning_records", ["attempt_id"])
    op.add_column(
        "learning_assessment_revisions",
        sa.Column(
            "revision_source",
            sa.String(24),
            nullable=False,
            server_default=sa.text("'user_authored'"),
        ),
    )
    op.add_column(
        "learning_assessment_revisions", sa.Column("attempt_id", sa.String(36), nullable=True)
    )
    op.add_column(
        "learning_assessment_revisions",
        sa.Column("evaluator_team_member_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "learning_assessment_revisions",
        sa.Column("evaluator_agent_version_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "learning_assessment_revisions",
        sa.Column("editor_team_member_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "learning_assessment_revisions",
        sa.Column("editor_agent_version_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "learning_assessment_revisions",
        sa.Column("source_model_call_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "learning_assessment_revisions",
        sa.Column("source_tool_call_id", sa.String(120), nullable=True),
    )
    op.execute(
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
    op.execute(
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

    op.create_table(
        "learning_assessment_resource_grants",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("participant_id", sa.String(36), nullable=True),
        sa.Column("team_member_id", sa.String(36), nullable=True),
        sa.Column("agent_version_id", sa.String(36), nullable=False),
        sa.Column("agent_authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(8), nullable=False, server_default="edit"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("operation = 'edit'", name="ck_learning_assessment_grant_operation"),
        sa.CheckConstraint(
            "agent_authorization_epoch >= 0", name="ck_learning_assessment_grant_epoch"
        ),
        sa.CheckConstraint(
            "(participant_id IS NULL AND team_member_id IS NULL) OR "
            "(participant_id IS NOT NULL AND team_member_id IS NOT NULL)",
            name="ck_learning_assessment_grant_participant_pair",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"],
            ["learning_assessments.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_grant_assessment",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_grant_owner",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_grant_course",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_grant_conversation",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id", "conversation_id"],
            ["conversation_participants.id", "conversation_participants.conversation_id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_grant_participant",
        ),
        sa.ForeignKeyConstraint(
            ["team_member_id"],
            ["team_version_members.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_grant_team_member",
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id"],
            ["agent_versions.id"],
            ondelete="RESTRICT",
            name="fk_learning_assessment_grant_agent_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assessment_id", "participant_id", "operation", name="uq_learning_assessment_grant"
        ),
        sa.UniqueConstraint(
            "assessment_id",
            "agent_version_id",
            "operation",
            name="uq_learning_assessment_grant_version",
        ),
    )
    op.create_index(
        "ix_learning_assessment_grant_conversation",
        "learning_assessment_resource_grants",
        ["conversation_id", "revoked_at"],
    )

    op.create_table(
        "assessment_attempt_questions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("activity_id", sa.String(36), nullable=False),
        sa.Column("activity_question_id", sa.String(36), nullable=False),
        sa.Column("question_version_id", sa.String(36), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("content_json", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("resolution", sa.String(16), nullable=True),
        sa.Column("presented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_answer_record_id", sa.String(36), nullable=True),
        sa.CheckConstraint("ordinal >= 0", name="ck_assessment_attempt_question_ordinal"),
        sa.CheckConstraint(
            "status IN ('not_presented', 'presented', 'resolved')",
            name="ck_assessment_attempt_question_status",
        ),
        sa.CheckConstraint(
            "(status='not_presented' AND presented_at IS NULL AND question_version_id IS NULL "
            "AND content_json IS NULL AND content_hash IS NULL) OR "
            "(status IN ('presented', 'resolved') AND presented_at IS NOT NULL "
            "AND question_version_id IS NOT NULL AND content_json IS NOT NULL "
            "AND length(content_hash)=64)",
            name="ck_assessment_attempt_question_snapshot",
        ),
        sa.CheckConstraint(
            "(status='resolved' AND resolution IN ('answered', 'skipped') "
            "AND resolved_at IS NOT NULL) OR "
            "(status!='resolved' AND resolution IS NULL AND resolved_at IS NULL)",
            name="ck_assessment_attempt_question_resolution",
        ),
        sa.CheckConstraint(
            "(resolution='answered' AND effective_answer_record_id IS NOT NULL) OR "
            "(resolution IS NULL OR resolution='skipped') OR status!='resolved'",
            name="ck_assessment_attempt_question_effective_answer",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "activity_id"],
            ["assessment_attempts.id", "assessment_attempts.activity_id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_question_attempt",
        ),
        sa.ForeignKeyConstraint(
            ["activity_question_id", "activity_id"],
            ["assessment_activity_questions.id", "assessment_activity_questions.activity_id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_question_activity_question",
        ),
        sa.ForeignKeyConstraint(
            ["question_version_id"],
            ["knowledge_asset_versions.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_question_version",
        ),
        sa.ForeignKeyConstraint(
            ["effective_answer_record_id"],
            ["learning_records.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_question_effective_answer",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", "ordinal", name="uq_assessment_attempt_question_order"),
        sa.UniqueConstraint(
            "attempt_id", "activity_question_id", name="uq_assessment_attempt_question_once"
        ),
        sa.UniqueConstraint("id", "attempt_id", name="uq_assessment_attempt_question_scope"),
    )
    op.create_index(
        "ix_assessment_attempt_questions_attempt_status",
        "assessment_attempt_questions",
        ["attempt_id", "status", "ordinal"],
    )

    op.create_table(
        "assessment_attempt_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("activity_id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("client_event_id", sa.String(36), nullable=False),
        sa.Column("event_kind", sa.String(16), nullable=False),
        sa.Column("classification", sa.String(40), nullable=True),
        sa.Column("question_id", sa.String(36), nullable=True),
        sa.Column("learning_record_id", sa.String(36), nullable=True),
        sa.Column("replacement_attempt_id", sa.String(36), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_kind IN ('start', 'answer', 'skip', 'pause', 'resume', 'complete', 'restart', "
            "'abandon', 'withdraw')",
            name="ck_assessment_attempt_event_kind",
        ),
        sa.CheckConstraint(
            "classification IS NULL OR classification IN "
            "('start_request', 'restart_request', 'answer_only', "
            "'answer_with_restricted_request', 'skip_request', "
            "'pause_request', 'resume_request', 'complete_request', 'redo_request', "
            "'abandon_request', 'progress_request', 'answers_request', 'restricted_request', "
            "'off_topic')",
            name="ck_assessment_attempt_event_classification",
        ),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_assessment_attempt_event_hash"),
        sa.CheckConstraint(
            "(event_kind IN ('answer', 'skip') AND question_id IS NOT NULL) OR "
            "(event_kind NOT IN ('answer', 'skip') AND question_id IS NULL)",
            name="ck_assessment_attempt_event_question",
        ),
        sa.CheckConstraint(
            "(event_kind IN ('answer', 'skip') AND learning_record_id IS NOT NULL) OR "
            "(event_kind NOT IN ('answer', 'skip') AND learning_record_id IS NULL)",
            name="ck_assessment_attempt_event_learning_record",
        ),
        sa.CheckConstraint(
            "(event_kind='abandon' AND classification='redo_request' "
            "AND replacement_attempt_id IS NOT NULL) OR "
            "(event_kind='abandon' AND classification='abandon_request' "
            "AND replacement_attempt_id IS NULL) OR "
            "(event_kind!='abandon' AND replacement_attempt_id IS NULL)",
            name="ck_assessment_attempt_event_replacement",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["assessment_attempts.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_event_attempt",
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["assessment_activities.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_event_activity",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_event_actor",
        ),
        sa.ForeignKeyConstraint(
            ["question_id", "attempt_id"],
            ["assessment_attempt_questions.id", "assessment_attempt_questions.attempt_id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_event_question",
        ),
        sa.ForeignKeyConstraint(
            ["learning_record_id"],
            ["learning_records.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_event_learning_record",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_attempt_id"],
            ["assessment_attempts.id"],
            ondelete="RESTRICT",
            name="fk_assessment_attempt_event_replacement",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "activity_id",
            "actor_user_id",
            "client_event_id",
            name="uq_assessment_attempt_event_idempotency",
        ),
    )
    op.create_index(
        "ix_assessment_attempt_events_attempt",
        "assessment_attempt_events",
        ["attempt_id", "created_at"],
    )

    op.create_table(
        "learning_boundaries",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("activity_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("current_revision_seq", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("current_revision_seq >= 0", name="ck_learning_boundary_revision_seq"),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["assessment_attempts.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_attempt",
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["assessment_activities.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_activity",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_owner",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_course",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_conversation",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", name="uq_learning_boundary_attempt"),
        sa.UniqueConstraint("id", "attempt_id", name="uq_learning_boundary_attempt_scope"),
    )
    op.create_index(
        "ix_learning_boundaries_owner_course",
        "learning_boundaries",
        ["owner_user_id", "course_id"],
    )

    op.create_table(
        "learning_boundary_revisions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("boundary_id", sa.String(36), nullable=False),
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("revision_seq", sa.Integer(), nullable=False),
        sa.Column("previous_revision_id", sa.String(36), nullable=True),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("summarizer_team_member_id", sa.String(36), nullable=False),
        sa.Column("summarizer_agent_version_id", sa.String(36), nullable=False),
        sa.Column("source_model_call_id", sa.String(36), nullable=False),
        sa.Column("source_tool_call_id", sa.String(120), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision_seq >= 1", name="ck_learning_boundary_revision_number"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_learning_boundary_revision_hash"),
        sa.ForeignKeyConstraint(
            ["boundary_id", "attempt_id"],
            ["learning_boundaries.id", "learning_boundaries.attempt_id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_revision_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["boundary_id", "previous_revision_id"],
            ["learning_boundary_revisions.boundary_id", "learning_boundary_revisions.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_revision_previous",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_revision_actor",
        ),
        sa.ForeignKeyConstraint(
            ["summarizer_team_member_id"],
            ["team_version_members.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_revision_member",
        ),
        sa.ForeignKeyConstraint(
            ["summarizer_agent_version_id"],
            ["agent_versions.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_revision_agent_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "boundary_id", "revision_seq", name="uq_learning_boundary_revision_number"
        ),
        sa.UniqueConstraint("boundary_id", "id", name="uq_learning_boundary_revision_scoped_id"),
        sa.UniqueConstraint("id", "attempt_id", name="uq_learning_boundary_revision_attempt_scope"),
        sa.UniqueConstraint("source_tool_call_id", name="uq_learning_boundary_tool_call"),
    )
    op.create_index(
        "ix_learning_boundary_revision_history",
        "learning_boundary_revisions",
        ["boundary_id", "revision_seq"],
    )

    op.create_table(
        "learning_boundary_evidence",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("boundary_revision_id", sa.String(36), nullable=False),
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("learning_record_id", sa.String(36), nullable=True),
        sa.Column("assessment_revision_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(learning_record_id IS NOT NULL AND assessment_revision_id IS NULL) OR "
            "(learning_record_id IS NULL AND assessment_revision_id IS NOT NULL)",
            name="ck_learning_boundary_evidence_source",
        ),
        sa.ForeignKeyConstraint(
            ["boundary_revision_id", "attempt_id"],
            ["learning_boundary_revisions.id", "learning_boundary_revisions.attempt_id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_evidence_revision",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["assessment_attempts.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_evidence_attempt",
        ),
        sa.ForeignKeyConstraint(
            ["learning_record_id"],
            ["learning_records.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_evidence_learning_record",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_revision_id"],
            ["learning_assessment_revisions.id"],
            ondelete="RESTRICT",
            name="fk_learning_boundary_evidence_assessment_revision",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "boundary_revision_id",
            "learning_record_id",
            name="uq_learning_boundary_evidence_record",
        ),
        sa.UniqueConstraint(
            "boundary_revision_id",
            "assessment_revision_id",
            name="uq_learning_boundary_evidence_assessment",
        ),
    )
    op.create_index(
        "ix_learning_boundary_evidence_attempt",
        "learning_boundary_evidence",
        ["attempt_id"],
    )

    op.create_table(
        "assessment_course_reports",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("activity_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("current_revision_seq", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "current_revision_seq >= 1", name="ck_assessment_course_report_revision"
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_course",
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["assessment_activities.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_activity",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_id", "activity_id", name="uq_assessment_course_report_activity"
        ),
        sa.UniqueConstraint(
            "id", "course_id", "activity_id", name="uq_assessment_course_report_scope"
        ),
    )
    op.create_index(
        "ix_assessment_course_reports_owner",
        "assessment_course_reports",
        ["owner_user_id", "course_id"],
    )

    op.create_table(
        "assessment_course_report_revisions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("activity_id", sa.String(36), nullable=False),
        sa.Column("revision_seq", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("client_event_id", sa.String(36), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision_seq >= 1", name="ck_assessment_course_report_revision_seq"),
        sa.CheckConstraint(
            "length(request_hash) = 64", name="ck_assessment_course_report_request_hash"
        ),
        sa.CheckConstraint(
            "length(source_hash) = 64", name="ck_assessment_course_report_source_hash"
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "course_id", "activity_id"],
            [
                "assessment_course_reports.id",
                "assessment_course_reports.course_id",
                "assessment_course_reports.activity_id",
            ],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_revision_report",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_revision_actor",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "report_id", "revision_seq", name="uq_assessment_course_report_revision_seq"
        ),
        sa.UniqueConstraint("report_id", "id", name="uq_assessment_course_report_revision_scope"),
        sa.UniqueConstraint(
            "actor_user_id",
            "client_event_id",
            name="uq_assessment_course_report_request_idempotency",
        ),
    )
    op.create_index(
        "ix_assessment_course_report_revision_activity",
        "assessment_course_report_revisions",
        ["course_id", "activity_id", "revision_seq"],
    )

    op.create_table(
        "assessment_course_report_evidence",
        sa.Column("report_revision_id", sa.String(36), nullable=False),
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_revision_id"],
            ["assessment_course_report_revisions.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_evidence_revision",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["assessment_attempts.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_evidence_attempt",
        ),
        sa.PrimaryKeyConstraint("report_revision_id", "attempt_id"),
    )
    op.create_index(
        "ix_assessment_course_report_evidence_attempt",
        "assessment_course_report_evidence",
        ["attempt_id"],
    )

    op.create_table(
        "assessment_course_report_mutations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("client_event_id", sa.String(36), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(request_hash) = 64", name="ck_assessment_course_report_mutation_hash"
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_mutation_actor",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["assessment_course_reports.id"],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_mutation_report",
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "revision_id"],
            [
                "assessment_course_report_revisions.report_id",
                "assessment_course_report_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_assessment_course_report_mutation_revision",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_user_id",
            "client_event_id",
            name="uq_assessment_course_report_mutation_idempotency",
        ),
    )
    op.create_index(
        "ix_assessment_course_report_mutations_report",
        "assessment_course_report_mutations",
        ["report_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        # SQLite DDL and Alembic's revision write must succeed or roll back together.
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    if bind.dialect.name != "sqlite":
        raise RuntimeError("Assessment attempt downgrade requires the SQLite application database.")
    for table in (
        "assessment_course_report_mutations",
        "assessment_course_report_evidence",
        "assessment_course_report_revisions",
        "assessment_course_reports",
        "assessment_attempt_events",
        "assessment_attempt_questions",
        "assessment_attempts",
        "assessment_activity_questions",
        "assessment_activities",
    ):
        if bind.exec_driver_sql(f"SELECT 1 FROM {table} LIMIT 1").first() is not None:
            raise RuntimeError("Cannot downgrade saved assessment activities or attempts.")
    if bind.exec_driver_sql(
        "SELECT 1 FROM learning_records WHERE attempt_id IS NOT NULL LIMIT 1"
    ).first():
        raise RuntimeError("Cannot downgrade learning records linked to attempts.")
    if bind.exec_driver_sql(
        "SELECT 1 FROM learning_assessment_revisions "
        "WHERE revision_source != 'user_authored' OR attempt_id IS NOT NULL "
        "OR evaluator_team_member_id IS NOT NULL OR evaluator_agent_version_id IS NOT NULL "
        "OR editor_team_member_id IS NOT NULL OR editor_agent_version_id IS NOT NULL "
        "OR source_model_call_id IS NOT NULL OR source_tool_call_id IS NOT NULL LIMIT 1"
    ).first():
        raise RuntimeError("Cannot downgrade non-user Assessment provenance.")
    if bind.exec_driver_sql(
        "SELECT 1 FROM learning_assessments WHERE attempt_id IS NOT NULL LIMIT 1"
    ).first():
        raise RuntimeError("Cannot downgrade attempt-linked Assessment records.")
    if bind.exec_driver_sql("SELECT 1 FROM learning_assessment_resource_grants LIMIT 1").first():
        raise RuntimeError("Cannot downgrade saved Assessment resource grants.")

    op.execute("DROP TRIGGER ck_learning_assessment_revision_source_update")
    op.execute("DROP TRIGGER ck_learning_assessment_revision_source_insert")
    op.drop_column("learning_assessment_revisions", "editor_agent_version_id")
    op.drop_column("learning_assessment_revisions", "editor_team_member_id")
    op.drop_column("learning_assessment_revisions", "source_tool_call_id")
    op.drop_column("learning_assessment_revisions", "source_model_call_id")
    op.drop_column("learning_assessment_revisions", "evaluator_agent_version_id")
    op.drop_column("learning_assessment_revisions", "evaluator_team_member_id")
    op.drop_column("learning_assessment_revisions", "attempt_id")
    op.drop_column("learning_assessment_revisions", "revision_source")
    op.drop_index("ix_learning_records_attempt", table_name="learning_records")
    with op.batch_alter_table("learning_records", recreate="always") as batch:
        batch.drop_constraint("fk_learning_records_attempt", type_="foreignkey")
        batch.drop_column("attempt_id")
    op.drop_index("uq_learning_assessments_attempt", table_name="learning_assessments")
    op.drop_column("learning_assessments", "attempt_id")
    op.drop_index(
        "ix_learning_assessment_grant_conversation",
        table_name="learning_assessment_resource_grants",
    )
    op.drop_table("learning_assessment_resource_grants")
    op.drop_index("ix_learning_boundary_evidence_attempt", table_name="learning_boundary_evidence")
    op.drop_table("learning_boundary_evidence")
    op.drop_index("ix_learning_boundary_revision_history", table_name="learning_boundary_revisions")
    op.drop_table("learning_boundary_revisions")
    op.drop_index("ix_learning_boundaries_owner_course", table_name="learning_boundaries")
    op.drop_table("learning_boundaries")
    op.drop_index(
        "ix_assessment_course_report_mutations_report",
        table_name="assessment_course_report_mutations",
    )
    op.drop_table("assessment_course_report_mutations")
    op.drop_index(
        "ix_assessment_course_report_evidence_attempt",
        table_name="assessment_course_report_evidence",
    )
    op.drop_table("assessment_course_report_evidence")
    op.drop_index(
        "ix_assessment_course_report_revision_activity",
        table_name="assessment_course_report_revisions",
    )
    op.drop_table("assessment_course_report_revisions")
    op.drop_index("ix_assessment_course_reports_owner", table_name="assessment_course_reports")
    op.drop_table("assessment_course_reports")
    op.drop_index("ix_assessment_attempt_events_attempt", table_name="assessment_attempt_events")
    op.drop_table("assessment_attempt_events")
    op.drop_index(
        "ix_assessment_attempt_questions_attempt_status", table_name="assessment_attempt_questions"
    )
    op.drop_table("assessment_attempt_questions")
    op.drop_index("uq_assessment_attempt_active_per_actor_recipe", table_name="assessment_attempts")
    op.drop_index("ix_assessment_attempts_actor_activity", table_name="assessment_attempts")
    op.drop_table("assessment_attempts")
    op.drop_index(
        "ix_assessment_activity_questions_activity", table_name="assessment_activity_questions"
    )
    op.drop_table("assessment_activity_questions")
    op.drop_index("ix_assessment_activities_course_publication", table_name="assessment_activities")
    op.drop_table("assessment_activities")
