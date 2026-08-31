"""Deterministic system baseline for the local Real-Core Demo.

The baseline is ordinary published Agent data with reserved stable IDs.  It is
created idempotently on a real Demo startup and is excluded from dirty counts;
student-created Agents and classroom data remain ordinary mutable history.
"""

from __future__ import annotations

import hashlib
import json
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
from app.seed import GROUP_BOWEN_ID

BASELINE_AGENT_ID = str(UUID("9f6c9dc8-b4bf-5f9f-98d2-f8e718c1ce0b"))
BASELINE_VERSION_ID = str(UUID("a7efcb9b-21fb-5d09-9366-3cc44b777d01"))
BASELINE_DOCUMENT_ID = str(UUID("e40d7ad6-98a7-537d-840b-0b47c1240b5d"))
BASELINE_SNAPSHOT_ID = str(UUID("2572c3ac-4a1b-5bd8-a14a-a194ae7d3c6e"))
BASELINE_SOURCE_FILE_ID = str(UUID("b57411fa-20e9-5a53-a997-bb5d7cf2c4d4"))
BASELINE_SNAPSHOT_FILE_ID = str(UUID("c44020ad-8cb0-5e20-8e53-a1ce1de945bd"))
BASELINE_FROZEN_FILE_ID = str(UUID("4a69fa04-ef4b-5a88-b1de-0b98799a1513"))
BASELINE_SNAPSHOT_DOCUMENT_ID = str(UUID("42fc313e-68cd-5d30-9cd1-fdc5e27fcf7f"))
BASELINE_CHUNK_ID = str(UUID("ce164c2b-c94b-5dbc-931b-6ee08e329f5e"))
BASELINE_SNAPSHOT_FILE_REFERENCE_ID = str(UUID("f537710d-31ca-51d3-87d0-d4dbcc3a1ca8"))
BASELINE_FROZEN_FILE_REFERENCE_ID = str(UUID("c7b9454e-8df6-5fae-875e-738aa00478f3"))

BASELINE_SOURCE_RELATIVE_PATH = "groups/66ee37fb-5772-5c8f-bb63-46d1783c53ae/baseline/source.md"
BASELINE_SNAPSHOT_RELATIVE_PATH = "snapshots/2572c3ac-4a1b-5bd8-a14a-a194ae7d3c6e/rag.md"
BASELINE_FROZEN_RELATIVE_PATH = (
    "snapshots/2572c3ac-4a1b-5bd8-a14a-a194ae7d3c6e/documents/"
    "42fc313e-68cd-5d30-9cd1-fdc5e27fcf7f.md"
)

BASELINE_AGENT_MD = """# Maya Demo Guide

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

BASELINE_KNOWLEDGE = """# Shared community resources

Transparent stewardship can balance access, care, and practical experimentation.
Communities learn more safely when they name trade-offs, invite affected voices,
and review decisions against the evidence available in the shared snapshot.
"""


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
    """Reject writes targeting the reserved system Agent."""

    if str(agent_id) == BASELINE_AGENT_ID:
        raise _baseline_mutation_error()


def reject_baseline_version_mutation(version_id: str) -> None:
    """Reject writes targeting the reserved published version."""

    if str(version_id) == BASELINE_VERSION_ID:
        raise _baseline_mutation_error()


def reject_baseline_document_mutation(document_id: str) -> None:
    """Reject writes targeting the reserved source document."""

    if str(document_id) == BASELINE_DOCUMENT_ID:
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


def _verify_existing_rows(db: Session, data_root: Path) -> bool:
    agent = db.get(Agent, BASELINE_AGENT_ID)
    version = db.get(AgentVersion, BASELINE_VERSION_ID)
    document = db.get(KnowledgeDocument, BASELINE_DOCUMENT_ID)
    snapshot = db.get(KnowledgeSnapshot, BASELINE_SNAPSHOT_ID)
    if all(row is None for row in (agent, version, document, snapshot)):
        return False
    if any(row is None for row in (agent, version, document, snapshot)):
        raise DemoBaselineConflict("baseline rows are only partially present")
    assert isinstance(agent, Agent)
    assert isinstance(version, AgentVersion)
    assert isinstance(document, KnowledgeDocument)
    assert isinstance(snapshot, KnowledgeSnapshot)
    expected_persona = compile_persona_or_raise(BASELINE_AGENT_MD, expected_name="Maya Demo Guide")
    expected_source = BASELINE_KNOWLEDGE.encode("utf-8")
    expected_hash = _sha256(expected_source)
    expected_combined = (
        f"<!-- source: baseline.md; document_id: {BASELINE_DOCUMENT_ID} -->\n{BASELINE_KNOWLEDGE}"
    ).encode()
    expected_combined_hash = _sha256(expected_combined)
    if (
        agent.group_id != GROUP_BOWEN_ID
        or agent.name != "Maya Demo Guide"
        or agent.description != "System baseline for the local Real-Core Demo."
        or agent.status != "active"
        or agent.current_published_version_id != BASELINE_VERSION_ID
        or version.agent_id != BASELINE_AGENT_ID
        or version.state != "published"
        or version.agent_md != BASELINE_AGENT_MD
        or version.raw_agent_md_hash != raw_agent_md_hash(BASELINE_AGENT_MD)
        or version.persona_compiler_version != expected_persona.compiler_version
        or version.knowledge_snapshot_id != BASELINE_SNAPSHOT_ID
        or version.persona_spec_hash != persona_spec_hash(expected_persona)
        or version.persona_spec_json != canonical_json(expected_persona)
        or version.persona_confirmation_revision != version.revision
        or version.persona_required is not True
        or document.source_filename != "baseline.md"
        or document.group_id != GROUP_BOWEN_ID
        or document.content_hash != expected_hash
        or document.index_status != "ready"
        or snapshot.agent_version_id != BASELINE_VERSION_ID
        or snapshot.stored_file_id != BASELINE_SNAPSHOT_FILE_ID
        or snapshot.content_hash != expected_combined_hash
        or snapshot.embedding_key != EMBEDDING_KEY
        or snapshot.embedding_provider != "mock"
        or snapshot.embedding_region != "local"
        or snapshot.embedding_dimension != EMBEDDING_DIMENSION
        or snapshot.embedding_policy_version != "w4-mock-v1"
    ):
        raise DemoBaselineConflict("reserved baseline rows differ from the frozen fixture")
    _ensure_file(data_root, BASELINE_SOURCE_RELATIVE_PATH, expected_source, expected_hash)
    _ensure_file(
        data_root,
        BASELINE_SNAPSHOT_RELATIVE_PATH,
        expected_combined,
        snapshot.content_hash,
    )
    _ensure_file(data_root, BASELINE_FROZEN_RELATIVE_PATH, expected_source, expected_hash)
    source_file = db.get(StoredFile, BASELINE_SOURCE_FILE_ID)
    snapshot_file = db.get(StoredFile, BASELINE_SNAPSHOT_FILE_ID)
    frozen_file = db.get(StoredFile, BASELINE_FROZEN_FILE_ID)
    snapshot_document = db.get(SnapshotDocument, BASELINE_SNAPSHOT_DOCUMENT_ID)
    chunk = db.get(KnowledgeChunk, BASELINE_CHUNK_ID)
    snapshot_file_reference = db.get(FileReference, BASELINE_SNAPSHOT_FILE_REFERENCE_ID)
    frozen_file_reference = db.get(FileReference, BASELINE_FROZEN_FILE_REFERENCE_ID)
    relation = db.get(
        AgentVersionDocument,
        {"agent_version_id": BASELINE_VERSION_ID, "document_id": BASELINE_DOCUMENT_ID},
    )
    if (
        snapshot_document is None
        or chunk is None
        or relation is None
        or not relation.enabled
        or source_file is None
        or snapshot_file is None
        or frozen_file is None
        or source_file.relative_path != BASELINE_SOURCE_RELATIVE_PATH
        or source_file.sha256 != expected_hash
        or snapshot_file.relative_path != BASELINE_SNAPSHOT_RELATIVE_PATH
        or snapshot_file.sha256 != expected_combined_hash
        or frozen_file.relative_path != BASELINE_FROZEN_RELATIVE_PATH
        or frozen_file.sha256 != expected_hash
        or snapshot_document.stored_file_id != BASELINE_FROZEN_FILE_ID
        or snapshot_file_reference is None
        or snapshot_file_reference.stored_file_id != BASELINE_SNAPSHOT_FILE_ID
        or snapshot_file_reference.owner_type != "knowledge_snapshot"
        or snapshot_file_reference.owner_id != BASELINE_SNAPSHOT_ID
        or frozen_file_reference is None
        or frozen_file_reference.stored_file_id != BASELINE_FROZEN_FILE_ID
        or frozen_file_reference.owner_type != "snapshot_document"
        or frozen_file_reference.owner_id != BASELINE_SNAPSHOT_DOCUMENT_ID
        or chunk.snapshot_id != BASELINE_SNAPSHOT_ID
        or chunk.snapshot_document_id != BASELINE_SNAPSHOT_DOCUMENT_ID
        or chunk.document_id != BASELINE_DOCUMENT_ID
        or chunk.embedding_key != EMBEDDING_KEY
        or chunk.embedding_dimension != EMBEDDING_DIMENSION
    ):
        raise DemoBaselineConflict("reserved baseline snapshot lineage is incomplete")
    return True


def ensure_demo_baseline(db: Session, data_root: Path) -> None:
    """Create or verify the fixed published Mock Agent and usable Snapshot."""

    if _verify_existing_rows(db, data_root):
        return None
    group = db.get(Group, GROUP_BOWEN_ID)
    if group is None:
        raise DemoBaselineConflict("Bowen group must be seeded before the Demo baseline")
    now = _now()
    source_bytes = BASELINE_KNOWLEDGE.encode("utf-8")
    source_hash = _sha256(source_bytes)
    source_filename = "baseline.md"
    compiled = compile_persona_or_raise(BASELINE_AGENT_MD, expected_name="Maya Demo Guide")
    compiled_json = canonical_json(compiled)
    compiled_hash = persona_spec_hash(compiled)
    chunks = build_chunks(BASELINE_KNOWLEDGE)
    if len(chunks) != 1:
        raise DemoBaselineConflict("the frozen baseline must contain exactly one chunk")
    chunk = chunks[0]
    combined = (
        f"<!-- source: {source_filename}; document_id: {BASELINE_DOCUMENT_ID} -->\n"
        f"{BASELINE_KNOWLEDGE}"
    )
    combined_bytes = combined.encode()
    combined_hash = _sha256(combined_bytes)
    _ensure_file(data_root, BASELINE_SOURCE_RELATIVE_PATH, source_bytes, source_hash)
    _ensure_file(data_root, BASELINE_SNAPSHOT_RELATIVE_PATH, combined_bytes, combined_hash)
    _ensure_file(data_root, BASELINE_FROZEN_RELATIVE_PATH, source_bytes, source_hash)

    agent = Agent(
        id=BASELINE_AGENT_ID,
        group_id=GROUP_BOWEN_ID,
        name="Maya Demo Guide",
        description="System baseline for the local Real-Core Demo.",
        status="active",
        current_published_version_id=BASELINE_VERSION_ID,
        created_at=now,
        updated_at=now,
    )
    version = AgentVersion(
        id=BASELINE_VERSION_ID,
        agent_id=BASELINE_AGENT_ID,
        version_seq=0,
        state="published",
        revision=1,
        agent_md=BASELINE_AGENT_MD,
        raw_agent_md_hash=raw_agent_md_hash(BASELINE_AGENT_MD),
        persona_spec_json=compiled_json,
        persona_spec_hash=compiled_hash,
        persona_compiler_version=compiled.compiler_version,
        persona_diagnostics_json="[]",
        persona_confirmation_revision=1,
        student_confirmed_at=now,
        persona_confirming_user_id="bad7de3c-0409-5d50-9ad7-bbb641d1f6a7",
        persona_required=True,
        avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
        knowledge_snapshot_id=BASELINE_SNAPSHOT_ID,
        published_at=now,
        created_at=now,
        updated_at=now,
    )
    source_file = StoredFile(
        id=BASELINE_SOURCE_FILE_ID,
        kind="markdown",
        relative_path=BASELINE_SOURCE_RELATIVE_PATH,
        sha256=source_hash,
        size_bytes=len(source_bytes),
        state="active",
        created_at=now,
        updated_at=now,
    )
    document = KnowledgeDocument(
        id=BASELINE_DOCUMENT_ID,
        group_id=GROUP_BOWEN_ID,
        source_filename=source_filename,
        stored_file_id=BASELINE_SOURCE_FILE_ID,
        char_count=len(BASELINE_KNOWLEDGE),
        index_status="ready",
        index_revision=1,
        workspace_state="active",
        content_hash=source_hash,
        created_at=now,
        updated_at=now,
    )
    snapshot_file = StoredFile(
        id=BASELINE_SNAPSHOT_FILE_ID,
        kind="snapshot_rag",
        relative_path=BASELINE_SNAPSHOT_RELATIVE_PATH,
        sha256=combined_hash,
        size_bytes=len(combined_bytes),
        state="active",
        created_at=now,
        updated_at=now,
    )
    frozen_file = StoredFile(
        id=BASELINE_FROZEN_FILE_ID,
        kind="snapshot_source",
        relative_path=BASELINE_FROZEN_RELATIVE_PATH,
        sha256=source_hash,
        size_bytes=len(source_bytes),
        state="active",
        created_at=now,
        updated_at=now,
    )
    snapshot = KnowledgeSnapshot(
        id=BASELINE_SNAPSHOT_ID,
        agent_version_id=BASELINE_VERSION_ID,
        stored_file_id=BASELINE_SNAPSHOT_FILE_ID,
        content_hash=combined_hash,
        total_char_count=len(BASELINE_KNOWLEDGE),
        embedding_key=EMBEDDING_KEY,
        embedding_provider="mock",
        embedding_region="local",
        embedding_dimension=EMBEDDING_DIMENSION,
        embedding_policy_version="w4-mock-v1",
        chunking_json=_canonical({"token_target": 600, "token_hard": 800, "overlap": 100}),
        created_at=now,
    )
    snapshot_document = SnapshotDocument(
        id=BASELINE_SNAPSHOT_DOCUMENT_ID,
        snapshot_id=BASELINE_SNAPSHOT_ID,
        document_id=BASELINE_DOCUMENT_ID,
        stored_file_id=BASELINE_FROZEN_FILE_ID,
        source_filename=source_filename,
        char_count=len(BASELINE_KNOWLEDGE),
        order_index=0,
    )
    snapshot_chunk = KnowledgeChunk(
        id=BASELINE_CHUNK_ID,
        snapshot_id=BASELINE_SNAPSHOT_ID,
        snapshot_document_id=BASELINE_SNAPSHOT_DOCUMENT_ID,
        document_id=BASELINE_DOCUMENT_ID,
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
                id=BASELINE_SNAPSHOT_FILE_REFERENCE_ID,
                stored_file_id=BASELINE_SNAPSHOT_FILE_ID,
                owner_type="knowledge_snapshot",
                owner_id=BASELINE_SNAPSHOT_ID,
                purpose="rag",
                created_at=now,
            ),
            FileReference(
                id=BASELINE_FROZEN_FILE_REFERENCE_ID,
                stored_file_id=BASELINE_FROZEN_FILE_ID,
                owner_type="snapshot_document",
                owner_id=BASELINE_SNAPSHOT_DOCUMENT_ID,
                purpose="source",
                created_at=now,
            ),
        ]
    )
    db.flush()
    db.add(
        AgentVersionDocument(
            agent_version_id=BASELINE_VERSION_ID,
            document_id=BASELINE_DOCUMENT_ID,
            enabled=True,
            order_index=0,
        )
    )
    db.add(snapshot_chunk)
    db.flush()
    return None


def is_system_baseline_agent(agent_id: str) -> bool:
    """Return true only for the reserved system baseline Agent."""

    return str(agent_id) == BASELINE_AGENT_ID


def baseline_is_usable(db: Session) -> bool:
    """Return whether the reserved Agent has a published, searchable snapshot."""

    version = db.get(AgentVersion, BASELINE_VERSION_ID)
    snapshot = db.get(KnowledgeSnapshot, BASELINE_SNAPSHOT_ID)
    chunk = db.get(KnowledgeChunk, BASELINE_CHUNK_ID)
    return bool(
        version is not None
        and snapshot is not None
        and chunk is not None
        and version.state == "published"
        and version.knowledge_snapshot_id == BASELINE_SNAPSHOT_ID
        and snapshot.agent_version_id == BASELINE_VERSION_ID
        and chunk.snapshot_id == BASELINE_SNAPSHOT_ID
    )


def dirty_counts(db: Session) -> tuple[int, int, int]:
    """Count user-owned work while excluding only the reserved baseline Agent."""

    agents = int(db.scalar(select(func.count(Agent.id)).where(Agent.id != BASELINE_AGENT_ID)) or 0)
    debates = int(db.scalar(select(func.count(Debate.id))) or 0)
    interactions = int(db.scalar(select(func.count(ClassroomInteractionWindow.id))) or 0)
    return agents, debates, interactions
