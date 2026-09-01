"""Deterministic system baselines for the local Real-Core Demo.

Two baselines are ordinary published Agent data with reserved stable IDs: the
Group A guide and the Group B guide.  Both are created idempotently on a real
Demo startup so a teacher can open a two-Agent Debate from an empty runtime, and
both are excluded from dirty counts.  Student-created Agents and classroom data
remain ordinary mutable history.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import PlatformError
from app.core.models import (
    Agent,
    AgentVersion,
    AgentVersionDocument,
    FileReference,
    Group,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSnapshot,
    SnapshotDocument,
    StoredFile,
)
from app.modules.agents.persona import (
    canonical_json,
    compile_persona_or_raise,
    persona_spec_hash,
    raw_agent_md_hash,
)
from app.modules.avatars import DEFAULT_AVATAR_CONFIG
from app.modules.debates.models import Debate
from app.modules.interactions.models import ClassroomInteractionWindow
from app.modules.knowledge.files import contained_path, write_atomic
from app.modules.knowledge.markdown import EMBEDDING_DIMENSION, EMBEDDING_KEY, build_chunks
from app.seed import GROUP_DEMO_ID


@dataclass(frozen=True)
class BaselineSpec:
    """Every reserved identifier and frozen text for one system baseline."""

    key: str
    group_id: str
    agent_id: str
    version_id: str
    document_id: str
    snapshot_id: str
    source_file_id: str
    snapshot_file_id: str
    frozen_file_id: str
    snapshot_document_id: str
    chunk_id: str
    snapshot_file_reference_id: str
    frozen_file_reference_id: str
    confirming_user_id: str
    agent_name: str
    description: str
    agent_md: str
    knowledge: str

    @property
    def source_relative_path(self) -> str:
        # Every seeded Agent lives in the one Demo group, so the baseline key
        # — not the group — is what keeps these source files distinct.
        return f"groups/{self.group_id}/baseline/{self.key}/source.md"

    @property
    def snapshot_relative_path(self) -> str:
        return f"snapshots/{self.snapshot_id}/rag.md"

    @property
    def frozen_relative_path(self) -> str:
        return f"snapshots/{self.snapshot_id}/documents/{self.snapshot_document_id}.md"


_AGENT_DIRECTORY = Path(__file__).resolve().parent / "agents"


def _agent_asset(name: str) -> str:
    """Read one seeded Agent's authored text from the package.

    The persona and knowledge are product content, not a test fixture: they
    ship inside the application package so the container needs no mount, and
    keeping them as files rather than inlined constants preserves the authored
    bytes exactly. ``_verify_existing_rows`` still compares every derived hash
    on startup, so a drifted file fails closed instead of reseeding silently.
    """

    return (_AGENT_DIRECTORY / name).read_text(encoding="utf-8")


SOCRATES_AGENT_MD = _agent_asset("socrates.agent.md")
SOCRATES_KNOWLEDGE = _agent_asset("socrates.knowledge.md")
PLATO_AGENT_MD = _agent_asset("plato.agent.md")
PLATO_KNOWLEDGE = _agent_asset("plato.knowledge.md")
LAOZI_AGENT_MD = _agent_asset("laozi.agent.md")
LAOZI_KNOWLEDGE = _agent_asset("laozi.knowledge.md")


BASELINE_SOCRATES = BaselineSpec(
    key="socrates",
    group_id=GROUP_DEMO_ID,
    agent_id=str(UUID("93c04441-1bae-54b2-8037-78622b88d640")),
    version_id=str(UUID("e792ee07-7f8b-52d2-817b-d315a3d32445")),
    document_id=str(UUID("b3c49aff-9bd2-5106-bb19-df49fefcd57f")),
    snapshot_id=str(UUID("49985a15-9633-5190-9982-173c7a21d6e7")),
    source_file_id=str(UUID("85151808-81ad-5c44-87bc-63b7f256ed8b")),
    snapshot_file_id=str(UUID("e3e14380-5a80-5cfe-911a-c370577ccd6f")),
    frozen_file_id=str(UUID("f2cf5047-d385-5268-9546-4891cca2e2e2")),
    snapshot_document_id=str(UUID("46674f4f-7397-56ed-af24-3aca35e54823")),
    chunk_id=str(UUID("8930b6e8-c664-5f41-a794-a79e7157c71d")),
    snapshot_file_reference_id=str(UUID("52f7361a-26d9-525a-b995-ac0fc8de2dca")),
    frozen_file_reference_id=str(UUID("8cd981ac-313c-5123-ad58-92a02dcb7573")),
    confirming_user_id="60541c78-30f1-55c5-b2aa-207b6a766883",
    agent_name="Socrates",
    description="Seeded Demo Agent for the local mutual-learning session.",
    agent_md=SOCRATES_AGENT_MD,
    knowledge=SOCRATES_KNOWLEDGE,
)

BASELINE_PLATO = BaselineSpec(
    key="plato",
    group_id=GROUP_DEMO_ID,
    agent_id=str(UUID("9b5d4adf-d82d-578e-9e70-6adf7713715f")),
    version_id=str(UUID("632571be-07c9-5da9-98c8-19da1d044ea4")),
    document_id=str(UUID("07ffd76c-cca8-5d8d-9305-4acf8e291e48")),
    snapshot_id=str(UUID("4913e647-0750-5d33-8e79-1bdc39a890f2")),
    source_file_id=str(UUID("c5b28abd-fb52-5364-b5ad-41c0753427af")),
    snapshot_file_id=str(UUID("34b7bef0-bbd8-5486-b679-a26eed7c90c7")),
    frozen_file_id=str(UUID("12c57cc1-956c-52f7-93e5-8297b44c854c")),
    snapshot_document_id=str(UUID("2732aaff-cb74-5cfd-ac92-8123823111dc")),
    chunk_id=str(UUID("3c5b2d05-a32c-5883-8bac-08d3911694ab")),
    snapshot_file_reference_id=str(UUID("0843f3b8-d66a-5081-aa42-2dbe81a38118")),
    frozen_file_reference_id=str(UUID("21fa3a3b-59bd-5960-8297-5d61d4ef5647")),
    confirming_user_id="bc170f51-45fb-5296-a36d-a2edc8f8d315",
    agent_name="Plato",
    description="Seeded Demo Agent for the local mutual-learning session.",
    agent_md=PLATO_AGENT_MD,
    knowledge=PLATO_KNOWLEDGE,
)

BASELINE_LAOZI = BaselineSpec(
    key="laozi",
    group_id=GROUP_DEMO_ID,
    agent_id=str(UUID("007c71c4-80b8-5168-9721-b8b66a86a1a3")),
    version_id=str(UUID("5d69d715-e597-50fb-923b-fcffdf1464f2")),
    document_id=str(UUID("c01f183f-ab7a-5f80-8434-6b55e097d61c")),
    snapshot_id=str(UUID("4be98d3b-f324-5319-ae47-9021e5a78a76")),
    source_file_id=str(UUID("b04fc099-9195-5933-8dfa-e41670afc1b6")),
    snapshot_file_id=str(UUID("708f93ec-e2a1-5240-8ff3-84c4675ec7b2")),
    frozen_file_id=str(UUID("57472fa4-6cb8-5e15-ad8a-96b2e3c1236e")),
    snapshot_document_id=str(UUID("6014de16-6223-55b7-a6ae-8ee3f136082a")),
    chunk_id=str(UUID("7d6f29c5-f446-575c-a83a-c3ebb6b403b4")),
    snapshot_file_reference_id=str(UUID("11aaa267-682d-54d6-96bd-927498753d88")),
    frozen_file_reference_id=str(UUID("478f9390-70ac-5702-89b3-1d9d3b92d6b4")),
    confirming_user_id="89857c76-2d84-5ecf-b680-990815b98680",
    agent_name="Laozi",
    description="Seeded Demo Agent for the local mutual-learning session.",
    agent_md=LAOZI_AGENT_MD,
    knowledge=LAOZI_KNOWLEDGE,
)

BASELINE_SPECS: tuple[BaselineSpec, ...] = (BASELINE_SOCRATES, BASELINE_PLATO, BASELINE_LAOZI)

# Socrates is the primary baseline.  ``/api/v1/demo/baseline`` returns exactly
# one baseline object and the acceptance driver asserts that field set, so the
# other two are reachable only through the ordinary published-Agent routes.
BASELINE_AGENT_ID = BASELINE_SOCRATES.agent_id
BASELINE_VERSION_ID = BASELINE_SOCRATES.version_id
BASELINE_DOCUMENT_ID = BASELINE_SOCRATES.document_id
BASELINE_SNAPSHOT_ID = BASELINE_SOCRATES.snapshot_id
BASELINE_SOURCE_FILE_ID = BASELINE_SOCRATES.source_file_id
BASELINE_SNAPSHOT_FILE_ID = BASELINE_SOCRATES.snapshot_file_id
BASELINE_FROZEN_FILE_ID = BASELINE_SOCRATES.frozen_file_id
BASELINE_SNAPSHOT_DOCUMENT_ID = BASELINE_SOCRATES.snapshot_document_id
BASELINE_CHUNK_ID = BASELINE_SOCRATES.chunk_id
BASELINE_SNAPSHOT_FILE_REFERENCE_ID = BASELINE_SOCRATES.snapshot_file_reference_id
BASELINE_FROZEN_FILE_REFERENCE_ID = BASELINE_SOCRATES.frozen_file_reference_id
BASELINE_SOURCE_RELATIVE_PATH = BASELINE_SOCRATES.source_relative_path
BASELINE_SNAPSHOT_RELATIVE_PATH = BASELINE_SOCRATES.snapshot_relative_path
BASELINE_FROZEN_RELATIVE_PATH = BASELINE_SOCRATES.frozen_relative_path
BASELINE_AGENT_MD = BASELINE_SOCRATES.agent_md
BASELINE_KNOWLEDGE = BASELINE_SOCRATES.knowledge

BASELINE_AGENT_IDS = frozenset(spec.agent_id for spec in BASELINE_SPECS)
BASELINE_VERSION_IDS = frozenset(spec.version_id for spec in BASELINE_SPECS)
BASELINE_DOCUMENT_IDS = frozenset(spec.document_id for spec in BASELINE_SPECS)


class DemoBaselineConflict(RuntimeError):
    """A reserved baseline row or file differs from the frozen fixture."""

    code = "demo_baseline_conflict"


BASELINE_MUTATION_ERROR_CODE = "demo_baseline_immutable"


def _baseline_mutation_error() -> PlatformError:
    """Return the single safe error used by every baseline write guard."""

    return PlatformError(
        BASELINE_MUTATION_ERROR_CODE,
        "The published Demo baseline is immutable.",
        409,
    )


def reject_baseline_agent_mutation(agent_id: str) -> None:
    """Reject writes targeting any reserved system Agent."""

    if str(agent_id) in BASELINE_AGENT_IDS:
        raise _baseline_mutation_error()


def reject_baseline_version_mutation(version_id: str) -> None:
    """Reject writes targeting any reserved published version."""

    if str(version_id) in BASELINE_VERSION_IDS:
        raise _baseline_mutation_error()


def reject_baseline_document_mutation(document_id: str) -> None:
    """Reject writes targeting any reserved source document."""

    if str(document_id) in BASELINE_DOCUMENT_IDS:
        raise _baseline_mutation_error()


def _now() -> datetime:
    return datetime.now(UTC)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _ensure_file(data_root: Path, relative_path: str, content: bytes, expected_sha: str) -> None:
    path = contained_path(data_root, relative_path)
    if path.exists():
        if not path.is_file() or _sha256(path.read_bytes()) != expected_sha:
            raise DemoBaselineConflict(f"baseline file conflicts: {relative_path}")
        path.chmod(0o600)
        return
    write_atomic(data_root, relative_path, content)


def _verify_existing_rows(db: Session, data_root: Path, spec: BaselineSpec) -> bool:
    agent = db.get(Agent, spec.agent_id)
    version = db.get(AgentVersion, spec.version_id)
    document = db.get(KnowledgeDocument, spec.document_id)
    snapshot = db.get(KnowledgeSnapshot, spec.snapshot_id)
    if all(row is None for row in (agent, version, document, snapshot)):
        return False
    if any(row is None for row in (agent, version, document, snapshot)):
        raise DemoBaselineConflict("baseline rows are only partially present")
    assert isinstance(agent, Agent)
    assert isinstance(version, AgentVersion)
    assert isinstance(document, KnowledgeDocument)
    assert isinstance(snapshot, KnowledgeSnapshot)
    expected_persona = compile_persona_or_raise(spec.agent_md, expected_name=spec.agent_name)
    expected_source = spec.knowledge.encode("utf-8")
    expected_hash = _sha256(expected_source)
    expected_combined = (
        f"<!-- source: baseline.md; document_id: {spec.document_id} -->\n{spec.knowledge}"
    ).encode()
    expected_combined_hash = _sha256(expected_combined)
    if (
        agent.group_id != spec.group_id
        or agent.name != spec.agent_name
        or agent.description != spec.description
        or agent.status != "active"
        or agent.current_published_version_id != spec.version_id
        or version.agent_id != spec.agent_id
        or version.state != "published"
        or version.agent_md != spec.agent_md
        or version.raw_agent_md_hash != raw_agent_md_hash(spec.agent_md)
        or version.persona_compiler_version != expected_persona.compiler_version
        or version.knowledge_snapshot_id != spec.snapshot_id
        or version.persona_spec_hash != persona_spec_hash(expected_persona)
        or version.persona_spec_json != canonical_json(expected_persona)
        or version.persona_confirmation_revision != version.revision
        or version.persona_required is not True
        or document.source_filename != "baseline.md"
        or document.group_id != spec.group_id
        or document.content_hash != expected_hash
        or document.index_status != "ready"
        or snapshot.agent_version_id != spec.version_id
        or snapshot.stored_file_id != spec.snapshot_file_id
        or snapshot.content_hash != expected_combined_hash
        or snapshot.embedding_key != EMBEDDING_KEY
        or snapshot.embedding_provider != "mock"
        or snapshot.embedding_region != "local"
        or snapshot.embedding_dimension != EMBEDDING_DIMENSION
        or snapshot.embedding_policy_version != "w4-mock-v1"
    ):
        raise DemoBaselineConflict("reserved baseline rows differ from the frozen fixture")
    _ensure_file(data_root, spec.source_relative_path, expected_source, expected_hash)
    _ensure_file(
        data_root,
        spec.snapshot_relative_path,
        expected_combined,
        snapshot.content_hash,
    )
    _ensure_file(data_root, spec.frozen_relative_path, expected_source, expected_hash)
    source_file = db.get(StoredFile, spec.source_file_id)
    snapshot_file = db.get(StoredFile, spec.snapshot_file_id)
    frozen_file = db.get(StoredFile, spec.frozen_file_id)
    snapshot_document = db.get(SnapshotDocument, spec.snapshot_document_id)
    chunk = db.get(KnowledgeChunk, spec.chunk_id)
    snapshot_file_reference = db.get(FileReference, spec.snapshot_file_reference_id)
    frozen_file_reference = db.get(FileReference, spec.frozen_file_reference_id)
    relation = db.get(
        AgentVersionDocument,
        {"agent_version_id": spec.version_id, "document_id": spec.document_id},
    )
    if (
        snapshot_document is None
        or chunk is None
        or relation is None
        or not relation.enabled
        or source_file is None
        or snapshot_file is None
        or frozen_file is None
        or source_file.relative_path != spec.source_relative_path
        or source_file.sha256 != expected_hash
        or snapshot_file.relative_path != spec.snapshot_relative_path
        or snapshot_file.sha256 != expected_combined_hash
        or frozen_file.relative_path != spec.frozen_relative_path
        or frozen_file.sha256 != expected_hash
        or snapshot_document.stored_file_id != spec.frozen_file_id
        or snapshot_file_reference is None
        or snapshot_file_reference.stored_file_id != spec.snapshot_file_id
        or snapshot_file_reference.owner_type != "knowledge_snapshot"
        or snapshot_file_reference.owner_id != spec.snapshot_id
        or frozen_file_reference is None
        or frozen_file_reference.stored_file_id != spec.frozen_file_id
        or frozen_file_reference.owner_type != "snapshot_document"
        or frozen_file_reference.owner_id != spec.snapshot_document_id
        or chunk.snapshot_id != spec.snapshot_id
        or chunk.snapshot_document_id != spec.snapshot_document_id
        or chunk.document_id != spec.document_id
        or chunk.embedding_key != EMBEDDING_KEY
        or chunk.embedding_dimension != EMBEDDING_DIMENSION
    ):
        raise DemoBaselineConflict("reserved baseline snapshot lineage is incomplete")
    return True


def _create_baseline(db: Session, data_root: Path, spec: BaselineSpec) -> None:
    """Insert one frozen baseline; the caller has verified it is absent."""

    group = db.get(Group, spec.group_id)
    if group is None:
        raise DemoBaselineConflict(f"group {spec.group_id} must be seeded before the Demo baseline")
    now = _now()
    source_bytes = spec.knowledge.encode("utf-8")
    source_hash = _sha256(source_bytes)
    source_filename = "baseline.md"
    compiled = compile_persona_or_raise(spec.agent_md, expected_name=spec.agent_name)
    compiled_json = canonical_json(compiled)
    compiled_hash = persona_spec_hash(compiled)
    chunks = build_chunks(spec.knowledge)
    if len(chunks) != 1:
        raise DemoBaselineConflict("the frozen baseline must contain exactly one chunk")
    chunk = chunks[0]
    combined = (
        f"<!-- source: {source_filename}; document_id: {spec.document_id} -->\n{spec.knowledge}"
    )
    combined_bytes = combined.encode()
    combined_hash = _sha256(combined_bytes)
    _ensure_file(data_root, spec.source_relative_path, source_bytes, source_hash)
    _ensure_file(data_root, spec.snapshot_relative_path, combined_bytes, combined_hash)
    _ensure_file(data_root, spec.frozen_relative_path, source_bytes, source_hash)

    agent = Agent(
        id=spec.agent_id,
        group_id=spec.group_id,
        name=spec.agent_name,
        description=spec.description,
        status="active",
        current_published_version_id=spec.version_id,
        created_at=now,
        updated_at=now,
    )
    version = AgentVersion(
        id=spec.version_id,
        agent_id=spec.agent_id,
        version_seq=0,
        state="published",
        revision=1,
        agent_md=spec.agent_md,
        raw_agent_md_hash=raw_agent_md_hash(spec.agent_md),
        persona_spec_json=compiled_json,
        persona_spec_hash=compiled_hash,
        persona_compiler_version=compiled.compiler_version,
        persona_diagnostics_json="[]",
        persona_confirmation_revision=1,
        student_confirmed_at=now,
        persona_confirming_user_id=spec.confirming_user_id,
        persona_required=True,
        avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
        knowledge_snapshot_id=spec.snapshot_id,
        published_at=now,
        created_at=now,
        updated_at=now,
    )
    source_file = StoredFile(
        id=spec.source_file_id,
        kind="markdown",
        relative_path=spec.source_relative_path,
        sha256=source_hash,
        size_bytes=len(source_bytes),
        state="active",
        created_at=now,
        updated_at=now,
    )
    document = KnowledgeDocument(
        id=spec.document_id,
        group_id=spec.group_id,
        source_filename=source_filename,
        stored_file_id=spec.source_file_id,
        char_count=len(spec.knowledge),
        index_status="ready",
        index_revision=1,
        workspace_state="active",
        content_hash=source_hash,
        created_at=now,
        updated_at=now,
    )
    snapshot_file = StoredFile(
        id=spec.snapshot_file_id,
        kind="snapshot_rag",
        relative_path=spec.snapshot_relative_path,
        sha256=combined_hash,
        size_bytes=len(combined_bytes),
        state="active",
        created_at=now,
        updated_at=now,
    )
    frozen_file = StoredFile(
        id=spec.frozen_file_id,
        kind="snapshot_source",
        relative_path=spec.frozen_relative_path,
        sha256=source_hash,
        size_bytes=len(source_bytes),
        state="active",
        created_at=now,
        updated_at=now,
    )
    snapshot = KnowledgeSnapshot(
        id=spec.snapshot_id,
        agent_version_id=spec.version_id,
        stored_file_id=spec.snapshot_file_id,
        content_hash=combined_hash,
        total_char_count=len(spec.knowledge),
        embedding_key=EMBEDDING_KEY,
        embedding_provider="mock",
        embedding_region="local",
        embedding_dimension=EMBEDDING_DIMENSION,
        embedding_policy_version="w4-mock-v1",
        chunking_json=_canonical({"token_target": 600, "token_hard": 800, "overlap": 100}),
        created_at=now,
    )
    snapshot_document = SnapshotDocument(
        id=spec.snapshot_document_id,
        snapshot_id=spec.snapshot_id,
        document_id=spec.document_id,
        stored_file_id=spec.frozen_file_id,
        source_filename=source_filename,
        char_count=len(spec.knowledge),
        order_index=0,
    )
    snapshot_chunk = KnowledgeChunk(
        id=spec.chunk_id,
        snapshot_id=spec.snapshot_id,
        snapshot_document_id=spec.snapshot_document_id,
        document_id=spec.document_id,
        chunk_index=chunk.index,
        chunk_text=chunk.text,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
        embedding_blob=chunk.embedding,
        embedding_dimension=EMBEDDING_DIMENSION,
        embedding_key=EMBEDDING_KEY,
    )
    db.add_all(
        [
            agent,
            version,
            source_file,
            document,
            snapshot_file,
            frozen_file,
            snapshot,
            snapshot_document,
        ]
    )
    db.flush()
    # FileReference has a polymorphic owner and therefore no ORM relationship
    # to order this insert behind the concrete StoredFile rows above.
    db.add_all(
        [
            FileReference(
                id=spec.snapshot_file_reference_id,
                stored_file_id=spec.snapshot_file_id,
                owner_type="knowledge_snapshot",
                owner_id=spec.snapshot_id,
                purpose="rag",
                created_at=now,
            ),
            FileReference(
                id=spec.frozen_file_reference_id,
                stored_file_id=spec.frozen_file_id,
                owner_type="snapshot_document",
                owner_id=spec.snapshot_document_id,
                purpose="source",
                created_at=now,
            ),
        ]
    )
    db.flush()
    db.add(
        AgentVersionDocument(
            agent_version_id=spec.version_id,
            document_id=spec.document_id,
            enabled=True,
            order_index=0,
        )
    )
    db.add(snapshot_chunk)
    db.flush()
    return None


def ensure_demo_baseline(db: Session, data_root: Path) -> None:
    """Create or verify every fixed published Mock Agent and usable Snapshot."""

    for spec in BASELINE_SPECS:
        if _verify_existing_rows(db, data_root, spec):
            continue
        _create_baseline(db, data_root, spec)
    return None


def is_system_baseline_agent(agent_id: str) -> bool:
    """Return true for any reserved system baseline Agent."""

    return str(agent_id) in BASELINE_AGENT_IDS


def _spec_is_usable(db: Session, spec: BaselineSpec) -> bool:
    version = db.get(AgentVersion, spec.version_id)
    snapshot = db.get(KnowledgeSnapshot, spec.snapshot_id)
    chunk = db.get(KnowledgeChunk, spec.chunk_id)
    return bool(
        version is not None
        and snapshot is not None
        and chunk is not None
        and version.state == "published"
        and version.knowledge_snapshot_id == spec.snapshot_id
        and snapshot.agent_version_id == spec.version_id
        and chunk.snapshot_id == spec.snapshot_id
    )


def baseline_is_usable(db: Session) -> bool:
    """Return whether every reserved Agent has a published, searchable snapshot."""

    return all(_spec_is_usable(db, spec) for spec in BASELINE_SPECS)


def dirty_counts(db: Session) -> tuple[int, int, int]:
    """Count user-owned work while excluding only the reserved baseline Agents."""

    agents = int(
        db.scalar(select(func.count(Agent.id)).where(Agent.id.notin_(BASELINE_AGENT_IDS))) or 0
    )
    debates = int(db.scalar(select(func.count(Debate.id))) or 0)
    interactions = int(db.scalar(select(func.count(ClassroomInteractionWindow.id))) or 0)
    return agents, debates, interactions
