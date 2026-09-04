"""Record which language a Debate is generated in.

Speech was English by assertion in three separate validators and by a
word-count regex that only matches Latin letters, so a Chinese debate could not
be produced and could not have been detected as unsupported except by failing.
The choice belongs to the Debate, is made when the teacher starts it, and is
read from one place afterwards.

Existing rows are English: that is what they were generated in.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_debate_output_language"
down_revision: str | Sequence[str] | None = "0018_remove_translation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "debates",
        sa.Column(
            "output_language",
            sa.String(length=8),
            nullable=False,
            server_default="en",
        ),
    )


def downgrade() -> None:
    # A plain DROP COLUMN, not a batch rebuild. SQLite has supported dropping a
    # column outright since 3.35, and recreating ``debates`` to remove one
    # nullable column made the rebuild itself the risk: every turn, playback
    # state and interaction row points at that table.
    op.drop_column("debates", "output_language")
