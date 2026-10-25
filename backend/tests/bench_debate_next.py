"""Next latency benchmark (PR C). Not collected by default; run it explicitly:

    MAYA_TEST_POSTGRES_URL=... python -m pytest tests/bench_debate_next.py -s -o addopts=""

It replays a seeded classroom through the real HTTP and WebSocket surface
(Mock providers, no paid calls) and times every Next twice: alone, and while
other tabs keep reading the Debate detail. Before PR C every playback query
ran on the event loop, so Next queued behind those reads.
"""

from __future__ import annotations

import statistics
import threading
import time
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.test_classroom_lifecycle import _saved_classroom
from tests.test_wave2_playback import _headers, _receive_until

PASSES = 3
READERS = 4
READ_INTERVAL_SECONDS = 0.1


def _command(debate_id: str, command_type: str, **fields: Any) -> dict[str, Any]:
    return {
        "command_id": str(uuid4()),
        "command_type": command_type,
        "command_version": 1,
        "debate_id": debate_id,
        **fields,
    }


def _replay_pass(
    client: TestClient,
    socket: Any,
    debate_id: str,
    csrf: str,
    control_version: int,
    turn_ids: list[str],
) -> tuple[list[float], int]:
    # Each pass takes the controller first, as a teacher starting a new replay does.
    socket.send_json(
        _command(debate_id, "playback.controller.acquire", expected_control_version=control_version)
    )
    acquired = _receive_until(socket, "message_type", "controller.acquired")
    epoch = acquired["controller_epoch"]
    control_version = int(acquired["control_version"])
    replay = client.post(
        f"/api/v1/debates/{debate_id}/replay",
        headers=_headers(csrf),
        json={"expected_control_version": control_version},
    )
    assert replay.status_code == 200, replay.text
    control_version = replay.json()["control_version"]
    timings: list[float] = []
    for index, turn_id in enumerate(turn_ids):
        for command_type, extra, until in (
            (
                "playback.media.prepare",
                {"playback_action": "replay"},
                ("message_type", "media.prepared"),
            ),
            (
                "playback.started_ack",
                {"playback_action": "replay"},
                ("event_type", "replay.started"),
            ),
        ):
            socket.send_json(
                _command(
                    debate_id,
                    command_type,
                    expected_control_version=control_version,
                    controller_epoch=epoch,
                    turn_id=turn_id,
                    **extra,
                )
            )
            _receive_until(socket, *until)
        socket.send_json(
            _command(
                debate_id,
                "playback.ended_ack",
                expected_control_version=control_version,
                controller_epoch=epoch,
                turn_id=turn_id,
            )
        )
        if index == len(turn_ids) - 1:
            done = _receive_until(socket, "event_type", "replay.completed")
            return timings, int(done["payload"]["control_version"])
        waiting = _receive_until(socket, "event_type", "playback.waiting_next")
        started = time.perf_counter()
        advanced = client.post(
            f"/api/v1/debates/{debate_id}/next",
            headers=_headers(csrf),
            json={
                "expected_control_version": waiting["payload"]["control_version"],
                "expected_current_turn_id": turn_id,
            },
        )
        timings.append((time.perf_counter() - started) * 1000)
        assert advanced.status_code == 200, advanced.text
        control_version = advanced.json()["control_version"]
    raise AssertionError("replay did not complete")


def _summary(label: str, values: list[float]) -> str:
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return (
        f"{label:<22} n={len(values):>3}  p50={statistics.median(values):7.1f} ms  "
        f"p95={p95:7.1f} ms  max={ordered[-1]:7.1f} ms"
    )


def test_bench_next(app_factory: Any) -> None:
    from app.modules.debates.models import DebateTurn

    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            with database.session() as db:
                turn_ids = list(
                    db.scalars(
                        select(DebateTurn.id)
                        .where(DebateTurn.debate_id == debate_id)
                        .order_by(DebateTurn.turn_index)
                    )
                )
            _, csrf = login(client)
            results: dict[str, list[float]] = {"idle": [], "with readers": []}
            reads: list[float] = []
            with client.websocket_connect(
                f"/api/v1/debates/{debate_id}/events",
                headers={"origin": "http://testserver"},
            ) as socket:
                snapshot = _receive_until(socket, "event_type", "snapshot")
                control_version = int(snapshot["payload"]["playback"]["control_version"])

                def reader(stop: threading.Event) -> None:
                    # A tab polling the detail at a steady rate, not a flood.
                    while not stop.wait(READ_INTERVAL_SECONDS):
                        started = time.perf_counter()
                        client.get(f"/api/v1/debates/{debate_id}")
                        reads.append((time.perf_counter() - started) * 1000)

                for label in ("idle", "with readers"):
                    stop = threading.Event()
                    threads = (
                        [threading.Thread(target=reader, args=(stop,)) for _ in range(READERS)]
                        if label == "with readers"
                        else []
                    )
                    for thread in threads:
                        thread.start()
                    try:
                        for _ in range(PASSES):
                            timings, control_version = _replay_pass(
                                client, socket, debate_id, csrf, control_version, turn_ids
                            )
                            results[label].extend(timings)
                    finally:
                        stop.set()
                        for thread in threads:
                            thread.join(timeout=30)
                logged_out = client.post(
                    "/api/v1/auth/logout",
                    headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
                )
                assert logged_out.status_code == 204
                socket.send_json(
                    _command(
                        debate_id,
                        "playback.controller.acquire",
                        expected_control_version=control_version,
                    )
                )
                _receive_until(socket, "code", "session_revoked")
    finally:
        database.dispose()

    print()
    print(
        f"Next latency, {len(turn_ids)} speeches x {PASSES} replay passes, "
        f"{READERS} readers every {READ_INTERVAL_SECONDS}s"
    )
    for label, values in results.items():
        print(_summary(f"Next ({label})", values))
    if reads:
        print(_summary("detail reads", reads))
