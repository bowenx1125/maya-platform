"""The debate list has to distinguish a stalled draft from a thinking one."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.modules.debates.models import DebateTurn
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.test_wave3_mock_rag_delta import (
    COURSE_ID,
    GROUP_DEMO_ID,
    _headers,
    _insert_sql_published_agent,
)


def _draft_debate(app_factory: Callable[..., Any]) -> tuple[Any, Any, str]:
    app, database, _settings = app_factory()
    client = TestClient(app)
    client.__enter__()
    first = _insert_sql_published_agent(
        database,
        group_id=GROUP_DEMO_ID,
        name="Stall A",
        evidence="A snapshot passage for the stall projection test.",
        confirmed_persona=True,
    )
    second = _insert_sql_published_agent(
        database,
        group_id=GROUP_DEMO_ID,
        name="Stall B",
        evidence="A second snapshot passage for the stall projection test.",
        confirmed_persona=True,
    )
    _session, csrf = login(client)
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=_headers(csrf, **{"Idempotency-Key": "stall-projection-0001"}),
        json={
            "topic": "How should communities weigh speed against care?",
            "participants": [
                {"agent_id": first, "stance_mode": "open"},
                {"agent_id": second, "stance_mode": "open"},
            ],
            "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
            "round_count": 2,
        },
    )
    assert response.status_code == 201, response.text
    return client, database, str(response.json()["id"])


def _materialise_plan(database: Any, debate_id: str) -> list[Any]:
    """Create the turn rows warming would have made.

    A draft has no plan until something asks for one, and warming — the only
    asker before Start — is deliberately disabled under a test client.
    """

    from app.modules.debates.playback.sql_repository import SqlPlaybackRepository

    repository = SqlPlaybackRepository()
    with database.session() as session:
        debate = repository.get_debate(session, debate_id)
        assert debate is not None
        repository.ensure_turn_plan(session, debate)
        session.commit()
    with database.session() as session:
        return list(
            session.scalars(
                select(DebateTurn)
                .where(DebateTurn.debate_id == debate_id)
                .order_by(DebateTurn.turn_index)
            ).all()
        )


def _listed(client: TestClient, debate_id: str) -> dict[str, Any]:
    listing = client.get(f"/api/v1/courses/{COURSE_ID}/debates")
    assert listing.status_code == 200, listing.text
    for item in listing.json():
        if item["id"] == debate_id:
            return item
    raise AssertionError(f"{debate_id} missing from the course listing")


def test_a_draft_that_is_still_thinking_reports_no_stall(
    app_factory: Callable[..., Any],
) -> None:
    client, _database, debate_id = _draft_debate(app_factory)
    try:
        assert _listed(client, debate_id)["stall"] is None
    finally:
        client.__exit__(None, None, None)


def test_the_first_turn_that_will_not_generate_becomes_the_stall(
    app_factory: Callable[..., Any],
) -> None:
    """Warming stops at that turn and changes no status, so the list must say so.

    Two turns are failed here on purpose: the projection has to report the one
    warming actually stopped at, which is the earliest by plan order, not
    whichever row the database happens to return first.
    """

    client, database, debate_id = _draft_debate(app_factory)
    try:
        turns = _materialise_plan(database, debate_id)
        assert len(turns) >= 3
        with database.session() as session:
            turns = list(
                session.scalars(
                    select(DebateTurn)
                    .where(DebateTurn.debate_id == debate_id)
                    .order_by(DebateTurn.turn_index)
                ).all()
            )
            turns[1].generation_status = "failed"
            turns[1].safe_error_code = "rule_invalid"
            turns[2].generation_status = "turn_generation_failed"
            turns[2].safe_error_code = "llm_timeout"
            session.commit()
            expected_turn_id = str(turns[1].id)
            expected_round = int(turns[1].round_no)

        item = _listed(client, debate_id)
        assert item["status"] == "draft"
        assert item["stall"] == {
            "turn_id": expected_turn_id,
            "round_no": expected_round,
            "safe_error_code": "rule_invalid",
        }
    finally:
        client.__exit__(None, None, None)


def test_a_failed_turn_with_no_code_still_reports_a_stall(
    app_factory: Callable[..., Any],
) -> None:
    """A missing code must not hide the stall behind a frozen percentage."""

    client, database, debate_id = _draft_debate(app_factory)
    try:
        first = _materialise_plan(database, debate_id)[0]
        expected_turn_id, expected_round = str(first.id), int(first.round_no)
        with database.session() as session:
            turn = session.get(DebateTurn, expected_turn_id)
            assert turn is not None
            turn.generation_status = "failed"
            turn.safe_error_code = None
            session.commit()

        assert _listed(client, debate_id)["stall"] == {
            "turn_id": expected_turn_id,
            "round_no": expected_round,
            "safe_error_code": "turn_generation_failed",
        }
    finally:
        client.__exit__(None, None, None)
