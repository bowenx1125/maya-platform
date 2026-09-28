"""Atomicity and rollback coverage for the additive Knowledge Set migration."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import Database
from sqlalchemy import event
from sqlalchemy.engine import Engine

from tests.legacy_organization import seed_legacy_organization

PREVIOUS_REVISION = "0035_w1_resource_ownership"
CURRENT_REVISION = "0036_knowledge_sets_assets"


def _database_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _config(path: Path) -> Config:
    backend_root = Path(__file__).parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", _database_url(path))
    config.attributes["database_url"] = _database_url(path)
    return config


def _fingerprint(path: Path) -> str:
    """Fingerprint all SQLite schema objects and table rows, including Alembic head."""

    with sqlite3.connect(path) as connection:
        objects = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        table_rows: list[tuple[str, list[tuple[Any, ...]]]] = []
        for object_type, table_name, _owner, _sql in objects:
            if object_type != "table":
                continue
            escaped = str(table_name).replace('"', '""')
            rows = connection.execute(f'SELECT * FROM "{escaped}"').fetchall()
            table_rows.append((str(table_name), rows))
    encoded = json.dumps(
        {"objects": objects, "rows": table_rows},
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: {"bytes": value.hex()} if isinstance(value, bytes) else str(value),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _revision(path: Path) -> str:
    database = Database(_database_url(path))
    try:
        with database.engine.connect() as connection:
            return str(
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            )
    finally:
        database.dispose()


def _seed_populated_0035(path: Path) -> None:
    command.upgrade(_config(path), "0001_wave0_baseline")
    database = Database(_database_url(path))
    try:
        with database.session() as session:
            seed_legacy_organization(session)
    finally:
        database.dispose()
    command.upgrade(_config(path), PREVIOUS_REVISION)


@pytest.mark.parametrize(
    ("failure_match", "failure_label"),
    [
        ("CREATE TABLE knowledge_asset_versions", "asset-version table creation"),
        ("UPDATE alembic_version", "Alembic head update"),
    ],
)
def test_0036_failure_rolls_back_full_populated_database_and_retry_succeeds(
    tmp_path: Path,
    failure_match: str,
    failure_label: str,
) -> None:
    path = tmp_path / "populated.sqlite3"
    _seed_populated_0035(path)
    assert _revision(path) == PREVIOUS_REVISION
    before = _fingerprint(path)
    fired = False

    def inject_failure(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        nonlocal fired
        if failure_match in statement:
            fired = True
            raise RuntimeError(f"injected {failure_label} failure")

    event.listen(Engine, "before_cursor_execute", inject_failure)
    try:
        with pytest.raises(RuntimeError, match=f"injected {failure_label} failure"):
            command.upgrade(_config(path), CURRENT_REVISION)
    finally:
        event.remove(Engine, "before_cursor_execute", inject_failure)

    assert fired, f"the {failure_label} fault injection did not fire"
    assert _revision(path) == PREVIOUS_REVISION
    assert _fingerprint(path) == before

    command.upgrade(_config(path), CURRENT_REVISION)
    assert _revision(path) == CURRENT_REVISION
    database = Database(_database_url(path))
    try:
        with database.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
    finally:
        database.dispose()


def test_fresh_database_upgrades_to_knowledge_sets_head(tmp_path: Path) -> None:
    path = tmp_path / "fresh.sqlite3"
    command.upgrade(_config(path), CURRENT_REVISION)
    assert _revision(path) == CURRENT_REVISION
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "knowledge_sets",
            "knowledge_set_sources",
            "knowledge_assets",
            "knowledge_asset_versions",
            "knowledge_asset_version_sources",
            "agent_knowledge_sets",
        } <= tables
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_0036_downgrade_refuses_to_discard_saved_set_data(tmp_path: Path) -> None:
    path = tmp_path / "populated-knowledge-sets.sqlite3"
    _seed_populated_0035(path)
    command.upgrade(_config(path), CURRENT_REVISION)
    set_id = str(uuid4())
    with sqlite3.connect(path) as connection:
        user_id = connection.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()[0]
        course_id = connection.execute("SELECT id FROM courses ORDER BY id LIMIT 1").fetchone()[0]
        connection.execute(
            "INSERT INTO knowledge_sets "
            "(id, owner_user_id, course_id, group_id, ownership_scope, visibility, display_name, "
            "metadata_revision, content_revision, authorization_epoch, created_at, updated_at) "
            "VALUES (?, ?, ?, NULL, 'personal', 'private', 'Retained fixture', 0, 0, 0, ?, ?)",
            (set_id, user_id, course_id, "2026-09-27T12:00:00+00:00", "2026-09-27T12:00:00+00:00"),
        )
    before = _fingerprint(path)

    with pytest.raises(RuntimeError, match="Knowledge Set data exists"):
        command.downgrade(_config(path), PREVIOUS_REVISION)

    assert _revision(path) == CURRENT_REVISION
    assert _fingerprint(path) == before
