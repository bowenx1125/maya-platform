"""Store course-scoped standing consent for exact Chat disclosure classes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050_chat_provider_standing_grants"
down_revision: str | Sequence[str] | None = "0049_runtime_model_call_stages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        # SQLite DDL and Alembic's revision write must succeed or roll back together.
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    op.create_table(
        "chat_provider_standing_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_operation", sa.String(32), nullable=False),
        sa.Column(
            "policy_hash",
            sa.String(64),
            sa.ForeignKey("provider_policy_snapshots.policy_hash", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("field_classes_json", sa.Text(), nullable=False),
        sa.Column("field_classes_hash", sa.String(64), nullable=False),
        sa.Column(
            "confirmed_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider_operation IN ('llm_agent_chat', 'embedding_query')",
            name="ck_chat_provider_standing_operation",
        ),
        sa.CheckConstraint("length(field_classes_hash)=64", name="ck_chat_provider_standing_hash"),
    )
    op.create_index(
        "uq_chat_provider_standing_scope",
        "chat_provider_standing_grants",
        [
            "course_id",
            "provider_operation",
            "policy_hash",
            "field_classes_hash",
            "confirmed_by_user_id",
        ],
        unique=True,
        sqlite_where=sa.text("revoked_at IS NULL"),
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "chat_provider_consent_bindings",
        sa.Column(
            "manifest_hash",
            sa.String(64),
            sa.ForeignKey("provider_export_manifests.manifest_hash", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "confirmation_id",
            sa.String(36),
            sa.ForeignKey("provider_export_confirmations.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("agent_conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "confirmed_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "standing_grant_id",
            sa.String(36),
            sa.ForeignKey("chat_provider_standing_grants.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(manifest_hash)=64", name="ck_chat_provider_consent_manifest_hash"
        ),
    )
    op.create_index(
        "ix_chat_provider_consent_conversation",
        "chat_provider_consent_bindings",
        ["conversation_id"],
    )
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            """CREATE TRIGGER chat_provider_standing_grant_immutable
            BEFORE UPDATE ON chat_provider_standing_grants
            WHEN NEW.id IS NOT OLD.id
              OR NEW.course_id IS NOT OLD.course_id
              OR NEW.provider_operation IS NOT OLD.provider_operation
              OR NEW.policy_hash IS NOT OLD.policy_hash
              OR NEW.field_classes_json IS NOT OLD.field_classes_json
              OR NEW.field_classes_hash IS NOT OLD.field_classes_hash
              OR NEW.confirmed_by_user_id IS NOT OLD.confirmed_by_user_id
              OR NEW.confirmed_at IS NOT OLD.confirmed_at
              OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS NOT OLD.revoked_at)
            BEGIN SELECT RAISE(ABORT, 'chat_provider_standing_immutable'); END"""
        )
        op.execute(
            """CREATE TRIGGER chat_provider_consent_binding_immutable
            BEFORE UPDATE ON chat_provider_consent_bindings
            BEGIN SELECT RAISE(ABORT, 'chat_provider_consent_immutable'); END"""
        )
        op.execute(
            """CREATE TRIGGER chat_provider_consent_binding_no_delete
            BEFORE DELETE ON chat_provider_consent_bindings
            BEGIN SELECT RAISE(ABORT, 'chat_provider_consent_immutable'); END"""
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        # SQLite DDL and Alembic's revision write must succeed or roll back together.
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    if bind.exec_driver_sql("SELECT 1 FROM chat_provider_consent_bindings LIMIT 1").first():
        raise RuntimeError("Cannot discard exact Chat provider consent evidence.")
    if bind.exec_driver_sql("SELECT 1 FROM chat_provider_standing_grants LIMIT 1").first():
        raise RuntimeError("Cannot discard Chat provider standing grants.")
    if bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER chat_provider_consent_binding_no_delete")
        op.execute("DROP TRIGGER chat_provider_consent_binding_immutable")
        op.execute("DROP TRIGGER chat_provider_standing_grant_immutable")
    op.drop_index(
        "ix_chat_provider_consent_conversation",
        table_name="chat_provider_consent_bindings",
    )
    op.drop_table("chat_provider_consent_bindings")
    op.drop_index("uq_chat_provider_standing_scope", table_name="chat_provider_standing_grants")
    op.drop_table("chat_provider_standing_grants")
