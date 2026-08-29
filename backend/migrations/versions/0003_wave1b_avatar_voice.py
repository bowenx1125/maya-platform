"""Wave 1B voice profiles, provider-operation ledger and previews.

The migration only adds new tables.  Existing Wave 0 and Wave 1A rows are
never rewritten, which keeps the populated ``0001 -> 0002 -> 0003`` upgrade
byte-for-byte for all pre-existing data.

Revision ID: 0003_wave1b_avatar_voice
Revises: 0002_wave1_agents_rag
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_wave1b_avatar_voice"
down_revision = "0002_wave1_agents_rag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("group_id", sa.String(36), nullable=True),
        sa.Column("display_name", sa.String(240), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="validating"),
        sa.Column("provider_key", sa.String(32), nullable=False),
        sa.Column("target_model_key", sa.String(120), nullable=False),
        sa.Column("external_id_encrypted", sa.LargeBinary, nullable=True),
        sa.Column("recovery_name", sa.String(120), nullable=False),
        sa.Column("provenance_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("source_filename", sa.String(255), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("consent_copy_version", sa.String(80), nullable=True),
        sa.Column("consent_actor_user_id", sa.String(36), nullable=True),
        sa.Column("consent_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('system', 'group')", name="ck_voice_profiles_scope"),
        sa.CheckConstraint(
            "status IN ('validating', 'enrolling', 'preview_ready', 'ready', 'deleting', "
            "'outcome_unknown', 'failed', 'deleted')",
            name="ck_voice_profiles_status",
        ),
        sa.CheckConstraint(
            "(scope = 'system' AND group_id IS NULL) OR (scope = 'group' AND group_id IS NOT NULL)",
            name="ck_voice_profiles_scope_group",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["groups.id"], name="fk_voice_profiles_group", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["consent_actor_user_id"],
            ["users.id"],
            name="fk_voice_profiles_consent_actor",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("recovery_name", name="uq_voice_profiles_recovery_name"),
    )
    op.create_index("ix_voice_profiles_group_status", "voice_profiles", ["group_id", "status"])
    op.create_index(
        "uq_voice_profiles_one_system",
        "voice_profiles",
        ["scope"],
        unique=True,
        sqlite_where=sa.text("scope = 'system'"),
    )

    op.create_table(
        "voice_provider_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("operation_type", sa.String(24), nullable=False),
        sa.Column("profile_scope", sa.String(16), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="prepared"),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        sa.Column("claim_token", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("provider_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("charged_request_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("input_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("safe_request_id", sa.String(120), nullable=True),
        sa.Column("safe_error_code", sa.String(64), nullable=True),
        sa.Column("idempotency_record_id", sa.String(36), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "operation_type IN ('enroll', 'delete', 'exists', 'tts_preview')",
            name="ck_voice_provider_operations_type",
        ),
        sa.CheckConstraint(
            "profile_scope IN ('system', 'group')",
            name="ck_voice_provider_operations_scope",
        ),
        sa.CheckConstraint(
            "state IN ('prepared', 'dispatched', 'reconciling', 'succeeded', 'failed', "
            "'outcome_unknown')",
            name="ck_voice_provider_operations_state",
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_voice_provider_operations_attempt"),
        sa.CheckConstraint(
            "request_count >= 0 AND charged_request_count >= 0 AND input_bytes >= 0 "
            "AND output_bytes >= 0",
            name="ck_voice_provider_operations_counters",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["voice_profiles.id"],
            name="fk_voice_provider_operations_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["idempotency_record_id"],
            ["idempotency_records.id"],
            name="fk_voice_provider_operations_idempotency",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_voice_provider_operations_profile",
        "voice_provider_operations",
        ["profile_id", "operation_type"],
    )
    op.create_index(
        "ix_voice_provider_operations_state_deadline",
        "voice_provider_operations",
        ["state", "provider_deadline"],
    )
    op.create_index(
        "uq_voice_provider_operations_system_enroll_active",
        "voice_provider_operations",
        ["profile_scope", "operation_type"],
        unique=True,
        sqlite_where=sa.text(
            "profile_scope = 'system' AND operation_type = 'enroll' "
            "AND state IN ('prepared', 'dispatched', 'reconciling', 'outcome_unknown')"
        ),
    )
    op.create_index(
        "uq_voice_provider_operations_profile_delete",
        "voice_provider_operations",
        ["profile_id"],
        unique=True,
        sqlite_where=sa.text("operation_type = 'delete'"),
    )

    op.create_table(
        "voice_previews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("group_id", sa.String(36), nullable=True),
        sa.Column("stored_file_id", sa.String(36), nullable=True),
        sa.Column("relative_path", sa.String(500), nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('active', 'expired', 'confirmed', 'replaced')",
            name="ck_voice_previews_state",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["voice_profiles.id"],
            name="fk_voice_previews_profile",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name="fk_voice_previews_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stored_file_id"],
            ["stored_files.id"],
            name="fk_voice_previews_stored_file",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_voice_previews_profile_state", "voice_previews", ["profile_id", "state"])
    op.create_index("ix_voice_previews_expiry", "voice_previews", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_voice_previews_expiry", table_name="voice_previews")
    op.drop_index("ix_voice_previews_profile_state", table_name="voice_previews")
    op.drop_table("voice_previews")
    op.drop_index(
        "uq_voice_provider_operations_profile_delete",
        table_name="voice_provider_operations",
    )
    op.drop_index(
        "uq_voice_provider_operations_system_enroll_active",
        table_name="voice_provider_operations",
    )
    op.drop_index(
        "ix_voice_provider_operations_state_deadline", table_name="voice_provider_operations"
    )
    op.drop_index("ix_voice_provider_operations_profile", table_name="voice_provider_operations")
    op.drop_table("voice_provider_operations")
    op.drop_index("uq_voice_profiles_one_system", table_name="voice_profiles")
    op.drop_index("ix_voice_profiles_group_status", table_name="voice_profiles")
    op.drop_table("voice_profiles")
