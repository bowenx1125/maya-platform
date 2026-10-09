"""Exact Provider calls for Maya's native Agno Team execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from agno.models.message import Message
from agno.models.response import ModelResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.auth.service import AuthContext
from app.modules.provider_disclosure.team_standing import authorize_team_dispatch
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamProviderConsentBinding,
    TeamProviderStandingGrant,
    TeamTurnResult,
)
from app.providers.control import (
    LLM_DEBATE_TURN_BUCKET,
    ExportFieldV1,
    ExportManifestV1,
    ProviderReservationRequestV1,
    ProviderScopeBudgetV1,
    canonical_json_bytes,
    validate_provider_preflight,
)
from app.providers.control_repository import (
    ProviderDispatchRejected,
    ProviderRepository,
    ProviderRepositoryError,
    ProviderSendingGuard,
)
from app.providers.factory import llm_provider
from app.providers.llm_adapter import DashScopeLLMAdapter
from app.providers.llm_price_card import LLM_INPUT_TOKEN_CAP, LLM_RESERVED_OUTPUT_TOKEN_CAP
from app.providers.llm_transport import HttpxLLMTransport, LLMTransport, LLMTransportError
from app.providers.standing_consent import standing_consent_enabled

from .assessment_protocol import ASSESSMENT_SOURCE_REVOKED_OWNER_ACTIONS_PROTOCOL
from .chat_team_sdk import TeamDispatchError
from .team_runtime import MemberRequest

CONTROL_UNBOUNDED_REQUESTS = 2_147_483_647
CONTROL_UNBOUNDED_TOKENS = 9_223_372_036_854_775_807
CONTROL_UNBOUNDED_COST_CNY = 1.0e18
TEAM_PER_CALL_MAX_TOKENS = LLM_INPUT_TOKEN_CAP + LLM_RESERVED_OUTPUT_TOKEN_CAP


@dataclass(frozen=True)
class TeamProviderDispatch:
    response: ModelResponse
    call_id: str


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _wire_message(message: Message) -> dict[str, Any]:
    role = message.role
    content = message.content
    if not isinstance(role, str) or not role:
        raise TeamDispatchError("team_messages_invalid")
    if content is not None and not isinstance(content, str):
        raise TeamDispatchError("team_text_only")
    item: dict[str, Any] = {"role": role, "content": content}
    for field in ("name", "tool_call_id", "tool_calls"):
        value = getattr(message, field, None)
        if value is not None:
            item[field] = value
    try:
        canonical_json_bytes(item)
    except Exception:
        raise TeamDispatchError("team_messages_invalid") from None
    return item


def team_request_bytes(
    model_key: str,
    messages: list[Message],
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
) -> bytes:
    body: dict[str, object] = {
        "model": model_key,
        "messages": [_wire_message(message) for message in messages],
        "stream": False,
        "enable_thinking": False,
    }
    if tools is not None:
        body["tools"] = tools
    if tool_choice is not None:
        body["tool_choice"] = tool_choice
    try:
        return canonical_json_bytes(body)
    except Exception:
        raise TeamDispatchError("team_messages_invalid") from None


def has_repeated_no_progress_tool_cycle(
    messages: list[Message], tools: list[dict[str, Any]] | None
) -> bool:
    """Detect two adjacent identical completed calls with the same saved result."""
    available = {
        function.get("name")
        for tool in (tools or [])
        if isinstance(tool, dict)
        and isinstance((function := tool.get("function")), dict)
        and isinstance(function.get("name"), str)
    }
    if not available:
        return False
    waiting: dict[str, tuple[str, str]] = {}
    completed: list[tuple[str, str, str]] = []
    for message in messages:
        if message.role == "assistant":
            for call in getattr(message, "tool_calls", None) or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function")
                call_id = call.get("id")
                if not isinstance(function, dict) or not isinstance(call_id, str):
                    continue
                name = function.get("name")
                arguments = function.get("arguments")
                if not isinstance(name, str) or name not in available:
                    continue
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        continue
                try:
                    canonical_arguments = json.dumps(
                        arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                    )
                except (TypeError, ValueError):
                    continue
                waiting[call_id] = (name, canonical_arguments)
        elif message.role == "tool":
            call_id = getattr(message, "tool_call_id", None)
            result = message.content
            if not isinstance(call_id, str) or not isinstance(result, str):
                continue
            call = waiting.pop(call_id, None)
            if call is not None:
                completed.append((*call, result))
    return len(completed) > 1 and completed[-1] == completed[-2]


def _raw_response_text(response: object) -> str:
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            raise TeamDispatchError("team_response_invalid") from None
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    json_method = getattr(response, "json", None)
    if not callable(json_method):
        raise TeamDispatchError("team_response_invalid")
    try:
        return canonical_json_bytes(json_method()).decode("utf-8")
    except Exception:
        raise TeamDispatchError("team_response_invalid") from None


def _model_response(response_json: str) -> ModelResponse:
    try:
        payload = json.loads(response_json)
        choices = payload["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError
        choice = choices[0]
        message = choice["message"]
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ValueError
        content = message.get("content")
        calls = message.get("tool_calls") or []
        if content is not None and not isinstance(content, str):
            raise ValueError
        if not isinstance(calls, list):
            raise ValueError
        for call in calls:
            function = call.get("function") if isinstance(call, dict) else None
            if (
                not isinstance(call, dict)
                or not isinstance(call.get("id"), str)
                or not call["id"]
                or call.get("type") != "function"
                or not isinstance(function, dict)
                or not isinstance(function.get("name"), str)
                or not isinstance(function.get("arguments"), str)
            ):
                raise ValueError
        if not calls and (not isinstance(content, str) or not content.strip()):
            raise ValueError
        if choice.get("finish_reason") not in {"stop", "tool_calls"}:
            raise ValueError
        return ModelResponse(role="assistant", content=content, tool_calls=calls)
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise TeamDispatchError("team_response_invalid") from None


def _current_claim_guard(
    *,
    actor_user_id: str,
    result_id: str,
    claim_token: str,
    selected_binding_ids: set[str],
    serialized_request: bytes | None,
    current_policy_hash: str,
    query_context: Any | None = None,
    revoked_assessment_scope: Any | None = None,
) -> ProviderSendingGuard:
    from app.modules.teams.models import (
        CourseTeamPublication,
        Team,
        TeamMemberInvokeGrant,
        TeamVersion,
        TeamVersionMember,
    )

    result_table = TeamTurnResult.__table__
    turn_table = ConversationTurn.__table__
    chat_table = Conversation.__table__
    participant_table = ConversationParticipant.__table__
    consent_table = TeamProviderConsentBinding.__table__
    grant_table = TeamProviderStandingGrant.__table__
    team_table = Team.__table__
    version_table = TeamVersion.__table__
    member_table = TeamVersionMember.__table__
    invoke_table = TeamMemberInvokeGrant.__table__
    publication_table = CourseTeamPublication.__table__

    def guard(connection: Any, operation: Any) -> bool:
        current = (
            connection.execute(
                select(
                    result_table.c.participant_id,
                    chat_table.c.user_id,
                    chat_table.c.course_id,
                    chat_table.c.team_id,
                    chat_table.c.team_version_id,
                    chat_table.c.team_owner_user_id,
                    chat_table.c.team_authorization_epoch,
                    chat_table.c.publication_id,
                    chat_table.c.publication_epoch,
                    participant_table.c.team_member_id,
                    participant_table.c.agent_id,
                    participant_table.c.agent_version_id,
                    chat_table.c.entry_kind,
                    chat_table.c.origin,
                )
                .join(turn_table, turn_table.c.id == result_table.c.turn_id)
                .join(chat_table, chat_table.c.id == result_table.c.conversation_id)
                .join(participant_table, participant_table.c.id == result_table.c.participant_id)
                .where(
                    result_table.c.id == result_id,
                    result_table.c.state == "running",
                    turn_table.c.state == "pending",
                    turn_table.c.claim_token == claim_token,
                    chat_table.c.withdrawn_at.is_(None),
                    chat_table.c.user_id == actor_user_id,
                    chat_table.c.active_request_id == turn_table.c.id,
                )
            )
            .mappings()
            .first()
        )
        if current is None:
            return False
        if current["entry_kind"] == "team":
            if (
                current["origin"] != "custom_team"
                or current["team_owner_user_id"] != actor_user_id
                or current["publication_id"] is not None
            ):
                return False
        elif current["entry_kind"] == "maya_team":
            standing_id = connection.execute(
                select(consent_table.c.standing_grant_id).where(
                    consent_table.c.manifest_hash == operation["export_manifest_hash"],
                    consent_table.c.result_id == result_id,
                )
            ).scalar_one_or_none()
            standing = (
                connection.execute(
                    select(grant_table).where(
                        grant_table.c.id == standing_id,
                        grant_table.c.team_id == current["team_id"],
                        grant_table.c.team_version_id == current["team_version_id"],
                        grant_table.c.publication_id == current["publication_id"],
                        grant_table.c.course_id == current["course_id"],
                        grant_table.c.publisher_user_id == current["team_owner_user_id"],
                        grant_table.c.provider_operation == operation["provider_operation"],
                        grant_table.c.policy_hash == operation["policy_hash"],
                        grant_table.c.team_epoch == current["team_authorization_epoch"],
                        grant_table.c.publication_epoch == current["publication_epoch"],
                        grant_table.c.revoked_at.is_(None),
                    )
                )
                .mappings()
                .first()
            )
            if current["origin"] != "published_course_team" or standing is None:
                return False
            publication = connection.execute(
                select(publication_table.c.id).where(
                    publication_table.c.id == current["publication_id"],
                    publication_table.c.team_id == current["team_id"],
                    publication_table.c.team_version_id == current["team_version_id"],
                    publication_table.c.course_id == current["course_id"],
                    publication_table.c.publisher_user_id == current["team_owner_user_id"],
                    publication_table.c.authorization_epoch == current["publication_epoch"],
                    publication_table.c.state.in_(("published", "retained")),
                )
            ).first()
            if publication is None:
                return False
        else:
            return False

        team = connection.execute(
            select(team_table.c.id).where(
                team_table.c.id == current["team_id"],
                team_table.c.course_id == current["course_id"],
                team_table.c.owner_user_id == current["team_owner_user_id"],
                team_table.c.authorization_epoch == current["team_authorization_epoch"],
                team_table.c.deleted_at.is_(None),
            )
        ).first()
        version = connection.execute(
            select(version_table.c.id).where(
                version_table.c.id == current["team_version_id"],
                version_table.c.team_id == current["team_id"],
                version_table.c.authorization_epoch == current["team_authorization_epoch"],
            )
        ).first()
        if team is None or version is None:
            return False
        member_rows = connection.execute(
            select(
                member_table.c.id, member_table.c.agent_id, member_table.c.agent_version_id
            ).where(
                member_table.c.id.in_(selected_binding_ids),
                member_table.c.team_version_id == current["team_version_id"],
            )
        ).all()
        if len(member_rows) != len(selected_binding_ids):
            return False
        if current["entry_kind"] == "team" and any(
            connection.execute(
                select(invoke_table.c.id).where(
                    invoke_table.c.team_member_id == binding_id,
                    invoke_table.c.publication_id == current["publication_id"],
                )
            ).first()
            is not None
            for binding_id in selected_binding_ids
        ):
            return False
        from app.modules.provider_disclosure.team_standing import (
            current_team_dispatch_is_authorized,
        )

        return current_team_dispatch_is_authorized(
            connection,
            operation=operation,
            actor_user_id=actor_user_id,
            result_id=result_id,
            claim_token=claim_token,
            selected_binding_ids=selected_binding_ids,
            revoked_assessment_scope=revoked_assessment_scope,
            serialized_request=serialized_request,
            current_policy_hash=current_policy_hash,
            query_context=query_context,
        )

    return guard


def dispatch_team_model(
    db: Session,
    settings: Settings,
    request: MemberRequest,
    messages: list[Message],
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    *,
    ordinal: int,
    selected_binding_ids: set[str],
    actor_context: AuthContext | None,
    allow_no_progress_once: bool = False,
    transport: LLMTransport | None = None,
) -> TeamProviderDispatch:
    """Replay a durable result stage or make one exact, one-shot provider call."""

    del actor_context
    selected = llm_provider(settings)
    if not isinstance(selected, DashScopeLLMAdapter):
        raise TeamDispatchError("provider_preflight_blocked")
    config = selected.config
    repository = ProviderRepository(db)
    policy_hash = settings.provider_policy_hash_for("llm") or ""
    policy = repository.get_policy_snapshot(policy_hash)
    if policy is None or policy.endpoint != config.resolved_endpoint:
        raise TeamDispatchError("provider_preflight_blocked")

    wire = team_request_bytes(config.model_key, messages, tools, tool_choice)
    if has_repeated_no_progress_tool_cycle(messages, tools) and not allow_no_progress_once:
        raise TeamDispatchError("team_no_progress")
    request_hash = hashlib.sha256(wire).hexdigest()
    wire_text = wire.decode("utf-8")
    message_wire = [_wire_message(message) for message in messages]
    manifest_fields: tuple[ExportFieldV1, ...]
    if request.assessment_revoked_scope is not None:
        manifest_fields = (
            ExportFieldV1(
                "private_conversation_messages",
                _digest([{"role": "user", "content": request.message}]),
            ),
            ExportFieldV1(
                "topic_and_platform_rules",
                _digest(ASSESSMENT_SOURCE_REVOKED_OWNER_ACTIONS_PROTOCOL),
            ),
        )
        persona_spec_hash = _digest(ASSESSMENT_SOURCE_REVOKED_OWNER_ACTIONS_PROTOCOL)
    else:
        manifest_fields = (
            ExportFieldV1("private_conversation_messages", _digest(message_wire)),
            ExportFieldV1("teacher_agent_instructions", _digest(request.system_message)),
            ExportFieldV1("authorized_courseware_text", _digest(request.knowledge_json)),
            ExportFieldV1("opaque_local_id", _digest(request.participant_id)),
        )
        persona_spec_hash = _digest(request.system_message)
    manifest = ExportManifestV1(
        scope_id=f"team-result:{request.result_id}",
        provider_operation="llm_agent_chat",
        model_key=config.model_key,
        policy_hash=policy.policy_hash,
        build_manifest_hash=request_hash,
        persona_spec_hash=persona_spec_hash,
        fields=manifest_fields,
    )
    revoked_command_scope = None
    if request.assessment_revoked_scope is not None:
        from app.modules.provider_disclosure.team_standing import RevokedAssessmentCommandScope

        revoked = request.assessment_revoked_scope
        revoked_command_scope = RevokedAssessmentCommandScope(
            actor_user_id=revoked.actor_user_id,
            source_conversation_id=revoked.conversation_id,
            attempt_id=revoked.attempt_id,
            activity_id=revoked.activity_id,
            turn_id=revoked.turn_id,
            result_id=revoked.result_id,
            participant_id=revoked.participant_id,
            team_member_id=revoked.team_member_id,
            source_error_code=revoked.source_error_code,
        )
        authorize_team_dispatch(
            db,
            actor_user_id=request.actor_id,
            result_id=request.result_id,
            manifest=manifest,
            selected_binding_ids=selected_binding_ids,
            claim_token=request.claim_token,
            revoked_assessment_scope=revoked_command_scope,
            serialized_request=wire,
            current_policy_hash=policy_hash,
        )
    else:
        authorize_team_dispatch(
            db,
            actor_user_id=request.actor_id,
            result_id=request.result_id,
            manifest=manifest,
            selected_binding_ids=selected_binding_ids,
            claim_token=request.claim_token,
            operator_consent=standing_consent_enabled(settings),
        )
    db.commit()
    confirmation = repository.get_export_confirmation(manifest.manifest_hash)
    if confirmation is None:
        raise TeamDispatchError("provider_confirmation_required")
    try:
        validate_provider_preflight(
            policy,
            manifest,
            confirmation,
            scope_id=manifest.scope_id,
            provider_operation=manifest.provider_operation,
            model_key=manifest.model_key,
        )
    except Exception:
        raise TeamDispatchError("provider_preflight_blocked") from None

    previous = repository.get_team_provider_call_stage(request.result_id, ordinal)
    if previous is not None:
        if previous.request_hash != request_hash or previous.request_json != wire_text:
            raise TeamDispatchError("team_request_changed")
        if previous.state in {"acceptance_unknown"}:
            raise TeamDispatchError("team_acceptance_unknown")
        if previous.state == "not_sent":
            raise TeamDispatchError("team_provider_not_sent")
        if previous.state != "succeeded" and previous.state != "accepted":
            raise TeamDispatchError("team_call_unavailable")
        if previous.accepted_response_json is None:
            raise TeamDispatchError("team_response_unavailable")
        try:
            resumed_response = _model_response(previous.accepted_response_json)
        except TeamDispatchError:
            if previous.state == "accepted":
                repository.mark_failed(
                    previous.operation_id, safe_error_code="team_response_invalid"
                )
            raise
        if previous.state == "accepted":
            repository.mark_succeeded(previous.operation_id)
        return TeamProviderDispatch(resumed_response, previous.call_id)

    scope_id = manifest.scope_id
    repository.save_scope_budget(
        scope_id,
        ProviderScopeBudgetV1(
            max_requests=CONTROL_UNBOUNDED_REQUESTS,
            max_total_tokens=CONTROL_UNBOUNDED_TOKENS,
            max_cost_cny=CONTROL_UNBOUNDED_COST_CNY,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        ),
    )
    request_record = ProviderReservationRequestV1(
        scope_id=scope_id,
        provider_operation="llm_agent_chat",
        logical_item_id=f"{request.result_id}:{ordinal}",
        attempt_no=1,
        request_hash=request_hash,
        max_tokens=TEAM_PER_CALL_MAX_TOKENS,
        max_cost_cny=0.0,
        policy_hash=policy.policy_hash,
        export_manifest_hash=manifest.manifest_hash,
        build_manifest_hash=request_hash,
        model_key=config.model_key,
    )
    guard = _current_claim_guard(
        actor_user_id=request.actor_id,
        result_id=request.result_id,
        claim_token=request.claim_token,
        selected_binding_ids=selected_binding_ids,
        revoked_assessment_scope=revoked_command_scope,
        serialized_request=wire,
        current_policy_hash=policy.policy_hash,
    )
    try:
        operation = repository.create_team_prepared(
            request_record,
            result_id=request.result_id,
            ordinal=ordinal,
            request_json=wire_text,
            claim_token=request.claim_token,
            binding_guard=guard,
        )
        repository.reserve(operation.id)
        repository.transition(
            operation.id,
            expected="reserved",
            state="sending",
            sending_guard=guard,
        )
    except ProviderDispatchRejected as exc:
        raise TeamDispatchError("team_context_changed") from exc
    except Exception as exc:
        code = getattr(exc, "code", "provider_preflight_blocked")
        safe_code = (
            code
            if isinstance(code, str) and code.startswith("provider_")
            else "provider_preflight_blocked"
        )
        raise TeamDispatchError(safe_code) from None

    provider_transport = transport or HttpxLLMTransport()
    try:
        response = provider_transport.post_bytes(
            config.resolved_endpoint,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            content=wire,
            timeout=HttpxLLMTransport.timeout(),
        )
    except LLMTransportError as exc:
        if exc.acceptance == "not_sent":
            repository.mark_not_sent(operation.id, safe_error_code=exc.safe_error_code)
            raise TeamDispatchError("team_provider_not_sent") from None
        repository.mark_acceptance_unknown(operation.id, safe_error_code=exc.safe_error_code)
        raise TeamDispatchError("team_acceptance_unknown") from None
    except Exception:
        repository.mark_acceptance_unknown(operation.id)
        raise TeamDispatchError("team_acceptance_unknown") from None

    status = getattr(response, "status_code", None)
    if status != 200:
        repository.mark_failed(
            operation.id,
            safe_error_code=(
                "provider_auth_failed" if status in {401, 403} else "provider_http_rejected"
            ),
        )
        raise TeamDispatchError(
            "provider_auth_failed" if status in {401, 403} else "team_provider_rejected"
        )
    try:
        response_json = _raw_response_text(response)
    except TeamDispatchError:
        repository.mark_failed(operation.id, safe_error_code="team_response_invalid")
        raise
    try:
        repository.stage_team_accepted(operation.id, response_json=response_json)
        result = _model_response(response_json)
    except TeamDispatchError:
        repository.mark_failed(operation.id, safe_error_code="team_response_invalid")
        raise
    except ProviderRepositoryError:
        repository.mark_failed(operation.id, safe_error_code="team_response_invalid")
        raise TeamDispatchError("team_response_invalid") from None
    repository.mark_succeeded(operation.id)
    stage = repository.get_team_provider_call_stage(request.result_id, ordinal)
    if stage is None:
        raise TeamDispatchError("team_response_unavailable")
    return TeamProviderDispatch(result, stage.call_id)


__all__ = ["TeamProviderDispatch", "dispatch_team_model", "team_request_bytes"]
