"""Persistence/API checks for Wave 4 Persona compilation and confirmation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import Database
from app.core.models import AgentVersion
from app.modules.agents.persona import compile_persona
from app.seed import GROUP_DEMO_ID
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.legacy_organization import seed_legacy_organization

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"


def _headers(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, **extra}


def _persona_md(name: str, *, role: str = "Watershed steward") -> str:
    return f"""# {name}

## Identity

- Role: {role}
- Historical or cultural context: A fictional community keeper of shared water memory.

## Cultural lens

- Intergenerational responsibility

## Core values

- Reciprocity

## Initial position

Protect shared resources through careful, long-term stewardship.

## Speaking style

- Tone: Calm and reflective
- Argument pattern: Start with context, then weigh consequences
- Concession style: Acknowledge valid concerns before qualifying them
- Question style: Ask one open question about long-term effects

## Debate strategy

- Connect present choices to future stewardship

## Boundaries

- Do not claim evidence outside the snapshot
"""


def _create_agent(
    client: TestClient, csrf: str, key: str = "persona-api-create-001"
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/agents",
        headers=_headers(csrf, **{"Idempotency-Key": key}),
        json={"name": "River Keeper", "description": "Persona API fixture"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_0009_columns_are_nullable_for_legacy_and_constraints_are_reversible(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'persona.sqlite3'}", tmp_path)
    database.upgrade_schema()
    inspector = inspect(database.engine)
    columns = {item["name"]: item for item in inspector.get_columns("agent_versions")}
    assert {
        "raw_agent_md_hash",
        "persona_spec_json",
        "persona_spec_hash",
        "persona_compiler_version",
        "persona_diagnostics_json",
        "persona_confirmation_revision",
        "student_confirmed_at",
        "persona_confirming_user_id",
    }.issubset(columns)
    assert all(
        columns[name]["nullable"]
        for name in columns
        if (name.startswith("persona_") and name != "persona_required")
        or name == "raw_agent_md_hash"
    )
    assert columns["persona_required"]["nullable"] is False
    with database.engine.connect() as connection:
        trigger_names = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='trigger' "
                    "AND name LIKE 'ck_agent_versions_persona_fields_%'"
                )
            )
        }
    assert trigger_names == {
        "ck_agent_versions_persona_fields_insert",
        "ck_agent_versions_persona_fields_update",
    }


def test_0009_rejects_partial_persona_rows_and_lossy_downgrade(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'persona-populated.sqlite3'}"
    database = Database(database_url, tmp_path)
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.attributes["database_url"] = database_url
    command.upgrade(cfg, "0008_wave4_mutual_learning_rounds")
    now = datetime.now(UTC)
    agent_md = _persona_md("Migration Agent")
    with database.session() as session:
        seed_legacy_organization(session)
        connection = session.connection()
        metadata = MetaData()
        agents = Table("agents", metadata, autoload_with=connection)
        versions = Table("agent_versions", metadata, autoload_with=connection)
        session.execute(
            agents.insert().values(
                id="persona-migration-agent",
                group_id=GROUP_DEMO_ID,
                name="Migration Agent",
                description="",
                metadata_revision=0,
                status="active",
                current_published_version_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            versions.insert().values(
                id="persona-migration-version",
                agent_id="persona-migration-agent",
                version_seq=0,
                state="draft",
                revision=1,
                agent_md=agent_md,
                avatar_config_json="{}",
                created_at=now,
                updated_at=now,
            )
        )
    command.upgrade(cfg, "0009_persona_structured_fields")
    with database.engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "UPDATE agent_versions SET persona_spec_json='{}' "
                    "WHERE id='persona-migration-version'"
                )
            )
    compiled = compile_persona(agent_md, expected_name="Migration Agent")
    assert compiled.compiled and compiled.canonical_json and compiled.persona_spec_hash
    with database.engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO agent_versions "
                    "(id,agent_id,version_seq,state,revision,agent_md,raw_agent_md_hash,"
                    "persona_spec_json,avatar_config_json,created_at,updated_at) "
                    "VALUES ('persona-migration-partial','persona-migration-agent',1,'published',1,"
                    ":agent_md,:raw_hash,:spec,'{}',:now,:now)"
                ),
                {
                    "agent_md": _persona_md("Migration Agent"),
                    "raw_hash": compiled.source_agent_md_hash,
                    "spec": compiled.canonical_json,
                    "now": datetime.now(UTC),
                },
            )
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE agent_versions SET persona_spec_json=:spec, persona_spec_hash=:spec_hash, "
                "persona_compiler_version='persona_template_v1' "
                "WHERE id='persona-migration-version'"
            ),
            {"spec": compiled.canonical_json, "spec_hash": compiled.persona_spec_hash},
        )
        connection.execute(
            text(
                "UPDATE agent_versions SET persona_confirmation_revision=revision, "
                "student_confirmed_at=:now, persona_confirming_user_id='student-confirming' "
                "WHERE id='persona-migration-version'"
            ),
            {"now": datetime.now(UTC)},
        )
    with database.engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "UPDATE agent_versions SET agent_md=:agent_md "
                    "WHERE id='persona-migration-version'"
                ),
                {"agent_md": _persona_md("Migration Agent", role="Changed role")},
            )
    with pytest.raises(RuntimeError, match="Cannot downgrade 0009"):
        command.downgrade(cfg, "0008_wave4_mutual_learning_rounds")
    with database.engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0009_persona_structured_fields"
        )
    assert "persona_spec_json" in {
        item["name"] for item in inspect(database.engine).get_columns("agent_versions")
    }


def test_0009_does_not_backfill_existing_legacy_agent_versions(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'persona-legacy.sqlite3'}"
    database = Database(database_url, tmp_path)
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.attributes["database_url"] = database_url
    command.upgrade(cfg, "0008_wave4_mutual_learning_rounds")
    with database.session() as session:
        seed_legacy_organization(session)
        now = datetime.now(UTC)
        session.execute(
            text(
                "INSERT INTO agents "
                "(id,group_id,name,description,metadata_revision,status,created_at,updated_at) "
                "VALUES ('legacy-persona-agent',:group_id,'Legacy Agent','',0,'active',:now,:now)"
            ),
            {"group_id": GROUP_DEMO_ID, "now": now},
        )
        session.flush()
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO agent_versions "
                "(id,agent_id,version_seq,state,revision,agent_md,avatar_config_json,"
                "voice_profile_id,knowledge_snapshot_id,published_at,created_at,updated_at) "
                "VALUES ('legacy-persona-version','legacy-persona-agent',0,'published',1,"
                "'# Legacy Agent\n\nHistorical raw source.','{}',NULL,NULL,NULL,:now,:now)"
            ),
            {"now": now},
        )
    command.upgrade(cfg, "head")
    with database.session() as session:
        row = session.get(AgentVersion, "legacy-persona-version")
        assert row is not None
        assert row.agent_md == "# Legacy Agent\n\nHistorical raw source."
        assert row.raw_agent_md_hash is None
        assert row.persona_spec_json is None
        assert row.persona_spec_hash is None
        assert row.persona_compiler_version is None
        assert row.persona_confirmation_revision is None
        assert row.student_confirmed_at is None
        assert row.persona_confirming_user_id is None
