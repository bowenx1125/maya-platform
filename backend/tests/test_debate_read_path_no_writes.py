"""GET /debates/{id} must not write; the draft plan is built by writers.

#106 made the draft detail read path build the turn plan and head prepare job.
Those writes were never committed, so on SQLite every polled GET held the
writer lock and the prewarm worker failed with ``database is locked``.  Reads
now never build the plan: create, the prewarm planner and Start do.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.models import Job
from app.modules.debates.models import DebateTurn
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select

from tests.conftest import login
from tests.test_wave2_playback import COURSE_ID, GROUP_DEMO_ID, _headers, _insert_published_agent

_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "REPLACE")


def _create_draft(client: TestClient, database: Any, csrf: str, key: str) -> str:
    agents = [
        _insert_published_agent(
            database,
            group_id=GROUP_DEMO_ID,
            name=f"Read path {key} {index}",
            evidence="A classroom can compare evidence and respect different viewpoints.",
        )
        for index in range(2)
    ]
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
        json={
            "topic": "How should a classroom compare different viewpoints?",
            "round_count": 4,
            "output_language": "en",
            "participants": [{"agent_id": item, "stance_mode": "open"} for item in agents],
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _strip_plan(database: Any, debate_id: str) -> None:
    """Model a legacy/edited draft that has no turn plan and no prepare job."""

    with database.session() as db:
        db.execute(delete(Job).where(Job.debate_id == debate_id))
        db.execute(delete(DebateTurn).where(DebateTurn.debate_id == debate_id))


def _counts(database: Any, debate_id: str) -> tuple[int, int]:
    with database.session() as db:
        turns = db.scalar(
            select(func.count()).select_from(DebateTurn).where(DebateTurn.debate_id == debate_id)
        )
        jobs = db.scalar(select(func.count()).select_from(Job).where(Job.debate_id == debate_id))
    return int(turns or 0), int(jobs or 0)


def test_create_builds_plan_and_head_prepare_job(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        _, csrf = login(client)
        debate_id = _create_draft(client, database, csrf, "create")
        turns, jobs = _counts(database, debate_id)
        assert turns > 0
        assert jobs == 1


def test_get_detail_and_list_issue_no_writes(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        _, csrf = login(client)
        debate_id = _create_draft(client, database, csrf, "get")
        _strip_plan(database, debate_id)

        writes: list[str] = []

        def _capture(_conn, _cursor, statement, _params, _context, _many) -> None:
            if statement.lstrip().upper().startswith(_WRITE_VERBS):
                writes.append(statement)

        event.listen(database.engine, "before_cursor_execute", _capture)
        try:
            for _ in range(3):
                detail = client.get(f"/api/v1/debates/{debate_id}")
                assert detail.status_code == 200, detail.text
            listing = client.get(f"/api/v1/courses/{COURSE_ID}/debates")
            assert listing.status_code == 200, listing.text
        finally:
            event.remove(database.engine, "before_cursor_execute", _capture)

        debate_writes = [item for item in writes if "debate_turns" in item or "jobs" in item]
        assert debate_writes == []
        assert _counts(database, debate_id) == (0, 0)


def test_start_on_planless_draft_is_refused_until_prewarm_backfills(app_factory: Any) -> None:
    """Start needs a ready Preview; the plan for a planless draft comes from warming."""

    app, database, _settings = app_factory()
    with TestClient(app) as client:
        _, csrf = login(client)
        debate_id = _create_draft(client, database, csrf, "start")
        _strip_plan(database, debate_id)
        detail = client.get(f"/api/v1/debates/{debate_id}").json()

        refused = client.post(
            f"/api/v1/debates/{debate_id}/start",
            headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
            json={
                "expected_revision": detail["revision"],
                "expected_current_audio_debate_id": None,
                "confirm_previous_audio_cleanup": False,
            },
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "preview_not_ready"

        assert app.state.prewarm_scheduler._plan(debate_id)
        turns, jobs = _counts(database, debate_id)
        assert turns > 0
        assert jobs == 1


def test_prewarm_planner_backfills_plan_and_head_job(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        _, csrf = login(client)
        debate_id = _create_draft(client, database, csrf, "prewarm")
        _strip_plan(database, debate_id)
        plan = app.state.prewarm_scheduler._plan(debate_id)
        assert plan, "the planner should rebuild the draft plan"
        turns, jobs = _counts(database, debate_id)
        assert turns > 0
        assert jobs == 1

        # Turns present but the head prepare job missing (the #106 D3 shape).
        with database.session() as db:
            db.execute(delete(Job).where(Job.debate_id == debate_id))
        assert app.state.prewarm_scheduler._plan(debate_id)
        assert _counts(database, debate_id) == (turns, 1)
