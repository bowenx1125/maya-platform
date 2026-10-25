"""A member result that became ready is never rewritten into a non-ready row with text.

40-student run (2026-10-18): team_turn_results violated ck_team_result_body
once. On PostgreSQL nothing serialized Team writers: a writer read a result
as running, another transaction committed it ready with its text (the
Boundary write, a parallel settle), and the first writer then saved
failed / pending / acceptance_unknown over it, keeping the text. Writers
now lock the result rows they change, so they act on the committed state.
PostgreSQL only: SQLite's writer lock already serializes these paths.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.core import adaptive_admission as aa
from app.core import write_guard as wg
from app.core.errors import PlatformError
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamTurnResult,
)
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from tests.conftest import login
from tests.postgres_db import named_url
from tests.test_mayaform_assessment_attempts import _custom_conversation_with_participants

_POSTGRES_URL = os.environ.get("MAYA_TEST_POSTGRES_URL")
READY_TEXT = "Saved by the Boundary write."


@pytest.fixture()
def postgres_team(app_factory: Any) -> Any:
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
    database.dispose()


def _running_turn(database: Any, client: TestClient) -> tuple[str, str, str]:
    session, _csrf = login(client, "bowen")
    now = datetime.now(UTC)
    with database.session() as db:
        conversation_id = _custom_conversation_with_participants(db, session["user"]["id"])
        member = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.is_leader.is_(False),
            )
        )
        assert member is not None
        turn_id, token, result_id = str(uuid4()), str(uuid4()), str(uuid4())
        db.add(
            ConversationTurn(
                id=turn_id,
                conversation_id=conversation_id,
                position=0,
                user_text="hello",
                assistant_text=None,
                sources_json="[]",
                mode="mock",
                state="pending",
                safe_error_code=None,
                routing_json='{"mode":"all","participant_ids":[]}',
                request_hash="a" * 64,
                claim_token=token,
                created_at=now,
            )
        )
        db.flush()
        db.add(
            TeamTurnResult(
                id=result_id,
                turn_id=turn_id,
                conversation_id=conversation_id,
                participant_id=member.id,
                ordinal=0,
                state="running",
                assistant_text=None,
                sources_json="[]",
                safe_error_code=None,
                created_at=now,
            )
        )
        db.get(Conversation, conversation_id).active_request_id = turn_id
        db.commit()
    return turn_id, token, result_id


def _race(
    database: Any,
    monkeypatch: pytest.MonkeyPatch,
    pause_at: str,
    writer: Callable[[], Any],
    result_id: str,
) -> tuple[list[BaseException], TeamTurnResult]:
    """Pause ``writer`` after it read the result, commit it ready meanwhile."""

    reached, release = threading.Event(), threading.Event()
    original = getattr(runtime, pause_at)

    def paused(*args: Any, **kwargs: Any) -> Any:
        if threading.current_thread().name == "writer" and not reached.is_set():
            reached.set()
            release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, pause_at, paused)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            writer()
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    worker = threading.Thread(target=run, name="writer")
    worker.start()
    assert reached.wait(10)

    def boundary_write() -> None:
        # What update_learning_boundary does to a running result.
        with database.session() as db:
            db.execute(
                text(
                    "UPDATE team_turn_results SET state='ready', assistant_text=:body "
                    "WHERE id=:id AND state='running'"
                ),
                {"body": READY_TEXT, "id": result_id},
            )
            db.commit()

    other = threading.Thread(target=boundary_write)
    other.start()
    other.join(0.5)  # unfenced, it commits now; fenced, it waits for the writer
    release.set()
    worker.join(20)
    other.join(20)
    assert not worker.is_alive() and not other.is_alive()
    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        assert result is not None
        db.expunge(result)
    return errors, result


def _consistent(result: TeamTurnResult) -> bool:
    if result.state == "ready":
        return bool(result.assistant_text and result.assistant_text.strip())
    return result.assistant_text is None


def test_failed_settle_racing_a_ready_write_keeps_a_valid_result(
    postgres_team: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, _settings, client = postgres_team
    turn_id, token, result_id = _running_turn(database, client)
    errors, result = _race(
        database,
        monkeypatch,
        "_assessment_result_for_result",
        lambda: runtime.settle_member(
            database.session_factory,
            turn_id,
            token,
            result_id,
            error=PlatformError("team_provider_rejected", "rejected", 503),
        ),
        result_id,
    )
    assert errors == []
    assert _consistent(result)


def test_interrupt_racing_a_ready_write_keeps_a_valid_result(
    postgres_team: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, settings, client = postgres_team
    turn_id, token, result_id = _running_turn(database, client)
    claim = runtime.TeamClaim(turn_id=turn_id, token=token, created=True, settings=settings)
    errors, result = _race(
        database,
        monkeypatch,
        "_append_event",
        lambda: runtime.interrupt_team_turn(database.session_factory, claim),
        result_id,
    )
    assert errors == []
    assert _consistent(result)
