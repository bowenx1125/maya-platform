"""Add single-use login choices and session-local entry metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0088_bowen_identity_choice"
down_revision: str | Sequence[str] | None = "0087_account_author_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_identity_challenges",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("client_fingerprint_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_login_identity_challenges_expires_at", "login_identity_challenges", ["expires_at"]
    )
    op.add_column("sessions", sa.Column("entered_via_user_id", sa.String(36), nullable=True))
    op.add_column("sessions", sa.Column("active_course_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_sessions_entered_via",
        "sessions",
        "users",
        ["entered_via_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sessions_active_course",
        "sessions",
        "courses",
        ["active_course_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sessions_active_course", "sessions", type_="foreignkey")
    op.drop_constraint("fk_sessions_entered_via", "sessions", type_="foreignkey")
    op.drop_column("sessions", "active_course_id")
    op.drop_column("sessions", "entered_via_user_id")
    op.drop_index("ix_login_identity_challenges_expires_at", table_name="login_identity_challenges")
    op.drop_table("login_identity_challenges")
