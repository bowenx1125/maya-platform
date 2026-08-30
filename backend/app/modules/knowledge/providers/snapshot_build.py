"""Immutable, pre-provider SnapshotBuildV1 values.

``SnapshotBuildV1`` is a private candidate.  It is created before an
embedding request and carries the exact source/chunk manifest that a caller
must later use for one new immutable KnowledgeSnapshot.  This module performs
no database or filesystem writes and never mutates an existing snapshot.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from app.modules.knowledge.markdown import MarkdownDocument, chunk_markdown, normalize_markdown

DEFAULT_CHUNKING_VERSION = "markdown-heading-paragraph-v1"

# Embedding identity is deliberately closed.  In particular, the Mock and
# real resources do not share a model name with a dimension-based switch: a
# persisted build must say which provider resource produced its vectors.
MOCK_EMBEDDING_PROVIDER = "mock"
MOCK_EMBEDDING_MODEL = "mock-sha256-v1"
MOCK_EMBEDDING_MODEL_KEY = MOCK_EMBEDDING_MODEL
MOCK_EMBEDDING_REGION = "local"
MOCK_EMBEDDING_DIMENSION = 256
MOCK_EMBEDDING_POLICY_VERSION = "w4-mock-v1"

REAL_EMBEDDING_MODEL = "text-embedding-v4"
REAL_EMBEDDING_MODEL_KEY = REAL_EMBEDDING_MODEL
REAL_EMBEDDING_DIMENSION = 1024
REAL_EMBEDDING_REGION = "cn-beijing"
REAL_EMBEDDING_POLICY_VERSION = "w4-embed-v1"

REAL_EMBEDDING_PROVIDER = "dashscope"

# Historical aliases identify the pre-Wave-4 deterministic Mock format.  New
# code should use the explicit MOCK_* or REAL_* names above.
MOCK_EMBEDDING_KEY = MOCK_EMBEDDING_MODEL_KEY
FIXED_EMBEDDING_MODEL = MOCK_EMBEDDING_MODEL
FIXED_EMBEDDING_DIMENSION = MOCK_EMBEDDING_DIMENSION
SNAPSHOT_BUILD_VERSION = "snapshot-build-v1"


@dataclass(frozen=True, slots=True)
class EmbeddingIdentityV1:
    """The complete provider/model/region/dimension/policy identity."""

    provider: str
    model_key: str
    region: str
    dimension: int
    policy_version: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider, str)
            or not self.provider
            or not isinstance(self.model_key, str)
            or not self.model_key
            or not isinstance(self.region, str)
            or not self.region
            or not isinstance(self.policy_version, str)
            or not self.policy_version
            or isinstance(self.dimension, bool)
            or not isinstance(self.dimension, int)
            or self.dimension < 1
        ):
            raise ValueError("embedding identity is invalid")

    def as_record(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model_key": self.model_key,
            "region": self.region,
            "dimension": self.dimension,
            "policy_version": self.policy_version,
        }


MOCK_EMBEDDING_IDENTITY = EmbeddingIdentityV1(
    provider=MOCK_EMBEDDING_PROVIDER,
    model_key=MOCK_EMBEDDING_MODEL,
    region=MOCK_EMBEDDING_REGION,
    dimension=MOCK_EMBEDDING_DIMENSION,
    policy_version=MOCK_EMBEDDING_POLICY_VERSION,
)
REAL_EMBEDDING_IDENTITY = EmbeddingIdentityV1(
    provider=REAL_EMBEDDING_PROVIDER,
    model_key=REAL_EMBEDDING_MODEL,
    region=REAL_EMBEDDING_REGION,
    dimension=REAL_EMBEDDING_DIMENSION,
    policy_version=REAL_EMBEDDING_POLICY_VERSION,
)


def embedding_identity_for(
    model_key: str,
    dimension: int,
    *,
    provider: str | None = None,
    region: str | None = None,
    policy_version: str | None = None,
) -> EmbeddingIdentityV1 | None:
    """Resolve a supported identity and reject all cross-field combinations."""

    if model_key == MOCK_EMBEDDING_MODEL and dimension == MOCK_EMBEDDING_DIMENSION:
        candidate = MOCK_EMBEDDING_IDENTITY
    elif model_key == REAL_EMBEDDING_MODEL and dimension == REAL_EMBEDDING_DIMENSION:
        candidate = REAL_EMBEDDING_IDENTITY
    else:
        return None
    if (
        provider is not None
        and provider != candidate.provider
        or region is not None
        and region != candidate.region
        or policy_version is not None
        and policy_version != candidate.policy_version
    ):
        return None
    return candidate


def embedding_policy_version_for(model_key: str, dimension: int) -> str | None:
    """Return the frozen policy identity for an exact supported resource pair."""

    identity = embedding_identity_for(model_key, dimension)
    return identity.policy_version if identity is not None else None


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_FILENAME_RE = re.compile(r"^[^/\\\x00\x00-\x1f\x7f]+$")


class SnapshotBuildError(ValueError):
    """A candidate cannot satisfy the immutable build contract."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_filename(value: str) -> str:
    if not isinstance(value, str) or not value or not _SAFE_FILENAME_RE.fullmatch(value):
        raise SnapshotBuildError("invalid source filename")
    return value


def _safe_text(value: object, *, field: str = "text") -> str:
    if not isinstance(value, str) or not value.strip():
        raise SnapshotBuildError(f"{field} is required")
    if "\x00" in value:
        raise SnapshotBuildError(f"{field} contains NUL")
    return value


@dataclass(frozen=True, slots=True)
class SnapshotBuildChunkV1:
    """One frozen chunk in document order, without a vector result."""

    chunk_id: str
    document_id: str
    document_order: int
    chunk_index: int
    text: str
    start_offset: int
    end_offset: int
    text_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.chunk_id or not self.document_id:
            raise SnapshotBuildError("chunk and document identity are required")
        if self.document_order < 0 or self.chunk_index < 0:
            raise SnapshotBuildError("chunk order must be non-negative")
        text = _safe_text(self.text)
        if self.start_offset < 0 or self.end_offset < self.start_offset:
            raise SnapshotBuildError("invalid chunk offsets")
        if self.end_offset - self.start_offset != len(text):
            raise SnapshotBuildError("chunk offsets do not match text length")
        digest = _sha256(text.encode("utf-8"))
        if self.text_sha256 and self.text_sha256 != digest:
            raise SnapshotBuildError("chunk text hash mismatch")
        object.__setattr__(self, "text_sha256", digest)

    @property
    def content_hash(self) -> str:
        """Descriptive alias used by persistence adapters."""

        return self.text_sha256

    @property
    def chunk_hash(self) -> str:
        return self.text_sha256

    @property
    def id(self) -> str:
        return self.chunk_id

    def canonical(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_order": self.document_order,
            "chunk_index": self.chunk_index,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "text": self.text,
            "text_sha256": self.text_sha256,
        }


@dataclass(frozen=True, slots=True)
class SnapshotBuildInputDocument:
    """Normalized source input accepted by :func:`prepare_snapshot_build`."""

    document_id: str
    source_filename: str
    text: str
    order_index: int = 0
    source_sha256: str = ""

    @property
    def normalized_text(self) -> str:
        return self.text

    @classmethod
    def from_bytes(
        cls,
        *,
        document_id: str,
        source_filename: str,
        source_bytes: bytes,
        order_index: int = 0,
    ) -> SnapshotBuildInputDocument:
        """Normalize strict UTF-8 Markdown while retaining the raw hash."""

        try:
            document = normalize_markdown(source_filename, source_bytes)
        except ValueError as exc:
            raise SnapshotBuildError("source bytes are not valid Markdown") from exc
        return cls(
            document_id=document_id,
            source_filename=source_filename,
            text=document.normalized,
            order_index=order_index,
            source_sha256=document.source_sha256,
        )


@dataclass(frozen=True, slots=True)
class SnapshotBuildDocumentV1:
    """Frozen source metadata and chunks used by one build."""

    document_id: str
    source_filename: str
    order_index: int
    normalized_text: str
    source_sha256: str = ""
    content_sha256: str = ""
    chunks: tuple[SnapshotBuildChunkV1, ...] = ()

    def __post_init__(self) -> None:
        if not self.document_id:
            raise SnapshotBuildError("document identity is required")
        _safe_filename(self.source_filename)
        if self.order_index < 0:
            raise SnapshotBuildError("document order must be non-negative")
        text = _safe_text(self.normalized_text, field="normalized document")
        content_hash = _sha256(text.encode("utf-8"))
        if self.content_sha256 and self.content_sha256 != content_hash:
            raise SnapshotBuildError("document content hash mismatch")
        source_hash = self.source_sha256 or content_hash
        if not _HASH_RE.fullmatch(source_hash):
            raise SnapshotBuildError("source hash must be a SHA-256 hex digest")
        ordered = tuple(self.chunks)
        if tuple(item.chunk_index for item in ordered) != tuple(range(len(ordered))):
            raise SnapshotBuildError("document chunks must be contiguous and ordered")
        for chunk in ordered:
            if chunk.document_id != self.document_id or chunk.document_order != self.order_index:
                raise SnapshotBuildError("chunk does not belong to document")
        if not ordered:
            raise SnapshotBuildError("document must contain at least one chunk")
        object.__setattr__(self, "source_sha256", source_hash)
        object.__setattr__(self, "content_sha256", content_hash)
        object.__setattr__(self, "chunks", ordered)

    @property
    def char_count(self) -> int:
        return len(self.normalized_text)

    @property
    def byte_count(self) -> int:
        return len(self.normalized_text.encode("utf-8"))

    @property
    def content_hash(self) -> str:
        return self.content_sha256

    @property
    def source_hash(self) -> str:
        return self.source_sha256

    @property
    def document_order(self) -> int:
        return self.order_index

    def canonical(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "source_filename": self.source_filename,
            "order_index": self.order_index,
            "source_sha256": self.source_sha256,
            "content_sha256": self.content_sha256,
            "char_count": self.char_count,
            "byte_count": self.byte_count,
            "chunks": [chunk.canonical() for chunk in self.chunks],
        }


@dataclass(frozen=True, slots=True)
class SnapshotBuildV1:
    """A complete immutable, non-public embedding build candidate."""

    build_id: str
    agent_version_id: str
    knowledge_snapshot_id: str
    draft_revision: int
    persona_spec_hash: str
    documents: tuple[SnapshotBuildDocumentV1, ...]
    chunking_version: str = DEFAULT_CHUNKING_VERSION
    embedding_model_key: str = MOCK_EMBEDDING_MODEL
    embedding_dimension: int = MOCK_EMBEDDING_DIMENSION
    embedding_provider: str = MOCK_EMBEDDING_PROVIDER
    embedding_region: str = MOCK_EMBEDDING_REGION
    embedding_policy_version: str = MOCK_EMBEDDING_POLICY_VERSION

    def __post_init__(self) -> None:
        if not self.build_id or not self.agent_version_id or not self.knowledge_snapshot_id:
            raise SnapshotBuildError("build, AgentVersion and snapshot identity are required")
        if self.draft_revision < 0:
            raise SnapshotBuildError("draft revision must be non-negative")
        if not self.persona_spec_hash.strip():
            raise SnapshotBuildError("PersonaSpec hash is required")
        if not self.chunking_version.strip():
            raise SnapshotBuildError("chunking version is required")
        if (
            not isinstance(self.embedding_model_key, str)
            or not self.embedding_model_key.strip()
            or self.embedding_model_key.lower() == "latest"
            or isinstance(self.embedding_dimension, bool)
            or not isinstance(self.embedding_dimension, int)
            or self.embedding_dimension < 1
            or not isinstance(self.embedding_provider, str)
            or not self.embedding_provider.strip()
            or not isinstance(self.embedding_region, str)
            or not self.embedding_region.strip()
            or not isinstance(self.embedding_policy_version, str)
            or not self.embedding_policy_version.strip()
        ):
            raise SnapshotBuildError("embedding model and dimension are required")
        identity = embedding_identity_for(
            self.embedding_model_key,
            self.embedding_dimension,
            provider=self.embedding_provider,
            region=self.embedding_region,
            policy_version=self.embedding_policy_version,
        )
        if identity is None:
            raise SnapshotBuildError("embedding identity does not match a closed resource")
        ordered = tuple(self.documents)
        if not ordered:
            raise SnapshotBuildError("a SnapshotBuild must contain a document")
        if tuple(item.order_index for item in ordered) != tuple(range(len(ordered))):
            raise SnapshotBuildError("documents must be ordered from zero")
        ids: set[str] = set()
        chunk_ids: set[str] = set()
        for document in ordered:
            if document.document_id in ids:
                raise SnapshotBuildError("duplicate document identity")
            ids.add(document.document_id)
            for chunk in document.chunks:
                if chunk.chunk_id in chunk_ids:
                    raise SnapshotBuildError("duplicate chunk identity")
                chunk_ids.add(chunk.chunk_id)
        object.__setattr__(self, "documents", ordered)

    @property
    def chunks(self) -> tuple[SnapshotBuildChunkV1, ...]:
        return tuple(chunk for document in self.documents for chunk in document.chunks)

    @property
    def embedding_identity(self) -> EmbeddingIdentityV1:
        """Return the frozen five-field identity for this build."""

        identity = embedding_identity_for(
            self.embedding_model_key,
            self.embedding_dimension,
            provider=self.embedding_provider,
            region=self.embedding_region,
            policy_version=self.embedding_policy_version,
        )
        if identity is None:  # pragma: no cover - guarded by __post_init__
            raise SnapshotBuildError("embedding identity does not match a closed resource")
        return identity

    @property
    def total_char_count(self) -> int:
        return sum(document.char_count for document in self.documents)

    @property
    def total_byte_count(self) -> int:
        return sum(document.byte_count for document in self.documents)

    @property
    def canonical_manifest(self) -> dict[str, object]:
        """Return a fresh canonical manifest mapping; callers cannot mutate the build."""

        return {
            "manifest_version": SNAPSHOT_BUILD_VERSION,
            "build_id": self.build_id,
            "agent_version_id": self.agent_version_id,
            "knowledge_snapshot_id": self.knowledge_snapshot_id,
            "draft_revision": self.draft_revision,
            "persona_spec_hash": self.persona_spec_hash,
            "chunking_version": self.chunking_version,
            "embedding_provider": self.embedding_provider,
            "embedding_model_key": self.embedding_model_key,
            "embedding_region": self.embedding_region,
            "embedding_dimension": self.embedding_dimension,
            "embedding_policy_version": self.embedding_policy_version,
            "total_char_count": self.total_char_count,
            "total_byte_count": self.total_byte_count,
            "documents": [document.canonical() for document in self.documents],
        }

    def manifest(self) -> dict[str, object]:
        """Method form for persistence adapters that prefer callables."""

        return self.canonical_manifest

    @property
    def canonical_manifest_bytes(self) -> bytes:
        return _canonical_json(self.canonical_manifest)

    @property
    def manifest_hash(self) -> str:
        return _sha256(self.canonical_manifest_bytes)

    @property
    def build_manifest_hash(self) -> str:
        return self.manifest_hash

    @property
    def snapshot_id(self) -> str:
        return self.knowledge_snapshot_id

    @property
    def version_id(self) -> str:
        return self.agent_version_id

    @property
    def canonical_manifest_hash(self) -> str:
        return self.manifest_hash

    def verify_manifest_hash(self, expected: str) -> None:
        if expected != self.manifest_hash:
            raise SnapshotBuildError("SnapshotBuild manifest hash mismatch")

    def compatible_with(self, other: SnapshotBuildV1) -> bool:
        return self.manifest_hash == other.manifest_hash

    def assert_compatible(self, other: SnapshotBuildV1) -> None:
        if not self.compatible_with(other):
            raise SnapshotBuildError("embedding result belongs to a different SnapshotBuild")

    def publish_candidate(
        self,
        vectors: Sequence[Sequence[float]],
        *,
        build_manifest_hash: str | None = None,
        model_key: str | None = None,
        dimension: int | None = None,
        existing_snapshot_ids: Sequence[str] = (),
    ) -> SnapshotPublishCandidateV1:
        """Validate vectors and produce a new-snapshot-only publication value."""

        expected_hash = build_manifest_hash or self.manifest_hash
        self.verify_manifest_hash(expected_hash)
        if self.knowledge_snapshot_id in set(existing_snapshot_ids):
            raise SnapshotBuildError("a SnapshotBuild cannot overwrite an existing snapshot")
        chosen_model = self.embedding_model_key if model_key is None else model_key
        chosen_dimension = self.embedding_dimension if dimension is None else dimension
        if chosen_model != self.embedding_model_key or chosen_dimension != self.embedding_dimension:
            raise SnapshotBuildError("embedding metadata does not match SnapshotBuild")
        if len(vectors) != len(self.chunks):
            raise SnapshotBuildError("embedding vector count does not match build chunks")
        frozen_vectors: list[tuple[float, ...]] = []
        for vector in vectors:
            try:
                if any(
                    isinstance(item, bool) or not isinstance(item, (int, float)) for item in vector
                ):
                    raise TypeError("non-numeric vector item")
                values = tuple(float(item) for item in vector)
            except (TypeError, ValueError) as exc:
                raise SnapshotBuildError("embedding vector contains a non-numeric value") from exc
            if len(values) != self.embedding_dimension:
                raise SnapshotBuildError("embedding vector dimension does not match build")
            if any(not math.isfinite(value) for value in values):
                raise SnapshotBuildError("embedding vector contains a non-finite value")
            frozen_vectors.append(values)
        return SnapshotPublishCandidateV1(
            build=self,
            build_manifest_hash=expected_hash,
            chunk_ids=tuple(chunk.chunk_id for chunk in self.chunks),
            vectors=tuple(frozen_vectors),
            model_key=chosen_model,
            dimension=chosen_dimension,
            embedding_provider=self.embedding_provider,
            embedding_region=self.embedding_region,
            policy_version=self.embedding_policy_version,
        )

    @classmethod
    def from_documents(
        cls,
        *,
        agent_version_id: str,
        knowledge_snapshot_id: str,
        draft_revision: int,
        persona_spec_hash: str,
        documents: Sequence[SnapshotBuildInputDocument | MarkdownDocument | Mapping[str, object]],
        build_id: str | None = None,
        chunking_version: str = DEFAULT_CHUNKING_VERSION,
        embedding_model_key: str = MOCK_EMBEDDING_MODEL,
        embedding_dimension: int = MOCK_EMBEDDING_DIMENSION,
        embedding_provider: str = MOCK_EMBEDDING_PROVIDER,
        embedding_region: str = MOCK_EMBEDDING_REGION,
        embedding_policy_version: str = MOCK_EMBEDDING_POLICY_VERSION,
    ) -> SnapshotBuildV1:
        if not documents:
            raise SnapshotBuildError("a SnapshotBuild needs at least one document")
        normalized = tuple(_coerce_document(item, index) for index, item in enumerate(documents))
        if tuple(item.order_index for item in normalized) != tuple(range(len(normalized))):
            raise SnapshotBuildError("documents must be ordered from zero")
        output: list[SnapshotBuildDocumentV1] = []
        for document in normalized:
            raw_chunks = chunk_markdown(document.text)
            chunks = tuple(
                SnapshotBuildChunkV1(
                    chunk_id=str(
                        uuid5(
                            NAMESPACE_URL,
                            "maya:snapshot-build-v1:"
                            + knowledge_snapshot_id
                            + ":"
                            + document.document_id
                            + ":"
                            + str(index),
                        )
                    ),
                    document_id=document.document_id,
                    document_order=document.order_index,
                    chunk_index=index,
                    text=text,
                    start_offset=start,
                    end_offset=end,
                )
                for index, (chunk_index, text, start, end) in enumerate(raw_chunks)
            )
            # ``chunk_markdown`` currently starts at zero and increments by one;
            # keep the explicit check so a future chunker cannot silently alter
            # the persisted order.
            if tuple(item[0] for item in raw_chunks) != tuple(range(len(raw_chunks))):
                raise SnapshotBuildError("chunker returned an unstable order")
            output.append(
                SnapshotBuildDocumentV1(
                    document_id=document.document_id,
                    source_filename=document.source_filename,
                    order_index=document.order_index,
                    normalized_text=document.text,
                    source_sha256=document.source_sha256,
                    chunks=chunks,
                )
            )
        chosen_build_id = build_id
        if chosen_build_id is None:
            chosen_build_id = str(
                uuid5(
                    NAMESPACE_URL,
                    "maya:snapshot-build-v1:" + agent_version_id + ":" + knowledge_snapshot_id,
                )
            )
        return cls(
            build_id=chosen_build_id,
            agent_version_id=agent_version_id,
            knowledge_snapshot_id=knowledge_snapshot_id,
            draft_revision=draft_revision,
            persona_spec_hash=persona_spec_hash,
            documents=tuple(output),
            chunking_version=chunking_version,
            embedding_model_key=embedding_model_key,
            embedding_dimension=embedding_dimension,
            embedding_provider=embedding_provider,
            embedding_region=embedding_region,
            embedding_policy_version=embedding_policy_version,
        )


@dataclass(frozen=True, slots=True)
class SnapshotPublishCandidateV1:
    """Validated values a persistence adapter may atomically publish."""

    build: SnapshotBuildV1
    build_manifest_hash: str
    chunk_ids: tuple[str, ...]
    vectors: tuple[tuple[float, ...], ...]
    model_key: str
    dimension: int
    embedding_provider: str = ""
    embedding_region: str = ""
    policy_version: str = ""

    def __post_init__(self) -> None:
        self.build.verify_manifest_hash(self.build_manifest_hash)
        if self.chunk_ids != tuple(chunk.chunk_id for chunk in self.build.chunks):
            raise SnapshotBuildError("publish candidate chunk order does not match build")
        if (
            self.model_key != self.build.embedding_model_key
            or self.dimension != self.build.embedding_dimension
        ):
            raise SnapshotBuildError("publish candidate metadata does not match build")
        identity = self.build.embedding_identity
        provider = self.embedding_provider or identity.provider
        region = self.embedding_region or identity.region
        policy = self.policy_version or identity.policy_version
        if (
            provider != identity.provider
            or region != identity.region
            or policy != identity.policy_version
        ):
            raise SnapshotBuildError("publish candidate identity does not match build")
        object.__setattr__(self, "embedding_provider", provider)
        object.__setattr__(self, "embedding_region", region)
        object.__setattr__(self, "policy_version", policy)
        if len(self.vectors) != len(self.chunk_ids):
            raise SnapshotBuildError("publish candidate vector count does not match build")
        for vector in self.vectors:
            try:
                valid = len(vector) == self.dimension and all(
                    not isinstance(value, bool)
                    and isinstance(value, (int, float))
                    and math.isfinite(float(value))
                    for value in vector
                )
            except (TypeError, ValueError):
                valid = False
            if not valid:
                raise SnapshotBuildError("publish candidate vector shape is invalid")

    @property
    def knowledge_snapshot_id(self) -> str:
        return self.build.knowledge_snapshot_id

    @property
    def agent_version_id(self) -> str:
        return self.build.agent_version_id


def _coerce_document(
    value: SnapshotBuildInputDocument | MarkdownDocument | Mapping[str, object],
    index: int,
) -> SnapshotBuildInputDocument:
    if isinstance(value, SnapshotBuildInputDocument):
        result = value
    elif isinstance(value, MarkdownDocument):
        result = SnapshotBuildInputDocument(
            document_id=f"document-{index}",
            source_filename=value.filename,
            text=value.normalized,
            order_index=index,
            source_sha256=value.source_sha256 or value.content_hash,
        )
    elif isinstance(value, Mapping):
        document_id = value.get("document_id", value.get("id"))
        filename = value.get("source_filename", value.get("filename"))
        text = value.get("text", value.get("normalized_text", value.get("content")))
        source_bytes = value.get("source_bytes", value.get("normalized_bytes"))
        order = value.get("order_index", index)
        source_hash = value.get("source_sha256", "")
        if not isinstance(document_id, str) or not isinstance(filename, str):
            raise SnapshotBuildError("document identity and filename are required")
        if isinstance(source_bytes, (bytes, bytearray)):
            try:
                normalized_source = normalize_markdown(filename, bytes(source_bytes))
            except ValueError as exc:
                raise SnapshotBuildError("source bytes are not valid Markdown") from exc
            text = normalized_source.normalized
            source_hash = normalized_source.source_sha256
        if not isinstance(text, str):
            raise SnapshotBuildError("normalized document text is required")
        if isinstance(order, bool) or not isinstance(order, int):
            raise SnapshotBuildError("document order is invalid")
        if not isinstance(source_hash, str):
            raise SnapshotBuildError("source hash is invalid")
        result = SnapshotBuildInputDocument(document_id, filename, text, order, source_hash)
    else:
        raise SnapshotBuildError("unsupported SnapshotBuild document input")
    if result.order_index != index:
        raise SnapshotBuildError("documents must be supplied in canonical order")
    _safe_filename(result.source_filename)
    _safe_text(result.text, field="normalized document")
    return result


def prepare_snapshot_build(
    *,
    agent_version_id: str,
    knowledge_snapshot_id: str,
    draft_revision: int,
    persona_spec_hash: str,
    documents: Sequence[SnapshotBuildInputDocument | MarkdownDocument | Mapping[str, object]],
    build_id: str | None = None,
    chunking_version: str = DEFAULT_CHUNKING_VERSION,
    embedding_model_key: str = MOCK_EMBEDDING_MODEL,
    embedding_dimension: int = MOCK_EMBEDDING_DIMENSION,
    embedding_provider: str = MOCK_EMBEDDING_PROVIDER,
    embedding_region: str = MOCK_EMBEDDING_REGION,
    embedding_policy_version: str = MOCK_EMBEDDING_POLICY_VERSION,
) -> SnapshotBuildV1:
    """Build a deterministic candidate without writing or calling a provider."""

    return SnapshotBuildV1.from_documents(
        agent_version_id=agent_version_id,
        knowledge_snapshot_id=knowledge_snapshot_id,
        draft_revision=draft_revision,
        persona_spec_hash=persona_spec_hash,
        documents=documents,
        build_id=build_id,
        chunking_version=chunking_version,
        embedding_model_key=embedding_model_key,
        embedding_dimension=embedding_dimension,
        embedding_provider=embedding_provider,
        embedding_region=embedding_region,
        embedding_policy_version=embedding_policy_version,
    )


# Common integration aliases.
build_snapshot = prepare_snapshot_build
SnapshotBuildDocument = SnapshotBuildDocumentV1
SnapshotBuildChunk = SnapshotBuildChunkV1


__all__ = [
    "DEFAULT_CHUNKING_VERSION",
    "FIXED_EMBEDDING_DIMENSION",
    "FIXED_EMBEDDING_MODEL",
    "MOCK_EMBEDDING_DIMENSION",
    "MOCK_EMBEDDING_KEY",
    "MOCK_EMBEDDING_MODEL",
    "MOCK_EMBEDDING_MODEL_KEY",
    "MOCK_EMBEDDING_PROVIDER",
    "MOCK_EMBEDDING_REGION",
    "MOCK_EMBEDDING_IDENTITY",
    "MOCK_EMBEDDING_POLICY_VERSION",
    "REAL_EMBEDDING_DIMENSION",
    "REAL_EMBEDDING_IDENTITY",
    "REAL_EMBEDDING_MODEL",
    "REAL_EMBEDDING_MODEL_KEY",
    "REAL_EMBEDDING_POLICY_VERSION",
    "REAL_EMBEDDING_PROVIDER",
    "REAL_EMBEDDING_REGION",
    "EmbeddingIdentityV1",
    "SNAPSHOT_BUILD_VERSION",
    "SnapshotBuildChunk",
    "SnapshotBuildChunkV1",
    "SnapshotBuildDocument",
    "SnapshotBuildDocumentV1",
    "SnapshotBuildError",
    "SnapshotBuildInputDocument",
    "SnapshotBuildV1",
    "SnapshotPublishCandidateV1",
    "build_snapshot",
    "embedding_identity_for",
    "embedding_policy_version_for",
    "prepare_snapshot_build",
]
