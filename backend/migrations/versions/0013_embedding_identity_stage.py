"""Persist embedding identity and sanitized accepted-vector stages.

The migration extends the existing immutable ``knowledge_snapshots`` row.  It
does not rewrite snapshot IDs, chunk IDs, vector blobs or any other published
product data.  Historical rows receive the explicit local Mock identity.  A
real identity is intentionally a separate closed combination so an old Mock
snapshot cannot be mistaken for a Provider result.

Accepted stages retain only server-owned hashes and opaque local IDs.  The
``chunk_id`` on a staged vector is the frozen SnapshotBuild identity; it is
not a foreign key to ``knowledge_chunks`` because staging happens before a
published snapshot exists.  The supplier response envelope, credential,
endpoint and workspace are not represented by either stage table.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_embedding_identity_stage"
down_revision: str | Sequence[str] | None = "0012_persona_activation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SNAPSHOT_IDENTITY_CHECK = (
    "(embedding_provider = 'mock' "
    "AND embedding_model_key = 'mock-sha256-v1' "
    "AND embedding_region = 'local' "
    "AND embedding_dimension = 256 "
    "AND embedding_policy_version = 'w4-mock-v1') "
    "OR (embedding_provider = 'dashscope' "
    "AND embedding_model_key = 'text-embedding-v4' "
    "AND embedding_region = 'cn-beijing' "
    "AND embedding_dimension = 1024 "
    "AND embedding_policy_version = 'w4-embed-v1')"
)


def _add_snapshot_identity() -> None:
    """Add required identity columns with safe historical defaults."""

    # ADD COLUMN is natively supported by SQLite and does not touch the
    # referenced snapshot_documents/knowledge_chunks tables.  Do not use an
    # implicit batch recreate for this additive part of the migration.
    op.add_column(
        "knowledge_snapshots",
        sa.Column(
            "embedding_provider",
            sa.String(length=40),
            nullable=False,
            server_default=sa.text("'mock'"),
        ),
    )
    op.add_column(
        "knowledge_snapshots",
        sa.Column(
            "embedding_region",
            sa.String(length=40),
            nullable=False,
            server_default=sa.text("'local'"),
        ),
    )
    op.add_column(
        "knowledge_snapshots",
        sa.Column(
            "embedding_dimension",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("256"),
        ),
    )
    op.add_column(
        "knowledge_snapshots",
        sa.Column(
            "embedding_policy_version",
            sa.String(length=80),
            nullable=False,
            server_default=sa.text("'w4-mock-v1'"),
        ),
    )

    # The existing model-key column is the snapshot's model identity.  Make
    # every historical row use the explicit Mock key required by this
    # identity contract; IDs, chunk rows and vector blobs remain untouched.
    op.execute(
        sa.text(
            "UPDATE knowledge_snapshots SET "
            "embedding_provider = 'mock', "
            "embedding_model_key = 'mock-sha256-v1', "
            "embedding_region = 'local', "
            "embedding_dimension = 256, "
            "embedding_policy_version = 'w4-mock-v1'"
        )
    )

    _add_snapshot_identity_check()


def _add_snapshot_identity_check() -> None:
    """Add the closed identity check without cascading child rows on SQLite."""

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        with op.batch_alter_table("knowledge_snapshots") as batch:
            batch.create_check_constraint(
                "ck_knowledge_snapshots_embedding_identity",
                _SNAPSHOT_IDENTITY_CHECK,
            )
        return

    # knowledge_snapshots is referenced by snapshot_documents and
    # knowledge_chunks with ON DELETE CASCADE.  A SQLite table rebuild would
    # otherwise delete those historical rows when the old parent is dropped.
    # Match the lossless parent-table rebuild protocol used by migration 0008.
    with op.get_context().autocommit_block():
        sqlite = op.get_bind()
        sqlite.exec_driver_sql("PRAGMA foreign_keys=OFF")
        sqlite.exec_driver_sql("BEGIN IMMEDIATE")
        committed = False
        try:
            with op.batch_alter_table("knowledge_snapshots", recreate="always") as batch:
                batch.create_check_constraint(
                    "ck_knowledge_snapshots_embedding_identity",
                    _SNAPSHOT_IDENTITY_CHECK,
                )
            violations = sqlite.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"0013 left foreign-key violations: {violations}")
            sqlite.exec_driver_sql("COMMIT")
            committed = True
        finally:
            if not committed:
                sqlite.exec_driver_sql("ROLLBACK")
            sqlite.exec_driver_sql("PRAGMA foreign_keys=ON")
            enabled = sqlite.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
            if enabled != 1:
                raise RuntimeError("0013 failed to restore SQLite foreign-key enforcement")


def _create_embedding_stage_tables() -> None:
    op.create_table(
        "embedding_accepted_stages",
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("build_id", sa.String(length=120), nullable=False),
        sa.Column("build_manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("model_key", sa.String(length=80), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("response_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["provider_operations.id"],
            name="fk_embedding_accepted_stages_operation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("operation_id"),
        sa.CheckConstraint(
            "batch_index >= 0", name="ck_embedding_accepted_stages_batch_index"
        ),
        sa.CheckConstraint("dimension > 0", name="ck_embedding_accepted_stages_dimension"),
        sa.CheckConstraint(
            "length(build_manifest_hash) = 64",
            name="ck_embedding_accepted_stages_build_hash",
        ),
        sa.CheckConstraint(
            "length(response_hash) = 64",
            name="ck_embedding_accepted_stages_response_hash",
        ),
        sa.CheckConstraint("length(build_id) > 0", name="ck_embedding_accepted_stages_build_id"),
        sa.CheckConstraint("length(model_key) > 0", name="ck_embedding_accepted_stages_model"),
        sa.CheckConstraint(
            "length(policy_version) > 0", name="ck_embedding_accepted_stages_policy_version"
        ),
    )
    op.create_index(
        "ix_embedding_accepted_stages_build",
        "embedding_accepted_stages",
        ["build_id", "batch_index"],
        unique=False,
    )

    op.create_table(
        "embedding_accepted_vectors",
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("embedding_blob", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["embedding_accepted_stages.operation_id"],
            name="fk_embedding_accepted_vectors_stage",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("operation_id", "item_index"),
        sa.UniqueConstraint(
            "operation_id",
            "chunk_id",
            name="uq_embedding_accepted_vectors_chunk",
        ),
        sa.CheckConstraint(
            "item_index >= 0", name="ck_embedding_accepted_vectors_item_index"
        ),
        sa.CheckConstraint("length(embedding_blob) > 0", name="ck_embedding_accepted_vectors_blob"),
    )
    op.create_index(
        "ix_embedding_accepted_vectors_chunk",
        "embedding_accepted_vectors",
        ["chunk_id"],
        unique=False,
    )


def _add_manifest_owners() -> None:
    """Bind new manifests to their owning course/group/version when present.

    Existing ProviderExportManifest rows intentionally remain NULL.  The
    application layer requires all three values for a new W4-EMBED manifest;
    the nullable columns preserve older provider-control history.
    """

    def rebuild() -> None:
        with op.batch_alter_table("provider_export_manifests", recreate="always") as batch:
            batch.add_column(sa.Column("course_id", sa.String(length=36), nullable=True))
            batch.add_column(sa.Column("group_id", sa.String(length=36), nullable=True))
            batch.add_column(sa.Column("agent_version_id", sa.String(length=36), nullable=True))
            batch.create_foreign_key(
                "fk_provider_export_manifests_course",
                "courses",
                ["course_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_foreign_key(
                "fk_provider_export_manifests_group",
                "groups",
                ["group_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_foreign_key(
                "fk_provider_export_manifests_agent_version",
                "agent_versions",
                ["agent_version_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_index(
                "ix_provider_export_manifests_course",
                ["course_id"],
                unique=False,
            )
            batch.create_index(
                "ix_provider_export_manifests_group",
                ["group_id"],
                unique=False,
            )
            batch.create_index(
                "ix_provider_export_manifests_agent_version",
                ["agent_version_id"],
                unique=False,
            )

    _rebuild_sqlite_preserving_children(
        "provider_export_manifests",
        rebuild,
    )


def _rebuild_sqlite_preserving_children(
    table: str,
    operation: Callable[[], None],
) -> None:
    """Run a parent-table batch rebuild without SQLite cascades.

    The helper is also used for downgrade rebuilds.
    """

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        operation()
        return
    del table  # The table name documents the guarded parent for call sites.
    with op.get_context().autocommit_block():
        sqlite = op.get_bind()
        sqlite.exec_driver_sql("PRAGMA foreign_keys=OFF")
        sqlite.exec_driver_sql("BEGIN IMMEDIATE")
        committed = False
        try:
            operation()
            violations = sqlite.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"0013 left foreign-key violations: {violations}")
            sqlite.exec_driver_sql("COMMIT")
            committed = True
        finally:
            if not committed:
                sqlite.exec_driver_sql("ROLLBACK")
            sqlite.exec_driver_sql("PRAGMA foreign_keys=ON")
            enabled = sqlite.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
            if enabled != 1:
                raise RuntimeError("0013 failed to restore SQLite foreign-key enforcement")


def upgrade() -> None:
    _add_snapshot_identity()
    _create_embedding_stage_tables()
    _add_manifest_owners()


def _has_non_mock_identity() -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM knowledge_snapshots WHERE "
            "embedding_provider IS NULL OR embedding_provider <> 'mock' "
            "OR embedding_model_key IS NULL OR embedding_model_key <> 'mock-sha256-v1' "
            "OR embedding_region IS NULL OR embedding_region <> 'local' "
            "OR embedding_dimension IS NULL OR embedding_dimension <> 256 "
            "OR embedding_policy_version IS NULL "
            "OR embedding_policy_version <> 'w4-mock-v1' LIMIT 1"
        )
    ).first()
    return row is not None


def _has_accepted_stages() -> bool:
    bind = op.get_bind()
    return bind.execute(
        sa.text("SELECT 1 FROM embedding_accepted_stages LIMIT 1")
    ).first() is not None


def _has_manifest_owners() -> bool:
    bind = op.get_bind()
    return bind.execute(
        sa.text(
            "SELECT 1 FROM provider_export_manifests WHERE "
            "course_id IS NOT NULL OR group_id IS NOT NULL "
            "OR agent_version_id IS NOT NULL LIMIT 1"
        )
    ).first() is not None


def downgrade() -> None:
    """Remove 0013 only when the operation is demonstrably lossless."""

    if _has_non_mock_identity():
        raise RuntimeError(
            "Cannot downgrade 0013 while a real or invalid embedding identity is retained."
        )
    if _has_accepted_stages():
        raise RuntimeError(
            "Cannot downgrade 0013 while accepted embedding stages are retained."
        )
    if _has_manifest_owners():
        raise RuntimeError(
            "Cannot downgrade 0013 while ProviderExportManifest owner bindings are retained."
        )

    op.drop_index("ix_embedding_accepted_vectors_chunk", table_name="embedding_accepted_vectors")
    op.drop_table("embedding_accepted_vectors")
    op.drop_index("ix_embedding_accepted_stages_build", table_name="embedding_accepted_stages")
    op.drop_table("embedding_accepted_stages")

    def drop_manifest_owners() -> None:
        with op.batch_alter_table("provider_export_manifests", recreate="always") as batch:
            batch.drop_index("ix_provider_export_manifests_agent_version")
            batch.drop_index("ix_provider_export_manifests_group")
            batch.drop_index("ix_provider_export_manifests_course")
            batch.drop_constraint(
                "fk_provider_export_manifests_agent_version", type_="foreignkey"
            )
            batch.drop_constraint("fk_provider_export_manifests_group", type_="foreignkey")
            batch.drop_constraint("fk_provider_export_manifests_course", type_="foreignkey")
            batch.drop_column("agent_version_id")
            batch.drop_column("group_id")
            batch.drop_column("course_id")

    _rebuild_sqlite_preserving_children("provider_export_manifests", drop_manifest_owners)

    def drop_snapshot_identity() -> None:
        with op.batch_alter_table("knowledge_snapshots", recreate="always") as batch:
            batch.drop_constraint("ck_knowledge_snapshots_embedding_identity", type_="check")
            batch.drop_column("embedding_policy_version")
            batch.drop_column("embedding_dimension")
            batch.drop_column("embedding_region")
            batch.drop_column("embedding_provider")

    _rebuild_sqlite_preserving_children("knowledge_snapshots", drop_snapshot_identity)
