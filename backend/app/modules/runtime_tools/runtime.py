from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agno.tools.function import Function
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.auth.service import AuthContext
from app.modules.runtime_tools.knowledge import GENERATE_AGENT_KNOWLEDGE_TOOL
from app.modules.runtime_tools.registry import ToolPostCommit, ToolSpec

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
    generation_waker: Callable[[str], None] | None = None,
) -> list[Function]:
    del settings
    if actor_context is None or actor_context.user.id != actor_id:
        return []
    post_commit: ToolPostCommit | None = None
    if generation_waker is not None:

        def wake_persisted_generation(spec: ToolSpec, result: dict[str, Any]) -> None:
            if spec.name != GENERATE_AGENT_KNOWLEDGE_TOOL or result.get("ok") is not True:
                return
            payload = result.get("result")
            if not isinstance(payload, dict) or payload.get("wake_generation") is not True:
                return
            run_id = payload.get("run_id")
            if isinstance(run_id, str) and run_id:
                generation_waker(run_id)

        post_commit = wake_persisted_generation

    return bind_runtime_functions(
        factory,
        actor_context,
        conversation_id=conversation_id,
        participant_id=participant_id,
        turn_id=turn_id,
        registry=runtime_registry(),
        post_commit=post_commit,
    )
