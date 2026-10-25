"""No SQLite-only SQL in app code.

PostgreSQL is the only database (PR B). ``sqlite_master``, ``PRAGMA``, ``BEGIN
IMMEDIATE``, ``INSERT OR IGNORE``, ``DROP TRIGGER`` and SQLite JSON table
functions fail there (Debate Delete All / Rebirth broke this way, #185).
The only allowed occurrence is the Alembic batch helper the historical
migrations import; those revisions never run on PostgreSQL.
"""

from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

PATTERN = re.compile(
    r"sqlite_master|sqlite_schema|\bPRAGMA\s+\w|BEGIN IMMEDIATE\"|"
    r"INSERT OR (?:IGNORE|REPLACE)|DROP TRIGGER|\bjson_each\(|json_group_array\(|"
    r"(?<!jsonb_)json_array_length\(|last_insert_rowid|\browid\b",
    re.IGNORECASE,
)

# file -> number of allowed occurrences.
REVIEWED: dict[str, int] = {}


def _occurrences() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in APP.rglob("*.py"):
        count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not PATTERN.search(line):
                continue
            # Prose in docstrings (``...``) or without a string literal is not SQL.
            if "``" in line or not re.search(r"[\"']", line):
                continue
            count += len(PATTERN.findall(line))
        if count:
            found[path.relative_to(APP).as_posix()] = count
    return found


def test_app_code_has_no_sqlite_only_sql() -> None:
    assert _occurrences() == REVIEWED
