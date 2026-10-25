"""Fresh PostgreSQL databases for the script tests (see backend/tests/postgres_db.py)."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tests import postgres_db  # noqa: E402


@pytest.fixture(autouse=True)
def _drop_test_databases() -> Iterator[None]:
    yield
    postgres_db.drop_created()


@pytest.fixture
def empty_postgres_url() -> str:
    """A new database with no tables, dropped after the test."""

    return postgres_db.new_database_url(schema=False)
