"""Preserve repeated Team replies and exact Provider dispatch/consent stages."""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import op

revision: str = "0044_team_provider_stage"
down_revision: str | Sequence[str] | None = "0043_learning_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    "id,turn_id,conversation_id,participant_id,ordinal,state,assistant_text,sources_json,"
    "safe_error_code,created_at,completed_at"
)
_UNIQUE = "CONSTRAINT uq_team_result_participant UNIQUE (turn_id, participant_id)"
_CALL_SQL = """CREATE TABLE team_provider_calls (
id VARCHAR(36) NOT NULL PRIMARY KEY,
result_id VARCHAR(36) NOT NULL REFERENCES team_turn_results(id) ON DELETE RESTRICT,
ordinal INTEGER NOT NULL,
operation_id VARCHAR(36) NOT NULL UNIQUE REFERENCES provider_operations(id) ON DELETE RESTRICT,
request_hash VARCHAR(64) NOT NULL,
manifest_hash VARCHAR(64) NOT NULL
    REFERENCES provider_export_manifests(manifest_hash) ON DELETE RESTRICT,
request_json TEXT NOT NULL,
accepted_response_json TEXT,
accepted_response_hash VARCHAR(64),
created_at DATETIME NOT NULL,
accepted_at DATETIME,
CONSTRAINT uq_team_provider_call_ordinal UNIQUE(result_id,ordinal),
CONSTRAINT ck_team_provider_call_ordinal CHECK(ordinal>=0),
CONSTRAINT ck_team_provider_call_request_hash CHECK(length(request_hash)=64),
CONSTRAINT ck_team_provider_call_acceptance CHECK(
    (accepted_response_json IS NULL AND accepted_response_hash IS NULL AND accepted_at IS NULL)
    OR (accepted_response_json IS NOT NULL AND length(accepted_response_hash)=64
        AND accepted_at IS NOT NULL))
)"""
_STANDING_SQL = """CREATE TABLE team_provider_standing_grants (
id VARCHAR(36) NOT NULL PRIMARY KEY,
team_id VARCHAR(36) NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
team_version_id VARCHAR(36) NOT NULL REFERENCES team_versions(id) ON DELETE RESTRICT,
publication_id VARCHAR(36) NOT NULL REFERENCES course_team_publications(id) ON DELETE RESTRICT,
course_id VARCHAR(36) NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
publisher_user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
provider_operation VARCHAR(32) NOT NULL,
policy_hash VARCHAR(64) NOT NULL
    REFERENCES provider_policy_snapshots(policy_hash) ON DELETE RESTRICT,
resource_manifest_json TEXT NOT NULL,
resource_hash VARCHAR(64) NOT NULL,
team_epoch INTEGER NOT NULL,
publication_epoch INTEGER NOT NULL,
disclosure_revision INTEGER NOT NULL,
confirmed_at DATETIME NOT NULL,
revoked_at DATETIME,
CONSTRAINT ck_team_provider_standing_operation
    CHECK(provider_operation IN ('llm_agent_chat','embedding_query')),
CONSTRAINT ck_team_provider_standing_hash CHECK(length(resource_hash)=64),
CONSTRAINT ck_team_provider_standing_epochs
    CHECK(team_epoch>=0 AND publication_epoch>=0 AND disclosure_revision>=1)
)"""
_CONSENT_SQL = """CREATE TABLE team_provider_consent_bindings (
manifest_hash VARCHAR(64) NOT NULL PRIMARY KEY
    REFERENCES provider_export_manifests(manifest_hash) ON DELETE RESTRICT,
confirmation_id VARCHAR(36) NOT NULL UNIQUE
    REFERENCES provider_export_confirmations(id) ON DELETE RESTRICT,
result_id VARCHAR(36) NOT NULL REFERENCES team_turn_results(id) ON DELETE RESTRICT,
actor_user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
confirmer_user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
confirmer_kind VARCHAR(24) NOT NULL,
standing_grant_id VARCHAR(36) REFERENCES team_provider_standing_grants(id) ON DELETE RESTRICT,
team_epoch INTEGER NOT NULL,
publication_epoch INTEGER,
created_at DATETIME NOT NULL,
CONSTRAINT ck_team_provider_consent_kind
    CHECK(confirmer_kind IN ('custom_owner','publisher_teacher','published_chat_owner')),
CONSTRAINT ck_team_provider_consent_epochs
    CHECK(team_epoch>=0 AND (publication_epoch IS NULL OR publication_epoch>=0))
)"""


def _begin() -> set[tuple[object, ...]]:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError("Team Provider migration requires SQLite.")
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    if bind.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 0:
        raise RuntimeError("Cannot safely rebuild Team results in an existing transaction.")
    bind.exec_driver_sql("BEGIN IMMEDIATE")
    return {tuple(row) for row in bind.exec_driver_sql("PRAGMA foreign_key_check")}


def _rebuild(*, restore_unique: bool) -> None:
    bind = op.get_bind()
    sql = bind.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='team_turn_results'"
    ).scalar_one()
    if restore_unique:
        sql = sql.rstrip().removesuffix(")") + ",\n" + _UNIQUE + ")"
    else:
        sql, count = re.subn(
            r"CONSTRAINT\s+uq_team_result_participant\s+UNIQUE\s*"
            r"\(turn_id,\s*participant_id\),?",
            "",
            sql,
        )
        if count != 1:
            raise RuntimeError("0044 expected the existing Team participant constraint.")
        sql = re.sub(r",\s*\)$", "\n)", sql)
    sql = re.sub(
        r"CREATE TABLE\s+[\"`\[]?team_turn_results[\"`\]]?",
        "CREATE TABLE team_turn_results__0044_rebuild",
        sql,
        count=1,
    )
    objects = list(
        bind.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE tbl_name='team_turn_results' "
            "AND type IN ('index','trigger') AND sql IS NOT NULL ORDER BY type,name"
        ).scalars()
    )
    bind.exec_driver_sql(sql)
    bind.exec_driver_sql(
        f"INSERT INTO team_turn_results__0044_rebuild ({_COLUMNS}) "
        f"SELECT {_COLUMNS} FROM team_turn_results"
    )
    for left, right in (
        ("team_turn_results", "team_turn_results__0044_rebuild"),
        ("team_turn_results__0044_rebuild", "team_turn_results"),
    ):
        if (
            bind.exec_driver_sql(
                f"SELECT {_COLUMNS} FROM {left} EXCEPT SELECT {_COLUMNS} FROM {right}"
            ).first()
            is not None
        ):
            raise RuntimeError("0044 failed to preserve Team replies.")
    bind.exec_driver_sql("DROP TABLE team_turn_results")
    bind.exec_driver_sql("ALTER TABLE team_turn_results__0044_rebuild RENAME TO team_turn_results")
    for statement in objects:
        bind.exec_driver_sql(statement)


def _check(initial: set[tuple[object, ...]]) -> None:
    current = {tuple(row) for row in op.get_bind().exec_driver_sql("PRAGMA foreign_key_check")}
    if current - initial:
        raise RuntimeError("0044 introduced invalid Team Provider relationships.")


def upgrade() -> None:
    initial = _begin()
    bind = op.get_bind()
    try:
        _rebuild(restore_unique=False)
        bind.exec_driver_sql(_CALL_SQL)
        bind.exec_driver_sql(_STANDING_SQL)
        bind.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_team_provider_standing_scope ON team_provider_standing_grants "
            "(team_version_id,publication_id,provider_operation,policy_hash,resource_hash,"
            "publisher_user_id) WHERE revoked_at IS NULL"
        )
        bind.exec_driver_sql(_CONSENT_SQL)
        _check(initial)
    except Exception:
        bind.exec_driver_sql("ROLLBACK")
        raise


def downgrade() -> None:
    initial = _begin()
    bind = op.get_bind()
    try:
        if any(
            bind.exec_driver_sql(statement).first() is not None
            for statement in (
                "SELECT 1 FROM team_provider_calls LIMIT 1",
                "SELECT 1 FROM team_provider_consent_bindings LIMIT 1",
                "SELECT 1 FROM team_provider_standing_grants LIMIT 1",
                "SELECT 1 FROM team_turn_results GROUP BY turn_id,participant_id HAVING count(*)>1",
            )
        ):
            raise RuntimeError("Cannot downgrade saved Team Provider evidence or repeated replies.")
        bind.exec_driver_sql("DROP TABLE team_provider_calls")
        bind.exec_driver_sql("DROP TABLE team_provider_consent_bindings")
        bind.exec_driver_sql("DROP TABLE team_provider_standing_grants")
        _rebuild(restore_unique=True)
        _check(initial)
    except Exception:
        bind.exec_driver_sql("ROLLBACK")
        raise
