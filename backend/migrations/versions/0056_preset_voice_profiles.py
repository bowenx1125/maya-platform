"""Let one supplier preset share the system voice scope with the fallback.

The partial unique index still admits only one enrolled system fallback.
A preset row sets provenance ``kind`` to ``preset`` and is excluded from
that index. Existing voice rows are not rewritten.

Revision ID: 0056_preset_voice_profiles
Revises: 0055_assessment_attempt_submission
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0056_preset_voice_profiles"
down_revision: str | Sequence[str] | None = "0055_assessment_attempt_submission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NON_PRESET_SYSTEM = (
    "scope = 'system' AND COALESCE(json_extract(provenance_json, '$.kind'), '') != 'preset'"
)


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    op.drop_index("uq_voice_profiles_one_system", table_name="voice_profiles")
    op.create_index(
        "uq_voice_profiles_one_system",
        "voice_profiles",
        ["scope"],
        unique=True,
        sqlite_where=sa.text(_NON_PRESET_SYSTEM),
    )


def downgrade() -> None:
    _begin()
    connection = op.get_bind()
    system_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM voice_profiles WHERE scope = 'system'")
    ).scalar_one()
    if int(system_count or 0) > 1:
        raise RuntimeError("Cannot downgrade while more than one system voice profile exists.")
    op.drop_index("uq_voice_profiles_one_system", table_name="voice_profiles")
    op.create_index(
        "uq_voice_profiles_one_system",
        "voice_profiles",
        ["scope"],
        unique=True,
        sqlite_where=sa.text("scope = 'system'"),
    )
