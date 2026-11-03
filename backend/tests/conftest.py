from __future__ import annotations

import csv
import io
import os
import subprocess
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import pytest
import yaml
from app.core.config import Settings, get_settings
from app.core.db import Database
from app.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from starlette.testclient import WebSocketTestSession

from tests import n_plus_one_report, postgres_db

n_plus_one_report.install()

# Capacity defaults scale with the host's CPUs (app/core/capacity.py). Tests
# assert the measured 2-vCPU numbers, so the machine running them must not
# change them.
os.environ.setdefault("CAPACITY_SCALE", "1")
# app.main read (and cached) the settings while being imported above.
get_settings.cache_clear()

WS_RECEIVE_TIMEOUT_SECONDS = 30.0


def _receive_with_timeout(self: WebSocketTestSession) -> Any:
    """A server that never answers fails the one test instead of hanging the suite."""

    async def receive() -> Any:
        with anyio.fail_after(WS_RECEIVE_TIMEOUT_SECONDS):
            return await self._send_rx.receive()

    return self.portal.call(receive)


WebSocketTestSession.receive = _receive_with_timeout  # type: ignore[method-assign]


def pytest_sessionstart(session: pytest.Session) -> None:
    if not os.environ.get(postgres_db.ENV):
        pytest.exit(
            f"{postgres_db.ENV} must name a PostgreSQL server: the suite runs on "
            "PostgreSQL only (one database per test).",
            returncode=4,
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if os.environ.get(postgres_db.ENV):
        postgres_db.drop_created()
        postgres_db.drop_template()


@pytest.fixture(autouse=True)
def _drop_test_databases() -> Iterator[None]:
    """Every database a test created with ``new_database_url`` goes with it."""

    yield
    postgres_db.drop_created()


@pytest.fixture
def postgres_url() -> str:
    """A fresh PostgreSQL database with the current schema."""

    return postgres_db.new_database_url()


@pytest.fixture
def app_factory(
    tmp_path: Path, postgres_url: str
) -> Callable[..., tuple[FastAPI, Database, Settings]]:
    # One fixture lifetime represents one unchanged private catalog across
    # multiple app/process instances.  Re-hashing the same password for every
    # factory call would create a new Argon2 salt and falsely look like a
    # material credential change, revoking otherwise valid sessions.
    password_hash = PasswordHash.recommended().hash("demo-password")
    credentials = {
        "users": [
            {
                "user_id": "08b9de2d-bb75-5c71-a64b-231b48f9eb25",
                "username": "maya",
                "password_hash": password_hash,
            },
            {
                "user_id": "60541c78-30f1-55c5-b2aa-207b6a766883",
                "username": "bowen",
                "password_hash": password_hash,
            },
            {
                "user_id": "bc170f51-45fb-5296-a36d-a2edc8f8d315",
                "username": "kaikai",
                "password_hash": password_hash,
            },
            {
                "user_id": "89857c76-2d84-5ecf-b680-990815b98680",
                "username": "jade",
                "password_hash": password_hash,
            },
        ]
    }
    credential_file = tmp_path / "demo_users.yaml"
    credential_file.write_text(yaml.safe_dump(credentials), encoding="utf-8")
    if os.name == "nt":
        identity = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            check=True,
        )
        # Localized console output: decode in the ANSI code page. text=True
        # dies under a UTF-8 mode interpreter before the value is ever used.
        sid = next(csv.reader(io.StringIO(identity.stdout.decode("mbcs", errors="replace"))))[1]
        subprocess.run(
            ["icacls", str(credential_file), "/inheritance:r", "/grant:r", f"*{sid}:F"],
            capture_output=True,
            check=True,
        )
    else:
        credential_file.chmod(0o600)

    def factory(
        *,
        demo_mode: bool = True,
    ) -> tuple[FastAPI, Database, Settings]:
        settings = Settings(
            maya_env="test",
            session_secret="x" * 32,
            demo_mode=demo_mode,
            demo_quick_login=False,
            # A developer .env with DEMO_AUTO_CONFIRM_PROVIDER=true would let
            # standing consent auto-confirm disclosures and skip the explicit
            # confirmation step tests must exercise.
            demo_auto_confirm_provider=False,
            allow_legacy_demo_users=True,
            database_url=postgres_url,
            data_root=tmp_path,
            # Keep the legacy fixture explicit and independent of any
            # developer .env file or repository-local private catalog.
            demo_accounts_file=tmp_path / "missing-accounts.private.md",
            demo_users_file=credential_file,
            llm_provider="mock",
            embedding_provider="mock",
            tts_provider="mock",
            voice_provider="mock",
            report_provider="mock",
            dashscope_api_key=None,
        )
        database = Database(settings.database_url, settings.data_root)
        return create_app(settings, database), database, settings

    return factory


@pytest.fixture
def app_bundle(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
) -> tuple[FastAPI, Database, Settings]:
    """One app/database pair shared by ``client`` and ``database``."""

    return app_factory()


@pytest.fixture
def client(app_bundle: tuple[FastAPI, Database, Settings]) -> Iterator[TestClient]:
    app, _database, _settings = app_bundle
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def database(app_bundle: tuple[FastAPI, Database, Settings]) -> Database:
    """The database behind ``client``, for tests that must seed extra rows."""

    return app_bundle[1]


def post_message(
    client: TestClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: Any = None,
    settle_seconds: float = 10.0,
) -> Any:
    """Send one Chat or Team message the way the app does, then read it back.

    ``url`` is ``/api/v1/conversations/{id}/messages``. The message goes
    through ``messages:stream`` (the only send route); a refusal before the
    stream starts comes back as is. Otherwise the saved conversation is read
    once the stream and any Team background work (a natural assessment resume)
    have finished.
    """

    import time as _time

    from app.modules.workspace.chat_stream import _TEAM_BACKGROUND_RUNS

    before = set(_TEAM_BACKGROUND_RUNS)
    response = client.post(
        f"{url}:stream",
        headers={**(headers or {}), "Accept": "text/event-stream"},
        json=json,
    )
    if response.status_code != 200:
        return response
    # The stream ends with the turn; a Team turn's background run (a natural
    # assessment resume) may still be finishing.
    deadline = _time.monotonic() + settle_seconds
    started = set(_TEAM_BACKGROUND_RUNS) - before
    while any(not task.done() for task in started) and _time.monotonic() < deadline:
        _time.sleep(0.02)
    return client.get(url[: url.rindex("/messages")])


def login(client: TestClient, username: str = "maya") -> tuple[dict[str, Any], str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "demo-password"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload, payload["csrf_token"]


# The product graph has exactly one Demo group, so a group the caller is not a
# member of cannot be reached through the seed. Access-control tests create one
# directly; it is never seeded, exported or shipped.
FOREIGN_GROUP_ID = "1f1b3c2e-0f4d-4a5b-9c6d-7e8f90a1b2c3"


def make_foreign_group(database: Any, course_id: str, name: str = "Foreign Group") -> str:
    """Insert a group in the same course that no seeded user belongs to."""

    from app.core.models import Group

    with database.session() as session:
        if session.get(Group, FOREIGN_GROUP_ID) is None:
            session.add(
                Group(
                    id=FOREIGN_GROUP_ID,
                    course_id=course_id,
                    name=name,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()
    return FOREIGN_GROUP_ID


@pytest.fixture(autouse=True)
def _calm_host_pressure(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep polling-pressure shortcuts off unless a test turns them on.

    ``polling_pressure`` reads host-wide ``/proc/loadavg`` and ``/proc/stat``.
    On a busy CI box it flips on mid-suite, so conversation and live views
    were served from the few-seconds pressure caches and tests that change
    membership, epochs or playback mode directly in the database saw stale
    answers. Tests that exercise pressure patch these names themselves.
    """

    from app.core import debate_gate
    from app.modules.workspace import chat as chat_module
    from app.modules.workspace import live as live_module
    from app.modules.workspace.poll_cache import reset_conversation_poll_cache

    calm = lambda _settings=None: False  # noqa: E731
    for module in (chat_module, live_module, debate_gate):
        monkeypatch.setattr(module, "polling_pressure", calm)
    reset_conversation_poll_cache()
    live_module.reset_live_caches()
    yield
    reset_conversation_poll_cache()
    live_module.reset_live_caches()
