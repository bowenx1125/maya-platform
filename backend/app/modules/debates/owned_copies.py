"""Debate-owned copies of the sources a participant was frozen from.

A Debate keeps its own AGENT.md, a deep copy of the RAG snapshot (files and
chunks), a copy of each bound Knowledge set's markdown, and a voice snapshot.
Deleting the live Agent, RAG, Knowledge or Voice does not change that copy.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.models import (
    AgentVersion,
    KnowledgeChunk,
    KnowledgeSnapshot,
    SnapshotDocument,
    StoredFile,
    VoiceProfile,
)
from app.modules.knowledge.files import read_contained, write_atomic


def voice_snapshot(profile: VoiceProfile | None) -> tuple[str | None, bytes | None]:
    if profile is None:
        return None, None
    payload = {
        "voice_profile_id": profile.id,
        "display_name": profile.display_name,
        "scope": profile.scope,
        "group_id": profile.group_id,
        "provider_key": profile.provider_key,
        "target_model_key": profile.target_model_key,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")), profile.external_id_encrypted


def fill_owned_copies(db: Session, row: object) -> bool:
    """Fill missing copies on one ``DebateParticipant``; True when changed."""

    changed = False
    if (
        getattr(row, "agent_md_snapshot", None) is None
        or getattr(row, "persona_spec_hash_snapshot", None) is None
    ):
        version_id = getattr(row, "agent_version_id", None)
        version = db.get(AgentVersion, version_id) if version_id else None
        if version is not None:
            if getattr(row, "agent_md_snapshot", None) is None:
                row.agent_md_snapshot = version.agent_md  # type: ignore[attr-defined]
                changed = True
            if getattr(row, "persona_spec_hash_snapshot", None) is None:
                row.persona_spec_hash_snapshot = version.persona_spec_hash  # type: ignore[attr-defined]
                changed = True
    if getattr(row, "voice_snapshot_json", None) is None:
        profile_id = getattr(row, "effective_voice_profile_id", None)
        profile = db.get(VoiceProfile, profile_id) if profile_id else None
        payload, cipher = voice_snapshot(profile)
        if payload is not None:
            row.voice_snapshot_json = payload  # type: ignore[attr-defined]
            row.voice_external_id_encrypted = cipher  # type: ignore[attr-defined]
            changed = True
    return changed


@dataclass(frozen=True)
class FrozenOwner:
    course_id: str
    group_id: str | None
    version_id: str | None
    agent_md: str
    persona_spec_hash: str


def frozen_owner(db: Session, row: Any) -> FrozenOwner:
    """Everything a running Debate needs about a participant's source Agent.

    Reads only the participant row; the live version is a fallback for rows
    written before 0077 that have no AGENT.md copy yet.
    """

    agent_md = row.agent_md_snapshot
    persona_hash = getattr(row, "persona_spec_hash_snapshot", None)
    if agent_md is None or persona_hash is None:
        version = db.get(AgentVersion, row.agent_version_id) if row.agent_version_id else None
        if version is None and agent_md is None:
            raise ValueError("the frozen participant AGENT.md is unavailable")
        if version is not None:
            agent_md = version.agent_md if agent_md is None else agent_md
            persona_hash = version.persona_spec_hash if persona_hash is None else persona_hash
    return FrozenOwner(
        course_id=str(row.course_id),
        group_id=str(row.group_id) if row.group_id else None,
        version_id=str(row.agent_version_id) if row.agent_version_id else None,
        agent_md=str(agent_md or ""),
        persona_spec_hash=str(persona_hash or ""),
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _copy_stored(db: Session, data_root: Path, file_id: str | None, relative: str) -> str:
    source = db.get(StoredFile, file_id) if file_id else None
    payload = b""
    kind = "markdown"
    if source is not None:
        kind = source.kind
        try:
            payload = read_contained(data_root, source.relative_path)
        except OSError:
            payload = b""
    digest, size = write_atomic(data_root, relative, payload)
    now = _now()
    stored = StoredFile(
        id=str(uuid4()),
        kind=kind,
        relative_path=relative,
        sha256=digest,
        size_bytes=size,
        state="active",
        created_at=now,
        updated_at=now,
    )
    db.add(stored)
    db.flush()
    return stored.id


def copy_snapshot_for_debate(
    db: Session, source_id: str, debate_id: str, data_root: Path
) -> tuple[str, dict[str, str]]:
    """Deep-copy one Agent snapshot. Returns the new id and old->new chunk ids.

    The copy's document links are null, so deleting the original RAG row
    cannot reach it. ``owner_debate_id`` marks it so version pruning skips it.
    """

    source = db.get(KnowledgeSnapshot, source_id)
    if source is None:
        raise ValueError("the frozen knowledge snapshot is unavailable")
    if source.owner_debate_id == debate_id:
        return source.id, {}
    new_id = str(uuid4())
    combined = _copy_stored(
        db,
        data_root,
        source.stored_file_id,
        f"debate-knowledge/{debate_id}/{new_id}/combined",
    )
    now = _now()
    db.add(
        KnowledgeSnapshot(
            id=new_id,
            agent_version_id=None,
            owner_debate_id=debate_id,
            stored_file_id=combined,
            content_hash=source.content_hash,
            total_char_count=source.total_char_count,
            embedding_key=source.embedding_key,
            embedding_provider=source.embedding_provider,
            embedding_region=source.embedding_region,
            embedding_dimension=source.embedding_dimension,
            embedding_policy_version=source.embedding_policy_version,
            chunking_json=source.chunking_json,
            created_at=now,
        )
    )
    db.flush()
    documents = db.scalars(
        select(SnapshotDocument)
        .where(SnapshotDocument.snapshot_id == source.id)
        .order_by(SnapshotDocument.order_index)
    ).all()
    doc_map: dict[str, str] = {}
    for doc in documents:
        new_doc = str(uuid4())
        doc_map[doc.id] = new_doc
        db.add(
            SnapshotDocument(
                id=new_doc,
                snapshot_id=new_id,
                document_id=None,
                stored_file_id=_copy_stored(
                    db,
                    data_root,
                    doc.stored_file_id,
                    f"debate-knowledge/{debate_id}/{new_id}/{new_doc}",
                ),
                source_filename=doc.source_filename,
                char_count=doc.char_count,
                order_index=doc.order_index,
                source_authorization_epoch=doc.source_authorization_epoch,
            )
        )
    db.flush()
    chunk_map: dict[str, str] = {}
    chunks = db.scalars(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.snapshot_id == source.id)
        .order_by(KnowledgeChunk.chunk_index)
    ).all()
    for chunk in chunks:
        new_chunk = str(uuid4())
        chunk_map[chunk.id] = new_chunk
        db.add(
            KnowledgeChunk(
                id=new_chunk,
                snapshot_id=new_id,
                snapshot_document_id=doc_map[chunk.snapshot_document_id],
                document_id=None,
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                embedding_blob=chunk.embedding_blob,
                embedding_dimension=chunk.embedding_dimension,
                embedding_key=chunk.embedding_key,
            )
        )
    db.flush()
    return new_id, chunk_map


def _rewrite_ids(value: Any, chunk_map: dict[str, str], snapshot_id: str, old_snapshot: str) -> Any:
    if isinstance(value, dict):
        rewritten = {
            key: _rewrite_ids(item, chunk_map, snapshot_id, old_snapshot)
            for key, item in value.items()
        }
        if rewritten.get("chunk_id") in chunk_map:
            rewritten["chunk_id"] = chunk_map[str(rewritten["chunk_id"])]
        if rewritten.get("snapshot_id") == old_snapshot:
            rewritten["snapshot_id"] = snapshot_id
        return rewritten
    if isinstance(value, list):
        return [_rewrite_ids(item, chunk_map, snapshot_id, old_snapshot) for item in value]
    return value


def adopt_participant_knowledge(db: Session, row: Any, data_root: Path) -> bool:
    """Point one participant at a Debate-owned snapshot and Knowledge copy."""

    from app.modules.debates.models import DebateKnowledgeCopy, DebateTurn, TurnSource
    from app.modules.knowledge_sets.models import (
        AgentKnowledgeSet,
        KnowledgeSet,
        KnowledgeSetMarkdownVersion,
    )

    changed = False
    source = db.get(KnowledgeSnapshot, row.knowledge_snapshot_id)
    if source is not None and source.owner_debate_id != row.debate_id:
        old_snapshot = source.id
        new_id, chunk_map = copy_snapshot_for_debate(db, old_snapshot, row.debate_id, data_root)
        if chunk_map:
            for turn in db.scalars(
                select(DebateTurn).where(DebateTurn.participant_id == row.id)
            ).all():
                for raw_name in ("retrieval_receipts_json", "evidence_trace_json"):
                    raw = getattr(turn, raw_name, None)
                    if not raw:
                        continue
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    rewritten = _rewrite_ids(parsed, chunk_map, new_id, old_snapshot)
                    if rewritten != parsed:
                        setattr(turn, raw_name, json.dumps(rewritten, separators=(",", ":")))
            turn_ids = [
                turn.id
                for turn in db.scalars(
                    select(DebateTurn).where(DebateTurn.participant_id == row.id)
                ).all()
            ]
            sources = db.scalars(
                select(TurnSource).where(
                    TurnSource.turn_id.in_(turn_ids or [""]),
                    TurnSource.snapshot_id == old_snapshot,
                )
            ).all()
            for item in sources:
                mapped = chunk_map.get(item.chunk_id)
                if mapped is None:
                    continue
                item.chunk_id = mapped
                item.snapshot_id = new_id
        db.execute(
            update(DebateTurn)
            .where(
                DebateTurn.participant_id == row.id,
                DebateTurn.knowledge_snapshot_id == old_snapshot,
            )
            .values(knowledge_snapshot_id=new_id)
        )
        row.knowledge_snapshot_id = new_id
        changed = True
    if row.agent_id:
        bindings = db.scalars(
            select(AgentKnowledgeSet)
            .where(AgentKnowledgeSet.agent_id == row.agent_id)
            .order_by(AgentKnowledgeSet.order_index)
        ).all()
        for binding in bindings:
            already = db.scalar(
                select(DebateKnowledgeCopy.id).where(
                    DebateKnowledgeCopy.participant_id == row.id,
                    DebateKnowledgeCopy.source_knowledge_set_id == binding.knowledge_set_id,
                )
            )
            if already is not None:
                continue
            knowledge = db.get(KnowledgeSet, binding.knowledge_set_id)
            if knowledge is None:
                continue
            markdown = db.scalar(
                select(KnowledgeSetMarkdownVersion)
                .where(KnowledgeSetMarkdownVersion.knowledge_set_id == knowledge.id)
                .order_by(KnowledgeSetMarkdownVersion.version_seq.desc())
            )
            text = markdown.markdown if markdown is not None else ""
            if not text:
                continue
            db.add(
                DebateKnowledgeCopy(
                    id=str(uuid4()),
                    debate_id=row.debate_id,
                    participant_id=row.id,
                    source_knowledge_set_id=knowledge.id,
                    name=knowledge.display_name,
                    markdown=text,
                    content_hash=_sha256(text),
                    created_at=_now(),
                )
            )
            changed = True
    if changed:
        db.flush()
    return changed


def adopt_debate_knowledge(
    db: Session, debate_id: str, participants: list[Any], data_root: Path
) -> None:
    for row in participants:
        adopt_participant_knowledge(db, row, data_root)


def delete_debate_knowledge(db: Session, debate_id: str, data_root: Path | None) -> None:
    """Remove copies owned by a Debate after its participant rows are gone."""

    from app.modules.debates.models import DebateKnowledgeCopy, DebateParticipant

    referenced = set(
        db.scalars(
            select(DebateParticipant.knowledge_snapshot_id).where(
                DebateParticipant.debate_id == debate_id
            )
        ).all()
    )
    snapshots = db.scalars(
        select(KnowledgeSnapshot).where(KnowledgeSnapshot.owner_debate_id == debate_id)
    ).all()
    for snapshot in snapshots:
        if snapshot.id in referenced:
            continue
        _delete_snapshot_files(db, snapshot, data_root)
        db.delete(snapshot)
    if not referenced:
        for copy in db.scalars(
            select(DebateKnowledgeCopy).where(DebateKnowledgeCopy.debate_id == debate_id)
        ).all():
            db.delete(copy)
    db.flush()


def _delete_snapshot_files(
    db: Session, snapshot: KnowledgeSnapshot, data_root: Path | None
) -> None:
    from app.modules.real_delete import release_stored_file

    file_ids = [snapshot.stored_file_id]
    file_ids.extend(
        db.scalars(
            select(SnapshotDocument.stored_file_id).where(
                SnapshotDocument.snapshot_id == snapshot.id
            )
        ).all()
    )
    db.delete(snapshot)
    db.flush()
    for file_id in file_ids:
        release_stored_file(db, data_root, file_id)
