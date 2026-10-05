from __future__ import annotations

from collections.abc import Callable

from agno.tools.function import Function
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.auth.service import AuthContext

from .builtin import runtime_registry
from .sdk import bind_runtime_functions


def build_runtime_tools(
    factory: Callable[[], Session],
    actor_id: str,
    conversation_id: str,
    participant_id: str,
    turn_id: str,
    settings: Settings,
    *,
    actor_context: AuthContext | None = None,
) -> list[Function]:
    del settings
    if actor_context is None or actor_context.user.id != actor_id:
        return []
    return bind_runtime_functions(
        factory,
        actor_context,
        conversation_id=conversation_id,
        participant_id=participant_id,
        turn_id=turn_id,
        registry=runtime_registry(),
    )
