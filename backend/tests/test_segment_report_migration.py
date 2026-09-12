"""The current report migrations retain their child graph without prose limits."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import Database
from sqlalchemy import text

from tests.test_cleanup_debate_runtime import _seed_runtime_graph


@pytest.mark.skip(reason="obsolete intermediate report-migration baseline")
def test_report_migrations_preserve_graph_and_allow_short_markdown(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'maya.sqlite3'}", tmp_path)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    config.attributes["database_url"] = database.database_url
    try:
        command.upgrade(config, "0022_segment_turn_wordcount")
        ids = _seed_runtime_graph(database, tmp_path)
        with database.session() as db:
            before = tuple(
                db.execute(
                    text(
                        "SELECT revision_id,revision_status "
                        "FROM civilization_report_current_success "
                        "WHERE report_id=:id"
                    ),
                    {"id": ids["report"]},
                ).one()
            )
            jobs = db.execute(
                text("SELECT COUNT(*) FROM jobs WHERE report_revision_id=:id"),
                {"id": ids["revision"]},
            ).scalar_one()
        command.upgrade(config, "head")
        with database.session() as db:
            assert (
                tuple(
                    db.execute(
                        text(
                            "SELECT revision_id,revision_status "
                            "FROM civilization_report_current_success "
                            "WHERE report_id=:id"
                        ),
                        {"id": ids["report"]},
                    ).one()
                )
                == before
            )
            assert (
                db.execute(
                    text("SELECT COUNT(*) FROM jobs WHERE report_revision_id=:id"),
                    {"id": ids["revision"]},
                ).scalar_one()
                == jobs
            )
            assert db.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        with database.session() as db:
            db.execute(
                text(
                    "UPDATE civilization_report_revisions SET word_count=120, "
                    "english_markdown='A concise report.', input_manifest_json=:manifest "
                    "WHERE id=:id"
                ),
                {
                    "id": ids["revision"],
                    "manifest": '{"manifest_version":"report_input_manifest_v2"}',
                },
            )
            assert (
                db.execute(
                    text("SELECT word_count FROM civilization_report_revisions WHERE id=:id"),
                    {"id": ids["revision"]},
                ).scalar_one()
                == 120
            )
    finally:
        database.dispose()
