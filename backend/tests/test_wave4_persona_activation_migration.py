"""Migration evidence for the explicit Persona activation boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.core.db import ALEMBIC_HEAD, Database
from app.seed import GROUP_DEMO_ID
from sqlalchemy import inspect, text

from tests.legacy_organization import seed_legacy_organization


def _config(database_url: str) -> Config:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


def _persona_required(database: Database) -> dict[str, bool]:
    with database.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, persona_required FROM agent_versions "
                "WHERE id IN ('activation-published', 'activation-draft') ORDER BY id"
            )
        ).all()
    return {str(row.id): bool(row.persona_required) for row in rows}


def test_0012_marks_only_mutable_drafts_and_round_trips(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'persona-activation.sqlite3'}"
    config = _config(database_url)
    command.upgrade(config, "0011_evidence_trace_json")
    database = Database(database_url, tmp_path)
    now = datetime.now(UTC)
    with database.session() as session:
        seed_legacy_organization(session)
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO agents "
                "(id,group_id,name,description,metadata_revision,status,"
                "current_published_version_id,created_at,updated_at) "
                "VALUES ('activation-agent',:group_id,'Activation Agent','',0,'active',"
                "'activation-published',:now,:now)"
            ),
            {"group_id": GROUP_DEMO_ID, "now": now},
        )
        for version_id, version_seq, state in (
            ("activation-published", 0, "published"),
            ("activation-draft", 1, "draft"),
        ):
            connection.execute(
                text(
                    "INSERT INTO agent_versions "
                    "(id,agent_id,version_seq,state,revision,agent_md,"
                    "avatar_config_json,published_at,created_at,updated_at) "
                    "VALUES (:id,'activation-agent',:version_seq,:state,0,"
                    "'# Activation Agent','{}',:published_at,:now,:now)"
                ),
                {
                    "id": version_id,
                    "version_seq": version_seq,
                    "state": state,
                    "published_at": now if state == "published" else None,
                    "now": now,
                },
            )

    command.upgrade(config, ALEMBIC_HEAD)
    assert _persona_required(database) == {
        "activation-draft": True,
        "activation-published": False,
    }

    command.downgrade(config, "0011_evidence_trace_json")
    assert "persona_required" not in {
        str(column["name"]) for column in inspect(database.engine).get_columns("agent_versions")
    }
    command.upgrade(config, ALEMBIC_HEAD)
    assert _persona_required(database) == {
        "activation-draft": True,
        "activation-published": False,
    }
