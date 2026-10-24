"""Crash-boundary cleanup and permission repair for Wave 1A storage."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.models import (
    AgentVersion,
    AgentVersionDocument,
    FileOperation,
    FileReference,
    Job,
    KnowledgeChunk,
    KnowledgeDocument,
    SnapshotDocument,
    StoredFile,
)
from app.modules.knowledge.files import contained_path, mark_owned_files_private
from app.modules.knowledge_sets.models import (
    KnowledgeAssetVersionSource,
    KnowledgeDocumentVersion,
    KnowledgeGenerationSourceReceipt,
    KnowledgeSetSource,
)

LOGGER = logging.getLogger(__name__)

_RECOVERABLE_OPERATION_STATES = ("prepared", "staged", "promoted", "cleanup_required")


def _remove_owned_path(data_root: Path, relative_path: str | None) -> None:
    """Remove exactly one journal-owned file/tree after containment checks."""

    if not relative_path:
        return
    try:
        target = contained_path(data_root, relative_path)
    except ValueError:
        # Never turn a malformed journal row into a broad filesystem delete.
        return
    root = data_root.resolve()
    if target == root or not (target.exists() or target.is_symlink()):
        return
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)


def _remove_empty_entity_parent(
    data_root: Path,
    relative_path: str | None,
    entity_id: str,
) -> None:
    """Prune one exact UUID parent left by an upload file cleanup."""

    if not relative_path:
        return
    try:
        parent = contained_path(data_root, relative_path).parent
    except ValueError:
        return
    if parent.name != entity_id or parent == data_root.resolve() or parent.is_symlink():
        return
    try:
        parent.rmdir()
    except OSError:
        return


def recover_file_operations(
    session: Session,
    data_root: Path,
    *,
    idempotency_record_id: str | None = None,
    operation_id: str | None = None,
) -> None:
    """Recover durable file journals before a lease can be taken over."""

    query = select(FileOperation).where(
        FileOperation.state.in_(_RECOVERABLE_OPERATION_STATES),
        FileOperation.operation_kind.not_in(
            (
                "debate_audio_swap",
                "debate_turn_tts",
                "debate_cleanup_voice_v1",
                "debate_cleanup_all_v1",
                "agent_cascade_publish",
                "agent_cascade_park",
            )
        ),
    )
    if idempotency_record_id is not None:
        query = query.where(FileOperation.idempotency_record_id == idempotency_record_id)
    if operation_id is not None:
        query = query.where(FileOperation.id == operation_id)
    for operation in session.scalars(query).all():
        # Both paths are independently journaled.  A promoted upload has a
        # final target and a staging source; publish uses exact UUID trees.
        _remove_owned_path(data_root, operation.source_relative_path)
        _remove_owned_path(data_root, operation.target_relative_path)
        if operation.operation_kind in {"document_upload", "document_replace"}:
            _remove_empty_entity_parent(
                data_root,
                operation.target_relative_path,
                operation.entity_id,
            )
        operation.state = "recovered"
        operation.safe_error_code = "file_operation_failed"


def recover_startup(session: Session, data_root: Path) -> None:
    """Recover visible journal/job states before accepting a new request."""

    recover_file_operations(session, data_root)

    # Any indexing row left in-flight across a process crash is no longer
    # resumable in the synchronous Demo.  Keep document/job outcomes
    # consistent and require an explicit reindex.
    for document in session.scalars(
        select(KnowledgeDocument).where(KnowledgeDocument.index_status.in_(("pending", "indexing")))
    ).all():
        document.index_status = "failed"
        document.safe_error_code = "provider_unavailable"

    for job in session.scalars(
        select(Job).where(
            Job.state.in_(("pending", "running")),
            Job.debate_id.is_(None),
        )
    ).all():
        job.state = "interrupted"
        job.safe_error_code = "provider_unavailable"
    # A document that never indexed has nothing to keep. One that failed a
    # later reindex still has its previous index and stays.
    purge_failed_knowledge_uploads(session, data_root)
    mark_owned_files_private(data_root)


def purge_failed_knowledge_uploads(session: Session, data_root: Path) -> int:
    """Delete never-indexed failed uploads, including their stored bytes."""

    # Callers such as startup recovery mark rows failed in this session, and
    # the session does not autoflush.
    session.flush()
    documents = list(
        session.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.index_status == "failed",
                KnowledgeDocument.index_revision == 0,
            )
        ).all()
    )
    removed = 0
    for document in documents:
        if _failed_upload_is_bound(session, document.id):
            continue
        nested = session.begin_nested()
        try:
            stored = session.get(StoredFile, document.stored_file_id)
            relative = stored.relative_path if stored is not None else None
            _remove_owned_path(data_root, relative)
            _remove_empty_entity_parent(data_root, relative, document.id)
            session.execute(
                delete(AgentVersionDocument).where(AgentVersionDocument.document_id == document.id)
            )
            session.execute(
                delete(FileReference).where(
                    (FileReference.stored_file_id == document.stored_file_id)
                    | (
                        (FileReference.owner_type == "knowledge_document")
                        & (FileReference.owner_id == document.id)
                    )
                )
            )
            session.delete(document)
            session.flush()
            if stored is not None and not _stored_file_still_used(session, stored.id):
                session.delete(stored)
            session.flush()
            nested.commit()
            removed += 1
        except (IntegrityError, OSError):
            nested.rollback()
            LOGGER.info("failed_upload_delete_blocked document_id=%s", document.id)
    return removed


def _failed_upload_is_bound(session: Session, document_id: str) -> bool:
    checks = (
        select(SnapshotDocument.id).where(SnapshotDocument.document_id == document_id),
        select(KnowledgeChunk.id).where(KnowledgeChunk.document_id == document_id),
        select(KnowledgeSetSource.id).where(KnowledgeSetSource.document_id == document_id),
        select(KnowledgeDocumentVersion.id).where(
            KnowledgeDocumentVersion.document_id == document_id
        ),
        select(KnowledgeAssetVersionSource.id).where(
            KnowledgeAssetVersionSource.document_id == document_id
        ),
        select(KnowledgeGenerationSourceReceipt.id).where(
            KnowledgeGenerationSourceReceipt.document_id == document_id
        ),
        select(AgentVersionDocument.document_id)
        .join(AgentVersion, AgentVersion.id == AgentVersionDocument.agent_version_id)
        .where(
            AgentVersionDocument.document_id == document_id,
            AgentVersion.state != "draft",
        ),
    )
    return any(session.scalar(check.limit(1)) is not None for check in checks)


def _stored_file_still_used(session: Session, stored_file_id: str) -> bool:
    return (
        session.scalar(
            select(KnowledgeDocument.id)
            .where(KnowledgeDocument.stored_file_id == stored_file_id)
            .limit(1)
        )
        is not None
        or session.scalar(
            select(FileReference.id).where(FileReference.stored_file_id == stored_file_id).limit(1)
        )
        is not None
    )
