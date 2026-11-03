"""An ordinary Team's members answer one message at the same time (2026-11-03).

A member never sees a teammate's reply from the same turn (its history stops
at earlier turns), yet members ran one after another: three members waited
for three model calls in a row. They now run together, are still shown in
the stored order (Leader first), and the turn finishes exactly once. A Team
that can run a formal assessment keeps one-at-a-time.

The history read was also one query per earlier turn for every member call;
it is one query now.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any
from uuid import uuid4

from app.core.models import AgentVersion
from app.modules.auth.service import get_auth_context
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.provider_disclosure.team_standing import (
    confirm_team_standing_grant,
    prepare_team_standing_grant,
)
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamChatEvent,
    TeamTurnResult,
)
from app.modules.workspace.schemas import TeamRouting
from app.providers.control_repository import ProviderRepository
from app.providers.llm_adapter import DashScopeLLMConfig
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from tests.test_mayaform_assessment_attempts import _login
from tests.test_mayaform_team_conversations import _create
from tests.test_mayaform_teams import COURSE_ID, MAYA_ID, _headers, _make_agent_version
from tests.test_team_tool_argument_retries import _text_body
from tests.test_wave4_provider_preflight import _digest, _policy

NAMES = ("Leader", "Ada", "Bo")
CALL_SECONDS = 0.4


def _ordinary_team(
    client: TestClient, database: Any, app_bundle: Any, *, formal: bool = False
) -> tuple[Any, Any, str]:
    app, _database, base_settings = app_bundle
    _teacher_token, teacher_csrf = _login(client, "maya")
    with database.session() as db:
        ensure_demo_baseline(db, base_settings.resolved_data_root)
    version_ids: list[str] = []
    for index, name in enumerate(NAMES):
        _agent_id, version_id = _make_agent_version(
            database, owner_id=MAYA_ID, name=name, visibility="public"
        )
        with database.session() as db:
            version = db.get(AgentVersion, version_id)
            body = f"# {name}\n\nAnswer as {name}."
            if formal and index == 0:
                body += "\n\n# Team Ruleset\n\n## Formal assessment\n\nAsk one question.\n"
            version.agent_md = body
            version.avatar_config_json = json.dumps(
                {
                    "template_id": "synthetic",
                    "material_theme": "default",
                    "default_expression": "neutral",
                    "expression_strength": "low",
                    "motion_style": "calm",
                }
            )
        version_ids.append(version_id)
    team = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(teacher_csrf, f"par-{uuid4()}"),
        json={
            "display_name": f"parallel-{uuid4().hex[:6]}",
            "visibility": "public",
            "members": [
                {"agent_version_id": v, "is_leader": i == 0, "position": i}
                for i, v in enumerate(version_ids)
            ],
        },
    )
    assert team.status_code == 201, team.text
    student_token, student_csrf = _login(client, "bowen")
    session = _create(client, student_csrf, {"kind": "maya_team", "team_id": team.json()["id"]})
    conversation_id = session["id"]
    with database.session() as db:
        actor = get_auth_context(db, base_settings, student_token)
    settings = base_settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "dashscope_api_key": "synthetic-key",
            "dashscope_workspace_id": "synthetic-workspace",
            "dashscope_region": "cn-beijing",
        }
    )
    policy = _policy(
        policy_id="parallel",
        endpoint=DashScopeLLMConfig(
            api_key="synthetic-key",
            workspace_id="synthetic-workspace",
            region="cn-beijing",
            model_key=settings.llm_model,
            policy_hash=_digest("parallel-policy"),
        ).resolved_endpoint,
    )
    settings = settings.model_copy(update={"llm_provider_policy_hash": policy.policy_hash})
    app.state.settings = settings
    ProviderRepository(database).save_policy_snapshot(policy)
    with database.session() as db:
        conversation = db.get(Conversation, conversation_id)
        plan = prepare_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=conversation.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
        )
        confirm_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=conversation.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
            expected_resource_hash=plan.resource_hash,
            expected_team_epoch=plan.team_epoch,
            expected_publication_epoch=plan.publication_epoch,
        )
        db.commit()
    return actor, settings, conversation_id


class _Transport:
    """Each call takes CALL_SECONDS and answers with the speaker's name."""

    calls: list[tuple[str, float, float]] = []
    lock = threading.Lock()

    class Response:
        status_code = 200

        def __init__(self, content: bytes) -> None:
            self.content = content

    @staticmethod
    def timeout() -> float:
        return 30.0

    def post_bytes(self, _endpoint: str, *, content: bytes, **_kwargs: Any) -> Any:
        body = json.loads(content)
        system = body["messages"][0]["content"]
        speaker = next((name for name in NAMES if f"Answer as {name}." in system), "?")
        started = time.perf_counter()
        time.sleep(CALL_SECONDS)
        with self.lock:
            self.calls.append((speaker, started, time.perf_counter()))
        return self.Response(_text_body(f"{speaker} says hi."))


def _turn(database: Any, actor: Any, settings: Any, conversation_id: str, message: str) -> str:
    with database.session() as db:
        conversation = db.get(Conversation, conversation_id)
        claim = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            request_id=str(uuid4()),
            expected_revision=conversation.revision,
            message=message,
            routing=TeamRouting(mode="all"),
            actor_context=actor,
        )
    runtime.execute_team_turn(database.session_factory, claim)
    return claim.turn_id


def test_members_answer_together_in_the_stored_order(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    actor, settings, conversation_id = _ordinary_team(client, database, app_bundle)
    _Transport.calls = []
    monkeypatch.setattr("app.modules.workspace.chat_team_provider.HttpxLLMTransport", _Transport)

    turn_id = _turn(database, actor, settings, conversation_id, "大家好")

    assert sorted(speaker for speaker, _s, _e in _Transport.calls) == sorted(NAMES)
    # All three calls overlapped: one call's time, not three.
    latest_start = max(start for _n, start, _e in _Transport.calls)
    earliest_end = min(end for _n, _s, end in _Transport.calls)
    assert latest_start < earliest_end
    with database.session() as db:
        turn = db.get(ConversationTurn, turn_id)
        assert turn is not None and turn.state == "ready"
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None and conversation.active_request_id is None
        rows = db.execute(
            select(TeamTurnResult, ConversationParticipant)
            .join(
                ConversationParticipant,
                ConversationParticipant.id == TeamTurnResult.participant_id,
            )
            .where(TeamTurnResult.turn_id == turn_id)
            .order_by(TeamTurnResult.ordinal)
        ).all()
        assert [member.display_name for _result, member in rows] == list(NAMES)
        assert [result.assistant_text for result, _member in rows] == [
            f"{name} says hi." for name in NAMES
        ]
        kinds = list(
            db.scalars(
                select(TeamChatEvent.kind)
                .where(TeamChatEvent.turn_id == turn_id)
                .order_by(TeamChatEvent.sequence)
            )
        )
        sequences = list(
            db.scalars(
                select(TeamChatEvent.sequence).where(
                    TeamChatEvent.conversation_id == conversation_id
                )
            )
        )
    assert kinds.count("member_result") == 3
    assert kinds.count("turn_done") == 1 and kinds[-1] == "turn_done"
    assert len(sequences) == len(set(sequences))


def test_an_assessment_team_still_answers_one_at_a_time(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    actor, settings, conversation_id = _ordinary_team(client, database, app_bundle, formal=True)
    _Transport.calls = []
    monkeypatch.setattr("app.modules.workspace.chat_team_provider.HttpxLLMTransport", _Transport)

    turn_id = _turn(database, actor, settings, conversation_id, "大家好")

    ordered = sorted(_Transport.calls, key=lambda call: call[1])
    assert len(ordered) >= 2
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        assert earlier[2] <= later[1]
    with database.session() as db:
        turn = db.get(ConversationTurn, turn_id)
        assert turn is not None and turn.state in {"ready", "partial"}


def test_history_is_one_read_however_long_the_chat(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    actor, settings, conversation_id = _ordinary_team(client, database, app_bundle)
    monkeypatch.setattr(_Transport, "post_bytes", _fast_post)
    monkeypatch.setattr("app.modules.workspace.chat_team_provider.HttpxLLMTransport", _Transport)
    for index in range(6):
        _turn(database, actor, settings, conversation_id, f"第 {index} 句")

    reads: list[str] = []

    def count(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append(statement)

    with database.session() as db:
        turn_position = db.scalar(
            select(ConversationTurn.position)
            .where(ConversationTurn.conversation_id == conversation_id)
            .order_by(ConversationTurn.position.desc())
            .limit(1)
        )
        event.listen(database.engine, "before_cursor_execute", count)
        try:
            history = runtime.team_history(db, conversation_id, int(turn_position) + 1, None)
        finally:
            event.remove(database.engine, "before_cursor_execute", count)
    assert sum(1 for item in history if item["role"] == "user") == 6
    assert sum(1 for item in history if item["role"] == "system") == 18
    # attempt lookup, Knowledge-notice fallback, turns, replies: no per-turn read.
    assert len(reads) <= 4, len(reads)

    # Whole turn, for the record (2026-11-03, 3 members, 6 earlier turns):
    # 703 SELECTs before, ~645 now; at 20 earlier turns 745 -> 629. Most of
    # what is left is the Provider standing check run before each send.
    measured: list[str] = []

    def count_turn(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            measured.append(statement)

    event.listen(database.engine, "before_cursor_execute", count_turn)
    try:
        _turn(database, actor, settings, conversation_id, "再来一句")
    finally:
        event.remove(database.engine, "before_cursor_execute", count_turn)
    print(f"MEASURE team_turn_selects members=3 earlier_turns=6 selects={len(measured)}")


def _fast_post(self: Any, _endpoint: str, *, content: bytes, **_kwargs: Any) -> Any:
    body = json.loads(content)
    system = body["messages"][0]["content"]
    speaker = next((name for name in NAMES if f"Answer as {name}." in system), "?")
    return _Transport.Response(_text_body(f"{speaker} says hi."))
