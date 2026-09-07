"""A report-table rebuild must retain its child graph and versioned length rule."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import Database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.test_cleanup_debate_runtime import _seed_runtime_graph


def test_report_length_migration_preserves_graph_and_legacy_lower_bound(tmp_path):
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
        command.upgrade(config, "0023_segment_report_wordcount")
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
        with pytest.raises(IntegrityError), database.session() as db:
            db.execute(
                text("UPDATE civilization_report_revisions SET word_count=120 WHERE id=:id"),
                {"id": ids["revision"]},
            )
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
        with pytest.raises(RuntimeError, match="short segment reports"):
            command.downgrade(config, "0022_segment_turn_wordcount")
    finally:
        database.dispose()
