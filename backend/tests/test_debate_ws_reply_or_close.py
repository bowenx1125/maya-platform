"""A Debate WebSocket never leaves a client waiting (2026-10-25).

Every command gets an answer even when its handler fails unexpectedly, and
the socket is closed with a code (and the reason logged) when the event
stream itself fails, instead of the handler ending silently.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.conftest import login
from tests.test_classroom_lifecycle import _saved_classroom
from tests.test_wave2_playback import _receive_until


def _acquire(debate_id: str, control_version: int) -> dict[str, Any]:
    return {
        "command_id": str(uuid4()),
        "command_type": "playback.controller.acquire",
        "command_version": 1,
        "debate_id": debate_id,
        "expected_control_version": control_version,
    }


def test_an_unexpected_command_failure_is_answered_and_logged(
    app_factory: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            _, csrf = login(client)

            async def broken(*_args: Any, **_kwargs: Any) -> Any:
                raise ValueError("unexpected")

            with client.websocket_connect(
                f"/api/v1/debates/{debate_id}/events", headers={"origin": "http://testserver"}
            ) as socket:
                snapshot = _receive_until(socket, "event_type", "snapshot")
                playback = app.state.playback_service
                monkeypatch.setattr(playback, "controller_acquire", broken)
                command = _acquire(debate_id, snapshot["payload"]["playback"]["control_version"])
                with caplog.at_level(logging.ERROR):
                    socket.send_json(command)
                    rejected = _receive_until(socket, "message_type", "command.rejected")
                assert rejected["command_id"] == command["command_id"]
                assert rejected["code"] == "internal_error"
                assert rejected["recoverable"] is True
                assert "debate_ws command failed" in caplog.text
                assert "playback.controller.acquire" in caplog.text
                # The socket stays usable for the next command.
                monkeypatch.undo()
                socket.send_json(
                    _acquire(debate_id, snapshot["payload"]["playback"]["control_version"])
                )
                _receive_until(socket, "message_type", "controller.acquired")
                client.post(
                    "/api/v1/auth/logout",
                    headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
                )
                socket.send_json(_acquire(debate_id, 0))
                _receive_until(socket, "code", "session_revoked")
    finally:
        database.dispose()


def test_an_event_stream_failure_closes_the_socket_with_a_code(
    app_factory: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    app, database, settings = app_factory()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            login(client)
            hub = app.state.playback_service.event_hub
            real_stream = hub.stream

            async def gap_after_snapshot(debate: str, factory: Any) -> Any:
                async for message in real_stream(debate, factory):
                    yield message
                    raise RuntimeError("debate event sequence gap")

            monkeypatch.setattr(hub, "stream", gap_after_snapshot)
            with caplog.at_level(logging.WARNING):
                with client.websocket_connect(
                    f"/api/v1/debates/{debate_id}/events",
                    headers={"origin": "http://testserver"},
                ) as socket:
                    _receive_until(socket, "event_type", "snapshot")
                    with pytest.raises(WebSocketDisconnect) as closed:
                        socket.receive_json()
            assert closed.value.code == 1011
            assert "debate_ws closed" in caplog.text
            assert "reason=RuntimeError" in caplog.text
    finally:
        database.dispose()
