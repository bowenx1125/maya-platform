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

from tests.conftest import login, post_message
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
        _make_agent_version(
            database, owner_id=MAYA_ID, name=f"Teacher member {index}", visibility="public"
        )[1]
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


def _create(client: TestClient, csrf: str, entry: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/api/v1/conversations", headers=_headers(csrf), json={"entry": entry})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("kind", ["agent", "team", "maya_team"])
def test_three_entries_freeze_real_identity_and_mock_entries_can_send(
    client: TestClient, database: Database, kind: str
) -> None:
    team, versions, csrf = _team(client, database)
    entry = (
        {"kind": kind, "version_id": versions[0]}
        if kind == "agent"
        else {"kind": kind, "team_id": team["id"]}
    )
    # Every Chat is private; asking for a public one is a malformed request.
    public = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={"entry": entry, "chat_visibility": "public"},
    )
    assert public.status_code == 400
    session = _create(client, csrf, entry)
    assert session["entry_kind"] == kind
    assert session["chat_visibility"] == "private"
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
        # Without a complete published recipe even a Maya Team has no opening.
        assert db.scalar(select(func.count()).select_from(ConversationTurn)) == 0
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


def test_every_chat_stays_with_its_owner_even_a_stored_legacy_public_one(
    client: TestClient, database: Database
) -> None:
    team, _versions, _csrf = _team(client, database)
    sessions: dict[str, dict[str, Any]] = {}
    for username in ("bowen", "kaikai"):
        _, csrf = login(client, username)
        sessions[username] = _create(client, csrf, {"kind": "maya_team", "team_id": team["id"]})
    # A Chat created before every Chat became private still reads as its owner's.
    with database.session() as db:
        legacy = db.get(Conversation, sessions["bowen"]["id"])
        assert legacy is not None
        legacy.chat_visibility = "public"
    assert client.get(f"/api/v1/conversations/{sessions['bowen']['id']}").status_code == 404
    assert [row["id"] for row in client.get("/api/v1/conversations").json()] == [
        sessions["kaikai"]["id"]
    ]
    _, csrf = login(client, "maya")
    assert client.get("/api/v1/conversations").json() == []
    for session in sessions.values():
        assert client.get(f"/api/v1/conversations/{session['id']}").status_code == 404
        denied = client.post(
            f"/api/v1/conversations/{session['id']}/messages:stream",
            headers={**_headers(csrf), "Accept": "text/event-stream"},
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "message": "Teacher must not send.",
            },
        )
        assert denied.status_code == 404
        assert (
            client.delete(
                f"/api/v1/conversations/{session['id']}", headers=_headers(csrf)
            ).status_code
            == 404
        )
    _, csrf = login(client, "bowen")
    owned = client.get(f"/api/v1/conversations/{sessions['bowen']['id']}").json()
    assert owned["read_only"] is False and owned["can_send"] is True


def test_team_freezes_own_shared_sets_and_names_without_private_body_projection(
    client: TestClient, database: Database
) -> None:
    _, csrf = login(client, "maya")
    versions = [
        _make_agent_version(database, owner_id=MAYA_ID, name=f"Frozen {i}", visibility="public")[1]
        for i in range(2)
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


def test_legacy_single_stays_private_and_its_sources_stay_with_the_owner(
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
    single = _create(client, csrf, {"kind": "agent", "version_id": version_id})
    with database.session() as db:
        row = db.get(Conversation, single["id"])
        assert row is not None
        row.chat_visibility = "public"
        db.add(
            ConversationTurn(
                id=str(uuid4()),
                conversation_id=single["id"],
                position=1,
                user_text="Owner user text",
                assistant_text="Owner answer",
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
    owner = client.get(f"/api/v1/conversations/{single['id']}").json()
    assert owner["turns"][0]["sources"][0]["filename"] == "PRIVATE_FILENAME"
    _, _csrf = login(client, "maya")
    for conversation_id in (legacy.json()["id"], single["id"]):
        denied = client.get(f"/api/v1/conversations/{conversation_id}")
        assert denied.status_code == 404
        assert "PRIVATE_" not in denied.text and "Owner answer" not in denied.text


def test_publication_grant_is_not_a_single_or_custom_entry_grant(
    client: TestClient, database: Database
) -> None:
    team, versions, _csrf = _team(client, database)
    # New public Teams take only public Agents; a Team saved earlier, or a
    # member made private later, still holds one, and its grant must not open
    # a direct Chat with it.
    with database.session() as db:
        version = db.get(AgentVersion, versions[0])
        assert version is not None
        agent = db.get(Agent, version.agent_id)
        assert agent is not None
        agent.visibility = "private"
        version.draft_visibility = "private"
        version.published_visibility = "private"
    _, csrf = login(client, "bowen")
    agent_denied = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={"entry": {"kind": "agent", "version_id": versions[0]}},
    )
    assert agent_denied.status_code == 404
    team_chat = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={"entry": {"kind": "team", "team_id": team["id"]}, "chat_visibility": "private"},
    )
    assert team_chat.status_code == 200, team_chat.text
    assert team_chat.json()["entry_kind"] == "team"
    assert team_chat.json()["origin"] == "custom_team"
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
        assert db.scalar(select(func.count()).select_from(Conversation)) == 1
    session = _create(client, csrf, {"kind": "maya_team", "team_id": team["id"]})
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


def test_team_list_chat_scores_only_when_the_published_recipe_is_complete(
    client: TestClient, database: Database, monkeypatch: Any
) -> None:
    from app.modules.learning.recipes import (
        COMPLETION_DECLARATION,
        QUESTION_SCOPE_DECLARATION,
        SUPPORTED_RECIPE_ID,
    )

    _, csrf = login(client, "maya")
    versions = [
        _make_agent_version(database, owner_id=MAYA_ID, name=name, visibility="public")[1]
        for name in ("Leader", "Evaluator", "Boundary")
    ]
    created_set = client.post(
        f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
        headers=_headers(csrf, f"recipe-set-{uuid4()}"),
        json={"display_name": "Recipe questions"},
    )
    assert created_set.status_code == 201, created_set.text
    set_id = created_set.json()["id"]
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"recipe-team-{uuid4()}"),
        json={
            "display_name": "Recipe circle",
            "visibility": "public",
            "members": [
                {"agent_version_id": version_id, "is_leader": index == 0, "position": index}
                for index, version_id in enumerate(versions)
            ],
            "shared_knowledge_set_ids": [set_id],
        },
    )
    assert created.status_code == 201, created.text
    team_id = created.json()["id"]
    plain = _create(client, csrf, {"kind": "team", "team_id": team_id})
    assert plain["entry_kind"] == "team"
    assert plain["origin"] == "custom_team"
    assert plain["turns"] == []

    with database.session() as db:
        leader = db.get(AgentVersion, versions[0])
        evaluator = db.get(AgentVersion, versions[1])
        boundary = db.get(AgentVersion, versions[2])
        assert leader is not None and evaluator is not None and boundary is not None
        from app.modules.workspace.formal_assessment import formal_ruleset_markdown

        leader.agent_md = (
            f"{leader.agent_md}\nMAYA-ASSESSMENT-RECIPE: {SUPPORTED_RECIPE_ID}\n"
            f"{QUESTION_SCOPE_DECLARATION}\n{COMPLETION_DECLARATION}\n\n"
            + formal_ruleset_markdown(
                answer_recorder="Evaluator",
                question_guide="Leader",
                scorer="Evaluator",
                summarizer="Boundary",
                student_round_order=("Evaluator", "Leader"),
            )
        )
        db.commit()

    incomplete = _create(client, csrf, {"kind": "team", "team_id": team_id})
    assert incomplete["entry_kind"] == "team"
    assert incomplete["turns"] == []

    monkeypatch.setattr(
        "app.modules.learning.recipes._selected_questions",
        lambda _db, _set_ids: [("set", "asset", 1, "question")],
    )
    ready = _create(client, csrf, {"kind": "team", "team_id": team_id})
    assert ready["entry_kind"] == "maya_team"
    assert ready["origin"] == "published_course_team"
    assert ready["turns"] == []
    assert ready["revision"] == 0
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


def test_deleted_published_team_chat_remains_readable(
    client: TestClient, database: Database
) -> None:
    team, _versions, _csrf = _team(client, database)
    _, student_csrf = login(client, "bowen")
    session = _create(client, student_csrf, {"kind": "maya_team", "team_id": team["id"]})
    _, teacher_csrf = login(client, "maya")
    deleted = client.delete(
        f"/api/v1/teams/{team['id']}",
        headers=_headers(teacher_csrf, f"delete-published-team-{uuid4()}"),
    )
    assert deleted.status_code == 204, deleted.text
    _, student_csrf = login(client, "bowen")
    listed = client.get("/api/v1/conversations")
    assert listed.status_code == 200, listed.text
    saved = next(item for item in listed.json() if item["id"] == session["id"])
    assert saved["entry_kind"] == "maya_team"
    assert saved["team"]["available"] is False
    assert saved["team"]["deleted"] is True
    opened = client.get(f"/api/v1/conversations/{session['id']}")
    assert opened.status_code == 200, opened.text
    assert opened.json()["team"]["name"] == session["team"]["name"]


def test_a_chat_says_its_publisher_deleted_the_agent_or_a_team_member(
    client: TestClient, database: Database
) -> None:
    team, versions, _csrf = _team(client, database)
    agent_id, version_id = _make_agent_version(
        database, owner_id=MAYA_ID, name="Shared tutor", visibility="public"
    )
    # Students no longer open single chats with a teacher's public Agent (#182);
    # this is a chat opened before that rule.
    from tests.test_studyform_teacher_public_agents import _legacy_single_chat

    single_id = _legacy_single_chat(database, version_id, BOWEN_ID)
    _, student_csrf = login(client, "bowen")
    single = client.get(f"/api/v1/conversations/{single_id}").json()
    assert single["agent"]["deleted"] is False
    assert single["agent"]["visibility"] == "public"
    team_chat = _create(client, student_csrf, {"kind": "maya_team", "team_id": team["id"]})
    assert not any(member["deleted"] for member in team_chat["team"]["members"])

    _, teacher_csrf = login(client, "maya")
    with database.session() as db:
        member_agent_id = db.get(AgentVersion, versions[0]).agent_id  # type: ignore[union-attr]
    for deleted_agent in (agent_id, member_agent_id):
        response = client.delete(
            f"/api/v1/agents/{deleted_agent}",
            headers=_headers(teacher_csrf, f"delete-agent-{uuid4()}"),
        )
        assert response.status_code == 204, response.text

    # The student who chatted is not the publisher, yet still learns the
    # Agent was deleted rather than that it is merely unavailable.
    _, student_csrf = login(client, "bowen")
    saved = client.get(f"/api/v1/conversations/{single['id']}").json()
    assert saved["agent"]["deleted"] is True
    assert saved["agent"]["available"] is False
    assert [turn["user_text"] for turn in saved["turns"]] == []
    denied = post_message(
        client,
        f"/api/v1/conversations/{single['id']}/messages",
        headers=_headers(student_csrf),
        json={"request_id": str(uuid4()), "expected_revision": 0, "message": "Hello"},
    )
    assert denied.status_code == 409 and denied.json()["code"] == "agent_deleted"

    team_saved = client.get(f"/api/v1/conversations/{team_chat['id']}").json()
    assert team_saved["team"]["deleted"] is False
    deleted_members = [
        member["name"] for member in team_saved["team"]["members"] if member["deleted"]
    ]
    assert deleted_members == ["Teacher member 0"]


def test_student_teams_list_chat_with_teacher_public_team_can_send(
    client: TestClient, database: Database
) -> None:
    """Bug (2026-10-18): a student opened the teacher's public Team from the
    Teams list (kind "team"). The Chat was created, but its recheck only let the
    owner or a group student in, so every member looked unavailable and the
    Chat said "Team Chat sending is unavailable in the current runtime"."""

    team, _versions, _csrf = _team(client, database)
    _, student_csrf = login(client, "bowen")
    session = _create(client, student_csrf, {"kind": "team", "team_id": team["id"]})
    assert session["entry_kind"] == "team"
    assert session["origin"] == "custom_team"
    assert session["team"]["available"] is True
    assert all(member["available"] for member in session["team"]["members"])
    assert session["can_send"] is True
    reloaded = client.get(f"/api/v1/conversations/{session['id']}")
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["can_send"] is True
    sent = post_message(
        client,
        f"/api/v1/conversations/{session['id']}/messages",
        headers=_headers(student_csrf),
        json={"request_id": str(uuid4()), "expected_revision": 0, "message": "Hello team"},
    )
    assert sent.status_code == 200, sent.text
    turns = sent.json()["turns"]
    assert len(turns) == 1 and turns[0]["state"] in {"ready", "partial"}, turns
    # The Chat page sends over the stream endpoint; it must not 404 either.
    streamed = client.post(
        f"/api/v1/conversations/{session['id']}/messages:stream",
        headers={**_headers(student_csrf), "Accept": "text/event-stream"},
        json={"request_id": str(uuid4()), "expected_revision": 1, "message": "Hello again"},
    )
    assert streamed.status_code == 200, streamed.text

    # Revoking the publication (the teacher makes the Team private again by
    # deleting it) still closes the Chat: access follows the live publication.
    _, teacher_csrf = login(client, "maya")
    deleted = client.delete(
        f"/api/v1/teams/{team['id']}",
        headers=_headers(teacher_csrf, f"delete-public-team-{uuid4()}"),
    )
    assert deleted.status_code == 204, deleted.text
    login(client, "bowen")
    closed = client.get(f"/api/v1/conversations/{session['id']}").json()
    assert closed["can_send"] is False
    assert closed["team"]["deleted"] is True


def test_other_teacher_private_team_chat_stays_closed_to_student(
    client: TestClient, database: Database
) -> None:
    """The fix lets a student continue a teacher's published public Team only;
    a private or unpublished Team of someone else is still not reachable."""

    _, csrf = login(client, "maya")
    versions = [
        _make_agent_version(database, owner_id=MAYA_ID, name=f"Private member {i}")[1]
        for i in range(2)
    ]
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"private-team-{uuid4()}"),
        json=_team_payload(versions, visibility="private"),
    )
    assert created.status_code == 201, created.text
    _, student_csrf = login(client, "bowen")
    response = client.post(
        "/api/v1/conversations",
        headers=_headers(student_csrf),
        json={"entry": {"kind": "team", "team_id": created.json()["id"]}},
    )
    assert response.status_code == 404, response.text
