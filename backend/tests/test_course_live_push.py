"""Server push of a course's Live status (replaces the 5 s student poll)."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.modules.debates.models import Debate, PlaybackState
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.workspace import live_push
from app.modules.workspace.live import _live_statuses
from app.modules.workspace.live_push import CourseLiveWatcher
from app.modules.workspace.models import LivePresence
from app.modules.workspace.schemas import LiveSummary
from app.seed import COURSE_ID, TEACHER_ID
from fastapi.testclient import TestClient

from tests.conftest import login


def _summary(topic: str = "T") -> LiveSummary:
    return LiveSummary(course_id=UUID(COURSE_ID), debate_id=uuid4(), topic=topic)


def test_watcher_reads_all_courses_once_and_pushes_only_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        state: dict[str, LiveSummary | None] = {}
        calls: list[list[str]] = []

        def load(courses: list[str]) -> dict[str, LiveSummary | None]:
            calls.append(sorted(courses))
            return {key: state.get(key) for key in courses}

        watcher = CourseLiveWatcher(load, poll_seconds=3600)
        a1 = await watcher.subscribe("a")
        a2 = await watcher.subscribe("a")
        b = await watcher.subscribe("b")
        assert a1 and a2 and b
        await watcher.check_now()
        assert calls == [["a", "b"]]  # one read for every socket and course
        assert a1.get_nowait() is None and a2.get_nowait() is None and b.get_nowait() is None
        await watcher.check_now()
        assert a1.empty() and b.empty()  # unchanged: nothing sent
        live = _summary()
        state["a"] = live
        await watcher.check_now()
        assert a1.get_nowait() == live and a2.get_nowait() == live and b.empty()
        state["a"] = None
        await watcher.check_now()
        assert a1.get_nowait() is None
        monkeypatch.setattr(live_push, "MAX_SOCKETS", 3)
        assert await watcher.subscribe("c") is None  # full: client keeps slow poll
        for course, queue in (("a", a1), ("a", a2), ("b", b)):
            await watcher.unsubscribe(course, queue)
        assert watcher._task is None and watcher.socket_count() == 0

    asyncio.run(scenario())


def test_watcher_survives_a_failed_read() -> None:
    async def scenario() -> None:
        attempts = {"n": 0}

        def load(courses: list[str]) -> dict[str, LiveSummary | None]:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("db down")
            return {}

        watcher = CourseLiveWatcher(load, poll_seconds=0.01)
        queue = await watcher.subscribe("a")
        assert queue is not None
        assert await asyncio.wait_for(queue.get(), 2) is None
        await watcher.unsubscribe("a", queue)

    asyncio.run(scenario())


def _debate(database: Any) -> str:
    debate_id = str(uuid4())
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            Debate(
                id=debate_id,
                course_id=COURSE_ID,
                topic="Pushed classroom",
                background="",
                rule_set_id="ordered_multi_expert_mutual_learning_v1",
                rule_snapshot_json="{}",
                status="draft",
                revision=0,
                last_sequence=0,
                created_by=TEACHER_ID,
                created_at=now,
                updated_at=now,
            )
        )
    with database.session() as db:
        db.add(PlaybackState(id=str(uuid4()), debate_id=debate_id, created_at=now, updated_at=now))
    return debate_id


def test_course_live_socket_pushes_start_and_end(app_bundle: Any, client: TestClient) -> None:
    app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    url = f"/api/v1/courses/{COURSE_ID}/live/events"
    with client.websocket_connect(url) as socket:
        assert socket.receive()["code"] == 4401  # signed out
    debate_id = _debate(database)
    service = app.state.playback_service
    app.state.course_live_watcher = CourseLiveWatcher(
        lambda courses: _live_statuses(database, service, courses), poll_seconds=0.05
    )
    _, student_csrf = login(client, "bowen")
    with client.websocket_connect(url) as socket:
        assert socket.receive_json() == {"live": None}
        # The teacher's heartbeat (either backend) writes the shared row.
        with database.session() as db:
            db.add(
                LivePresence(
                    course_id=COURSE_ID,
                    debate_id=debate_id,
                    session_hash="other-backend",
                    lease_id=str(uuid4()),
                    expires_at=datetime.now(UTC) + timedelta(seconds=20),
                )
            )
        message = socket.receive_json()
        assert message["live"]["debate_id"] == debate_id
        assert message["live"]["topic"] == "Pushed classroom"
        with database.session() as db:
            db.get(LivePresence, COURSE_ID).expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert socket.receive_json() == {"live": None}  # the lease simply expired
    assert app.state.course_live_watcher.socket_count() == 0
    assert student_csrf
