"""Keep others' material readable after its contributor's account is erased."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0087_account_author_links"
down_revision: str | Sequence[str] | None = "0086_student_group_choice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "knowledge_set_sources",
    "knowledge_assets",
    "knowledge_asset_versions",
    "agent_knowledge_sets",
    "knowledge_set_markdown_versions",
    "team_versions",
)


def upgrade() -> None:
    for table in TABLES:
        op.alter_column(table, "created_by_user_id", existing_type=sa.String(36), nullable=True)


def downgrade() -> None:
    # A downgrade after account erasure requires resolving null authors first;
    # the database refuses it rather than inventing historical attribution.
    for table in reversed(TABLES):
        op.alter_column(table, "created_by_user_id", existing_type=sa.String(36), nullable=False)
