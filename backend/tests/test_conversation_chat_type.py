"""chat_type backfill and the list/create contract that reads it.

The migration is applied to a table shaped like agent_conversations before
0081 (no chat_type column). Rows are classified only when entry_kind and the
agent or team binding already agree. Create stores that same two-value type;
?entry_kind= still filters, and omitting it still returns every kind.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from app.core.db import ALEMBIC_HEAD, Database
from app.modules.workspace.models import Conversation
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from tests.postgres_db import named_url
from tests.test_conversation_list_filters import _seed
from tests.test_mayaform_team_conversations import _make_agent_version
from tests.test_mayaform_teams import COURSE_ID, MAYA_ID, _headers

_LEGACY_TABLE = """
CREATE TABLE agent_conversations (
    id varchar(36) PRIMARY KEY,
    entry_kind varchar(16) NOT NULL,
    origin varchar(32) NOT NULL,
    team_id varchar(36),
    team_version_id varchar(36),
    team_owner_user_id varchar(36),
    team_name_snapshot text,
    team_authorization_epoch integer,
    publication_id varchar(36),
    publication_epoch integer,
    source_removed_at timestamptz,
    agent_version_id varchar(36),
    snapshot_id varchar(36),
    history_agent_id varchar(36),
    history_agent_version_id varchar(36),
    history_team_id varchar(36),
    history_team_version_id varchar(36),
    note text NOT NULL
)
"""


def _legacy_database(tmp_path: Path) -> Database:
    database = Database(named_url(f"{tmp_path}/chat-type", schema=False))
    with database.engine.begin() as connection:
        connection.execute(text(_LEGACY_TABLE))
        # 0080 already had teacher_group_access. 0082 adds expires_at, and
        # 0083's quiz tables reference courses, groups and users, so a
        # database stamped at 0080 must contain those parents before upgrade.
        connection.execute(
            text(
                "CREATE TABLE teacher_group_access ("
                "group_id varchar(36) NOT NULL, "
                "user_id varchar(36) NOT NULL, "
                "created_at timestamptz NOT NULL, "
                "PRIMARY KEY (group_id, user_id))"
            )
        )
        connection.execute(text("CREATE TABLE users (id varchar(36) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE courses (id varchar(36) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE groups (id varchar(36) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE alembic_version (version_num varchar(64) NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('0080_drop_playback_rate')")
        )
    return database


def _insert(connection, **values: object) -> None:
    columns = ", ".join(values)
    params = ", ".join(f":{name}" for name in values)
    connection.execute(
        text(f"INSERT INTO agent_conversations ({columns}) VALUES ({params})"),
        values,
    )


def _classified_rows() -> list[dict[str, object]]:
    removed_at = datetime.now(UTC)
    return [
        {
            "id": "agent-live",
            "entry_kind": "agent",
            "origin": "single_agent",
            "agent_version_id": "version-1",
            "note": "agent live",
        },
        {
            "id": "agent-removed",
            "entry_kind": "agent",
            "origin": "single_agent",
            "source_removed_at": removed_at,
            "history_agent_id": "agent-1",
            "history_agent_version_id": "version-1",
            "note": "agent removed",
        },
        {
            "id": "team-live",
            "entry_kind": "team",
            "origin": "custom_team",
            "team_id": "team-1",
            "team_version_id": "team-version-1",
            "team_owner_user_id": "owner-1",
            "team_name_snapshot": "Circle",
            "team_authorization_epoch": 0,
            "note": "team live",
        },
        {
            "id": "maya-live",
            "entry_kind": "maya_team",
            "origin": "published_course_team",
            "team_id": "team-2",
            "team_version_id": "team-version-2",
            "team_owner_user_id": "owner-1",
            "team_name_snapshot": "Published",
            "team_authorization_epoch": 1,
            "publication_id": "publication-1",
            "publication_epoch": 0,
            "note": "maya live",
        },
        {
            "id": "team-removed",
            "entry_kind": "team",
            "origin": "custom_team",
            "source_removed_at": removed_at,
            "team_name_snapshot": "Gone",
            "team_authorization_epoch": 0,
            "history_team_id": "team-3",
            "history_team_version_id": "team-version-3",
            "note": "team removed",
        },
    ]


def _types(database: Database) -> dict[str, str | None]:
    with database.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, chat_type, note FROM agent_conversations ORDER BY id")
        ).all()
    return {row.id: row.chat_type for row in rows}


def _notes(database: Database) -> dict[str, str]:
    with database.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, note FROM agent_conversations ORDER BY id")
        ).all()
    return {row.id: row.note for row in rows}


def _chat_type_column(database: Database) -> dict[str, object] | None:
    columns = inspect(database.engine).get_columns("agent_conversations")
    return next((column for column in columns if column["name"] == "chat_type"), None)


def test_backfill_classifies_bound_chats_and_downgrades(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = _legacy_database(tmp_path)
    with database.engine.begin() as connection:
        for row in _classified_rows():
            _insert(connection, **row)
    database.upgrade_schema()
    # Alembic's fileConfig writes this line itself; it does not propagate
    # into the pytest log handler.
    assert "agent_conversations chat_type unclassified: 0" in capsys.readouterr().err
    assert _types(database) == {
        "agent-live": "agent",
        "agent-removed": "agent",
        "maya-live": "team",
        "team-live": "team",
        "team-removed": "team",
    }
    column = _chat_type_column(database)
    assert column is not None and column["nullable"] is False
    checks = {
        item["name"]
        for item in inspect(database.engine).get_check_constraints("agent_conversations")
    }
    assert "ck_conversations_chat_type" in checks
    with database.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == ALEMBIC_HEAD
        )

    command.downgrade(database._alembic_config(), "0080_drop_playback_rate")  # type: ignore[attr-defined]
    assert _chat_type_column(database) is None
    assert _notes(database)["agent-live"] == "agent live"
    assert _notes(database)["team-removed"] == "team removed"
    with database.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0080_drop_playback_rate"
        )

    database.upgrade_schema()
    assert _types(database)["maya-live"] == "team"
    assert _types(database)["agent-removed"] == "agent"
    assert _chat_type_column(database)["nullable"] is False  # type: ignore[index]


def test_backfill_leaves_unclassified_rows_nullable_and_logs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = _legacy_database(tmp_path / "unknown")
    with database.engine.begin() as connection:
        _insert(
            connection,
            id="agent-live",
            entry_kind="agent",
            origin="single_agent",
            agent_version_id="version-1",
            note="kept",
        )
        # entry_kind says agent, but a team id is also set: do not guess.
        _insert(
            connection,
            id="disagrees",
            entry_kind="agent",
            origin="single_agent",
            agent_version_id="version-1",
            team_id="team-1",
            note="disagrees",
        )
        _insert(
            connection,
            id="unknown-kind",
            entry_kind="other",
            origin="single_agent",
            note="unknown",
        )
    database.upgrade_schema()
    assert "agent_conversations chat_type unclassified: 2" in capsys.readouterr().err
    assert _types(database) == {
        "agent-live": "agent",
        "disagrees": None,
        "unknown-kind": None,
    }
    column = _chat_type_column(database)
    assert column is not None and column["nullable"] is True
    assert _notes(database) == {
        "agent-live": "kept",
        "disagrees": "disagrees",
        "unknown-kind": "unknown",
    }
    command.downgrade(database._alembic_config(), "0080_drop_playback_rate")  # type: ignore[attr-defined]
    assert _chat_type_column(database) is None
    assert _notes(database)["disagrees"] == "disagrees"


def test_create_writes_chat_type_and_typed_lists_stay_apart(
    client: TestClient, database: Database
) -> None:
    from tests.conftest import login

    made = _seed(client, database)
    with database.session() as db:
        agent = db.get(Conversation, made["agent"])
        team = db.get(Conversation, made["team"])
        maya = db.get(Conversation, made["maya_team"])
        assert agent is not None and agent.chat_type == "agent"
        assert team is not None and team.chat_type == "team"
        assert maya is not None and maya.chat_type == "team"

    def listed(query: str) -> set[str]:
        response = client.get(f"/api/v1/conversations{query}")
        assert response.status_code == 200, response.text
        return {row["id"] for row in response.json()}

    agents = listed("?entry_kind=agent")
    teams = listed("?entry_kind=team")
    everything = listed("")
    assert made["agent"] in agents and made["team"] not in agents
    assert made["maya_team"] not in agents
    assert {made["team"], made["maya_team"]} <= teams and made["agent"] not in teams
    assert {made["agent"], made["team"], made["maya_team"]} <= everything

    _, csrf = login(client, "maya")
    version_id = _make_agent_version(database, owner_id=MAYA_ID, name="Legacy body")[1]
    legacy = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={"version_id": version_id},
    )
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["entry_kind"] == "agent"
    with database.session() as db:
        stored = db.get(Conversation, legacy.json()["id"])
        assert stored is not None and stored.chat_type == "agent"

    with pytest.raises(IntegrityError):
        with database.session() as db:
            row = db.get(Conversation, made["agent"])
            assert row is not None
            row.chat_type = "team"
    with database.session() as db:
        row = db.get(Conversation, made["agent"])
        assert row is not None and row.chat_type == "agent"

    # An insert that omits chat_type still stores the type for its entry_kind.
    filled_id = str(uuid4())
    with database.session() as db:
        db.add(
            Conversation(
                id=filled_id,
                user_id=MAYA_ID,
                course_id=COURSE_ID,
                agent_version_id=version_id,
                entry_kind="agent",
                origin="single_agent",
                created_at=datetime.now(UTC),
            )
        )
    with database.session() as db:
        filled = db.get(Conversation, filled_id)
        assert filled is not None and filled.chat_type == "agent"
