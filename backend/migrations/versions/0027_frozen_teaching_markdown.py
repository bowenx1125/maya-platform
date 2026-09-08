"""Freeze Markdown teaching defaults for existing four-round records."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0027_frozen_teaching_markdown"
down_revision = "0026_debate_background"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.modules.debates.teaching_rules import freeze_teaching_rules

    bind = op.get_bind()
    defaults = freeze_teaching_rules()
    rows = bind.execute(sa.text("SELECT id, rule_snapshot_json FROM debates")).all()
    for debate_id, raw in rows:
        snapshot = json.loads(raw)
        if snapshot.get("teaching_protocol") != "four_round_v1" or "system_prompts" in snapshot:
            continue
        snapshot.update(defaults)
        bind.execute(
            sa.text("UPDATE debates SET rule_snapshot_json=:value WHERE id=:id"),
            {"id": debate_id, "value": json.dumps(snapshot, sort_keys=True, separators=(",", ":"))},
        )


def downgrade() -> None:
    # Retain frozen text: losing it would change already-created lessons.
    pass
