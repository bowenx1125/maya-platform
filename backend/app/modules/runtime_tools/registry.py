"""Transactional Tool dispatch bound to accepted model call identities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import PlatformError, conflict, not_found
from app.core.models import CourseMember, ProviderOperation, SessionRecord, User
from app.modules.auth.service import AuthContext
from app.modules.workspace.models import (
    Conversation,
    ConversationTurn,
    TeamProviderCall,
    TeamTurnResult,
)

from .models import RuntimeModelCallStage, RuntimeToolReceipt

ToolClass = Literal["Public", "Student", "Teacher"]
ToolHandler = Callable[
    [Session, AuthContext, Conversation, BaseModel, str, "ToolCallIdentity"], Any
]
ToolAuthorization = Callable[[Session, AuthContext, Conversation, BaseModel], None]
ToolReplayAuthorization = Callable[
    [Session, AuthContext, Conversation, BaseModel, "ToolCallIdentity", dict[str, Any]], None
]
ToolPostCommit = Callable[["ToolSpec", dict[str, Any]], None]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    authorization_class: ToolClass
    description: str
    payload_model: type[BaseModel]
    authorize: ToolAuthorization
    handler: ToolHandler
    authorize_execution: (
        Callable[[Session, AuthContext, Conversation, BaseModel, ToolCallIdentity], None] | None
    ) = None
    authorize_replay: ToolReplayAuthorization | None = None
    replay_read: ToolHandler | None = None
    stop_after_tool_call: bool = False
    entry_kinds: frozenset[str] | None = None


@dataclass(frozen=True)
class ToolCallIdentity:
    conversation_id: str
    turn_id: str
    participant_id: str
    model_call_id: str
    tool_call_id: str
    conversation_revision: int | None = None
    claim_token: str | None = None


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _scope(db: Session, actor: AuthContext, conversation_id: str) -> tuple[Conversation, str]:
    user = db.get(User, actor.user.id)
    session = db.get(SessionRecord, actor.session.id_hash)
    row = db.get(Conversation, conversation_id)
    expires_at = session.expires_at if session is not None else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if (
        user is None
        or user.status != "active"
        or session is None
        or session.user_id != actor.user.id
        or session.revoked_at is not None
        or expires_at is None
        or expires_at <= datetime.now(UTC)
        or row is None
        or row.withdrawn_at is not None
        or row.user_id != user.id
    ):
        raise not_found()
    member = db.get(CourseMember, (row.course_id, user.id))
    if member is None or member.role not in {"student", "teacher"}:
        raise not_found()
    return row, member.role


def exposed_tools(
    db: Session, actor: AuthContext, conversation_id: str, registry: Mapping[str, ToolSpec]
) -> tuple[ToolSpec, ...]:
    row, role = _scope(db, actor, conversation_id)
    return tuple(
        spec
        for spec in registry.values()
        if spec.authorization_class
        in ({"Public", "Teacher"} if role == "teacher" else {"Public", "Student"})
        and (spec.entry_kinds is None or row.entry_kind in spec.entry_kinds)
    )


def _accepted_call(
    db: Session, identity: ToolCallIdentity, name: str, arguments: dict[str, Any]
) -> str:
    team_stage = db.get(TeamProviderCall, identity.model_call_id)
    stage: TeamProviderCall | RuntimeModelCallStage | None = team_stage
    if team_stage is not None:
        result = db.get(TeamTurnResult, team_stage.result_id)
        matches = (
            result is not None
            and result.conversation_id == identity.conversation_id
            and result.turn_id == identity.turn_id
            and result.participant_id == identity.participant_id
        )
    else:
        stage = db.get(RuntimeModelCallStage, identity.model_call_id)
        conversation = db.get(Conversation, identity.conversation_id)
        matches = (
            stage is not None
            and stage.conversation_id == identity.conversation_id
            and stage.turn_id == identity.turn_id
            and stage.executor_agent_version_id == identity.participant_id
            and conversation is not None
            and conversation.agent_version_id == identity.participant_id
        )
    if stage is None or stage.accepted_response_json is None or not matches:
        raise conflict("tool_call_unverified", "This Tool call has no accepted model result.")
    operation = db.get(ProviderOperation, stage.operation_id)
    if (
        operation is None
        or operation.state not in {"accepted", "succeeded"}
        or operation.request_hash != stage.request_hash
        or operation.staged_response_hash != stage.accepted_response_hash
    ):
        raise conflict("tool_call_unverified", "This Tool call has no accepted dispatch receipt.")
    if isinstance(stage, RuntimeModelCallStage):
        from app.modules.provider_disclosure.service import (
            CHAT_STANDING_FIELD_CLASSES,
            single_chat_consent_is_current,
        )

        current_conversation = db.get(Conversation, identity.conversation_id)
        if current_conversation is None or not single_chat_consent_is_current(
            db.connection(),
            manifest_hash=operation.export_manifest_hash,
            conversation_id=current_conversation.id,
            actor_user_id=current_conversation.user_id,
            course_id=current_conversation.course_id,
            policy_hash=operation.policy_hash,
            field_classes=CHAT_STANDING_FIELD_CLASSES,
        ):
            raise conflict(
                "provider_authorization_revoked", "Current Chat authorization has changed."
            )
    if (
        hashlib.sha256(stage.accepted_response_json.encode()).hexdigest()
        != stage.accepted_response_hash
        or hashlib.sha256(stage.request_json.encode()).hexdigest() != stage.request_hash
    ):
        raise conflict(
            "tool_call_unverified", "The accepted model result failed its integrity check."
        )
    try:
        request = json.loads(stage.request_json)
        response = json.loads(stage.accepted_response_json)
    except (ValueError, TypeError):
        raise conflict("tool_call_unverified", "The saved model result is unavailable.") from None
    requested_tools = request.get("tools", []) if isinstance(request, dict) else []
    if not isinstance(requested_tools, list) or not any(
        isinstance(tool, dict)
        and isinstance(tool.get("function"), dict)
        and tool["function"].get("name") == name
        for tool in requested_tools
    ):
        raise conflict("tool_not_available", "This Tool was not provided to this invocation.")
    if not isinstance(response, dict):
        raise conflict("tool_call_unverified", "The saved model result is unavailable.")
    message = response
    choices = response.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        candidate = choices[0].get("message")
        if isinstance(candidate, dict):
            message = candidate
    calls = message.get("tool_calls", [])
    for call in calls if isinstance(calls, list) else []:
        if not isinstance(call, dict) or call.get("id") != identity.tool_call_id:
            continue
        function = call.get("function")
        if not isinstance(function, dict) or function.get("name") != name:
            break
        saved = function.get("arguments")
        if isinstance(saved, str):
            try:
                saved = json.loads(saved)
            except ValueError:
                break
        if saved == {"arguments": arguments}:
            return stage.operation_id
    raise conflict(
        "tool_call_unverified", "This Tool call does not match its accepted model result."
    )


def execute_tool(
    db: Session,
    actor: AuthContext,
    identity: ToolCallIdentity,
    name: str,
    arguments: dict[str, Any],
    registry: Mapping[str, ToolSpec],
) -> dict[str, Any]:
    """The caller owns one writer transaction containing receipt and side effect."""
    try:
        row, role = _scope(db, actor, identity.conversation_id)
        if identity.conversation_revision is not None:
            bound_turn = db.get(ConversationTurn, identity.turn_id)
            if (
                row.revision != identity.conversation_revision
                or bound_turn is None
                or bound_turn.conversation_id != row.id
                or bound_turn.claim_token != identity.claim_token
            ):
                raise conflict("tool_run_superseded", "Continue through the current run.")
        spec = registry.get(name)
        allowed_classes = {"Public", "Teacher"} if role == "teacher" else {"Public", "Student"}
        if spec is None or spec.authorization_class not in allowed_classes:
            return {
                "ok": False,
                "code": "tool_not_authorized",
                "message": "This Tool is not available for your current course role.",
            }
        payload = spec.payload_model.model_validate(arguments)
        spec.authorize(db, actor, row, payload)
        model_operation_id = _accepted_call(db, identity, name, arguments)
        request_hash = hashlib.sha256(
            canonical(
                {
                    "actor": actor.user.id,
                    "conversation": row.id,
                    "turn": identity.turn_id,
                    "participant": identity.participant_id,
                    "name": name,
                    "arguments": arguments,
                }
            ).encode()
        ).hexdigest()
        existing = db.scalar(
            select(RuntimeToolReceipt).where(
                RuntimeToolReceipt.model_operation_id == model_operation_id,
                RuntimeToolReceipt.tool_call_id == identity.tool_call_id,
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise conflict(
                    "tool_call_changed",
                    "This Tool call has already been used with different arguments.",
                )
            if spec.replay_read is not None:
                return {
                    "ok": True,
                    "result": spec.replay_read(
                        db,
                        actor,
                        row,
                        payload,
                        str(uuid5(UUID(model_operation_id), identity.tool_call_id)),
                        identity,
                    ),
                }
            saved_result = json.loads(existing.result_json)
            if not isinstance(saved_result, dict):
                raise conflict("tool_receipt_invalid", "The saved Tool result is unavailable.")
            if spec.authorize_replay is not None:
                spec.authorize_replay(db, actor, row, payload, identity, saved_result)
            elif spec.authorize_execution is not None:
                spec.authorize_execution(db, actor, row, payload, identity)
            return saved_result
        team_stage = db.get(TeamProviderCall, identity.model_call_id)
        team_result = (
            db.get(TeamTurnResult, team_stage.result_id) if team_stage is not None else None
        )
        if team_stage is not None and (team_result is None or team_result.state != "running"):
            raise conflict(
                "tool_run_inactive", "Resume the current run before executing this Tool."
            )
        if spec.authorize_execution is not None:
            spec.authorize_execution(db, actor, row, payload, identity)
        turn = db.get(ConversationTurn, identity.turn_id)
        if (
            turn is None
            or turn.conversation_id != row.id
            or turn.state != "pending"
            or row.active_request_id != identity.turn_id
        ):
            raise conflict(
                "tool_run_inactive", "Resume the current run before executing this Tool."
            )
        with db.begin_nested():
            result = {
                "ok": True,
                "result": spec.handler(
                    db,
                    actor,
                    row,
                    payload,
                    str(uuid5(UUID(model_operation_id), identity.tool_call_id)),
                    identity,
                ),
            }
            if (
                name == "update_learning_boundary"
                and identity.claim_token is not None
                and result
                == {
                    "ok": True,
                    "result": {"saved": True},
                }
            ):
                from app.modules.workspace.team_runtime import settle_completed_boundary_tool_call

                settle_completed_boundary_tool_call(db, actor, row, identity, payload, result)
            receipt = RuntimeToolReceipt(
                id=str(uuid4()),
                actor_user_id=actor.user.id,
                conversation_id=row.id,
                turn_id=identity.turn_id,
                model_operation_id=model_operation_id,
                tool_call_id=identity.tool_call_id,
                tool_name=name,
                request_hash=request_hash,
                result_json=canonical(result),
                created_at=datetime.now(UTC),
            )
            db.add(receipt)
            db.flush()
        return result
    except ValidationError:
        return {
            "ok": False,
            "code": "invalid_tool_arguments",
            "message": "Use the documented arguments for this Tool.",
        }
    except PlatformError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}
