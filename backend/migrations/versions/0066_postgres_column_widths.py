"""Widen columns that PostgreSQL enforces but SQLite never did.

* budget token counters: INTEGER -> BIGINT (2**63-1 is stored as "unbounded")
* budget cost columns: NUMERIC(12,6) -> NUMERIC(28,6)
* embedding_accepted_vectors.chunk_id: VARCHAR(36) -> VARCHAR(64) (sha256 ids)

SQLite does not enforce these widths, so the migration is a no-op there.
Downgrade intentionally keeps the wider types to avoid truncating data.

Revision ID: 0066_postgres_column_widths
Revises: 0065_auth_login_admission
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066_postgres_column_widths"
down_revision: str | Sequence[str] | None = "0065_auth_login_admission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALTERS = (
    ("provider_export_manifests", "max_total_tokens", sa.BigInteger()),
    ("provider_export_manifests", "max_cost_cny", sa.Numeric(28, 6)),
    ("provider_scope_budgets", "max_total_tokens", sa.BigInteger()),
    ("provider_scope_budgets", "max_cost_cny", sa.Numeric(28, 6)),
    ("provider_scope_budgets", "allocated_total_tokens", sa.BigInteger()),
    ("provider_scope_budgets", "allocated_cost_cny", sa.Numeric(28, 6)),
    ("embedding_accepted_vectors", "chunk_id", sa.String(length=64)),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table, column, type_ in _ALTERS:
        op.alter_column(table, column, type_=type_, existing_nullable=False)


def downgrade() -> None:
    return
