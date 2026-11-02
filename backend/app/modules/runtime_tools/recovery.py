"""Recover accepted Chat envelopes without confusing acceptance with completion."""

from __future__ import annotations

import hashlib
from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import ProviderOperation
from app.modules.workspace.models import Conversation, ConversationTurn, TeamProviderCall

from .models import RuntimeModelCallStage


def accepted_chat_stage_complete(db: Session, operation: ProviderOperation) -> bool:
    stage: RuntimeModelCallStage | TeamProviderCall | None = db.get(
        RuntimeModelCallStage, operation.id
    )
    if stage is None:
        stage = db.scalar(
            select(TeamProviderCall).where(TeamProviderCall.operation_id == operation.id)
        )
    if stage is None or stage.accepted_response_json is None:
        return False
    return (
        operation.request_hash == stage.request_hash
        and operation.staged_response_hash == stage.accepted_response_hash
        and hashlib.sha256(stage.request_json.encode()).hexdigest() == stage.request_hash
        and hashlib.sha256(stage.accepted_response_json.encode()).hexdigest()
        == stage.accepted_response_hash
    )


def recover_single_chat_runs(db: Session, conversation_ids: Collection[str] | None = None) -> None:
    """Settle Single Chats left mid-turn; ``conversation_ids`` limits it to those."""

    query = select(Conversation).where(
        Conversation.entry_kind == "agent", Conversation.active_request_id.is_not(None)
    )
    if conversation_ids is not None:
        query = query.where(Conversation.id.in_(tuple(conversation_ids)))
    for conversation in db.scalars(query):
        turn = db.get(ConversationTurn, conversation.active_request_id)
        if turn is not None and turn.state == "pending":
            stages = list(
                db.scalars(
                    select(RuntimeModelCallStage).where(
                        RuntimeModelCallStage.conversation_id == conversation.id,
                        RuntimeModelCallStage.turn_id == turn.id,
                        RuntimeModelCallStage.executor_agent_version_id
                        == conversation.agent_version_id,
                    )
                )
            )
            resumable = bool(stages)
            for stage in stages:
                operation = db.get(ProviderOperation, stage.operation_id)
                if (
                    operation is None
                    or operation.request_hash != stage.request_hash
                    or hashlib.sha256(stage.request_json.encode()).hexdigest() != stage.request_hash
                ):
                    resumable = False
                    break
                if operation.state in {"reserved", "not_sent"}:
                    if (
                        operation.charged_request_count != 0
                        or stage.accepted_response_json is not None
                        or stage.accepted_response_hash is not None
                    ):
                        resumable = False
                        break
                    continue
                if operation.state not in {
                    "accepted",
                    "succeeded",
                } or not accepted_chat_stage_complete(db, operation):
                    resumable = False
                    break
            if conversation.withdrawn_at is not None:
                turn.state = "failed"
                turn.safe_error_code = "chat_withdrawn"
            elif turn.mode == "real" and resumable:
                # This pauses local execution only. Explicit resume supplies fresh
                # actor authorization, reuses accepted envelopes, and may retry only
                # proven-unsent stages. Startup never sends a provider request.
                turn.state = "paused"
                turn.safe_error_code = "chat_recovery_available"
            else:
                turn.state = "acceptance_unknown" if turn.mode == "real" else "failed"
                turn.safe_error_code = "chat_interrupted"
        conversation.active_request_id = None
        conversation.revision += 1
