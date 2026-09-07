"""Allow a turn to cite verified evidence first published by another Agent."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_shared_discussion_evidence"
down_revision: str | Sequence[str] | None = "0023_segment_report_wordcount"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Turn ownership and immutable chunk scope remain database constraints.
    # The four-round runtime separately requires the exact original receipt
    # from a completed predecessor before accepting another Agent's evidence.
    # No table references turn_sources, so its rebuild needs no FK-disable fence.
    with op.batch_alter_table("turn_sources", recreate="always") as batch:
        batch.drop_constraint("fk_turn_sources_participant_snapshot", type_="foreignkey")


def downgrade() -> None:
    shared = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM turn_sources AS s "
                "JOIN debate_participants AS p ON p.id=s.participant_id "
                "WHERE s.snapshot_id<>p.knowledge_snapshot_id"
            )
        )
        .scalar_one()
    )
    if shared:
        raise RuntimeError("Cannot downgrade while shared discussion evidence is retained")
    with op.batch_alter_table("turn_sources", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_turn_sources_participant_snapshot",
            "debate_participants",
            ["participant_id", "snapshot_id"],
            ["id", "knowledge_snapshot_id"],
            ondelete="RESTRICT",
        )
