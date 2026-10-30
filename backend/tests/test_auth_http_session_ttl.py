"""HTTP-layer session TTL with an injectable auth clock (default unchanged)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.auth.dependencies import get_auth_clock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.conftest import login

T0 = datetime(2026, 10, 21, 8, 0, 0, tzinfo=UTC)
BOWEN_ID = "60541c78-30f1-55c5-b2aa-207b6a766883"


def _install_clock(app: FastAPI, holder: dict[str, datetime | None]) -> None:
    def _clock() -> datetime | None:
        return holder["now"]

    app.dependency_overrides[get_auth_clock] = _clock


def test_http_session_ttl_require_auth_me_29_ok_31_unauth(app_factory: Any) -> None:
    """Login at T0; /me via require_auth stays valid at +29d and fails at +31d."""

    app, _database, _settings = app_factory()
    holder: dict[str, datetime | None] = {"now": T0}
    _install_clock(app, holder)

    with TestClient(app) as client:
        # Fixed clock only via dependency override — no client time fields.
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "maya", "password": "demo-password"},
        )
        assert response.status_code == 200, response.text
        # Clock is dependency-only; login body/response carry no client time field.
        assert "now" not in response.json()
        assert "expires_at" in response.json()

        holder["now"] = T0 + timedelta(days=29)
        assert client.get("/api/v1/auth/me").status_code == 200
        assert client.get("/api/v1/avatar-templates").status_code == 200

        holder["now"] = T0 + timedelta(days=31)
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.get("/api/v1/avatar-templates").status_code == 401

    app.dependency_overrides.pop(get_auth_clock, None)


def test_http_session_ttl_require_demo_auth_switch_29_ok_31_unauth(app_factory: Any) -> None:
    """Demo switch path uses require_demo_auth; same 29/31 window after T0 login."""

    app, _database, _settings = app_factory(demo_mode=True)
    holder: dict[str, datetime | None] = {"now": T0}
    _install_clock(app, holder)

    with TestClient(app) as client:
        _payload, csrf = login(client, "maya")

        holder["now"] = T0 + timedelta(days=29)
        switched = client.post(
            "/api/v1/auth/switch",
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
            json={"user_id": BOWEN_ID},
        )
        assert switched.status_code == 200, switched.text

        # Re-login at a fresh T0 so the +31d check uses a known expiry.
        holder["now"] = T0
        _payload, csrf = login(client, "maya")
        holder["now"] = T0 + timedelta(days=31)
        expired = client.post(
            "/api/v1/auth/switch",
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
            json={"user_id": BOWEN_ID},
        )
        assert expired.status_code == 401, expired.text

    app.dependency_overrides.pop(get_auth_clock, None)


def test_http_auth_default_clock_still_works(app_factory: Any) -> None:
    """Without overriding get_auth_clock, login and /me use service-layer utc_now()."""

    app, _database, _settings = app_factory()
    assert get_auth_clock not in app.dependency_overrides

    with TestClient(app) as client:
        payload, _csrf = login(client)
        assert payload["user"]["username"] == "maya"
        assert client.get("/api/v1/auth/me").status_code == 200
