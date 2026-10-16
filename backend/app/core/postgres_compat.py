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


def ensure_postgres_compat(engine: Engine) -> None:
    """Install JSON helpers once. SQLite already provides these names."""

    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as connection:
        connection.execute(text(_JSON_EXTRACT))
        connection.execute(text(_JSON_VALID))
