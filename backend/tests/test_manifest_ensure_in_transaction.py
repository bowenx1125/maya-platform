"""Ensuring an existing export manifest inside one_transaction() stays usable.

Production (2026-10-19, Team "起点问卷"): the Summarizer has a knowledge set.
Its query manifest was written first, then the standing authorization ensured
the same manifest inside ``one_transaction()``. The duplicate INSERT aborted
that PostgreSQL transaction, the duplicate check's SELECT failed with
``InFailedSqlTransaction`` (InternalError) and the member showed "This Team
member could not reply." SQLite does not abort a transaction on a failed
statement, so only PostgreSQL showed it.

Set ``MAYA_TEST_POSTGRES_URL`` (a scratch database; its ``public`` schema is
dropped) to also run the PostgreSQL case.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from app.core.db import Database
from app.providers.control import confirm_export_manifest
from app.providers.control_repository import ProviderRepository
from sqlalchemy import event, text

from tests.test_wave4_provider_control_orm import _manifest, _policy

_POSTGRES_URL = os.environ.get("MAYA_TEST_POSTGRES_URL")


def _seed(database: Database):  # type: ignore[no-untyped-def]
    repository = ProviderRepository(database)
    policy = _policy()
    policy_id = repository.save_policy_snapshot(policy, snapshot_id="policy-1")
    manifest = _manifest(policy, scope_id="team-result:r1")
    repository.ensure_export_manifest(
        manifest, policy_snapshot_id=policy_id, manifest_id="manifest-1"
    )
    return repository, policy, policy_id, manifest


def _failed_statements(database: Database) -> list[str]:
    failures: list[str] = []

    def handle_error(context):  # type: ignore[no-untyped-def]
        failures.append(type(context.original_exception).__name__)

    event.listen(database.engine, "handle_error", handle_error)
    return failures


def _ensure_again_and_confirm(repository, policy, policy_id, manifest) -> str:  # type: ignore[no-untyped-def]
    # Same shape as authorize_team_dispatch: ensure, then read and confirm.
    with repository.one_transaction():
        manifest_id = repository.ensure_export_manifest(manifest, policy_snapshot_id=policy_id)
        assert repository.get_export_confirmation(manifest.manifest_hash) is None
        repository.save_export_confirmation(
            manifest_id,
            confirm_export_manifest(manifest, policy, confirmed_at="2026-10-19T00:42:00Z"),
        )
    return str(manifest_id)


def test_existing_manifest_is_verified_without_a_failing_insert(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'm.sqlite3'}")
    database.upgrade_schema()
    repository, policy, policy_id, manifest = _seed(database)
    failures = _failed_statements(database)
    assert _ensure_again_and_confirm(repository, policy, policy_id, manifest) == "manifest-1"
    # Before: a duplicate INSERT failed here (IntegrityError), which aborts
    # the shared transaction on PostgreSQL.
    assert failures == []
    assert repository.get_export_confirmation(manifest.manifest_hash) is not None
    database.dispose()


def test_ensure_in_one_transaction_on_postgres(tmp_path: Path) -> None:
    if not _POSTGRES_URL:
        pytest.skip("MAYA_TEST_POSTGRES_URL is not set")
    database = Database(_POSTGRES_URL, tmp_path)
    with database.engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    database.initialize_schema()
    try:
        repository, policy, policy_id, manifest = _seed(database)
        assert _ensure_again_and_confirm(repository, policy, policy_id, manifest) == "manifest-1"
        assert repository.get_export_confirmation(manifest.manifest_hash) is not None
    finally:
        database.engine.dispose()


def test_concurrent_duplicate_insert_keeps_postgres_transaction_usable(tmp_path: Path) -> None:
    """A race lost at INSERT time (row appears after the read) is still verified."""
    if not _POSTGRES_URL:
        pytest.skip("MAYA_TEST_POSTGRES_URL is not set")
    database = Database(_POSTGRES_URL, tmp_path)
    with database.engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    database.initialize_schema()
    try:
        repository, policy, policy_id, manifest = _seed(database)
        original = repository._read_one
        calls = {"n": 0}

        def miss_first_read(statement):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return None if calls["n"] == 1 else original(statement)

        repository._read_one = miss_first_read
        assert _ensure_again_and_confirm(repository, policy, policy_id, manifest) == "manifest-1"
    finally:
        database.engine.dispose()
