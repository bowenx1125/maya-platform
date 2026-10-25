#!/usr/bin/env python3
"""Copy a SQLite snapshot into an empty PostgreSQL database. Dry-run by default.

The SQLite file is opened read-only (``mode=ro&immutable=1``: no locks and no
-wal/-shm side files) and is never written,
vacuumed or deleted; removing it is a manual step after a stable week.

Dry-run prints, per table, the SQLite row count, the PostgreSQL row count and
what --apply would do. --apply also needs --confirm-production. The copy runs
in one transaction (foreign keys are checked before it commits) and records a
receipt, so running it again is a no-op:

- PostgreSQL has a receipt: already imported, nothing to do (exit 0);
- PostgreSQL has accounts but no receipt: refused, nothing is written (exit 2);
- PostgreSQL is empty: the rows are copied and the counts compared.

Columns that exist only in PostgreSQL take their model default (they must be
nullable or have one); SQLite-only columns and tables are listed and skipped.

    docker cp scripts/migrate_sqlite_to_postgres.py maya-production-backend-1:/tmp/
    docker exec -e PYTHONPATH=/app -w /app maya-production-backend-1 \\
      python /tmp/migrate_sqlite_to_postgres.py --source /app/data/maya.sqlite3
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SCRIPT_ROOT / "backend"
if BACKEND_ROOT.is_dir() and str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.db import Database, registered_metadata  # noqa: E402
from sqlalchemy import Integer, create_engine, func, insert, select, text  # noqa: E402
from sqlalchemy.engine import Connection, Engine  # noqa: E402
from sqlalchemy.schema import Table  # noqa: E402

# courses.current_audio_debate_id and debates.course_id form a known cycle;
# the copy handles it with replica role, so the sort warning is noise.
warnings.filterwarnings("ignore", message="Cannot correctly sort tables")

RECEIPT = "maya_import_receipts"
# Sign-in admission rows are short-lived counters, not data.
SKIPPED = frozenset({"auth_login_admissions", RECEIPT})
BATCH = 500


@dataclass
class TablePlan:
    name: str
    source_rows: int | None
    destination_rows: int | None
    columns: list[str] = field(default_factory=list)
    missing_in_source: list[str] = field(default_factory=list)
    source_only: list[str] = field(default_factory=list)
    problem: str | None = None


def readonly_sqlite(source: Path) -> Engine:
    """A SQLAlchemy engine over a read-only DB-API connection."""

    # immutable=1: no locks and no -wal/-shm files next to the source, so
    # nothing in its directory is written either.
    uri = f"file:{source.resolve()}?mode=ro&immutable=1"

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
        connection.execute("PRAGMA query_only = ON")
        return connection

    return create_engine("sqlite://", creator=connect, future=True)


def _source_tables(connection: Connection) -> set[str]:
    rows = connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).all()
    return {str(row[0]) for row in rows}


def _source_columns(connection: Connection, table: str) -> list[str]:
    if not table.replace("_", "").isalnum():
        raise RuntimeError(f"Refusing an unexpected table name: {table!r}")
    return [str(row[1]) for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")]


def _source_version(connection: Connection, tables: set[str]) -> str | None:
    if "alembic_version" not in tables:
        return None
    return connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()


def _destination_has(connection: Connection, table: str) -> bool:
    return (
        connection.execute(text("SELECT to_regclass(:name)"), {"name": f"public.{table}"}).scalar()
        is not None
    )


def _count(connection: Connection, table: Table) -> int:
    return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


def _receipt(connection: Connection) -> dict[str, Any] | None:
    if not _destination_has(connection, RECEIPT):
        return None
    row = (
        connection.execute(text(f"SELECT * FROM {RECEIPT} WHERE id = 'current'")).mappings().first()
    )
    return dict(row) if row else None


def plan_tables(source: Connection, destination: Connection | None) -> list[TablePlan]:
    metadata = registered_metadata()
    present = _source_tables(source)
    plans: list[TablePlan] = []
    for table in metadata.sorted_tables:
        if table.name in SKIPPED:
            continue
        destination_rows = (
            _count(destination, table)
            if destination is not None and _destination_has(destination, table.name)
            else None
        )
        if table.name not in present:
            plans.append(TablePlan(table.name, None, destination_rows))
            continue
        source_columns = _source_columns(source, table.name)
        model_columns = [column.name for column in table.columns]
        plan = TablePlan(
            table.name,
            int(source.exec_driver_sql(f"SELECT COUNT(*) FROM {table.name}").scalar_one()),
            destination_rows,
            columns=[name for name in model_columns if name in source_columns],
            missing_in_source=[name for name in model_columns if name not in source_columns],
            source_only=[name for name in source_columns if name not in model_columns],
        )
        for name in plan.missing_in_source:
            column = table.columns[name]
            if not column.nullable and column.default is None and column.server_default is None:
                plan.problem = f"column {name} is required in PostgreSQL and absent in SQLite"
        plans.append(plan)
    for name in sorted(present - {table.name for table in metadata.sorted_tables}):
        if name not in SKIPPED and name != "alembic_version":
            plans.append(TablePlan(name, None, None, problem="not in the current schema; skipped"))
    return plans


def _copy(source: Connection, destination: Connection, plans: list[TablePlan]) -> None:
    metadata = registered_metadata()
    # courses.current_audio_debate_id and debates.course_id refer to each
    # other: replica role lets both land, and the foreign keys are checked
    # explicitly before commit.
    destination.execute(text("SET LOCAL session_replication_role = 'replica'"))
    for plan in plans:
        if plan.source_rows is None or plan.name not in metadata.tables:
            continue
        table = metadata.tables[plan.name]
        columns = ", ".join(plan.columns)
        result = source.exec_driver_sql(f"SELECT {columns} FROM {plan.name}")
        while batch := result.fetchmany(BATCH):
            destination.execute(
                insert(table), [dict(zip(plan.columns, row, strict=True)) for row in batch]
            )
    destination.execute(text("SET LOCAL session_replication_role = 'origin'"))
    _check_foreign_keys(destination)
    _reset_sequences(destination)


def _check_foreign_keys(connection: Connection) -> None:
    for table in registered_metadata().sorted_tables:
        for constraint in table.foreign_key_constraints:
            pairs = [(element.parent.name, element.column.name) for element in constraint.elements]
            if not pairs:
                continue
            parent = constraint.elements[0].column.table.name
            joined = " AND ".join(f"c.{child} = p.{ref}" for child, ref in pairs)
            present = " AND ".join(f"c.{child} IS NOT NULL" for child, _ref in pairs)
            dangling = connection.execute(
                text(
                    f"SELECT 1 FROM {table.name} AS c LEFT JOIN {parent} AS p ON {joined} "
                    f"WHERE {present} AND p.{pairs[0][1]} IS NULL LIMIT 1"
                )
            ).first()
            if dangling is not None:
                raise RuntimeError(f"Copied rows leave a dangling foreign key on {table.name}.")


def _reset_sequences(connection: Connection) -> None:
    for table in registered_metadata().sorted_tables:
        keys = list(table.primary_key.columns)
        if len(keys) != 1 or not isinstance(keys[0].type, Integer):
            continue
        sequence = connection.execute(
            text("SELECT pg_get_serial_sequence(:table, :column)"),
            {"table": table.name, "column": keys[0].name},
        ).scalar()
        if sequence:
            connection.execute(
                text(
                    f"SELECT setval(:sequence, COALESCE((SELECT MAX({keys[0].name}) "
                    f"FROM {table.name}), 0) + 1, false)"
                ),
                {"sequence": sequence},
            )


def _write_receipt(connection: Connection, version: str | None, plans: list[TablePlan]) -> None:
    connection.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {RECEIPT} (id text PRIMARY KEY, source_version text "
            "NOT NULL, table_count integer NOT NULL, user_count integer NOT NULL)"
        )
    )
    users = next((plan.source_rows or 0 for plan in plans if plan.name == "users"), 0)
    connection.execute(
        text(
            f"INSERT INTO {RECEIPT} (id, source_version, table_count, user_count) "
            "VALUES ('current', :version, :tables, :users)"
        ),
        {
            "version": version or "unknown",
            "tables": sum(1 for plan in plans if plan.source_rows is not None),
            "users": users,
        },
    )


def _print_plans(plans: list[TablePlan], action: str) -> None:
    width = max(len(plan.name) for plan in plans)
    print(f"{'table'.ljust(width)}  {'sqlite':>9}  {'postgres':>9}  {action}")
    for plan in plans:
        source = "-" if plan.source_rows is None else str(plan.source_rows)
        destination = "-" if plan.destination_rows is None else str(plan.destination_rows)
        notes = []
        if plan.problem:
            notes.append(plan.problem)
        elif plan.source_rows is not None and action == "would copy":
            notes.append(str(plan.source_rows))
        if plan.missing_in_source:
            notes.append("default: " + ",".join(plan.missing_in_source))
        if plan.source_only:
            notes.append("skipped columns: " + ",".join(plan.source_only))
        print(f"{plan.name.ljust(width)}  {source:>9}  {destination:>9}  {'; '.join(notes)}")


def run(source_path: Path, database_url: str, *, apply: bool) -> int:
    if not source_path.is_file():
        print(f"SQLite file not found: {source_path}", file=sys.stderr)
        return 2
    source_engine = readonly_sqlite(source_path)
    database = Database(database_url)
    try:
        with source_engine.connect() as source, database.engine.connect() as destination:
            tables = _source_tables(source)
            version = _source_version(source, tables)
            schema_ready = _destination_has(destination, "users")
            receipt = _receipt(destination) if schema_ready else None
            users = (
                _count(destination, registered_metadata().tables["users"]) if schema_ready else 0
            )
            plans = plan_tables(source, destination)
            print(f"sqlite: {source_path} (read-only, alembic {version or 'none'})")
            print(f"postgres: schema {'ready' if schema_ready else 'missing'}, accounts {users}")
            if receipt is not None:
                _print_plans(plans, "already imported")
                print(
                    "already imported (receipt from alembic "
                    f"{receipt['source_version']}); nothing to do"
                )
                return 0
            if users > 0:
                _print_plans(plans, "refused")
                print("PostgreSQL already has accounts and no receipt; refusing to mix data.")
                return 2
            problems = [
                plan for plan in plans if plan.problem and plan.name in registered_metadata().tables
            ]
            _print_plans(plans, "would copy" if not apply else "copying")
            if problems:
                print(f"{len(problems)} table(s) cannot be copied; nothing written.")
                return 2
            if not apply:
                total = sum(plan.source_rows or 0 for plan in plans)
                print(
                    f"dry-run: {total} rows would be copied. "
                    "Re-run with --apply --confirm-production to copy."
                )
                return 0
        if not schema_ready:
            database.upgrade_schema()
        with source_engine.connect() as source, database.engine.begin() as destination:
            _copy(source, destination, plans)
            _write_receipt(destination, version, plans)
        with source_engine.connect() as source, database.engine.connect() as destination:
            after = plan_tables(source, destination)
        mismatched = [
            plan.name
            for plan in after
            if plan.source_rows is not None
            and plan.name in registered_metadata().tables
            and plan.source_rows != plan.destination_rows
        ]
        _print_plans(after, "copied")
        if mismatched:
            print("count mismatch after copy: " + ", ".join(mismatched), file=sys.stderr)
            return 1
        print("copied; every table count matches. The SQLite file was not modified.")
        return 0
    finally:
        source_engine.dispose()
        database.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, type=Path, help="SQLite file (opened read-only)")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="PostgreSQL URL (default: DATABASE_URL)",
    )
    parser.add_argument("--apply", action="store_true", help="copy the rows")
    parser.add_argument(
        "--confirm-production", action="store_true", help="required together with --apply"
    )
    args = parser.parse_args(argv)
    if not args.database_url.startswith("postgresql"):
        parser.error("--database-url (or DATABASE_URL) must be a PostgreSQL URL")
    if args.apply and not args.confirm_production:
        parser.error("--apply needs --confirm-production; back up PostgreSQL first")
    return run(args.source, args.database_url, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
