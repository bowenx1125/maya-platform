"""Crash-boundary cleanup and permission repair for Wave 1A storage."""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import FileOperation, Job, KnowledgeDocument
from app.modules.knowledge.files import contained_path, mark_owned_files_private

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

    query = select(FileOperation).where(FileOperation.state.in_(_RECOVERABLE_OPERATION_STATES))
    if idempotency_record_id is not None:
        query = query.where(FileOperation.idempotency_record_id == idempotency_record_id)
    if operation_id is not None:
        query = query.where(FileOperation.id == operation_id)
    for operation in session.scalars(query).all():
        # Both paths are independently journaled.  A promoted upload has a
        # final target and a staging source; publish uses exact UUID trees.
        _remove_owned_path(data_root, operation.source_relative_path)
        _remove_owned_path(data_root, operation.target_relative_path)
        if operation.operation_kind == "document_upload":
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

    for job in session.scalars(select(Job).where(Job.state.in_(("pending", "running")))).all():
        job.state = "interrupted"
        job.safe_error_code = "provider_unavailable"
    mark_owned_files_private(data_root)
