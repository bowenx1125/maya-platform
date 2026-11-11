"""The teacher-only per-Agent diagnostics read for one Debate."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import Error
from app.modules.auth.dependencies import get_db, require_auth
from app.modules.auth.service import AuthContext
from app.modules.debates.diagnostics import DebateDiagnostics, debate_diagnostics

router = APIRouter(tags=["Debates"])


@router.get(
    "/debates/{debate_id}/diagnostics",
    response_model=DebateDiagnostics,
    operation_id="getDebateDiagnostics",
    responses={
        200: {"model": DebateDiagnostics},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
def get_debate_diagnostics_route(
    debate_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DebateDiagnostics:
    return debate_diagnostics(db, actor_user_id=context.user.id, debate_id=str(debate_id))
