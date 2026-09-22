"""Exact owner-bound export manifests for real turn-query embeddings."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.db import Database
from app.core.models import (
    Agent,
    AgentVersion,
    Group,
    KnowledgeSnapshot,
    ProviderPolicySnapshot,
)
from app.modules.agents.markdown import markdown_hash
from app.modules.knowledge.vector import EmbeddingIdentityV1
from app.providers.control import (
    ExportFieldV1,
    ExportManifestV1,
    ProviderPolicySnapshotV1,
    canonical_json_bytes,
    sha256_hex,
)
from app.providers.control_repository import ProviderRepository

from .outbound_guard import OutboundEmbeddingDataError, scan_real_embedding_texts
from .query_embedding import QUERY_PROVIDER_OPERATION, query_hash
from .snapshot_build import REAL_EMBEDDING_IDENTITY

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_QUERY_KINDS = frozenset(
    {"viewpoint", "pending_question", "rebuttal", "updated_position", "context", "barrage"}
)


class QueryManifestError(RuntimeError):
    """A dynamic turn query cannot be disclosed or confirmed safely."""

    def __init__(self, message: str, *, code: str = "embedding_query_manifest_invalid") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class QueryExportPlanV1:
    scope_id: str
    turn_id: str
    snapshot_id: str
    identity: EmbeddingIdentityV1
    transcript_hash: str
    persona_spec_hash: str
    query_kinds: tuple[str, ...]
    query_texts: tuple[str, ...]
    query_hashes: tuple[str, ...]
    build_manifest_hash: str
    manifest: ExportManifestV1


def _engine(source: Database | Engine | Session) -> Engine:
    if isinstance(source, Database):
        return source.engine
    if isinstance(source, Engine):
        return source
    if isinstance(source, Session):
        bind = source.get_bind()
        if isinstance(bind, Engine):
            return bind
    raise TypeError("query manifest requires Database, Engine or Session")


def _policy_row_id(source: Database | Engine | Session, policy_hash: str) -> str:
    table = ProviderPolicySnapshot.__table__
    with _engine(source).connect() as connection:
        row = (
            connection.execute(
                select(table.c.id, table.c.policy_hash).where(table.c.policy_hash == policy_hash)
            )
            .mappings()
            .first()
        )
    if row is None or str(row["policy_hash"]) != policy_hash:
        raise QueryManifestError(
            "the configured Provider policy is not persisted",
            code="provider_preflight_blocked",
        )
    return str(row["id"])


def _assert_snapshot_owner(
    db: Session,
    *,
    course_id: str,
    group_id: str,
    agent_version_id: str,
    snapshot_id: str,
    persona_spec_hash: str,
    identity: EmbeddingIdentityV1,
) -> None:
    version = db.get(AgentVersion, agent_version_id)
    snapshot = db.get(KnowledgeSnapshot, snapshot_id)
    if version is None or snapshot is None:
        raise QueryManifestError("the frozen query Snapshot owner is unavailable")
    agent = db.get(Agent, version.agent_id)
    group = db.get(Group, group_id)
    if (
        agent is None
        or agent.deleted_at is not None
        or group is None
        or group.course_id != course_id
        or agent.group_id != group.id
        or version.agent_id != agent.id
        or version.state not in {"published", "superseded"}
        or str(version.knowledge_snapshot_id or "") != snapshot.id
        or snapshot.agent_version_id != version.id
        or persona_spec_hash not in {markdown_hash(version.agent_md), version.persona_spec_hash}
    ):
        raise QueryManifestError("the frozen query Snapshot owner changed")
    persisted = EmbeddingIdentityV1(
        provider=snapshot.embedding_provider,
        model_key=snapshot.embedding_model_key,
        region=snapshot.embedding_region,
        dimension=snapshot.embedding_dimension,
        policy_version=snapshot.embedding_policy_version,
    )
    if persisted != identity:
        raise QueryManifestError(
            "the frozen query Snapshot identity changed",
            code="embedding_query_identity_mismatch",
        )


def ensure_real_query_export_manifest(
    database: Database | Engine | Session,
    *,
    db: Session,
    scope_id: str,
    turn_id: str,
    course_id: str,
    group_id: str,
    agent_version_id: str,
    snapshot_id: str,
    identity: EmbeddingIdentityV1,
    transcript_hash: str,
    persona_spec_hash: str,
    subqueries: Sequence[tuple[str, str]],
    policy: ProviderPolicySnapshotV1,
) -> QueryExportPlanV1:
    """Ensure one exact query-set manifest without selecting a Provider."""

    real_identity = EmbeddingIdentityV1(
        provider=REAL_EMBEDDING_IDENTITY.provider,
        model_key=REAL_EMBEDDING_IDENTITY.model_key,
        region=REAL_EMBEDDING_IDENTITY.region,
        dimension=REAL_EMBEDDING_IDENTITY.dimension,
        policy_version=REAL_EMBEDDING_IDENTITY.policy_version,
    )
    if identity != real_identity:
        raise QueryManifestError(
            "query manifest requires the fixed real Snapshot identity",
            code="embedding_query_identity_mismatch",
        )
    if not _SHA256_RE.fullmatch(transcript_hash) or not _SHA256_RE.fullmatch(persona_spec_hash):
        raise QueryManifestError("query transcript or Persona hash is invalid")
    if not 1 <= len(subqueries) <= 3:
        raise QueryManifestError("a query manifest requires one to three subqueries")
    kinds: list[str] = []
    texts: list[str] = []
    hashes: list[str] = []
    for kind, raw_text in subqueries:
        text = raw_text.strip()
        if kind not in _QUERY_KINDS or not text or "\x00" in text:
            raise QueryManifestError("query manifest subquery is invalid")
        value_hash = query_hash(text)
        if value_hash in hashes:
            continue
        kinds.append(kind)
        texts.append(text)
        hashes.append(value_hash)
    if not texts:
        raise QueryManifestError("query manifest has no unique subquery")
    try:
        scan_real_embedding_texts(texts, field_name="turn query")
    except OutboundEmbeddingDataError as exc:
        raise QueryManifestError(
            "a turn query contains data forbidden for real Embedding",
            code=exc.code,
        ) from exc
    _assert_snapshot_owner(
        db,
        course_id=course_id,
        group_id=group_id,
        agent_version_id=agent_version_id,
        snapshot_id=snapshot_id,
        persona_spec_hash=persona_spec_hash,
        identity=identity,
    )
    policy.validate()
    repository = ProviderRepository(database)
    persisted_policy = repository.get_policy_snapshot(policy.policy_hash)
    if persisted_policy != policy:
        raise QueryManifestError(
            "the configured Provider policy changed",
            code="provider_preflight_blocked",
        )
    policy_row_id = _policy_row_id(database, policy.policy_hash)
    build_manifest_hash = sha256_hex(
        canonical_json_bytes(
            {
                "version": "embedding-query-export-v1",
                "scope_id": scope_id,
                "turn_id": turn_id,
                "snapshot_id": snapshot_id,
                "identity": {
                    "provider": identity.provider,
                    "model_key": identity.model_key,
                    "region": identity.region,
                    "dimension": identity.dimension,
                    "policy_version": identity.policy_version,
                },
                "transcript_hash": transcript_hash,
                "persona_spec_hash": persona_spec_hash,
                "subqueries": [
                    {"kind": kind, "text": text, "query_hash": value_hash}
                    for kind, text, value_hash in zip(kinds, texts, hashes, strict=True)
                ],
            }
        )
    )
    manifest = ExportManifestV1(
        scope_id=scope_id,
        provider_operation=QUERY_PROVIDER_OPERATION,
        model_key=identity.model_key,
        policy_hash=policy.policy_hash,
        build_manifest_hash=build_manifest_hash,
        persona_spec_hash=persona_spec_hash,
        fields=(
            ExportFieldV1(
                "current_evidence_excerpt",
                sha256_hex(canonical_json_bytes(texts)),
            ),
            *(
                (
                    ExportFieldV1(
                        "anonymous_classroom_barrage",
                        sha256_hex(
                            canonical_json_bytes(
                                [
                                    text
                                    for kind, text in zip(kinds, texts, strict=True)
                                    if kind == "barrage"
                                ]
                            )
                        ),
                    ),
                )
                if "barrage" in kinds
                else ()
            ),
        ),
    )
    repository.ensure_export_manifest(
        manifest,
        policy_snapshot_id=policy_row_id,
        manifest_id=str(uuid5(NAMESPACE_URL, "maya:query-export-v1:" + manifest.manifest_hash)),
        course_id=course_id,
        group_id=group_id,
        agent_version_id=agent_version_id,
    )
    return QueryExportPlanV1(
        scope_id=scope_id,
        turn_id=turn_id,
        snapshot_id=snapshot_id,
        identity=identity,
        transcript_hash=transcript_hash,
        persona_spec_hash=persona_spec_hash,
        query_kinds=tuple(kinds),
        query_texts=tuple(texts),
        query_hashes=tuple(hashes),
        build_manifest_hash=build_manifest_hash,
        manifest=manifest,
    )


__all__ = [
    "QueryExportPlanV1",
    "QueryManifestError",
    "ensure_real_query_export_manifest",
]
