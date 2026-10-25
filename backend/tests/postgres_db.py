"""One fresh PostgreSQL database per test.

``MAYA_TEST_POSTGRES_URL`` names a server (and a scratch database some older
tests reset in place). Each worker builds one template database with the
current schema at the start of a run; ``new_database_url()`` clones it (or
starts empty) and the database is dropped when the test ends.
"""

from __future__ import annotations

import os
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url

ENV = "MAYA_TEST_POSTGRES_URL"
_created: list[str] = []
_named: dict[tuple[str, bool], str] = {}
_template_ready = False


def base_url() -> URL:
    value = os.environ.get(ENV)
    if not value:
        raise RuntimeError(f"{ENV} must name a PostgreSQL server for the test suite.")
    return make_url(value)


_RUN = (os.environ.get("PYTEST_XDIST_TESTRUNUID") or uuid.uuid4().hex)[:8]


def _worker() -> str:
    # Unique per run as well as per worker: two concurrent runs must not
    # share (or drop) each other's template.
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main").replace("-", "_")
    return f"{_RUN}_{worker}"


def _template_name() -> str:
    return f"maya_tpl_{_worker()}"


def _admin() -> Engine:
    return create_engine(
        base_url().set(database="postgres"), isolation_level="AUTOCOMMIT", future=True
    )


def _url(name: str) -> str:
    return base_url().set(database=name).render_as_string(hide_password=False)


def _build_template() -> None:
    global _template_ready
    if _template_ready:
        return
    from app.core.db import Database

    name = _template_name()
    admin = _admin()
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{name}" TEMPLATE template0'))
    finally:
        admin.dispose()
    database = Database(_url(name))
    try:
        database.initialize_schema()
    finally:
        database.dispose()
    _template_ready = True


def new_database_url(*, schema: bool = True) -> str:
    """A new database, dropped at the end of the current test."""

    if schema:
        _build_template()
    name = f"maya_t_{_worker()}_{uuid.uuid4().hex[:12]}"
    template = _template_name() if schema else "template0"
    admin = _admin()
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{template}"'))
    finally:
        admin.dispose()
    _created.append(name)
    return _url(name)


def named_url(key: str, *, schema: bool = True) -> str:
    """The same new database for every use of ``key`` within one test.

    Replaces a test's ``sqlite:///<path>`` file: opening the same path twice
    reached the same data, so the same key returns the same database.
    """

    found = _named.get((key, schema))
    if found is None:
        found = _named[(key, schema)] = new_database_url(schema=schema)
    return found


def drop_created() -> None:
    _named.clear()
    if not _created:
        return
    admin = _admin()
    try:
        with admin.connect() as connection:
            while _created:
                name = _created.pop()
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


def drop_template() -> None:
    admin = _admin()
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{_template_name()}" WITH (FORCE)'))
    finally:
        admin.dispose()


def public_table_count(url: str) -> int:
    engine = create_engine(url, future=True)
    try:
        with engine.connect() as connection:
            return int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                ).scalar_one()
            )
    finally:
        engine.dispose()
