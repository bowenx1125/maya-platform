"""Self-registration waits in the adaptive queue and one writer turn per process.

Audit item 3: registration bypassed the adaptive queue, and every concurrent
registrant checked out a pooled DB connection only to block on the global
registration advisory lock. Now it takes a ``login`` slot, hashes outside the
writer turn, and commits inside it, so waiters hold no connection.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from app.core import adaptive_admission as aa
from app.core.models import User
from app.modules.auth import registration
from fastapi.testclient import TestClient
from sqlalchemy import func, select


@pytest.fixture(autouse=True)
def _clean_gates() -> Any:
    aa.reset_adaptive_admission_state()
    registration.reset_registration_turn_state()
    yield
    aa.reset_adaptive_admission_state()
    registration.reset_registration_turn_state()


def _body(name: str) -> dict[str, str]:
    return {"username": name, "password": "correct-horse-1", "group_name": "Team Aurora"}


def test_registration_is_admitted_through_the_login_class(client: TestClient) -> None:
    before = aa.adaptive_admission_snapshot()["classes"]["login"]["admitted"]
    response = client.post("/api/v1/auth/register", json=_body("queued-student"))
    assert response.status_code == 201, response.text
    after = aa.adaptive_admission_snapshot()["classes"]["login"]["admitted"]
    assert after == before + 1


def test_concurrent_registrations_take_one_writer_turn_at_a_time(
    client: TestClient, app_bundle: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _app, database, _settings = app_bundle
    original = registration.register_student
    lock = threading.Lock()
    peak = {"now": 0, "max": 0}

    def tracked(*args: Any, **kwargs: Any) -> Any:
        # The router hashes before its turn and hands the hash over.
        assert kwargs.get("password_hash")
        with lock:
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
        try:
            assert registration.registration_turn_in_flight() == 1
            return original(*args, **kwargs)
        finally:
            with lock:
                peak["now"] -= 1

    monkeypatch.setattr("app.modules.auth.router.register_student", tracked)
    names = [f"crowd-student-{index}" for index in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(
            pool.map(
                lambda name: client.post("/api/v1/auth/register", json=_body(name)).status_code,
                names,
            )
        )
    assert statuses == [201] * 8
    assert peak["max"] == 1
    assert registration.registration_turn_in_flight() == 0
    with database.session() as db:
        assert (
            db.scalar(select(func.count()).select_from(User).where(User.username.in_(names))) == 8
        )


def test_registration_turn_wait_timeout_is_a_retryable_busy_503(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    settings.adaptive_admission_wait_seconds = 1
    held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with registration.registration_turn(settings):
            held.set()
            release.wait(10)

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert held.wait(5)
        response = client.post("/api/v1/auth/register", json=_body("late-student"))
    finally:
        release.set()
        thread.join()
    assert response.status_code == 503, response.text
    error = response.json()
    payload = error.get("error", error)
    assert payload["code"] == "adaptive_admission_busy"
    assert payload["details"]["reason"] == "registration_wait_timeout"
    assert payload["details"]["retryable"] is True
    # Nothing was stored: the student can simply send the form again.
    with database.session() as db:
        assert db.scalar(select(User.id).where(User.username == "late-student")) is None
