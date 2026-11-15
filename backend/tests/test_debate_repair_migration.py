"""The retry-policy migration preserves existing ledger rows on PostgreSQL."""

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

migration = import_module("migrations.versions.0092_repair_feedback_v2")


def test_single_head_and_full_alembic_round_trip() -> None:
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
    assert migration.down_revision == "0091_quiz_show_results"
    command.downgrade(config, migration.down_revision)
    with database.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == migration.down_revision
        )
    command.upgrade(config, "head")
    assert database.check_ready()
    database.dispose()


def test_constraint_round_trip_preserves_old_rows_and_refuses_lossy_v2_downgrade() -> None:
    engine = create_engine(new_database_url(schema=False))
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE provider_export_manifests (id integer PRIMARY KEY, "
                "provider_operation text NOT NULL, max_attempts integer NOT NULL, "
                "repair_policy_version text, repair_policy_hash text, "
                "CONSTRAINT ck_provider_export_manifests_llm_retry_policy CHECK ("
                + migration._OLD
                + "))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO provider_export_manifests VALUES "
                "(1, 'llm_debate_turn', 1, NULL, NULL), "
                "(2, 'llm_debate_turn', 2, 'repair_feedback_v1', :hash), "
                "(3, 'llm_debate_card', 1, NULL, NULL)"
            ),
            {"hash": migration._V1_HASH},
        )
        before = connection.execute(
            text("SELECT * FROM provider_export_manifests ORDER BY id")
        ).all()
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.downgrade()
            migration.upgrade()
        assert (
            connection.execute(text("SELECT * FROM provider_export_manifests ORDER BY id")).all()
            == before
        )
        connection.execute(
            text(
                "INSERT INTO provider_export_manifests VALUES "
                "(4, 'llm_debate_turn', 2, 'repair_feedback_v2', :hash)"
            ),
            {"hash": migration._V2_HASH},
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM provider_export_manifests")).scalar_one()
            == 4
        )
        assert (
            connection.execute(
                text("SELECT repair_policy_hash FROM provider_export_manifests WHERE id = 4")
            ).scalar_one()
            == migration._V2_HASH
        )
    engine.dispose()
