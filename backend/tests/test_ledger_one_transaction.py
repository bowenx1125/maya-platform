"""Ledger steps between two network points commit as one transaction.

2026-10-18: each model call committed nine separate ledger transactions.
Budget, prepared operation, binding and reservation now commit together, as
do the accepted stage and success; any failure rolls every step back.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from app.core.models import ProviderOperation
from app.providers.control import ProviderScopeBudgetV1
from app.providers.control_repository import ProviderRepository, ScopeBudgetMissing
from sqlalchemy import event, func, select

from tests.test_wave4_provider_control_orm import _repository_with_confirmed_manifest, _request


def _count_write_commits(database):  # type: ignore[no-untyped-def]
    commits: list[int] = []
    wrote: set[int] = set()

    def statement(conn, cursor, text, parameters, context, executemany):  # type: ignore[no-untyped-def]
        if not text.lstrip()[:6].upper().startswith("SELECT"):
            wrote.add(id(conn))

    def commit(conn):  # type: ignore[no-untyped-def]
        if id(conn) in wrote:
            wrote.discard(id(conn))
            commits.append(1)

    event.listen(database.engine, "after_cursor_execute", statement)
    event.listen(database.engine, "commit", commit)
    return commits


def test_budget_prepare_and_reserve_commit_once(tmp_path: Path) -> None:
    database, repository, manifest = _repository_with_confirmed_manifest(tmp_path)
    commits = _count_write_commits(database)
    with repository.one_transaction():
        repository.save_scope_budget(
            "scope-1",
            ProviderScopeBudgetV1(max_requests=20, max_total_tokens=120_000, max_cost_cny=0.10),
        )
        operation = repository.create_prepared(_request(manifest))
        # Reads inside the transaction see its own uncommitted rows.
        assert repository.operation(operation.id).state == "prepared"
        reservation = repository.reserve(operation.id)
    assert len(commits) == 1
    assert repository.operation(operation.id).state == "reserved"
    assert reservation.operation_id == operation.id
    database.dispose()


def test_a_failure_rolls_every_step_back(tmp_path: Path) -> None:
    database, _repository, manifest = _repository_with_confirmed_manifest(tmp_path)
    repository = ProviderRepository(database, require_export_confirmation=False)
    with pytest.raises(ScopeBudgetMissing):
        with repository.one_transaction():
            # No budget for this scope: reserve fails after the operation row.
            operation = repository.create_prepared(
                replace(_request(manifest), scope_id="no-budget")
            )
            repository.reserve(operation.id)
    with database.session() as db:
        # Before, a "prepared" row was left behind and blocked a retry.
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0
    database.dispose()


def test_nested_transactions_join_the_outer_one(tmp_path: Path) -> None:
    database, repository, manifest = _repository_with_confirmed_manifest(tmp_path)
    commits = _count_write_commits(database)
    with repository.one_transaction():
        operation = repository.create_prepared(_request(manifest))
        with repository.one_transaction():
            repository.reserve(operation.id)
    assert len(commits) == 1
    database.dispose()


def test_steps_outside_one_transaction_still_commit_each(tmp_path: Path) -> None:
    database, repository, manifest = _repository_with_confirmed_manifest(tmp_path)
    commits = _count_write_commits(database)
    operation = repository.create_prepared(_request(manifest))
    repository.reserve(operation.id)
    assert len(commits) == 2
    database.dispose()
