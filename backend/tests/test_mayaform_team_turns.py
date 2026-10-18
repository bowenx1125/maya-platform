"""Durable Team target routing/recovery with synthetic member execution only."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from app.core.errors import PlatformError
from app.core.models import Agent, ProviderOperation, SessionRecord
from app.modules.auth.service import session_hash
from app.modules.workspace import chat_team_context, chat_team_sdk
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.chat_stream import stream_team_events
from app.modules.workspace.chat_team_context import TeamMemberContext
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
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine

from tests.conftest import login, post_message
from tests.test_mayaform_team_conversations import (
    COURSE_ID,
    MAYA_ID,
    _config,
    _create,
    _fingerprint,
    _headers,
    _make_agent_version,
    _seed_0040,
)
from tests.test_wave4_provider_preflight import _digest, _policy


def _chat(
    client: TestClient, database: Any, *, member_count: int = 3
) -> tuple[dict[str, Any], str, str]:
    _, csrf = login(client, "maya")
    versions = [
        _make_agent_version(
            database, owner_id=MAYA_ID, name=f"Member {index}", visibility="public"
        )[1]
        for index in range(member_count)
    ]
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"b2-team-{uuid4()}"),
        json={
            "display_name": "Three perspectives",
            "visibility": "public",
            "members": [
                {"agent_version_id": version_id, "position": index, "is_leader": index == 0}
                for index, version_id in enumerate(versions)
            ],
        },
    )
    assert response.status_code == 201, response.text
    user, csrf = login(client, "bowen")
    session = _create(client, csrf, {"kind": "maya_team", "team_id": response.json()["id"]})
    return session, csrf, user["user"]["id"]


def _body(session: dict[str, Any], mode: str, *, ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "request_id": str(uuid4()),
        "expected_revision": session["revision"],
        "message": "  中文原文 @someone\nDo not guess textual targets.  ",
        "routing": {"mode": mode, "participant_ids": ids or []},
    }


def _configure_team_llm_preflight(settings: Any, database: Any) -> None:
    settings.llm_provider = "dashscope"
    settings.dashscope_api_key = "synthetic-key"
    settings.dashscope_workspace_id = "synthetic-workspace"
    settings.dashscope_region = "cn-beijing"
    config = DashScopeLLMConfig(
        api_key=settings.dashscope_api_key,
        workspace_id=settings.dashscope_workspace_id,
        region=settings.dashscope_region,
        model_key=settings.llm_model,
        policy_hash=_digest("team-stream-session-handoff"),
    )
    policy = _policy(
        policy_id="team-stream-session-handoff",
        endpoint=config.resolved_endpoint,
    )
    settings.llm_provider_policy_hash = policy.policy_hash
    # A developer .env can enable demo auto-confirm standing consent; the
    # tests below cover the confirmation-required gate, so force it off.
    settings.demo_auto_confirm_provider = False
    settings.provider_standing_consent = False
    ProviderRepository(database).save_policy_snapshot(policy)


@pytest.mark.parametrize("session_change", ["none", "revoked", "deleted", "expired"])
def test_stream_worker_handoff_rechecks_the_request_session_for_every_member(
    session_change: str,
    client: TestClient,
    database: Any,
    app_bundle: Any,
    monkeypatch: Any,
) -> None:
    session, csrf, _actor_id = _chat(client, database, member_count=4)
    _app, _database, settings = app_bundle
    _configure_team_llm_preflight(settings, database)
    synthetic_context = TeamMemberContext(
        agent_md="# Synthetic member",
        knowledge_json="{}",
        sources=(),
        content_hash=_digest("synthetic member context"),
    )
    monkeypatch.setattr(
        chat_team_context,
        "load_member_context",
        lambda *_args, **_kwargs: synthetic_context,
    )
    selected_members: list[str] = []
    original_run_selected_agent = chat_team_sdk.run_selected_agent

    def record_selected_agent(spec: Any, **kwargs: Any) -> Any:
        selected_members.append(spec.participant_id)
        return original_run_selected_agent(spec, **kwargs)

    monkeypatch.setattr(chat_team_sdk, "run_selected_agent", record_selected_agent)
    transport = Mock(side_effect=AssertionError("Team preflight must not call a Provider"))
    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.HttpxLLMTransport.post_bytes",
        transport,
    )

    raw_session_token = client.cookies.get("maya_session")
    assert raw_session_token
    session_id_hash = session_hash(raw_session_token)
    if session_change != "none":
        from app.modules.workspace import chat as chat_module

        original_stream = chat_module.stream_team_events

        def change_session_before_worker(
            selected_database: Any,
            conversation_id: str,
            selected_actor_id: str,
            claim: Any,
            after_sequence: int = 0,
            on_finished: Any = None,
            write_slot: Any = None,
        ) -> Any:
            if not claim.created:
                return original_stream(
                    selected_database,
                    conversation_id,
                    selected_actor_id,
                    claim,
                    after_sequence,
                    on_finished=on_finished,
                    write_slot=write_slot,
                )
            with selected_database.session() as db:
                auth_session = db.get(SessionRecord, session_id_hash)
                assert auth_session is not None
                if session_change == "revoked":
                    auth_session.revoked_at = datetime.now(UTC)
                elif session_change == "deleted":
                    db.delete(auth_session)
                else:
                    auth_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            return original_stream(
                selected_database,
                conversation_id,
                selected_actor_id,
                claim,
                after_sequence,
                on_finished=on_finished,
                write_slot=write_slot,
            )

        monkeypatch.setattr(chat_module, "stream_team_events", change_session_before_worker)

    body = _body(session, "all")
    url = f"/api/v1/conversations/{session['id']}/messages:stream"
    headers = {**_headers(csrf), "Accept": "text/event-stream"}
    response = client.post(url, headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.text.count("event: member_result") == 4
    assert response.text.count("event: turn_done") == 1

    member_ids = [member["id"] for member in session["team"]["members"]]
    with database.session() as db:
        turn = db.get(ConversationTurn, body["request_id"])
        row = db.get(Conversation, session["id"])
        results = db.scalars(
            select(TeamTurnResult)
            .where(TeamTurnResult.turn_id == body["request_id"])
            .order_by(TeamTurnResult.ordinal)
        ).all()
        assert turn is not None and row is not None
        assert row.active_request_id is None
        assert [result.participant_id for result in results] == member_ids
        if session_change == "none":
            assert [result.state for result in results] == ["failed"] * 4
            assert [result.safe_error_code for result in results] == [
                "provider_confirmation_required"
            ] * 4
            assert selected_members == member_ids
        else:
            assert [result.state for result in results] == ["failed"] * 4
            assert [result.safe_error_code for result in results] == ["not_found"] * 4
            assert selected_members == []
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0
        assert (
            db.scalar(select(func.coalesce(func.sum(ProviderOperation.charged_request_count), 0)))
            == 0
        )
    assert transport.call_count == 0

    previous_execution_count = len(selected_members)
    if session_change != "none":
        _actor, csrf = login(client, "bowen")
        headers = {**_headers(csrf), "Accept": "text/event-stream"}
    replay = client.post(url, headers=headers, json=body)
    assert replay.status_code == 200, replay.text
    assert len(selected_members) == previous_execution_count
    assert transport.call_count == 0
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


@pytest.mark.parametrize("mode", ["selected", "all"])
def test_explicit_targets_are_frozen_once_and_do_not_add_a_leader_summary(
    client: TestClient, database: Any, monkeypatch: Any, mode: str
) -> None:
    session, csrf, actor_id = _chat(client, database)
    ids = [member["id"] for member in session["team"]["members"]]
    seen: list[runtime.MemberRequest] = []

    def reply(request: runtime.MemberRequest) -> runtime.MemberReply:
        seen.append(request)
        return runtime.MemberReply(f"Reply {request.speaker_name}")

    monkeypatch.setattr(runtime, "invoke_mock_member", reply)
    body = _body(session, mode, ids=[ids[2], ids[1], ids[1]])
    url = f"/api/v1/conversations/{session['id']}/messages"
    response = post_message(client, url, headers=_headers(csrf), json=body)
    assert response.status_code == 200, response.text
    turn = [item for item in response.json()["turns"] if item["user_text"]][-1]
    expected = ids if mode == "all" else ids[1:]
    assert [request.participant_id for request in seen] == expected
    assert all(request.actor_id == actor_id for request in seen)
    # Without a complete published recipe the Team has no Leader opening.
    assert all(request.history == () and request.message == body["message"] for request in seen)
    assert turn["user_text"] == body["message"] and turn["assistant_text"] is None
    assert turn["state"] == "ready"
    assert [result["participant_id"] for result in turn["member_results"]] == expected
    assert post_message(client, url, headers=_headers(csrf), json=body).json() == response.json()
    assert len(seen) == len(expected)
    changed = {**body, "message": body["message"] + "x"}
    assert post_message(client, url, headers=_headers(csrf), json=changed).status_code == 409
    if mode == "selected":
        changed = {**body, "routing": {"mode": "selected", "participant_ids": [ids[0]]}}
        assert post_message(client, url, headers=_headers(csrf), json=changed).status_code == 409
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(ConversationTurn)) == 1
        parent = db.get(ConversationTurn, body["request_id"])
        assert parent is not None and parent.assistant_text is None and parent.sources_json == "[]"
        assert db.scalar(select(func.count()).select_from(TeamTurnResult)) == len(expected)
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


def test_selected_preflight_blocks_revoked_target_without_blocking_other_members(
    client: TestClient, database: Any, monkeypatch: Any
) -> None:
    session, csrf, _actor = _chat(client, database)
    ids = [member["id"] for member in session["team"]["members"]]
    with database.session() as db:
        participant = db.get(ConversationParticipant, ids[2])
        agent = db.get(Agent, participant.agent_id)
        agent.authorization_epoch += 1
    current = client.get(f"/api/v1/conversations/{session['id']}").json()
    assert current["can_send"] is True
    assert current["team"]["available"] is False
    assert [member["available"] for member in current["team"]["members"]] == [True, True, False]
    seen: list[str] = []

    def reply(request: runtime.MemberRequest) -> runtime.MemberReply:
        seen.append(request.participant_id)
        return runtime.MemberReply("Allowed answer")

    monkeypatch.setattr(runtime, "invoke_mock_member", reply)
    url = f"/api/v1/conversations/{session['id']}/messages"
    blocked = post_message(
        client, url, headers=_headers(csrf), json=_body(session, "selected", ids=ids[1:])
    )
    assert blocked.status_code == 404 and seen == []
    blocked = post_message(
        client, url, headers=_headers(csrf), json=_body(session, "selected", ids=[str(uuid4())])
    )
    assert blocked.status_code == 404 and seen == []
    allowed = post_message(
        client, url, headers=_headers(csrf), json=_body(session, "selected", ids=[ids[1]])
    )
    assert allowed.status_code == 200, allowed.text
    assert seen == [ids[1]]
    assert [item for item in allowed.json()["turns"] if item["user_text"]][-1]["state"] == "ready"


def test_partial_unknown_replay_followup_full_history_and_late_result_are_isolated(
    client: TestClient, database: Any, monkeypatch: Any
) -> None:
    session, csrf, _actor = _chat(client, database)
    ids = [member["id"] for member in session["team"]["members"]]
    seen: list[runtime.MemberRequest] = []

    def reply(request: runtime.MemberRequest) -> runtime.MemberReply:
        seen.append(request)
        if request.participant_id == ids[2]:
            raise PlatformError("team_acceptance_unknown", "Synthetic unknown receipt.", 503)
        return runtime.MemberReply("Accepted member answer")

    monkeypatch.setattr(runtime, "invoke_mock_member", reply)
    url = f"/api/v1/conversations/{session['id']}/messages"
    body = _body(session, "selected", ids=ids[1:])
    response = post_message(client, url, headers=_headers(csrf), json=body)
    assert response.status_code == 200, response.text
    first = [item for item in response.json()["turns"] if item["user_text"]][-1]
    assert first["state"] == "partial"
    assert [result["state"] for result in first["member_results"]] == [
        "ready",
        "acceptance_unknown",
    ]
    assert post_message(client, url, headers=_headers(csrf), json=body).json() == response.json()
    assert len(seen) == 2
    followup = {**_body(response.json(), "selected", ids=[ids[1]]), "message": "Follow-up"}
    continued = post_message(client, url, headers=_headers(csrf), json=followup)
    assert continued.status_code == 200, continued.text
    assert [turn["state"] for turn in continued.json()["turns"]] == ["partial", "ready"]
    history = seen[-1].history
    assert history[0] == {"role": "user", "content": body["message"]}
    assert history[1]["content"].endswith("Accepted member answer")
    assert history[1]["name"] != ids[1]
    assert "acceptance_unknown" in history[2]["content"]
    assert all(item["content"] != "Follow-up" for item in history)
    with database.session() as db:
        old_turn = db.get(ConversationTurn, body["request_id"])
        token = old_turn.claim_token
    assert (
        runtime.settle_member(
            database.session_factory,
            body["request_id"],
            token,
            first["member_results"][1]["id"],
            reply=runtime.MemberReply("Late wrong answer"),
        )
        is False
    )
    assert client.get(f"/api/v1/conversations/{session['id']}").json() == continued.json()


def test_sse_events_replay_by_durable_sequence_without_execution(
    client: TestClient, database: Any, monkeypatch: Any
) -> None:
    session, csrf, _actor = _chat(client, database)
    ids = [member["id"] for member in session["team"]["members"]]
    seen: list[str] = []

    def reply(request: runtime.MemberRequest) -> runtime.MemberReply:
        seen.append(request.participant_id)
        return runtime.MemberReply("Persisted member answer")

    monkeypatch.setattr(runtime, "invoke_mock_member", reply)
    body = _body(session, "all")
    url = f"/api/v1/conversations/{session['id']}/messages:stream"
    headers = {**_headers(csrf), "Accept": "text/event-stream"}
    first = client.post(url, headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert seen == ids
    assert first.text.count("event: member_result") == 3
    assert first.text.count("event: turn_done") == 1
    sequences = [int(line[4:]) for line in first.text.splitlines() if line.startswith("id: ")]
    assert sequences == [1, 2, 3, 4, 5]
    replay = client.post(url, headers={**headers, "Last-Event-ID": "2"}, json=body)
    assert replay.status_code == 200 and seen == ids
    assert [int(line[4:]) for line in replay.text.splitlines() if line.startswith("id: ")] == [
        3,
        4,
        5,
    ]
    with database.session() as db:
        row = db.get(Conversation, session["id"])
        assert row.active_request_id is None
        assert db.scalar(select(func.count()).select_from(TeamChatEvent)) == 5


@pytest.mark.asyncio
async def test_sse_disconnect_keeps_the_durable_team_run_alive(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    session, _csrf, actor_id = _chat(client, database)
    ids = [member["id"] for member in session["team"]["members"]]
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def reply(request: runtime.MemberRequest) -> runtime.MemberReply:
        if request.participant_id == ids[2]:
            started.set()
            assert release.wait(5)
            finished.set()
        return runtime.MemberReply(
            "Accepted before disconnect"
            if request.participant_id == ids[1]
            else "Late must not publish"
        )

    monkeypatch.setattr(runtime, "invoke_mock_member", reply)
    with database.session() as db:
        claim = runtime.claim_team_turn(
            db,
            app_bundle[2],
            conversation_id=session["id"],
            actor_id=actor_id,
            request_id=str(uuid4()),
            expected_revision=session["revision"],
            message="One original user request",
            routing=TeamRouting(mode="selected", participant_ids=ids[1:]),
        )
    stream = stream_team_events(database, session["id"], actor_id, claim)
    assert b"turn_started" in await anext(stream)
    assert b"member_result" in await anext(stream)
    next_event = asyncio.create_task(anext(stream))
    assert await asyncio.to_thread(started.wait, 2)
    next_event.cancel()
    with pytest.raises(asyncio.CancelledError):
        await next_event
    release.set()
    assert await asyncio.to_thread(finished.wait, 2)
    for _ in range(100):
        with database.session() as db:
            # SQLite does not begin a read transaction for SELECTs here; keep
            # turn and member states in one committed snapshot.
            snapshot = db.execute(
                select(
                    ConversationTurn.state,
                    Conversation.active_request_id,
                    TeamTurnResult.state,
                    TeamTurnResult.assistant_text,
                )
                .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
                .join(TeamTurnResult, TeamTurnResult.turn_id == ConversationTurn.id)
                .where(
                    ConversationTurn.id == claim.turn_id,
                    Conversation.id == session["id"],
                )
                .order_by(TeamTurnResult.ordinal)
            ).all()
            if snapshot and snapshot[0][0] == "ready":
                assert {record[0] for record in snapshot} == {"ready"}
                assert all(record[1] is None for record in snapshot)
                assert [record[2] for record in snapshot] == ["ready", "ready"]
                assert snapshot[1][3] == "Late must not publish"
                break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("The durable Team run did not settle after its SSE observer disconnected.")
    await stream.aclose()


def test_pause_fences_late_member_and_resume_uses_a_new_claim(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    session, _csrf, actor_id = _chat(client, database)
    ids = [member["id"] for member in session["team"]["members"]]
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    late_calls = 0

    def reply(request: runtime.MemberRequest) -> runtime.MemberReply:
        nonlocal late_calls
        if request.participant_id == ids[2]:
            late_calls += 1
            if late_calls == 1:
                started.set()
                assert release.wait(5)
                finished.set()
                return runtime.MemberReply("Stale response after pause")
            return runtime.MemberReply("Response after resume")
        return runtime.MemberReply("Committed before pause")

    monkeypatch.setattr(runtime, "invoke_mock_member", reply)
    with database.session() as db:
        claim = runtime.claim_team_turn(
            db,
            app_bundle[2],
            conversation_id=session["id"],
            actor_id=actor_id,
            request_id=str(uuid4()),
            expected_revision=session["revision"],
            message="Keep this request durable",
            routing=TeamRouting(mode="selected", participant_ids=ids[1:]),
        )
    worker = threading.Thread(
        target=runtime.execute_team_turn,
        args=(database.session_factory, claim),
        daemon=True,
    )
    worker.start()
    assert started.wait(2)
    with database.session() as db:
        runtime.pause_team_turn(
            db,
            conversation_id=session["id"],
            actor_id=actor_id,
            turn_id=claim.turn_id,
        )
    release.set()
    worker.join(2)
    assert finished.is_set() and not worker.is_alive()
    with database.session() as db:
        turn = db.get(ConversationTurn, claim.turn_id)
        results = db.scalars(
            select(TeamTurnResult)
            .where(TeamTurnResult.turn_id == claim.turn_id)
            .order_by(TeamTurnResult.ordinal)
        ).all()
        assert turn.state == "paused" and turn.claim_token != claim.token
        assert [result.state for result in results] == ["ready", "running"]
        assert results[0].assistant_text == "Committed before pause"
        assert results[1].assistant_text is None

    with database.session() as db:
        resumed = runtime.resume_team_turn(
            db,
            app_bundle[2],
            conversation_id=session["id"],
            actor_id=actor_id,
            turn_id=claim.turn_id,
        )
    assert resumed.token != claim.token
    runtime.execute_team_turn(database.session_factory, resumed)
    with database.session() as db:
        turn = db.get(ConversationTurn, claim.turn_id)
        results = db.scalars(
            select(TeamTurnResult)
            .where(TeamTurnResult.turn_id == claim.turn_id)
            .order_by(TeamTurnResult.ordinal)
        ).all()
        assert turn.state == "ready"
        assert [result.assistant_text for result in results] == [
            "Committed before pause",
            "Response after resume",
        ]
        assert late_calls == 2


def test_startup_settles_member_states_without_reexecution(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    session, _csrf, actor_id = _chat(client, database)
    ids = [member["id"] for member in session["team"]["members"]]
    with database.session() as db:
        claim = runtime.claim_team_turn(
            db,
            app_bundle[2],
            conversation_id=session["id"],
            actor_id=actor_id,
            request_id=str(uuid4()),
            expected_revision=session["revision"],
            message="Recover only",
            routing=TeamRouting(mode="all"),
        )
    result_ids = runtime.result_ids(database.session_factory, claim.turn_id)
    runtime.execute_member(database.session_factory, claim.turn_id, claim.token, result_ids[0])
    with database.session() as db:
        turn = db.get(ConversationTurn, claim.turn_id)
        turn.mode = "real"
        pending = db.get(TeamTurnResult, result_ids[1])
        pending.state = "running"
    monkeypatch.setattr(
        runtime, "invoke_mock_member", lambda _: pytest.fail("Recovery must not invoke")
    )
    with database.session() as db:
        assert runtime.recover_team_runs(db) == 1
    with database.session() as db:
        assert runtime.recover_team_runs(db) == 0
        turn = db.get(ConversationTurn, claim.turn_id)
        results = db.scalars(
            select(TeamTurnResult)
            .where(TeamTurnResult.turn_id == claim.turn_id)
            .order_by(TeamTurnResult.ordinal)
        ).all()
        assert turn.state == "paused"
        assert [result.state for result in results] == ["ready", "pending", "pending"]
    assert len(ids) == 3


@pytest.mark.parametrize(
    "failure_match", [None, "CREATE TABLE team_turn_results", "UPDATE alembic_version"]
)
def test_0042_populated_single_history_and_atomic_rollback(
    tmp_path: Path, failure_match: str | None
) -> None:
    import sqlite3

    path = tmp_path / "team-turns.sqlite3"
    _seed_0040(path)
    command.upgrade(_config(path), "0041_team_conversations")
    before = _fingerprint(path)
    with sqlite3.connect(path) as db:
        old_turns = db.execute("SELECT * FROM agent_conversation_turns ORDER BY id").fetchall()
        ledger = db.execute("SELECT * FROM provider_operations ORDER BY id").fetchall()
    if failure_match:

        def fail(_db: Any, _cursor: Any, sql: str, _params: Any, _ctx: Any, _many: bool) -> None:
            if failure_match in sql:
                raise RuntimeError("0042 injected failure")

        event.listen(Engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(RuntimeError, match="0042 injected failure"):
                command.upgrade(_config(path), "0042_team_turn_results")
        finally:
            event.remove(Engine, "before_cursor_execute", fail)
        assert _fingerprint(path) == before
    command.upgrade(_config(path), "0042_team_turn_results")
    with sqlite3.connect(path) as db:
        assert (
            db.execute(
                "SELECT id,conversation_id,position,user_text,assistant_text,sources_json,mode,"
                "state,safe_error_code,created_at FROM agent_conversation_turns ORDER BY id"
            ).fetchall()
            == old_turns
        )
        assert db.execute("SELECT * FROM provider_operations ORDER BY id").fetchall() == ledger
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_extract_team_ruleset_only_from_guide_heading() -> None:
    assert runtime.extract_team_ruleset("# Persona\n\nHello.") is None
    assert runtime.extract_team_ruleset("# Team Ruleset\n") == ""
    body = runtime.extract_team_ruleset(
        "# Guide\n\nLead the room.\n\n"
        "# Team Ruleset\n\n"
        "## Formal assessment\n"
        "answer_recorder: Jade\n"
        "question_guide: Bowen\n"
        "scorer: Jade\n"
        "summarizer: Kaikai\n"
        "student_round_order: Jade, Bowen\n\n"
        "## Informal\n"
        "Only Courser replies at length; others acknowledge briefly.\n\n"
        "# Notes\n\nIgnore for routing.\n"
    )
    assert body is not None
    assert "scorer: Jade" in body
    assert "## Informal" in body
    system = runtime._member_system(
        "# Member\n\nSpeak.",
        "{}",
        team_ruleset=body,
        speaker_name="Scorer",
    )
    assert "You are Scorer." in system
    assert "<team_informal>" in system
    assert "Only Courser replies at length" in system
    assert "does not rename you" in system
    assert "scorer: Jade" not in system
    assert "<team_ruleset>" not in system
    assert system.index("You are Scorer.") < system.index("<team_informal>")
    assert system.rstrip().endswith(
        "You are Scorer. Speak only as yourself to the student. "
        "Do not claim another member's name, role, or title, and do not "
        "introduce yourself as anyone else."
    )
    assert "saying 正式测评" not in system
    leader = runtime._member_system(
        "# Member\n\nSpeak.",
        "{}",
        team_ruleset=body,
        speaker_name="Bowen",
        is_leader=True,
    )
    assert "You are Bowen." in leader
    assert "saying 正式测评" in leader
    assert "not on every reply" in leader
    assert "scorer: Jade" not in leader
    active = runtime._member_system(
        "# Member\n\nSpeak.",
        "{}",
        assessment_active=True,
        team_ruleset=body,
        speaker_name="Bowen",
        is_leader=True,
    )
    assert "saying 正式测评" not in active
    assert "<active_assessment_action_protocol>" in active
    defaults_only = runtime._member_system("# Member\n\nSpeak.", "{}")
    assert "<team_ruleset>" not in defaults_only
    assert "<team_informal>" not in defaults_only
    assert "no # Team Ruleset section" in defaults_only
    assert "You are " not in defaults_only
    assert "saying 正式测评" not in defaults_only
    leader_defaults = runtime._member_system(
        "# Member\n\nSpeak.", "{}", speaker_name="Guide", is_leader=True
    )
    assert "saying 正式测评" in leader_defaults
    assert "no # Team Ruleset section" in leader_defaults


def test_history_speaker_name_keeps_ascii_and_sanitizes_the_rest() -> None:
    participant_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert runtime.history_speaker_name("Scorer", participant_id) == "Scorer"
    assert runtime.history_speaker_name("评分员", participant_id) == "aaaaaaaa"
    assert runtime.history_speaker_name("Jade Li", participant_id) == "Jade_Li_aaaaaaaa"


def test_ordinary_turn_runs_the_leader_first_and_an_at_mention_must_reply(
    client: TestClient, database: Any, monkeypatch: Any
) -> None:
    # The leader sits last by position; ordinary chat still asks it first.
    _, csrf = login(client, "maya")
    versions = [
        _make_agent_version(
            database, owner_id=MAYA_ID, name=f"Member {index}", visibility="public"
        )[1]
        for index in range(3)
    ]
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"b2-team-{uuid4()}"),
        json={
            "display_name": "Leader last",
            "visibility": "public",
            "members": [
                {"agent_version_id": version_id, "position": index, "is_leader": index == 2}
                for index, version_id in enumerate(versions)
            ],
        },
    )
    assert created.status_code == 201, created.text
    _, csrf = login(client, "bowen")
    session = _create(client, csrf, {"kind": "maya_team", "team_id": created.json()["id"]})
    members = session["team"]["members"]
    leader = next(member for member in members if member["is_leader"])
    others = [member["id"] for member in members if not member["is_leader"]]
    seen: list[runtime.MemberRequest] = []

    def reply(request: runtime.MemberRequest) -> runtime.MemberReply:
        seen.append(request)
        return runtime.MemberReply(f"Reply {request.speaker_name}")

    monkeypatch.setattr(runtime, "invoke_mock_member", reply)
    url = f"/api/v1/conversations/{session['id']}/messages"
    body = {**_body(session, "all"), "message": "Hello everyone"}
    response = post_message(client, url, headers=_headers(csrf), json=body)
    assert response.status_code == 200, response.text
    turn = [item for item in response.json()["turns"] if item["user_text"]][-1]
    assert [request.participant_id for request in seen] == [leader["id"], *others]
    assert [result["participant_id"] for result in turn["member_results"]] == [
        leader["id"],
        *others,
    ]
    assert all("@-mentioned you" not in request.system_message for request in seen)

    target = next(member for member in members if member["id"] == others[1])
    seen.clear()
    mention = {
        "request_id": str(uuid4()),
        "expected_revision": response.json()["revision"],
        "message": f"@{target['name']} 你怎么看",
        "routing": {"mode": "selected", "participant_ids": [target["id"]]},
    }
    response = post_message(client, url, headers=_headers(csrf), json=mention)
    assert response.status_code == 200, response.text
    assert [request.participant_id for request in seen] == [target["id"]]
    assert "You must reply" in seen[0].system_message
    assert "do not leave the reply empty" in seen[0].system_message


def test_member_system_marks_only_an_at_mentioned_member() -> None:
    plain = runtime._member_system("# Member\n\nSpeak.", "{}", speaker_name="Ada")
    named = runtime._member_system("# Member\n\nSpeak.", "{}", speaker_name="Ada", mentioned=True)
    assert "leave the reply empty" in plain and "You must reply" not in plain
    assert "You must reply" in named
    # A live assessment ledger chooses speakers; the mention line never applies.
    active = runtime._member_system(
        "# Member\n\nSpeak.", "{}", assessment_active=True, speaker_name="Ada", mentioned=True
    )
    assert "You must reply" not in active


def test_mention_parser_matches_longest_name_and_ignores_unknown() -> None:
    from app.modules.workspace.mention_parse import mentioned_names

    names = ["Guider", "Scorer", "Scorer Pro"]
    assert mentioned_names("@Scorer你是干嘛的", names) == ["Scorer"]
    assert mentioned_names("@Scorer Pro hi", names) == ["Scorer Pro"]
    assert mentioned_names("@Nobody 你好", names) == []
    assert mentioned_names("```\n@Guider\n``` x", names) == []
    assert mentioned_names("@Scorer @Guider @Scorer", names) == ["Scorer", "Guider"]


def test_wrong_name_at_mention_falls_back_to_default_reply_rules(
    client: TestClient, database: Any, monkeypatch: Any
) -> None:
    session, csrf, _ = _chat(client, database)
    members = session["team"]["members"]
    leader = next(member for member in members if member["is_leader"])
    others = [member["id"] for member in members if not member["is_leader"]]
    seen: list[runtime.MemberRequest] = []

    def reply(request: runtime.MemberRequest) -> runtime.MemberReply:
        seen.append(request)
        # Non-leaders may stay silent by relevance; that is not a failure.
        text = "" if request.participant_id != leader["id"] else "Leader reply"
        return runtime.MemberReply(text)

    monkeypatch.setattr(runtime, "invoke_mock_member", reply)
    url = f"/api/v1/conversations/{session['id']}/messages"
    body = {**_body(session, "all"), "message": "@NoSuchMember 你好介绍你自己"}
    response = post_message(client, url, headers=_headers(csrf), json=body)
    assert response.status_code == 200, response.text
    turn = [item for item in response.json()["turns"] if item["user_text"]][-1]
    assert turn["state"] != "failed"
    assert [request.participant_id for request in seen] == [leader["id"], *others]
    assert all("@-mentioned you" not in request.system_message for request in seen)
