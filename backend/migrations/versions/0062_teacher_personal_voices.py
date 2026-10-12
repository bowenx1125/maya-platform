"""Let a teacher keep personal voices that belong to no group."""

import re
from collections.abc import Sequence

from alembic import op

revision: str = "0062_teacher_personal_voices"
down_revision: str | Sequence[str] | None = "0061_personal_agent_debaters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE = "CONSTRAINT ck_voice_profiles_scope CHECK (scope IN ('system', 'group'))"
_PERSONAL_SCOPE = (
    "CONSTRAINT ck_voice_profiles_scope CHECK (scope IN ('system', 'group', 'personal'))"
)
_SCOPE_GROUP = (
    "CONSTRAINT ck_voice_profiles_scope_group CHECK "
    "((scope = 'system' AND group_id IS NULL) OR (scope = 'group' AND group_id IS NOT NULL))"
)
# The owner stays enforced in code: consent_actor_user_id is ON DELETE SET NULL,
# and an ownerless personal voice is shown to nobody.
_PERSONAL_SCOPE_GROUP = (
    "CONSTRAINT ck_voice_profiles_scope_group CHECK "
    "((scope = 'system' AND group_id IS NULL) OR (scope = 'group' AND group_id IS NOT NULL) "
    "OR (scope = 'personal' AND group_id IS NULL))"
)
_OPERATION_SCOPE = (
    "CONSTRAINT ck_voice_provider_operations_scope CHECK (profile_scope IN ('system', 'group'))"
)
_PERSONAL_OPERATION_SCOPE = (
    "CONSTRAINT ck_voice_provider_operations_scope CHECK "
    "(profile_scope IN ('system', 'group', 'personal'))"
)


def _begin() -> set[tuple[object, ...]]:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError("The voice scope migration requires the SQLite database.")
    # Agent versions, Debate participants and provider ledgers reference voice
    # profiles, so the rebuilt table cannot be dropped with enforcement on.
    # migrations/env.py restores it after the enclosing transaction.
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    if bind.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 0:
        raise RuntimeError("Cannot safely rebuild voice profiles inside an existing transaction.")
    bind.exec_driver_sql("BEGIN IMMEDIATE")
    return {tuple(row) for row in bind.exec_driver_sql("PRAGMA foreign_key_check")}


def _rebuild_table(table: str, replacements: tuple[tuple[str, str], ...]) -> None:
    """SQLite cannot alter a CHECK in place: copy into a rebuilt table."""

    bind = op.get_bind()
    table_sql = bind.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).scalar_one()
    normalized = " ".join(table_sql.split()).replace("( ", "(").replace(" )", ")")
    for old, new in replacements:
        if normalized.count(old) != 1:
            raise RuntimeError(f"{table} does not have the expected scope checks.")
        normalized = normalized.replace(old, new)
    indexes = [
        row[0]
        for row in bind.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
            (table,),
        )
    ]
    rebuilt = f"{table}_0062"
    # A table that was renamed or built from metadata stores its name quoted.
    create, count = re.subn(
        rf'^CREATE TABLE "?{table}"? \(', f"CREATE TABLE {rebuilt} (", normalized, count=1
    )
    if count != 1:
        raise RuntimeError(f"{table} has an unexpected definition.")
    bind.exec_driver_sql(create)
    bind.exec_driver_sql(f"INSERT INTO {rebuilt} SELECT * FROM {table}")
    bind.exec_driver_sql(f"DROP TABLE {table}")
    bind.exec_driver_sql(f"ALTER TABLE {rebuilt} RENAME TO {table}")
    for statement in indexes:
        bind.exec_driver_sql(statement)


def _rebuild(
    profile_replacements: tuple[tuple[str, str], ...],
    operation_replacements: tuple[tuple[str, str], ...],
    initial: set[tuple[object, ...]],
) -> None:
    bind = op.get_bind()
    try:
        _rebuild_table("voice_profiles", profile_replacements)
        _rebuild_table("voice_provider_operations", operation_replacements)
        current = {tuple(row) for row in bind.exec_driver_sql("PRAGMA foreign_key_check")}
        if current - initial:
            raise RuntimeError("0062 introduced invalid voice profile relationships.")
    except Exception:
        bind.exec_driver_sql("ROLLBACK")
        raise


def upgrade() -> None:
    _rebuild(
        ((_SCOPE, _PERSONAL_SCOPE), (_SCOPE_GROUP, _PERSONAL_SCOPE_GROUP)),
        ((_OPERATION_SCOPE, _PERSONAL_OPERATION_SCOPE),),
        _begin(),
    )


def downgrade() -> None:
    initial = _begin()
    personal = op.get_bind().exec_driver_sql(
        "SELECT 1 FROM voice_profiles WHERE scope = 'personal' LIMIT 1"
    )
    if personal.first() is not None:
        op.get_bind().exec_driver_sql("ROLLBACK")
        raise RuntimeError("Cannot downgrade while a teacher keeps a personal voice")
    _rebuild(
        ((_PERSONAL_SCOPE, _SCOPE), (_PERSONAL_SCOPE_GROUP, _SCOPE_GROUP)),
        ((_PERSONAL_OPERATION_SCOPE, _OPERATION_SCOPE),),
        initial,
    )
