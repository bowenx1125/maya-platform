"""Team event polling must not mix turn state and events from different commits."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from app.modules.workspace.team_runtime import _begin_consistent_read
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy.schema import CreateSchema, DropSchema

from tests.postgres_db import named_url


@pytest.fixture
def postgres_poll_database() -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    url = os.environ.get("MAYA_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("MAYA_TEST_POSTGRES_URL is not set")
    if make_url(url).get_backend_name() != "postgresql":
        pytest.fail("MAYA_TEST_POSTGRES_URL must name a PostgreSQL test database")
    url = named_url("pg", schema=False)
    admin = create_engine(url, poolclass=NullPool)
    schema = f"maya_poll_snapshot_{uuid4().hex}"
    engine = None
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        engine = create_engine(
            url,
            connect_args={"options": f"-csearch_path={schema}"},
            poolclass=QueuePool,
            pool_size=2,
            max_overflow=0,
            pool_timeout=5,
        )
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT current_schema()")) == schema
            connection.execute(text("CREATE TABLE poll_turn (id integer PRIMARY KEY, state text)"))
            connection.execute(
                text("CREATE TABLE poll_event (sequence integer PRIMARY KEY, kind text)")
            )
            connection.execute(text("INSERT INTO poll_turn VALUES (1, 'pending')"))
        yield engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        if engine is not None:
            engine.dispose()
        try:
            if created:
                with admin.begin() as connection:
                    connection.execute(DropSchema(schema, cascade=True))
        finally:
            admin.dispose()


def test_turn_done_cannot_overtake_the_state_loaded_by_the_same_poll(
    postgres_poll_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_poll_database

    def finish_turn() -> int:
        with factory() as writer:
            writer_pid = writer.scalar(text("SELECT pg_backend_pid()"))
            writer.execute(text("UPDATE poll_turn SET state = 'ready' WHERE id = 1"))
            writer.execute(text("INSERT INTO poll_event VALUES (1, 'turn_done')"))
            writer.commit()
            return int(writer_pid)

    with factory() as reader:
        _begin_consistent_read(reader)
        reader_pid = reader.scalar(text("SELECT pg_backend_pid()"))
        state = reader.scalar(text("SELECT state FROM poll_turn WHERE id = 1"))
        assert state == "pending"
        # The worker commits on a different real connection after the poll's
        # turn SELECT, exactly before that poll asks for newly appended events.
        with ThreadPoolExecutor(max_workers=1) as pool:
            writer_pid = pool.submit(finish_turn).result(timeout=10)
        assert writer_pid != reader_pid
        events = reader.scalars(text("SELECT kind FROM poll_event ORDER BY sequence")).all()
        assert events == [], (state, events)
        assert reader.scalar(text("SELECT state FROM poll_turn WHERE id = 1")) == "pending"

    with factory() as next_poll:
        _begin_consistent_read(next_poll)
        assert next_poll.scalar(text("SELECT state FROM poll_turn WHERE id = 1")) == "ready"
        assert next_poll.scalars(text("SELECT kind FROM poll_event ORDER BY sequence")).all() == [
            "turn_done"
        ]


def test_poll_isolation_resets_before_the_connection_is_reused(
    postgres_poll_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    engine, factory = postgres_poll_database
    with factory() as reader:
        _begin_consistent_read(reader)
        reader_pid = reader.scalar(text("SELECT pg_backend_pid()"))
        assert reader.scalar(text("SHOW transaction_isolation")) == "repeatable read"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT pg_backend_pid()")) == reader_pid
        assert connection.scalar(text("SHOW transaction_isolation")) == "read committed"


def test_poll_snapshot_must_begin_before_any_existing_transaction(
    postgres_poll_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_poll_database
    with factory() as reader:
        reader.execute(text("SELECT 1"))
        with pytest.raises(RuntimeError, match="before database reads"):
            _begin_consistent_read(reader)
