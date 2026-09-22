"""Product-owned real-Embedding publication orchestration.

This module binds the pure SnapshotBuild/runtime ports to the current Maya
organization rows.  It deliberately has no selector, settings lookup or
default HTTP transport: callers must provide an already reviewed policy,
exact confirmation and either an injected provider or an injected transport.
The only database writes are the existing ProviderRepository policy/manifest
rows and the publication/runtime adapters owned by the main application.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.db import Database
from app.core.models import (
    Agent,
    AgentVersion,
    AgentVersionDocument,
    Course,
    Group,
    KnowledgeDocument,
    ProviderExportConfirmation,
    ProviderExportManifest,
    ProviderPolicySnapshot,
)
from app.modules.agents.markdown import markdown_hash
from app.modules.knowledge.markdown import MAX_RAG_CHARS, normalize_markdown
from app.modules.knowledge.services import document_file_content
from app.providers.control import (
    ExportConfirmationV1,
    ExportFieldV1,
    ExportManifestV1,
    ProviderPolicySnapshotV1,
    canonical_json_bytes,
    sha256_hex,
)
from app.providers.control_repository import ProviderRepository

from .adapters import (
    DEFAULT_DASHSCOPE_EMBEDDING_ENDPOINT_PATH,
    DashScopeEmbeddingAdapter,
    DashScopeEmbeddingConfig,
    EmbeddingTransport,
)
from .embedding import EmbeddingProvider
from .operations import EmbeddingOperationV1
from .outbound_guard import OutboundEmbeddingDataError, scan_real_embedding_texts
from .packing import (
    DEFAULT_EMBEDDING_COST_CAP_CNY,
    DEFAULT_EMBEDDING_PRICE_CNY_PER_MILLION,
    plan_embedding_batches,
)
from .runtime import SnapshotEmbeddingRuntime, SnapshotEmbeddingRunV1
from .snapshot_build import (
    REAL_EMBEDDING_DIMENSION,
    REAL_EMBEDDING_MODEL,
    REAL_EMBEDDING_POLICY_VERSION,
    REAL_EMBEDDING_PROVIDER,
    REAL_EMBEDDING_REGION,
    SnapshotBuildInputDocument,
    SnapshotBuildV1,
    prepare_snapshot_build,
)
from .sql_runtime import SqlAlchemyEmbeddingControlAdapter, SqlAlchemySnapshotPublicationStore
from .sql_stage import SqlAlchemyEmbeddingStageStore


class ProductPublicationError(RuntimeError):
    """A real product publication precondition failed before provider I/O."""

    def __init__(self, message: str, *, code: str = "embedding_publication_blocked") -> None:
        super().__init__(message)
        self.code = code


EmbeddingProductPublicationError = ProductPublicationError


@dataclass(frozen=True, slots=True)
class RealSnapshotBuildContext:
    """Owner-bound projection captured while preparing one real build."""

    build: SnapshotBuildV1
    course_id: str
    group_id: str
    agent_id: str
    agent_version_id: str
    documents: tuple[SnapshotBuildInputDocument, ...]


@dataclass(frozen=True, slots=True)
class ExportManifestContext:
    """The exact idempotent manifest and its server-only row identities."""

    manifest: ExportManifestV1
    policy_snapshot_id: str
    manifest_id: str


def _product_error(message: str, code: str) -> ProductPublicationError:
    return ProductPublicationError(message, code=code)


@contextmanager
def _session_for(source: Database | Engine | Session) -> Iterator[Session]:
    if isinstance(source, Session):
        yield source
        return
    if isinstance(source, Database):
        session = source.session_factory()
    elif isinstance(source, Engine):
        from sqlalchemy.orm import sessionmaker

        session = sessionmaker(bind=source, class_=Session, autoflush=False)()
    else:
        raise TypeError("publication database must be Database, Engine or Session")
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _engine_for(source: Database | Engine | Session) -> Engine:
    if isinstance(source, Database):
        return source.engine
    if isinstance(source, Engine):
        return source
    if isinstance(source, Session):
        bind = source.get_bind()
        if isinstance(bind, Engine):
            return bind
    raise TypeError("publication database must be Database, Engine or Session")


def _owner_rows(
    db: Session,
    *,
    course_id: str,
    group_id: str,
    agent_version_id: str,
    expected_revision: int | None = None,
) -> tuple[Course, Group, Agent, AgentVersion]:
    """Load and verify the complete course -> group -> agent -> version chain."""

    course = db.get(Course, course_id)
    group = db.get(Group, group_id)
    version = db.get(AgentVersion, agent_version_id)
    if course is None or group is None or version is None:
        raise _product_error("embedding publication owner was not found", "owner_not_found")
    agent = db.get(Agent, version.agent_id)
    if agent is None or agent.deleted_at is not None:
        raise _product_error("embedding publication agent was not found", "owner_not_found")
    if group.course_id != course.id or agent.group_id != group.id or version.agent_id != agent.id:
        raise _product_error("embedding publication owner does not match", "owner_mismatch")
    if expected_revision is not None and version.revision != expected_revision:
        raise _product_error("embedding publication revision is stale", "revision_stale")
    if version.state != "draft":
        raise _product_error("only a draft AgentVersion can be published", "version_immutable")
    return course, group, agent, version


def _enabled_documents(
    db: Session,
    *,
    version: AgentVersion,
    group: Group,
    data_root: Path,
) -> tuple[SnapshotBuildInputDocument, ...]:
    relations = list(
        db.scalars(
            select(AgentVersionDocument)
            .where(AgentVersionDocument.agent_version_id == version.id)
            .order_by(AgentVersionDocument.order_index, AgentVersionDocument.document_id)
        ).all()
    )
    enabled = [relation for relation in relations if relation.enabled]
    if not enabled or [row.order_index for row in enabled] != list(range(len(enabled))):
        raise _product_error("the enabled document order is incomplete", "document_owner_drift")

    documents: list[SnapshotBuildInputDocument] = []
    for order, relation in enumerate(enabled):
        document = db.get(KnowledgeDocument, relation.document_id)
        if (
            document is None
            or document.group_id != group.id
            or document.workspace_state != "active"
            or document.index_status != "ready"
            or document.stored_file is None
            or document.stored_file.state != "active"
        ):
            raise _product_error("an enabled document is not publishable", "document_owner_drift")
        try:
            source_bytes = document_file_content(data_root, document)
        except Exception as exc:
            raise _product_error(
                "an enabled document could not be read", "document_read_failed"
            ) from exc
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        if source_hash != document.stored_file.sha256:
            raise _product_error("an enabled document changed", "document_integrity_mismatch")
        try:
            normalized = normalize_markdown(document.source_filename, source_bytes)
        except Exception as exc:
            raise _product_error(
                "an enabled document is not valid Markdown", "document_invalid"
            ) from exc
        if (
            normalized.char_count != document.char_count
            or normalized.content_hash != document.content_hash
        ):
            raise _product_error(
                "an enabled document content changed", "document_integrity_mismatch"
            )
        documents.append(
            SnapshotBuildInputDocument(
                document_id=document.id,
                source_filename=document.source_filename,
                text=normalized.normalized,
                order_index=order,
                source_sha256=source_hash,
            )
        )
    if any(len(document.text) > MAX_RAG_CHARS for document in documents):
        raise _product_error("a document exceeds the publication limit", "rag_over_limit")
    return tuple(documents)


def _scan_document_outbound_texts(documents: tuple[SnapshotBuildInputDocument, ...]) -> None:
    """Require text values before export hashing; do not restrict authored content."""

    try:
        scan_real_embedding_texts(
            (document.text for document in documents),
            field_name="document chunk source",
        )
    except OutboundEmbeddingDataError as exc:
        raise _product_error(
            "a document contains data forbidden for real Embedding",
            exc.code,
        ) from exc


def _deterministic_ids(
    *,
    agent_version_id: str,
    revision: int,
    persona_spec_hash: str,
    documents: tuple[SnapshotBuildInputDocument, ...],
) -> tuple[str, str]:
    source = canonical_json_bytes(
        {
            "agent_version_id": agent_version_id,
            "revision": revision,
            "persona_spec_hash": persona_spec_hash,
            "identity": {
                "provider": REAL_EMBEDDING_PROVIDER,
                "model_key": REAL_EMBEDDING_MODEL,
                "region": REAL_EMBEDDING_REGION,
                "dimension": REAL_EMBEDDING_DIMENSION,
                "policy_version": REAL_EMBEDDING_POLICY_VERSION,
            },
            "documents": [
                {
                    "document_id": document.document_id,
                    "order_index": document.order_index,
                    "source_sha256": document.source_sha256,
                }
                for document in documents
            ],
        }
    )
    source_hash = sha256_hex(source)
    snapshot_id = str(uuid5(NAMESPACE_URL, "maya:real-snapshot-v1:" + source_hash))
    build_id = str(uuid5(NAMESPACE_URL, "maya:real-build-v1:" + snapshot_id + ":" + source_hash))
    return snapshot_id, build_id


def prepare_real_snapshot_build(
    database: Database | Engine | Session,
    data_root: Path | str,
    *,
    course_id: str,
    group_id: str,
    agent_version_id: str,
    expected_revision: int | None = None,
) -> SnapshotBuildV1:
    """Freeze current enabled source bytes into a deterministic real build."""

    root = Path(data_root)
    with _session_for(database) as db:
        _course, group, _agent, version = _owner_rows(
            db,
            course_id=course_id,
            group_id=group_id,
            agent_version_id=agent_version_id,
            expected_revision=expected_revision,
        )
        if not version.agent_md.strip() or len(version.agent_md) > 12_000:
            raise _product_error("Agent Markdown is empty or too long", "agent_md_invalid")
        documents = _enabled_documents(db, version=version, group=group, data_root=root)
        _scan_document_outbound_texts(documents)
        snapshot_id, build_id = _deterministic_ids(
            agent_version_id=version.id,
            revision=version.revision,
            persona_spec_hash=markdown_hash(version.agent_md),
            documents=documents,
        )
        return prepare_snapshot_build(
            agent_version_id=version.id,
            knowledge_snapshot_id=snapshot_id,
            draft_revision=version.revision,
            persona_spec_hash=markdown_hash(version.agent_md),
            documents=documents,
            build_id=build_id,
            embedding_provider=REAL_EMBEDDING_PROVIDER,
            embedding_model_key=REAL_EMBEDDING_MODEL,
            embedding_region=REAL_EMBEDDING_REGION,
            embedding_dimension=REAL_EMBEDDING_DIMENSION,
            embedding_policy_version=REAL_EMBEDDING_POLICY_VERSION,
        )


def _ordered_value_hash(values: list[str]) -> str:
    return sha256_hex(canonical_json_bytes(values))


def _ensure_policy_snapshot(
    repository: ProviderRepository,
    database: Database | Engine | Session,
    policy: ProviderPolicySnapshotV1,
) -> str:
    policy.validate()
    row = _policy_row(database, policy.policy_hash)
    if row is None or str(row["policy_hash"]) != policy.policy_hash:
        raise _product_error("provider policy is not a verified snapshot", "policy_drift")
    if str(row["policy_id"]) != policy.policy_id or str(row["region"]) != policy.region:
        raise _product_error("provider policy changed", "policy_drift")
    stored = repository.get_policy_snapshot(str(row["id"]))
    if stored != policy:
        raise _product_error("provider policy contents changed", "policy_drift")
    return str(row["id"])


def _policy_row(
    database: Database | Engine | Session,
    policy_hash: str,
) -> Any | None:
    table = ProviderPolicySnapshot.__table__
    with _engine_for(database).connect() as connection:
        return (
            connection.execute(select(table).where(table.c.policy_hash == policy_hash))
            .mappings()
            .first()
        )


def _manifest_row(
    database: Database | Engine | Session,
    manifest_hash: str,
) -> Any | None:
    table = ProviderExportManifest.__table__
    with _engine_for(database).connect() as connection:
        return (
            connection.execute(select(table).where(table.c.manifest_hash == manifest_hash))
            .mappings()
            .first()
        )


def _confirmation_row(
    database: Database | Engine | Session,
    manifest_hash: str,
) -> Any | None:
    table = ProviderExportConfirmation.__table__
    with _engine_for(database).connect() as connection:
        return (
            connection.execute(select(table).where(table.c.manifest_hash == manifest_hash))
            .mappings()
            .first()
        )


def _assert_manifest_row_owner(
    row: Any,
    *,
    policy_snapshot_id: str,
    course_id: str,
    group_id: str,
    agent_version_id: str,
) -> Any:
    if row is None:
        raise _product_error("provider export manifest is missing", "manifest_missing")
    if (
        str(row["policy_snapshot_id"]) != policy_snapshot_id
        or str(row["course_id"]) != course_id
        or str(row["group_id"]) != group_id
        or str(row["agent_version_id"]) != agent_version_id
    ):
        raise _product_error("provider export manifest owner changed", "manifest_owner_drift")
    return row


def ensure_real_embedding_export_manifest(
    database: Database | Engine | Session,
    build: SnapshotBuildV1,
    *,
    course_id: str,
    group_id: str,
    agent_version_id: str,
    policy: ProviderPolicySnapshotV1,
) -> ExportManifestV1:
    """Create or reread one exact owner-bound embedding export manifest."""

    if build.agent_version_id != agent_version_id:
        raise _product_error("build owner does not match manifest owner", "owner_mismatch")
    identity = build.embedding_identity
    if (
        identity.provider != REAL_EMBEDDING_PROVIDER
        or identity.model_key != REAL_EMBEDDING_MODEL
        or identity.region != REAL_EMBEDDING_REGION
        or identity.dimension != REAL_EMBEDDING_DIMENSION
        or identity.policy_version != REAL_EMBEDDING_POLICY_VERSION
    ):
        raise _product_error("build is not the fixed real embedding identity", "identity_mismatch")
    try:
        scan_real_embedding_texts(
            (chunk.text for chunk in build.chunks),
            field_name="document chunk source",
        )
    except OutboundEmbeddingDataError as exc:
        raise _product_error(
            "a document contains data forbidden for real Embedding",
            exc.code,
        ) from exc
    with _session_for(database) as db:
        _owner_rows(
            db,
            course_id=course_id,
            group_id=group_id,
            agent_version_id=agent_version_id,
            expected_revision=build.draft_revision,
        )
    repository = ProviderRepository(database)
    policy_snapshot_id = _ensure_policy_snapshot(repository, database, policy)
    fields = (
        ExportFieldV1(
            "current_evidence_excerpt",
            _ordered_value_hash([chunk.text for chunk in build.chunks]),
        ),
        ExportFieldV1(
            "opaque_local_id",
            _ordered_value_hash([chunk.chunk_id for chunk in build.chunks]),
        ),
    )
    manifest = ExportManifestV1(
        scope_id=build.build_id,
        provider_operation="embedding",
        model_key=REAL_EMBEDDING_MODEL,
        policy_hash=policy.policy_hash,
        build_manifest_hash=build.manifest_hash,
        persona_spec_hash=build.persona_spec_hash,
        fields=fields,
    )
    manifest_id = str(uuid5(NAMESPACE_URL, "maya:provider-export-v1:" + manifest.manifest_hash))
    try:
        repository.save_export_manifest(
            manifest,
            policy_snapshot_id=policy_snapshot_id,
            manifest_id=manifest_id,
            course_id=course_id,
            group_id=group_id,
            agent_version_id=agent_version_id,
        )
    except Exception:
        row = _manifest_row(database, manifest.manifest_hash)
        row = _assert_manifest_row_owner(
            row,
            policy_snapshot_id=policy_snapshot_id,
            course_id=course_id,
            group_id=group_id,
            agent_version_id=agent_version_id,
        )
        if str(row["id"]) != manifest_id:
            raise _product_error(
                "provider export manifest identity changed", "manifest_drift"
            ) from None
    row = _manifest_row(database, manifest.manifest_hash)
    row = _assert_manifest_row_owner(
        row,
        policy_snapshot_id=policy_snapshot_id,
        course_id=course_id,
        group_id=group_id,
        agent_version_id=agent_version_id,
    )
    if str(row["id"]) != manifest_id:
        raise _product_error("provider export manifest identity changed", "manifest_drift")
    stored = repository.get_export_manifest(manifest.manifest_hash)
    if stored != manifest:
        raise _product_error("provider export manifest contents changed", "manifest_drift")
    return stored


def require_exact_confirmation(
    database: Database | Engine | Session,
    manifest: ExportManifestV1,
    policy: ProviderPolicySnapshotV1,
    *,
    confirmation: ExportConfirmationV1 | None = None,
    course_id: str | None = None,
    group_id: str | None = None,
    agent_version_id: str | None = None,
) -> ExportConfirmationV1:
    """Require the durable confirmation for exactly this manifest and policy."""

    try:
        policy.validate()
        manifest.validate()
    except Exception as exc:
        raise _product_error("provider policy or manifest is invalid", "policy_drift") from exc
    if manifest.policy_hash != policy.policy_hash:
        raise _product_error("provider policy and manifest differ", "policy_drift")
    policy_row = _policy_row(database, policy.policy_hash)
    if policy_row is None or str(policy_row["policy_hash"]) != policy.policy_hash:
        raise _product_error("provider policy is not a verified snapshot", "policy_drift")
    manifest_row = _manifest_row(database, manifest.manifest_hash)
    if manifest_row is None or str(manifest_row["manifest_hash"]) != manifest.manifest_hash:
        raise _product_error(
            "exact provider confirmation is required",
            "provider_confirmation_required",
        )
    if str(manifest_row["policy_snapshot_id"]) != str(policy_row["id"]):
        raise _product_error("provider manifest policy changed", "policy_drift")
    if course_id is not None or group_id is not None or agent_version_id is not None:
        if not course_id or not group_id or not agent_version_id:
            raise _product_error("provider manifest owner is incomplete", "manifest_owner_drift")
        _assert_manifest_row_owner(
            manifest_row,
            policy_snapshot_id=str(manifest_row["policy_snapshot_id"]),
            course_id=course_id,
            group_id=group_id,
            agent_version_id=agent_version_id,
        )
    row = _confirmation_row(database, manifest.manifest_hash)
    if row is None:
        raise _product_error(
            "exact provider confirmation is required",
            "provider_confirmation_required",
        )
    persisted = ExportConfirmationV1(
        manifest_hash=str(row["manifest_hash"]),
        policy_hash=str(row["policy_hash"]),
        confirmed_at=str(row["confirmed_at"]),
        confirmation_revision=int(row["confirmation_revision"]),
    )
    if (
        persisted.manifest_hash != manifest.manifest_hash
        or persisted.policy_hash != policy.policy_hash
        or persisted.confirmation_revision != manifest.operation_revision
        or confirmation is not None
        and confirmation != persisted
    ):
        raise _product_error("provider confirmation is stale", "provider_confirmation_stale")
    if str(row["policy_snapshot_id"]) != str(manifest_row["policy_snapshot_id"]):
        raise _product_error("provider confirmation policy changed", "provider_confirmation_stale")
    return persisted


def _validate_policy_endpoint(policy: ProviderPolicySnapshotV1) -> None:
    try:
        parsed = urlsplit(policy.endpoint)
    except ValueError as exc:
        raise _product_error("provider endpoint is invalid", "provider_endpoint_invalid") from exc
    host = (parsed.hostname or "").lower()
    suffix = ".cn-beijing.maas.aliyuncs.com"
    workspace = host[: -len(suffix)] if host.endswith(suffix) else ""
    allowed = (
        bool(workspace)
        and "." not in workspace
        and all(char.isascii() and (char.isalnum() or char == "-") for char in workspace)
    )
    if (
        parsed.scheme.lower() != "https"
        or not allowed
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != DEFAULT_DASHSCOPE_EMBEDDING_ENDPOINT_PATH
    ):
        raise _product_error(
            "provider endpoint is not the fixed Beijing resource", "provider_endpoint_invalid"
        )


def _validate_real_provider(
    provider: EmbeddingProvider,
    policy: ProviderPolicySnapshotV1,
) -> None:
    for field, expected in (
        ("model_key", REAL_EMBEDDING_MODEL),
        ("dimension", REAL_EMBEDDING_DIMENSION),
        ("provider", REAL_EMBEDDING_PROVIDER),
        ("region", REAL_EMBEDDING_REGION),
        ("policy_version", REAL_EMBEDDING_POLICY_VERSION),
    ):
        actual = getattr(provider, field, None)
        if actual is not None and actual != expected:
            raise _product_error("embedding provider identity changed", "provider_identity_drift")
    config = getattr(provider, "config", None)
    if isinstance(config, DashScopeEmbeddingConfig):
        if (
            config.model_key != REAL_EMBEDDING_MODEL
            or config.dimension != REAL_EMBEDDING_DIMENSION
            or config.region != REAL_EMBEDDING_REGION
            or config.policy_version != REAL_EMBEDDING_POLICY_VERSION
        ):
            raise _product_error(
                "embedding provider configuration changed", "provider_identity_drift"
            )
        try:
            resolved_endpoint = config.resolved_endpoint
        except Exception as exc:
            raise _product_error(
                "embedding provider endpoint is invalid", "provider_endpoint_invalid"
            ) from exc
        if policy.endpoint != resolved_endpoint:
            raise _product_error(
                "provider policy endpoint does not match the configured resource",
                "provider_endpoint_invalid",
            )
    else:
        provider_endpoint = getattr(provider, "endpoint", None)
        if provider_endpoint is not None and provider_endpoint != policy.endpoint:
            raise _product_error(
                "provider policy endpoint does not match the provider resource",
                "provider_endpoint_invalid",
            )
    _validate_policy_endpoint(policy)


def _run_confirmed(
    database: Database | Engine | Session,
    db: Session,
    data_root: Path,
    *,
    course_id: str,
    group_id: str,
    agent_version_id: str,
    policy: ProviderPolicySnapshotV1,
    manifest: ExportManifestV1 | None,
    confirmation: ExportConfirmationV1 | None,
    build: SnapshotBuildV1 | None,
    provider: EmbeddingProvider | None,
    config: DashScopeEmbeddingConfig | None,
    transport: EmbeddingTransport | None,
    expected_revision: int | None,
    timeout_seconds: float,
    price_cny_per_million: Decimal | float | int | str = DEFAULT_EMBEDDING_PRICE_CNY_PER_MILLION,
    cost_cap_cny: Decimal | float | int | str = DEFAULT_EMBEDDING_COST_CAP_CNY,
    idempotency_record_id: str | None = None,
    claim_token: str | None = None,
    acceptance_run_id: str | None = None,
    call_no: int | None = None,
    target_agent_id: str | None = None,
    target_version_id: str | None = None,
) -> SnapshotEmbeddingRunV1:
    fresh_build = prepare_real_snapshot_build(
        db,
        data_root,
        course_id=course_id,
        group_id=group_id,
        agent_version_id=agent_version_id,
        expected_revision=expected_revision,
    )
    selected_build = fresh_build if build is None else build
    if selected_build.manifest_hash != fresh_build.manifest_hash:
        raise _product_error("current source or owner drifted", "snapshot_build_drift")
    try:
        scan_real_embedding_texts(
            (chunk.text for chunk in selected_build.chunks),
            field_name="document chunk source",
        )
    except OutboundEmbeddingDataError as exc:
        raise _product_error(
            "a document contains data forbidden for real Embedding",
            exc.code,
        ) from exc
    selected_manifest = ensure_real_embedding_export_manifest(
        database,
        selected_build,
        course_id=course_id,
        group_id=group_id,
        agent_version_id=agent_version_id,
        policy=policy,
    )
    if manifest is not None and manifest != selected_manifest:
        raise _product_error("provider export manifest changed", "manifest_drift")
    exact_confirmation = require_exact_confirmation(
        database,
        selected_manifest,
        policy,
        confirmation=confirmation,
        course_id=course_id,
        group_id=group_id,
        agent_version_id=agent_version_id,
    )
    del exact_confirmation
    if acceptance_run_id is not None:
        if (
            call_no != 1
            or target_agent_id is None
            or target_version_id is None
            or target_version_id != agent_version_id
        ):
            raise _product_error(
                "Snapshot acceptance binding is incomplete",
                "acceptance_binding_invalid",
            )
        # Call1 is deliberately a one-shot Snapshot proof.  A multi-batch
        # build must fail before the bound operation is created, reserved or
        # sent so it cannot consume a partially bound Demo run.
        plan = plan_embedding_batches(
            selected_build,
            price_cny_per_million=price_cny_per_million,
            cost_cap_cny=cost_cap_cny,
        )
        if len(plan.batches) != 1:
            raise _product_error(
                "Snapshot acceptance binding requires one batch",
                "acceptance_binding_multibatch",
            )
    if provider is not None and transport is not None:
        raise _product_error("provide a provider or transport, not both", "provider_input_invalid")
    if (idempotency_record_id is None) != (claim_token is None):
        raise _product_error(
            "idempotency record and claim token must be supplied together",
            "idempotency_claim_invalid",
        )
    selected_provider = provider
    if selected_provider is None:
        if config is None or transport is None:
            raise _product_error(
                "an injected provider or transport is required",
                "provider_input_required",
            )
        try:
            selected_provider = DashScopeEmbeddingAdapter(
                config,
                transport,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            raise _product_error(
                "embedding provider configuration is invalid", "provider_identity_drift"
            ) from exc
    _validate_real_provider(selected_provider, policy)
    _course, _group, agent, version = _owner_rows(
        db,
        course_id=course_id,
        group_id=group_id,
        agent_version_id=agent_version_id,
        expected_revision=selected_build.draft_revision,
    )
    control = SqlAlchemyEmbeddingControlAdapter(
        database,
        policy_hash=policy.policy_hash,
        export_manifest_hash=selected_manifest.manifest_hash,
        build_manifest_hash=selected_build.manifest_hash,
        model_key=REAL_EMBEDDING_MODEL,
        acceptance_run_id=acceptance_run_id,
        call_no=call_no,
        target_agent_id=target_agent_id,
        target_version_id=target_version_id,
    )
    stage_store = SqlAlchemyEmbeddingStageStore(database)
    publisher = SqlAlchemySnapshotPublicationStore(
        db,
        data_root=data_root,
        version=version,
        agent=agent,
        expected_revision=selected_build.draft_revision,
        idempotency_record_id=idempotency_record_id,
        claim_token=claim_token,
    )
    runtime = SnapshotEmbeddingRuntime(
        control=control,
        provider=selected_provider,
        publisher=publisher,
        stage_store=stage_store,
        price_cny_per_million=price_cny_per_million,
        cost_cap_cny=cost_cap_cny,
        provider_operation="embedding",
    )

    def current_verifier(_: SnapshotBuildV1) -> bool:
        current = prepare_real_snapshot_build(
            db,
            data_root,
            course_id=course_id,
            group_id=group_id,
            agent_version_id=agent_version_id,
            expected_revision=selected_build.draft_revision,
        )
        return current.manifest_hash == selected_build.manifest_hash

    # A worker may be restarted after one or more accepted stages were
    # committed.  Never call ``run`` in that case: it would construct a new
    # attempt and could resend a supplier-accepted batch.  The pure runtime's
    # complete-stage recovery path publishes without touching the provider;
    # a partial/malformed set remains a terminal recovery item for the worker.
    raw_operations = control.repository.operations(scope_id=selected_build.build_id)
    existing_operations = tuple(
        operation for raw in raw_operations if (operation := control.get(raw.id)) is not None
    )
    try:
        existing_stages = stage_store.values(build_id=selected_build.build_id)
    except Exception:
        existing_stages = None
    if acceptance_run_id is not None and (existing_operations or existing_stages):
        raise _product_error(
            "Snapshot acceptance run already has provider history",
            "acceptance_binding_invalid",
        )
    if existing_operations or existing_stages:
        plan = plan_embedding_batches(
            selected_build,
            price_cny_per_million=price_cny_per_million,
            cost_cap_cny=cost_cap_cny,
        )
        expected_costs = {
            batch.batch_index: (batch.total_tokens * float(str(price_cny_per_million)) / 1_000_000)
            for batch in plan.batches
        }
        normalized_operations: list[EmbeddingOperationV1] = []
        for operation in existing_operations:
            expected_cost = expected_costs.get(operation.batch_index)
            if expected_cost is not None and abs(operation.max_cost_cny - expected_cost) > (
                5e-7 + 1e-12
            ):
                raise _product_error(
                    "accepted embedding budget changed",
                    "embedding_budget_drift",
                )
            normalized_operations.append(
                replace(
                    operation,
                    max_cost_cny=(
                        expected_cost if expected_cost is not None else operation.max_cost_cny
                    ),
                )
            )
        accepted_operations = tuple(
            operation for operation in normalized_operations if operation.state == "accepted"
        )
        if len(accepted_operations) == len(plan.batches):
            return runtime.resume_from_stages(
                selected_build,
                operations=accepted_operations,
                stages=existing_stages,
                scope_id=selected_build.build_id,
            )
        return runtime.continue_from_stages(
            selected_build,
            operations=tuple(normalized_operations),
            stages=existing_stages,
            scope_id=selected_build.build_id,
            current_build=selected_build,
            current_build_verifier=current_verifier,
        )

    try:
        return runtime.run(
            selected_build,
            scope_id=selected_build.build_id,
            current_build=selected_build,
            current_build_verifier=current_verifier,
        )
    except Exception as exc:
        # The bound repository seam rejects all run/manifest/target drift
        # before creating a prepared operation.  Convert only its safe,
        # product-facing binding errors here; provider/runtime failures keep
        # their existing behavior and result handling.
        if acceptance_run_id is not None:
            raise _product_error(str(exc), "acceptance_binding_invalid") from exc
        raise


def run_confirmed_real_embedding_publication(
    database: Database | Engine | Session,
    *,
    data_root: Path | str,
    course_id: str,
    group_id: str,
    agent_version_id: str,
    policy: ProviderPolicySnapshotV1,
    manifest: ExportManifestV1 | None = None,
    confirmation: ExportConfirmationV1 | None = None,
    build: SnapshotBuildV1 | None = None,
    provider: EmbeddingProvider | None = None,
    config: DashScopeEmbeddingConfig | None = None,
    transport: EmbeddingTransport | None = None,
    expected_revision: int | None = None,
    timeout_seconds: float = 30.0,
    price_cny_per_million: Decimal | float | int | str = DEFAULT_EMBEDDING_PRICE_CNY_PER_MILLION,
    cost_cap_cny: Decimal | float | int | str = DEFAULT_EMBEDDING_COST_CAP_CNY,
    idempotency_record_id: str | None = None,
    claim_token: str | None = None,
    acceptance_run_id: str | None = None,
    call_no: int | None = None,
    target_agent_id: str | None = None,
    target_version_id: str | None = None,
) -> SnapshotEmbeddingRunV1:
    """Run one confirmed real publication using only injected provider I/O."""

    root = Path(data_root)
    if isinstance(database, Session):
        return _run_confirmed(
            database,
            database,
            root,
            course_id=course_id,
            group_id=group_id,
            agent_version_id=agent_version_id,
            policy=policy,
            manifest=manifest,
            confirmation=confirmation,
            build=build,
            provider=provider,
            config=config,
            transport=transport,
            expected_revision=expected_revision,
            timeout_seconds=timeout_seconds,
            price_cny_per_million=price_cny_per_million,
            cost_cap_cny=cost_cap_cny,
            idempotency_record_id=idempotency_record_id,
            claim_token=claim_token,
            acceptance_run_id=acceptance_run_id,
            call_no=call_no,
            target_agent_id=target_agent_id,
            target_version_id=target_version_id,
        )
    with _session_for(database) as db:
        return _run_confirmed(
            database,
            db,
            root,
            course_id=course_id,
            group_id=group_id,
            agent_version_id=agent_version_id,
            policy=policy,
            manifest=manifest,
            confirmation=confirmation,
            build=build,
            provider=provider,
            config=config,
            transport=transport,
            expected_revision=expected_revision,
            timeout_seconds=timeout_seconds,
            price_cny_per_million=price_cny_per_million,
            cost_cap_cny=cost_cap_cny,
            idempotency_record_id=idempotency_record_id,
            claim_token=claim_token,
            acceptance_run_id=acceptance_run_id,
            call_no=call_no,
            target_agent_id=target_agent_id,
            target_version_id=target_version_id,
        )


# Descriptive aliases for the main window and focused tests.
build_real_snapshot = prepare_real_snapshot_build
prepare_real_embedding_snapshot_build = prepare_real_snapshot_build
ensure_embedding_export_manifest = ensure_real_embedding_export_manifest
ensure_real_export_manifest = ensure_real_embedding_export_manifest
require_provider_confirmation = require_exact_confirmation
publish_confirmed_real_embedding = run_confirmed_real_embedding_publication


__all__ = [
    "EmbeddingProductPublicationError",
    "ExportManifestContext",
    "ProductPublicationError",
    "RealSnapshotBuildContext",
    "build_real_snapshot",
    "ensure_embedding_export_manifest",
    "ensure_real_embedding_export_manifest",
    "ensure_real_export_manifest",
    "prepare_real_embedding_snapshot_build",
    "prepare_real_snapshot_build",
    "publish_confirmed_real_embedding",
    "require_exact_confirmation",
    "require_provider_confirmation",
    "run_confirmed_real_embedding_publication",
]
