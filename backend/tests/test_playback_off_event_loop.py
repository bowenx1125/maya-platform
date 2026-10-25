"""Guard: playback routes and controller commands run no SQL on the event loop.

PR C moved the synchronous SQLAlchemy work of every playback route and
WebSocket command onto worker threads (``playback.offload``). A statement
executed on a thread that is running an event loop, other than an offload
worker's own loop, stalls every other request and socket of the process. This
test drives a whole replay through the real HTTP and WebSocket surface and
fails on any such statement.
"""

from __future__ import annotations

import asyncio
import threading
import traceback
from typing import Any
from uuid import uuid4

from app.modules.debates.playback.offload import offloaded_now
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.engine import Engine

from tests.conftest import login
from tests.test_classroom_lifecycle import _saved_classroom
from tests.test_wave2_playback import _headers, _receive_until


class _LoopSqlRecorder:
    def __init__(self) -> None:
        self.violations: list[str] = []
        self.offloaded = 0
        self._lock = threading.Lock()

    def __call__(self, conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if offloaded_now():
            with self._lock:
                self.offloaded += 1
            return
        stack = "".join(
            line
            for line in traceback.format_stack(limit=40)
            if "/app/" in line and "sqlalchemy" not in line
        )
        with self._lock:
            self.violations.append(f"{statement.split()[0]} on {loop!r}\n{stack}")


def _command(debate_id: str, command_type: str, **fields: Any) -> dict[str, Any]:
    return {
        "command_id": str(uuid4()),
        "command_type": command_type,
        "command_version": 1,
        "debate_id": debate_id,
        **fields,
    }


def test_replay_routes_and_commands_run_no_sql_on_the_event_loop(app_factory: Any) -> None:
    from app.modules.debates.models import DebateTurn

    app, database, settings = app_factory()
    recorder = _LoopSqlRecorder()
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
            event.listen(Engine, "before_cursor_execute", recorder)
            try:
                with client.websocket_connect(
                    f"/api/v1/debates/{debate_id}/events",
                    headers={"origin": "http://testserver"},
                ) as socket:
                    snapshot = _receive_until(socket, "event_type", "snapshot")
                    control_version = snapshot["payload"]["playback"]["control_version"]
                    socket.send_json(
                        _command(
                            debate_id,
                            "playback.controller.acquire",
                            expected_control_version=control_version,
                        )
                    )
                    acquired = _receive_until(socket, "message_type", "controller.acquired")
                    epoch = acquired["controller_epoch"]
                    replay = client.post(
                        f"/api/v1/debates/{debate_id}/replay",
                        headers=_headers(csrf),
                        json={"expected_control_version": acquired["control_version"]},
                    )
                    assert replay.status_code == 200, replay.text
                    control_version = replay.json()["control_version"]
                    for index, turn_id in enumerate(turn_ids[:2]):
                        socket.send_json(
                            _command(
                                debate_id,
                                "playback.media.prepare",
                                expected_control_version=control_version,
                                controller_epoch=epoch,
                                turn_id=turn_id,
                                playback_action="replay",
                            )
                        )
                        prepared = _receive_until(socket, "message_type", "media.prepared")
                        audio = client.get(prepared["media_url"])
                        assert audio.status_code == 200
                        ahead = client.post(
                            f"/api/v1/debates/{debate_id}/next-audio",
                            headers=_headers(csrf),
                            json={"controller_epoch": epoch, "turn_id": turn_ids[index + 1]},
                        )
                        assert ahead.status_code == 200, ahead.text
                        assert client.get(ahead.json()["media_url"]).status_code == 200
                        socket.send_json(
                            _command(
                                debate_id,
                                "playback.started_ack",
                                expected_control_version=control_version,
                                controller_epoch=epoch,
                                turn_id=turn_id,
                                playback_action="replay",
                            )
                        )
                        _receive_until(socket, "event_type", "replay.started")
                        socket.send_json(
                            _command(
                                debate_id,
                                "playback.ended_ack",
                                expected_control_version=control_version,
                                controller_epoch=epoch,
                                turn_id=turn_id,
                            )
                        )
                        waiting = _receive_until(socket, "event_type", "playback.waiting_next")
                        advanced = client.post(
                            f"/api/v1/debates/{debate_id}/next",
                            headers=_headers(csrf),
                            json={
                                "expected_control_version": waiting["payload"]["control_version"],
                                "expected_current_turn_id": turn_id,
                            },
                        )
                        assert advanced.status_code == 200, advanced.text
                        control_version = advanced.json()["control_version"]
                    # End the way a revoked tab does: the server closes the
                    # socket itself, so the handler has finished before the
                    # test client tears the connection down.
                    logged_out = client.post(
                        "/api/v1/auth/logout",
                        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
                    )
                    assert logged_out.status_code == 204, logged_out.text
                    socket.send_json(
                        _command(
                            debate_id,
                            "playback.controller.acquire",
                            expected_control_version=control_version,
                        )
                    )
                    _receive_until(socket, "code", "session_revoked")
            finally:
                event.remove(Engine, "before_cursor_execute", recorder)
    finally:
        database.dispose()

    assert recorder.offloaded > 0
    assert recorder.violations == [], "\n\n".join(recorder.violations[:5])
