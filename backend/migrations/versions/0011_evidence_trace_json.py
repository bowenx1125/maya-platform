"""Persist immutable public EvidenceTraceV1 rows with each DebateTurn."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_evidence_trace_json"
down_revision: str | Sequence[str] | None = "0010_provider_control_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "debate_turns",
        sa.Column(
            "evidence_trace_json",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    populated = bind.execute(
        sa.text(
            "SELECT 1 FROM debate_turns "
            "WHERE trim(COALESCE(evidence_trace_json, '[]')) NOT IN ('', '[]') LIMIT 1"
        )
    ).first()
    if populated is not None:
        raise RuntimeError("Cannot downgrade 0011 while EvidenceTrace rows are retained.")
    op.drop_column("debate_turns", "evidence_trace_json")
