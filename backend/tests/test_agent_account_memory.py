"""Account memory stays with the signed-in account and out of Debates."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import SessionRecord, User
from app.modules.auth.service import AuthContext
from app.modules.debates.playback import generation_adapter
from app.modules.runtime_tools.agent_memory import (
    ReadAgentMemoryArguments,
    WriteAgentMemoryArguments,
    read_agent_memory,
    write_agent_memory,
)
from app.modules.runtime_tools.registry import ToolCallIdentity
from app.modules.workspace.models import (
    AgentAccountMemory,
    Conversation,
    ConversationParticipant,
    ConversationTurn,
)
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_mayaform_team_conversations import _create, _team


def _actor(db, username: str) -> AuthContext:
    user = db.scalar(select(User).where(User.username == username))
    session = db.scalar(select(SessionRecord).where(SessionRecord.user_id == user.id))
    assert user is not None and session is not None
    return AuthContext("token", session, user, "csrf")


def _turn(db, conversation_id: str, user_text: str, position: int = 0) -> ConversationTurn:
    turn = ConversationTurn(
        id=str(uuid4()),
        conversation_id=conversation_id,
        position=position,
        user_text=user_text,
        assistant_text=None,
        sources_json="[]",
        mode="mock",
        state="pending",
        created_at=datetime.now(UTC),
    )
    db.add(turn)
    db.flush()
    return turn


def _identity(conversation_id: str, turn_id: str, participant_id: str) -> ToolCallIdentity:
    return ToolCallIdentity(
        conversation_id=conversation_id,
        turn_id=turn_id,
        participant_id=participant_id,
        model_call_id="model-call",
        tool_call_id="tool-call",
    )


def test_leader_stores_only_the_named_members_memory_for_this_account(client, database) -> None:
    team, _versions, csrf = _team(client, database)
    session = _create(client, csrf, {"kind": "team", "team_id": team["id"]})
    leader = next(member for member in session["team"]["members"] if member["is_leader"])
    other = next(member for member in session["team"]["members"] if not member["is_leader"])
    remembered = "我喜欢短回答"
    message = f"请{other['name']}记住{remembered}"

    with database.session() as db:
        conversation = db.get(Conversation, session["id"])
        assert conversation is not None
        turn = _turn(db, session["id"], message)
        maya = _actor(db, "maya")
        with pytest.raises(PlatformError) as missing:
            write_agent_memory(
                db,
                maya,
                conversation,
                WriteAgentMemoryArguments(text=remembered),
                "call",
                _identity(session["id"], turn.id, leader["id"]),
            )
        assert missing.value.code == "agent_memory_needs_target"
        saved = write_agent_memory(
            db,
            maya,
            conversation,
            WriteAgentMemoryArguments(text=remembered, member_names=[other["name"]]),
            "call",
            _identity(session["id"], turn.id, leader["id"]),
        )
        other_participant = db.get(ConversationParticipant, other["id"])
        assert other_participant is not None
        follow = _turn(db, session["id"], other["name"], position=1)
        named_later = write_agent_memory(
            db,
            maya,
            conversation,
            WriteAgentMemoryArguments(text=remembered, member_names=[other["name"]]),
            "call",
            _identity(session["id"], follow.id, leader["id"]),
        )
        assert named_later["memories"][0]["memory_id"] == saved["memories"][0]["memory_id"]
        assert saved["memories"] == [
            {
                "memory_id": saved["memories"][0]["memory_id"],
                "agent_id": other_participant.agent_id,
                "text": remembered,
            }
        ]
        assert read_agent_memory(
            db,
            maya,
            conversation,
            ReadAgentMemoryArguments(),
            "call",
            _identity(session["id"], turn.id, other["id"]),
        )["memories"] == [{"memory_id": saved["memories"][0]["memory_id"], "text": remembered}]
        assert (
            read_agent_memory(
                db,
                maya,
                conversation,
                ReadAgentMemoryArguments(),
                "call",
                _identity(session["id"], turn.id, leader["id"]),
            )["memories"]
            == []
        )
        bowen_id = db.scalar(select(User.id).where(User.username == "bowen"))
        assert (
            db.scalar(
                select(func.count())
                .select_from(AgentAccountMemory)
                .where(AgentAccountMemory.owner_user_id == bowen_id)
            )
            == 0
        )

    assert "agent_account_memories" not in inspect.getsource(generation_adapter)
    assert "read_agent_memory" not in inspect.getsource(generation_adapter)


def test_single_agent_memory_rejects_text_that_is_not_in_the_message(
    client, database, app_bundle
) -> None:
    from app.modules.demo_baseline.service import BASELINE_VERSION_ID, ensure_demo_baseline

    _app, _database, settings = app_bundle
    del _app, _database
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    )
    assert created.status_code == 200, created.text
    with database.session() as db:
        conversation = db.get(Conversation, created.json()["id"])
        assert conversation is not None
        turn = _turn(db, conversation.id, "请记住我喜欢短回答")
        version_id = conversation.agent_version_id
        assert version_id is not None
        with pytest.raises(PlatformError) as rejected:
            write_agent_memory(
                db,
                _actor(db, "bowen"),
                conversation,
                WriteAgentMemoryArguments(text="另一件没有说过的事"),
                "call",
                _identity(conversation.id, turn.id, version_id),
            )
        assert rejected.value.code == "agent_memory_span_missing"
        saved = write_agent_memory(
            db,
            _actor(db, "bowen"),
            conversation,
            WriteAgentMemoryArguments(text="我喜欢短回答"),
            "call",
            _identity(conversation.id, turn.id, version_id),
        )
        again = write_agent_memory(
            db,
            _actor(db, "bowen"),
            conversation,
            WriteAgentMemoryArguments(text="我喜欢短回答"),
            "call",
            _identity(conversation.id, turn.id, version_id),
        )
        assert again["memories"][0]["memory_id"] == saved["memories"][0]["memory_id"]
        owner_id = db.scalar(select(User.id).where(User.username == "bowen"))
        assert (
            db.scalar(
                select(func.count())
                .select_from(AgentAccountMemory)
                .where(AgentAccountMemory.owner_user_id == owner_id)
            )
            == 1
        )
