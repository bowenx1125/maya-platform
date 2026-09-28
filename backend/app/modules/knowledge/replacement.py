"""Copy-on-write Markdown replacement orchestration.

This module owns the long-running filesystem/journal work and the final
SQLite writer boundary for editing an existing group document.  The ordinary
knowledge router should only parse/authorize the request and call this
service; initial upload, preview, retrieval and snapshot code remain in
``services.py``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy import case, select, text, update
from sqlalchemy.orm import Session

from app.core.errors import (
    PlatformError,
    invalid_state,
    not_found,
    rag_over_limit,
    stale_revision,
)
from app.core.models import (
    AgentVersion,
    AgentVersionDocument,
    FileReference,
    IdempotencyRecord,
    Job,
    KnowledgeDocument,
    StoredFile,
)
from app.modules.knowledge.files import (
    promote_atomic,
    remove_empty_directory,
    stage_atomic,
    verify_staged,
)
from app.modules.knowledge.markdown import MAX_RAG_CHARS, MarkdownDocument, build_chunks
from app.modules.knowledge.services import (
    assert_claim_owned,
    create_file_operation,
    document_file_content,
    load_file_operation,
    now_utc,
    recover_operation_now,
    replace_document_chunks,
    saga_checkpoint,
    transition_file_operation,
)


@dataclass(frozen=True)
class DraftDocumentReference:
    """The complete CAS input for one draft/source relation."""

    version_id: str
    revision: int
    enabled: bool
    order_index: int


def _draft_document_references(
    db: Session,
    document_id: str,
) -> tuple[DraftDocumentReference, ...]:
    """Capture every current draft relation to one workspace document."""

    rows = db.execute(
        select(AgentVersionDocument, AgentVersion.revision)
        .join(AgentVersion, AgentVersion.id == AgentVersionDocument.agent_version_id)
        .where(
            AgentVersionDocument.document_id == document_id,
            AgentVersion.state == "draft",
        )
    ).all()
    return tuple(
        sorted(
            (
                DraftDocumentReference(
                    version_id=relation.agent_version_id,
                    revision=int(revision),
                    enabled=bool(relation.enabled),
                    order_index=relation.order_index,
                )
                for relation, revision in rows
            ),
            key=lambda item: item.version_id,
        )
    )


def replace_document_copy_on_write(
    db: Session,
    data_root: Path,
    old_document_id: str,
    replacement: MarkdownDocument,
    source_bytes: bytes,
    *,
    expected_content_hash: str | None,
    expected_index_revision: int | None,
    idempotency_record_id: str,
    claim_token: str,
    authorization_check: Callable[[Session, str], None] | None = None,
    checkpoint: Callable[[str], None] = saga_checkpoint,
) -> tuple[KnowledgeDocument, tuple[str, ...], str]:
    """Create and atomically promote an immutable Markdown replacement.

    Filesystem work deliberately happens before the final writer transaction.
    Until that transaction commits, the replacement has no
    ``KnowledgeDocument`` row and cannot appear in the library, upload
    candidates, or draft previews.  A durable ``document_replace`` journal
    owns both the staging tree and promoted target so every failure path can
    remove the exact tree without broad cleanup.

    The old workspace document is the single-use CAS marker: a successful
    replacement changes it from ``active`` to ``hidden``.  A second editor
    naming the same old document therefore cannot commit even when it submits
    the same content hash.  Published/superseded relations are never touched.
    """

    old_document = db.get(KnowledgeDocument, old_document_id)
    if old_document is None:
        raise not_found()
    if authorization_check is not None:
        authorization_check(db, old_document.group_id)
    if expected_content_hash is None or expected_index_revision is None:
        raise stale_revision(old_document.index_revision)
    if old_document.workspace_state != "active":
        raise stale_revision(old_document.index_revision)
    old_stored = old_document.stored_file
    if old_stored is None:
        raise invalid_state("The source Markdown file is unavailable.")
    if old_document.content_hash != expected_content_hash:
        raise stale_revision(old_document.index_revision)
    if old_document.index_revision != expected_index_revision:
        raise stale_revision(old_document.index_revision)

    captured_content_hash = old_document.content_hash
    captured_index_revision = old_document.index_revision
    captured_stored_id = old_stored.id
    captured_stored_path = old_stored.relative_path
    captured_stored_sha = old_stored.sha256
    captured_group_id = old_document.group_id
    captured_references = _draft_document_references(db, old_document_id)

    operation_id = str(uuid4())
    new_document_id = str(uuid4())
    staging_root = f"tmp/publish/{operation_id}"
    staging_path = f"{staging_root}/source.md"
    target_path = f"groups/{captured_group_id}/knowledge/{new_document_id}/source.md"
    expected_source_sha = hashlib.sha256(source_bytes).hexdigest()
    expected_source_size = len(source_bytes)

    try:
        create_file_operation(
            db,
            operation_id=operation_id,
            idempotency_record_id=idempotency_record_id,
            operation_kind="document_replace",
            entity_id=new_document_id,
            request_id=str(uuid4()),
            source_relative_path=staging_root,
            target_relative_path=target_path,
            expected_sha256=expected_source_sha,
            claim_token=claim_token,
        )
        checkpoint("replace.prepared")

        record = db.get(IdempotencyRecord, idempotency_record_id)
        if record is None:
            raise invalid_state("The idempotency claim could not be loaded.")
        assert_claim_owned(db, record)
        staged_sha, staged_size = stage_atomic(data_root, staging_path, source_bytes)
        if staged_sha != expected_source_sha or staged_size != expected_source_size:
            raise PlatformError(
                "file_operation_failed",
                "The staged Markdown could not be verified.",
                503,
            )
        verify_staged(data_root, staging_path, expected_source_sha, expected_source_size)
        transition_file_operation(
            db,
            operation_id,
            "staged",
            expected_state="prepared",
            expected_sha256=expected_source_sha,
            idempotency_record_id=idempotency_record_id,
            claim_token=claim_token,
        )
        checkpoint("replace.staged")

        # Compute the complete replacement index while the old document is
        # untouched.  Keep the deterministic Mock boundary and retry policy
        # used by initial uploads/reindexing, but fail the entire edit when
        # indexing cannot produce a usable replacement.
        chunks = None
        index_attempts = 0
        for attempt in range(2):
            index_attempts = attempt + 1
            try:
                chunks = build_chunks(replacement.normalized)
                break
            except Exception:
                if attempt == 1:
                    chunks = None
        if chunks is None:
            raise PlatformError(
                "provider_unavailable",
                "The replacement Markdown could not be indexed.",
                503,
            )

        record = db.get(IdempotencyRecord, idempotency_record_id)
        if record is None:
            raise invalid_state("The idempotency claim could not be loaded.")
        assert_claim_owned(db, record)
        promote_atomic(data_root, staging_path, target_path)
        remove_empty_directory(data_root, staging_root)
        verify_staged(data_root, target_path, expected_source_sha, expected_source_size)
        transition_file_operation(
            db,
            operation_id,
            "promoted",
            expected_state="staged",
            expected_sha256=expected_source_sha,
            idempotency_record_id=idempotency_record_id,
            claim_token=claim_token,
        )
        checkpoint("replace.promoted")

        # End the pre-staging read snapshot before acquiring SQLite's writer
        # lock.  ``BEGIN IMMEDIATE`` is intentional: all final rereads,
        # relation rewrites, revision CAS updates and old-document hiding are
        # one serialized decision.
        db.rollback()
        db.execute(text("BEGIN IMMEDIATE"))
        record = db.get(IdempotencyRecord, idempotency_record_id)
        if record is None:
            raise invalid_state("The idempotency claim could not be loaded.")
        assert_claim_owned(db, record)

        final_old = db.get(KnowledgeDocument, old_document_id)
        if final_old is None:
            raise not_found()
        if authorization_check is not None:
            authorization_check(db, final_old.group_id)
        if final_old.workspace_state != "active":
            raise stale_revision(final_old.index_revision)
        final_stored = final_old.stored_file
        if (
            final_old.group_id != captured_group_id
            or final_old.content_hash != captured_content_hash
            or final_old.index_revision != captured_index_revision
            or final_stored is None
            or final_stored.id != captured_stored_id
            or final_stored.relative_path != captured_stored_path
            or final_stored.sha256 != captured_stored_sha
        ):
            raise stale_revision(final_old.index_revision)
        final_old_bytes = document_file_content(data_root, final_old)
        if hashlib.sha256(final_old_bytes).hexdigest() != captured_stored_sha:
            raise invalid_state("The source Markdown changed during replacement.")

        final_references = _draft_document_references(db, old_document_id)
        if final_references != captured_references:
            # A relation/revision change includes publication, another edit,
            # explicit enable/disable and creation of a new draft relation.
            # Return the current draft revision where possible; no mutation
            # has happened yet and the promoted tree is recovered below.
            current_revisions = [
                db.scalar(
                    select(AgentVersion.revision).where(AgentVersion.id == capture.version_id)
                )
                for capture in captured_references
            ]
            current_revision = next(
                (int(value) for value in current_revisions if value is not None),
                None,
            )
            if any(
                value is not None and int(value) != capture.revision
                for value, capture in zip(
                    current_revisions,
                    captured_references,
                    strict=False,
                )
            ):
                raise stale_revision(current_revision)
            raise invalid_state("The draft document references changed during replacement.")

        if replacement.char_count > MAX_RAG_CHARS:
            raise rag_over_limit()

        timestamp = now_utc()
        stored_file = StoredFile(
            id=str(uuid4()),
            kind="markdown",
            relative_path=target_path,
            sha256=expected_source_sha,
            size_bytes=expected_source_size,
            state="active",
            created_at=timestamp,
            updated_at=timestamp,
        )
        new_document = KnowledgeDocument(
            id=new_document_id,
            group_id=captured_group_id,
            source_filename=replacement.filename,
            source_owner_role=old_document.source_owner_role,
            stored_file_id=stored_file.id,
            char_count=replacement.char_count,
            index_status="ready",
            index_revision=1,
            workspace_state="active",
            content_hash=replacement.content_hash,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(stored_file)
        db.add(new_document)
        db.flush()
        replace_document_chunks(db, new_document, chunks)
        db.add(
            FileReference(
                id=str(uuid4()),
                stored_file_id=stored_file.id,
                owner_type="knowledge_document",
                owner_id=new_document.id,
                purpose="source",
                created_at=timestamp,
            )
        )
        db.add(
            Job(
                id=str(uuid4()),
                document_id=new_document.id,
                operation="replace_document",
                state="completed",
                attempt=index_attempts,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )

        # Replace both enabled and disabled relations.  The captured CAS
        # tuples are still the complete set under the writer lock.
        affected_versions: list[str] = []
        for capture in captured_references:
            relation_changed = db.execute(
                update(AgentVersionDocument)
                .where(
                    AgentVersionDocument.agent_version_id == capture.version_id,
                    AgentVersionDocument.document_id == old_document_id,
                    AgentVersionDocument.enabled == capture.enabled,
                    AgentVersionDocument.order_index == capture.order_index,
                )
                .values(document_id=new_document.id)
            )
            if getattr(relation_changed, "rowcount", 0) != 1:
                raise stale_revision(capture.revision)
            version_changed = db.execute(
                update(AgentVersion)
                .where(
                    AgentVersion.id == capture.version_id,
                    AgentVersion.state == "draft",
                    AgentVersion.revision == capture.revision,
                )
                .values(
                    revision=AgentVersion.revision + 1,
                    updated_at=timestamp,
                    persona_confirmation_revision=case(
                        (
                            AgentVersion.persona_confirmation_revision.is_not(None),
                            AgentVersion.revision + 1,
                        ),
                        else_=None,
                    ),
                )
            )
            if getattr(version_changed, "rowcount", 0) != 1:
                raise stale_revision(capture.revision)
            affected_versions.append(capture.version_id)

        remaining_current_refs = db.scalar(
            select(AgentVersionDocument.agent_version_id)
            .join(AgentVersion, AgentVersion.id == AgentVersionDocument.agent_version_id)
            .where(
                AgentVersionDocument.document_id == old_document_id,
                AgentVersion.state == "draft",
            )
        )
        if remaining_current_refs is not None:
            raise invalid_state("The old Markdown remains referenced by a draft.")
        final_old.workspace_state = "hidden"
        final_old.updated_at = timestamp
        operation = load_file_operation(db, operation_id)
        operation.state = "committed"
        operation.updated_at = timestamp
        db.flush()
        checkpoint("replace.before_final_commit")
        return new_document, tuple(affected_versions), operation_id
    except PlatformError:
        try:
            recover_operation_now(db, data_root, operation_id)
        except Exception:
            try:
                transition_file_operation(
                    db,
                    operation_id,
                    "cleanup_required",
                    safe_error_code="file_operation_failed",
                )
            except Exception:
                pass
        raise
    except Exception:
        # A database/index exception may occur after BEGIN IMMEDIATE.  Release
        # that transaction before the independent journal transition so the
        # cleanup marker is durable instead of waiting on our own writer lock.
        db.rollback()
        try:
            transition_file_operation(
                db,
                operation_id,
                "cleanup_required",
                safe_error_code="file_operation_failed",
            )
        except Exception:
            pass
        raise
