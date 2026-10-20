"""0075 against a copy of the production schema (PostgreSQL only).

Set ``MAYA_TEST_POSTGRES_URL`` and ``MAYA_TEST_PROD_SCHEMA_SQL`` (a
``pg_dump -s --no-owner --no-privileges`` file at 0074). The dump is schema
only and is never committed. The test restores it into a scratch database,
upgrades to head and checks every delete rule; a model-parity test runs
everywhere.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import app.main  # noqa: F401  (registers every model on Base.metadata)
import pytest
from alembic import command
from alembic.config import Config
from app.core.db import ALEMBIC_HEAD
from app.core.models import Base
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

_ROOT = Path(__file__).parents[1]
_RULE = {"SET NULL": "n", "CASCADE": "c", "RESTRICT": "r"}


def _migration() -> ModuleType:
    path = _ROOT / "migrations" / "versions" / "0075_real_delete_history_links.py"
    spec = importlib.util.spec_from_file_location("m0075", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _model_rule(table: str, column: str) -> tuple[str | None, bool]:
    t = Base.metadata.tables[table]
    for fk in t.foreign_keys:
        if [c.name for c in fk.constraint.columns] == [column]:
            return fk.ondelete, bool(t.c[column].nullable)
    raise AssertionError(f"{table}.{column} has no single-column FK in the models")


def test_models_match_the_migration() -> None:
    m = _migration()
    for table, _name, column, _ref, ondelete, nullable in m._RELINKS:
        rule, is_nullable = _model_rule(table, column)
        assert rule == ondelete, (table, column)
        if nullable:
            assert is_nullable, (table, column)
    for column in ("agent_id", "agent_version_id"):
        assert _model_rule("debate_participants", column)[0] == "SET NULL"
    assert _model_rule("debate_participants", "knowledge_snapshot_id")[0] == "RESTRICT"
    names = {c.name for c in Base.metadata.tables["debate_participants"].constraints}
    assert not names & set(m._DEBATE_COMPOSITES)


_URL = os.environ.get("MAYA_TEST_POSTGRES_URL")
_SCHEMA = os.environ.get("MAYA_TEST_PROD_SCHEMA_SQL")


@pytest.mark.skipif(not (_URL and _SCHEMA), reason="needs Postgres and a prod schema dump")
def test_upgrade_prod_schema_copy() -> None:
    assert _URL and _SCHEMA
    url = make_url(_URL)
    name = f"maya_mig_{uuid4().hex[:10]}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
    scratch = url.set(database=name)
    try:
        env = {**os.environ, "PGPASSWORD": url.password or ""}
        subprocess.run(
            [
                "psql", "-q", "-v", "ON_ERROR_STOP=1", "-h", url.host or "127.0.0.1",
                "-p", str(url.port or 5432), "-U", url.username or "postgres",
                "-d", name, "-f", _SCHEMA,
            ],
            check=True, env=env, capture_output=True,
        )  # fmt: skip
        engine = create_engine(scratch)
        with engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM alembic_version")
            conn.exec_driver_sql(
                "INSERT INTO alembic_version (version_num) VALUES ('0074_interaction_voter_key')"
            )
        config = Config(str(_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(_ROOT / "migrations"))
        config.attributes["database_url"] = scratch.render_as_string(hide_password=False)
        command.upgrade(config, "head")

        m = _migration()
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == (
                ALEMBIC_HEAD
            )
            for table, constraint, column, _ref, ondelete, nullable in m._RELINKS:
                rule = conn.execute(
                    text("SELECT confdeltype FROM pg_constraint WHERE conname = :n"),
                    {"n": constraint},
                ).scalar_one()
                assert rule == _RULE[ondelete], (table, constraint)
                is_null = conn.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name = :t AND column_name = :c"
                    ),
                    {"t": table, "c": column},
                ).scalar_one()
                assert (is_null == "YES") or not nullable, (table, column)
            gone = conn.execute(
                text("SELECT count(*) FROM pg_constraint WHERE conname = ANY(:n)"),
                {"n": list(m._DEBATE_COMPOSITES)},
            ).scalar_one()
            assert gone == 0
            for constraint, rule in (
                ("fk_debate_participants_agent", "n"),
                ("fk_debate_participants_agent_version", "n"),
                ("fk_debate_participants_snapshot", "r"),
            ):
                assert (
                    conn.execute(
                        text("SELECT confdeltype FROM pg_constraint WHERE conname = :n"),
                        {"n": constraint},
                    ).scalar_one()
                    == rule
                )
            # Left RESTRICT on purpose: assessment provenance and chats (#230).
            for constraint in (
                "fk_assessment_activity_recipe_version",
                "agent_conversations_agent_version_id_fkey",
            ):
                assert (
                    conn.execute(
                        text("SELECT confdeltype FROM pg_constraint WHERE conname = :n"),
                        {"n": constraint},
                    ).scalar_one()
                    == "r"
                )
        engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.dispose()
