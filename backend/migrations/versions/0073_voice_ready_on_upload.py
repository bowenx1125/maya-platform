"""Uploaded voices are ready at once: promote clean preview-ready profiles.

Owner decision 2026-10-19: a successfully uploaded voice is selectable right
away, with no listen-to-the-end confirmation. Group and personal profiles that
finished enrolling cleanly (``preview_ready`` with no safe error) become
``ready``. Profiles a TTS check marked with an error, system fallback voices
and every other status are left as they are. No row is deleted.

Revision ID: 0073_voice_ready_on_upload
Revises: 0072_attempt_teacher_hidden
Create Date: 2026-10-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0073_voice_ready_on_upload"
down_revision: str | Sequence[str] | None = "0072_attempt_teacher_hidden"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    op.get_bind().exec_driver_sql(
        "UPDATE voice_profiles SET status = 'ready', updated_at = CURRENT_TIMESTAMP "
        "WHERE status = 'preview_ready' AND scope IN ('group', 'personal') "
        "AND safe_error_code IS NULL"
    )


def downgrade() -> None:
    # Data-only promotion; which rows were preview-ready is not recorded, and
    # demoting ready voices would make bound Agents unselectable again.
    _begin()
