"""Login admission waits in line instead of reporting a capability outage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.errors import PlatformError
from app.modules.auth.admission import (
    AuthLoginAdmission,
    acquire_login_admission,
    release_login_admission,
)
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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


def _queue_error(db: Session, settings: Settings, ticket: object) -> dict[str, Any]:
    with pytest.raises(PlatformError) as caught:
        acquire_login_admission(db, settings, ticket if isinstance(ticket, str) else None)
    assert caught.value.code == "auth_login_queued"
    details = caught.value.details
    assert isinstance(details, dict)
    return details


def test_queue_tickets_keep_order_position_and_progress(tmp_path: Path) -> None:
    app, database, settings = _new_app(
        tmp_path, settings_overrides={"auth_login_admission_limit": 1}
    )
    with TestClient(app, base_url=PUBLIC_ORIGIN):
        with database.session() as db:
            slot = acquire_login_admission(db, settings, None)
            assert slot is not None
            first = _queue_error(db, settings, None)
            second = _queue_error(db, settings, None)
            assert first["position"] == 0 and second["position"] == 1
            assert second["queue_length"] == 2
            assert second["estimated_wait_seconds"] >= first["estimated_wait_seconds"]
            assert first["ticket_expires_in_seconds"] == settings.auth_login_queue_ticket_seconds

            # Retrying with the ticket keeps the place instead of rejoining.
            again = _queue_error(db, settings, second["ticket"])
            assert again["ticket"] == second["ticket"] and again["position"] == 1

            release_login_admission(db, slot)
            # A newcomer cannot skip the waiting line once a slot frees up.
            newcomer = _queue_error(db, settings, None)
            assert newcomer["position"] == 2
            # Second in line still waits; the head of the line is admitted.
            assert _queue_error(db, settings, second["ticket"])["position"] == 1
            admitted = acquire_login_admission(db, settings, str(first["ticket"]))
            assert admitted == first["ticket"]
            release_login_admission(db, admitted)
            assert acquire_login_admission(db, settings, str(second["ticket"])) == second["ticket"]
    database.dispose()


def test_expired_queue_ticket_rejoins_at_the_back(tmp_path: Path) -> None:
    app, database, settings = _new_app(
        tmp_path, settings_overrides={"auth_login_admission_limit": 1}
    )
    with TestClient(app, base_url=PUBLIC_ORIGIN):
        with database.session() as db:
            assert acquire_login_admission(db, settings, None) is not None
            stale = _queue_error(db, settings, None)
            fresh = _queue_error(db, settings, None)
            row = db.get(AuthLoginAdmission, stale["ticket"])
            assert row is not None
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
            assert _queue_error(db, settings, fresh["ticket"])["position"] == 0
            rejoined = _queue_error(db, settings, stale["ticket"])
            assert rejoined["ticket"] != stale["ticket"]
            assert rejoined["position"] == 1
            # Waiting tickets use the longer queue lease, not the admission lease.
            waiting = db.get(AuthLoginAdmission, rejoined["ticket"])
            assert waiting is not None
            lease = (waiting.expires_at.replace(tzinfo=UTC) - datetime.now(UTC)).total_seconds()
            assert lease > settings.auth_login_admission_lease_seconds
    database.dispose()
