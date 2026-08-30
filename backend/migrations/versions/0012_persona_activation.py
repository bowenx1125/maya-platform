"""Persist the Persona requirement activation boundary.

Published and superseded rows are immutable legacy history and are not
backfilled.  Draft rows are mutable work that must satisfy PersonaSpecV1 before
their next publication, so activation marks every existing draft.  All product
creation paths explicitly mark new drafts as required.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_persona_activation"
down_revision: str | Sequence[str] | None = "0011_evidence_trace_json"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_versions",
        sa.Column(
            "persona_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        sa.text("UPDATE agent_versions SET persona_required = 1 WHERE state = 'draft'")
    )


def downgrade() -> None:
    op.drop_column("agent_versions", "persona_required")
