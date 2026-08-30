"""Lossless migration probe for positive mutual-learning round numbers."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.db import Database  # noqa: E402
from app.seed import seed_demo_data  # noqa: E402
from test_wave2_migration import (  # noqa: E402
    PRE_WAVE_3_POLISH_REVISION,
    WAVE_0_REVISION,
    WAVE_1B_REVISION,
    WAVE_2_REVISION,
    database_url,
    downgrade_alembic,
    insert_legacy_playback_fixture,
    insert_wave1_rows_and_voice_ledger,
    run_alembic,
    table_columns,
    table_fingerprints,
)

REVISION_0007 = "0007_wave3_interaction_report"
REVISION_0008 = "0008_wave4_mutual_learning_rounds"


def _seed_legacy(path: Path, data_root: Path) -> dict[str, str]:
    run_alembic(path, WAVE_0_REVISION)
    wave_zero = Database(database_url(path), data_root)
    try:
        with wave_zero.session() as session:
            seed_demo_data(session)
    finally:
        wave_zero.dispose()
    run_alembic(path, WAVE_1B_REVISION)
    database = Database(database_url(path), data_root)
    try:
        insert_wave1_rows_and_voice_ledger(database)
    finally:
        database.dispose()
    run_alembic(path, WAVE_2_REVISION)
    fixture = insert_legacy_playback_fixture(path)
    run_alembic(path, PRE_WAVE_3_POLISH_REVISION)
    run_alembic(path, REVISION_0007)
    return fixture


def _assert_revision_and_fks(path: Path, expected: str) -> None:
    database = Database(database_url(path))
    try:
        with database.engine.connect() as connection:
            actual = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            if actual != expected:
                raise AssertionError(f"expected revision {expected}, got {actual}")
            violations = connection.execute(text("PRAGMA foreign_key_check")).all()
            if violations:
                raise AssertionError(f"foreign-key violations: {violations}")
    finally:
        database.dispose()


def _round_check(path: Path) -> str:
    database = Database(database_url(path))
    try:
        rows = inspect(database.engine).get_check_constraints("debate_turns")
        match = next((row for row in rows if row.get("name") == "ck_debate_turns_round"), None)
        if match is None:
            raise AssertionError("ck_debate_turns_round is missing")
        return "".join(str(match.get("sqltext") or "").lower().split())
    finally:
        database.dispose()


def _clone_turn(path: Path, source_id: str, *, round_no: int, turn_index: int) -> str:
    database = Database(database_url(path))
    clone_id = str(uuid4())
    try:
        columns = [str(row["name"]) for row in inspect(database.engine).get_columns("debate_turns")]
        expressions = []
        values: dict[str, object] = {"source_id": source_id, "clone_id": clone_id}
        for column in columns:
            if column == "id":
                expressions.append(":clone_id")
            elif column == "round_no":
                expressions.append(":round_no")
                values["round_no"] = round_no
            elif column == "turn_index":
                expressions.append(":turn_index")
                values["turn_index"] = turn_index
            else:
                expressions.append(f'"{column}"')
        statement = text(
            f"INSERT INTO debate_turns ({', '.join(columns)}) "
            f"SELECT {', '.join(expressions)} FROM debate_turns WHERE id=:source_id"
        )
        with database.engine.begin() as connection:
            result = connection.execute(statement, values)
            if result.rowcount != 1:
                raise AssertionError("source turn was not cloned")
        return clone_id
    finally:
        database.dispose()


def _assert_round_zero_rejected(path: Path, source_id: str) -> None:
    try:
        _clone_turn(path, source_id, round_no=0, turn_index=99)
    except IntegrityError:
        return
    raise AssertionError("round zero unexpectedly satisfied ck_debate_turns_round")


def _expect_lossless_downgrade_refusal(path: Path) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url(path)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", REVISION_0007],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        raise AssertionError("downgrade with round >2 unexpectedly succeeded")
    output = result.stdout + result.stderr
    if "Cannot downgrade 0008 while debate_turns contains rounds greater than two" not in output:
        raise AssertionError(f"downgrade failed for the wrong reason: {output[-1200:]}")


def _assert_rows_preserved(before: dict[str, str], after: dict[str, str], label: str) -> None:
    for table, fingerprint in before.items():
        if table == "alembic_version":
            continue
        if after.get(table) != fingerprint:
            raise AssertionError(f"{label} changed pre-existing rows in {table}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maya-wave4-migration-") as temporary:
        root = Path(temporary)

        fresh = root / "fresh.sqlite3"
        # Keep this probe pinned to 0008 as later Wave 4 migrations are
        # appended. Database readiness and the Persona migration have their
        # own head-specific tests.
        run_alembic(fresh, REVISION_0008)
        run_alembic(fresh, REVISION_0008)
        _assert_revision_and_fks(fresh, REVISION_0008)
        if _round_check(fresh) != "round_no>=1":
            raise AssertionError(f"unexpected positive-round check: {_round_check(fresh)}")

        legacy = root / "legacy.sqlite3"
        _seed_legacy(legacy, root / "legacy-data")
        columns = table_columns(legacy)
        before = table_fingerprints(legacy, columns_by_table=columns)
        run_alembic(legacy, REVISION_0008)
        _assert_revision_and_fks(legacy, REVISION_0008)
        _assert_rows_preserved(
            before,
            table_fingerprints(legacy, columns_by_table=columns),
            "0008",
        )
        downgrade_alembic(legacy, REVISION_0007)
        _assert_revision_and_fks(legacy, REVISION_0007)
        if _round_check(legacy) != "round_no>=1andround_no<=2":
            raise AssertionError(f"unexpected legacy round check: {_round_check(legacy)}")
        _assert_rows_preserved(
            before,
            table_fingerprints(legacy, columns_by_table=columns),
            "lossless downgrade",
        )
        run_alembic(legacy, REVISION_0008)
        _assert_rows_preserved(
            before,
            table_fingerprints(legacy, columns_by_table=columns),
            "re-upgrade",
        )

        extended = root / "extended.sqlite3"
        extended_fixture = _seed_legacy(extended, root / "extended-data")
        run_alembic(extended, REVISION_0008)
        round_five_id = _clone_turn(
            extended,
            extended_fixture["turn_id"],
            round_no=5,
            turn_index=10,
        )
        _assert_round_zero_rejected(extended, extended_fixture["turn_id"])
        _expect_lossless_downgrade_refusal(extended)
        _assert_revision_and_fks(extended, REVISION_0008)
        database = Database(database_url(extended))
        try:
            with database.engine.connect() as connection:
                stored_round = connection.execute(
                    text("SELECT round_no FROM debate_turns WHERE id=:id"),
                    {"id": round_five_id},
                ).scalar_one()
                if stored_round != 5:
                    raise AssertionError("failed downgrade changed the round-five row")
        finally:
            database.dispose()

    print("WAVE4_MIGRATION_OK")


if __name__ == "__main__":
    main()
