"""PostgreSQL functions that match the SQLite JSON helpers used in SQL text.

Debate checks and a few statements call ``json_extract`` and ``json_valid``.
Those names exist in SQLite. Installing the same names in PostgreSQL keeps the
statements valid without rewriting every query. The functions are immutable and
return NULL / false for invalid JSON, which is the SQLite failure mode.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

_JSON_EXTRACT = """
CREATE OR REPLACE FUNCTION json_extract(doc text, path text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  parsed jsonb;
  parts text[];
BEGIN
  IF doc IS NULL OR path IS NULL OR left(path, 2) <> '$.' THEN
    RETURN NULL;
  END IF;
  BEGIN
    parsed := doc::jsonb;
  EXCEPTION WHEN others THEN
    RETURN NULL;
  END;
  parts := string_to_array(substr(path, 3), '.');
  RETURN parsed #>> parts;
END;
$$
"""

_JSON_VALID = """
CREATE OR REPLACE FUNCTION json_valid(doc text)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
  IF doc IS NULL THEN
    RETURN false;
  END IF;
  BEGIN
    PERFORM doc::jsonb;
  EXCEPTION WHEN others THEN
    RETURN false;
  END;
  RETURN true;
END;
$$
"""


# Fixed key for pg_advisory_xact_lock; serializes the install across replicas.
POSTGRES_COMPAT_LOCK_KEY = 0x6D617961_6A736F6E  # "mayajson"

_FUNCTIONS = (("json_extract", _JSON_EXTRACT), ("json_valid", _JSON_VALID))


def _function_body(ddl: str) -> str:
    """Return the text between the $$ quotes, which is what pg_proc.prosrc stores."""

    return ddl.split("$$", 2)[1]


def ensure_postgres_compat(engine: Engine) -> None:
    """Install JSON helpers once. SQLite already provides these names.

    Several backend replicas start at the same time. Two concurrent
    ``CREATE OR REPLACE FUNCTION`` statements on the same function fail with
    "tuple concurrently updated", so the install runs under a transaction-scoped
    advisory lock and skips functions whose stored body already matches.
    """

    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": POSTGRES_COMPAT_LOCK_KEY},
        )
        for name, ddl in _FUNCTIONS:
            existing = (
                connection.execute(
                    text(
                        "SELECT p.prosrc FROM pg_proc p "
                        "JOIN pg_namespace n ON n.oid = p.pronamespace "
                        "WHERE p.proname = :name AND n.nspname = current_schema()"
                    ),
                    {"name": name},
                )
                .scalars()
                .all()
            )
            if _function_body(ddl) in existing:
                continue
            connection.execute(text(ddl))
