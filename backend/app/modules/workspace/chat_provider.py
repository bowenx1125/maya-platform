"""One-shot chat calls using the existing policy, budget and transport boundaries."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

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
from app.providers.control import (
    LLM_DEBATE_TURN_BUCKET,
    ExportFieldV1,
    ExportManifestV1,
    ProviderReservationRequestV1,
    ProviderScopeBudgetV1,
    confirm_export_manifest,
    validate_provider_preflight,
)
from app.providers.control_repository import (
    ProviderDispatchRejected,
    ProviderRepository,
    ProviderSendingGuard,
)
from app.providers.factory import embedding_provider, llm_provider
from app.providers.llm_adapter import DashScopeLLMAdapter
from app.providers.llm_price_card import LLM_INPUT_TOKEN_CAP, LLM_RESERVED_OUTPUT_TOKEN_CAP
from app.providers.llm_transport import HttpxLLMTransport, LLMTransportError

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
        if not (settings.demo_mode and settings.demo_auto_confirm_provider):
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
            turn_id=request_id,
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
        )
        confirmation = repository.get_export_confirmation(plan.manifest.manifest_hash)
        selected = embedding_provider(settings)
        config = getattr(selected, "config", None)
        if getattr(config, "resolved_endpoint", None) != policy.endpoint or confirmation is None:
            raise PlatformError(
                "provider_preflight_blocked", "Embedding configuration changed.", 409
            )
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
            sending_guard=sending_guard,
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
) -> tuple[str, str]:
    selected = llm_provider(settings.model_copy(update={"llm_provider": "dashscope"}))
    if not isinstance(selected, DashScopeLLMAdapter):
        raise PlatformError("provider_preflight_blocked", "LLM is not configured.", 409)
    config = selected.config
    repository = ProviderRepository(db)
    policy = repository.get_policy_snapshot(settings.provider_policy_hash_for(component) or "")
    if policy is None or policy.endpoint != config.resolved_endpoint:
        raise PlatformError("provider_preflight_blocked", "LLM policy is unavailable.", 409)
    body: dict[str, object] = {
        "model": config.model_key,
        "messages": messages,
        "stream": False,
        "enable_thinking": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "chat_reply",
                "strict": True,
                "schema": CHAT_REPLY_SCHEMA,
            },
        },
    }
    cost = 0.0
    request_hash = digest(body)
    manifest = ExportManifestV1(
        scope_id=scope_id,
        provider_operation="llm_agent_chat",
        model_key=config.model_key,
        policy_hash=policy.policy_hash,
        build_manifest_hash=request_hash,
        persona_spec_hash=persona_hash,
        fields=(
            ExportFieldV1(
                "private_conversation_messages" if version_id else "topic_and_platform_rules",
                digest(messages),
            ),
        ),
        max_total_tokens=CHAT_PER_CALL_MAX_TOKENS,
        max_cost_cny=cost,
    )
    confirm_manifest(
        db, settings, manifest, course_id=course_id, group_id=group_id, version_id=version_id
    )
    confirmation = repository.get_export_confirmation(manifest.manifest_hash)
    if confirmation is None:
        raise PlatformError("provider_confirmation_required", "Confirmation is required.", 409)
    # Chat payloads carry Agent Markdown and RAG excerpts as educational text.
    # Scanning that prose for credential-shaped substrings rejects legitimate
    # lessons (observed: SiyaH Agent.md containing "Authorization" -> export_data_forbidden).
    # Auth headers carry the API key separately; do not weaken credential handling.
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
            max_cost_cny=cost,
            policy_hash=policy.policy_hash,
            export_manifest_hash=manifest.manifest_hash,
            build_manifest_hash=request_hash,
            model_key=config.model_key,
        )
    )
    repository.reserve(operation.id)
    try:
        repository.transition(
            operation.id,
            expected="reserved",
            state="sending",
            sending_guard=sending_guard,
        )
    except ProviderDispatchRejected as exc:
        raise PlatformError("chat_request_stale", "This request is no longer active.", 409) from exc
    try:
        response = cast(
            Any,
            HttpxLLMTransport().post(
                config.resolved_endpoint,
                headers={"Authorization": f"Bearer {config.api_key}"},
                json=body,
                timeout=HttpxLLMTransport.timeout(),
            ),
        )
    except LLMTransportError as exc:
        if exc.acceptance == "not_sent":
            repository.mark_not_sent(operation.id)
        else:
            repository.mark_acceptance_unknown(operation.id)
        raise PlatformError(
            exc.safe_error_code, "The request could not be completed safely.", 503
        ) from None
    except Exception:
        repository.mark_acceptance_unknown(operation.id)
        raise PlatformError(
            "chat_acceptance_unknown", "The request outcome is unknown.", 503
        ) from None
    if response.status_code in {401, 403}:
        repository.mark_failed(operation.id, safe_error_code="provider_auth_failed")
        raise PlatformError("provider_auth_failed", "Check the API key and service access.", 503)
    try:
        if response.status_code != 200:
            raise ValueError()
        payload = response.json()
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("choices"), list)
            or len(payload["choices"]) != 1
        ):
            raise ValueError()
        choice = payload["choices"][0]
        result = json.loads(choice["message"]["content"])
        if not isinstance(result, dict) or set(result) != {"reply"}:
            raise ValueError()
        reply = result.get("reply")
        if not isinstance(reply, str) or not reply.strip() or choice.get("finish_reason") != "stop":
            raise ValueError()
    except (AttributeError, KeyError, IndexError, TypeError, ValueError):
        repository.mark_failed(operation.id, safe_error_code="chat_response_invalid")
        raise PlatformError(
            "chat_response_invalid", "The reply could not be validated.", 503
        ) from None
    repository.mark_accepted(operation.id, response_hash=digest(reply))
    return reply, operation.id


def chat_messages(
    version: AgentVersion, history: list[dict[str, str]], sources: list[ChatSource]
) -> tuple[list[dict[str, str]], str]:
    context = {
        "agent_markdown": version.agent_md,
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
        "complete history directly to remember what the user told you and what you both "
        "discussed, including when reopened. Do not replace earlier turns with a summary, "
        "crop them, or behave as though they were discarded. When asked about memory, answer "
        "from the supplied history; do not claim that every message is a fresh start or that "
        "you cannot see this supplied conversation. "
        "Do not invent memory of other conversations or facts absent from the supplied context. "
        "Use only the supplied evidence for factual citations; cite [S1] etc only when relevant. "
        "Distinguish evidence from interpretation and acknowledge missing evidence. "
        "Never claim to have access to other people's conversations or private resources. "
        "Return exactly a JSON object with one nonempty string field named reply.\n"
        + json.dumps(context, ensure_ascii=False)
    )
    return [{"role": "system", "content": instruction}, *history], markdown_hash(version.agent_md)
