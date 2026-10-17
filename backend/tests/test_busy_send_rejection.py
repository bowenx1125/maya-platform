"""A busy server or a busy conversation refuses a send with nothing stored.

Queue full and a spent 180 s wait answer ``adaptive_admission_busy`` (503);
a conversation whose previous message is still being answered answers
``chat_busy`` (409). The student's text is never saved by a refused send, so
it can only come back when the student presses Send again, and the same
request id never makes two rows.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from app.core import adaptive_admission as aa
from app.core import write_guard as wg
from app.modules.demo_baseline.service import BASELINE_VERSION_ID, ensure_demo_baseline
from app.modules.workspace.models import Conversation, ConversationTurn
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_mayaform_team_turns import _body, _chat, _headers


@pytest.fixture()
def healthy_host() -> Iterator[None]:
    aa.reset_adaptive_admission_state()
    wg.reset_write_guard_state()
    aa.set_signal_readers(load=lambda: 0.5, mem=lambda: 4000.0)
    yield
    aa.set_signal_readers()
    aa.reset_adaptive_admission_state()
    wg.reset_write_guard_state()


@pytest.fixture()
def agent_chat(app_bundle: Any, client: TestClient, healthy_host: None) -> dict[str, Any]:
    app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    _, csrf = login(client, "bowen")
    session = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    return {"app": app, "database": database, "csrf": csrf, "session": session}


class _HeldServer:
    """Occupy the only admission slot so a send must queue."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.release = threading.Event()
        self.started = threading.Event()
        self.thread = threading.Thread(target=self._hold)

    def _hold(self) -> None:
        with aa.adaptive_slot("login", self.app.state.settings):
            self.started.set()
            self.release.wait(10)

    def __enter__(self) -> _HeldServer:
        settings = self.app.state.settings
        settings.adaptive_admission_max_in_flight = 1
        self.thread.start()
        assert self.started.wait(5)
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release.set()
        self.thread.join(5)


def _turn_count(database: Any) -> int:
    with database.session() as db:
        return int(db.scalar(select(func.count()).select_from(ConversationTurn)) or 0)


def _send(client: TestClient, chat: dict[str, Any], *, stream: bool, request_id: str) -> Any:
    session = chat["session"]
    suffix = ":stream" if stream else ""
    headers = {"X-CSRF-Token": chat["csrf"]}
    if stream:
        headers["Accept"] = "text/event-stream"
    return client.post(
        f"/api/v1/conversations/{session['id']}/messages{suffix}",
        headers=headers,
        json={
            "request_id": request_id,
            "expected_revision": session["revision"],
            "message": "A message typed during a busy minute",
        },
    )


@pytest.mark.parametrize("stream", [False, True])
def test_full_queue_answers_503_queue_full_and_stores_nothing(
    client: TestClient, agent_chat: dict[str, Any], stream: bool
) -> None:
    app, database = agent_chat["app"], agent_chat["database"]
    app.state.settings.adaptive_admission_queue_max = 0
    with _HeldServer(app):
        response = _send(client, agent_chat, stream=stream, request_id=str(uuid4()))
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "adaptive_admission_busy"
    assert body["details"]["reason"] == "queue_full"
    assert body["details"]["retryable"] is True
    assert _turn_count(database) == 0
    with database.session() as db:
        row = db.get(Conversation, agent_chat["session"]["id"])
        assert row is not None
        assert row.active_request_id is None
        assert row.revision == agent_chat["session"]["revision"]


@pytest.mark.parametrize("stream", [False, True])
def test_spent_wait_answers_503_wait_timeout_and_stores_nothing(
    client: TestClient, agent_chat: dict[str, Any], stream: bool
) -> None:
    app, database = agent_chat["app"], agent_chat["database"]
    app.state.settings.adaptive_admission_wait_seconds = 1
    with _HeldServer(app):
        response = _send(client, agent_chat, stream=stream, request_id=str(uuid4()))
    assert response.status_code == 503
    assert response.json()["code"] == "adaptive_admission_busy"
    assert response.json()["details"]["reason"] == "wait_timeout"
    assert _turn_count(database) == 0
    # Nothing replays the refused message once the server frees up.
    assert aa.adaptive_admission_snapshot(app.state.settings)["queue_depth"] == 0
    assert _turn_count(database) == 0


@pytest.mark.parametrize("stream", [False, True])
def test_previous_message_still_running_answers_409_chat_busy_at_once(
    client: TestClient, agent_chat: dict[str, Any], stream: bool
) -> None:
    app, database = agent_chat["app"], agent_chat["database"]
    with database.session() as db:
        row = db.get(Conversation, agent_chat["session"]["id"])
        assert row is not None
        row.active_request_id = str(uuid4())
        db.commit()
    # Busy server too: chat_busy must answer before queueing, not after it.
    app.state.settings.adaptive_admission_wait_seconds = 30
    with _HeldServer(app):
        response = _send(client, agent_chat, stream=stream, request_id=str(uuid4()))
    assert response.status_code == 409
    assert response.json()["code"] == "chat_busy"
    assert _turn_count(database) == 0


def test_one_request_id_is_stored_once(client: TestClient, agent_chat: dict[str, Any]) -> None:
    database = agent_chat["database"]
    request_id = str(uuid4())
    first = _send(client, agent_chat, stream=False, request_id=request_id)
    assert first.status_code == 200, first.text
    again = _send(client, agent_chat, stream=False, request_id=request_id)
    assert again.status_code == 200
    with database.session() as db:
        assert db.scalar(select(func.count()).where(ConversationTurn.id == request_id)) == 1
    assert _turn_count(database) == 1
    assert aa.adaptive_admission_snapshot(agent_chat["app"].state.settings)["in_flight"] == 0


@pytest.mark.parametrize("path", ["messages", "messages:stream"])
def test_team_send_on_a_full_queue_stores_nothing(
    client: TestClient, database: Any, app_bundle: Any, healthy_host: None, path: str
) -> None:
    app = app_bundle[0]
    session, csrf, _actor = _chat(client, database)
    before = _turn_count(database)
    app.state.settings.adaptive_admission_queue_max = 0
    headers = _headers(csrf)
    if path.endswith("stream"):
        headers["Accept"] = "text/event-stream"
    with _HeldServer(app):
        response = client.post(
            f"/api/v1/conversations/{session['id']}/{path}",
            headers=headers,
            json=_body(session, "all"),
        )
    assert response.status_code == 503
    assert response.json()["code"] == "adaptive_admission_busy"
    assert _turn_count(database) == before
    assert aa.adaptive_admission_snapshot(app.state.settings)["in_flight"] == 0
