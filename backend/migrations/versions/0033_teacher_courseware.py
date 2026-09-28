"""Mark teacher-contributed courseware in the shared knowledge library."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_teacher_courseware"
down_revision: str | Sequence[str] | None = "0032_recovery_input_unbounded"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledge_documents"
_OWNER_ROLE_CHECK = "ck_knowledge_documents_source_owner_role"


def upgrade() -> None:
    with op.batch_alter_table(_TABLE, recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "source_owner_role",
                sa.String(length=16),
                nullable=False,
                server_default="student",
            )
        )
        batch.create_check_constraint(
            _OWNER_ROLE_CHECK,
            "source_owner_role IN ('student', 'teacher')",
        )


def downgrade() -> None:
    with op.batch_alter_table(_TABLE, recreate="always") as batch:
        batch.drop_constraint(_OWNER_ROLE_CHECK, type_="check")
        batch.drop_column("source_owner_role")
