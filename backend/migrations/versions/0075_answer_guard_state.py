"""Assessment: server-side relevance guard state per attempt question.

2026-10-20 owner design: the program, not the prompt, decides when a free
answer is recorded. Per attempt question it keeps whether the reply was judged
off-topic once, the reply awaiting 确认 and the last unrecorded reply. One
nullable column; existing rows keep NULL (empty state). Nothing is rewritten.

Revision ID: 0075_answer_guard_state
Revises: 0074_interaction_voter_key
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075_answer_guard_state"
down_revision: str | Sequence[str] | None = "0074_interaction_voter_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("assessment_attempt_questions") as batch:
        batch.add_column(sa.Column("guard_state_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("assessment_attempt_questions") as batch:
        batch.drop_column("guard_state_json")
