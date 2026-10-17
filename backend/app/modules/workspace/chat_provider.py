"""One-shot chat calls using the existing policy, budget and transport boundaries."""

import hashlib
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from agno.models.message import Message
from agno.models.response import ModelResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import PlatformError, not_found
from app.core.models import (
    Agent,
    AgentVersion,
    KnowledgeDocument,
    KnowledgeSnapshot,
    ProviderPolicySnapshot,
    SnapshotDocument,
)
from app.modules.agents.markdown import markdown_hash
from app.modules.debates.playback.generation_adapter import SqlSnapshotRetriever
from app.modules.knowledge.mock_lexical import MOCK_LEXICAL_ANCHOR_POLICY_ID
from app.modules.knowledge.providers import (
    QueryEmbeddingService,
    SqlAlchemyEmbeddingStageStore,
    SqlAlchemyQueryControlAdapter,
    controlled_query_provider,
    persisted_snapshot_identity,
)
from app.modules.knowledge.providers.query_manifest import ensure_real_query_export_manifest
from app.modules.knowledge.services import can_invoke_version, snapshot_sources_are_readable
from app.modules.learning.schemas import AssessmentRuntimeResult
from app.modules.provider_disclosure.service import (
    confirm_chat_manifest_from_standing_grant,
    single_chat_consent_is_current,
)
from app.providers.control import (
    LLM_DEBATE_TURN_BUCKET,
    ExportFieldV1,
    ExportManifestV1,
    ProviderReservationRequestV1,
    ProviderScopeBudgetV1,
    canonical_json_bytes,
    confirm_export_manifest,
    validate_provider_preflight,
)
from app.providers.control_repository import (
    ProviderDispatchRejected,
    ProviderRepository,
    ProviderRepositoryError,
    ProviderSendingGuard,
)
from app.providers.factory import embedding_provider, llm_provider
from app.providers.llm_adapter import DashScopeLLMAdapter
from app.providers.llm_price_card import LLM_INPUT_TOKEN_CAP, LLM_RESERVED_OUTPUT_TOKEN_CAP
from app.providers.llm_transport import HttpxLLMTransport, LLMTransportError
from app.providers.standing_consent import standing_consent_enabled

from .models import Conversation
from .schemas import ChatSource

# Chats must not impose its own conversation-turn or request-byte ceiling.
# The provider-control layer currently requires finite integer/float budget values,
# so use very large sentinels for scope ceilings only to mean "no product-level cap".
# Per-call reservations stay finite so successive turns can share one scope budget.
# Real provider context-window, rate-limit and transport limits still apply.
CONTROL_UNBOUNDED_REQUESTS = 2_147_483_647
CONTROL_UNBOUNDED_TOKENS = 9_223_372_036_854_775_807
CONTROL_UNBOUNDED_COST_CNY = 1.0e18
CHAT_PER_CALL_MAX_TOKENS = LLM_INPUT_TOKEN_CAP + LLM_RESERVED_OUTPUT_TOKEN_CAP
# json_object only requires any JSON value. qwen3.7-plus then sometimes returns
# a bare array such as [2026] with finish_reason stop, which fails the reply
# object check and surfaces as chat_response_invalid. A strict schema keeps the
# same one-field reply rule the prompt already states.
CHAT_REPLY_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"reply": {"type": "string"}},
    "required": ["reply"],
    "additionalProperties": False,
}
logger = logging.getLogger("maya.workspace")


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def confirm_manifest(
    db: Session,
    settings: Settings,
    manifest: ExportManifestV1,
    *,
    course_id: str,
    group_id: str | None = None,
    version_id: str | None = None,
    actor_user_id: str | None = None,
    turn_id: str | None = None,
    claim_revision: int | None = None,
) -> None:
    repository = ProviderRepository(db)
    policy = repository.get_policy_snapshot(manifest.policy_hash)
    policy_id = db.scalar(
        select(ProviderPolicySnapshot.id).where(
            ProviderPolicySnapshot.policy_hash == manifest.policy_hash
        )
    )
    if policy is None or policy_id is None:
        raise PlatformError("provider_preflight_blocked", "Provider policy is unavailable.", 409)
    db.commit()
    manifest_id = repository.ensure_export_manifest(
        manifest,
        policy_snapshot_id=policy_id,
        course_id=course_id,
        group_id=group_id,
        agent_version_id=version_id,
    )
    if repository.get_export_confirmation(manifest.manifest_hash) is None:
        granted = False
        if (
            manifest.provider_operation in {"llm_agent_chat", "embedding_query"}
            and actor_user_id is not None
            and turn_id is not None
        ):
            granted = confirm_chat_manifest_from_standing_grant(
                db,
                manifest,
                actor_user_id=actor_user_id,
                conversation_id=manifest.scope_id,
                turn_id=turn_id,
                claim_revision=claim_revision,
                current_policy_hash=(
                    settings.provider_policy_hash_for("embedding")
                    if manifest.provider_operation == "embedding_query"
                    else None
                ),
                operator_consent=standing_consent_enabled(settings),
            )
        if granted:
            return
        if (
            manifest.provider_operation == "embedding_query"
            and actor_user_id is not None
            and turn_id is not None
        ):
            raise PlatformError(
                "provider_confirmation_required",
                "A current Embedding purpose grant is required.",
                409,
                {"manifest_hash": manifest.manifest_hash},
            )
        if not standing_consent_enabled(settings):
            raise PlatformError(
                "provider_confirmation_required",
                "The teacher must confirm this disclosure.",
                409,
                {"manifest_hash": manifest.manifest_hash},
            )
        repository.save_export_confirmation(
            manifest_id,
            confirm_export_manifest(
                manifest,
                policy,
                confirmed_at=datetime.now(UTC).isoformat(),
                expected_manifest_hash=manifest.manifest_hash,
                expected_policy_hash=policy.policy_hash,
            ),
        )


def retrieve_sources(
    db: Session,
    settings: Settings,
    version: AgentVersion,
    *,
    course_id: str,
    scope_id: str,
    request_id: str,
    message: str,
    actor_user_id: str | None = None,
    turn_id: str | None = None,
    claim_revision: int | None = None,
    sending_guard: ProviderSendingGuard | None = None,
) -> list[ChatSource]:
    if version.knowledge_snapshot_id is None:
        return []
    snapshot = db.get(KnowledgeSnapshot, version.knowledge_snapshot_id)
    if snapshot is None:
        raise PlatformError("snapshot_unavailable", "The published knowledge is unavailable.", 409)
    conversation = db.get(Conversation, scope_id)
    if conversation is None or conversation.snapshot_id != snapshot.id:
        raise not_found()
    agent = db.get(Agent, version.agent_id)
    if agent is None or not can_invoke_version(db, conversation.user_id, version, agent):
        raise not_found()
    sources = db.execute(
        select(SnapshotDocument.source_authorization_epoch, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeDocument.id == SnapshotDocument.document_id)
        .where(SnapshotDocument.snapshot_id == snapshot.id)
    ).all()
    if any(document.course_id != course_id for _, document in sources) or not (
        snapshot_sources_are_readable(
            db,
            conversation.user_id,
            snapshot.id,
            agent=agent,
            allow_historical_epoch_for_owner=True,
        )
    ):
        raise not_found()
    identity = persisted_snapshot_identity(snapshot)
    query = QueryEmbeddingService()
    if identity.provider != "mock":
        if settings.embedding_provider != "dashscope":
            raise PlatformError(
                "embedding_mode_mismatch", "This knowledge requires Real Embedding.", 409
            )
        repository = ProviderRepository(db)
        policy = repository.get_policy_snapshot(
            settings.provider_policy_hash_for("embedding") or ""
        )
        if policy is None:
            raise PlatformError("provider_preflight_blocked", "Embedding is not configured.", 409)
        plan = ensure_real_query_export_manifest(
            db,
            db=db,
            scope_id=scope_id,
            turn_id=turn_id or request_id,
            course_id=course_id,
            group_id=agent.group_id,
            agent_version_id=version.id,
            snapshot_id=snapshot.id,
            identity=identity,
            transcript_hash=digest(message),
            persona_spec_hash=markdown_hash(version.agent_md),
            subqueries=(("viewpoint", message),),
            policy=policy,
        )
        confirm_manifest(
            db,
            settings,
            plan.manifest,
            course_id=course_id,
            group_id=agent.group_id,
            version_id=version.id,
            actor_user_id=actor_user_id,
            turn_id=turn_id,
            claim_revision=claim_revision,
        )
        confirmation = repository.get_export_confirmation(plan.manifest.manifest_hash)
        selected = embedding_provider(settings.chat_settings())
        config = getattr(selected, "config", None)
        if getattr(config, "resolved_endpoint", None) != policy.endpoint or confirmation is None:
            raise PlatformError(
                "provider_preflight_blocked", "Embedding configuration changed.", 409
            )
        query_sending_guard = sending_guard
        if actor_user_id is not None and turn_id is not None and claim_revision is not None:

            def query_sending_guard_with_consent(connection: Any, operation: Any) -> bool:
                return (
                    sending_guard is not None
                    and sending_guard(connection, operation)
                    and single_chat_consent_is_current(
                        connection,
                        manifest_hash=plan.manifest.manifest_hash,
                        conversation_id=scope_id,
                        actor_user_id=actor_user_id,
                        course_id=course_id,
                        policy_hash=policy.policy_hash,
                        field_classes=("current_evidence_excerpt",),
                        provider_operation="embedding_query",
                    )
                )

            query_sending_guard = query_sending_guard_with_consent
        control = SqlAlchemyQueryControlAdapter(
            db,
            scope_id=scope_id,
            snapshot_id=snapshot.id,
            identity=identity,
            policy_hash=policy.policy_hash,
            export_manifest_hash=plan.manifest.manifest_hash,
            build_manifest_hash=plan.build_manifest_hash,
            query_hashes=plan.query_hashes,
            logical_item_id=f"chat:{request_id}",
            max_requests=CONTROL_UNBOUNDED_REQUESTS,
            confirmation_revision=confirmation.confirmation_revision,
            sending_guard=query_sending_guard,
        )
        query = QueryEmbeddingService(
            provider=controlled_query_provider(
                selected, control=control, stage_store=SqlAlchemyEmbeddingStageStore(db)
            ),
            control=control,
            manifest=control,
            budget=control,
            build_manifest_hash=plan.build_manifest_hash,
        )
    result = SqlSnapshotRetriever(db, query_embeddings=query).retrieve(
        snapshot.id,
        [message],
        policy_id=MOCK_LEXICAL_ANCHOR_POLICY_ID if identity.provider == "mock" else None,
        topic_anchor=message if identity.provider == "mock" else None,
    )
    return [
        ChatSource(chunk_id=UUID(item.chunk_id), filename=item.source_filename, excerpt=item.text)
        for item in result.receipts
    ]


def _single_chat_inputs_are_current(
    db: Session,
    *,
    actor_id: str,
    conversation_id: str,
    version_id: str,
) -> bool:
    conversation = db.get(Conversation, conversation_id)
    version = db.get(AgentVersion, version_id)
    if (
        conversation is None
        or version is None
        or conversation.entry_kind != "agent"
        or conversation.withdrawn_at is not None
        or conversation.user_id != actor_id
        or conversation.agent_version_id != version.id
        or conversation.snapshot_id != version.knowledge_snapshot_id
    ):
        return False
    agent = db.get(Agent, version.agent_id)
    if (
        agent is None
        or agent.deleted_at is not None
        or agent.status != "active"
        or (
            agent.owner_user_id != actor_id
            and conversation.agent_authorization_epoch != agent.authorization_epoch
        )
        or not can_invoke_version(db, actor_id, version, agent)
    ):
        return False
    if conversation.snapshot_id is None:
        return True
    return snapshot_sources_are_readable(
        db,
        actor_id,
        conversation.snapshot_id,
        agent=agent,
        allow_historical_epoch_for_owner=True,
    )


def _turn_generated_knowledge(db: Session, conversation_id: str, turn_id: str) -> bool:
    """This turn's own Knowledge generation is the expected change, not a stale context.

    Starting generation binds the new Knowledge to the Agent at once, so the
    reply after the Tool call would otherwise fail its own turn.
    """

    from app.modules.runtime_tools.knowledge import GENERATE_AGENT_KNOWLEDGE_TOOL
    from app.modules.runtime_tools.models import RuntimeToolReceipt

    return (
        db.scalar(
            select(RuntimeToolReceipt.id)
            .where(
                RuntimeToolReceipt.conversation_id == conversation_id,
                RuntimeToolReceipt.turn_id == turn_id,
                RuntimeToolReceipt.tool_name == GENERATE_AGENT_KNOWLEDGE_TOOL,
            )
            .limit(1)
        )
        is not None
    )


def real_reply(
    db: Session,
    settings: Settings,
    *,
    scope_id: str,
    request_id: str,
    course_id: str,
    messages: list[dict[str, str]],
    persona_hash: str,
    version_id: str | None = None,
    group_id: str | None = None,
    component: str = "llm",
    sending_guard: ProviderSendingGuard | None = None,
    actor_context: Any | None = None,
    sources: list[ChatSource] | None = None,
    canonical_knowledge: list[dict[str, Any]] | None = None,
    allow_not_sent_retry: bool = False,
    generation_waker: Callable[[str], None] | None = None,
    required_tool: str | None = None,
) -> tuple[str, str]:
    selected = llm_provider(
        settings.chat_settings().model_copy(update={"llm_provider": "dashscope"})
    )
    if not isinstance(selected, DashScopeLLMAdapter):
        raise PlatformError("provider_preflight_blocked", "LLM is not configured.", 409)
    config = selected.config
    repository = ProviderRepository(db)
    policy = repository.get_policy_snapshot(settings.provider_policy_hash_for(component) or "")
    if policy is None or policy.endpoint != config.resolved_endpoint:
        raise PlatformError("provider_preflight_blocked", "LLM policy is unavailable.", 409)
    from .chat_team_sdk import MemberSpec, TeamDispatchError, run_selected_agent

    model_messages = [
        Message(role=item["role"], content=item["content"])
        for item in messages
        if isinstance(item, dict) and isinstance(item.get("role"), str)
    ]
    if not model_messages or model_messages[-1].role != "user":
        raise PlatformError("chat_messages_invalid", "The conversation could not be prepared.", 503)
    participant_id = version_id or scope_id
    tools: list[Any] = []
    if actor_context is not None and version_id is not None:
        from app.modules.runtime_tools.runtime import build_runtime_tools

        tools = build_runtime_tools(
            sessionmaker(bind=db.get_bind(), expire_on_commit=False),
            actor_context.user.id,
            scope_id,
            participant_id,
            request_id,
            settings,
            actor_context=actor_context,
            generation_waker=generation_waker,
        )

    cursors: dict[str, int] = {}
    latest_operation: str | None = None

    def dispatch(
        member_id: str,
        _invocation_id: str,
        current_messages: Any,
        tool_schemas: list[dict[str, Any]] | None,
        tool_choice: Any,
        _run_context: Any,
    ) -> ModelResponse:
        nonlocal latest_operation
        if member_id != participant_id:
            raise TeamDispatchError("chat_context_changed")
        if actor_context is not None and version_id is not None:
            if not _single_chat_inputs_are_current(
                db,
                actor_id=actor_context.user.id,
                conversation_id=scope_id,
                version_id=version_id,
            ):
                raise TeamDispatchError("chat_context_changed")
            if canonical_knowledge is not None:
                version = db.get(AgentVersion, version_id)
                if version is None:
                    raise TeamDispatchError("chat_context_changed")
                from app.modules.knowledge_sets.service import get_agent_runtime_knowledge

                try:
                    current_knowledge = get_agent_runtime_knowledge(
                        db, actor_context, version.agent_id
                    )
                except PlatformError:
                    raise TeamDispatchError("chat_context_changed") from None
                if current_knowledge != canonical_knowledge and not _turn_generated_knowledge(
                    db, scope_id, request_id
                ):
                    raise TeamDispatchError("chat_context_changed")
        dispatch_ordinal = cursors.get(member_id, 0)
        cursors[member_id] = dispatch_ordinal + 1
        wire_messages = [_chat_wire_message(item) for item in current_messages]
        body: dict[str, object] = {
            "model": config.model_key,
            "messages": wire_messages,
            "stream": False,
            "enable_thinking": False,
        }
        if tool_schemas is not None:
            body["tools"] = tool_schemas
        offered = {
            tool.get("function", {}).get("name")
            for tool in tool_schemas or []
            if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
        }
        if dispatch_ordinal == 0 and required_tool is not None and required_tool in offered:
            # The caller rejects this turn unless the tool runs, so the model
            # is not allowed to answer in prose instead.
            tool_choice = {"type": "function", "function": {"name": required_tool}}
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        try:
            wire = canonical_json_bytes(body)
        except Exception:
            raise TeamDispatchError("chat_messages_invalid") from None
        request_hash = hashlib.sha256(wire).hexdigest()
        wire_text = wire.decode("utf-8")
        manifest = ExportManifestV1(
            scope_id=scope_id,
            provider_operation="llm_agent_chat",
            model_key=config.model_key,
            policy_hash=policy.policy_hash,
            build_manifest_hash=request_hash,
            persona_spec_hash=persona_hash,
            fields=(
                ExportFieldV1(
                    "authorized_courseware_text",
                    digest(
                        {
                            "evidence": [
                                {"filename": source.filename, "excerpt": source.excerpt}
                                for source in (sources or [])
                            ],
                            "canonical_knowledge": canonical_knowledge,
                        }
                        if canonical_knowledge
                        else [
                            {"filename": source.filename, "excerpt": source.excerpt}
                            for source in (sources or [])
                        ]
                    ),
                ),
                ExportFieldV1(
                    "private_conversation_messages",
                    digest(wire_messages[1:]),
                ),
                ExportFieldV1("teacher_agent_instructions", persona_hash),
                ExportFieldV1(
                    "topic_and_platform_rules",
                    digest(
                        {
                            "system_message": wire_messages[0],
                            "tool_schemas": tool_schemas or [],
                        }
                    ),
                ),
            ),
            max_total_tokens=CHAT_PER_CALL_MAX_TOKENS,
            max_cost_cny=0.0,
        )
        try:
            confirm_manifest(
                db,
                settings,
                manifest,
                course_id=course_id,
                group_id=group_id,
                version_id=version_id,
                actor_user_id=(str(actor_context.user.id) if actor_context is not None else None),
                turn_id=request_id,
            )
            confirmation = repository.get_export_confirmation(manifest.manifest_hash)
            if confirmation is None:
                raise PlatformError(
                    "provider_confirmation_required", "Confirmation is required.", 409
                )
            # Chat content and tool schemas are educational text. Authorization
            # headers carry credentials separately from this exact request body.
            validate_provider_preflight(
                policy,
                manifest,
                confirmation,
                scope_id=scope_id,
                provider_operation="llm_agent_chat",
                model_key=config.model_key,
            )
            field_classes = tuple(field.field_class for field in manifest.fields)
            if actor_context is not None and not single_chat_consent_is_current(
                db.connection(),
                manifest_hash=manifest.manifest_hash,
                conversation_id=scope_id,
                actor_user_id=str(actor_context.user.id),
                course_id=course_id,
                policy_hash=policy.policy_hash,
                field_classes=field_classes,
            ):
                raise PlatformError(
                    "provider_confirmation_required",
                    "The Provider authorization is no longer current.",
                    409,
                )
            previous = repository.get_runtime_model_call_stage(
                request_id, participant_id, dispatch_ordinal
            )
            retry_not_sent = False
            if previous is not None:
                if previous.request_hash != request_hash or previous.request_json != wire_text:
                    raise TeamDispatchError("chat_request_changed")
                if previous.state == "acceptance_unknown":
                    raise TeamDispatchError("chat_acceptance_unknown")
                if previous.state == "not_sent":
                    if not allow_not_sent_retry:
                        raise TeamDispatchError("chat_provider_not_sent")
                    retry_not_sent = True
                elif previous.state in {"accepted", "succeeded"}:
                    latest_operation = previous.operation_id
                    if previous.accepted_response_json is None:
                        raise TeamDispatchError("chat_response_unavailable")
                    try:
                        model_response = _chat_model_response(previous.accepted_response_json)
                    except PlatformError as exc:
                        if previous.state == "accepted":
                            repository.mark_failed(previous.operation_id, safe_error_code=exc.code)
                        raise
                    if previous.state == "accepted":
                        repository.mark_succeeded(previous.operation_id)
                    return model_response
                else:
                    raise TeamDispatchError("chat_call_unavailable")

            ordinal = repository.next_runtime_model_call_ordinal(request_id, participant_id)
            if previous is not None and not retry_not_sent:
                raise TeamDispatchError("chat_call_unavailable")

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
                logical_item_id=request_id,
                attempt_no=ordinal + 1,
                request_hash=request_hash,
                # This reserves an estimate only; it is not sent as max_tokens.
                max_tokens=CHAT_PER_CALL_MAX_TOKENS,
                max_cost_cny=0.0,
                policy_hash=policy.policy_hash,
                export_manifest_hash=manifest.manifest_hash,
                build_manifest_hash=request_hash,
                model_key=config.model_key,
            )
            effective_sending_guard = sending_guard
            if actor_context is not None:

                def guarded_sending(connection: Any, operation: Any) -> bool:
                    return bool(
                        (sending_guard is None or sending_guard(connection, operation))
                        and single_chat_consent_is_current(
                            connection,
                            manifest_hash=manifest.manifest_hash,
                            conversation_id=scope_id,
                            actor_user_id=str(actor_context.user.id),
                            course_id=course_id,
                            policy_hash=policy.policy_hash,
                            field_classes=field_classes,
                        )
                    )

                effective_sending_guard = guarded_sending

            operation = repository.create_runtime_model_call_prepared(
                request_record,
                conversation_id=scope_id,
                turn_id=request_id,
                executor_agent_version_id=participant_id,
                ordinal=ordinal,
                dispatch_ordinal=dispatch_ordinal,
                request_json=wire_text,
                binding_guard=effective_sending_guard or (lambda _connection, _operation: True),
            )
            repository.reserve(operation.id)
            try:
                repository.transition(
                    operation.id,
                    expected="reserved",
                    state="sending",
                    sending_guard=effective_sending_guard,
                )
            except ProviderDispatchRejected as exc:
                raise PlatformError(
                    "chat_request_stale", "This request is no longer active.", 409
                ) from exc
            latest_operation = operation.id
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
                # Memory pressure (and any future pre-send PlatformError) means
                # bytes never left the host — treat as not_sent, preserve code.
                repository.mark_not_sent(operation.id, safe_error_code=exc.code)
                raise
            except LLMTransportError as exc:
                if exc.acceptance == "not_sent":
                    repository.mark_not_sent(operation.id, safe_error_code=exc.safe_error_code)
                    raise PlatformError(
                        "chat_provider_not_sent", "The Provider did not receive this request.", 503
                    ) from None
                repository.mark_acceptance_unknown(
                    operation.id, safe_error_code=exc.safe_error_code
                )
                raise PlatformError(
                    "chat_acceptance_unknown", "The request outcome is unknown.", 503
                ) from None
            except Exception:
                repository.mark_acceptance_unknown(operation.id)
                raise PlatformError(
                    "chat_acceptance_unknown", "The request outcome is unknown.", 503
                ) from None
            status = getattr(response, "status_code", None)
            if status in {401, 403}:
                repository.mark_failed(operation.id, safe_error_code="provider_auth_failed")
                raise PlatformError(
                    "provider_auth_failed", "Check the API key and service access.", 503
                )
            if status != 200:
                repository.mark_failed(operation.id, safe_error_code="provider_http_rejected")
                raise PlatformError(
                    "chat_provider_rejected", "The Provider rejected the request.", 503
                )
            response_json = _raw_chat_response(response)
            repository.stage_runtime_model_call_accepted(operation.id, response_json=response_json)
            try:
                model_response = _chat_model_response(response_json)
            except PlatformError as exc:
                repository.mark_failed(operation.id, safe_error_code=exc.code)
                raise
            repository.mark_succeeded(operation.id)
            return model_response
        except PlatformError:
            raise
        except (ProviderDispatchRejected, ProviderRepositoryError, ValueError, TypeError) as exc:
            logger.warning(
                "Single Chat dispatch rejected conversation_id=%s request_id=%s error_type=%s",
                scope_id,
                request_id,
                type(exc).__name__,
            )
            raise TeamDispatchError("chat_dispatch_unavailable") from None
        except Exception as exc:
            logger.warning(
                "Single Chat dispatch unavailable conversation_id=%s request_id=%s error_type=%s",
                scope_id,
                request_id,
                type(exc).__name__,
            )
            raise TeamDispatchError("chat_dispatch_unavailable") from None

    if len(model_messages) < 2 or model_messages[0].role != "system":
        raise PlatformError("chat_messages_invalid", "The conversation could not be prepared.", 503)
    system_prompt = model_messages[0].content
    final_message = model_messages[-1].content
    if not isinstance(system_prompt, str) or not isinstance(final_message, str):
        raise PlatformError("chat_messages_invalid", "The conversation could not be prepared.", 503)
    try:
        output = run_selected_agent(
            MemberSpec(participant_id, "Maya Chat Agent", system_prompt),
            model_key=config.model_key,
            dispatch=dispatch,
            actor_id=actor_context.user.id if actor_context is not None else scope_id,
            conversation_id=scope_id,
            turn_id=request_id,
            history=model_messages[1:-1],
            message=final_message,
            tools=tools,
        )
    except TeamDispatchError as exc:
        code = exc.safe_error_code
        raise PlatformError(code, "The chat request could not be completed safely.", 503) from None
    if not isinstance(output.content, str) or not output.content.strip():
        raise PlatformError("chat_response_invalid", "The reply could not be validated.", 503)
    if latest_operation is None:
        raise PlatformError("chat_response_unavailable", "The reply was not saved.", 503)
    return output.content, latest_operation


def _chat_wire_message(message: Message) -> dict[str, Any]:
    if not isinstance(message.role, str) or not message.role:
        raise ValueError("invalid role")
    if message.content is not None and not isinstance(message.content, str):
        raise ValueError("text-only chat")
    result: dict[str, Any] = {"role": message.role, "content": message.content}
    for field in ("name", "tool_call_id", "tool_calls"):
        value = getattr(message, field, None)
        if value is not None:
            result[field] = value
    return result


def _raw_chat_response(response: object) -> str:
    raw = getattr(response, "content", None)
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise PlatformError(
                "chat_response_invalid", "The reply could not be validated.", 503
            ) from None
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    json_method = getattr(response, "json", None)
    if callable(json_method):
        try:
            return canonical_json_bytes(json_method()).decode("utf-8")
        except Exception:
            pass
    raise PlatformError("chat_response_invalid", "The reply could not be validated.", 503)


def _chat_model_response(response_json: str) -> ModelResponse:
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
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        raise PlatformError(
            "chat_response_invalid", "The reply could not be validated.", 503
        ) from None


def conversation_user_texts(db: Session, conversation_id: str) -> list[str]:
    from .models import ConversationTurn

    return list(
        db.scalars(
            select(ConversationTurn.user_text)
            .where(ConversationTurn.conversation_id == conversation_id)
            .order_by(ConversationTurn.position, ConversationTurn.id)
        )
    )


_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN_WORD = re.compile(r"[A-Za-z]+")
_OPTION_LETTER = re.compile(r"[A-Fa-f]")
_ASKS_ENGLISH = re.compile(
    r"(用|说|讲|换成|改用|改成|切换到?)\s*英文|英文(回答|回复|交流|说)"
    r"|\b(in|speak|use|switch to|reply in|answer in)\s+english\b",
    re.IGNORECASE,
)
_ASKS_CHINESE = re.compile(
    r"(用|说|讲|换成|改用|改成|切换到?)\s*中文|中文(回答|回复|交流|说)"
    r"|\b(in|speak|use|switch to|reply in|answer in)\s+chinese\b",
    re.IGNORECASE,
)


def sentence_chinese(text: str) -> bool | None:
    """The language of one message, or None when it is not a sentence.

    Owner decision (2026-10-13): only a sentence changes the reply language.
    An option letter ("B", "A C"), a number, an ID or a single word such as
    "skip" says nothing about it. A request for a language wins.
    """

    if _ASKS_ENGLISH.search(text):
        return False
    if _ASKS_CHINESE.search(text):
        return True
    if len(_CJK.findall(text)) >= 2:
        return True
    words = [word for word in _LATIN_WORD.findall(text) if not _OPTION_LETTER.fullmatch(word)]
    if not _CJK.search(text) and len(words) >= 2:
        return False
    return None


def latest_sentence_chinese(user_texts: list[str]) -> bool | None:
    """The language of the learner's latest sentence, if they wrote one."""

    for text in reversed(user_texts):
        language = sentence_chinese(text)
        if language is not None:
            return language
    return None


def prefers_chinese(user_texts: list[str]) -> bool:
    """Follow the learner's latest sentence; English before any sentence."""

    return bool(latest_sentence_chinese(user_texts))


def reply_language_from_projection(value: dict[str, Any]) -> tuple[dict[str, Any], bool | None]:
    """Split the Leader's chosen reply language off a stored assessment result."""

    projection = dict(value)
    language = projection.pop("reply_language", None)
    return projection, (language == "zh" if language in {"zh", "en"} else None)


def assessment_reply_chinese(db: Session, conversation_id: str, user_texts: list[str]) -> bool:
    """The language of server sentences: the learner's latest sentence decides.

    A bare option letter is not a sentence, so answering "B" keeps the current
    language. A student who asks for English gets English progress lines.
    Before any sentence, the Leader's latest choice applies.
    """

    latest = latest_sentence_chinese(user_texts)
    if latest is not None:
        return latest

    from app.modules.runtime_tools.models import RuntimeToolReceipt

    for raw in db.scalars(
        select(RuntimeToolReceipt.result_json)
        .where(
            RuntimeToolReceipt.conversation_id == conversation_id,
            RuntimeToolReceipt.tool_name == "assessment_action",
        )
        .order_by(RuntimeToolReceipt.created_at.desc(), RuntimeToolReceipt.id.desc())
        .limit(20)
    ):
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        value = payload.get("result") if isinstance(payload, dict) else None
        if isinstance(value, dict):
            _projection, chinese = reply_language_from_projection(value)
            if chinese is not None:
                return chinese
    return prefers_chinese(user_texts)


def assessment_safe_reply_text(
    result: AssessmentRuntimeResult,
    user_texts: list[str],
    *,
    prose: str | None = None,
    follow_up: bool = False,
    chinese: bool | None = None,
    follow_up_pending: bool = False,
    include_question: bool = True,
    opening: str | None = None,
) -> str:
    """Render the server's student-safe assessment projection.

    ``prose`` is accepted only for read-only progress replies, where the member
    may answer an unrelated or formatting question before the server restates
    progress and the current Question.
    """
    if chinese is None:
        chinese = prefers_chinese(user_texts)
    context = result.context
    if result.response_key == "assessment.redirect":
        if context.redirect_to_original_conversation:
            redirect = (
                "请回到原对话继续测试。" if chinese else "Continue this test in its original chat."
            )
        elif result.disposition == "read":
            redirect = (
                "测试进行中，不能提供答案、提示或评判。"
                if chinese
                else "Answers, hints and judgments aren't available during the test."
            )
        else:
            redirect = "我们继续测试。" if chinese else "Let's continue the test."
    else:
        redirect = ""
    labels = {
        "assessment.started": (
            "正式测试开始，你的作答会保存到学习记录。"
            if chinese
            else "Formal test started. Your answers will be saved to your learning record."
        ),
        "assessment.answer_recorded": ("已记录你的回答。" if chinese else "Answer saved."),
        "assessment.answer_recorded_restricted_request": (
            "已记录你的回答。测试中不能提供答案、提示或评判。"
            if chinese
            else "Answer saved. Answers, hints and judgments aren't available during the test."
        ),
        "assessment.paused": (
            "测试已暂停，说“继续”即可接着答。"
            if chinese
            else 'Test paused. Say "continue" to pick up where you left off.'
        ),
        "assessment.resumed": ("测试继续。" if chinese else "Test resumed."),
        "assessment.completed": (
            "测试结束，恭喜完成！作答记录已保存。你可以继续聊天，之后的对话不会计入这次测试。"
            if chinese
            else (
                "Test complete. Congratulations! Your answers are saved. You can keep "
                "chatting; nothing after this counts toward the test."
            )
        ),
        "assessment.abandoned": (
            "已放弃本次测试，作答记录不会保留。"
            if chinese
            else "Test abandoned. Its answers were not kept."
        ),
        "assessment.abandoned_and_restarted": (
            "已放弃上一次测试并重新开始，旧的作答不会保留。"
            if chinese
            else (
                "The previous test was abandoned without keeping its answers. "
                "A new test has started."
            )
        ),
        "assessment.progress": ("当前进度：" if chinese else "Progress:"),
        "assessment.answers": ("你已提交的回答：" if chinese else "Your submitted answers:"),
        "assessment.results_pending": (
            "好的，正在保存并评估你的作答。"
            if chinese
            else "Okay. Saving and reviewing your answers."
        ),
        "assessment.restart_requires_choice": (
            "要重新开始，请明确说“放弃并重做”。"
            if chinese
            else 'To start over, say "abandon and redo".'
        ),
        "assessment.redirect": redirect,
    }
    progress = context.progress
    # Every Question of the round is resolved: the server is already scoring,
    # so nothing is left for the student to submit or say.
    grading = (
        context.attempt.status == "in_progress"
        and progress.question_count > 0
        and progress.resolved_count >= progress.question_count
    )
    question = context.current_question
    latest = user_texts[-1].strip() if user_texts else ""
    from app.modules.learning.answer_format import answer_format, format_hint

    # Owner decision (2026-10-13): a reply that is not this Question's answer
    # is named as such, with the format to use, instead of "我们继续测试" or a
    # progress count the student did not ask for.
    not_recorded = assessment_answer_not_recorded(result, latest)
    lines = []
    guidance = (result.guidance or "").strip()
    if not_recorded and guidance:
        # The model said how to answer, or acknowledged the student. The
        # question text is not pasted again on this turn.
        lines.append(guidance)
    elif not_recorded and question is not None:
        lines.append(
            (
                "这条回复不是本题的答案，没有记录。"
                if chinese
                else "That reply was not recorded as an answer to this question. "
            )
            + format_hint(answer_format(question.prompt), chinese)
        )
    else:
        if prose and prose.strip() and not grading:
            lines.append(prose.strip())
        lines.append(labels[result.response_key])
    if grading and result.response_key != "assessment.results_pending":
        # Follow-ups still to come: this is not the final scoring yet.
        lines.append(
            ("请稍候。" if chinese else "One moment, please.")
            if follow_up_pending
            else "本轮题目已全部作答，正在保存并评分，请稍候。"
            if chinese
            else "Every question this round is answered. Saving and scoring now."
        )
    if result.response_key in {"assessment.progress", "assessment.answers"} and not not_recorded:
        if chinese:
            lines.append(
                f"已完成 {progress.resolved_count}/{progress.question_count} 题；"
                f"已回答 {progress.answered_count} 题，跳过 {progress.skipped_count} 题。"
            )
        else:
            lines.append(
                f"Resolved {progress.resolved_count}/{progress.question_count}; "
                f"answered {progress.answered_count}, skipped {progress.skipped_count}."
            )
    if result.response_key == "assessment.answers":
        for answer in result.answers:
            lines.append(
                f"你的回答：{answer.answer_text}"
                if chinese
                else f"Your answer: {answer.answer_text}"
            )
    if include_question and question is not None:
        if follow_up:
            lines.append("下面是追问。" if chinese else "Next, a follow-up question.")
        ordinal = question.ordinal + 1
        lines.append(
            f"第 {ordinal} 题：{question.prompt}"
            if chinese
            else f"Question {ordinal}: {question.prompt}"
        )
    rendered = "\n\n".join(lines)
    preamble = (opening or "").strip()
    # Only the turn that opens Question 1. Later answers keep the question line alone.
    if (
        preamble
        and include_question
        and question is not None
        and result.response_key in {"assessment.started", "assessment.abandoned_and_restarted"}
    ):
        return f"{preamble}\n\n{rendered}"
    return rendered


def assessment_answer_not_recorded(result: AssessmentRuntimeResult, latest_user_text: str) -> bool:
    """Whether this result refused to store the latest message as an answer.

    The scorer states the miss and the format. The Guide restates the Question
    once. Both pasting the Question is the duplicate re-ask.
    """

    from app.modules.learning.answer_format import asks_progress

    context = result.context
    progress = context.progress
    grading = (
        context.attempt.status == "in_progress"
        and progress.question_count > 0
        and progress.resolved_count >= progress.question_count
    )
    question = context.current_question
    return (
        question is not None
        and not grading
        and not context.redirect_to_original_conversation
        and (
            (
                result.response_key == "assessment.progress"
                and not asks_progress(latest_user_text.strip())
            )
            or (result.response_key == "assessment.redirect" and result.disposition != "read")
        )
    )


ACCOUNT_MEMORY_RULE = (
    "This chat window is only the messages supplied in this request. "
    "Account memory belongs only to the signed-in account and the Agent that is speaking. "
    "Other accounts cannot read or write it. Public or Private only decides who may use the Agent, "
    "not who may see that memory. Debate input never includes account memory. "
    "Call read_agent_memory for notes this account asked this Agent to remember across chats. "
    "Call read_memory or the assessment tools for this formal test's saved answers and progress. "
    "Do not treat assessment records as account memory or the reverse. "
    "Call write_agent_memory when the user wants this Agent to keep something for later "
    "chats, however they phrase it. text must be an exact span of the user's own words "
    "in this chat. "
    "If read_agent_memory already has that fact, pass its memory_id and restate the fact "
    "in the current message. "
    "In a Team, if it is unclear which member should keep it, the Leader asks who and does "
    "not write yet. After the user names one or more members, the Leader calls "
    "write_agent_memory with those member_names. "
    "A single-Agent chat, or an @ member, writes only that speaking Agent's notes. "
    "Never write another account's memory, an assessment answer, a score, or a Rubric."
)

AGENT_LIMIT_REPLY_RULE = (
    "If the user asks to see records, statistics, reports or another person's work that this "
    "role or this chat is not allowed to see, your entire reply is exactly 看不到。 when the "
    "user has been writing in Chinese, or exactly Can't see that. when they have been writing "
    "in English. If the user asks for a function you do not have, your entire reply is exactly "
    "做不到。 when the user has been writing in Chinese, or exactly Can't. when they have been "
    "writing in English. Do not call a tool for either case, and do not repeat a tool call that "
    "already returned the same denial or the same result."
)


def chat_messages(
    version: AgentVersion,
    history: list[dict[str, str]],
    sources: list[ChatSource],
    *,
    canonical_knowledge: list[dict[str, Any]] | None = None,
    audience: Literal["student", "teacher"] = "student",
) -> tuple[list[dict[str, str]], str]:
    context = {
        "agent_markdown": version.agent_md,
        "canonical_knowledge": canonical_knowledge or [],
        "evidence": [
            {"label": f"S{index + 1}", "text": item.excerpt} for index, item in enumerate(sources)
        ],
    }
    instruction = (
        "You are the selected educational Agent in a private one-to-one conversation. "
        "Follow the published agent_markdown for your identity, style and approach to questions. "
        "Determine the reply language from the final user message in this request. "
        "When that message is in Chinese, write the reply in Chinese; when it is in English, "
        "write the reply in English. Follow an explicit request to translate or answer in "
        "another language instead. For mixed-language messages, use the language of the "
        "actual question; brief names, quotations and technical terms do not change it. "
        "This reply-language rule takes priority over language preferences in agent_markdown, "
        "evidence and earlier conversation messages, including earlier assistant replies. "
        "Do not carry an earlier reply's language into the current answer. "
        "当前消息用中文提问时，默认用中文回答；仅在用户明确要求其他语言时切换。 "
        "The user and assistant messages below are the complete saved history of this same "
        "conversation, in chronological order, followed by the current question. Use the "
        "complete history directly for what was said in this window. Do not replace earlier "
        "turns with a summary, crop them, or behave as though they were discarded. "
        f"{ACCOUNT_MEMORY_RULE} "
        "Use only the supplied evidence for factual citations; cite [S1] etc only when relevant. "
        "Distinguish evidence from interpretation and acknowledge missing evidence. "
        "Never claim to have access to other people's conversations or private resources. "
        "Reply directly in natural text. Use any available Maya Tools when the current task "
        "calls for a saved record or formal activity action; never claim an action succeeded "
        "unless its Tool returns success. "
        + (
            "The person writing is a course teacher, not a student taking a test. "
            "Do not greet them as the learner or tell them to continue a question. "
            "When they ask about attempts, answers, scores or summaries, call the teacher "
            "tools and use only what those tools return. phase summary_not_saved, or "
            "summary_status not_saved, means the answers are saved and the summary write "
            "failed. Do not quote internal field names such as boundary_summary. "
            "Do not say a report was generated, a download is below, or an answer sheet "
            "is attached unless the tool result for this turn contains that report or "
            "those attempts. "
            if audience == "teacher"
            else ""
        )
        + f"{AGENT_LIMIT_REPLY_RULE}\n"
        + json.dumps(context, ensure_ascii=False)
    )
    return [{"role": "system", "content": instruction}, *history], markdown_hash(version.agent_md)
