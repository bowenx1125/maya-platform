"""Markdown library, deterministic RAG and immutable snapshot routes."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import case, delete, or_, select, text, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, get_settings
from app.core.errors import (
    Error,
    PlatformError,
    conflict,
    invalid_state,
    not_found,
    stale_revision,
    validation_failure,
    version_immutable,
)
from app.core.models import (
    Agent,
    AgentVersion,
    AgentVersionDocument,
    FileReference,
    Group,
    Job,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    SnapshotDocument,
    StoredFile,
)
from app.modules.agents.schemas import (
    AgentVersion as AgentVersionDTO,
)
from app.modules.agents.schemas import (
    KnowledgeDocumentMutation,
    KnowledgeSnapshot,
    RagPreview,
    SetDocumentsRequest,
)
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext
from app.modules.demo_baseline.service import (
    reject_baseline_document_mutation,
    reject_baseline_version_mutation,
)
from app.modules.knowledge.files import (
    content_disposition,
    frozen_download_filename,
    promote_atomic,
    read_contained,
    remove_empty_directory,
    stage_atomic,
    verify_staged,
)
from app.modules.knowledge.ingest import (
    INGEST_VERSION,
    KnowledgeImportError,
    convert_knowledge_upload,
)
from app.modules.knowledge.markdown import (
    MarkdownInputError,
    build_chunks,
    normalize_markdown,
)
from app.modules.knowledge.multipart import UploadTooLargeError, integer_field, parse_upload
from app.modules.knowledge.replacement import replace_document_copy_on_write
from app.modules.knowledge.schemas import JobStatus, UpdateKnowledgeDocumentVisibility
from app.modules.knowledge.schemas import KnowledgeDocument as KnowledgeDocumentDTO
from app.modules.knowledge.services import (
    _document_dto,
    _enabled_documents,
    abandon_claim,
    assert_claim_owned,
    can_bind_source,
    can_mutate_source,
    claim_idempotency,
    course_member_role,
    create_file_operation,
    document_file_content,
    finish_idempotency,
    job_dto,
    load_file_operation,
    parse_json_payload_hash,
    rag_preview,
    recover_operation_now,
    renew_idempotency_lease,
    replace_document_chunks,
    saga_checkpoint,
    scoped_student_group_role,
    snapshot_dto,
    transition_file_operation,
    version_dto,
    visible_mutable_document,
    visible_snapshot,
    visible_student_document,
    visible_student_version,
)
from app.modules.knowledge_sets.models import KnowledgeDocumentVersion, KnowledgeSetSource

router = APIRouter(tags=["Knowledge"])
KNOWLEDGE_UPLOAD_LEASE_SECONDS = 90

_UPLOAD_BODY = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": ["file"],
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                    "target_agent_version_id": {"type": "string", "format": "uuid"},
                    "expected_revision": {"type": "integer", "minimum": 0},
                    "visibility": {"type": "string", "enum": ["private", "public"]},
                },
            }
        }
    },
}


def _raise_knowledge_import_failure(reason: str) -> None:
    if reason in {"upload_size", "pdf_limit", "docx_limit"}:
        raise validation_failure(
            "The document exceeds the local PDF/Word conversion capacity. "
            "Convert it to Markdown externally and upload that Markdown.",
            code="knowledge_import_too_large",
        )
    if reason == "unsupported_format":
        raise validation_failure(
            "Upload Markdown, PDF or Word (.docx).", code="knowledge_import_unsupported"
        )
    if reason in {"pdf_no_text", "docx_no_text"}:
        raise validation_failure(
            "No readable text could be extracted from this document.",
            code="knowledge_import_no_text",
        )
    raise validation_failure(
        "The document could not be converted safely. "
        "Keep the original and upload converted Markdown.",
        code="knowledge_import_processing_failed",
    )


def _now() -> datetime:
    return datetime.now(UTC)


@router.get(
    "/groups/{group_id}/knowledge-documents",
    response_model=list[KnowledgeDocumentDTO],
    operation_id="listKnowledgeDocuments",
    responses={
        200: {
            "model": list[KnowledgeDocumentDTO],
            "description": "Current group Markdown library.",
        },
        404: {"model": Error, "description": "Group not found."},
    },
)
def list_knowledge_documents(
    group_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[KnowledgeDocumentDTO]:
    scoped_student_group_role(db, context, str(group_id))
    docs = db.scalars(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.group_id == str(group_id),
            KnowledgeDocument.workspace_state == "active",
            or_(
                KnowledgeDocument.owner_user_id == context.user.id,
                KnowledgeDocument.visibility == "public",
            ),
        )
        .order_by(KnowledgeDocument.created_at, KnowledgeDocument.id)
    ).all()
    return [
        _document_dto(
            document,
            can_manage_visibility=document.owner_user_id == context.user.id,
        )
        for document in docs
    ]


@router.get(
    "/courses/{course_id}/workspace-documents",
    response_model=list[KnowledgeDocumentDTO],
    operation_id="listCourseWorkspaceDocuments",
    responses={404: {"model": Error, "description": "Course not found."}},
)
def list_course_workspace_documents(
    course_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[KnowledgeDocumentDTO]:
    course_key = str(course_id)
    if course_member_role(db, context.user.id, course_key) != "teacher":
        raise not_found()
    documents = db.scalars(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.course_id == course_key,
            KnowledgeDocument.owner_user_id == context.user.id,
            KnowledgeDocument.ownership_scope == "personal",
            KnowledgeDocument.workspace_state == "active",
        )
        .order_by(KnowledgeDocument.created_at, KnowledgeDocument.id)
    ).all()
    return [_document_dto(document, can_manage_visibility=True) for document in documents]


@router.post(
    "/courses/{course_id}/workspace-documents",
    response_model=KnowledgeDocumentMutation,
    status_code=201,
    operation_id="uploadCourseWorkspaceDocument",
    openapi_extra={"requestBody": _UPLOAD_BODY},
    responses={
        201: {"model": KnowledgeDocumentMutation, "description": "Document stored and indexed."},
        404: {"model": Error, "description": "Course or draft not found."},
        409: {"model": Error, "description": "Revision or idempotency conflict."},
        422: {"model": Error, "description": "Invalid Markdown upload."},
    },
)
@router.post(
    "/groups/{group_id}/knowledge-documents",
    response_model=KnowledgeDocumentMutation,
    status_code=201,
    operation_id="uploadKnowledgeDocument",
    openapi_extra={"requestBody": _UPLOAD_BODY},
    responses={
        201: {"model": KnowledgeDocumentMutation, "description": "Document stored and indexed."},
        404: {"model": Error, "description": "Group or draft not found."},
        409: {"model": Error, "description": "Revision or idempotency conflict."},
        422: {"model": Error, "description": "Invalid Markdown upload."},
    },
)
async def upload_knowledge_document(
    request: Request,
    group_id: UUID | None = None,
    course_id: UUID | None = None,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> KnowledgeDocumentMutation:
    if (group_id is None) == (course_id is None):
        raise not_found()
    personal_workspace = course_id is not None
    scope_key = str(course_id or group_id)
    resource_course_id: str
    if personal_workspace:
        if course_member_role(db, context.user.id, scope_key) != "teacher":
            raise not_found()
        group_role = "owner"
        resource_course_id = scope_key
    else:
        assert group_id is not None
        group_role = scoped_student_group_role(db, context, str(group_id))
        group_course_id = db.scalar(select(Group.course_id).where(Group.id == str(group_id)))
        if group_course_id is None:
            raise not_found()
        resource_course_id = group_course_id
    try:
        fields, source_filename, source_content = await parse_upload(request)
    except UploadTooLargeError:
        _raise_knowledge_import_failure("upload_size")
    except (ValueError, UnicodeDecodeError):
        _raise_knowledge_import_failure("invalid")
    source_sha256 = hashlib.sha256(source_content).hexdigest()
    source_owner_role = course_member_role(db, context.user.id, resource_course_id)
    try:
        target_id_raw = fields.get("target_agent_version_id")
        target_id = str(UUID(target_id_raw)) if target_id_raw else None
        expected_revision = integer_field(fields, "expected_revision", required=False)
        visibility = fields.get("visibility", "private")
        if visibility not in {"private", "public"}:
            raise ValueError("visibility must be private or public")
    except (ValueError, MarkdownInputError, UnicodeDecodeError):
        raise validation_failure(
            "The Markdown upload is not valid.", code="file_operation_failed"
        ) from None
    # A target draft keeps the original Wave 1A CAS contract.  Omitting it
    # creates a group-library document only; in particular it does not create
    # or enable an AgentVersion relation.  Teachers retain read-only access to
    # this endpoint and therefore cannot use the standalone create path.
    if target_id is not None:
        reject_baseline_version_mutation(target_id)
    scoped = visible_student_version(db, context, target_id) if target_id else None
    if target_id and scoped is not None:
        if personal_workspace:
            if (
                scoped.agent.ownership_scope != "personal"
                or scoped.agent.group_id is not None
                or scoped.agent.owner_user_id != context.user.id
                or scoped.agent.course_id != resource_course_id
            ):
                raise not_found()
        elif scoped.agent.group_id != str(group_id):
            raise not_found()
    if target_id and scoped is not None and scoped.version.state != "draft":
        raise version_immutable()
    if target_id and scoped is not None:
        # RAG uploaded into an Agent takes that Agent's Private or Public, so a
        # private Agent's material never reaches the group's Brainform and a
        # public Agent's material is shared with the group it serves.
        if "visibility" not in fields:
            visibility = scoped.agent.visibility
        elif visibility != scoped.agent.visibility:
            raise conflict(
                "document_visibility_follows_agent",
                "RAG added to an Agent has the same Private or Public as the Agent.",
            )
    if (
        target_id
        and scoped is not None
        and visibility == "private"
        and scoped.agent.owner_user_id != context.user.id
    ):
        raise not_found()
    if target_id and expected_revision is None and scoped is not None:
        # The multipart contract keeps this field wire-optional, but the
        # business operation is always CAS-protected.  Resolve the
        # authorized draft first so the response carries its current
        # revision and cannot be used as an existence oracle.
        raise stale_revision(scoped.version.revision)
    if target_id is None and group_role not in {"student", "owner"}:
        raise not_found()
    body_hash = parse_json_payload_hash(
        "uploadKnowledgeDocument",
        context,
        [scope_key, "personal" if personal_workspace else "group", target_id or "library"],
        {
            "upload_filename": source_filename,
            "upload_sha256": source_sha256,
            "ingest_version": INGEST_VERSION,
            "target_agent_version_id": target_id,
            "expected_revision": expected_revision,
            "visibility": visibility,
        },
    )
    record, replay = claim_idempotency(
        db,
        context,
        "uploadKnowledgeDocument",
        idempotency_key,
        body_hash,
        data_root=settings.resolved_data_root,
    )
    if replay is not None:
        return KnowledgeDocumentMutation.model_validate(json.loads(bytes(replay.body)))
    operation_id: str | None = None
    final_committed = False
    try:
        # Re-read all mutable state after the independently committed claim.
        # This is the authoritative pre-staging check; no file is touched if
        # the draft has already advanced.
        db.rollback()
        if personal_workspace and course_member_role(db, context.user.id, scope_key) != "teacher":
            raise not_found()
        if not personal_workspace:
            assert group_id is not None
            scoped_student_group_role(db, context, str(group_id))
        scoped = visible_student_version(db, context, target_id) if target_id else None
        if target_id and scoped is not None:
            wrong_scope = (
                scoped.agent.ownership_scope != "personal"
                or scoped.agent.owner_user_id != context.user.id
                or scoped.agent.course_id != resource_course_id
                if personal_workspace
                else scoped.agent.group_id != str(group_id)
            )
            if wrong_scope or scoped.version.state != "draft":
                raise version_immutable() if scoped.version.state != "draft" else not_found()
            if scoped.version.revision != expected_revision:
                raise stale_revision(scoped.version.revision)
            current_docs = _enabled_documents(db, scoped.version.id)
        else:
            current_docs = []

        try:
            renew_idempotency_lease(db, record, lease_seconds=KNOWLEDGE_UPLOAD_LEASE_SECONDS)
            filename, content = await run_in_threadpool(
                convert_knowledge_upload, source_filename, source_content
            )
            document = normalize_markdown(filename, content)
        except KnowledgeImportError as exc:
            _raise_knowledge_import_failure(exc.reason)
        except (MarkdownInputError, UnicodeDecodeError, ValueError):
            _raise_knowledge_import_failure("invalid")
        timestamp = _now()
        document_id = str(uuid4())
        operation_id = str(uuid4())
        relative_path = (
            f"groups/{group_id}/knowledge/{document_id}/source.md"
            if visibility == "public" and not personal_workspace
            else f"users/{context.user.id}/knowledge/{document_id}/source.md"
        )
        staging_root = f"tmp/publish/{operation_id}"
        staging_path = f"{staging_root}/source.md"
        create_file_operation(
            db,
            operation_id=operation_id,
            idempotency_record_id=record.id,
            operation_kind="document_upload",
            entity_id=document_id,
            request_id=str(uuid4()),
            source_relative_path=staging_root,
            target_relative_path=relative_path,
            expected_sha256=document.source_sha256,
            claim_token=record.claim_token,
        )
        saga_checkpoint("upload.prepared")

        assert_claim_owned(db, record)
        expected_sha, expected_size = document.source_sha256, len(content)
        staged_sha, staged_size = stage_atomic(
            settings.resolved_data_root,
            staging_path,
            content,
        )
        if staged_sha != expected_sha or staged_size != expected_size:
            raise PlatformError(
                "file_operation_failed",
                "The staged Markdown could not be verified.",
                503,
            )
        verify_staged(
            settings.resolved_data_root,
            staging_path,
            expected_sha,
            expected_size,
        )
        assert_claim_owned(db, record)
        transition_file_operation(
            db,
            operation_id,
            "staged",
            expected_state="prepared",
            expected_sha256=expected_sha,
            idempotency_record_id=record.id,
            claim_token=record.claim_token,
        )
        saga_checkpoint("upload.staged")

        # Build the full replacement before any final DB mutation.  A failed
        # provider/index calculation therefore cannot erase an existing
        # index; a newly uploaded document simply commits as failed below.
        chunks = None
        index_attempts = 0
        for attempt in range(2):
            index_attempts = attempt + 1
            try:
                chunks = build_chunks(document.normalized)
                break
            except Exception:
                if attempt == 1:
                    chunks = None
        assert_claim_owned(db, record)
        promote_atomic(settings.resolved_data_root, staging_path, relative_path)
        remove_empty_directory(settings.resolved_data_root, staging_root)
        verify_staged(
            settings.resolved_data_root,
            relative_path,
            expected_sha,
            expected_size,
        )
        transition_file_operation(
            db,
            operation_id,
            "promoted",
            expected_state="staged",
            idempotency_record_id=record.id,
            claim_token=record.claim_token,
        )
        saga_checkpoint("upload.promoted")

        # A promoted orphan is not visible until this one conditional DB
        # transaction succeeds.  Revalidate scope, revision and source bytes
        # after the filesystem boundary to make races deterministic.
        db.rollback()
        assert_claim_owned(db, record)
        if personal_workspace and course_member_role(db, context.user.id, scope_key) != "teacher":
            raise not_found()
        if not personal_workspace:
            assert group_id is not None
            scoped_student_group_role(db, context, str(group_id))
        scoped = visible_student_version(db, context, target_id) if target_id else None
        if target_id and scoped is not None:
            wrong_scope = (
                scoped.agent.ownership_scope != "personal"
                or scoped.agent.owner_user_id != context.user.id
                or scoped.agent.course_id != resource_course_id
                if personal_workspace
                else scoped.agent.group_id != str(group_id)
            )
            if wrong_scope or scoped.version.state != "draft":
                raise version_immutable() if scoped.version.state != "draft" else not_found()
            if scoped.version.revision != expected_revision:
                raise stale_revision(scoped.version.revision)
            current_docs = _enabled_documents(db, scoped.version.id)
            changed = db.execute(
                update(AgentVersion)
                .where(
                    AgentVersion.id == scoped.version.id,
                    AgentVersion.state == "draft",
                    AgentVersion.revision == expected_revision,
                )
                .values(
                    revision=AgentVersion.revision + 1,
                    updated_at=_now(),
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
                current_revision = db.scalar(
                    select(AgentVersion.revision).where(AgentVersion.id == scoped.version.id)
                )
                raise stale_revision(current_revision)
            db.refresh(scoped.version)
        elif not personal_workspace:
            assert group_id is not None
            scoped_student_group_role(db, context, str(group_id))
        stored_file = StoredFile(
            id=str(uuid4()),
            kind="markdown",
            relative_path=relative_path,
            sha256=expected_sha,
            size_bytes=expected_size,
            state="active",
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(stored_file)
        row = KnowledgeDocument(
            id=document_id,
            group_id=str(group_id) if group_id is not None else None,
            owner_user_id=context.user.id,
            course_id=resource_course_id,
            ownership_scope="personal" if personal_workspace else "group",
            visibility=visibility,
            authorization_epoch=0,
            source_filename=document.filename,
            source_owner_role=source_owner_role,
            stored_file_id=stored_file.id,
            char_count=document.char_count,
            index_status="ready" if chunks is not None else "failed",
            index_revision=1 if chunks is not None else 0,
            workspace_state="active",
            content_hash=document.content_hash,
            created_at=timestamp,
            updated_at=timestamp,
        )
        if chunks is None:
            row.safe_error_code = "provider_unavailable"
        db.add(row)
        db.flush()
        db.add(
            FileReference(
                id=str(uuid4()),
                stored_file_id=stored_file.id,
                owner_type="knowledge_document",
                owner_id=row.id,
                purpose="source",
                created_at=timestamp,
            )
        )
        job = Job(
            id=str(uuid4()),
            document_id=row.id,
            operation="index_document",
            state="completed" if chunks is not None else "failed",
            safe_error_code=None if chunks is not None else "provider_unavailable",
            attempt=index_attempts,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(job)
        if chunks is not None:
            replace_document_chunks(db, row, chunks)
        if target_id and scoped is not None:
            db.add(
                AgentVersionDocument(
                    agent_version_id=scoped.version.id,
                    document_id=row.id,
                    enabled=True,
                    order_index=len(current_docs),
                )
            )
            if visibility != "public" or scoped.agent.visibility != "public":
                scoped.version.draft_visibility = "private"
        operation = load_file_operation(db, operation_id)
        operation.state = "committed"
        operation.updated_at = _now()
        result = KnowledgeDocumentMutation(
            document=_document_dto(row, can_manage_visibility=True),
            agent_version=(
                version_dto(
                    db,
                    scoped.version,
                    scoped.agent,
                    include_private_sources=scoped.agent.owner_user_id == context.user.id,
                )
                if target_id and scoped is not None
                else None
            ),
        )
        result_payload = result.model_dump(mode="json")
        finish_idempotency(db, record, 201, result_payload)
        db.flush()
        saga_checkpoint("upload.before_final_commit")
        db.commit()
        final_committed = True
        saga_checkpoint("upload.after_final_commit")
        return result
    except PlatformError:
        if operation_id is not None and not final_committed:
            try:
                recover_operation_now(db, settings.resolved_data_root, operation_id)
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
            finally:
                abandon_claim(db, record)
        else:
            abandon_claim(db, record)
        raise
    except Exception:
        # Unexpected errors represent a crash/infrastructure boundary.  Keep
        # the durable journal and pending claim for startup recovery rather
        # than deleting an orphan based on an incomplete in-memory decision.
        if operation_id is not None and not final_committed:
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


@router.post(
    "/knowledge-documents/{document_id}/replace",
    response_model=KnowledgeDocumentDTO,
    status_code=201,
    operation_id="replaceKnowledgeDocument",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": [
                            "file",
                            "expected_content_hash",
                            "expected_index_revision",
                        ],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "expected_content_hash": {"type": "string"},
                            "expected_index_revision": {
                                "type": "integer",
                                "minimum": 0,
                            },
                        },
                    }
                }
            },
        }
    },
    responses={
        201: {"model": KnowledgeDocumentDTO, "description": "Immutable replacement created."},
        404: {"model": Error, "description": "Document not found."},
        409: {"model": Error, "description": "Replacement CAS conflict."},
        422: {"model": Error, "description": "Invalid Markdown replacement."},
    },
)
async def replace_knowledge_document(
    document_id: UUID,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> KnowledgeDocumentDTO:
    """Edit one group Markdown source using copy-on-write semantics."""

    reject_baseline_document_mutation(str(document_id))
    # Keep owner-scoped stale CAS requests distinguishable from guessed
    # cross-scope IDs. A winning replacement hides the old source, so a
    # concurrent request by its owner must still reach the 409 CAS branch.
    scoped = visible_mutable_document(db, context, str(document_id), require_active=False)
    try:
        fields, source_filename, source_content = await parse_upload(request)
    except UploadTooLargeError:
        _raise_knowledge_import_failure("upload_size")
    except (ValueError, UnicodeDecodeError):
        _raise_knowledge_import_failure("invalid")
    try:
        filename, content = await run_in_threadpool(
            convert_knowledge_upload, source_filename, source_content
        )
        replacement = normalize_markdown(filename, content)
        expected_content_hash = fields.get("expected_content_hash")
        if (
            expected_content_hash is None
            or len(expected_content_hash) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in expected_content_hash)
        ):
            raise ValueError("expected_content_hash is invalid")
        expected_index_revision = integer_field(fields, "expected_index_revision", required=True)
    except KnowledgeImportError as exc:
        _raise_knowledge_import_failure(exc.reason)
    except (ValueError, MarkdownInputError, UnicodeDecodeError):
        raise validation_failure(
            "The Markdown replacement is not valid.", code="file_operation_failed"
        ) from None
    body_hash = parse_json_payload_hash(
        "replaceKnowledgeDocument",
        context,
        [str(document_id), scoped.document.group_id or scoped.document.course_id],
        {
            "old_document_id": str(document_id),
            "expected_content_hash": expected_content_hash,
            "expected_index_revision": expected_index_revision,
            "filename": replacement.filename,
            "content_hash": replacement.content_hash,
            "source_sha256": replacement.source_sha256,
        },
    )
    record, replay = claim_idempotency(
        db,
        context,
        "replaceKnowledgeDocument",
        idempotency_key,
        body_hash,
        data_root=settings.resolved_data_root,
    )
    if replay is not None:
        return KnowledgeDocumentDTO.model_validate(json.loads(bytes(replay.body)))

    try:
        # A successful stable-ID write advances the document head, so an
        # identical retry must resolve from its accepted idempotency record
        # before comparing the old expected hash/revision with that new head.
        if (
            scoped.document.content_hash != expected_content_hash
            or expected_index_revision is None
            or scoped.document.index_revision != expected_index_revision
            or scoped.document.workspace_state != "active"
        ):
            raise stale_revision(scoped.document.index_revision)
        # ``replace_document_copy_on_write`` re-captures this source and all
        # draft references after the claim, stages/indexes/promotes bytes via
        # its typed journal, and owns the final BEGIN IMMEDIATE transaction.
        db.rollback()
        enqueued_run_ids: list[str] = []
        new_document, _affected_versions, _operation_id = replace_document_copy_on_write(
            db,
            settings.resolved_data_root,
            str(document_id),
            replacement,
            content,
            expected_content_hash=expected_content_hash,
            expected_index_revision=expected_index_revision,
            idempotency_record_id=record.id,
            claim_token=record.claim_token,
            actor_user_id=context.user.id,
            enqueued_generation_run_ids=enqueued_run_ids,
            checkpoint=saga_checkpoint,
        )
        result = _document_dto(
            new_document,
            can_manage_visibility=scoped.role == "owner",
        )
        finish_idempotency(db, record, 201, result.model_dump(mode="json"))
        db.flush()
        db.commit()
        saga_checkpoint("replace.after_final_commit")
        if not settings.is_test:
            task_manager = getattr(request.app.state, "knowledge_generation_task_manager", None)
            if task_manager is not None:
                for run_id in enqueued_run_ids:
                    task_manager.wake(run_id)
        return result
    except PlatformError:
        # The service has already recovered its promoted tree for business
        # failures.  Abandon only the idempotency claim; a crash-like generic
        # exception deliberately leaves its journal for startup recovery.
        abandon_claim(db, record)
        raise


@router.get(
    "/knowledge-documents/{document_id}",
    response_model=KnowledgeDocumentDTO,
    operation_id="getKnowledgeDocument",
    responses={
        200: {"model": KnowledgeDocumentDTO, "description": "Group-scoped document metadata."},
        404: {"model": Error, "description": "Document not found."},
    },
)
def get_knowledge_document(
    document_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> KnowledgeDocumentDTO:
    scoped = visible_student_document(db, context, str(document_id))
    return _document_dto(
        scoped.document,
        can_manage_visibility=scoped.document.owner_user_id == context.user.id,
    )


@router.patch(
    "/knowledge-documents/{document_id}",
    response_model=KnowledgeDocumentDTO,
    operation_id="updateKnowledgeDocumentVisibility",
    responses={
        200: {"model": KnowledgeDocumentDTO, "description": "Source visibility updated."},
        404: {"model": Error, "description": "Document not found."},
        409: {"model": Error, "description": "Source authorization revision conflict."},
    },
)
def update_knowledge_document_visibility(
    document_id: UUID,
    payload: UpdateKnowledgeDocumentVisibility,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> KnowledgeDocumentDTO:
    scoped = visible_mutable_document(db, context, str(document_id))
    if scoped.document.owner_user_id != context.user.id:
        raise not_found()
    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))
    current = db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == str(document_id),
            KnowledgeDocument.owner_user_id == context.user.id,
            KnowledgeDocument.course_id == scoped.document.course_id,
            KnowledgeDocument.authorization_epoch == payload.expected_authorization_epoch,
        )
    )
    if current is None:
        latest = db.scalar(
            select(KnowledgeDocument.authorization_epoch).where(
                KnowledgeDocument.id == str(document_id),
                KnowledgeDocument.owner_user_id == context.user.id,
            )
        )
        db.rollback()
        if latest is None:
            raise not_found()
        raise stale_revision(latest)
    if not can_mutate_source(db, context, current):
        db.rollback()
        raise not_found()
    if current.visibility != payload.visibility:
        current.visibility = payload.visibility
        current.authorization_epoch += 1
        current.updated_at = _now()
        if payload.visibility == "private":
            drafts = db.scalars(
                select(AgentVersion)
                .join(
                    AgentVersionDocument,
                    AgentVersionDocument.agent_version_id == AgentVersion.id,
                )
                .where(
                    AgentVersion.state == "draft",
                    AgentVersionDocument.document_id == current.id,
                    AgentVersionDocument.enabled.is_(True),
                )
            ).all()
            for draft in drafts:
                draft.draft_visibility = "private"
    db.flush()
    result = _document_dto(current, can_manage_visibility=True)
    db.commit()
    return result


@router.get(
    "/knowledge-documents/{document_id}/download",
    operation_id="downloadKnowledgeDocument",
    response_class=Response,
    responses={
        200: {
            "description": "Original Markdown bytes.",
            "content": {"text/markdown": {"schema": {"type": "string"}}},
        },
        404: {"model": Error, "description": "Document not found."},
    },
)
def download_knowledge_document(
    document_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    scoped = visible_student_document(db, context, str(document_id))
    return Response(
        document_file_content(settings.resolved_data_root, scoped.document),
        media_type="text/markdown",
        headers={"Content-Disposition": content_disposition(scoped.document.source_filename)},
    )


@router.post(
    "/knowledge-documents/{document_id}/reindex",
    response_model=JobStatus,
    status_code=202,
    operation_id="reindexKnowledgeDocument",
    responses={
        202: {"model": JobStatus, "description": "Indexing job accepted."},
        404: {"model": Error, "description": "Document not found."},
        409: {"model": Error, "description": "Indexing conflict."},
    },
)
def reindex_knowledge_document(
    document_id: UUID,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobStatus:
    reject_baseline_document_mutation(str(document_id))
    scoped = visible_mutable_document(db, context, str(document_id))
    body_hash = parse_json_payload_hash("reindexKnowledgeDocument", context, [str(document_id)], {})
    record, replay = claim_idempotency(
        db,
        context,
        "reindexKnowledgeDocument",
        idempotency_key,
        body_hash,
        data_root=settings.resolved_data_root,
    )
    if replay is not None:
        return replay  # type: ignore[return-value]
    assert_claim_owned(db, record)
    if scoped.document.workspace_state != "active":
        abandon_claim(db, record)
        raise not_found()
    timestamp = _now()
    job = Job(
        id=str(uuid4()),
        document_id=scoped.document.id,
        operation="reindex_document",
        state="running",
        attempt=scoped.document.index_revision + 1,
        created_at=timestamp,
        updated_at=timestamp,
    )
    scoped.document.index_status = "indexing"
    scoped.document.updated_at = timestamp
    db.add(job)
    # Persist the in-flight marker before computing.  A process crash after
    # this commit is recoverable as document=failed/job=interrupted.
    db.commit()
    saga_checkpoint("reindex.started")

    chunks = None
    source_valid = True
    try:
        raw = document_file_content(settings.resolved_data_root, scoped.document)
        stored = scoped.document.stored_file
        if stored is None or hashlib.sha256(raw).hexdigest() != stored.sha256:
            source_valid = False
        normalized = (
            normalize_markdown(scoped.document.source_filename, raw).normalized
            if source_valid
            else ""
        )
    except Exception:
        normalized = ""
        source_valid = False
    if source_valid and normalized:
        for attempt in range(2):
            job.attempt = attempt + 1
            try:
                chunks = build_chunks(normalized)
                break
            except Exception:
                if attempt == 1:
                    chunks = None
    saga_checkpoint("reindex.computed")

    try:
        db.rollback()
        assert_claim_owned(db, record)
        final_scoped = visible_mutable_document(db, context, str(document_id))
        final_job = db.get(Job, job.id)
        if final_job is None:
            raise invalid_state("The indexing job could not be recovered.")
        final_raw = document_file_content(settings.resolved_data_root, final_scoped.document)
        stored = final_scoped.document.stored_file
        unchanged = stored is not None and hashlib.sha256(final_raw).hexdigest() == stored.sha256
        if chunks is not None and unchanged and source_valid:
            replace_document_chunks(db, final_scoped.document, chunks)
            final_scoped.document.index_revision += 1
            final_scoped.document.index_status = "ready"
            final_scoped.document.safe_error_code = None
            final_job.state = "completed"
            final_job.safe_error_code = None
        else:
            # Keep the previous complete index intact on computation/source
            # failure; only the status/job become failed and block publish.
            final_scoped.document.index_status = "failed"
            final_scoped.document.safe_error_code = "provider_unavailable"
            final_job.state = "failed"
            final_job.safe_error_code = "provider_unavailable"
        final_job.updated_at = _now()
        result = job_dto(final_job)
        finish_idempotency(db, record, 202, result.model_dump(mode="json"))
        db.flush()
        saga_checkpoint("reindex.before_final_commit")
        db.commit()
        saga_checkpoint("reindex.after_final_commit")
        return result
    except PlatformError:
        # The in-flight marker remains durable for startup recovery.  Only
        # pre-start validation paths abandon the claim.
        raise


@router.post(
    "/knowledge-documents/{document_id}/hide",
    response_model=KnowledgeDocumentDTO,
    operation_id="hideKnowledgeDocument",
    responses={
        200: {
            "model": KnowledgeDocumentDTO,
            "description": (
                "Removed from the group Knowledge library; published snapshots stay intact."
            ),
        },
        404: {"model": Error, "description": "Document not found."},
        409: {"model": Error, "description": "Document is still enabled by a draft."},
    },
)
def hide_knowledge_document(
    document_id: UUID,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> KnowledgeDocumentDTO:
    """Remove a source from the working Knowledge library.

    Published Agent snapshots keep their own frozen RAG copy.  When a snapshot
    still points at this document id for lineage, the row stays for the FK and
    only leaves the library (workspace_state=hidden).  When nothing published
    depends on the row, it is deleted outright.  Either path must never rewrite
    snapshot bytes or snapshot document rows.
    """

    reject_baseline_document_mutation(str(document_id))
    scoped = visible_mutable_document(db, context, str(document_id))
    body_hash = parse_json_payload_hash("hideKnowledgeDocument", context, [str(document_id)], {})
    record, replay = claim_idempotency(
        db, context, "hideKnowledgeDocument", idempotency_key, body_hash
    )
    if replay is not None:
        return replay  # type: ignore[return-value]
    assert_claim_owned(db, record)
    enabled = db.scalar(
        select(AgentVersionDocument.agent_version_id)
        .join(AgentVersion, AgentVersion.id == AgentVersionDocument.agent_version_id)
        .where(
            AgentVersionDocument.document_id == scoped.document.id,
            AgentVersionDocument.enabled.is_(True),
            AgentVersion.state == "draft",
        )
    )
    if enabled is not None:
        abandon_claim(db, record)
        raise invalid_state("An enabled draft document cannot be deleted.")
    # Drop draft-only disabled links so a deleted library file cannot linger in
    # draft selections.  Published and superseded version links stay untouched.
    draft_ids = list(
        db.scalars(
            select(AgentVersion.id).where(
                AgentVersion.state == "draft",
                AgentVersion.id.in_(
                    select(AgentVersionDocument.agent_version_id).where(
                        AgentVersionDocument.document_id == scoped.document.id
                    )
                ),
            )
        ).all()
    )
    if draft_ids:
        db.execute(
            delete(AgentVersionDocument).where(
                AgentVersionDocument.document_id == scoped.document.id,
                AgentVersionDocument.agent_version_id.in_(draft_ids),
            )
        )
    snapshot_bound = (
        db.scalar(
            select(KnowledgeDocumentVersion.id)
            .where(KnowledgeDocumentVersion.document_id == scoped.document.id)
            .limit(1)
        )
        is not None
        or db.scalar(
            select(KnowledgeSetSource.id)
            .where(KnowledgeSetSource.document_id == scoped.document.id)
            .limit(1)
        )
        is not None
        or db.scalar(
            select(SnapshotDocument.id)
            .where(SnapshotDocument.document_id == scoped.document.id)
            .limit(1)
        )
        is not None
        or db.scalar(
            select(KnowledgeChunk.id)
            .where(KnowledgeChunk.document_id == scoped.document.id)
            .limit(1)
        )
        is not None
        or db.scalar(
            select(AgentVersionDocument.agent_version_id)
            .join(AgentVersion, AgentVersion.id == AgentVersionDocument.agent_version_id)
            .where(
                AgentVersionDocument.document_id == scoped.document.id,
                AgentVersion.state.in_(("published", "superseded")),
            )
            .limit(1)
        )
        is not None
    )
    if snapshot_bound:
        # Library removal only.  Snapshot rows keep their lineage FK and their
        # own frozen file bytes; neither is rewritten here.
        scoped.document.workspace_state = "hidden"
        scoped.document.updated_at = _now()
        result = _document_dto(
            scoped.document,
            can_manage_visibility=scoped.document.owner_user_id == context.user.id,
        )
    else:
        result = _document_dto(
            scoped.document,
            can_manage_visibility=scoped.document.owner_user_id == context.user.id,
        )
        result = result.model_copy(update={"workspace_state": "hidden"})
        stored_file_id = scoped.document.stored_file_id
        db.execute(
            delete(KnowledgeDocumentChunk).where(
                KnowledgeDocumentChunk.document_id == scoped.document.id
            )
        )
        db.execute(
            delete(AgentVersionDocument).where(
                AgentVersionDocument.document_id == scoped.document.id
            )
        )
        db.delete(scoped.document)
        remaining = db.scalar(
            select(KnowledgeDocument.id)
            .where(KnowledgeDocument.stored_file_id == stored_file_id)
            .limit(1)
        )
        snapshot_file = db.scalar(
            select(SnapshotDocument.id)
            .where(SnapshotDocument.stored_file_id == stored_file_id)
            .limit(1)
        )
        if remaining is None and snapshot_file is None:
            stored = db.get(StoredFile, stored_file_id)
            if stored is not None:
                db.execute(
                    delete(FileReference).where(FileReference.stored_file_id == stored_file_id)
                )
                db.delete(stored)
    finish_idempotency(db, record, 200, result.model_dump(mode="json"))
    saga_checkpoint("hide_knowledge_document.before_final_commit")
    db.commit()
    saga_checkpoint("hide_knowledge_document.after_final_commit")
    return result


@router.put(
    "/agent-versions/{version_id}/knowledge-documents",
    response_model=AgentVersionDTO,
    operation_id="setAgentVersionDocuments",
    responses={
        200: {"model": AgentVersionDTO, "description": "Enabled set replaced."},
        404: {"model": Error, "description": "Version or document not found."},
        409: {"model": Error, "description": "Revision conflict."},
        422: {"model": Error, "description": "Invalid document set."},
    },
)
def set_agent_version_documents(
    version_id: UUID,
    payload: SetDocumentsRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> AgentVersionDTO:
    # This route keeps the exact anonymous object body from the frozen
    # contract while validating it explicitly at the service boundary.
    expected_revision = payload.expected_revision
    document_ids = [str(value) for value in payload.document_ids]
    reject_baseline_version_mutation(str(version_id))
    scoped = visible_student_version(db, context, str(version_id))
    if scoped.version.state != "draft":
        raise version_immutable()
    if scoped.version.revision != expected_revision:
        raise stale_revision(scoped.version.revision)
    if len(set(document_ids)) != len(document_ids):
        raise validation_failure(
            "document_ids must not contain duplicates.",
            code="file_operation_failed",
        )
    agent = db.get(Agent, scoped.agent.id)
    if agent is None:
        raise not_found()
    documents = (
        list(
            db.scalars(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.id.in_(document_ids),
                    KnowledgeDocument.course_id == agent.course_id,
                    KnowledgeDocument.workspace_state == "active",
                )
            ).all()
        )
        if document_ids
        else []
    )
    if len(documents) != len(document_ids) or any(
        not can_bind_source(db, context, agent, document) for document in documents
    ):
        raise not_found()
    documents_by_id = {document.id: document for document in documents}
    ordered = [documents_by_id[item] for item in document_ids]
    changed = db.execute(
        update(AgentVersion)
        .where(
            AgentVersion.id == scoped.version.id,
            AgentVersion.state == "draft",
            AgentVersion.revision == expected_revision,
        )
        .values(
            revision=AgentVersion.revision + 1,
            updated_at=_now(),
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
        current_revision = db.scalar(
            select(AgentVersion.revision).where(AgentVersion.id == scoped.version.id)
        )
        raise stale_revision(current_revision)
    db.refresh(scoped.version)
    db.execute(
        delete(AgentVersionDocument).where(
            AgentVersionDocument.agent_version_id == scoped.version.id
        )
    )
    for index, document in enumerate(ordered):
        db.add(
            AgentVersionDocument(
                agent_version_id=scoped.version.id,
                document_id=document.id,
                enabled=True,
                order_index=index,
            )
        )
    if scoped.agent.visibility != "public" or any(
        document.visibility != "public" for document in ordered
    ):
        scoped.version.draft_visibility = "private"
    db.flush()
    return version_dto(
        db,
        scoped.version,
        scoped.agent,
        include_private_sources=scoped.agent.owner_user_id == context.user.id,
    )


@router.get(
    "/agent-versions/{version_id}/rag-preview",
    response_model=RagPreview,
    operation_id="getRagPreview",
    responses={
        200: {"model": RagPreview, "description": "Draft-only combined Markdown preview."},
        404: {"model": Error, "description": "Draft not found."},
    },
)
def get_rag_preview(
    version_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RagPreview:
    scoped = visible_student_version(db, context, str(version_id))
    if scoped.version.state != "draft":
        raise not_found()
    return rag_preview(db, scoped.version, settings.resolved_data_root)


@router.get(
    "/knowledge-snapshots/{snapshot_id}",
    response_model=KnowledgeSnapshot,
    operation_id="getKnowledgeSnapshot",
    responses={
        200: {"model": KnowledgeSnapshot, "description": "Published immutable snapshot metadata."},
        404: {"model": Error, "description": "Snapshot not found."},
    },
)
def get_knowledge_snapshot(
    snapshot_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> KnowledgeSnapshot:
    scoped = visible_snapshot(db, context, str(snapshot_id))
    return snapshot_dto(db, scoped.snapshot)


@router.get(
    "/knowledge-snapshots/{snapshot_id}/download",
    operation_id="downloadSnapshotRag",
    response_class=Response,
    responses={
        200: {
            "description": "Frozen combined RAG Markdown.",
            "content": {"text/markdown": {"schema": {"type": "string"}}},
        },
        404: {"model": Error, "description": "Snapshot not found."},
    },
)
def download_snapshot_rag(
    snapshot_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    scoped = visible_snapshot(db, context, str(snapshot_id))
    stored = scoped.snapshot.stored_file
    if stored is None:
        raise not_found()
    filename = frozen_download_filename(
        "RAG.md",
        scoped.agent.name,
        f"V1.{scoped.version.version_seq}",
    )
    return Response(
        read_contained(settings.resolved_data_root, stored.relative_path),
        media_type="text/markdown",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.get(
    "/knowledge-snapshots/{snapshot_id}/documents/{snapshot_document_id}/download",
    operation_id="downloadSnapshotDocument",
    response_class=Response,
    responses={
        200: {
            "description": "Frozen source Markdown.",
            "content": {"text/markdown": {"schema": {"type": "string"}}},
        },
        404: {"model": Error, "description": "Snapshot document not found."},
    },
)
def download_snapshot_document(
    snapshot_id: UUID,
    snapshot_document_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    scoped = visible_snapshot(db, context, str(snapshot_id))
    row = db.execute(
        select(SnapshotDocument).where(
            SnapshotDocument.id == str(snapshot_document_id),
            SnapshotDocument.snapshot_id == scoped.snapshot.id,
        )
    ).first()
    if row is None:
        raise not_found()
    document = row[0]
    stored = db.scalar(
        select(StoredFile)
        .join(SnapshotDocument, SnapshotDocument.stored_file_id == StoredFile.id)
        .where(
            SnapshotDocument.id == document.id,
            SnapshotDocument.snapshot_id == scoped.snapshot.id,
        )
    )
    if stored is None:
        raise not_found()
    snapshot_documents = list(
        db.scalars(
            select(SnapshotDocument)
            .where(SnapshotDocument.snapshot_id == scoped.snapshot.id)
            .order_by(SnapshotDocument.order_index, SnapshotDocument.id)
        ).all()
    )
    ordinal = document.order_index + 1 if len(snapshot_documents) > 1 else None
    filename = frozen_download_filename(
        document.source_filename,
        scoped.agent.name,
        f"V1.{scoped.version.version_seq}",
        ordinal=ordinal,
    )
    return Response(
        read_contained(settings.resolved_data_root, stored.relative_path),
        media_type="text/markdown",
        headers={"Content-Disposition": content_disposition(filename)},
    )
