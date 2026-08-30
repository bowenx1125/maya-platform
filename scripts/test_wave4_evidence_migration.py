"""Lossless 0011 EvidenceTrace persistence migration probe."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import inspect, text

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.db import Database  # noqa: E402
from test_wave2_migration import database_url, downgrade_alembic, run_alembic  # noqa: E402
from test_wave4_migration import _assert_revision_and_fks, _seed_legacy  # noqa: E402

REVISION_0010 = "0010_provider_control_ledger"
REVISION_0011 = "0011_evidence_trace_json"


def _column_names(path: Path) -> set[str]:
    database = Database(database_url(path))
    try:
        return {str(item["name"]) for item in inspect(database.engine).get_columns("debate_turns")}
    finally:
        database.dispose()


def _expect_lossy_downgrade_refusal(path: Path) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url(path)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", REVISION_0010],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        raise AssertionError("0011 downgrade with retained trace unexpectedly succeeded")
    if "Cannot downgrade 0011 while EvidenceTrace rows are retained" not in (
        result.stdout + result.stderr
    ):
        raise AssertionError("0011 downgrade failed for the wrong reason")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maya-wave4-evidence-migration-") as temporary:
        root = Path(temporary)

        fresh = root / "fresh.sqlite3"
        run_alembic(fresh, REVISION_0011)
        run_alembic(fresh, REVISION_0011)
        _assert_revision_and_fks(fresh, REVISION_0011)
        if "evidence_trace_json" not in _column_names(fresh):
            raise AssertionError("0011 evidence_trace_json column is missing")

        populated = root / "populated.sqlite3"
        fixture = _seed_legacy(populated, root / "populated-data")
        run_alembic(populated, REVISION_0011)
        _assert_revision_and_fks(populated, REVISION_0011)
        database = Database(database_url(populated))
        try:
            with database.engine.connect() as connection:
                legacy_value = connection.execute(
                    text("SELECT evidence_trace_json FROM debate_turns WHERE id=:turn_id"),
                    {"turn_id": fixture["turn_id"]},
                ).scalar_one()
                if legacy_value != "[]":
                    raise AssertionError("0011 rewrote a legacy turn trace")
        finally:
            database.dispose()

        downgrade_alembic(populated, REVISION_0010)
        _assert_revision_and_fks(populated, REVISION_0010)
        if "evidence_trace_json" in _column_names(populated):
            raise AssertionError("lossless 0011 downgrade retained the new column")
        run_alembic(populated, REVISION_0011)

        database = Database(database_url(populated))
        try:
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE debate_turns SET evidence_trace_json=:trace "
                        "WHERE id=:turn_id"
                    ),
                    {
                        "turn_id": fixture["turn_id"],
                        "trace": '[{"trace_version":"evidence_trace_v1"}]',
                    },
                )
        finally:
            database.dispose()
        _expect_lossy_downgrade_refusal(populated)
        _assert_revision_and_fks(populated, REVISION_0011)

    print("WAVE4_EVIDENCE_MIGRATION_OK")


if __name__ == "__main__":
    main()
