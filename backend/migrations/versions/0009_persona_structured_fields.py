"""Add nullable structured Persona/confirmation fields to AgentVersion.

Legacy published rows are intentionally not backfilled.  New draft writers
populate the hash/structured fields through the Persona service and retain the
existing ``agent_md`` column as the sole raw authored source.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_persona_structured_fields"
down_revision: str | Sequence[str] | None = "0008_wave4_mutual_learning_rounds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COMPILATION_CHECK = (
    "((persona_spec_json IS NULL AND persona_spec_hash IS NULL "
    "AND persona_compiler_version IS NULL) OR "
    "(persona_spec_json IS NOT NULL AND persona_spec_hash IS NOT NULL "
    "AND persona_compiler_version IS NOT NULL))"
)
_CONFIRMATION_CHECK = (
    "((persona_confirmation_revision IS NULL AND student_confirmed_at IS NULL "
    "AND persona_confirming_user_id IS NULL) OR "
    "(persona_confirmation_revision IS NOT NULL AND student_confirmed_at IS NOT NULL "
    "AND persona_confirming_user_id IS NOT NULL))"
)
_CONFIRMATION_REVISION_CHECK = (
    "persona_confirmation_revision IS NULL OR persona_confirmation_revision = revision"
)
_TRIGGER_COMPILATION_CHECK = (
    "((NEW.persona_spec_json IS NULL AND NEW.persona_spec_hash IS NULL "
    "AND NEW.persona_compiler_version IS NULL) OR "
    "(NEW.persona_spec_json IS NOT NULL AND NEW.persona_spec_hash IS NOT NULL "
    "AND NEW.persona_compiler_version IS NOT NULL))"
)
_TRIGGER_CONFIRMATION_CHECK = (
    "((NEW.persona_confirmation_revision IS NULL AND NEW.student_confirmed_at IS NULL "
    "AND NEW.persona_confirming_user_id IS NULL) OR "
    "(NEW.persona_confirmation_revision IS NOT NULL AND NEW.student_confirmed_at IS NOT NULL "
    "AND NEW.persona_confirming_user_id IS NOT NULL))"
)
_TRIGGER_CONFIRMATION_REVISION_CHECK = (
    "NEW.persona_confirmation_revision IS NULL OR NEW.persona_confirmation_revision = NEW.revision"
)
_TRIGGER_RAW_EDIT_CHECK = (
    "NEW.agent_md = OLD.agent_md OR "
    "(NEW.persona_spec_json IS NULL AND NEW.persona_spec_hash IS NULL AND "
    "NEW.persona_compiler_version IS NULL AND "
    "NEW.persona_confirmation_revision IS NULL AND "
    "NEW.student_confirmed_at IS NULL AND NEW.persona_confirming_user_id IS NULL)"
)

_COLUMNS = (
    sa.Column("raw_agent_md_hash", sa.String(71), nullable=True),
    sa.Column("persona_spec_json", sa.Text(), nullable=True),
    sa.Column("persona_spec_hash", sa.String(64), nullable=True),
    sa.Column("persona_compiler_version", sa.String(64), nullable=True),
    sa.Column("persona_diagnostics_json", sa.Text(), nullable=True),
    sa.Column("persona_confirmation_revision", sa.Integer(), nullable=True),
    sa.Column("student_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("persona_confirming_user_id", sa.String(36), nullable=True),
)

_INSERT_TRIGGER = "ck_agent_versions_persona_fields_insert"
_UPDATE_TRIGGER = "ck_agent_versions_persona_fields_update"


def _add_columns() -> None:
    for column in _COLUMNS:
        op.add_column("agent_versions", column)


def _add_checks() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite cannot add a CHECK to an existing table without rebuilding
        # the AgentVersion parent of several immutable child tables.  Triggers
        # enforce the same all-or-none shape while keeping all history rows in
        # place and make the native downgrade reversible.
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {_INSERT_TRIGGER} BEFORE INSERT ON agent_versions "
                f"WHEN NOT ({_TRIGGER_COMPILATION_CHECK} AND {_TRIGGER_CONFIRMATION_CHECK} "
                f"AND ({_TRIGGER_CONFIRMATION_REVISION_CHECK})) BEGIN SELECT RAISE(ABORT, "
                "'ck_agent_versions_persona_fields'); END"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {_UPDATE_TRIGGER} BEFORE UPDATE OF revision, "
                "agent_md, raw_agent_md_hash, persona_spec_json, persona_spec_hash, "
                "persona_compiler_version, persona_diagnostics_json, "
                "persona_confirmation_revision, student_confirmed_at, "
                "persona_confirming_user_id ON agent_versions "
                f"WHEN NOT ({_TRIGGER_COMPILATION_CHECK} AND {_TRIGGER_CONFIRMATION_CHECK} "
                f"AND ({_TRIGGER_RAW_EDIT_CHECK}) "
                f"AND ({_TRIGGER_CONFIRMATION_REVISION_CHECK})) BEGIN SELECT RAISE(ABORT, "
                "'ck_agent_versions_persona_fields'); END"
            )
        )
        return
    op.create_check_constraint(
        "ck_agent_versions_persona_compilation_fields",
        "agent_versions",
        _COMPILATION_CHECK,
    )
    op.create_check_constraint(
        "ck_agent_versions_persona_confirmation_fields",
        "agent_versions",
        _CONFIRMATION_CHECK,
    )
    op.create_check_constraint(
        "ck_agent_versions_persona_confirmation_revision",
        "agent_versions",
        _CONFIRMATION_REVISION_CHECK,
    )


def upgrade() -> None:
    _add_columns()
    _add_checks()


def _assert_lossless_downgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM agent_versions WHERE "
            "raw_agent_md_hash IS NOT NULL OR persona_spec_json IS NOT NULL OR "
            "persona_spec_hash IS NOT NULL OR persona_compiler_version IS NOT NULL OR "
            "persona_diagnostics_json IS NOT NULL OR persona_confirmation_revision IS NOT NULL OR "
            "student_confirmed_at IS NOT NULL OR persona_confirming_user_id IS NOT NULL LIMIT 1"
        )
    ).first()
    if row is not None:
        raise RuntimeError("Cannot downgrade 0009 while AgentVersion Persona fields contain data.")


def _drop_checks() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {_UPDATE_TRIGGER}"))
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {_INSERT_TRIGGER}"))
        return
    op.drop_constraint(
        "ck_agent_versions_persona_confirmation_revision", "agent_versions", type_="check"
    )
    op.drop_constraint(
        "ck_agent_versions_persona_confirmation_fields", "agent_versions", type_="check"
    )
    op.drop_constraint(
        "ck_agent_versions_persona_compilation_fields", "agent_versions", type_="check"
    )


def downgrade() -> None:
    _assert_lossless_downgrade()
    _drop_checks()
    for column in reversed(_COLUMNS):
        op.drop_column("agent_versions", column.name)
