"""K3-B1 creation/privacy and lossless migration; no Team runtime is claimed."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import Database
from app.core.models import Agent, AgentVersion, Course, CourseMember, ProviderOperation
from app.modules.knowledge_sets.models import AgentKnowledgeSet
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationParticipantSet,
    ConversationSharedSet,
    ConversationTurn,
)
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine

from tests.conftest import login
from tests.legacy_organization import seed_legacy_organization
from tests.test_mayaform_teams import (
    BOWEN_ID,
    COURSE_ID,
    MAYA_ID,
    _attach_personal_snapshot,
    _headers,
    _team_payload,
)
from tests.test_mayaform_teams import (
    _make_agent_version as _seed_agent_version,
)

PREVIOUS = "0040_teams_publication_grants"
CURRENT = "0041_team_conversations"
OLD_COLUMNS = (
    "id, user_id, course_id, agent_version_id, snapshot_id, revision, "
    "active_request_id, created_at, agent_name_snapshot, agent_authorization_epoch"
)


def _make_agent_version(database: Database, **kwargs: Any) -> tuple[str, str]:
    agent_id, version_id = _seed_agent_version(database, **kwargs)
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        assert version is not None
        version.avatar_config_json = json.dumps(
            {
                "template_id": "synthetic",
                "material_theme": "default",
                "default_expression": "neutral",
                "expression_strength": "low",
                "motion_style": "calm",
            }
        )
    return agent_id, version_id


def _team(client: TestClient, database: Database) -> tuple[dict[str, Any], list[str], str]:
    _, csrf = login(client, "maya")
    versions = [
        _make_agent_version(database, owner_id=MAYA_ID, name=f"Teacher member {index}")[1]
        for index in range(2)
    ]
    payload = _team_payload(versions, visibility="public")
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"b1-team-{uuid4()}"),
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json(), versions, csrf


def _create(
    client: TestClient, csrf: str, entry: dict[str, Any], visibility: str = "private"
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={"entry": entry, "chat_visibility": visibility},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("kind", ["agent", "team", "maya_team"])
@pytest.mark.parametrize("visibility", ["private", "public"])
def test_three_entries_freeze_real_identity_and_mock_entries_can_send(
    client: TestClient, database: Database, kind: str, visibility: str
) -> None:
    team, versions, csrf = _team(client, database)
    entry = (
        {"kind": kind, "version_id": versions[0]}
        if kind == "agent"
        else {"kind": kind, "team_id": team["id"]}
    )
    session = _create(client, csrf, entry, visibility)
    assert session["entry_kind"] == kind
    assert session["chat_visibility"] == visibility
    assert session["read_only"] is False
    assert session["can_send"] is True
    assert (
        session["origin"]
        == {"agent": "single_agent", "team": "custom_team", "maya_team": "published_course_team"}[
            kind
        ]
    )
    reloaded = client.get(f"/api/v1/conversations/{session['id']}").json()
    assert datetime.fromisoformat(reloaded["created_at"]).replace(
        tzinfo=UTC
    ) == datetime.fromisoformat(session["created_at"]).replace(tzinfo=UTC)
    assert {**reloaded, "created_at": session["created_at"]} == session
    with database.session() as db:
        row = db.get(Conversation, session["id"])
        assert row is not None and row.user_id == MAYA_ID
        participants = db.scalars(
            select(ConversationParticipant).where(ConversationParticipant.conversation_id == row.id)
        ).all()
        if kind == "agent":
            assert row.agent_version_id == versions[0] and not participants
        else:
            assert row.agent_version_id is None and row.snapshot_id is None
            assert row.team_version_id == team["current_version_id"]
            assert len(participants) == 2 and sum(item.is_leader for item in participants) == 1
            assert {item.agent_version_id for item in participants} == set(versions)
            assert bool(row.publication_id) is (kind == "maya_team")
            assert all(bool(item.invoke_grant_id) is (kind == "maya_team") for item in participants)
    # Creation alone never invokes a Provider; Team runtime is exercised by
    # the separate B2 tests without changing the frozen entry provenance.
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(ConversationTurn)) == 0
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


def test_two_students_keep_separate_privacy_and_teacher_has_public_read_only(
    client: TestClient, database: Database
) -> None:
    team, _versions, _csrf = _team(client, database)
    sessions: dict[str, dict[str, dict[str, Any]]] = {}
    for username in ("bowen", "kaikai"):
        _, csrf = login(client, username)
        sessions[username] = {
            visibility: _create(
                client, csrf, {"kind": "maya_team", "team_id": team["id"]}, visibility
            )
            for visibility in ("private", "public")
        }
    assert len({row["id"] for user in sessions.values() for row in user.values()}) == 4
    for visibility in ("private", "public"):
        assert (
            client.get(f"/api/v1/conversations/{sessions['bowen'][visibility]['id']}").status_code
            == 404
        )
    assert {row["id"] for row in client.get("/api/v1/conversations").json()} == {
        row["id"] for row in sessions["kaikai"].values()
    }
    _, csrf = login(client, "maya")
    visible = client.get("/api/v1/conversations").json()
    assert {row["id"] for row in visible} == {sessions[user]["public"]["id"] for user in sessions}
    for user in sessions:
        private_id = sessions[user]["private"]["id"]
        public_id = sessions[user]["public"]["id"]
        assert client.get(f"/api/v1/conversations/{private_id}").status_code == 404
        read = client.get(f"/api/v1/conversations/{public_id}").json()
        assert read["read_only"] is True and read["can_send"] is False
        for suffix in ("messages", "messages:stream"):
            denied = client.post(
                f"/api/v1/conversations/{public_id}/{suffix}",
                headers={**_headers(csrf), "Accept": "text/event-stream"},
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 0,
                    "message": "Teacher must not send.",
                },
            )
            assert denied.status_code == 404
        assert (
            client.delete(f"/api/v1/conversations/{public_id}", headers=_headers(csrf)).status_code
            == 404
        )
    with database.session() as db:
        member = db.get(CourseMember, (COURSE_ID, MAYA_ID))
        assert member is not None
        member.role = "student"
    assert client.get("/api/v1/conversations").json() == []
    assert (
        client.get(f"/api/v1/conversations/{sessions['bowen']['public']['id']}").status_code == 404
    )


def test_team_freezes_own_shared_sets_and_names_without_private_body_projection(
    client: TestClient, database: Database
) -> None:
    _, csrf = login(client, "maya")
    versions = [
        _make_agent_version(database, owner_id=MAYA_ID, name=f"Frozen {i}")[1] for i in range(2)
    ]
    _attach_personal_snapshot(database, versions[0])
    set_ids = []
    for index in range(2):
        response = client.post(
            f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
            headers=_headers(csrf, f"b1-set-{uuid4()}"),
            json={"display_name": f"Private Set {index}"},
        )
        assert response.status_code == 201, response.text
        set_ids.append(response.json()["id"])
    with database.session() as db:
        version = db.get(AgentVersion, versions[0])
        assert version is not None
        version.agent_md = "# Frozen 0\n\nPRIVATE_AGENT_BODY_CANARY"
        db.add(
            AgentKnowledgeSet(
                agent_id=version.agent_id,
                knowledge_set_id=set_ids[0],
                order_index=0,
                created_by_user_id=MAYA_ID,
                created_at=datetime.now(UTC),
            )
        )
    payload = {
        **_team_payload(versions, visibility="public"),
        "shared_knowledge_set_ids": [set_ids[1]],
    }
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"b1-team-{uuid4()}"),
        json=payload,
    )
    assert response.status_code == 201, response.text
    team = response.json()
    _, student_csrf = login(client, "bowen")
    session = _create(client, student_csrf, {"kind": "maya_team", "team_id": team["id"]})
    encoded = json.dumps(session)
    for value in (
        *set_ids,
        "PRIVATE_AGENT_BODY_CANARY",
        "private-source.md",
        "K3 private source fence fixture",
        "invoke_grant_id",
        "owner_user_id",
        "source_fences",
    ):
        assert value not in encoded
    with database.session() as db:
        participants = db.scalars(
            select(ConversationParticipant)
            .where(ConversationParticipant.conversation_id == session["id"])
            .order_by(ConversationParticipant.position)
        ).all()
        assert participants[0].snapshot_id is not None and participants[1].snapshot_id is None
        assert list(
            db.scalars(
                select(ConversationParticipantSet.knowledge_set_id).where(
                    ConversationParticipantSet.participant_id == participants[0].id
                )
            )
        ) == [set_ids[0]]
        assert list(
            db.scalars(
                select(ConversationSharedSet.knowledge_set_id).where(
                    ConversationSharedSet.conversation_id == session["id"]
                )
            )
        ) == [set_ids[1]]
    _, csrf = login(client, "maya")
    updated = client.put(
        f"/api/v1/teams/{team['id']}",
        headers=_headers(csrf, f"b1-team-save-{uuid4()}"),
        json={**payload, "display_name": "Renamed Team", "expected_metadata_revision": 0},
    )
    assert updated.status_code == 200, updated.text
    _, student_csrf = login(client, "bowen")
    old = client.get(f"/api/v1/conversations/{session['id']}").json()
    assert old["team"] == session["team"]
    assert old["team"]["available"] is True
    new = _create(client, student_csrf, {"kind": "maya_team", "team_id": team["id"]})
    assert new["team"]["name"] == "Renamed Team"
    assert new["team"]["version_id"] != old["team"]["version_id"]
    with database.session() as db:
        agent = db.get(Agent, participants[0].agent_id)
        assert agent is not None
        agent.authorization_epoch += 1
    old = client.get(f"/api/v1/conversations/{session['id']}").json()
    assert old["team"]["name"] == session["team"]["name"]
    assert old["team"]["available"] is False


@pytest.mark.parametrize(
    "override",
    [
        {"members": []},
        {"leader_id": str(uuid4())},
        {"shared_knowledge_set_ids": []},
        {"team_version_id": str(uuid4())},
        {"origin": "published_course_team"},
    ],
)
def test_maya_entry_rejects_client_configuration_overrides(
    client: TestClient, database: Database, override: dict[str, Any]
) -> None:
    team, _versions, _csrf = _team(client, database)
    _, csrf = login(client, "bowen")
    response = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={"entry": {"kind": "maya_team", "team_id": team["id"], **override}},
    )
    assert response.status_code == 400
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 0


def test_legacy_single_stays_private_and_teacher_public_read_has_no_raw_sources(
    client: TestClient, database: Database
) -> None:
    _, csrf = login(client, "bowen")
    _, version_id = _make_agent_version(database, owner_id=BOWEN_ID, name="Single owner")
    legacy = client.post(
        "/api/v1/conversations", headers=_headers(csrf), json={"version_id": version_id}
    )
    assert legacy.status_code == 200
    assert legacy.json()["chat_visibility"] == "private"
    invalid = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={"version_id": version_id, "chat_visibility": "public"},
    )
    assert invalid.status_code == 400
    public = _create(client, csrf, {"kind": "agent", "version_id": version_id}, "public")
    with database.session() as db:
        db.add(
            ConversationTurn(
                id=str(uuid4()),
                conversation_id=public["id"],
                position=1,
                user_text="Public user text",
                assistant_text="Public answer",
                sources_json=json.dumps(
                    [
                        {
                            "chunk_id": str(uuid4()),
                            "filename": "PRIVATE_FILENAME",
                            "excerpt": "PRIVATE_EXCERPT",
                        }
                    ]
                ),
                mode="mock",
                state="ready",
                created_at=datetime.now(UTC),
            )
        )
    _, _csrf = login(client, "maya")
    assert client.get(f"/api/v1/conversations/{legacy.json()['id']}").status_code == 404
    read = client.get(f"/api/v1/conversations/{public['id']}")
    assert read.status_code == 200
    assert read.json()["turns"][0]["assistant_text"] == "Public answer"
    assert read.json()["turns"][0]["sources"] == []
    assert "PRIVATE_" not in read.text


def test_publication_grant_is_not_a_single_or_custom_entry_grant(
    client: TestClient, database: Database
) -> None:
    team, versions, _csrf = _team(client, database)
    _, csrf = login(client, "bowen")
    for body in (
        {"entry": {"kind": "agent", "version_id": versions[0]}},
        {"entry": {"kind": "team", "team_id": team["id"]}},
    ):
        response = client.post("/api/v1/conversations", headers=_headers(csrf), json=body)
        assert response.status_code == 404
    ambiguous = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={
            "version_id": versions[0],
            "entry": {"kind": "maya_team", "team_id": team["id"]},
        },
    )
    assert ambiguous.status_code == 400
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 0
    session = _create(client, csrf, {"kind": "maya_team", "team_id": team["id"]}, "public")
    other, _csrf = login(client, "kaikai")
    other_id = other["user"]["id"]
    with database.session() as db:
        member = db.get(CourseMember, (COURSE_ID, other_id))
        assert member is not None
        db.delete(member)
        course_id = str(uuid4())
        now = datetime.now(UTC)
        db.add(Course(id=course_id, code="other-course", name="Other", created_at=now))
        db.flush()
        db.add(CourseMember(course_id=course_id, user_id=other_id, role="teacher", created_at=now))
    assert client.get("/api/v1/conversations").json() == []
    assert client.get(f"/api/v1/conversations/{session['id']}").status_code == 404


def _config(path: Path) -> Config:
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.attributes["database_url"] = f"sqlite:///{path}"
    return config


def _fingerprint(path: Path) -> str:
    with sqlite3.connect(path) as db:
        schema = db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        data = {
            name: db.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
            for kind, name, _table, _sql in schema
            if kind == "table"
        }
    return hashlib.sha256(
        json.dumps([schema, data], sort_keys=True, default=str).encode()
    ).hexdigest()


def _seed_0040(path: Path) -> None:
    command.upgrade(_config(path), "0001_wave0_baseline")
    database = Database(f"sqlite:///{path}")
    with database.session() as db:
        seed_legacy_organization(db)
    command.upgrade(_config(path), PREVIOUS)
    _, version_id = _make_agent_version(database, owner_id=MAYA_ID, name="Migrated Single")
    conversation_id = str(uuid4())
    now = datetime.now(UTC)
    with database.engine.begin() as db:
        db.exec_driver_sql(
            f"INSERT INTO agent_conversations ({OLD_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                MAYA_ID,
                COURSE_ID,
                version_id,
                None,
                3,
                None,
                now,
                "Frozen old name",
                0,
            ),
        )
        for position, state in enumerate(("ready", "failed", "acceptance_unknown"), start=1):
            db.exec_driver_sql(
                "INSERT INTO agent_conversation_turns (id,conversation_id,position,user_text,"
                "assistant_text,sources_json,mode,state,safe_error_code,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    conversation_id,
                    position,
                    f"完整用户原文 {position}",
                    "Old answer" if state == "ready" else None,
                    "[]",
                    "real",
                    state,
                    None if state == "ready" else "chat_interrupted",
                    now,
                ),
            )
    with database.session() as db:
        db.add(
            ProviderOperation(
                id=str(uuid4()),
                scope_id=conversation_id,
                provider_operation="llm_agent_chat",
                logical_item_id="preserved-charged-call",
                attempt_no=1,
                request_hash="a" * 64,
                max_tokens=0,
                max_cost_cny=0,
                policy_hash="b" * 64,
                export_manifest_hash="c" * 64,
                state="acceptance_unknown",
                request_count=1,
                charged_request_count=1,
                created_at=now,
                updated_at=now,
            )
        )
    database.dispose()


def test_0041_populated_upgrade_preserves_single_history_and_provider_ledger(
    tmp_path: Path,
) -> None:
    path = tmp_path / "populated.sqlite3"
    _seed_0040(path)
    with sqlite3.connect(path) as db:
        before = [
            db.execute(f"SELECT {columns} FROM {table} ORDER BY id").fetchall()
            for table, columns in (
                ("agent_conversations", OLD_COLUMNS),
                ("agent_conversation_turns", "*"),
                ("provider_operations", "*"),
            )
        ]
    command.upgrade(_config(path), CURRENT)
    with sqlite3.connect(path) as db:
        after = [
            db.execute(f"SELECT {columns} FROM {table} ORDER BY id").fetchall()
            for table, columns in (
                ("agent_conversations", OLD_COLUMNS),
                ("agent_conversation_turns", "*"),
                ("provider_operations", "*"),
            )
        ]
        assert after == before
        assert db.execute(
            "SELECT entry_kind,chat_visibility,origin FROM agent_conversations"
        ).fetchall() == [("agent", "private", "single_agent")]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (CURRENT,)
        assert (
            db.execute("SELECT name FROM sqlite_master WHERE name='chat_messages'").fetchall() == []
        )
        indexes = {row[1] for row in db.execute("PRAGMA index_list(agent_conversations)")}
        assert {"ix_agent_conversations_user_id", "ix_conversations_course_privacy"} <= indexes


@pytest.mark.parametrize(
    "failure_match", ["CREATE TABLE conversation_participants", "UPDATE alembic_version"]
)
def test_0041_failure_rolls_back_populated_database_and_head(
    tmp_path: Path, failure_match: str
) -> None:
    path = tmp_path / "rollback.sqlite3"
    _seed_0040(path)
    before = _fingerprint(path)
    fired = False

    def fail(
        _conn: Any, _cursor: Any, statement: str, _params: Any, _context: Any, _many: bool
    ) -> None:
        nonlocal fired
        if failure_match in statement:
            fired = True
            raise RuntimeError("0041 injected failure")

    event.listen(Engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="0041 injected failure"):
            command.upgrade(_config(path), CURRENT)
    finally:
        event.remove(Engine, "before_cursor_execute", fail)
    assert fired and _fingerprint(path) == before
    command.upgrade(_config(path), CURRENT)


def test_0041_fresh_full_chain_and_parent_child_foreign_keys(tmp_path: Path) -> None:
    path = tmp_path / "fresh.sqlite3"
    command.upgrade(_config(path), CURRENT)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (CURRENT,)
        for table in (
            "conversation_participants",
            "conversation_participant_sets",
            "conversation_shared_sets",
        ):
            assert db.execute(f"PRAGMA foreign_key_list({table})").fetchall()


def test_memory_entry_creates_and_replays_an_owner_saved_team_conversation(
    client: TestClient, database: Database
) -> None:
    versions = [
        _make_agent_version(database, owner_id=BOWEN_ID, name=f"Memory member {index}")[1]
        for index in range(2)
    ]
    _, csrf = login(client, "bowen")
    team_response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"memory-team-{uuid4()}"),
        json=_team_payload(versions),
    )
    assert team_response.status_code == 201, team_response.text
    action = {
        "action_id": str(uuid4()),
        "course_id": COURSE_ID,
        "source": {"kind": "team", "team_id": team_response.json()["id"]},
    }
    first = client.post(
        "/api/v1/conversations/memory-entry",
        headers=_headers(csrf),
        json=action,
    )
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["session"]["entry_kind"] == "team"
    assert payload["session"]["read_only"] is False
    assert payload["session"]["can_send"] is True
    replay = client.post(
        "/api/v1/conversations/memory-entry",
        headers=_headers(csrf),
        json=action,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["conversation_id"] == payload["conversation_id"]
    assert replay.json()["request_id"] == payload["request_id"]
    assert replay.json()["session"]["turns"] == []
