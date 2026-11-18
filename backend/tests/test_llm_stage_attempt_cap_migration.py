"""Alembic 0095: raise stage/recovery attempt caps; no data rewrite."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from app.core.db import ALEMBIC_HEAD, Database
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.postgres_db import new_database_url

migration = import_module("migrations.versions.0095_llm_stage_attempt_cap")


def test_0095_is_head_and_round_trips_from_0094() -> None:
    database = Database(new_database_url())
    database.upgrade_schema()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    config.attributes["database_url"] = str(
        database.engine.url.render_as_string(hide_password=False)
    )
    assert ScriptDirectory.from_config(config).get_heads() == [ALEMBIC_HEAD]
    assert ALEMBIC_HEAD == "0095_llm_stage_attempt_cap"
    assert migration.revision == ALEMBIC_HEAD
    assert migration.down_revision == "0094_agent_debate_cards"

    command.downgrade(config, migration.down_revision)
    with database.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == migration.down_revision
        )
        # Prod-shaped attempt_no=2 remains legal under the old check.
        assert connection.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname IN ('ck_llm_stages_attempt', "
                "'ck_llm_recovery_inputs_attempt') "
                "ORDER BY conname"
            )
        ).all() == [
            ("ck_llm_recovery_inputs_attempt", "CHECK (((attempt_no >= 1) AND (attempt_no <= 2)))"),
            ("ck_llm_stages_attempt", "CHECK (((attempt_no >= 1) AND (attempt_no <= 2)))"),
        ]

    command.upgrade(config, "head")
    assert database.check_ready()
    with database.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == ALEMBIC_HEAD
        )
        defs = connection.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname IN ('ck_llm_stages_attempt', "
                "'ck_llm_recovery_inputs_attempt') "
                "ORDER BY conname"
            )
        ).all()
        assert defs == [
            (
                "ck_llm_recovery_inputs_attempt",
                "CHECK (((attempt_no >= 1) AND (attempt_no <= 32)))",
            ),
            ("ck_llm_stages_attempt", "CHECK (((attempt_no >= 1) AND (attempt_no <= 32)))"),
        ]
    database.dispose()


def test_0095_check_constraints_only_preserve_rows_and_block_lossy_downgrade() -> None:
    engine = create_engine(new_database_url(schema=False))
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE llm_accepted_stages ("
                "id bigserial PRIMARY KEY, "
                "attempt_no integer NOT NULL, "
                "CONSTRAINT ck_llm_stages_attempt CHECK (" + migration._OLD + "))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE llm_recovery_inputs ("
                "id bigserial PRIMARY KEY, "
                "attempt_no integer NOT NULL, "
                "CONSTRAINT ck_llm_recovery_inputs_attempt CHECK (" + migration._OLD + "))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO llm_accepted_stages (attempt_no) VALUES (1), (2); "
                "INSERT INTO llm_recovery_inputs (attempt_no) VALUES (1), (2);"
            )
        )
        before_stages = connection.execute(
            text("SELECT attempt_no FROM llm_accepted_stages ORDER BY id")
        ).all()
        before_recovery = connection.execute(
            text("SELECT attempt_no FROM llm_recovery_inputs ORDER BY id")
        ).all()
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        # Existing prod-shaped rows are untouched; attempt 3 becomes legal.
        connection.execute(text("INSERT INTO llm_accepted_stages (attempt_no) VALUES (3)"))
        connection.execute(text("INSERT INTO llm_recovery_inputs (attempt_no) VALUES (32)"))
        assert connection.execute(
            text("SELECT attempt_no FROM llm_accepted_stages ORDER BY id")
        ).all() == before_stages + [(3,)]
        assert connection.execute(
            text("SELECT attempt_no FROM llm_recovery_inputs ORDER BY id")
        ).all() == before_recovery + [(32,)]
    with pytest.raises(IntegrityError), engine.begin() as connection:
        # Downgrade must refuse while attempt_no > 2 rows exist (no data rewrite).
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM llm_accepted_stages WHERE attempt_no > 2"))
        connection.execute(text("DELETE FROM llm_recovery_inputs WHERE attempt_no > 2"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()
        assert (
            connection.execute(text("SELECT attempt_no FROM llm_accepted_stages ORDER BY id")).all()
            == before_stages
        )
        assert (
            connection.execute(text("SELECT attempt_no FROM llm_recovery_inputs ORDER BY id")).all()
            == before_recovery
        )
    engine.dispose()
