"""Deterministic fresh/populated/downgrade evidence for migration 0013."""

from __future__ import annotations

import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
TEST_ROOT = BACKEND_ROOT / "tests"
for import_root in (BACKEND_ROOT, TEST_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.core.db import Database

from test_wave4_embedding_identity_orm import (
    REVISION,
    _database_url,
    _downgrade,
    _revision,
    _seed_populated_legacy,
    _table_names,
    _upgrade,
)


def _assert_legacy_content(path: Path, fixture: dict[str, str]) -> None:
    database = Database(_database_url(path))
    try:
        with database.engine.connect() as connection:
            snapshot = connection.execute(
                text(
                    "SELECT id, embedding_provider, embedding_model_key, embedding_region, "
                    "embedding_dimension, embedding_policy_version FROM knowledge_snapshots "
                    "WHERE id=:snapshot_id"
                ),
                fixture,
            ).one()
            if tuple(snapshot) != (
                fixture["snapshot_id"],
                "mock",
                "mock-sha256-v1",
                "local",
                256,
                "w4-mock-v1",
            ):
                raise AssertionError(f"legacy snapshot identity drifted: {snapshot}")
            chunk = connection.execute(
                text("SELECT id, embedding_blob FROM knowledge_chunks WHERE id=:chunk_id"),
                fixture,
            ).one()
            if tuple(chunk) != (fixture["chunk_id"], b"legacy-vector"):
                raise AssertionError(f"legacy chunk/vector drifted: {chunk}")
    finally:
        database.dispose()


def _insert_real_identity(path: Path, fixture: dict[str, str]) -> None:
    database = Database(_database_url(path))
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE knowledge_snapshots SET embedding_provider='dashscope', "
                    "embedding_model_key='text-embedding-v4', embedding_region='cn-beijing', "
                    "embedding_dimension=1024, embedding_policy_version='w4-embed-v1' "
                    "WHERE id=:snapshot_id"
                ),
                fixture,
            )
    finally:
        database.dispose()


def _insert_stage(path: Path, fixture: dict[str, str]) -> None:
    database = Database(_database_url(path))
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO embedding_accepted_stages "
                    "(operation_id,build_id,build_manifest_hash,batch_index,model_key,"
                    "embedding_provider,embedding_region,dimension,policy_version,response_hash,"
                    "created_at) VALUES (:operation_id,'build-001',:hash,0,'text-embedding-v4',"
                    "'dashscope','cn-beijing',1024,'w4-embed-v1',:hash,:now)"
                ),
                {**fixture, "hash": "d" * 64, "now": datetime.now(UTC)},
            )
    finally:
        database.dispose()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maya-wave4-embedding-identity-") as directory:
        root = Path(directory)

        fresh = root / "fresh.sqlite3"
        _upgrade(fresh)
        _upgrade(fresh)
        if _revision(fresh) != REVISION:
            raise AssertionError("fresh/repeat migration did not reach 0013")
        if not {"embedding_accepted_stages", "embedding_accepted_vectors"} <= set(
            _table_names(fresh)
        ):
            raise AssertionError("fresh migration omitted accepted embedding stage tables")
        _downgrade(fresh)
        if _revision(fresh) != "0012_persona_activation":
            raise AssertionError("fresh downgrade did not return to 0012")

        populated = root / "populated.sqlite3"
        fixture = _seed_populated_legacy(populated)
        _upgrade(populated)
        _assert_legacy_content(populated, fixture)
        _downgrade(populated)
        if _revision(populated) != "0012_persona_activation":
            raise AssertionError("populated lossless downgrade did not return to 0012")
        database = Database(_database_url(populated))
        try:
            with database.engine.connect() as connection:
                if (
                    connection.execute(
                        text("SELECT embedding_blob FROM knowledge_chunks WHERE id=:chunk_id"),
                        fixture,
                    ).scalar_one()
                    != b"legacy-vector"
                ):
                    raise AssertionError("lossless downgrade changed the legacy vector")
        finally:
            database.dispose()

        real = root / "real.sqlite3"
        real_fixture = _seed_populated_legacy(real)
        _upgrade(real)
        _insert_real_identity(real, real_fixture)
        try:
            _downgrade(real)
        except RuntimeError as error:
            if "real or invalid embedding identity" not in str(error):
                raise AssertionError(f"real identity refused for wrong reason: {error}") from error
        else:
            raise AssertionError("real identity downgrade unexpectedly succeeded")

        staged = root / "staged.sqlite3"
        stage_fixture = _seed_populated_legacy(staged)
        _upgrade(staged)
        _insert_stage(staged, stage_fixture)
        try:
            _downgrade(staged)
        except RuntimeError as error:
            if "accepted embedding stages" not in str(error):
                raise AssertionError(
                    f"stage downgrade refused for wrong reason: {error}"
                ) from error
        else:
            raise AssertionError("accepted stage downgrade unexpectedly succeeded")

    print("WAVE4_EMBEDDING_IDENTITY_MIGRATION_OK")


if __name__ == "__main__":
    main()
