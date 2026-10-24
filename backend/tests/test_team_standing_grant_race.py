"""Students' first messages to one published Team record one standing grant, without a race.

40-student load test (2026-10-19): one member reply failed with a SQLAlchemy
IntegrityError (gkpj). Every student's first message found no Provider grant
for the published Team and recorded the operator's standing consent as one;
the concurrent inserts collided on uq_team_provider_standing_scope. The grant
is now inserted ON CONFLICT DO NOTHING and read back, so concurrent first
messages share one grant and nothing raises or logs a unique violation.
PostgreSQL only: SQLite's writer lock already serializes these writes.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import pytest
from app.core import adaptive_admission as aa
from app.core import write_guard as wg
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.provider_disclosure import team_standing
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    TeamProviderStandingGrant,
    TeamTurnResult,
)
from app.modules.workspace.team_conversation import frozen_team_selection
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError

from tests.postgres_db import named_url
from tests.test_mayaform_team_conversations import BOWEN_ID
from tests.test_team_provider_disclosure import _prepared

_POSTGRES_URL = os.environ.get("MAYA_TEST_POSTGRES_URL")
STUDENTS = 6


@pytest.fixture()
def postgres_app(app_factory: Any) -> Any:
    if not _POSTGRES_URL:
        pytest.skip("MAYA_TEST_POSTGRES_URL is not set")
    from app.core.db import Database
    from app.main import create_app

    _app, sqlite_database, base = app_factory()
    sqlite_database.dispose()
    settings = base.model_copy(update={"database_url": named_url("pg", schema=False)})
    database = Database(named_url("pg", schema=False), settings.data_root)
    with database.engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    app = create_app(settings, database)
    aa.reset_adaptive_admission_state()
    wg.reset_write_guard_state()
    with TestClient(app) as client:
        client.headers["Origin"] = "http://testserver"
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
            db.commit()
        yield database, settings, client
    aa.reset_adaptive_admission_state()
    wg.reset_write_guard_state()
    database.dispose()


def test_concurrent_first_messages_share_one_standing_grant(
    postgres_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, settings, client = postgres_app
    result_id, manifest, _document, _set_id = _prepared(client, database, settings)
    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        assert result is not None
        conversation_id = result.conversation_id
        participant = db.get(ConversationParticipant, result.participant_id)
        assert participant is not None
        member_id = participant.team_member_id

    # Hold every thread right before its "is there a grant yet?" check, so
    # all of them find none, as 40 first messages arriving together did.
    barrier = threading.Barrier(STUDENTS)
    calls = threading.local()
    real_prepare = team_standing.prepare_team_standing_grant

    def prepare(*args: Any, **kwargs: Any) -> Any:
        plan = real_prepare(*args, **kwargs)
        calls.count = getattr(calls, "count", 0) + 1
        if calls.count == 2:  # the confirm step, just before its existence check
            barrier.wait(timeout=30)
        return plan

    monkeypatch.setattr(team_standing, "prepare_team_standing_grant", prepare)

    violations: list[str] = []

    def count_violation(context: Any) -> None:
        if isinstance(context.sqlalchemy_exception, IntegrityError):
            violations.append(str(context.original_exception).splitlines()[0])

    event.listen(database.engine, "handle_error", count_violation)
    grants: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def first_message() -> None:
        try:
            with database.session() as db:
                conversation = db.get(Conversation, conversation_id)
                assert conversation is not None
                grant = team_standing.operator_standing_grant(
                    db,
                    BOWEN_ID,
                    frozen_team_selection(db, conversation),
                    {member_id},
                    manifest.policy_hash,
                    manifest.provider_operation,
                )
                assert grant is not None
                grant_id = grant.id
                db.commit()
            with lock:
                grants.append(grant_id)
        except BaseException as exc:  # noqa: BLE001 - reported below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=first_message) for _ in range(STUDENTS)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
    finally:
        event.remove(database.engine, "handle_error", count_violation)

    assert errors == []
    assert violations == []
    assert len(grants) == STUDENTS and len(set(grants)) == 1
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(TeamProviderStandingGrant)) == 1
