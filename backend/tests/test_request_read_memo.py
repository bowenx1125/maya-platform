"""Repeated authorization reads run once per request, and never go stale across a model call.

Read breakdown (2026-10-18): one formal answer turn ran 812 SELECTs, 112 of
them distinct; the assessment context was rebuilt ~12 times and the Team
member check ~24 times. A Team turn now memoizes those reads for the request
only: each Session's copy ends with its transaction, the request-wide copy
ends at every model call, and nothing outlives the request.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.core.errors import PlatformError, not_found
from app.core.models import Agent, CourseMember
from app.core.read_memo import forget_request_reads, memoized, request_read_memo
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.models import ConversationParticipant, TeamTurnResult
from app.modules.workspace.schemas import TeamRouting
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from tests.conftest import post_message
from tests.test_mayaform_team_turns import _body, _chat, _headers


def test_memo_is_off_outside_a_request(database: Any) -> None:
    calls: list[int] = []
    with database.session() as db:
        for _ in range(3):
            memoized(db, ("k",), lambda: calls.append(1))
            memoized(db, ("k",), lambda: calls.append(1), across_sessions=True)
    assert len(calls) == 6


def test_session_memo_ends_with_its_transaction(database: Any) -> None:
    calls: list[int] = []

    def compute() -> int:
        calls.append(1)
        return len(calls)

    with request_read_memo(), database.session() as db:
        db.execute(text("SELECT 1"))  # a transaction is open, as in a real read
        assert memoized(db, ("k",), compute) == 1
        assert memoized(db, ("k",), compute) == 1
        db.commit()
        db.execute(text("SELECT 1"))
        assert memoized(db, ("k",), compute) == 2
        db.rollback()
        assert memoized(db, ("k",), compute) == 3
    with request_read_memo(), database.session() as other:
        # A new request (and Session) never sees the old one's copy.
        assert memoized(other, ("k",), compute) == 4


def test_request_memo_spans_sessions_until_a_model_call(database: Any) -> None:
    calls: list[int] = []

    def compute() -> int:
        calls.append(1)
        return len(calls)

    with request_read_memo():
        with database.session() as first:
            assert memoized(first, ("k",), compute, across_sessions=True) == 1
            first.commit()
        with database.session() as second:
            assert memoized(second, ("k",), compute, across_sessions=True) == 1
        forget_request_reads()
        with database.session() as third:
            assert memoized(third, ("k",), compute, across_sessions=True) == 2
    with request_read_memo(), database.session() as later:
        assert memoized(later, ("k",), compute, across_sessions=True) == 3


def test_a_refusal_is_never_remembered(database: Any) -> None:
    calls: list[int] = []

    def refuse() -> None:
        calls.append(1)
        raise not_found()

    with request_read_memo(), database.session() as db:
        for _ in range(2):
            with pytest.raises(PlatformError):
                memoized(db, ("k",), refuse, across_sessions=True)
    assert len(calls) == 2


def test_a_member_revoked_during_a_model_call_is_still_refused(
    client: TestClient, database: Any, monkeypatch: Any
) -> None:
    session, csrf, _actor = _chat(client, database)
    ids = [member["id"] for member in session["team"]["members"]]
    seen: list[str] = []

    def reply(request: runtime.MemberRequest) -> runtime.MemberReply:
        seen.append(request.participant_id)
        if request.participant_id == ids[1]:
            # While the first member's model call runs, the next member's
            # Agent is revoked by another request.
            with database.session() as db:
                participant = db.get(ConversationParticipant, ids[2])
                agent = db.get(Agent, participant.agent_id)
                agent.authorization_epoch += 1
                db.commit()
        return runtime.MemberReply(f"Answer from {request.participant_id[:8]}")

    monkeypatch.setattr(runtime, "invoke_mock_member", reply)
    url = f"/api/v1/conversations/{session['id']}/messages"
    response = post_message(
        client, url, headers=_headers(csrf), json=_body(session, "selected", ids=ids[1:])
    )
    assert response.status_code == 200, response.text
    assert seen == [ids[1]]
    with database.session() as db:
        states = {
            row.participant_id: row.state
            for row in db.scalars(
                select(TeamTurnResult).where(TeamTurnResult.conversation_id == session["id"])
            )
        }
    assert states[ids[1]] == "ready"
    assert states[ids[2]] != "ready"


def test_a_student_removed_during_a_model_call_is_refused_after_it(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    session, _csrf, actor_id = _chat(client, database)
    ids = [member["id"] for member in session["team"]["members"]]
    seen: list[str] = []

    def reply(request: runtime.MemberRequest) -> runtime.MemberReply:
        seen.append(request.participant_id)
        if request.participant_id == ids[1]:
            # The student's course role was read (and memoized) before this
            # call; another request removes them from the course meanwhile.
            with database.session() as db:
                memberships = db.scalars(
                    select(CourseMember).where(CourseMember.user_id == actor_id)
                ).all()
                assert memberships
                for membership in memberships:
                    db.delete(membership)
                db.commit()
        return runtime.MemberReply("Answer")

    monkeypatch.setattr(runtime, "invoke_mock_member", reply)
    with database.session() as db:
        claim = runtime.claim_team_turn(
            db,
            app_bundle[2],
            conversation_id=session["id"],
            actor_id=actor_id,
            request_id=str(uuid4()),
            expected_revision=session["revision"],
            message="One user request",
            routing=TeamRouting(mode="selected", participant_ids=ids[1:]),
        )
    runtime.execute_team_turn(database.session_factory, claim)

    assert seen == [ids[1]]
    with database.session() as db:
        states = {
            row.participant_id: row.state
            for row in db.scalars(
                select(TeamTurnResult).where(TeamTurnResult.turn_id == claim.turn_id)
            )
        }
    # Nothing is saved for a student who is no longer in the course.
    assert "ready" not in states.values(), states
