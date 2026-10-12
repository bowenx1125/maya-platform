"""Keep source-version identity separate from a mutable library filename."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import invalid_state
from app.core.models import KnowledgeDocument
from app.modules.knowledge_sets.models import KnowledgeDocumentVersion


def current_source_version(
    db: Session, document: KnowledgeDocument
) -> KnowledgeDocumentVersion | None:
    version = db.scalar(
        select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.document_id == document.id,
            KnowledgeDocumentVersion.version_seq == document.content_version_seq,
        )
    )
    if version is not None and (
        version.stored_file_id != document.stored_file_id
        or version.content_hash != document.content_hash
        or document.stored_file is None
        or version.file_sha256 != document.stored_file.sha256
    ):
        raise invalid_state("The source version no longer matches its recorded content.")
    return version


def retain_current_source_version(db: Session, document: KnowledgeDocument) -> None:
    """Backfill the existing head before its display name changes, without advancing it."""
    if current_source_version(db, document) is not None:
        return
    if document.stored_file is None:
        raise invalid_state("The source file is unavailable.")
    db.add(
        KnowledgeDocumentVersion(
            id=str(uuid4()),
            document_id=document.id,
            version_seq=document.content_version_seq,
            stored_file_id=document.stored_file_id,
            source_filename=document.source_filename,
            char_count=document.char_count,
            index_revision=document.index_revision,
            content_hash=document.content_hash,
            file_sha256=document.stored_file.sha256,
            authorization_epoch=document.authorization_epoch,
            created_by_user_id=None,
            created_at=document.created_at,
        )
    )
    db.flush()


def source_version_filename(db: Session, document: KnowledgeDocument) -> str:
    version = current_source_version(db, document)
    return version.source_filename if version is not None else document.source_filename
