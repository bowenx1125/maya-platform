"""Archived classrooms retain history without claiming active playback authority."""

from datetime import UTC, datetime
from importlib import import_module
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.models import Course
from app.modules.debates.models import Debate
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import login
from tests.test_text_playback_fallback import UnavailableTTS
from tests.test_wave2_playback import COURSE_ID, GROUP_DEMO_ID, _headers, _insert_published_agent


@pytest.mark.parametrize(
    ("archived", "username", "expected_status"),
    [(True, "maya", 200), (False, "maya", 409), (True, "bowen", 403)],
)
def test_archived_running_classroom_does_not_block_visible_start(
    app_factory, archived, username, expected_status
):
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        agents = [
            _insert_published_agent(
                database,
                group_id=GROUP_DEMO_ID,
                name=f"Archive test {i}",
                evidence="A classroom compares evidence and explains different views.",
            )
            for i in range(2)
        ]
        _, csrf = login(client)
        ids = []
        for topic in ("Prior classroom", "New visible classroom"):
            response = client.post(
                f"/api/v1/courses/{COURSE_ID}/debates",
                headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
                json={
                    "topic": topic,
                    "round_count": 4,
                    "participants": [{"agent_id": item, "stance_mode": "open"} for item in agents],
                },
            )
            assert response.status_code == 201, response.text
            ids.append(response.json()["id"])
        prior_id, new_id = ids
        app.state.playback_service.audio_store.tts_provider = UnavailableTTS()
        scheduler = app.state.prewarm_scheduler
        for turn_id, ready in scheduler._plan(new_id):
            if not ready:
                client.portal.call(scheduler._prepare, new_id, turn_id)
        archived_at = datetime.now(UTC) if archived else None
        with database.session() as db:
            prior = db.get(Debate, prior_id)
            prior.status = "running"
            prior.deleted_at = archived_at
            db.get(Course, COURSE_ID).current_audio_debate_id = prior_id
        if username != "maya":
            _, csrf = login(client, username)
        response = client.post(
            f"/api/v1/debates/{new_id}/start",
            headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
            json={
                "expected_revision": 0,
                "expected_current_audio_debate_id": prior_id,
                "confirm_previous_audio_cleanup": False,
            },
        )
        assert response.status_code == expected_status, response.text
        if expected_status == 409:
            assert response.json()["code"] == "debate_already_running"
            assert response.json()["details"]["blocking_debate"]["id"] == prior_id
        with database.session() as db:
            repository = app.state.playback_service.repository
            assert repository.course_running(db, COURSE_ID, except_debate_id=new_id) is not archived
            blocker = repository.running_debate(db, COURSE_ID, except_debate_id=new_id)
            assert (blocker is None) is archived
            assert (prior_id in repository.running_debate_ids(db)) is not archived
            assert (repository.get_debate(db, prior_id) is None) is archived
            prior = db.get(Debate, prior_id)
            assert prior.status == "running"
            assert (prior.deleted_at is not None) is archived
            assert db.get(Debate, new_id).status == (
                "running" if expected_status == 200 else "draft"
            )


def test_active_slot_migration_keeps_history_and_single_visible_running(monkeypatch):
    migration = import_module("migrations.versions.0062_active_debate_slot")
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE debates (id TEXT PRIMARY KEY, course_id TEXT, "
                    "status TEXT, deleted_at TEXT)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO debates VALUES ('prior','course','running','archived'), "
                    "('new','course','draft',NULL), ('other','course','draft',NULL)"
                )
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX uq_debates_one_running_per_course "
                    "ON debates(course_id) WHERE status='running'"
                )
            )
            before = connection.execute(text("SELECT * FROM debates ORDER BY id")).all()
            with pytest.raises(IntegrityError):
                connection.execute(text("UPDATE debates SET status='running' WHERE id='new'"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert connection.execute(text("SELECT * FROM debates ORDER BY id")).all() == before
            connection.execute(text("UPDATE debates SET status='running' WHERE id='new'"))
            with pytest.raises(IntegrityError):
                connection.execute(text("UPDATE debates SET status='running' WHERE id='other'"))
            with pytest.raises(RuntimeError, match="archived running"):
                migration.downgrade()
            assert (
                "deleted_at IS NULL"
                in connection.execute(
                    text(
                        "SELECT sql FROM sqlite_master "
                        "WHERE name='uq_debates_one_running_per_course'"
                    )
                ).scalar_one()
            )
            assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
            connection.execute(text("UPDATE debates SET status='draft' WHERE id='new'"))
            migration.downgrade()
            with pytest.raises(IntegrityError):
                connection.execute(text("UPDATE debates SET status='running' WHERE id='new'"))
    finally:
        engine.dispose()


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_active_slot_migration_failure_preserves_index_without_prior_dml(monkeypatch, direction):
    migration = import_module("migrations.versions.0062_active_debate_slot")
    engine = create_engine("sqlite://")
    predicate = "status='running'"
    if direction == "downgrade":
        predicate += " AND deleted_at IS NULL"
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE debates (id TEXT PRIMARY KEY, course_id TEXT, "
                "status TEXT, deleted_at TEXT)"
            )
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX uq_debates_one_running_per_course "
                f"ON debates(course_id) WHERE {predicate}"
            )
            original_index = connection.execute(
                text("SELECT sql FROM sqlite_master WHERE name='uq_debates_one_running_per_course'")
            ).scalar_one()
        with pytest.raises(RuntimeError, match="injected index creation failure"):
            with engine.begin() as connection:
                assert not connection.connection.driver_connection.in_transaction
                operations = Operations(
                    MigrationContext.configure(
                        connection,
                        opts={"transactional_ddl": True, "transaction_per_migration": True},
                    )
                )

                def fail_create(*args, **kwargs):
                    raise RuntimeError("injected index creation failure")

                monkeypatch.setattr(operations, "create_index", fail_create)
                monkeypatch.setattr(migration, "op", operations)
                getattr(migration, direction)()
        with engine.connect() as connection:
            preserved_index = connection.execute(
                text("SELECT sql FROM sqlite_master WHERE name='uq_debates_one_running_per_course'")
            ).scalar_one_or_none()
            assert preserved_index == original_index
            assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
    finally:
        engine.dispose()
