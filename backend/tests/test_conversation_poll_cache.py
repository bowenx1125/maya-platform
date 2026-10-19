"""GET /conversations/{id} is cheap while admission sheds load.

60-student rerun (2026-10-19): polling is not admission-gated, and ~55
waiting students polling every second kept load at 4.7-5.9 with nothing else
running, so the danger latch never cleared.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.modules.demo_baseline.service import BASELINE_VERSION_ID, ensure_demo_baseline
from app.modules.workspace import chat as chat_module
from app.modules.workspace import poll_cache
from app.modules.workspace.models import Conversation
from fastapi.testclient import TestClient

from tests.conftest import login


@pytest.fixture()
def conversation(app_bundle: Any, client: TestClient) -> tuple[Any, TestClient, str]:
    _app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    )
    assert created.status_code in {200, 201}, created.text
    poll_cache.reset_conversation_poll_cache()
    yield database, client, created.json()["id"]
    poll_cache.reset_conversation_poll_cache()
    poll_cache.set_clock(None)


def _count_views(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    original = chat_module.session_view

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(chat_module, "session_view", counted)
    return calls


def test_calm_polls_are_built_fresh_every_time(
    conversation: tuple[Any, TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _database, client, conversation_id = conversation
    calls = _count_views(monkeypatch)
    for _ in range(3):
        response = client.get(f"/api/v1/conversations/{conversation_id}")
        assert response.status_code == 200
        assert poll_cache.POLL_AFTER_HEADER not in response.headers
    assert len(calls) == 3
    assert len(poll_cache.CONVERSATION_POLL_CACHE) == 0


def test_polls_under_pressure_reuse_a_short_lived_copy(
    conversation: tuple[Any, TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    database, client, conversation_id = conversation
    now = [100.0]
    poll_cache.set_clock(lambda: now[0])
    monkeypatch.setattr(chat_module, "polling_pressure", lambda _settings=None: True)
    calls = _count_views(monkeypatch)
    url = f"/api/v1/conversations/{conversation_id}"

    first = client.get(url)
    assert first.status_code == 200
    assert first.headers[poll_cache.POLL_AFTER_HEADER] == "5"
    now[0] += 2.0
    second = client.get(url)
    assert second.json() == first.json()
    assert len(calls) == 1  # served from the copy

    # Older than the TTL: rebuilt.
    now[0] += 4.0
    client.get(url)
    assert len(calls) == 2

    # A revision bump (a send, a finished turn) misses at once.
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        row.revision = int(row.revision or 0) + 1
        db.commit()
    now[0] += 0.5
    assert client.get(url).json()["revision"] == first.json()["revision"] + 1
    assert len(calls) == 3


def test_pressure_cache_is_per_user_and_still_checks_sign_in(
    conversation: tuple[Any, TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _database, client, conversation_id = conversation
    monkeypatch.setattr(chat_module, "polling_pressure", lambda _settings=None: True)
    url = f"/api/v1/conversations/{conversation_id}"
    assert client.get(url).status_code == 200
    # Another account never receives the cached copy.
    login(client, "kaikai")
    assert client.get(url).status_code == 404
    # Signed out: auth runs before the cache.
    client.cookies.clear()
    assert client.get(url).status_code == 401


def test_pressure_cache_can_be_turned_off(
    conversation: tuple[Any, TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _database, client, conversation_id = conversation
    app = client.app
    app.state.settings = app.state.settings.model_copy(  # type: ignore[attr-defined]
        update={"conversation_poll_pressure_cache_seconds": 0.0}
    )
    monkeypatch.setattr(chat_module, "polling_pressure", lambda _settings=None: True)
    calls = _count_views(monkeypatch)
    url = f"/api/v1/conversations/{conversation_id}"
    for _ in range(2):
        assert poll_cache.POLL_AFTER_HEADER not in client.get(url).headers
    assert len(calls) == 2


def test_cache_drops_the_oldest_entries() -> None:
    cache = poll_cache.ConversationPollCache(max_entries=2)
    cache.put("u", "a", 0, "A")
    cache.put("u", "b", 0, "B")
    cache.put("u", "c", 0, "C")
    assert len(cache) == 2
    assert cache.get("u", "a", 0, 60.0) is None
    assert cache.get("u", "c", 0, 60.0) == "C"
    assert cache.get("u", "c", 1, 60.0) is None  # another revision
