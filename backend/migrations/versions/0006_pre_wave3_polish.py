"""Add mutable Agent metadata CAS and teacher-gated whole replay state.

Revision ID: 0006_pre_wave3_polish
Revises: 0005_wave2_manual_advance

The delta preserves every historical Agent/version/snapshot/debate row.  It
adds only the Agent-level description revision and the persisted whole-replay
queue needed to recover a replay waiting for the teacher's Next command.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_pre_wave3_polish"
down_revision = "0005_wave2_manual_advance"
branch_labels = None
depends_on = None


_WAITING_NEXT_MODE_CHECK = (
    "status != 'waiting_next' OR "
    "(current_turn_id IS NOT NULL AND ((mode = 'live' "
    "AND replay_scope IS NULL AND replay_index IS NULL) OR "
    "(mode = 'replay' AND replay_scope = 'all' "
    "AND replay_index IS NOT NULL AND replay_index >= 0)))"
)

_WAITING_NEXT_LIVE_CHECK = (
    "status != 'waiting_next' OR "
    "(mode = 'live' AND current_turn_id IS NOT NULL "
    "AND replay_scope IS NULL AND replay_index IS NULL)"
)


def _add_agent_metadata_revision() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # Do not batch-recreate ``agents``.  It is the ON DELETE CASCADE parent
        # of ``agent_versions`` and SQLite cannot reliably change
        # ``foreign_keys`` inside Alembic's migration transaction.  Native
        # ADD COLUMN keeps every child row in place.  SQLite cannot later DROP
        # a column referenced by an inline CHECK, so equivalent INSERT/UPDATE
        # triggers enforce the non-negative invariant and are dropped before
        # the native downgrade.
        op.execute(
            sa.text("ALTER TABLE agents ADD COLUMN metadata_revision INTEGER NOT NULL DEFAULT 0")
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER ck_agents_metadata_revision_nonnegative_insert "
                "BEFORE INSERT ON agents "
                "WHEN NEW.metadata_revision < 0 "
                "BEGIN SELECT RAISE(ABORT, "
                "'ck_agents_metadata_revision_nonnegative'); END"
            )
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER ck_agents_metadata_revision_nonnegative_update "
                "BEFORE UPDATE OF metadata_revision ON agents "
                "WHEN NEW.metadata_revision < 0 "
                "BEGIN SELECT RAISE(ABORT, "
                "'ck_agents_metadata_revision_nonnegative'); END"
            )
        )
        return

    op.add_column(
        "agents",
        sa.Column(
            "metadata_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_agents_metadata_revision_nonnegative",
        "agents",
        "metadata_revision >= 0",
    )


def _drop_agent_metadata_revision() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite 3.35+ supports native DROP COLUMN.  Using it is essential:
        # batch recreation of this referenced parent can cascade-delete
        # AgentVersion/Snapshot/Debate history during downgrade.
        op.execute(sa.text("DROP TRIGGER IF EXISTS ck_agents_metadata_revision_nonnegative_insert"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS ck_agents_metadata_revision_nonnegative_update"))
        op.execute(sa.text("ALTER TABLE agents DROP COLUMN metadata_revision"))
        return

    op.drop_constraint("ck_agents_metadata_revision_nonnegative", "agents", type_="check")
    op.drop_column("agents", "metadata_revision")


def upgrade() -> None:
    _add_agent_metadata_revision()

    # Server-only derived state for the private Demo Markdown catalog.  It
    # binds an immutable account key to its historical User UUID and persists
    # the material fingerprint used to revoke sessions only when credentials,
    # role, group, username or active state truly changed across restarts.
    op.create_table(
        "demo_account_bindings",
        sa.Column("account_key", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("material_fingerprint", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_demo_account_bindings_user",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_demo_account_bindings_user_id",
        "demo_account_bindings",
        ["user_id"],
        unique=True,
    )
    op.create_index(
        "ix_demo_account_bindings_active",
        "demo_account_bindings",
        ["active"],
    )

    # Generic, server-only redacted audit envelope.  A local operator reset
    # may commit only when its state transition and this record commit in the
    # same SQLite writer transaction.
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("actor_kind", sa.String(24), nullable=True),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("course_id", sa.String(36), nullable=True),
        sa.Column("debate_id", sa.String(36), nullable=True),
        sa.Column("request_id", sa.String(36), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(event_type)) > 0",
            name="ck_audit_logs_event_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(details_json)) > 0",
            name="ck_audit_logs_details_nonempty",
        ),
    )
    op.create_index(
        "ix_audit_logs_debate_created",
        "audit_logs",
        ["debate_id", "created_at"],
    )
    op.create_index(
        "ix_audit_logs_event_created",
        "audit_logs",
        ["event_type", "created_at"],
    )

    with op.batch_alter_table("playback_states", recreate="always") as batch:
        batch.drop_constraint("ck_playback_states_waiting_next_live", type_="check")
        batch.add_column(
            sa.Column(
                "replay_turn_ids_json",
                sa.Text(),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("pending_action", sa.String(8), nullable=True))
        batch.add_column(sa.Column("pending_ticket_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("pending_media_command_id", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column(
                "audio_duration_ms",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.create_check_constraint(
            "ck_playback_states_waiting_next_mode",
            _WAITING_NEXT_MODE_CHECK,
        )
        batch.create_check_constraint(
            "ck_playback_states_pending_action",
            "pending_action IS NULL OR pending_action IN ('start', 'resume', 'next', 'replay')",
        )
        batch.create_check_constraint(
            "ck_playback_states_audio_duration",
            "audio_duration_ms >= 0",
        )


def downgrade() -> None:
    # No old release may resume an in-progress teacher-paced replay using its
    # former automatic semantics.  Convert every replay state to a conservative
    # completed live view and clear controller/replay authority while retaining
    # Debate/Turn/history rows and the course audio pointer.
    op.execute(
        sa.text(
            "UPDATE playback_states SET status='completed', mode='live', "
            "current_turn_id=NULL, cursor_ms=0, controller_epoch=NULL, "
            "controller_owner_connection=NULL, server_started_at=NULL, "
            "replay_scope=NULL, replay_index=NULL, replay_turn_ids_json='[]', "
            "pending_action=NULL, pending_ticket_hash=NULL, "
            "pending_media_command_id=NULL, audio_duration_ms=0 "
            "WHERE mode='replay'"
        )
    )
    with op.batch_alter_table("playback_states", recreate="always") as batch:
        batch.drop_constraint("ck_playback_states_waiting_next_mode", type_="check")
        batch.drop_constraint("ck_playback_states_pending_action", type_="check")
        batch.drop_constraint("ck_playback_states_audio_duration", type_="check")
        batch.drop_column("audio_duration_ms")
        batch.drop_column("pending_media_command_id")
        batch.drop_column("pending_ticket_hash")
        batch.drop_column("pending_action")
        batch.drop_column("replay_turn_ids_json")
        batch.create_check_constraint(
            "ck_playback_states_waiting_next_live",
            _WAITING_NEXT_LIVE_CHECK,
        )

    op.drop_index("ix_audit_logs_event_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_debate_created", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_demo_account_bindings_active", table_name="demo_account_bindings")
    op.drop_index("ix_demo_account_bindings_user_id", table_name="demo_account_bindings")
    op.drop_table("demo_account_bindings")

    _drop_agent_metadata_revision()
