from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from alembic import command
from alembic.config import Config
from app.core.db import ALEMBIC_HEAD, Database
from app.modules.debates.models import Debate
from app.modules.workspace.models import AgentAccountMemory
from fastapi.testclient import TestClient

from tests.test_knowledge_sets import _create_set
from tests.test_mayaform_team_conversations import _create, _team
from tests.test_mayaform_teams import COURSE_ID, MAYA_ID, _headers

BEFORE = "0059_chat_titles_pins"


def _config(database: Database) -> Config:
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", database.database_url)
    config.attributes["database_url"] = database.database_url
    return config


def _rows(database: Database, query: str) -> list[tuple[Any, ...]]:
    path = database.database_url.removeprefix("sqlite:///")
    with sqlite3.connect(path) as db:
        return db.execute(query).fetchall()


def test_reset_retires_every_old_resource_and_downgrade_puts_them_back(
    app_factory: Any,
) -> None:
    assert ALEMBIC_HEAD == "0063_attempt_actor_name"
    app, database, _settings = app_factory()
    # Built by Alembic, as a deployment is, so the reset can be stepped over.
    database.upgrade_schema()
    with TestClient(app) as client:
        _reset_and_restore(client, database)


def _reset_and_restore(client: TestClient, database: Database) -> None:
    team, versions, csrf = _team(client, database)
    agent_chat = _create(client, csrf, {"kind": "agent", "version_id": versions[0]})
    team_chat = _create(client, csrf, {"kind": "maya_team", "team_id": team["id"]})
    uploaded = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-documents",
        headers=_headers(csrf, f"reset-rag-{uuid4()}"),
        files={"file": ("old-notes.md", b"# Old notes\n\nKept for audit", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    knowledge = _create_set(client, csrf, "Old question bank", key=f"reset-set-{uuid4()}")
    now = datetime.now(UTC)
    debate_id = str(uuid4())
    memory_id = str(uuid4())
    agent_id = _rows(database, f"SELECT agent_id FROM agent_versions WHERE id = '{versions[0]}'")[
        0
    ][0]
    with database.session() as db:
        db.add(
            Debate(
                id=debate_id,
                course_id=COURSE_ID,
                topic="An old lesson",
                rule_set_id="ordered_multi_expert_mutual_learning_v1",
                rule_snapshot_json='{"round_count":2}',
                output_language="en",
                status="debate_finished",
                revision=0,
                last_sequence=0,
                cancellation_generation=0,
                created_by=MAYA_ID,
                created_at=now,
                updated_at=now,
                finished_at=now,
            )
        )
        db.add(
            AgentAccountMemory(
                id=memory_id,
                owner_user_id=MAYA_ID,
                agent_id=agent_id,
                course_id=COURSE_ID,
                body="Call me by my first name.",
                created_at=now,
                updated_at=now,
            )
        )
    assert len(client.get(f"/api/v1/courses/{COURSE_ID}/debates").json()) == 1

    config = _config(database)
    database.dispose()
    # Step back, then let the reset run over a classroom full of old work.
    command.downgrade(config, BEFORE)
    command.upgrade(config, "0060_legacy_data_reset")

    assert _rows(database, "SELECT count(*) FROM agents WHERE deleted_at IS NULL") == [(0,)]
    assert _rows(database, "SELECT DISTINCT status FROM agents") == [("archived",)]
    assert _rows(
        database, "SELECT count(*) FROM agent_conversations WHERE withdrawn_at IS NULL"
    ) == [(0,)]
    assert _rows(
        database,
        "SELECT workspace_state FROM knowledge_documents "
        f"WHERE id = '{uploaded.json()['document']['id']}'",
    ) == [("hidden",)]
    for table in ("knowledge_sets", "teams", "debates", "agent_account_memories"):
        assert _rows(database, f"SELECT count(*) FROM {table} WHERE deleted_at IS NULL") == [
            (0,)
        ], table
    assert _rows(database, "SELECT DISTINCT state FROM course_team_publications") == [("revoked",)]

    # Every list a person opens is empty, and nothing errors.
    assert client.get("/api/v1/conversations").json() == []
    assert client.get(f"/api/v1/conversations/{agent_chat['id']}").status_code == 404
    assert client.get(f"/api/v1/conversations/{team_chat['id']}").status_code == 404
    assert client.get(f"/api/v1/courses/{COURSE_ID}/debates").json() == []
    assert client.get(f"/api/v1/debates/{debate_id}").status_code == 404
    assert client.get(f"/api/v1/courses/{COURSE_ID}/workspace-documents").json() == []
    assert client.get(f"/api/v1/courses/{COURSE_ID}/teams").json() == []
    assert client.get(f"/api/v1/knowledge-sets/{knowledge['id']}").status_code == 404

    command.downgrade(config, BEFORE)
    assert _rows(database, "SELECT count(*) FROM agents WHERE deleted_at IS NOT NULL") == [(0,)]
    assert _rows(database, "SELECT DISTINCT status FROM agents") == [("active",)]
    assert _rows(
        database, "SELECT count(*) FROM agent_conversations WHERE withdrawn_at IS NOT NULL"
    ) == [(0,)]
    assert _rows(database, "SELECT DISTINCT workspace_state FROM knowledge_documents") == [
        ("active",)
    ]
    for table in ("knowledge_sets", "teams"):
        assert _rows(database, f"SELECT count(*) FROM {table} WHERE deleted_at IS NOT NULL") == [
            (0,)
        ], table
    assert _rows(database, "SELECT DISTINCT state FROM course_team_publications") == [
        ("published",)
    ]
    assert not _rows(database, "SELECT name FROM sqlite_master WHERE name = 'data_reset_rows'")
    command.upgrade(config, "head")
