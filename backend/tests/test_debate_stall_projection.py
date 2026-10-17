"""The debate list has to distinguish a stalled draft from a thinking one."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.modules.debates.models import Debate, DebateTurn, PlaybackState
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
            "round_count": 4,
        },
    )
    assert response.status_code == 201, response.text
    return client, database, str(response.json()["id"])


def _materialise_plan(database: Any, debate_id: str) -> list[Any]:
    """Return plan rows (create now ensures them; this stays idempotent).

    Warming is disabled under a test client, so older tests called this to
    invent turns. Line C M2 create/get also ask for the plan, so create already
    leaves turns + a head prepare job; re-calling ensure is a no-op.
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


@pytest.mark.parametrize("playback_status", ["ready", "paused", "playing", "completed"])
def test_playback_age_does_not_create_a_stall(
    app_factory: Callable[..., Any], playback_status: str
) -> None:
    client, database, debate_id = _draft_debate(app_factory)
    try:
        first = _materialise_plan(database, debate_id)[0]
        with database.session() as session:
            debate = session.get(Debate, debate_id)
            state = session.scalar(
                select(PlaybackState).where(PlaybackState.debate_id == debate_id)
            )
            assert debate is not None and state is not None
            debate.status = "debate_finished" if playback_status == "completed" else "running"
            state.status = playback_status
            state.mode = "live"
            state.current_turn_id = first.id
            state.updated_at = datetime.now(UTC) - timedelta(hours=1)
            session.commit()

        item = _listed(client, debate_id)
        assert item["stall"] is None
        assert item["status"] == (
            "debate_finished" if playback_status == "completed" else "running"
        )
    finally:
        client.__exit__(None, None, None)

def test_create_draft_materialises_head_prepare_job_without_prewarm(
    app_factory: Callable[..., Any],
) -> None:
    """Create must not wait for prewarm to own the slot before plan/job exist."""

    from sqlalchemy import text

    client, database, debate_id = _draft_debate(app_factory)
    try:
        with database.session() as session:
            turns = list(
                session.scalars(
                    select(DebateTurn)
                    .where(DebateTurn.debate_id == debate_id)
                    .order_by(DebateTurn.turn_index)
                ).all()
            )
            assert turns, "create must materialise the turn plan"
            head = turns[0]
            job = session.execute(
                text(
                    "SELECT state, claim_token, safe_error_code, operation "
                    "FROM jobs WHERE debate_id=:debate_id AND turn_id=:turn_id"
                ),
                {"debate_id": debate_id, "turn_id": str(head.id)},
            ).one()
            assert tuple(job) == ("pending", None, None, "debate_turn_prepare")

        detail = client.get(f"/api/v1/debates/{debate_id}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["turn_protocol"] == "segments_v2"
        assert body["preview_turns"], "Preview must list unpublished preparing turns"
        assert body["preview_turns"][0]["id"] == str(head.id)
        assert body["preview_turns"][0]["generation_status"] in {
            "pending",
            "running",
            "failed",
        }
        assert _listed(client, debate_id)["stall"] is None
    finally:
        client.__exit__(None, None, None)


def test_aged_pending_draft_projects_preparation_timeout_for_stall_and_preview(
    app_factory: Callable[..., Any],
) -> None:
    """After 90s, list Stalled + Preview Audio Not Ready/Retry anchors exist."""

    from sqlalchemy import text

    client, database, debate_id = _draft_debate(app_factory)
    try:
        stale = datetime.now(UTC) - timedelta(seconds=120)
        with database.session() as session:
            turns = list(
                session.scalars(
                    select(DebateTurn)
                    .where(DebateTurn.debate_id == debate_id)
                    .order_by(DebateTurn.turn_index)
                ).all()
            )
            assert turns
            head = turns[0]
            for turn in turns:
                turn.updated_at = stale
                turn.created_at = stale
            session.execute(
                text(
                    "UPDATE jobs SET updated_at=:stale, created_at=:stale "
                    "WHERE debate_id=:debate_id AND operation='debate_turn_prepare'"
                ),
                {"stale": stale, "debate_id": debate_id},
            )
            session.commit()
            head_id = str(head.id)
            head_round = int(head.round_no)

        item = _listed(client, debate_id)
        assert item["stall"] == {
            "turn_id": head_id,
            "round_no": head_round,
            "safe_error_code": "preparation_timeout",
        }

        detail = client.get(f"/api/v1/debates/{debate_id}")
        assert detail.status_code == 200, detail.text
        preview = detail.json()["preview_turns"]
        assert preview
        head_preview = next(row for row in preview if row["id"] == head_id)
        assert head_preview["generation_status"] == "failed"
        assert head_preview["safe_error_code"] == "preparation_timeout"
        assert head_preview["audio_ready"] is False
    finally:
        client.__exit__(None, None, None)

