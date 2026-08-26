"""Authenticated platform route for the immutable M07 avatar catalog."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.modules.auth.dependencies import require_auth
from app.modules.auth.service import AuthContext
from app.modules.avatars.catalog import avatar_templates
from app.modules.avatars.schemas import AvatarTemplate

router = APIRouter(tags=["Agents"])


@router.get(
    "/avatar-templates",
    response_model=list[AvatarTemplate],
    operation_id="listAvatarTemplates",
    responses={
        200: {
            "model": list[AvatarTemplate],
            "description": "Platform templates and supported parameter capabilities.",
        }
    },
)
def list_avatar_templates(_context: AuthContext = Depends(require_auth)) -> list[AvatarTemplate]:
    """List available templates in the frozen catalog order."""

    return avatar_templates()
