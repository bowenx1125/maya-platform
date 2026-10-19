"""Publish under DB pool pressure: queue behind admission, retry a lapsed lease."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import IdempotencyRecord, User
from app.modules.agents import router as agents_router
from app.modules.knowledge.services import assert_claim_owned, renew_idempotency_lease


def _seed(tmp_path: Path, *, lease_delta: timedelta) -> Database:
    database = Database(f"sqlite:///{tmp_path}/publish-pressure.sqlite3")
    database.initialize_schema()
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            User(
                id="u1",
                username="pressure-student",
                display_name="P",
                status="active",
                created_at=now,
            )
        )
        db.flush()
        db.add(
            IdempotencyRecord(
                id="rec1",
                actor_user_id="u1",
                operation="publishAgentVersion",
                key="pressure-key-0000",
                request_hash="b" * 64,
                state="pending",
                claim_token="tok",
                lease_expires_at=now + lease_delta,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    return database


@pytest.mark.parametrize("check", ["renew", "assert"])
def test_a_lease_that_lapsed_while_waiting_for_a_connection_is_retryable(
    tmp_path: Path, check: str
) -> None:
    database = _seed(tmp_path, lease_delta=timedelta(seconds=-5))
    with database.session() as db:
        record = db.get(IdempotencyRecord, "rec1")
        assert record is not None
        with pytest.raises(PlatformError) as caught:
            if check == "renew":
                renew_idempotency_lease(db, record, lease_seconds=900)
            else:
                assert_claim_owned(db, record)
        assert caught.value.status_code == 503
        assert caught.value.code == "idempotency_lease_expired"
    database.dispose()


def test_a_lease_taken_over_by_another_request_stays_a_conflict(tmp_path: Path) -> None:
    database = _seed(tmp_path, lease_delta=timedelta(seconds=-5))
    with database.session() as db:
        record = db.get(IdempotencyRecord, "rec1")
        assert record is not None
        record.claim_token = "other"
        db.commit()
        record.claim_token = "tok"
        with pytest.raises(PlatformError) as caught:
            assert_claim_owned(db, record)
        assert caught.value.code == "invalid_state"
    database.dispose()


def test_publish_runs_inside_the_create_admission_slot(monkeypatch: Any) -> None:
    events: list[str] = []

    class _Slot:
        def __enter__(self) -> None:
            events.append("enter")

        def __exit__(self, *exc: object) -> None:
            events.append("exit")

    monkeypatch.setattr(agents_router, "create_admission_slot", lambda settings=None: _Slot())

    def fake(*args: Any, **kwargs: Any) -> str:
        events.append("publish")
        return "ok"

    monkeypatch.setattr(agents_router, "_publish_agent_version_admitted", fake)

    class _Db:
        def commit(self) -> None:
            events.append("release-connection")

    publish: Any = agents_router.publish_agent_version
    result = publish(
        uuid4(),
        object(),
        idempotency_key="k" * 16,
        _csrf_header="x" * 32,
        context=object(),
        db=_Db(),
        settings=object(),
    )
    assert result == "ok"
    # The request's pool connection is handed back before queueing.
    assert events == ["release-connection", "enter", "publish", "exit"]
