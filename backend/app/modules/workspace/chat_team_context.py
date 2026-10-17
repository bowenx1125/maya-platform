"""Build a target's own raw knowledge and frozen Own/Shared Set union."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError, not_found
from app.core.models import Agent, AgentVersion, KnowledgeChunk, KnowledgeSnapshot
from app.modules.agents.markdown import markdown_hash
from app.modules.debates.playback.generation_adapter import SqlSnapshotSearch
from app.modules.knowledge.ports import VectorMatch
from app.modules.knowledge.providers import (
    QueryEmbeddingService,
    SqlAlchemyEmbeddingStageStore,
    SqlAlchemyQueryControlAdapter,
    controlled_query_provider,
    persisted_snapshot_identity,
)
from app.modules.knowledge.providers.query_manifest import ensure_real_query_export_manifest
from app.modules.knowledge_sets.service import (
    _without_question_section,
    runtime_knowledge_projection,
)
from app.providers.control import validate_provider_preflight
from app.providers.control_repository import ProviderRepository
from app.providers.factory import embedding_provider
from app.providers.standing_consent import standing_consent_enabled

from .models import Conversation, ConversationParticipant
from .schemas import ChatSource
from .team_conversation import frozen_team_selection


@dataclass(frozen=True)
class TeamMemberContext:
    agent_md: str
    knowledge_json: str
    sources: tuple[ChatSource, ...]
    content_hash: str


def _team_query_embeddings(
    db: Session,
    row: Conversation,
    participant: ConversationParticipant,
    snapshot: KnowledgeSnapshot,
    message: str,
    *,
    settings: Settings,
    result_id: str,
    turn_id: str,
    claim_token: str,
    selected_binding_ids: set[str],
) -> QueryEmbeddingService:
    """Build one exact, standing-authorized query service for this member result."""
    from app.modules.knowledge.providers.sql_query import SqlQueryRequestV1
    from app.modules.provider_disclosure.team_standing import authorize_team_dispatch
    from app.modules.workspace.chat_team_provider import _current_claim_guard

    identity = persisted_snapshot_identity(snapshot)
    if identity.provider != "dashscope" or settings.embedding_provider != "dashscope":
        raise PlatformError(
            "provider_preflight_blocked", "This Team's real retrieval is unavailable.", 409
        )
    policy_hash = settings.provider_policy_hash_for("embedding")
    repository = ProviderRepository(db)
    policy = repository.get_policy_snapshot(policy_hash or "")
    selected = embedding_provider(settings.chat_settings())
    config = getattr(selected, "config", None)
    if policy is None or getattr(config, "resolved_endpoint", None) != policy.endpoint:
        raise PlatformError("provider_preflight_blocked", "Embedding configuration changed.", 409)
    version = db.get(AgentVersion, participant.agent_version_id)
    agent = db.get(Agent, participant.agent_id)
    if version is None or agent is None or agent.id != version.agent_id:
        raise PlatformError("team_context_changed", "This Team target changed.", 409)
    plan = ensure_real_query_export_manifest(
        db,
        db=db,
        scope_id=f"team-result:{result_id}",
        turn_id=turn_id,
        course_id=row.course_id,
        group_id=agent.group_id,
        agent_version_id=version.id,
        snapshot_id=snapshot.id,
        identity=identity,
        transcript_hash=hashlib.sha256(message.encode("utf-8")).hexdigest(),
        persona_spec_hash=markdown_hash(version.agent_md),
        subqueries=(("context", message),),
        policy=policy,
    )
    authorize_team_dispatch(
        db,
        actor_user_id=row.user_id,
        result_id=result_id,
        manifest=plan.manifest,
        selected_binding_ids=selected_binding_ids,
        claim_token=claim_token,
        operator_consent=standing_consent_enabled(settings),
    )
    # The control adapter's sending fence reads the durable confirmation and
    # binding through a separate connection, so commit them before reserving.
    db.commit()
    confirmation = repository.get_export_confirmation(plan.manifest.manifest_hash)
    if confirmation is None:
        raise PlatformError(
            "provider_confirmation_required", "Team retrieval authorization is unavailable.", 409
        )
    try:
        validate_provider_preflight(
            policy,
            plan.manifest,
            confirmation,
            scope_id=plan.manifest.scope_id,
            provider_operation=plan.manifest.provider_operation,
            model_key=plan.manifest.model_key,
        )
    except Exception:
        raise PlatformError(
            "provider_preflight_blocked", "Team retrieval authorization is stale.", 409
        ) from None
    logical_item_id = f"team:{turn_id}:{participant.id}"
    query_context = SqlQueryRequestV1(
        scope_id=plan.scope_id,
        snapshot_id=snapshot.id,
        identity=identity,
        policy_hash=policy.policy_hash,
        export_manifest_hash=plan.manifest.manifest_hash,
        build_manifest_hash=plan.build_manifest_hash,
        query_hashes=plan.query_hashes,
        logical_item_id=logical_item_id,
        confirmation_revision=confirmation.confirmation_revision,
    )
    guard = _current_claim_guard(
        actor_user_id=row.user_id,
        result_id=result_id,
        claim_token=claim_token,
        selected_binding_ids=selected_binding_ids,
        serialized_request=None,
        current_policy_hash=policy.policy_hash,
        query_context=query_context,
    )
    control = SqlAlchemyQueryControlAdapter(
        db,
        scope_id=plan.scope_id,
        snapshot_id=snapshot.id,
        identity=identity,
        policy_hash=policy.policy_hash,
        export_manifest_hash=plan.manifest.manifest_hash,
        build_manifest_hash=plan.build_manifest_hash,
        query_hashes=plan.query_hashes,
        logical_item_id=logical_item_id,
        confirmation_revision=confirmation.confirmation_revision,
        sending_guard=guard,
        max_requests=2_147_483_647,
        max_total_tokens=9_223_372_036_854_775_807,
        max_cost_cny=1.0e18,
    )
    return QueryEmbeddingService(
        provider=controlled_query_provider(
            selected,
            control=control,
            stage_store=SqlAlchemyEmbeddingStageStore(db),
        ),
        control=control,
        manifest=control,
        budget=control,
        build_manifest_hash=plan.build_manifest_hash,
    )


def _is_question_asset(asset: dict[str, Any]) -> bool:
    content = asset.get("content")
    return isinstance(content, dict) and content.get("kind") == "question"


def _team_runs_assessments(db: Session, row: Conversation) -> bool:
    """Whether this Chat's Team Leader declares an assessment recipe."""

    from app.modules.learning.recipes import declared_recipe
    from app.modules.teams.models import TeamVersionMember

    if row.team_version_id is None:
        return False
    leader = db.scalar(
        select(TeamVersionMember).where(
            TeamVersionMember.team_version_id == row.team_version_id,
            TeamVersionMember.is_leader.is_(True),
        )
    )
    version = db.get(AgentVersion, leader.agent_version_id) if leader is not None else None
    return version is not None and declared_recipe(version.agent_md) is not None


def load_member_context(
    db: Session,
    row: Conversation,
    participant: ConversationParticipant,
    message: str,
    *,
    query_embeddings: QueryEmbeddingService | None = None,
    settings: Settings | None = None,
    result_id: str | None = None,
    turn_id: str | None = None,
    claim_token: str | None = None,
    selected_binding_ids: set[str] | None = None,
) -> TeamMemberContext:
    from .team_runtime import _validate_members

    _validate_members(db, row, [participant])
    version = db.get(AgentVersion, participant.agent_version_id)
    if version is None:
        raise not_found()
    selection = frozen_team_selection(db, row)
    member = next(
        item for item in selection.members if item.binding_id == participant.team_member_id
    )
    set_ids = tuple(
        dict.fromkeys((*member.own_knowledge_set_ids, *selection.shared_knowledge_set_ids))
    )
    knowledge_sets: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    # Bug (2026-10-13): with the question bank in its context, a Leader asked
    # for a formal test wrote the questions out itself, so nothing was saved,
    # and the teacher's rule that practice never shows test items broke. In a
    # Team that runs assessments, the server alone shows its Questions.
    hide_questions = _team_runs_assessments(db, row)
    for set_id in set_ids:
        projection = runtime_knowledge_projection(
            db,
            set_id,
            row.user_id,
            execution_owner_user_id=selection.owner_user_id,
        )
        set_assets = list(projection.assets)
        markdown = projection.canonical_markdown
        if hide_questions:
            set_assets = [asset for asset in set_assets if not _is_question_asset(asset)]
            if markdown is not None:
                markdown = _without_question_section(markdown) or None
        assets.extend(set_assets)
        if markdown is not None or set_assets:
            knowledge_sets.append(
                {
                    "canonical_set_id": set_id,
                    "markdown": markdown,
                    "assets": set_assets,
                }
            )
    sources: tuple[ChatSource, ...] = ()
    if participant.snapshot_id is not None:
        snapshot = db.get(KnowledgeSnapshot, participant.snapshot_id)
        if snapshot is None:
            raise not_found()
        if persisted_snapshot_identity(snapshot).provider != "mock" and query_embeddings is None:
            if (
                settings is None
                or result_id is None
                or turn_id is None
                or claim_token is None
                or selected_binding_ids is None
            ):
                raise PlatformError(
                    "provider_confirmation_required",
                    "The exact Team query authorization is unavailable.",
                    409,
                )
            query_embeddings = _team_query_embeddings(
                db,
                row,
                participant,
                snapshot,
                message,
                settings=settings,
                result_id=result_id,
                turn_id=turn_id,
                claim_token=claim_token,
                selected_binding_ids=selected_binding_ids,
            )
        count = int(
            db.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(KnowledgeChunk.snapshot_id == snapshot.id)
            )
            or 0
        )
        if count:
            # Preserve all authorized evidence; rank within this member's raw
            # Snapshot without importing Debate's fixed six-receipt ceiling.
            matches = SqlSnapshotSearch(db, query_embeddings=query_embeddings).search(
                snapshot.id, message, top_k=count
            )
            sources = tuple(
                ChatSource(
                    chunk_id=UUID(match.chunk_id),
                    filename=match.source_filename,
                    excerpt=match.chunk_text,
                )
                for match in cast(tuple[VectorMatch, ...], matches)
            )
    knowledge_json = json.dumps(
        {
            "raw_evidence": [source.model_dump(mode="json") for source in sources],
            "knowledge_sets": knowledge_sets,
            "knowledge_assets": assets,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return TeamMemberContext(
        agent_md=version.agent_md,
        knowledge_json=knowledge_json,
        sources=sources,
        content_hash=hashlib.sha256(knowledge_json.encode()).hexdigest(),
    )
