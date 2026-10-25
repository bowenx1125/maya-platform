"""Debate delete, voice delete, Rebirth and Remake run their SQL off the event loop.

Production 2026-10-26: DELETE /debates/{id} ran ~1.6 s of synchronous SQL on
the event loop, and a GET /courses/{id}/debates from the same replica waited
1.6 s behind it with 35 ms of its own database time. The cleanup routes now
offload that work (``playback.offload``) and hand only the task-manager
cancellation back to the server loop.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine

from tests.conftest import login
from tests.test_classroom_lifecycle import _body, _saved_classroom
from tests.test_playback_off_event_loop import _LoopSqlRecorder
from tests.test_wave2_playback import _headers


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("DELETE", ""),
        ("DELETE", "/audio"),
        ("POST", "/rebirth"),
        ("POST", "/remake"),
    ],
)
def test_cleanup_routes_run_no_sql_on_the_event_loop(
    app_factory: Any, method: str, suffix: str
) -> None:
    app, database, settings = app_factory()
    recorder = _LoopSqlRecorder()
    try:
        with TestClient(app) as client:
            debate_id = _saved_classroom(database, settings)
            _, csrf = login(client)
            body = _body(client, debate_id)
            event.listen(Engine, "before_cursor_execute", recorder)
            try:
                response = client.request(
                    method,
                    f"/api/v1/debates/{debate_id}{suffix}",
                    json=body,
                    headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
                )
            finally:
                event.remove(Engine, "before_cursor_execute", recorder)
            assert response.status_code == 200, response.text
    finally:
        database.dispose()
    assert recorder.violations == [], "\n\n".join(recorder.violations[:3])
    assert recorder.offloaded > 0
