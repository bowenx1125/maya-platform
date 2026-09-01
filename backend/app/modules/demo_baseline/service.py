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
from app.seed import GROUP_BOWEN_ID, GROUP_KAIKAI_ID


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
        return f"groups/{self.group_id}/baseline/source.md"

    @property
    def snapshot_relative_path(self) -> str:
        return f"snapshots/{self.snapshot_id}/rag.md"

    @property
    def frozen_relative_path(self) -> str:
        return f"snapshots/{self.snapshot_id}/documents/{self.snapshot_document_id}.md"


BASELINE_A_AGENT_MD = """# Maya Demo Guide

## Identity

- Role: Classroom guide for evidence-aware community exchange
- Historical or cultural context: A fictional teaching guide for comparing local perspectives.

## Cultural lens

- Shared responsibility

## Core values

- Reciprocity
- Care

## Initial position

Prefer transparent, evidence-aware choices that leave room for community voice.

## Speaking style

- Tone: Calm and respectful
- Argument pattern: State the concern, examine evidence, then weigh trade-offs
- Concession style: Acknowledge a sound point before refining it
- Question style: Ask one focused question about practical effects

## Debate strategy

- Connect evidence to responsible action without manufacturing certainty

## Boundaries

- Never invent evidence outside the assigned snapshot
"""

BASELINE_A_KNOWLEDGE = """# Shared community resources

Transparent stewardship can balance access, care, and practical experimentation.
Communities learn more safely when they name trade-offs, invite affected voices,
and review decisions against the evidence available in the shared snapshot.
"""

BASELINE_B_AGENT_MD = """# Maya Demo Companion

## Identity

- Role: Classroom companion for practice-first community exchange
- Historical or cultural context: A fictional teaching companion for testing ideas in practice.

## Cultural lens

- Learning by doing

## Core values

- Curiosity
- Craft

## Initial position

Prefer small reversible experiments that let a community learn from its own practice.

## Speaking style

- Tone: Warm and direct
- Argument pattern: Offer a concrete case, name what it shows, then generalize carefully
- Concession style: Restate the other position in its strongest form before answering
- Question style: Ask one focused question about how a claim would be tested

## Debate strategy

- Ground every general claim in an observable practice from the assigned snapshot

## Boundaries

- Never invent evidence outside the assigned snapshot
"""

BASELINE_B_KNOWLEDGE = """# Shared practice and apprenticeship

Communities keep skills alive by practising them together and revising what fails.
Short reversible trials expose hidden costs early, and an apprentice who repeats a
task under guidance learns limits that no summary of the practice can transmit.
"""


BASELINE_A = BaselineSpec(
    key="a",
    group_id=GROUP_BOWEN_ID,
    agent_id=str(UUID("9f6c9dc8-b4bf-5f9f-98d2-f8e718c1ce0b")),
    version_id=str(UUID("a7efcb9b-21fb-5d09-9366-3cc44b777d01")),
    document_id=str(UUID("e40d7ad6-98a7-537d-840b-0b47c1240b5d")),
    snapshot_id=str(UUID("2572c3ac-4a1b-5bd8-a14a-a194ae7d3c6e")),
    source_file_id=str(UUID("b57411fa-20e9-5a53-a997-bb5d7cf2c4d4")),
    snapshot_file_id=str(UUID("c44020ad-8cb0-5e20-8e53-a1ce1de945bd")),
    frozen_file_id=str(UUID("4a69fa04-ef4b-5a88-b1de-0b98799a1513")),
    snapshot_document_id=str(UUID("42fc313e-68cd-5d30-9cd1-fdc5e27fcf7f")),
    chunk_id=str(UUID("ce164c2b-c94b-5dbc-931b-6ee08e329f5e")),
    snapshot_file_reference_id=str(UUID("f537710d-31ca-51d3-87d0-d4dbcc3a1ca8")),
    frozen_file_reference_id=str(UUID("c7b9454e-8df6-5fae-875e-738aa00478f3")),
    confirming_user_id="bad7de3c-0409-5d50-9ad7-bbb641d1f6a7",
    agent_name="Maya Demo Guide",
    description="System baseline for the local Real-Core Demo.",
    agent_md=BASELINE_A_AGENT_MD,
    knowledge=BASELINE_A_KNOWLEDGE,
)

BASELINE_B = BaselineSpec(
    key="b",
    group_id=GROUP_KAIKAI_ID,
    agent_id=str(UUID("22f76355-e0da-5a6c-a8cd-36f2fb1b9a59")),
    version_id=str(UUID("a8106256-df18-5a5e-ac0a-19630adc1468")),
    document_id=str(UUID("34774092-3a02-5f46-bc17-a78aaa0eea23")),
    snapshot_id=str(UUID("abd4e8f9-d54d-5879-a519-e8cce4cc7a99")),
    source_file_id=str(UUID("4bd6f903-3f62-5944-ad35-5020c4d1becf")),
    snapshot_file_id=str(UUID("da52e25c-73de-559b-b87f-f0cfa280a5a2")),
    frozen_file_id=str(UUID("e180da8f-440b-5948-b46d-59b7a4d68e42")),
    snapshot_document_id=str(UUID("ba6da959-7105-5bd5-9ca0-51287bd260aa")),
    chunk_id=str(UUID("1de97388-f390-5f37-8921-6cdce020ec5c")),
    snapshot_file_reference_id=str(UUID("a559a397-d1c8-5877-b221-ab491fbe910e")),
    frozen_file_reference_id=str(UUID("672e5031-e438-5a1f-ad06-612c522ccd5f")),
    confirming_user_id="0c12d01a-5acf-5430-bc4d-731af768ff46",
    agent_name="Maya Demo Companion",
    description="Second system baseline for the local Real-Core Demo.",
    agent_md=BASELINE_B_AGENT_MD,
    knowledge=BASELINE_B_KNOWLEDGE,
)

BASELINE_SPECS: tuple[BaselineSpec, ...] = (BASELINE_A, BASELINE_B)

# The acceptance driver, the agents/knowledge routers and the demo status route
# still address the primary baseline through these frozen module constants.
BASELINE_AGENT_ID = BASELINE_A.agent_id
BASELINE_VERSION_ID = BASELINE_A.version_id
BASELINE_DOCUMENT_ID = BASELINE_A.document_id
BASELINE_SNAPSHOT_ID = BASELINE_A.snapshot_id
BASELINE_SOURCE_FILE_ID = BASELINE_A.source_file_id
BASELINE_SNAPSHOT_FILE_ID = BASELINE_A.snapshot_file_id
BASELINE_FROZEN_FILE_ID = BASELINE_A.frozen_file_id
BASELINE_SNAPSHOT_DOCUMENT_ID = BASELINE_A.snapshot_document_id
BASELINE_CHUNK_ID = BASELINE_A.chunk_id
BASELINE_SNAPSHOT_FILE_REFERENCE_ID = BASELINE_A.snapshot_file_reference_id
BASELINE_FROZEN_FILE_REFERENCE_ID = BASELINE_A.frozen_file_reference_id
BASELINE_SOURCE_RELATIVE_PATH = BASELINE_A.source_relative_path
BASELINE_SNAPSHOT_RELATIVE_PATH = BASELINE_A.snapshot_relative_path
BASELINE_FROZEN_RELATIVE_PATH = BASELINE_A.frozen_relative_path
BASELINE_AGENT_MD = BASELINE_A.agent_md
BASELINE_KNOWLEDGE = BASELINE_A.knowledge

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
