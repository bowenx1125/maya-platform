"""One ledgered Preview request; no Chat runtime, Tools, history or recovery stage."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.llm_admission import llm_admission_slot
from app.modules.workspace.chat_provider import (
    CHAT_PER_CALL_MAX_TOKENS,
    CONTROL_UNBOUNDED_COST_CNY,
    CONTROL_UNBOUNDED_REQUESTS,
    CONTROL_UNBOUNDED_TOKENS,
    _chat_model_response,
    _raw_chat_response,
    confirm_manifest,
    digest,
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
from app.providers.control_repository import ProviderRepository
from app.providers.factory import llm_provider
from app.providers.llm_adapter import DashScopeLLMAdapter
from app.providers.llm_transport import HttpxLLMTransport, LLMTransportError, rejected_status_code


def preview_reply(
    db: Session,
    settings: Settings,
    *,
    scope_id: str,
    request_id: str,
    course_id: str,
    group_id: str | None,
    version_id: str | None,
    messages: list[dict[str, str]],
    persona_hash: str,
    sources: Any,
) -> tuple[str, str]:
    adapter = llm_provider(settings.chat_settings())
    if not isinstance(adapter, DashScopeLLMAdapter):
        raise PlatformError("provider_preflight_blocked", "LLM is not configured.", 409)
    config = adapter.config
    repository = ProviderRepository(db)
    policy = repository.get_policy_snapshot(settings.provider_policy_hash_for("llm") or "")
    if policy is None or policy.endpoint != config.resolved_endpoint:
        raise PlatformError("provider_preflight_blocked", "LLM policy is unavailable.", 409)
    wire = canonical_json_bytes(
        {
            "model": config.model_key,
            "messages": messages,
            "stream": False,
            "enable_thinking": False,
            "n": 1,
        }
    )
    request_hash = hashlib.sha256(wire).hexdigest()
    manifest = ExportManifestV1(
        scope_id=scope_id,
        provider_operation="llm_agent_chat",
        model_key=config.model_key,
        policy_hash=policy.policy_hash,
        build_manifest_hash=request_hash,
        persona_spec_hash=persona_hash,
        fields=(
            ExportFieldV1("authorized_courseware_text", digest([s.excerpt for s in sources])),
            ExportFieldV1("private_conversation_messages", digest(messages[1:])),
            ExportFieldV1("teacher_agent_instructions", persona_hash),
            ExportFieldV1("topic_and_platform_rules", digest(messages[0])),
        ),
        max_attempts=1,
        max_total_tokens=CHAT_PER_CALL_MAX_TOKENS,
        max_cost_cny=0.0,
    )
    confirm_manifest(
        db, settings, manifest, course_id=course_id, group_id=group_id, version_id=version_id
    )
    confirmation = repository.get_export_confirmation(manifest.manifest_hash)
    if confirmation is None:
        raise PlatformError("provider_preflight_blocked", "LLM policy is unavailable.", 409)
    validate_provider_preflight(
        policy,
        manifest,
        confirmation,
        scope_id=scope_id,
        provider_operation="llm_agent_chat",
        model_key=config.model_key,
    )
    repository.save_scope_budget(
        scope_id,
        ProviderScopeBudgetV1(
            max_requests=CONTROL_UNBOUNDED_REQUESTS,
            max_total_tokens=CONTROL_UNBOUNDED_TOKENS,
            max_cost_cny=CONTROL_UNBOUNDED_COST_CNY,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        ),
    )
    operation = repository.create_prepared(
        ProviderReservationRequestV1(
            scope_id=scope_id,
            provider_operation="llm_agent_chat",
            logical_item_id=request_id,
            attempt_no=1,
            request_hash=request_hash,
            max_tokens=CHAT_PER_CALL_MAX_TOKENS,
            max_cost_cny=0.0,
            policy_hash=policy.policy_hash,
            export_manifest_hash=manifest.manifest_hash,
            build_manifest_hash=request_hash,
            model_key=config.model_key,
        )
    )
    try:
        with llm_admission_slot():
            repository.reserve(operation.id)
            repository.transition(operation.id, expected="reserved", state="sending")
            try:
                response = HttpxLLMTransport().post_bytes(
                    config.resolved_endpoint,
                    headers={
                        "Authorization": f"Bearer {config.api_key}",
                        "Content-Type": "application/json",
                    },
                    content=wire,
                    timeout=HttpxLLMTransport.timeout(),
                )
            except PlatformError as exc:
                repository.mark_not_sent(operation.id, safe_error_code=exc.code)
                raise
            except LLMTransportError as exc:
                if exc.acceptance == "not_sent":
                    repository.mark_not_sent(operation.id, safe_error_code=exc.safe_error_code)
                else:
                    repository.mark_acceptance_unknown(
                        operation.id, safe_error_code=exc.safe_error_code
                    )
                raise PlatformError(
                    "provider_unavailable", "The preview could not be generated.", 503
                ) from None
            except Exception:
                repository.mark_acceptance_unknown(operation.id)
                raise PlatformError(
                    "chat_acceptance_unknown", "The request outcome is unknown.", 503
                ) from None
    except PlatformError:
        if repository.operation(operation.id).state == "prepared":
            repository.mark_not_sent(operation.id, safe_error_code="provider_admission_refused")
        raise
    try:
        status = getattr(response, "status_code", None)
        if status != 200:
            raise PlatformError(
                rejected_status_code(status, "chat_provider_rejected"),
                "The Provider rejected the request.",
                503,
            )
        raw = _raw_chat_response(response)
        result = _chat_model_response(raw)
        if result.tool_calls or not isinstance(result.content, str) or not result.content.strip():
            raise PlatformError("chat_response_invalid", "The reply could not be validated.", 503)
    except PlatformError as exc:
        repository.mark_failed(operation.id, safe_error_code=exc.code)
        raise
    repository.mark_accepted(operation.id, response_hash=hashlib.sha256(raw.encode()).hexdigest())
    repository.mark_succeeded(operation.id)
    return result.content, operation.id
