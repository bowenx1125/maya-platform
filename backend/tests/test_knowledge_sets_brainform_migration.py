from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import Database
from app.seed import COURSE_ID, GROUP_SPECS, TEACHER_ID
from sqlalchemy import event
from sqlalchemy.engine import Engine

from tests.legacy_organization import seed_legacy_organization

PREVIOUS_REVISION = "0046_chat_withdrawal"
CURRENT_REVISION = "0047_brainform_markdown"


def _database_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _config(path: Path) -> Config:
    backend_root = Path(__file__).parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", _database_url(path))
    config.attributes["database_url"] = _database_url(path)
    return config


def _revision(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return str(connection.execute("SELECT version_num FROM alembic_version").fetchone()[0])


def _fingerprint(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        objects = connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        rows: list[tuple[str, list[tuple[Any, ...]]]] = []
        for kind, name, _table, _sql in objects:
            if kind == "table":
                escaped = str(name).replace('"', '""')
                rows.append(
                    (str(name), connection.execute(f'SELECT * FROM "{escaped}"').fetchall())
                )
    material = json.dumps(
        {"objects": objects, "rows": rows},
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: value.hex() if isinstance(value, bytes) else str(value),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _seed_populated_0046(path: Path) -> tuple[str, str, str, str, str]:
    command.upgrade(_config(path), "0001_wave0_baseline")
    database = Database(_database_url(path))
    try:
        with database.session() as session:
            seed_legacy_organization(session)
    finally:
        database.dispose()
    command.upgrade(_config(path), PREVIOUS_REVISION)

    source = "# Existing source\n\nKept with its current RAG document."
    source_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    file_id, document_id, set_id, asset_id, asset_version_id = (str(uuid4()) for _ in range(5))
    now = datetime.now(UTC).isoformat()
    content = json.dumps(
        {"kind": "note", "title": "Retained note", "body": "Legacy structured view."},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO stored_files "
            "(id,kind,relative_path,sha256,size,state,created_at,updated_at) "
            "VALUES (?,?,?,?,?,'active',?,?)",
            (
                file_id,
                "markdown",
                f"users/{TEACHER_ID}/legacy/source.md",
                source_sha,
                len(source.encode("utf-8")),
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO knowledge_documents "
            "(id,group_id,source_filename,stored_file_id,char_count,index_status,index_revision,"
            "workspace_state,content_hash,created_at,updated_at,owner_user_id,course_id,"
            "ownership_scope,visibility,authorization_epoch) "
            "VALUES (?,?,?,?,?,'ready',1,'active',?,?,?,?,?,'group','private',0)",
            (
                document_id,
                GROUP_SPECS[0][0],
                "source.md",
                file_id,
                len(source),
                source_hash,
                now,
                now,
                TEACHER_ID,
                COURSE_ID,
            ),
        )
        connection.execute(
            "INSERT INTO knowledge_sets "
            "(id,owner_user_id,course_id,group_id,ownership_scope,visibility,display_name,"
            "metadata_revision,content_revision,authorization_epoch,created_at,updated_at) "
            "VALUES (?,?,?,NULL,'personal','private','Legacy Knowledge',4,7,0,?,?)",
            (set_id, TEACHER_ID, COURSE_ID, now, now),
        )
        connection.execute(
            "INSERT INTO knowledge_assets "
            "(id,knowledge_set_id,kind,current_version_seq,created_by_user_id,"
            "created_at,updated_at) "
            "VALUES (?,?,'note',1,?,?,?)",
            (asset_id, set_id, TEACHER_ID, now, now),
        )
        connection.execute(
            "INSERT INTO knowledge_asset_versions "
            "(id,asset_id,version_seq,content_json,content_hash,set_authorization_epoch,origin,"
            "created_by_user_id,created_at) VALUES (?,?,1,?,?,0,'manual',?,?)",
            (
                asset_version_id,
                asset_id,
                content,
                hashlib.sha256(content.encode("utf-8")).hexdigest(),
                TEACHER_ID,
                now,
            ),
        )
    return document_id, file_id, source_hash, set_id, asset_version_id


def test_populated_upgrade_backfills_immutable_rag_and_markdown_versions_atomically(
    tmp_path: Path,
) -> None:
    path = tmp_path / "populated-0046.sqlite3"
    document_id, file_id, source_hash, set_id, asset_version_id = _seed_populated_0046(path)
    assert _revision(path) == PREVIOUS_REVISION
    before = _fingerprint(path)
    fired = False

    def fail_brainform_backfill_update(
        _connection: Any,
        _cursor: Any,
        statement: str,
        parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        nonlocal fired
        if "UPDATE knowledge_sets SET current_markdown_version_seq" in statement:
            fired = True
            raise RuntimeError("injected Brainform backfill failure")

    event.listen(Engine, "before_cursor_execute", fail_brainform_backfill_update)
    try:
        with pytest.raises(RuntimeError, match="injected Brainform backfill failure"):
            command.upgrade(_config(path), CURRENT_REVISION)
    finally:
        event.remove(Engine, "before_cursor_execute", fail_brainform_backfill_update)
    assert fired
    assert _revision(path) == PREVIOUS_REVISION
    assert _fingerprint(path) == before

    command.upgrade(_config(path), CURRENT_REVISION)
    assert _revision(path) == CURRENT_REVISION
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        document_version = connection.execute(
            "SELECT * FROM knowledge_document_versions WHERE document_id=?", (document_id,)
        ).fetchone()
        markdown_version = connection.execute(
            "SELECT * FROM knowledge_set_markdown_versions WHERE knowledge_set_id=?",
            (set_id,),
        ).fetchone()
        set_head = connection.execute(
            "SELECT current_markdown_version_seq FROM knowledge_sets WHERE id=?", (set_id,)
        ).fetchone()[0]
        assert document_version is not None
        assert document_version["version_seq"] == 1
        assert document_version["stored_file_id"] == file_id
        assert document_version["content_hash"] == source_hash
        assert markdown_version is not None
        assert markdown_version["version_seq"] == 1
        assert markdown_version["origin"] == "legacy"
        assert asset_version_id in markdown_version["asset_version_ids_json"]
        assert "Retained note" in markdown_version["markdown"]
        assert set_head == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
