"""Teacher Knowledge generation is bound to the Agent in the current chat."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.core.models import Agent, AgentVersion, ProviderOperation
from app.modules.agents.schemas import KnowledgeGenerationIntent
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import _agent_workspace_role, _enabled_documents
from app.modules.knowledge_sets.generation import (
    _current_generation_authorized,
    enqueue_generation_for_existing_set,
    enqueue_generation_for_publish,
    record_generation_action_alias_for_run,
    replay_generation_action_alias_for_run,
)
from app.modules.knowledge_sets.models import (
    AgentKnowledgeSet,
    KnowledgeGenerationRun,
    KnowledgeSet,
)
from app.modules.workspace.models import Conversation

from .registry import ToolCallIdentity, ToolSpec

GENERATE_AGENT_KNOWLEDGE_TOOL = "generate_agent_knowledge"
_TOOL_ACTION_NAMESPACE = UUID("28bbdb15-5e46-40c1-9c79-48538ad5da46")


class GenerateAgentKnowledgeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _current_agent(
    db: Session, actor: AuthContext, row: Conversation
) -> tuple[Agent, AgentVersion]:
    if row.entry_kind != "agent" or row.user_id != actor.user.id or row.agent_version_id is None:
        raise not_found()
    version = db.get(AgentVersion, row.agent_version_id)
    agent = db.get(Agent, version.agent_id) if version is not None else None
    if (
        version is None
        or agent is None
        or version.agent_id != agent.id
        or version.state != "published"
        or agent.current_published_version_id != version.id
        or agent.owner_user_id != actor.user.id
        or agent.course_id != row.course_id
        or agent.deleted_at is not None
        or agent.status != "active"
        or _agent_workspace_role(db, actor.user.id, agent) != "owner"
    ):
        raise not_found()
    return agent, version


def authorize_generate_agent_knowledge(
    db: Session, actor: AuthContext, row: Conversation, _payload: BaseModel
) -> None:
    _current_agent(db, actor, row)


def authorize_generate_agent_knowledge_execution(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    payload: BaseModel,
    identity: ToolCallIdentity,
) -> None:
    _current_agent(db, actor, row)
    if row.agent_version_id != identity.participant_id:
        raise not_found()
    authorize_generate_agent_knowledge(db, actor, row, payload)


def authorize_generate_agent_knowledge_replay(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    _payload: BaseModel,
    identity: ToolCallIdentity,
    saved_result: dict[str, Any],
) -> None:
    agent, version = _current_agent(db, actor, row)
    if row.agent_version_id != identity.participant_id or not isinstance(
        saved_result.get("result"), dict
    ):
        raise not_found()
    tool_result = saved_result["result"]
    run_id = tool_result.get("run_id")
    set_id = tool_result.get("canonical_set_id")
    if not isinstance(run_id, str) or not isinstance(set_id, str):
        raise not_found()
    run = db.get(KnowledgeGenerationRun, run_id)
    set_row = db.get(KnowledgeSet, set_id)
    if (
        run is None
        or set_row is None
        or tool_result.get("job_id") != run.job_id
        or run.owner_user_id != actor.user.id
        or run.agent_id != agent.id
        or run.agent_version_id != version.id
        or run.course_id != agent.course_id
        or run.knowledge_set_id != set_row.id
        or set_row.owner_user_id != actor.user.id
        or set_row.course_id != agent.course_id
        or set_row.ownership_scope != "personal"
        or set_row.group_id is not None
        or db.get(AgentKnowledgeSet, (agent.id, set_row.id)) is None
    ):
        raise not_found()
    try:
        source_manifest = json.loads(run.source_manifest_json)
    except (TypeError, ValueError):
        raise not_found() from None
    selected_ids = [document.id for document in _enabled_documents(db, version.id)]
    if (
        not isinstance(source_manifest, list)
        or [item.get("document_id") for item in source_manifest if isinstance(item, dict)]
        != selected_ids
        or not _current_generation_authorized(db, run)
    ):
        raise not_found()


def generate_agent_knowledge(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    _payload: BaseModel,
    _event_id: str,
    identity: ToolCallIdentity,
) -> dict[str, Any]:
    agent, version = _current_agent(db, actor, row)
    if identity.participant_id != version.id:
        raise not_found()
    documents = _enabled_documents(db, version.id)
    if not documents:
        raise conflict(
            "knowledge_generation_sources_missing",
            "This Agent has no available RAG sources for Knowledge generation.",
        )

    intent = KnowledgeGenerationIntent(
        source_document_ids=[UUID(document.id) for document in documents]
    )
    queued = enqueue_generation_for_publish(db, actor, agent, version, intent)
    set_row = db.get(KnowledgeSet, queued.run.knowledge_set_id)
    if set_row is None or set_row.owner_user_id != actor.user.id:
        raise not_found()
    action_id = _turn_action_id(actor, row, identity, queued.run)
    replay = replay_generation_action_alias_for_run(
        db,
        owner_user_id=actor.user.id,
        action_id=action_id,
        run=queued.run,
    )
    if replay is not None and replay.run.intent_generation != set_row.generation_intent_seq:
        raise conflict(
            "knowledge_generation_intent_stale",
            "A newer Knowledge generation intent replaced this action.",
        )
    run = (
        replay.run
        if replay is not None
        else db.scalar(
            select(KnowledgeGenerationRun)
            .where(
                KnowledgeGenerationRun.knowledge_set_id == queued.run.knowledge_set_id,
                KnowledgeGenerationRun.owner_user_id == actor.user.id,
                KnowledgeGenerationRun.agent_id == agent.id,
                KnowledgeGenerationRun.agent_version_id == version.id,
                KnowledgeGenerationRun.intent_generation == set_row.generation_intent_seq,
                KnowledgeGenerationRun.agent_md_hash == queued.run.agent_md_hash,
                KnowledgeGenerationRun.source_manifest_hash == queued.run.source_manifest_hash,
                KnowledgeGenerationRun.source_manifest_json == queued.run.source_manifest_json,
            )
            .order_by(
                KnowledgeGenerationRun.intent_generation.desc(),
                KnowledgeGenerationRun.created_at.desc(),
            )
            .limit(1)
        )
    )
    if run is None:
        raise conflict(
            "knowledge_generation_action_unavailable",
            "The current Knowledge generation run is unavailable.",
        )

    # Accepted or unknown provider operations are never turned into another
    # dispatch by a later invocation. A fresh explicit tool call can retry
    # known failures or resume a blocked pre-dispatch intent through the
    # existing action-receipt path.
    provider_operation = db.scalar(
        select(ProviderOperation)
        .where(ProviderOperation.scope_id == run.id)
        .order_by(ProviderOperation.created_at.desc(), ProviderOperation.id.desc())
        .limit(1)
    )
    provider_state = provider_operation.state if provider_operation is not None else None
    safe_error_code = provider_operation.safe_error_code if provider_operation is not None else None
    unknown_acceptance = any(
        isinstance(code, str) and "unknown" in code.casefold()
        for code in (run.safe_error_code, safe_error_code)
    )
    if replay is not None:
        result_run = replay.run
    elif unknown_acceptance or provider_state in {"sending", "accepted", "acceptance_unknown"}:
        result_run = run
    elif run.state in {"pending", "running", "completed"}:
        result_run = run
    else:
        retry = enqueue_generation_for_existing_set(
            db,
            set_id=run.knowledge_set_id,
            owner_user_id=actor.user.id,
            action_id=action_id,
            resume_blocked_unconfirmed=True,
            selected_source_document_ids=[document.id for document in documents],
        )
        result_run = retry.run

    db.refresh(set_row)
    if result_run.intent_generation != set_row.generation_intent_seq:
        raise conflict(
            "knowledge_generation_intent_stale",
            "A newer Knowledge generation intent replaced this action.",
        )
    record_generation_action_alias_for_run(
        db,
        owner_user_id=actor.user.id,
        action_id=action_id,
        run=result_run,
    )
    return _tool_result(
        result_run,
        wake_generation=(
            result_run.state == "pending" and not unknown_acceptance and provider_state != "sending"
        ),
    )


def _turn_action_id(
    actor: AuthContext,
    row: Conversation,
    identity: ToolCallIdentity,
    run: KnowledgeGenerationRun,
) -> str:
    exact_payload = json.dumps(
        {
            "actor_user_id": actor.user.id,
            "conversation_id": row.id,
            "turn_id": identity.turn_id,
            "agent_id": run.agent_id,
            "agent_version_id": run.agent_version_id,
            "canonical_set_id": run.knowledge_set_id,
            "agent_md_hash": run.agent_md_hash,
            "source_manifest_hash": run.source_manifest_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return str(uuid5(_TOOL_ACTION_NAMESPACE, exact_payload))


def _tool_result(run: KnowledgeGenerationRun, *, wake_generation: bool = False) -> dict[str, Any]:
    if run.state in {"pending", "running"}:
        status = "generating"
    elif run.state == "completed":
        status = "completed"
    else:
        status = "failed"
    return {
        "canonical_set_id": run.knowledge_set_id,
        "run_id": run.id,
        "job_id": run.job_id,
        "status": status,
        "generation_state": run.state,
        "wake_generation": wake_generation,
        "safe_error_code": run.safe_error_code,
    }


def knowledge_tools() -> dict[str, ToolSpec]:
    return {
        GENERATE_AGENT_KNOWLEDGE_TOOL: ToolSpec(
            GENERATE_AGENT_KNOWLEDGE_TOOL,
            "Teacher",
            "Generate or refresh the canonical Knowledge for this current published Agent from its "
            "currently selected RAG sources. Call only when the teacher asks for this action. "
            "The current Agent, source selection and canonical Set are derived from this chat; "
            "do not provide another Agent, Set or source. Repeated requests reuse an active or "
            "completed run for the same saved inputs.",
            GenerateAgentKnowledgeArguments,
            authorize_generate_agent_knowledge,
            generate_agent_knowledge,
            authorize_execution=authorize_generate_agent_knowledge_execution,
            authorize_replay=authorize_generate_agent_knowledge_replay,
            entry_kinds=frozenset({"agent"}),
        )
    }


__all__ = ["GENERATE_AGENT_KNOWLEDGE_TOOL", "knowledge_tools"]
