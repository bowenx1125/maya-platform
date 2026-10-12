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
from uuid import UUID, uuid4, uuid5

from sqlalchemy import case, select, text, update
from sqlalchemy.orm import Session

from app.core.errors import (
    PlatformError,
    invalid_state,
    not_found,
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
from app.modules.knowledge.markdown import MarkdownDocument, build_chunks
from app.modules.knowledge.services import (
    assert_claim_owned,
    can_mutate_source,
    create_file_operation,
    document_file_content,
    load_file_operation,
    now_utc,
    recover_operation_now,
    replace_document_chunks,
    saga_checkpoint,
    transition_file_operation,
)
from app.modules.knowledge_sets.models import (
    KnowledgeDocumentVersion,
    KnowledgeGenerationRun,
    KnowledgeSet,
    KnowledgeSetSource,
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
    actor_user_id: str,
    enqueued_generation_run_ids: list[str] | None = None,
    checkpoint: Callable[[str], None] = saga_checkpoint,
) -> tuple[KnowledgeDocument, tuple[str, ...], str]:
    """Append one Markdown version while keeping its logical document ID.

    Filesystem work deliberately happens before the final writer transaction.
    Until that transaction commits, the new immutable version has no current
    pointer and cannot appear in the library, upload candidates or previews.
    A durable ``document_replace`` journal owns staging and promotion so each
    failure path can remove only its own tree.

    The source ID is the stable logical resource key. Old bytes, hashes and
    source receipts stay attached to immutable version rows while RAG's live
    chunks and active Set bindings advance together.
    """

    old_document = db.get(KnowledgeDocument, old_document_id)
    if old_document is None:
        raise not_found()
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
    captured_owner_user_id = old_document.owner_user_id
    captured_course_id = old_document.course_id
    captured_scope = old_document.ownership_scope
    captured_visibility = old_document.visibility
    captured_authorization_epoch = old_document.authorization_epoch
    captured_version_seq = old_document.content_version_seq
    content_changed = replacement.content_hash != captured_content_hash
    captured_references = _draft_document_references(db, old_document_id)
    expected_source_sha = hashlib.sha256(source_bytes).hexdigest()
    expected_source_size = len(source_bytes)

    if (
        replacement.content_hash == captured_content_hash
        and expected_source_sha == captured_stored_sha
    ):
        # A filename-only edit changes the visible name while keeping the
        # indexed content, receipts and generation inputs identical.
        db.rollback()
        db.execute(text("BEGIN IMMEDIATE"))
        record = db.get(IdempotencyRecord, idempotency_record_id)
        final_old = db.get(KnowledgeDocument, old_document_id)
        if record is None:
            raise invalid_state("The idempotency claim could not be loaded.")
        assert_claim_owned(db, record)
        if final_old is None or not can_mutate_source(db, actor_user_id, final_old):
            raise not_found()
        if (
            final_old.workspace_state != "active"
            or final_old.content_hash != captured_content_hash
            or final_old.index_revision != captured_index_revision
            or final_old.content_version_seq != captured_version_seq
            or final_old.stored_file_id != captured_stored_id
        ):
            raise stale_revision(final_old.index_revision)
        final_stored = final_old.stored_file
        if (
            final_stored is None
            or final_stored.relative_path != captured_stored_path
            or final_stored.sha256 != captured_stored_sha
        ):
            raise stale_revision(final_old.index_revision)
        if _draft_document_references(db, old_document_id) != captured_references:
            raise invalid_state("The draft document references changed during replacement.")
        if final_old.source_filename == replacement.filename:
            return final_old, (), ""
        timestamp = now_utc()
        final_old.source_filename = replacement.filename
        final_old.updated_at = timestamp
        for source in db.scalars(
            select(KnowledgeSetSource).where(
                KnowledgeSetSource.document_id == old_document_id,
                KnowledgeSetSource.is_active.is_(True),
            )
        ).all():
            if source.source_filename != replacement.filename:
                source.source_filename = replacement.filename
                db.execute(
                    update(KnowledgeSet)
                    .where(KnowledgeSet.id == source.knowledge_set_id)
                    .values(
                        content_revision=KnowledgeSet.content_revision + 1,
                        updated_at=timestamp,
                    )
                    .execution_options(synchronize_session=False)
                )
        affected_versions: list[str] = []
        for capture in captured_references:
            changed = db.execute(
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
            if getattr(changed, "rowcount", 0) != 1:
                raise stale_revision(capture.revision)
            affected_versions.append(capture.version_id)
        checkpoint("replace.before_final_commit")
        return final_old, tuple(affected_versions), ""

    operation_id = str(uuid4())
    new_document_id = old_document_id
    staging_root = f"tmp/publish/{operation_id}"
    staging_path = f"{staging_root}/source.md"
    target_root = (
        f"groups/{captured_group_id}/knowledge/{new_document_id}"
        if captured_visibility == "public" and captured_group_id is not None
        else f"users/{captured_owner_user_id}/knowledge/{new_document_id}"
    )
    next_version_seq = captured_version_seq + 1
    target_path = f"{target_root}/versions/{next_version_seq}-{operation_id}/source.md"

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
        if content_changed:
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
        # A competing owner replacement may have already hidden this exact
        # source. Preserve owner-scoped CAS semantics (409 below) while still
        # rejecting guessed IDs before exposing that state to other actors.
        if not can_mutate_source(db, actor_user_id, final_old, require_active=False):
            raise not_found()
        if final_old.workspace_state != "active":
            raise stale_revision(final_old.index_revision)
        final_stored = final_old.stored_file
        if (
            final_old.group_id != captured_group_id
            or final_old.owner_user_id != captured_owner_user_id
            or final_old.course_id != captured_course_id
            or final_old.ownership_scope != captured_scope
            or final_old.visibility != captured_visibility
            or final_old.authorization_epoch != captured_authorization_epoch
            or final_old.content_hash != captured_content_hash
            or final_old.index_revision != captured_index_revision
            or final_old.content_version_seq != captured_version_seq
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

        timestamp = now_utc()
        current_version = db.scalar(
            select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.document_id == final_old.id,
                KnowledgeDocumentVersion.version_seq == captured_version_seq,
            )
        )
        if current_version is None:
            # Isolated pre-migration test databases and older imported rows
            # receive the exact previous head before the stable ID advances.
            current_version = KnowledgeDocumentVersion(
                id=str(uuid4()),
                document_id=final_old.id,
                version_seq=captured_version_seq,
                stored_file_id=captured_stored_id,
                source_filename=final_old.source_filename,
                char_count=final_old.char_count,
                index_revision=final_old.index_revision,
                content_hash=final_old.content_hash,
                file_sha256=captured_stored_sha,
                authorization_epoch=final_old.authorization_epoch,
                created_by_user_id=None,
                created_at=final_old.created_at,
            )
            db.add(current_version)
            db.flush()
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
        db.add(stored_file)
        db.flush()
        version_row = KnowledgeDocumentVersion(
            id=str(uuid4()),
            document_id=final_old.id,
            version_seq=next_version_seq,
            stored_file_id=stored_file.id,
            source_filename=replacement.filename,
            char_count=replacement.char_count,
            index_revision=captured_index_revision + int(content_changed),
            content_hash=replacement.content_hash,
            file_sha256=expected_source_sha,
            authorization_epoch=captured_authorization_epoch,
            created_by_user_id=actor_user_id,
            created_at=timestamp,
        )
        db.add(version_row)
        db.flush()
        db.add(
            FileReference(
                id=str(uuid4()),
                stored_file_id=captured_stored_id,
                owner_type="knowledge_document_version",
                owner_id=current_version.id,
                purpose="history",
                created_at=timestamp,
            )
        )
        current_references = db.scalars(
            select(FileReference).where(
                FileReference.owner_type == "knowledge_document",
                FileReference.owner_id == final_old.id,
                FileReference.purpose == "source",
            )
        ).all()
        if current_references:
            for reference in current_references:
                reference.stored_file_id = stored_file.id
        else:
            db.add(
                FileReference(
                    id=str(uuid4()),
                    stored_file_id=stored_file.id,
                    owner_type="knowledge_document",
                    owner_id=final_old.id,
                    purpose="source",
                    created_at=timestamp,
                )
            )

        # The document ID and every published source reference stay stable;
        # its separate snapshot files are not rewritten by this edit.
        final_old.source_filename = replacement.filename
        final_old.stored_file_id = stored_file.id
        final_old.char_count = replacement.char_count
        final_old.index_status = "ready"
        final_old.index_revision = captured_index_revision + int(content_changed)
        final_old.content_version_seq = next_version_seq
        final_old.content_hash = replacement.content_hash
        final_old.updated_at = timestamp
        if content_changed:
            assert chunks is not None
            replace_document_chunks(db, final_old, chunks)
            db.add(
                Job(
                    id=str(uuid4()),
                    document_id=final_old.id,
                    operation="replace_document",
                    state="completed",
                    attempt=index_attempts,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )

        # Drafts use the live source and must refresh their revision. Published
        # snapshots keep their independently frozen StoredFile references.
        affected_drafts: list[str] = []
        for capture in captured_references:
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
            affected_drafts.append(capture.version_id)

        affected_set_ids: set[str] = set()
        active_bindings = db.scalars(
            select(KnowledgeSetSource).where(
                KnowledgeSetSource.document_id == final_old.id,
                KnowledgeSetSource.is_active.is_(True),
            )
        ).all()
        for source in active_bindings:
            source.stored_file_id = stored_file.id
            source.source_content_hash = replacement.content_hash
            source.source_file_sha256 = expected_source_sha
            source.source_authorization_epoch = final_old.authorization_epoch
            source.source_index_revision = final_old.index_revision
            source.source_filename = replacement.filename
            affected_set_ids.add(source.knowledge_set_id)
        for set_id in affected_set_ids:
            db.execute(
                update(KnowledgeSet)
                .where(KnowledgeSet.id == set_id, KnowledgeSet.deleted_at.is_(None))
                .values(
                    content_revision=KnowledgeSet.content_revision + 1,
                    updated_at=timestamp,
                )
                .execution_options(synchronize_session=False)
            )
        if content_changed:
            from app.modules.knowledge_sets.generation import enqueue_generation_for_existing_set

            action_namespace = UUID("efdf85a2-3c5f-4f52-8f52-b4dd45e22d90")
            for set_id in sorted(affected_set_ids):
                prior_generation = db.scalar(
                    select(KnowledgeGenerationRun)
                    .where(KnowledgeGenerationRun.knowledge_set_id == set_id)
                    .order_by(
                        KnowledgeGenerationRun.created_at.desc(), KnowledgeGenerationRun.id.desc()
                    )
                    .limit(1)
                )
                if prior_generation is None or prior_generation.owner_user_id != actor_user_id:
                    continue
                action_id = str(
                    uuid5(
                        action_namespace,
                        f"rag:{set_id}:{final_old.id}:{final_old.content_version_seq}",
                    )
                )
                try:
                    queued = enqueue_generation_for_existing_set(
                        db,
                        set_id=set_id,
                        owner_user_id=actor_user_id,
                        action_id=action_id,
                    )
                except PlatformError as exc:
                    # Editing a source is separately authorized from running
                    # the Agent that consumes it. A revoked or raced generator
                    # fences only its task; the valid source save still commits.
                    if exc.status_code not in {404, 409}:
                        raise
                    continue
                if enqueued_generation_run_ids is not None:
                    enqueued_generation_run_ids.append(queued.run.id)

        operation = load_file_operation(db, operation_id)
        operation.state = "committed"
        operation.updated_at = timestamp
        db.flush()
        checkpoint("replace.before_final_commit")
        return final_old, tuple(affected_drafts), operation_id
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
