"""Copy a SQLite snapshot into PostgreSQL without modifying the source.

The source is opened read-only. A backup written with SQLite's backup API is a
new file. This module never deletes, updates, or vacuums the live database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import insert, select, text
from sqlalchemy.engine import Connection, Engine

from app.core.db import ALEMBIC_HEAD, Database
from app.core.models import Base

_RECEIPT = "maya_import_receipts"


def backup_sqlite(source: Path, destination: Path) -> None:
    """Write a consistent snapshot. The source is opened read-only."""

    if destination.exists():
        raise RuntimeError("Backup destination already exists.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        integrity = destination_connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise RuntimeError("SQLite backup failed integrity_check.")
    except Exception:
        destination_connection.close()
        destination.unlink(missing_ok=True)
        raise
    else:
        destination_connection.close()
    finally:
        source_connection.close()


def _readonly_engine(source: Path) -> Engine:
    from sqlalchemy import create_engine

    url = f"sqlite:///file:{source.resolve()}?mode=ro&uri=true"
    return create_engine(url, future=True)


def _register_models() -> None:
    from app.core.db import Database as _Database

    # Importing through initialize_schema's module list keeps one registry.
    probe = _Database("sqlite://")
    probe.initialize_schema()
    probe.dispose()


def _source_version(connection: Connection) -> str:
    row = connection.execute(
        text("SELECT version_num FROM alembic_version LIMIT 1")
    ).scalar_one_or_none()
    if not isinstance(row, str) or not row:
        raise RuntimeError("SQLite snapshot has no Alembic version.")
    return row


def _column_names(connection: Connection, table: str) -> set[str]:
    rows = connection.execute(text(f"PRAGMA table_info({table})")).all()
    return {str(row[1]) for row in rows}


def _assert_no_dangling_foreign_keys(connection: Connection) -> None:
    """Reject a copy whose rows do not satisfy the model foreign keys.

    The copy inserts with replica role so the courses/debates cycle can land
    in one transaction. The check runs before that transaction commits.
    """

    for table in Base.metadata.sorted_tables:
        if not table.name.replace("_", "").isalnum():
            raise RuntimeError("Refusing to check a table with an unexpected name.")
        for constraint in table.foreign_key_constraints:
            elements = list(constraint.elements)
            if not elements:
                continue
            parent = elements[0].column.table.name
            if not parent.replace("_", "").isalnum():
                raise RuntimeError("Refusing to check a foreign key with an unexpected name.")
            pairs = [(element.parent.name, element.column.name) for element in elements]
            if any(
                not child.replace("_", "").isalnum() or not referenced.replace("_", "").isalnum()
                for child, referenced in pairs
            ):
                raise RuntimeError("Refusing to check a foreign key with an unexpected name.")
            joined = " AND ".join(
                f"child.{child_name} = parent.{referenced}" for child_name, referenced in pairs
            )
            present = " AND ".join(f"child.{child_name} IS NOT NULL" for child_name, _ref in pairs)
            found = connection.execute(
                text(
                    f"SELECT 1 FROM {table.name} AS child "
                    f"LEFT JOIN {parent} AS parent ON {joined} "
                    f"WHERE {present} AND parent.{pairs[0][1]} IS NULL LIMIT 1"
                )
            ).first()
            if found is not None:
                raise RuntimeError(f"Imported rows leave a dangling foreign key on {table.name}.")


def import_sqlite(source: Path, destination: Database) -> dict[str, int]:
    """Copy rows into an empty PostgreSQL database. Returns per-table counts.

    The destination must already be at the Alembic head. A partial copy rolls
    back. The source is not written.
    """

    if destination.engine.dialect.name != "postgresql":
        raise RuntimeError("SQLite import destination must be PostgreSQL.")
    if not source.is_file():
        raise RuntimeError("SQLite snapshot is missing.")
    _register_models()
    source_engine = _readonly_engine(source)
    counts: dict[str, int] = {}
    try:
        with source_engine.connect() as source_connection:
            version = _source_version(source_connection)
            if version not in {ALEMBIC_HEAD, "0064_active_debate_slot"}:
                raise RuntimeError("SQLite snapshot is not at a supported schema head.")
            with destination.engine.begin() as destination_connection:
                existing_users = destination_connection.execute(
                    text("SELECT COUNT(*) FROM users")
                ).scalar_one()
                if int(existing_users or 0) > 0:
                    raise RuntimeError(
                        "PostgreSQL already has accounts. Refusing to mix in a snapshot."
                    )
                # courses.current_audio_debate_id and debates.course_id refer to
                # each other. Replica role lets both land before foreign keys
                # are checked, and the role ends with this transaction.
                destination_connection.execute(
                    text("SET LOCAL session_replication_role = 'replica'")
                )
                for table in Base.metadata.sorted_tables:
                    if table.name in {"auth_login_admissions", _RECEIPT}:
                        continue
                    source_columns = _column_names(source_connection, table.name)
                    destination_columns = {column.name for column in table.columns}
                    if source_columns != destination_columns:
                        missing = sorted(destination_columns - source_columns)
                        extra = sorted(source_columns - destination_columns)
                        raise RuntimeError(
                            f"Column mismatch for {table.name}; missing={missing} extra={extra}."
                        )
                    rows = source_connection.execute(select(table)).mappings().all()
                    if rows:
                        destination_connection.execute(insert(table), [dict(row) for row in rows])
                    counts[table.name] = len(rows)
                destination_connection.execute(
                    text("SET LOCAL session_replication_role = 'origin'")
                )
                _assert_no_dangling_foreign_keys(destination_connection)
                destination_connection.execute(
                    text(
                        f"CREATE TABLE IF NOT EXISTS {_RECEIPT} ("
                        "id text PRIMARY KEY, source_version text NOT NULL, "
                        "table_count integer NOT NULL, user_count integer NOT NULL)"
                    )
                )
                destination_connection.execute(
                    text(
                        f"INSERT INTO {_RECEIPT} "
                        "(id, source_version, table_count, user_count) "
                        "VALUES ('current', :version, :tables, :users)"
                    ),
                    {
                        "version": version,
                        "tables": len(counts),
                        "users": counts.get("users", 0),
                    },
                )
    finally:
        source_engine.dispose()
    return counts


def postgres_has_import_receipt(database: Database) -> bool:
    if database.engine.dialect.name != "postgresql":
        return False
    with database.engine.connect() as connection:
        exists = connection.execute(text(f"SELECT to_regclass('public.{_RECEIPT}')")).scalar_one()
        if exists is None:
            return False
        count = connection.execute(
            text(f"SELECT COUNT(*) FROM {_RECEIPT} WHERE id = 'current'")
        ).scalar_one()
        return int(count or 0) > 0


def maybe_import_postgres(database: Database, source: str, *, allow_empty: bool) -> bool:
    """Import when PostgreSQL has no accounts yet. Returns whether it copied.

    A database that already has accounts and no receipt is left untouched and
    startup fails, so a half-copied volume is not treated as success.
    """

    if database.engine.dialect.name != "postgresql":
        return False
    with database.engine.connect() as connection:
        users = int(connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one() or 0)
    if postgres_has_import_receipt(database):
        return False
    if users > 0:
        raise RuntimeError(
            "PostgreSQL has accounts but no import receipt. "
            "The SQLite file was not modified. Restore the PostgreSQL volume "
            "from empty and import again; do not delete the SQLite file."
        )
    if not source:
        if allow_empty:
            return False
        raise RuntimeError(
            "PostgreSQL is empty. Set MAYA_POSTGRES_IMPORT_SOURCE to a SQLite "
            "snapshot, or MAYA_POSTGRES_ALLOW_EMPTY=true for a fresh database."
        )
    import_sqlite(Path(source), database)
    return True


def main() -> None:
    """Backup and/or import. The live SQLite file is only ever opened read-only."""

    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Copy a SQLite snapshot into PostgreSQL.")
    parser.add_argument("--source", required=True, help="SQLite database file. Opened read-only.")
    parser.add_argument("--backup-to", help="Write a SQLite backup API snapshot to this new path.")
    parser.add_argument(
        "--destination-url",
        help="PostgreSQL SQLAlchemy URL. Required unless --backup-only is set.",
    )
    parser.add_argument(
        "--backup-only",
        action="store_true",
        help="Write the backup and stop. Does not open PostgreSQL.",
    )
    args = parser.parse_args()
    source = Path(args.source)
    if args.backup_to:
        backup_sqlite(source, Path(args.backup_to))
        print("backup integrity_check ok", file=sys.stderr)
        if args.backup_only:
            return
        source = Path(args.backup_to)
    if args.backup_only:
        raise SystemExit("--backup-only requires --backup-to")
    if not args.destination_url:
        raise SystemExit("--destination-url is required to import")
    database = Database(args.destination_url)
    try:
        database.upgrade_schema()
        counts = import_sqlite(source, database)
    finally:
        database.dispose()
    print(f"imported tables={len(counts)} users={counts.get('users', 0)}")


if __name__ == "__main__":
    main()
