"""ensure_postgres_compat must be safe when several replicas start together."""

from __future__ import annotations

from contextlib import contextmanager

from app.core import postgres_compat
from app.core.postgres_compat import ensure_postgres_compat


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _Connection:
    def __init__(self, existing):
        self.existing = existing
        self.statements: list[str] = []

    def execute(self, clause, params=None):
        sql = str(clause)
        self.statements.append(sql)
        if "FROM pg_proc" in sql:
            return _Result(self.existing.get(params["name"], []))
        return _Result([])


class _Dialect:
    def __init__(self, name):
        self.name = name


class _Engine:
    def __init__(self, existing, dialect="postgresql"):
        self.dialect = _Dialect(dialect)
        self.connection = _Connection(existing)

    @contextmanager
    def begin(self):
        yield self.connection


def _creates(statements):
    return [s for s in statements if "CREATE OR REPLACE FUNCTION" in s]


def test_lock_is_taken_before_any_ddl():
    engine = _Engine({})
    ensure_postgres_compat(engine)
    statements = engine.connection.statements
    assert "pg_advisory_xact_lock" in statements[0]
    assert len(_creates(statements)) == 2


def test_skips_when_definitions_already_match():
    existing = {
        name: [postgres_compat._function_body(ddl)]
        for name, ddl in postgres_compat._FUNCTIONS
    }
    engine = _Engine(existing)
    ensure_postgres_compat(engine)
    assert _creates(engine.connection.statements) == []


def test_replaces_stale_definition_only():
    existing = {"json_valid": [postgres_compat._function_body(postgres_compat._JSON_VALID)],
                "json_extract": ["old body"]}
    engine = _Engine(existing)
    ensure_postgres_compat(engine)
    creates = _creates(engine.connection.statements)
    assert len(creates) == 1 and "json_extract" in creates[0]


def test_sqlite_is_untouched():
    engine = _Engine({}, dialect="sqlite")
    ensure_postgres_compat(engine)
    assert engine.connection.statements == []
