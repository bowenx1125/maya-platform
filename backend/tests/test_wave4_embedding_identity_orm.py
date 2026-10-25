"""Migration and ORM coverage for the immutable embedding identity boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from app.core.db import Database
from app.core.models import EmbeddingAcceptedStage, EmbeddingAcceptedVector, KnowledgeSnapshot
from sqlalchemy import inspect, text

from tests.postgres_db import named_url

REVISION = "0013_embedding_identity_stage"
PREVIOUS_REVISION = "0012_persona_activation"
AUTHORED_CONTENT_REVISION = "0034_authored_content_unbounded"
AUTHORED_CONTENT_PREVIOUS_REVISION = "0033_budget_accounting_unbounded"


def test_orm_identity_is_on_snapshot_and_stage_chunk_id_is_build_opaque() -> None:
    snapshot = KnowledgeSnapshot(
        id="snapshot-orm",
        agent_version_id="version-orm",
        stored_file_id="file-orm",
        content_hash="a" * 64,
        total_char_count=1,
        embedding_key="mock",
        embedding_provider="mock",
        embedding_region="local",
        embedding_dimension=256,
        embedding_policy_version="w4-mock-v1",
        chunking_json="{}",
        created_at=datetime.now(UTC),
    )
    assert snapshot.embedding_key == "mock-sha256-v1"
    assert snapshot.embedding_model_key == "mock-sha256-v1"
    assert snapshot.embedding_model == "mock-sha256-v1"
    assert snapshot.provider == "mock"
    assert snapshot.region == "local"
    assert snapshot.dimension == 256
    assert snapshot.policy_version == "w4-mock-v1"
    assert {
        "embedding_provider",
        "embedding_model_key",
        "embedding_region",
        "embedding_dimension",
        "embedding_policy_version",
    } <= {str(column.name) for column in KnowledgeSnapshot.__table__.columns}
    assert not EmbeddingAcceptedVector.__table__.c.chunk_id.foreign_keys
    assert "operation_id" in {
        str(column.name) for column in EmbeddingAcceptedStage.__table__.columns
    }


def _config(database_url: str) -> Config:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


def _database_url(path: Path) -> str:
    return named_url(f"{path}")


def _revision(path: Path) -> str:
    database = Database(_database_url(path))
    try:
        with database.engine.connect() as connection:
            return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar())
    finally:
        database.dispose()


def _columns(path: Path, table: str) -> set[str]:
    database = Database(_database_url(path))
    try:
        return {str(item["name"]) for item in inspect(database.engine).get_columns(table)}
    finally:
        database.dispose()


def _foreign_key_violations(path: Path) -> tuple[str, ...]:
    database = Database(_database_url(path))
    try:
        with database.engine.connect() as connection:
            return tuple(
                sorted(
                    repr(tuple(row))
                    for row in connection.exec_driver_sql("PRAGMA foreign_key_check")
                )
            )
    finally:
        database.dispose()


def _table_names(path: Path) -> list[str]:
    database = Database(_database_url(path))
    try:
        return [str(value) for value in inspect(database.engine).get_table_names()]
    finally:
        database.dispose()
