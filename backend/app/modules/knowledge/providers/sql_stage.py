"""Durable sanitized accepted-vector staging for W4-EMBED."""

from __future__ import annotations

import struct
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import Engine, Table, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import Database
from app.core.models import (
    EmbeddingAcceptedStage,
    EmbeddingAcceptedVector,
    ProviderOperation,
    ProviderReservation,
)

from .runtime import AcceptedEmbeddingStageV1, SnapshotEmbeddingRuntimeError

_STAGE_TABLE = cast(Table, EmbeddingAcceptedStage.__table__)
_VECTOR_TABLE = cast(Table, EmbeddingAcceptedVector.__table__)
_OPERATION_TABLE = cast(Table, ProviderOperation.__table__)
_RESERVATION_TABLE = cast(Table, ProviderReservation.__table__)


class SqlAlchemyEmbeddingStageStore:
    """Commit sanitized vectors and ``sending -> accepted`` in one transaction."""

    def __init__(self, database: Database | Engine | Session) -> None:
        if isinstance(database, Database):
            self.engine = database.engine
        elif isinstance(database, Engine):
            self.engine = database
        elif isinstance(database, Session):
            bind = database.get_bind()
            if not isinstance(bind, Engine):
                raise TypeError("embedding stage store requires a SQLAlchemy Engine")
            self.engine = bind
        else:
            raise TypeError("embedding stage store requires Database, Engine or Session")

    @contextmanager
    def _write_connection(self) -> Iterator[Connection]:
        connection = self.engine.connect()
        committed = False
        try:
            connection.begin()
            yield connection
            connection.commit()
            committed = True
        finally:
            if not committed:
                connection.rollback()
            connection.close()

    def stage(self, value: AcceptedEmbeddingStageV1) -> AcceptedEmbeddingStageV1:
        """A durable stage is inseparable from its accepted ledger transition."""

        return self.stage_accepted(value)

    stage_and_accept = stage

    def stage_accepted(self, value: AcceptedEmbeddingStageV1) -> AcceptedEmbeddingStageV1:
        try:
            with self._write_connection() as connection:
                operation = (
                    connection.execute(
                        select(_OPERATION_TABLE).where(_OPERATION_TABLE.c.id == value.operation_id)
                    )
                    .mappings()
                    .first()
                )
                if operation is None:
                    raise SnapshotEmbeddingRuntimeError(
                        "accepted-stage operation does not exist",
                        code="embedding_atomic_stage_unavailable",
                    )
                existing = self._get(connection, value.operation_id)
                if existing is not None:
                    if (
                        existing != value
                        or operation["state"] != "accepted"
                        or operation["staged_response_hash"] != value.response_hash
                    ):
                        raise SnapshotEmbeddingRuntimeError(
                            "accepted embedding stage changed",
                            code="embedding_stage_conflict",
                        )
                    return existing
                if (
                    operation["state"] != "sending"
                    or operation["provider_operation"] not in {"embedding", "embedding_query"}
                    or operation["provider_operation"] == "embedding"
                    and operation["scope_id"] != value.build_id
                    or operation["build_manifest_hash"] != value.build_manifest_hash
                    or operation["model_key"] != value.model_key
                ):
                    raise SnapshotEmbeddingRuntimeError(
                        "accepted-stage operation does not match the build",
                        code="embedding_atomic_stage_unavailable",
                    )
                timestamp = datetime.now(UTC)
                connection.execute(
                    _STAGE_TABLE.insert().values(
                        operation_id=value.operation_id,
                        build_id=value.build_id,
                        build_manifest_hash=value.build_manifest_hash,
                        batch_index=value.batch_index,
                        model_key=value.model_key,
                        embedding_provider=value.embedding_provider,
                        embedding_region=value.embedding_region,
                        dimension=value.dimension,
                        policy_version=value.policy_version,
                        response_hash=value.response_hash,
                        created_at=timestamp,
                    )
                )
                connection.execute(
                    _VECTOR_TABLE.insert(),
                    [
                        {
                            "operation_id": value.operation_id,
                            "item_index": index,
                            "chunk_id": chunk_id,
                            "embedding_blob": struct.pack(f"<{value.dimension}f", *vector),
                        }
                        for index, (chunk_id, vector) in enumerate(
                            zip(value.chunk_ids, value.vectors, strict=True)
                        )
                    ],
                )
                changed = connection.execute(
                    update(_OPERATION_TABLE)
                    .where(
                        _OPERATION_TABLE.c.id == value.operation_id,
                        _OPERATION_TABLE.c.state == "sending",
                    )
                    .values(
                        state="accepted",
                        staged_response_hash=value.response_hash,
                        updated_at=timestamp,
                    )
                )
                reservation_changed = connection.execute(
                    update(_RESERVATION_TABLE)
                    .where(
                        _RESERVATION_TABLE.c.operation_id == value.operation_id,
                        _RESERVATION_TABLE.c.state == "sending",
                    )
                    .values(state="accepted", updated_at=timestamp)
                )
                if changed.rowcount != 1 or reservation_changed.rowcount != 1:
                    raise SnapshotEmbeddingRuntimeError(
                        "accepted-stage operation transition failed",
                        code="embedding_atomic_stage_unavailable",
                    )
        except SnapshotEmbeddingRuntimeError:
            raise
        except IntegrityError as exc:
            current = self.get(value.operation_id)
            if current == value:
                return current
            raise SnapshotEmbeddingRuntimeError(
                "accepted embedding stage changed",
                code="embedding_stage_conflict",
            ) from exc
        current = self.get(value.operation_id)
        if current != value:
            raise SnapshotEmbeddingRuntimeError(
                "accepted embedding stage could not be reloaded",
                code="embedding_stage_invalid",
            )
        return current

    def get(self, operation_id: str) -> AcceptedEmbeddingStageV1 | None:
        with self.engine.connect() as connection:
            return self._get(connection, operation_id)

    def values(self, *, build_id: str | None = None) -> tuple[AcceptedEmbeddingStageV1, ...]:
        statement = select(_STAGE_TABLE.c.operation_id).order_by(
            _STAGE_TABLE.c.batch_index,
            _STAGE_TABLE.c.operation_id,
        )
        if build_id is not None:
            statement = statement.where(_STAGE_TABLE.c.build_id == build_id)
        with self.engine.connect() as connection:
            ids = [str(row[0]) for row in connection.execute(statement).all()]
            return tuple(
                value
                for operation_id in ids
                if (value := self._get(connection, operation_id)) is not None
            )

    @staticmethod
    def _get(
        connection: Connection,
        operation_id: str,
    ) -> AcceptedEmbeddingStageV1 | None:
        row = (
            connection.execute(
                select(_STAGE_TABLE).where(_STAGE_TABLE.c.operation_id == operation_id)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        vectors = connection.execute(
            select(_VECTOR_TABLE)
            .where(_VECTOR_TABLE.c.operation_id == operation_id)
            .order_by(_VECTOR_TABLE.c.item_index)
        ).mappings()
        dimension = int(row["dimension"])
        chunk_ids: list[str] = []
        values: list[tuple[float, ...]] = []
        for expected_index, vector in enumerate(vectors):
            if int(vector["item_index"]) != expected_index:
                raise SnapshotEmbeddingRuntimeError(
                    "accepted embedding stage order is corrupt",
                    code="embedding_stage_invalid",
                )
            blob = bytes(vector["embedding_blob"])
            if len(blob) != dimension * 4:
                raise SnapshotEmbeddingRuntimeError(
                    "accepted embedding vector shape is corrupt",
                    code="embedding_stage_invalid",
                )
            chunk_ids.append(str(vector["chunk_id"]))
            values.append(struct.unpack(f"<{dimension}f", blob))
        try:
            return AcceptedEmbeddingStageV1(
                operation_id=str(row["operation_id"]),
                build_id=str(row["build_id"]),
                build_manifest_hash=str(row["build_manifest_hash"]),
                batch_index=int(row["batch_index"]),
                chunk_ids=tuple(chunk_ids),
                vectors=tuple(values),
                model_key=str(row["model_key"]),
                dimension=dimension,
                response_hash=str(row["response_hash"]),
                embedding_provider=str(row["embedding_provider"]),
                embedding_region=str(row["embedding_region"]),
                policy_version=str(row["policy_version"]),
            )
        except Exception as exc:
            raise SnapshotEmbeddingRuntimeError(
                "accepted embedding stage is corrupt",
                code="embedding_stage_invalid",
            ) from exc


__all__ = ["SqlAlchemyEmbeddingStageStore"]
