"""Rename an owned RAG without changing its content or generation identity."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import Error, conflict
from app.core.sqlutil import begin_immediate
from app.modules.auth.dependencies import get_db, require_authenticated_mutation
from app.modules.auth.service import AuthContext
from app.modules.demo_baseline.service import reject_baseline_document_mutation
from app.modules.knowledge.markdown import MarkdownInputError, normalize_markdown
from app.modules.knowledge.schemas import KnowledgeDocument as KnowledgeDocumentDTO
from app.modules.knowledge.services import (
    _document_dto,
    abandon_claim,
    assert_claim_owned,
    claim_idempotency,
    finish_idempotency,
    now_utc,
    parse_json_payload_hash,
    visible_mutable_document,
)
from app.modules.knowledge.source_versions import retain_current_source_version

router = APIRouter(tags=["knowledge"])


class RenameKnowledgeDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_filename: str
    filename: str = Field(min_length=1, max_length=255)

    @field_validator("filename")
    @classmethod
    def valid_markdown_filename(cls, value: str) -> str:
        try:
            normalize_markdown(value, b"filename validation")
        except MarkdownInputError as exc:
            raise ValueError(
                "Use a Markdown filename without path separators or control characters."
            ) from exc
        return value


@router.post(
    "/knowledge-documents/{document_id}:rename",
    response_model=KnowledgeDocumentDTO,
    operation_id="renameKnowledgeDocument",
    responses={
        404: {"model": Error, "description": "Owned document unavailable."},
        409: {"model": Error, "description": "Name changed or idempotency conflict."},
    },
)
def rename_knowledge_document(
    document_id: UUID,
    payload: RenameKnowledgeDocumentRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> KnowledgeDocumentDTO:
    document_key = str(document_id)
    reject_baseline_document_mutation(document_key)
    visible_mutable_document(db, context, document_key)
    body_hash = parse_json_payload_hash(
        "renameKnowledgeDocument", context, [document_key], payload.model_dump()
    )
    record, replay = claim_idempotency(
        db,
        context,
        "renameKnowledgeDocument",
        idempotency_key,
        body_hash,
        data_root=settings.resolved_data_root,
    )
    if replay is not None:
        visible_mutable_document(db, context, document_key)
        return replay  # type: ignore[return-value]
    try:
        db.rollback()
        begin_immediate(db)
        assert_claim_owned(db, record)
        document = visible_mutable_document(db, context, document_key).document
        if document.source_filename != payload.expected_filename:
            raise conflict(
                "knowledge_name_changed", "The document name changed. Refresh and try again."
            )
        retain_current_source_version(db, document)
        document.source_filename = payload.filename
        document.updated_at = now_utc()
        db.flush()
        result = _document_dto(document, can_manage_visibility=True)
        finish_idempotency(db, record, 200, result.model_dump(mode="json"))
        db.commit()
        return result
    except Exception:
        abandon_claim(db, record)
        raise
