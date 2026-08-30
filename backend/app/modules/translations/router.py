"""M15 teacher-only translation batch REST routes.

The main composition root owns router registration.  Keeping this module
standalone lets the main agent mount it after the 0007 migration and inject a
shared ``TranslationService`` through ``app.state``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.errors import Error
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext

from .schemas import TranslationBatchDTO
from .service import TranslationService

router = APIRouter(tags=["Translation"])


def get_translation_service(request: Request) -> TranslationService:
    """Use main-owned service composition, with a safe local fallback."""

    existing = getattr(request.app.state, "translation_service", None)
    if isinstance(existing, TranslationService):
        return existing
    database = getattr(request.app.state, "database", None)
    settings = getattr(request.app.state, "settings", None)
    if database is None:
        raise RuntimeError("translation service is not configured")
    service = TranslationService(database.session_factory, settings=settings)
    request.app.state.translation_service = service
    return service


@router.get(
    "/debates/{debate_id}/translations",
    response_model=list[TranslationBatchDTO],
    operation_id="listTranslationBatches",
    responses={
        200: {"model": list[TranslationBatchDTO]},
        403: {"model": Error},
        404: {"model": Error},
    },
)
def list_translation_batches_route(
    debate_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    service: TranslationService = Depends(get_translation_service),
) -> list[TranslationBatchDTO]:
    return service.list_batches(db, actor_user_id=context.user.id, debate_id=str(debate_id))


@router.post(
    "/debates/{debate_id}/translations",
    response_model=TranslationBatchDTO,
    status_code=202,
    operation_id="translateCurrentPublishedContent",
    responses={
        202: {"model": TranslationBatchDTO},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
        422: {"model": Error},
    },
)
async def translate_current_published_content_route(
    debate_id: UUID,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    service: TranslationService = Depends(get_translation_service),
) -> Any:
    result = service.request_translation(
        db,
        actor_user_id=context.user.id,
        debate_id=str(debate_id),
        idempotency_key=idempotency_key,
        context=context,
        schedule=True,
    )
    # ``claim_idempotency`` returns a JSONResponse for an exact replay.  The
    # explicit ``Any`` return keeps FastAPI from trying to validate that
    # already-serialized response against the 202 DTO a second time.
    del request
    return result


__all__ = ["get_translation_service", "router"]
