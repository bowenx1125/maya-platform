"""Login admission waits in line instead of reporting a capability outage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.modules.auth.admission import AuthLoginAdmission
from fastapi.testclient import TestClient

from tests.test_production_profile import (
    PUBLIC_ORIGIN,
    PUBLIC_TEACHER_PASSWORD,
    _new_app,
    _origin_headers,
    _post_login,
)


def test_full_login_line_returns_a_queue_ticket(tmp_path: Path) -> None:
    app, database, _settings = _new_app(
        tmp_path, settings_overrides={"auth_login_admission_limit": 1}
    )
    blocker = str(uuid4())
    with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
        with database.session() as session:
            session.add(
                AuthLoginAdmission(
                    id=blocker,
                    state="admitted",
                    created_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            )
        waiting = _post_login(client, "maya", PUBLIC_TEACHER_PASSWORD)
        assert waiting.status_code == 429
        body = waiting.json()
        assert body["code"] == "auth_login_queued"
        assert body["code"] != "provider_unavailable"
        assert "temporarily unavailable" not in body["message"].lower()
        ticket = body["details"]["ticket"]
        assert isinstance(ticket, str) and ticket != blocker
        assert body["details"]["position"] >= 0
        assert waiting.headers["retry-after"] == str(body["details"]["retry_after_seconds"])

        with database.session() as session:
            row = session.get(AuthLoginAdmission, blocker)
            assert row is not None
            session.delete(row)

        admitted = client.post(
            "/api/v1/auth/login",
            json={"username": "maya", "password": PUBLIC_TEACHER_PASSWORD},
            headers={**_origin_headers(), "X-Auth-Admission-Ticket": ticket},
        )
        assert admitted.status_code == 200
        assert admitted.json()["user"]["username"] == "maya"
    database.dispose()
