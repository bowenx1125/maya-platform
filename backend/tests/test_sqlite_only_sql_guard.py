"""Every SQLite-only statement in app code must sit behind a dialect check.

Production runs PostgreSQL.  ``sqlite_master``, ``PRAGMA``, ``BEGIN
IMMEDIATE``, ``INSERT OR IGNORE``, ``DROP TRIGGER`` and SQLite JSON table
functions fail there (Debate Delete All / Rebirth broke this way, #185).
This scan pins the reviewed call sites.  A new occurrence fails until it is
guarded by a dialect check and added to the allowlist below.
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

# file -> number of reviewed occurrences.  Each one is inside a branch that
# only runs when the bound dialect is SQLite (or is a SQLite-only tool).
REVIEWED: dict[str, int] = {
    "core/db.py": 7,  # sqlite pragmas listener, sqlite_master alembic probe, check_ready
    "core/sqlutil.py": 2,  # foreign_keys_ok / begin_immediate: dialect == "sqlite"
    "tools/sqlite_import.py": 2,  # offline SQLite import tool, never served
    "providers/control_repository.py": 1,  # dialect == "sqlite"
    "modules/knowledge/providers/sql_stage.py": 1,  # dialect == "sqlite"
    "modules/debates/cleanup.py": 4,  # trigger dance only when dialect == "sqlite"
    "modules/debates/rebirth.py": 2,  # final-input trigger only when dialect == "sqlite"
    "modules/teams/retarget.py": 1,  # defer_foreign_keys only when dialect == "sqlite"
    "modules/debates/playback/sql_repository.py": 6,  # postgres branches beside each
}


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


def test_sqlite_only_sql_is_reviewed_and_dialect_guarded() -> None:
    assert _occurrences() == REVIEWED
