"""Agent/version and teacher published projections."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import Any, NoReturn, cast
from unicodedata import normalize
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request, Response
from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError

from app.core.config import Settings, get_settings
from app.core.create_admission import create_admission_slot
from app.core.errors import (
    Error,
    PlatformError,
    conflict,
    invalid_state,
    not_found,
    stale_revision,
    unprocessable,
    validation_failure,
    version_immutable,
)
from app.core.locks import xact_lock
from app.core.models import (
    Agent,
    AgentEditAudit,
    AgentVersion,
    AgentVersionDocument,
    CourseMember,
    DemoAcceptanceRun,
    FileOperation,
    Group,
    IdempotencyRecord,
    KnowledgeDocument,
    SnapshotDocument,
    User,
)
from app.core.prefetch import prefetched
from app.core.read_memo import request_read_memo
from app.core.sqlutil import begin_immediate
from app.core.version_label import agent_version_label
from app.modules.agents.debate_cards import (
    AgentCardRequest,
    AgentCardResponse,
    check_agent_card,
    compile_after_save,
)
from app.modules.agents.persona import (
    raw_agent_md_hash,
)
from app.modules.agents.schemas import (
    AgentCreateRequest,
    AgentDetail,
    AgentPreviewRequest,
    AgentPreviewResponse,
    AgentSummary,
    PublishAgentVersionRequest,
    PublishedAgentAuthor,
    PublishedAgentSummary,
    SaveAvatarRequest,
    TestChatRequest,
    TestChatResponse,
    UpdateAgentDraftRequest,
    UpdateAgentMetadataRequest,
)
from app.modules.agents.schemas import (
    AgentVersion as AgentVersionDTO,
)
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext
from app.modules.avatars import (
    DEFAULT_AVATAR_CONFIG,
    AvatarConfigValidationError,
    validate_avatar_config,
)
from app.modules.debates.cards import CARD_TIMEOUT_SECONDS
from app.modules.demo_baseline.service import (
    reject_baseline_agent_mutation,
    reject_baseline_version_mutation,
)
from app.modules.knowledge.files import content_disposition, frozen_download_filename
from app.modules.knowledge.markdown import (
    MarkdownInputError,
    normalize_markdown,
    validate_markdown_characters,
)
from app.modules.knowledge.multipart import integer_field, parse_upload
from app.modules.knowledge.providers.product_publication import (
    ProductPublicationError,
    ensure_real_embedding_export_manifest,
    prepare_real_snapshot_build,
    require_exact_confirmation,
    run_confirmed_real_embedding_publication,
)
from app.modules.knowledge.services import (
    _enabled_documents,
    _visit_edits_agent,
    abandon_claim,
    agent_detail,
    agent_summary,
    assert_claim_owned,
    can_invoke_version,
    can_read_version,
    claim_idempotency,
    course_member_role,
    create_snapshot,
    finish_idempotency,
    observes_group,
    parse_json_payload_hash,
    prefetch_agent_reads,
    public_agent_editor_role,
    publish_without_snapshot,
    readable_agent,
    readable_version,
    renew_idempotency_lease,
    retrieval_response,
    saga_checkpoint,
    scoped_group_role,
    scoped_student_group_role,
    version_dto,
    version_is_currently_public,
    visible_student_agent,
    visible_student_version,
)
from app.modules.knowledge_sets.generation import (
    enqueue_generation_for_publish,
    generation_receipt,
    validate_generation_intent,
)
from app.modules.org.access import WorkspaceMember
from app.providers.control_repository import ProviderRepository
from app.providers.factory import embedding_provider as select_embedding_provider
from app.providers.standing_consent import apply_standing_provider_consent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agents"])

_AGENT_MD_UPLOAD_BODY = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": ["file", "expected_revision"],
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                    "expected_revision": {"type": "integer", "minimum": 0},
                },
            }
        }
    },
}


def _time() -> datetime:
    return datetime.now(UTC)


def _agent_name_key(name: str) -> str:
    return normalize("NFKC", name).strip().casefold()


def _available_agent_name(
    db: Session,
    name: str,
    *,
    group_id: str | None = None,
    owner_user_id: str | None = None,
    course_id: str | None = None,
    visibility: str | None = None,
    current: Agent | None = None,
    recheck_namespace: bool = False,
) -> str:
    """Return ``name`` or, when it is taken in this namespace, ``name-N``.

    N is one more than the largest suffix already used for this base name
    (minimum 2), so 'Zhu Xi' -> 'Zhu Xi-2' -> 'Zhu Xi-3'. Callers hold the
    namespace lock (``_lock_agent_name_namespace``) so two writers cannot
    resolve the same name.
    """
    # Call under the Agent writer lock so two normalized names cannot both win.
    key = _agent_name_key(name)
    if current is not None and key == _agent_name_key(current.name) and not recheck_namespace:
        return name
    statement = select(Agent.id, Agent.name).where(Agent.deleted_at.is_(None))
    if group_id is not None:
        statement = statement.where(
            Agent.ownership_scope == "group",
            Agent.group_id == group_id,
        )
        if visibility == "public":
            # Shared names occupy their own group-wide namespace. A public
            # editor must never learn whether a private Agent uses this name.
            statement = statement.where(Agent.visibility == "public")
        elif visibility == "private" and owner_user_id is not None:
            # Private names are unique only within the current actor's own
            # private workspace. Public and other owners' private names do
            # not collide with, or reveal, this namespace.
            statement = statement.where(
                Agent.visibility == "private",
                Agent.owner_user_id == owner_user_id,
            )
        else:
            # A private operation without an authenticated owner has no
            # private namespace to query.
            statement = statement.where(Agent.id == "")
    else:
        statement = statement.where(
            Agent.ownership_scope == "personal",
            Agent.owner_user_id == owner_user_id,
            Agent.course_id == course_id,
        )
    taken = {
        _agent_name_key(row.name)
        for row in db.execute(statement)
        if current is None or row.id != current.id
    }
    if key not in taken:
        return name
    base = name.strip()
    match = _SUFFIX_RE.match(base)
    if match and _agent_name_key(match.group(1)) + f"-{match.group(2)}" == key:
        base = match.group(1)
    base_key = _agent_name_key(base)
    highest = 1
    for existing in taken:
        if existing == base_key:
            continue
        found = _SUFFIX_RE.match(existing)
        if found and found.group(1) == base_key:
            highest = max(highest, int(found.group(2)))
    candidate = highest + 1
    while _agent_name_key(f"{base}-{candidate}") in taken:
        candidate += 1
    return f"{base}-{candidate}"


AGENT_NAME_MAX_LENGTH = 120


def _clean_agent_name(name: str) -> str:
    """Trim an Agent name and enforce the shared create/rename limits."""

    cleaned = name.strip()
    if not cleaned:
        raise unprocessable("agent_name_required", "Give the Agent a name.")
    if len(cleaned) > AGENT_NAME_MAX_LENGTH:
        raise unprocessable(
            "agent_name_too_long",
            "Agent names can be at most 120 characters.",
            {"max_length": AGENT_NAME_MAX_LENGTH},
        )
    return cleaned


_SUFFIX_RE = re.compile(r"^(.*\S)-(\d{1,6})$")


def _lock_agent_name_namespace(
    db: Session,
    *,
    group_id: str | None,
    owner_user_id: str | None,
    course_id: str | None,
    visibility: str | None,
) -> None:
    """Serialize name resolution per namespace across backends.

    The plain ``_begin_immediate`` takes no lock, so two creates could both
    see a name as free. A transaction lock on the namespace makes the
    check-then-write atomic; it is released at commit/rollback.
    """

    if group_id is not None:
        scope = (
            f"group:{group_id}:public"
            if visibility == "public"
            else f"group:{group_id}:private:{owner_user_id}"
        )
    else:
        scope = f"personal:{course_id}:{owner_user_id}"
    xact_lock(db, f"agent-name:{scope}")


def _reclaim_abandoned_agent_name(
    db: Session,
    name: str,
    *,
    owner_user_id: str,
    group_id: str | None = None,
    course_id: str | None = None,
    visibility: str | None = None,
) -> None:
    """Free a name held only by the actor's own never-written empty draft.

    Creating an Agent is two requests: create the row, then save AGENT.md.
    When the second step failed and the student left the page, the empty
    Agent kept the name and every retry with that name hit
    ``agent_name_conflict``. Such a row has no Markdown, no files, was never
    published and has no history, so retiring it loses nothing.
    """

    key = _agent_name_key(name)
    statement = select(Agent).where(
        Agent.deleted_at.is_(None),
        Agent.owner_user_id == owner_user_id,
        Agent.current_published_version_id.is_(None),
    )
    if group_id is not None:
        # Stay inside the exact namespace the name check uses, so a private
        # create never touches a public draft and vice versa.
        statement = statement.where(
            Agent.ownership_scope == "group",
            Agent.group_id == group_id,
            Agent.visibility == (visibility or "private"),
        )
    else:
        statement = statement.where(
            Agent.ownership_scope == "personal", Agent.course_id == course_id
        )
    for candidate in db.scalars(statement).all():
        if _agent_name_key(candidate.name) != key:
            continue
        versions = db.scalars(
            select(AgentVersion).where(AgentVersion.agent_id == candidate.id)
        ).all()
        if any(v.state != "draft" or (v.agent_md or "").strip() for v in versions):
            continue
        has_documents = db.scalar(
            select(AgentVersionDocument.document_id)
            .where(AgentVersionDocument.agent_version_id.in_([v.id for v in versions]))
            .limit(1)
        )
        if has_documents is not None or _agent_has_history(db, candidate.id):
            continue
        from app.modules.real_delete import hard_delete_agent

        hard_delete_agent(db, candidate, None)
    db.flush()


def _make_agent_public(db: Session, agent: Agent, *, actor_user_id: str) -> None:
    """Turn a private Agent public in place, as if it were copied to Public.

    Owner decision (2026-11-08): it behaves like an identical public copy
    that replaces the private one. Its RAG files go public with it (the
    owner's private files bound to its draft or published version), its
    Voice and AGENT.md stay, and its name moves to the public namespace
    (``Name-2`` on a clash, as on create). Done then publishes a new public
    version; until then the old private version stays private. Kept in place
    rather than copied, so chats, Teams and Debates that use it carry on.
    """

    _lock_agent_name_namespace(
        db,
        group_id=agent.group_id if agent.ownership_scope == "group" else None,
        owner_user_id=agent.owner_user_id,
        course_id=agent.course_id if agent.ownership_scope != "group" else None,
        visibility="public",
    )
    agent.name = _available_agent_name(
        db,
        agent.name,
        group_id=agent.group_id if agent.ownership_scope == "group" else None,
        owner_user_id=agent.owner_user_id,
        course_id=agent.course_id if agent.ownership_scope != "group" else None,
        visibility="public",
        current=agent,
        # Same name, new namespace: it must be checked against public names.
        recheck_namespace=True,
    )
    agent.visibility = "public"
    version_ids = [
        version_id
        for version_id in (
            db.scalar(
                select(AgentVersion.id).where(
                    AgentVersion.agent_id == agent.id, AgentVersion.state == "draft"
                )
            ),
            agent.current_published_version_id,
        )
        if version_id
    ]
    if not version_ids:
        return
    timestamp = _time()
    documents = db.scalars(
        select(KnowledgeDocument)
        .join(AgentVersionDocument, AgentVersionDocument.document_id == KnowledgeDocument.id)
        .where(
            AgentVersionDocument.agent_version_id.in_(version_ids),
            AgentVersionDocument.enabled.is_(True),
            KnowledgeDocument.owner_user_id == actor_user_id,
            KnowledgeDocument.visibility == "private",
        )
        .with_for_update()
    ).all()
    for document in {document.id: document for document in documents}.values():
        document.visibility = "public"
        document.authorization_epoch += 1
        document.updated_at = timestamp
    db.execute(
        update(AgentVersion)
        .where(AgentVersion.agent_id == agent.id, AgentVersion.state == "draft")
        .values(draft_visibility="public", updated_at=timestamp)
    )


def _summary_with_metadata(
    db: Session,
    agent: Agent,
    *,
    include_draft: bool = True,
    role: str | None = "owner",
    context: AuthContext | None = None,
) -> AgentSummary:
    """Build the shared projection with its authoritative metadata CAS."""

    return agent_summary(db, agent, include_draft=include_draft, role=role, context=context)


def _detail_with_metadata(
    db: Session, agent: Agent, role: str, context: AuthContext
) -> AgentDetail:
    """Return an Agent detail whose mutable metadata is current and explicit."""

    detail = agent_detail(db, agent, role, context=context)
    return detail.model_copy(update={"metadata_revision": agent.metadata_revision})


def _version_sources_are_public(db: Session, version: AgentVersion, agent: Agent) -> bool:
    if not version.knowledge_snapshot_id:
        return True
    rows = db.execute(
        select(SnapshotDocument.source_authorization_epoch, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeDocument.id == SnapshotDocument.document_id)
        .where(SnapshotDocument.snapshot_id == version.knowledge_snapshot_id)
    ).all()
    return all(
        source_epoch == document.authorization_epoch
        and document.visibility == "public"
        and document.workspace_state == "active"
        and document.course_id == agent.course_id
        for source_epoch, document in rows
    )


def _version_dto_for_actor(
    db: Session,
    version: AgentVersion,
    agent: Agent,
    context: AuthContext,
    role: str | None = None,
) -> AgentVersionDTO:
    return version_dto(
        db,
        version,
        agent,
        include_private_sources=agent.owner_user_id == context.user.id or role == "observer",
    )


def _student_delete_scope(db: Session, context: AuthContext, agent_id: str) -> Agent:
    """Creator always; a public Agent also by groupmates and course teachers.

    Anyone else (other group, other course, private Agent) gets a 404 so the
    Agent's existence is not revealed.
    """

    agent = db.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None:
        raise not_found()
    if public_agent_editor_role(db, context, agent) is None:
        # Keep the historical owner path (personal teacher Agents etc.).
        if (
            agent.owner_user_id != context.user.id
            or course_member_role(db, context.user.id, agent.course_id) is None
        ):
            raise not_found()
    return agent


def _touch_last_editor(db: Session, agent_id: str, user_id: str) -> None:
    """Record 「最后编辑」 without bumping any CAS revision."""

    row = db.get(AgentEditAudit, agent_id)
    if row is None:
        row = AgentEditAudit(agent_id=agent_id)
        db.add(row)
    row.last_edited_by_user_id = user_id
    row.last_edited_at = _time()
    db.flush()


def _agent_sources_are_public(db: Session, agent: Agent) -> bool:
    version_id = (
        db.scalar(
            select(AgentVersion.id).where(
                AgentVersion.agent_id == agent.id,
                AgentVersion.state == "draft",
            )
        )
        or agent.current_published_version_id
    )
    if version_id is None:
        return True
    rows = db.execute(
        select(KnowledgeDocument)
        .join(
            AgentVersionDocument,
            AgentVersionDocument.document_id == KnowledgeDocument.id,
        )
        .where(
            AgentVersionDocument.agent_version_id == version_id,
            AgentVersionDocument.enabled.is_(True),
        )
    ).all()
    return all(
        document.visibility == "public"
        and document.course_id == agent.course_id
        and document.workspace_state == "active"
        for (document,) in rows
    )


def _agent_has_history(db: Session, agent_id: str) -> bool:
    """Check every retained Agent history source while the writer lock is held."""

    # A publish claim has to exclude concurrent removal even while its
    # immutable snapshot is being staged on disk.  The guard is a durable,
    # Agent-scoped FileOperation row and is joined to the still-pending publish
    # claim so a failed/abandoned request never becomes permanent history.
    publish_guard = db.scalar(
        select(FileOperation.id)
        .join(IdempotencyRecord, IdempotencyRecord.id == FileOperation.idempotency_record_id)
        .where(
            FileOperation.entity_id == agent_id,
            FileOperation.operation_kind == "agent_publish_guard",
            FileOperation.state.in_(("prepared", "staged", "promoted", "cleanup_required")),
            IdempotencyRecord.operation == "publishAgentVersion",
            IdempotencyRecord.state == "pending",
        )
    )
    return publish_guard is not None


def _agent_in_live_team(db: Session, agent_id: str) -> bool:
    """True when the current version of any live Team lists this Agent."""

    from app.modules.teams.models import Team, TeamVersion, TeamVersionMember

    return (
        db.scalar(
            select(Team.id)
            .join(
                TeamVersion,
                (TeamVersion.team_id == Team.id)
                & (TeamVersion.version_seq == Team.current_version_seq),
            )
            .join(TeamVersionMember, TeamVersionMember.team_version_id == TeamVersion.id)
            .where(Team.deleted_at.is_(None), TeamVersionMember.agent_id == agent_id)
            .limit(1)
        )
        is not None
    )


def _live_team_blockers(db: Session, agent_id: str, actor_user_id: str) -> dict[str, Any]:
    """Which live Teams hold this Agent, as the actor may see them.

    The actor's own Teams are named so the error can open them; anyone else's
    Team is only counted, so a private Team's name never leaks.
    """

    from app.modules.teams.models import Team, TeamVersion, TeamVersionMember

    rows = db.execute(
        select(Team.id, Team.display_name, Team.group_id, Team.owner_user_id)
        .join(
            TeamVersion,
            (TeamVersion.team_id == Team.id)
            & (TeamVersion.version_seq == Team.current_version_seq),
        )
        .join(TeamVersionMember, TeamVersionMember.team_version_id == TeamVersion.id)
        .where(Team.deleted_at.is_(None), TeamVersionMember.agent_id == agent_id)
        .distinct()
        .order_by(Team.display_name)
    ).all()
    own = [
        {"team_id": row.id, "team_name": row.display_name, "group_id": row.group_id}
        for row in rows
        if row.owner_user_id == actor_user_id
    ]
    return {"teams": own, "other_team_count": len(rows) - len(own)}


def _begin_immediate(db: Session, agent_id: str | None = None) -> None:
    """Start the final serialized Agent writer transaction.

    Roll back the scoped authorization reads first. With ``agent_id`` the
    transaction holds that Agent's writer lock until it ends, so publish,
    metadata update and delete of one Agent cannot interleave between their
    final check and their write.
    """

    db.rollback()
    begin_immediate(db, lock_key=f"agent-writer:{agent_id}" if agent_id else None)


def _acquire_publish_guard(
    db: Session,
    context: AuthContext,
    version_id: str,
    expected_revision: int,
    record: IdempotencyRecord,
) -> tuple[AgentVersion, Agent, str]:
    """Re-read a publish target under the Agent's writer lock and fence deletion.

    The idempotency claim is committed before this function is called.  The
    immediate transaction then re-resolves the student-visible version and
    inserts a durable Agent-scoped guard before releasing the lock.  A delete
    that wins the lock first sees a missing version and the publish caller gets
    a stable 404; a publish that wins leaves a guard for the delete's final
    history check.
    """

    db.rollback()
    agent_id = db.scalar(select(AgentVersion.agent_id).where(AgentVersion.id == version_id))
    _begin_immediate(db, str(agent_id) if agent_id is not None else None)
    try:
        scoped = visible_student_version(db, context, version_id)
        if scoped.version.state != "draft":
            raise version_immutable()
        if scoped.agent.status != "active":
            raise invalid_state("Archived Agents cannot be published.")
        if scoped.version.revision != expected_revision:
            raise stale_revision(scoped.version.revision)
        # Keep an explicit CAS fence in the locked transaction as well as the
        # ORM re-read.  This makes the publish winner observable to a delete and
        # prevents a stale worker from installing a guard for another draft.
        fenced = db.execute(
            update(AgentVersion)
            .where(
                AgentVersion.id == scoped.version.id,
                AgentVersion.agent_id == scoped.agent.id,
                AgentVersion.state == "draft",
                AgentVersion.revision == expected_revision,
            )
            .values(revision=AgentVersion.revision)
        )
        if getattr(fenced, "rowcount", 0) != 1:
            current_revision = db.scalar(
                select(AgentVersion.revision).where(AgentVersion.id == scoped.version.id)
            )
            raise stale_revision(current_revision)
        timestamp = _time()
        guard_id = str(uuid4())
        db.add(
            FileOperation(
                id=guard_id,
                idempotency_record_id=record.id,
                operation_kind="agent_publish_guard",
                entity_id=scoped.agent.id,
                request_id=str(uuid4()),
                source_relative_path=None,
                target_relative_path=None,
                expected_sha256=None,
                state="prepared",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        db.flush()
        db.commit()
        return scoped.version, scoped.agent, guard_id
    except PlatformError:
        if db.in_transaction():
            db.rollback()
        raise


def _recover_publish_guard(db: Session, guard_id: str | None) -> None:
    """Release a guard after a failed publish without leaving a writer lock."""

    if guard_id is None:
        return
    db.rollback()
    begin_immediate(db)
    changed = db.execute(
        update(FileOperation)
        .where(FileOperation.id == guard_id, FileOperation.state == "prepared")
        .values(state="recovered", updated_at=_time())
    )
    if getattr(changed, "rowcount", 0) == 1:
        db.commit()
    else:
        db.rollback()


def _raise_embedding_publication_error(
    error: ProductPublicationError,
) -> NoReturn:
    """Expose only stable product-safe real-publication failures."""

    if error.code == "provider_confirmation_missing":
        raise conflict(
            "provider_confirmation_unavailable",
            "The exact provider disclosure confirmation could not be recorded.",
        ) from error
    if error.code == "persona_confirmation_required":
        raise validation_failure(
            "The Persona must be compiled and confirmed before publication.",
            {"publish_blockers": ["persona_confirmation_required"]},
            code="persona_confirmation_required",
        ) from error
    if error.code == "version_immutable":
        raise version_immutable() from error
    if error.code in {
        "manifest_drift",
        "manifest_owner_drift",
        "partial_embedding_recovery_required",
        "provider_confirmation_stale",
        "revision_stale",
        "snapshot_build_drift",
        "acceptance_binding_invalid",
        "acceptance_binding_multibatch",
    }:
        raise conflict(
            error.code,
            (
                "The Demo acceptance binding is invalid; prepare the exact Call1 again."
                if error.code.startswith("acceptance_binding_")
                else (
                    "The real Embedding publication inputs changed; prepare and confirm them again."
                )
            ),
        ) from error
    raise PlatformError(
        "provider_preflight_blocked",
        "Real Embedding is unavailable until every policy and account control is verified.",
        503,
    ) from error


def _publish_real_embedding_snapshot(
    db: Session,
    settings: Settings,
    *,
    version: AgentVersion,
    agent: Agent,
    expected_revision: int,
    record: IdempotencyRecord,
    acceptance_run_id: str | None = None,
    call_no: int | None = None,
) -> None:
    policy_hash = settings.provider_policy_hash_for("embedding")
    if policy_hash is None:
        raise PlatformError(
            "provider_preflight_blocked",
            "Real Embedding is unavailable until every policy and account control is verified.",
            503,
        )
    repository = ProviderRepository(db)
    policy = repository.get_policy_snapshot(policy_hash)
    if policy is None or policy.policy_hash != policy_hash:
        raise PlatformError(
            "provider_preflight_blocked",
            "Real Embedding is unavailable until every policy and account control is verified.",
            503,
        )
    try:
        build = prepare_real_snapshot_build(
            db,
            settings.resolved_data_root,
            course_id=agent.course_id,
            group_id=agent.group_id,
            agent_version_id=version.id,
            expected_revision=expected_revision,
        )
        manifest = ensure_real_embedding_export_manifest(
            db,
            build,
            course_id=agent.course_id,
            group_id=agent.group_id,
            agent_version_id=version.id,
            policy=policy,
        )
        try:
            confirmation = require_exact_confirmation(
                db,
                manifest,
                policy,
                course_id=agent.course_id,
                group_id=agent.group_id,
                agent_version_id=version.id,
            )
        except ProductPublicationError as error:
            if error.code not in {
                "provider_confirmation_missing",
                "provider_confirmation_stale",
            }:
                raise
            standing_confirmed = apply_standing_provider_consent(
                repository,
                manifest,
                policy,
                settings,
            )
            if not standing_confirmed:
                raise
            # Standing consent writes the same immutable confirmation a
            # teacher would submit. Re-run the owner-bound check before any
            # provider call so the operator flag cannot widen the manifest
            # scope.
            try:
                confirmation = require_exact_confirmation(
                    db,
                    manifest,
                    policy,
                    course_id=agent.course_id,
                    group_id=agent.group_id,
                    agent_version_id=version.id,
                )
            except ProductPublicationError:
                raise
        renew_idempotency_lease(db, record, lease_seconds=900)
        selected_provider = select_embedding_provider(settings)
        result = run_confirmed_real_embedding_publication(
            db,
            data_root=settings.resolved_data_root,
            course_id=agent.course_id,
            group_id=agent.group_id,
            agent_version_id=version.id,
            policy=policy,
            manifest=manifest,
            confirmation=confirmation,
            build=build,
            provider=selected_provider,
            expected_revision=expected_revision,
            acceptance_run_id=acceptance_run_id,
            call_no=call_no,
            target_agent_id=agent.id,
            target_version_id=version.id,
            idempotency_record_id=record.id,
            claim_token=record.claim_token,
        )
    except ProductPublicationError as error:
        _raise_embedding_publication_error(error)
    if result.status != "succeeded":
        code = result.safe_error_code or "provider_unavailable"
        if code not in {
            "acceptance_unknown",
            "provider_not_sent",
            "embedding_response_invalid",
            "snapshot_build_drift",
        }:
            code = "provider_unavailable"
        raise PlatformError(code, "The real Embedding publication did not complete.", 503)


@router.get(
    "/groups/{group_id}/agents",
    response_model=list[AgentSummary],
    operation_id="listGroupAgents",
    responses={
        200: {"model": list[AgentSummary], "description": "Group agents and current summary."},
        404: {"model": Error, "description": "Group not found."},
    },
)
def list_group_agents(
    group_id: UUID,
    include_archived: bool = Query(True),
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[AgentSummary]:
    role = scoped_group_role(db, context, str(group_id))
    if role is None:
        raise not_found()
    published_version = exists(
        select(AgentVersion.id).where(
            AgentVersion.id == Agent.current_published_version_id,
            AgentVersion.state == "published",
            AgentVersion.published_visibility == "public",
            AgentVersion.authorization_epoch == Agent.authorization_epoch,
        )
    )
    rows = db.execute(
        select(Agent)
        .join(Group, Group.id == Agent.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .outerjoin(
            WorkspaceMember,
            and_(WorkspaceMember.group_id == Group.id, WorkspaceMember.user_id == context.user.id),
        )
        .where(
            Agent.group_id == str(group_id),
            Agent.ownership_scope == "group",
            Agent.deleted_at.is_(None),
            CourseMember.user_id == context.user.id,
            or_(
                and_(
                    Agent.owner_user_id == context.user.id,
                    WorkspaceMember.user_id.is_not(None),
                ),
                and_(
                    WorkspaceMember.user_id.is_not(None),
                    Agent.visibility == "public",
                ),
                and_(
                    CourseMember.role == "teacher", Agent.visibility == "public", published_version
                ),
            ),
        )
    ).all()
    listed = [agent for (agent,) in rows]
    if observes_group(db, context.user.id, str(group_id)):
        # A teacher looking round the group sees its members' private work
        # too, read-only: the Agents it already lists keep their own role.
        seen = {agent.id for agent in listed}
        listed += [
            agent
            for agent in db.scalars(
                select(Agent)
                .where(
                    Agent.group_id == str(group_id),
                    Agent.ownership_scope == "group",
                    Agent.deleted_at.is_(None),
                    Agent.visibility != "public",
                    Agent.owner_user_id != context.user.id,
                )
                .order_by(Agent.created_at, Agent.id)
            ).all()
            if agent.id not in seen
        ]
    agents = []
    for agent in listed:
        if not include_archived and agent.status != "active":
            continue
        if agent.visibility != "public" and agent.owner_user_id != context.user.id:
            agents.append((agent, "observer"))
            continue
        if agent.owner_user_id == context.user.id and role == "student":
            agents.append((agent, "owner"))
        elif agent.owner_user_id == context.user.id and role == "teacher":
            current_version = db.get(AgentVersion, agent.current_published_version_id)
            if current_version and version_is_currently_public(current_version, agent):
                agents.append((agent, "teacher"))
        elif agent.visibility == "public" and role == "student":
            agents.append((agent, "student"))
        elif agent.visibility == "public" and role == "teacher":
            current_version = db.get(AgentVersion, agent.current_published_version_id)
            if current_version and version_is_currently_public(current_version, agent):
                agents.append((agent, "teacher"))
    return [
        _summary_with_metadata(
            db,
            agent,
            # A teacher sees a draft only when they may edit it (public Agent
            # of their course with no private provenance); see agent_summary.
            include_draft=True,
            role=agent_role,
            context=context,
        )
        for agent, agent_role in agents
    ]


@router.post(
    "/groups/{group_id}/agents",
    response_model=AgentDetail,
    status_code=201,
    operation_id="createAgent",
    responses={
        201: {"model": AgentDetail, "description": "Agent and V1.0 draft created."},
        409: {"model": Error, "description": "An Agent with this name already exists."},
        404: {"model": Error, "description": "Group not found."},
    },
)
def create_agent(
    group_id: UUID,
    payload: AgentCreateRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> AgentDetail:
    if payload.avatar_config is not None:
        try:
            validate_avatar_config(payload.avatar_config)
        except AvatarConfigValidationError as exc:
            raise validation_failure(exc.message, exc.details, code=exc.code) from exc
    payload = payload.model_copy(update={"name": _clean_agent_name(payload.name)})
    # The sign-in check above opened a read transaction; end it so a
    # request queued for admission holds no pooled connection while it waits.
    db.commit()
    with create_admission_slot():
        scoped_student_group_role(db, context, str(group_id))
        body_hash = parse_json_payload_hash(
            "createAgent", context, [str(group_id)], payload.model_dump()
        )
        record, replay = claim_idempotency(db, context, "createAgent", idempotency_key, body_hash)
        if replay is not None:
            return replay  # type: ignore[return-value]
        _begin_immediate(db)
        try:
            scoped_student_group_role(db, context, str(group_id))
            assert_claim_owned(db, record)
            _lock_agent_name_namespace(
                db,
                group_id=str(group_id),
                owner_user_id=context.user.id,
                course_id=None,
                visibility=payload.visibility,
            )
            _reclaim_abandoned_agent_name(
                db,
                payload.name,
                owner_user_id=context.user.id,
                group_id=str(group_id),
                visibility=payload.visibility,
            )
            resolved_name = _available_agent_name(
                db,
                payload.name,
                group_id=str(group_id),
                owner_user_id=context.user.id,
                visibility=payload.visibility,
            )
        except PlatformError:
            abandon_claim(db, record)
            raise
        timestamp = _time()
        group = db.get(Group, str(group_id))
        if group is None:
            abandon_claim(db, record)
            raise not_found()
        agent = Agent(
            id=str(uuid4()),
            group_id=str(group_id),
            owner_user_id=context.user.id,
            course_id=group.course_id,
            ownership_scope="group",
            visibility=payload.visibility,
            authorization_epoch=0,
            name=resolved_name,
            description=(
                payload.description if payload.description and payload.description.strip() else ""
            ),
            metadata_revision=0,
            status="active",
            created_at=timestamp,
            updated_at=timestamp,
        )
        version = AgentVersion(
            id=str(uuid4()),
            agent_id=agent.id,
            version_seq=0,
            state="draft",
            revision=0,
            agent_md="",
            raw_agent_md_hash=raw_agent_md_hash(""),
            # Ordinary Agents author free-text AGENT.md; strict Persona compile
            # stays for Demo baseline and explicit legacy paths only.
            persona_required=False,
            avatar_config_json=validate_avatar_config(
                payload.avatar_config or DEFAULT_AVATAR_CONFIG
            ).model_dump_json(),
            authorization_epoch=agent.authorization_epoch,
            draft_visibility=payload.visibility,
            published_visibility=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add_all([agent, version])
        db.flush()
        result = _detail_with_metadata(db, agent, "owner", context)
        finish_idempotency(db, record, 201, result.model_dump(mode="json"))
        saga_checkpoint("create_agent.before_final_commit")
        db.commit()
        saga_checkpoint("create_agent.after_final_commit")
        return result


@router.get(
    "/courses/{course_id}/workspace-agents",
    response_model=list[AgentSummary],
    operation_id="listCourseWorkspaceAgents",
    responses={404: {"model": Error, "description": "Course not found."}},
)
def list_course_workspace_agents(
    course_id: UUID,
    include_archived: bool = Query(True),
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[AgentSummary]:
    if course_member_role(db, context.user.id, str(course_id)) != "teacher":
        raise not_found()
    rows = db.scalars(
        select(Agent)
        .where(
            Agent.course_id == str(course_id),
            Agent.owner_user_id == context.user.id,
            Agent.ownership_scope == "personal",
            Agent.deleted_at.is_(None),
        )
        .order_by(Agent.created_at, Agent.id)
    ).all()
    return [
        _summary_with_metadata(db, agent, include_draft=True, context=context)
        for agent in rows
        if include_archived or agent.status == "active"
    ]


@router.post(
    "/courses/{course_id}/workspace-agents",
    response_model=AgentDetail,
    status_code=201,
    operation_id="createCourseWorkspaceAgent",
    responses={
        201: {"model": AgentDetail, "description": "Private personal Agent draft created."},
        404: {"model": Error, "description": "Course not found."},
        409: {"model": Error, "description": "Name or idempotency conflict."},
    },
)
def create_course_workspace_agent(
    course_id: UUID,
    payload: AgentCreateRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> AgentDetail:
    if payload.avatar_config is not None:
        try:
            validate_avatar_config(payload.avatar_config)
        except AvatarConfigValidationError as exc:
            raise validation_failure(exc.message, exc.details, code=exc.code) from exc
    payload = payload.model_copy(update={"name": _clean_agent_name(payload.name)})
    # The sign-in check above opened a read transaction; end it so a
    # request queued for admission holds no pooled connection while it waits.
    db.commit()
    with create_admission_slot():
        course_key = str(course_id)
        if course_member_role(db, context.user.id, course_key) != "teacher":
            raise not_found()
        body_hash = parse_json_payload_hash(
            "createCourseWorkspaceAgent", context, [course_key, "personal"], payload.model_dump()
        )
        record, replay = claim_idempotency(
            db, context, "createCourseWorkspaceAgent", idempotency_key, body_hash
        )
        if replay is not None:
            return replay  # type: ignore[return-value]
        _begin_immediate(db)
        try:
            if course_member_role(db, context.user.id, course_key) != "teacher":
                raise not_found()
            assert_claim_owned(db, record)
            _lock_agent_name_namespace(
                db,
                group_id=None,
                owner_user_id=context.user.id,
                course_id=course_key,
                visibility=payload.visibility,
            )
            _reclaim_abandoned_agent_name(
                db, payload.name, owner_user_id=context.user.id, course_id=course_key
            )
            resolved_name = _available_agent_name(
                db,
                payload.name,
                owner_user_id=context.user.id,
                course_id=course_key,
                visibility=payload.visibility,
            )
        except PlatformError:
            abandon_claim(db, record)
            raise
        timestamp = _time()
        agent = Agent(
            id=str(uuid4()),
            group_id=None,
            owner_user_id=context.user.id,
            course_id=course_key,
            ownership_scope="personal",
            visibility=payload.visibility,
            authorization_epoch=0,
            name=resolved_name,
            description=(
                payload.description if payload.description and payload.description.strip() else ""
            ),
            metadata_revision=0,
            status="active",
            created_at=timestamp,
            updated_at=timestamp,
        )
        version = AgentVersion(
            id=str(uuid4()),
            agent_id=agent.id,
            version_seq=0,
            state="draft",
            revision=0,
            agent_md="",
            raw_agent_md_hash=raw_agent_md_hash(""),
            # Ordinary Agents author free-text AGENT.md; strict Persona compile
            # stays for Demo baseline and explicit legacy paths only.
            persona_required=False,
            avatar_config_json=validate_avatar_config(
                payload.avatar_config or DEFAULT_AVATAR_CONFIG
            ).model_dump_json(),
            authorization_epoch=agent.authorization_epoch,
            draft_visibility="private",
            published_visibility=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add_all([agent, version])
        db.flush()
        result = _detail_with_metadata(db, agent, "owner", context)
        finish_idempotency(db, record, 201, result.model_dump(mode="json"))
        saga_checkpoint("create_course_workspace_agent.before_final_commit")
        db.commit()
        saga_checkpoint("create_course_workspace_agent.after_final_commit")
        return result


@router.get(
    "/agents/{agent_id}",
    response_model=AgentDetail,
    operation_id="getAgent",
    responses={
        200: {"model": AgentDetail, "description": "Agent projection."},
        404: {"model": Error, "description": "Agent not found."},
    },
)
def get_agent(
    agent_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> AgentDetail:
    with request_read_memo():
        scoped = readable_agent(db, context, str(agent_id))
        versions = db.scalars(
            select(AgentVersion).where(AgentVersion.agent_id == scoped.agent.id)
        ).all()
        prefetch_agent_reads(
            db, [(scoped.agent, version) for version in versions], viewer_id=context.user.id
        )
        return _detail_with_metadata(db, scoped.agent, scoped.role, context)


@router.patch(
    "/agents/{agent_id}",
    response_model=AgentDetail,
    operation_id="updateAgentMetadata",
    responses={
        200: {"model": AgentDetail, "description": "Mutable Agent metadata updated."},
        404: {"model": Error, "description": "Agent not found."},
        409: {"model": Error, "description": "Metadata revision conflict."},
        422: {
            "model": Error,
            "description": "agent_name_required or agent_name_too_long (max 120 characters).",
        },
    },
)
def update_agent_metadata(
    agent_id: UUID,
    payload: UpdateAgentMetadataRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> AgentDetail:
    """CAS-update name and/or description without touching versioned Agent data.

    ``name`` (optional) is trimmed and resolved in the Agent's name namespace
    exactly like create (a taken name becomes ``Name-2``; the Agent's own name
    is a no-op). The response carries the resolved name. No version is
    published, so versions and Debate snapshots keep their stored names.
    ``description`` changes only when it is sent.
    """

    reject_baseline_agent_mutation(str(agent_id))
    new_name = _clean_agent_name(payload.name) if payload.name is not None else None
    # A visibility field uses the same read as every other metadata edit.
    # It must not admit a caller who cannot see the Agent, or carry a name
    # or description change onto someone else's private Agent.
    scoped = visible_student_agent(db, context, str(agent_id))
    # Close the authorization read snapshot before taking the final writer
    # lock, so concurrent updates resolve to one deterministic winner.
    _begin_immediate(db, str(agent_id))
    try:
        current = db.scalar(
            select(Agent).where(
                Agent.id == str(agent_id),
                Agent.course_id == scoped.agent.course_id,
                Agent.group_id == scoped.agent.group_id,
                Agent.metadata_revision == payload.expected_metadata_revision,
            )
        )
        if current is None:
            latest = db.scalar(select(Agent.metadata_revision).where(Agent.id == str(agent_id)))
            db.rollback()
            if latest is None:
                raise not_found()
            raise conflict(
                "stale_metadata_revision",
                "The Agent description changed elsewhere.",
                {
                    "current_metadata_revision": latest,
                },
            )
        # Private can become Public for the owner only. A visibility field
        # from anyone else stops the whole update, including an unchanged
        # value sent beside a name or description. Public is final.
        # Only the owner publishes, so the private RAG that goes public with
        # the Agent is the creator's.
        if "visibility" in payload.model_fields_set and current.owner_user_id != context.user.id:
            raise not_found()
        if payload.visibility is not None and payload.visibility != current.visibility:
            if current.visibility == "public":
                db.rollback()
                raise conflict(
                    "agent_public_is_final",
                    "A public Agent stays public.",
                )
            _make_agent_public(db, current, actor_user_id=context.user.id)
        if new_name is not None:
            _lock_agent_name_namespace(
                db,
                group_id=current.group_id if current.ownership_scope == "group" else None,
                owner_user_id=current.owner_user_id,
                course_id=current.course_id if current.ownership_scope != "group" else None,
                visibility=current.visibility,
            )
            current.name = _available_agent_name(
                db,
                new_name,
                group_id=current.group_id if current.ownership_scope == "group" else None,
                owner_user_id=current.owner_user_id,
                course_id=current.course_id if current.ownership_scope != "group" else None,
                visibility=current.visibility,
                current=current,
            )
        if "description" in payload.model_fields_set:
            description = payload.description
            current.description = description if description and description.strip() else ""
        current.metadata_revision += 1
        current.updated_at = _time()
        _touch_last_editor(db, current.id, context.user.id)
        db.flush()
        result = _detail_with_metadata(
            db,
            current,
            "owner" if current.owner_user_id == context.user.id else "student",
            context,
        )
        db.commit()
        return result
    except PlatformError:
        # A stale CAS has already rolled back above.  This branch releases the
        # immediate lock for any other domain error before FastAPI serializes
        # the stable platform envelope.
        if db.in_transaction():
            db.rollback()
        raise


@router.delete(
    "/agents/{agent_id}",
    status_code=204,
    operation_id="deleteAgent",
    responses={
        204: {"description": "Shared Agent removed; existing chats retained read-only."},
        403: {"model": Error, "description": "CSRF failure or group workspace access required."},
        404: {"model": Error, "description": "Agent not found."},
        409: {"model": Error, "description": "Agent history is retained."},
    },
)
def delete_agent(
    agent_id: UUID,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Remove a shared Agent unless a publish is in flight.

    Debates keep their own copy, so a Debate does not block this. Chats stay
    readable under the snapshotted name and cannot continue.

    The final eligibility query and delete run in one transaction holding the
    Agent's advisory writer lock, which serializes them with publish and
    metadata updates of the same Agent, leaving exactly one committed winner.
    """

    # Keep the reserved-ID check before claiming idempotency or touching any
    # Agent-owned state. The identifier is already a public Demo projection.
    reject_baseline_agent_mutation(str(agent_id))
    body_hash = parse_json_payload_hash("deleteAgent", context, [str(agent_id)], {})
    record, replay = claim_idempotency(db, context, "deleteAgent", idempotency_key, body_hash)
    if replay is not None:
        return Response(status_code=204)
    assert_claim_owned(db, record)

    try:
        # Resolve authorization after the durable claim so an idempotent
        # replay can succeed even though the Agent row was already removed.
        # A denied first request abandons the claim below without revealing
        # anything about another group.
        _student_delete_scope(db, context, str(agent_id))
        _begin_immediate(db, str(agent_id))
        # Re-resolve both the actor scope and the Agent under the writer lock;
        # no publish/Debate writer can slip between this read and the delete.
        agent = _student_delete_scope(db, context, str(agent_id))
        if _agent_has_history(db, agent.id):
            db.rollback()
            abandon_claim(db, record)
            raise conflict(
                "agent_history_retained",
                "This Agent is being published and cannot be deleted.",
            )

        if _agent_in_live_team(db, agent.id):
            db.rollback()
            abandon_claim(db, record)
            raise conflict(
                "agent_in_team",
                "已被放进 Team，请先修改 Team。",
                _live_team_blockers(db, agent.id, context.user.id),
            )

        from app.modules.real_delete import hard_delete_agent

        hard_delete_agent(db, agent, settings.resolved_data_root)
        finish_idempotency(db, record, 204, {})
        saga_checkpoint("delete_agent.before_final_commit")
        db.commit()
        saga_checkpoint("delete_agent.after_final_commit")
        return Response(status_code=204)
    except PlatformError:
        if db.in_transaction():
            db.rollback()
        # A failed final check must not leave a pending idempotency lease that
        # blocks a later explicit request.  ``abandon_claim`` is idempotent.
        abandon_claim(db, record)
        raise


@router.get(
    "/agents/{agent_id}/versions",
    response_model=list[AgentVersionDTO],
    operation_id="listAgentVersions",
    responses={
        200: {"model": list[AgentVersionDTO], "description": "Visible version history."},
        404: {"model": Error, "description": "Agent not found."},
    },
)
def list_agent_versions(
    agent_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[AgentVersionDTO]:
    with request_read_memo():
        scoped = readable_agent(db, context, str(agent_id))
        query = select(AgentVersion).where(AgentVersion.agent_id == scoped.agent.id)
        if scoped.role == "teacher":
            query = query.where(AgentVersion.state.in_(("published", "superseded")))
        versions = list(db.scalars(query.order_by(AgentVersion.version_seq)).all())
        prefetch_agent_reads(
            db, [(scoped.agent, version) for version in versions], viewer_id=context.user.id
        )
        versions = [
            version
            for version in versions
            if can_read_version(db, version, scoped.agent, scoped.role, context=context)
        ]
        if scoped.role == "teacher" and not versions:
            raise not_found()
        return [
            _version_dto_for_actor(db, version, scoped.agent, context, scoped.role)
            for version in versions
        ]


@router.post(
    "/agents/{agent_id}/versions",
    response_model=AgentVersionDTO,
    status_code=201,
    operation_id="createNextAgentVersion",
    responses={
        201: {"model": AgentVersionDTO, "description": "Current published version cloned."},
        404: {"model": Error, "description": "Agent not found."},
        409: {
            "model": Error,
            "description": (
                "Version creation conflict, including stale_base_version when "
                "another editor already published a newer version."
            ),
        },
    },
)
def create_next_agent_version(
    agent_id: UUID,
    expected_base_version_id: UUID | None = Query(
        None,
        description=(
            "Published version the editor started from. When another editor has "
            "published since, the request is rejected with 409 stale_base_version."
        ),
    ),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> AgentVersionDTO:
    reject_baseline_agent_mutation(str(agent_id))
    scoped = visible_student_agent(db, context, str(agent_id))
    body_hash = parse_json_payload_hash(
        "createNextAgentVersion",
        context,
        [str(agent_id)],
        (
            {"expected_base_version_id": str(expected_base_version_id)}
            if expected_base_version_id is not None
            else {}
        ),
    )
    record, replay = claim_idempotency(
        db, context, "createNextAgentVersion", idempotency_key, body_hash
    )
    if replay is not None:
        return replay  # type: ignore[return-value]
    _begin_immediate(db, str(agent_id))
    scoped = visible_student_agent(db, context, str(agent_id))
    assert_claim_owned(db, record)
    if scoped.agent.status != "active" or not scoped.agent.current_published_version_id:
        abandon_claim(db, record)
        raise invalid_state(
            "An active published version is required before creating the next draft."
        )
    current = db.scalar(
        select(AgentVersion)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(
            AgentVersion.id == scoped.agent.current_published_version_id,
            AgentVersion.agent_id == scoped.agent.id,
        )
    )
    if current is None or current.state != "published":
        abandon_claim(db, record)
        raise invalid_state("The current published version is unavailable.")
    if expected_base_version_id is not None and str(expected_base_version_id) != current.id:
        # Two editors opened the same published version; the first Done
        # published a newer one.  The second must not silently overwrite it.
        abandon_claim(db, record)
        raise conflict(
            "stale_base_version",
            "Someone else published a newer version of this Agent.",
            {
                "expected_base_version_id": str(expected_base_version_id),
                "current_published_version_id": current.id,
                "current_version_label": agent_version_label(current.version_seq),
            },
        )
    # A private published Agent is the creator's, unless the caller is inside
    # that group on a live teacher visit. The visit may open the next draft
    # only when the Agent still has a publishing account.
    visiting = _visit_edits_agent(db, context, scoped.agent)
    if (
        scoped.agent.owner_user_id != context.user.id
        and not version_is_currently_public(current, scoped.agent)
        and not visiting
    ):
        abandon_claim(db, record)
        raise not_found()
    existing = db.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == scoped.agent.id,
            AgentVersion.state == "draft",
        )
    )
    if existing is not None:
        abandon_claim(db, record)
        raise invalid_state("An Agent can have only one draft version.")
    timestamp = _time()
    version = AgentVersion(
        id=str(uuid4()),
        agent_id=scoped.agent.id,
        version_seq=current.version_seq + 1,
        state="draft",
        revision=0,
        agent_md=current.agent_md,
        raw_agent_md_hash=raw_agent_md_hash(current.agent_md),
        persona_spec_json=None,
        persona_spec_hash=None,
        persona_compiler_version=None,
        persona_diagnostics_json=None,
        persona_confirmation_revision=None,
        student_confirmed_at=None,
        persona_confirming_user_id=None,
        # Keep the published marker: Demo baseline stays Persona-gated;
        # ordinary free-text Agents stay free-text.
        persona_required=bool(current.persona_required),
        avatar_config_json=current.avatar_config_json,
        voice_profile_id=current.voice_profile_id,
        knowledge_snapshot_id=None,
        authorization_epoch=scoped.agent.authorization_epoch,
        draft_visibility=(
            "public"
            if version_is_currently_public(current, scoped.agent)
            and _version_sources_are_public(db, current, scoped.agent)
            else "private"
        ),
        published_visibility=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(version)
    db.flush()
    for relation in db.scalars(
        select(AgentVersionDocument)
        .where(AgentVersionDocument.agent_version_id == current.id)
        .order_by(AgentVersionDocument.order_index)
    ).all():
        db.add(
            AgentVersionDocument(
                agent_version_id=version.id,
                document_id=relation.document_id,
                enabled=relation.enabled,
                order_index=relation.order_index,
            )
        )
    db.flush()
    result = _version_dto_for_actor(db, version, scoped.agent, context)
    finish_idempotency(db, record, 201, result.model_dump(mode="json"))
    saga_checkpoint("create_next_agent_version.before_final_commit")
    db.commit()
    saga_checkpoint("create_next_agent_version.after_final_commit")
    return result


@router.put(
    "/agent-versions/{version_id}/avatar",
    response_model=AgentVersionDTO,
    operation_id="saveAgentAvatar",
    responses={
        200: {"model": AgentVersionDTO, "description": "Avatar saved immediately."},
        404: {"model": Error, "description": "Version not found."},
        409: {"model": Error, "description": "Revision or base conflict."},
        422: {"model": Error, "description": "Invalid avatar."},
    },
)
def save_agent_avatar(
    version_id: UUID,
    payload: SaveAvatarRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> AgentVersionDTO:
    from app.modules.agents.avatar_save import save_avatar

    reject_baseline_version_mutation(str(version_id))
    scoped = visible_student_version(db, context, str(version_id))
    agent_id = scoped.agent.id
    body_hash = parse_json_payload_hash(
        "saveAgentAvatar", context, [str(version_id)], payload.model_dump(mode="json")
    )
    record, replay = claim_idempotency(db, context, "saveAgentAvatar", idempotency_key, body_hash)
    if replay is not None:
        return replay  # type: ignore[return-value]
    _begin_immediate(db, agent_id)
    try:
        assert_claim_owned(db, record)
        scoped = visible_student_version(db, context, str(version_id))
        db.refresh(scoped.version, with_for_update=True)
        version = save_avatar(db, scoped.agent, scoped.version, payload)
        _touch_last_editor(db, agent_id, context.user.id)
        db.flush()
        result = _version_dto_for_actor(db, version, scoped.agent, context)
        finish_idempotency(db, record, 200, result.model_dump(mode="json"))
        db.commit()
        return result
    except PlatformError:
        db.rollback()
        abandon_claim(db, record)
        raise


@router.post(
    "/agent-versions/{version_id}/debate-card",
    response_model=AgentCardResponse,
    operation_id="checkAgentDebateCard",
    responses={
        200: {
            "model": AgentCardResponse,
            "description": (
                "Stored card with bounded compilation for changed, failed or abandoned cards."
            ),
        },
        404: {"model": Error, "description": "Version not found."},
    },
)
async def check_agent_debate_card(
    version_id: UUID,
    payload: AgentCardRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AgentCardResponse:
    scoped = readable_version(db, context, str(version_id))
    if payload.agent_md is not None and payload.agent_md != scoped.version.agent_md:
        visible_student_version(db, context, str(version_id))
    agent_id = scoped.agent.id
    source = payload.agent_md if payload.agent_md is not None else scoped.version.agent_md
    db.commit()
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                check_agent_card, db.get_bind().engine, agent_id, str(version_id), source, settings
            ),
            timeout=CARD_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        # The independent worker retains the claim and ledger; cancellation
        # must never cause a resend or close its database session mid-call.
        return AgentCardResponse(card_status="compiling")


@router.get(
    "/agent-versions/{version_id}",
    response_model=AgentVersionDTO,
    operation_id="getAgentVersion",
    responses={
        200: {"model": AgentVersionDTO, "description": "Visible version projection."},
        404: {"model": Error, "description": "Version not found."},
    },
)
def get_agent_version(
    version_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> AgentVersionDTO:
    scoped = readable_version(db, context, str(version_id))
    return _version_dto_for_actor(db, scoped.version, scoped.agent, context, scoped.role)


@router.patch(
    "/agent-versions/{version_id}",
    response_model=AgentVersionDTO,
    operation_id="updateAgentDraft",
    responses={
        200: {"model": AgentVersionDTO, "description": "Draft saved with incremented revision."},
        404: {"model": Error, "description": "Version not found."},
        409: {"model": Error, "description": "Revision or immutability conflict."},
        422: {"model": Error, "description": "Invalid draft payload."},
    },
)
def update_agent_draft(
    version_id: UUID,
    payload: UpdateAgentDraftRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    background_tasks: BackgroundTasks = cast(BackgroundTasks, None),
) -> AgentVersionDTO:
    reject_baseline_version_mutation(str(version_id))
    visible_student_version(db, context, str(version_id))
    _begin_immediate(db)
    scoped = visible_student_version(db, context, str(version_id))
    if scoped.version.state != "draft":
        raise version_immutable()
    if scoped.version.revision != payload.expected_revision:
        raise stale_revision(scoped.version.revision)
    values: dict[str, object] = {
        "revision": AgentVersion.revision + 1,
        "updated_at": _time(),
        # Any intervening draft edit makes a prior student confirmation stale,
        # even when the edit only changes avatar/voice metadata.
        "persona_confirmation_revision": None,
        "student_confirmed_at": None,
        "persona_confirming_user_id": None,
    }
    raw_changed = False
    if "agent_md" in payload.model_fields_set:
        normalized_agent_md = payload.agent_md.replace("\r\n", "\n").replace("\r", "\n")
        try:
            validate_markdown_characters(normalized_agent_md)
        except MarkdownInputError as exc:
            raise validation_failure(
                "The AGENT.md text is not valid.",
                {"reason": str(exc)},
                code="file_operation_failed",
            ) from None
        raw_changed = normalized_agent_md != scoped.version.agent_md
        values["agent_md"] = normalized_agent_md
        values["raw_agent_md_hash"] = raw_agent_md_hash(normalized_agent_md)
        if raw_changed:
            # A changed raw source cannot keep an old structured extraction or
            # its diagnostics as active state.
            values.update(
                {
                    "persona_spec_json": None,
                    "persona_spec_hash": None,
                    "persona_compiler_version": None,
                    "persona_diagnostics_json": None,
                }
            )
    if scoped.agent.visibility != "public":
        values["draft_visibility"] = "private"
    if payload.avatar_config is not None:
        try:
            avatar = validate_avatar_config(payload.avatar_config)
        except AvatarConfigValidationError as exc:
            raise validation_failure(exc.message, exc.details, code=exc.code) from exc
        values["avatar_config_json"] = avatar.model_dump_json()
    if "voice_profile_id" in payload.model_fields_set:
        # Preserve the frozen absent/null/UUID tri-state: absent leaves the
        # binding untouched, explicit null clears it, UUID binds a ready voice
        # in the same group.  Import lazily to avoid coupling the core Agent
        # router to provider construction during module initialization.
        from app.modules.voices.service import validate_voice_binding

        requested_voice = str(payload.voice_profile_id) if payload.voice_profile_id else None
        # Re-saving the voice already on the draft is not a new binding: a
        # groupmate or teacher editing a shared public Agent keeps the
        # creator's voice without needing access to bind it themselves.
        if requested_voice != scoped.version.voice_profile_id:
            validate_voice_binding(db, context, scoped.version, requested_voice, settings)
        values["voice_profile_id"] = requested_voice
    changed = db.execute(
        update(AgentVersion)
        .where(
            AgentVersion.id == scoped.version.id,
            AgentVersion.state == "draft",
            AgentVersion.revision == payload.expected_revision,
        )
        .values(**values)
    )
    if getattr(changed, "rowcount", 0) != 1:
        current_revision = db.scalar(
            select(AgentVersion.revision).where(AgentVersion.id == scoped.version.id)
        )
        raise stale_revision(current_revision)
    _touch_last_editor(db, scoped.agent.id, context.user.id)
    db.refresh(scoped.version)
    db.flush()
    result = _version_dto_for_actor(db, scoped.version, scoped.agent, context)
    agent_id = scoped.agent.id
    db.commit()
    if background_tasks is not None:
        background_tasks.add_task(compile_after_save, db.get_bind(), agent_id, settings)
    return result


@router.post(
    "/agent-versions/{version_id}/agent-md/upload",
    response_model=AgentVersionDTO,
    operation_id="uploadAgentMd",
    openapi_extra={"requestBody": _AGENT_MD_UPLOAD_BODY},
    responses={
        200: {"model": AgentVersionDTO, "description": "AGENT.md replaced on the draft."},
        404: {"model": Error, "description": "Version not found."},
        409: {"model": Error, "description": "Revision or immutability conflict."},
        422: {"model": Error, "description": "Invalid Markdown upload."},
    },
)
async def upload_agent_md(
    version_id: UUID,
    request: Request,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    background_tasks: BackgroundTasks = cast(BackgroundTasks, None),
) -> AgentVersionDTO:
    reject_baseline_version_mutation(str(version_id))
    scoped = visible_student_version(db, context, str(version_id))
    if scoped.version.state != "draft":
        raise version_immutable()
    try:
        fields, filename, content = await parse_upload(request)
        expected_revision = integer_field(fields, "expected_revision", required=True)
        document = normalize_markdown(filename, content)
    except (ValueError, MarkdownInputError, UnicodeDecodeError) as exc:
        raise validation_failure(
            "The AGENT.md upload is not valid.", code="file_operation_failed"
        ) from exc
    assert expected_revision is not None
    _begin_immediate(db)
    scoped = visible_student_version(db, context, str(version_id))
    if scoped.version.state != "draft":
        raise version_immutable()
    if scoped.version.revision != expected_revision:
        raise stale_revision(scoped.version.revision)
    changed = db.execute(
        update(AgentVersion)
        .where(
            AgentVersion.id == scoped.version.id,
            AgentVersion.state == "draft",
            AgentVersion.revision == expected_revision,
        )
        .values(
            agent_md=document.normalized,
            raw_agent_md_hash=raw_agent_md_hash(document.normalized),
            persona_spec_json=None,
            persona_spec_hash=None,
            persona_compiler_version=None,
            persona_diagnostics_json=None,
            persona_confirmation_revision=None,
            student_confirmed_at=None,
            persona_confirming_user_id=None,
            **({"draft_visibility": "private"} if scoped.agent.visibility != "public" else {}),
            revision=AgentVersion.revision + 1,
            updated_at=_time(),
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        current_revision = db.scalar(
            select(AgentVersion.revision).where(AgentVersion.id == scoped.version.id)
        )
        raise stale_revision(current_revision)
    _touch_last_editor(db, scoped.agent.id, context.user.id)
    db.refresh(scoped.version)
    db.flush()
    result = _version_dto_for_actor(db, scoped.version, scoped.agent, context)
    agent_id = scoped.agent.id
    db.commit()
    if background_tasks is not None:
        background_tasks.add_task(compile_after_save, db.get_bind(), agent_id, settings)
    return result


@router.get(
    "/agent-versions/{version_id}/agent-md/download",
    response_class=Response,
    operation_id="downloadAgentMd",
    responses={
        200: {
            "description": "Published immutable AGENT.md.",
            "content": {"text/markdown": {"schema": {"type": "string"}}},
        },
        404: {"model": Error, "description": "Published Agent version not found."},
    },
)
def download_agent_md(
    version_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> Response:
    """Download AGENT.md only from a published/superseded visible version."""

    scoped = readable_version(db, context, str(version_id))
    if scoped.version.state not in {"published", "superseded"}:
        raise not_found()
    filename = frozen_download_filename(
        "AGENT.md",
        scoped.agent.name,
        agent_version_label(scoped.version.version_seq),
    )
    return Response(
        scoped.version.agent_md.encode("utf-8"),
        media_type="text/markdown",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.post(
    "/agent-versions/{version_id}/publish",
    response_model=AgentVersionDTO,
    operation_id="publishAgentVersion",
    responses={
        200: {"model": AgentVersionDTO, "description": "Immutable version and snapshot published."},
        404: {"model": Error, "description": "Version not found."},
        409: {"model": Error, "description": "Publish conflict."},
        422: {"model": Error, "description": "Publish validation failed."},
    },
)
def publish_agent_version(
    version_id: UUID,
    payload: PublishAgentVersionRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    # FastAPI still injects Request by its exact annotation. The default keeps
    # direct non-generation domain tests/callers compatible with the endpoint.
    request: Request = cast(Request, None),
    background_tasks: BackgroundTasks = cast(BackgroundTasks, None),
) -> AgentVersionDTO:
    # Each publish holds its request connection plus short independent
    # sessions for the idempotency lease, so unbounded concurrent publishes
    # exhaust the DB pool and the 10s claim lease expires while waiting for a
    # connection.  Queue publishes behind the create admission gate (below
    # pool capacity) before the claim starts, so they wait instead of failing.
    # Auth already checked out a pool connection for this request.  Commit
    # (persisting anything the auth path touched) so that connection returns
    # to the pool while we queue; otherwise every waiter pins one and the
    # admitted publishes starve for their own lease sessions.  Loaded ORM
    # state is expired and reloads lazily after admission.
    agent_id = db.scalar(select(AgentVersion.agent_id).where(AgentVersion.id == str(version_id)))
    db.commit()
    with create_admission_slot(settings):
        result = _publish_agent_version_admitted(
            version_id, payload, idempotency_key, context, db, settings, request
        )
    if background_tasks is not None and agent_id is not None:
        background_tasks.add_task(compile_after_save, db.get_bind(), agent_id, settings)
    return result


def _publish_agent_version_admitted(
    version_id: UUID,
    payload: PublishAgentVersionRequest,
    idempotency_key: str,
    context: AuthContext,
    db: Session,
    settings: Settings,
    request: Request,
) -> AgentVersionDTO:
    # Keep the original scope check for the stable permission/not-found
    # boundary, but never reuse that ORM object after the durable claim.  The
    # guarded re-read below is the authority for the publish write.
    reject_baseline_version_mutation(str(version_id))
    visible_student_version(db, context, str(version_id))

    open_run_id = db.scalar(
        select(DemoAcceptanceRun.id).where(
            DemoAcceptanceRun.target_version_id == str(version_id),
            DemoAcceptanceRun.state.in_(("prepared", "executing")),
        )
    )
    has_binding = payload.acceptance_run_id is not None
    if open_run_id is not None and not has_binding:
        raise conflict(
            "acceptance_binding_required",
            "The open Demo acceptance run requires its Call1 binding.",
        )
    if has_binding and open_run_id is None:
        raise conflict(
            "acceptance_binding_invalid",
            "The Demo acceptance run is not open for this target.",
        )
    if has_binding and payload.call_no != 1:
        raise conflict(
            "acceptance_binding_invalid",
            "Snapshot acceptance binding must use Call1.",
        )
    if has_binding and settings.embedding_provider == "mock":
        raise conflict(
            "acceptance_binding_provider_invalid",
            "Demo acceptance binding is available only for the reviewed real Snapshot.",
        )
    body_hash = parse_json_payload_hash(
        "publishAgentVersion",
        context,
        [str(version_id)],
        payload.model_dump(exclude_none=True),
    )
    record, replay = claim_idempotency(
        db,
        context,
        "publishAgentVersion",
        idempotency_key,
        body_hash,
        data_root=settings.resolved_data_root,
    )
    if replay is not None:
        replayed_version = AgentVersionDTO.model_validate_json(bytes(replay.body))
        if replayed_version.knowledge_generation is not None and not settings.is_test:
            task_manager = getattr(request.app.state, "knowledge_generation_task_manager", None)
            if task_manager is not None:
                task_manager.wake(str(replayed_version.knowledge_generation.run_id))
        return replay  # type: ignore[return-value]
    assert_claim_owned(db, record)
    guard_id: str | None = None
    try:
        version, agent, guard_id = _acquire_publish_guard(
            db,
            context,
            str(version_id),
            payload.expected_revision,
            record,
        )
        if payload.generation is not None:
            validate_generation_intent(db, context, agent, version, payload.generation)
        enabled_documents = _enabled_documents(db, version.id)
        if agent.visibility == "public" and not _agent_sources_are_public(db, agent):
            raise validation_failure(
                "Private sources must be shared before this Agent can be public.",
                code="private_source_for_public_agent",
            )
        if not enabled_documents:
            publish_without_snapshot(
                db,
                version,
                agent,
                expected_revision=payload.expected_revision,
            )
        elif settings.embedding_provider == "mock":
            create_snapshot(
                db,
                settings.resolved_data_root,
                version,
                agent,
                expected_revision=payload.expected_revision,
                idempotency_record_id=record.id,
                claim_token=record.claim_token,
            )
        elif settings.embedding_provider == "dashscope":
            _publish_real_embedding_snapshot(
                db,
                settings,
                version=version,
                agent=agent,
                expected_revision=payload.expected_revision,
                record=record,
                acceptance_run_id=(
                    str(payload.acceptance_run_id)
                    if payload.acceptance_run_id is not None
                    else None
                ),
                call_no=payload.call_no,
            )
        else:  # pragma: no cover - Settings validates the closed selector.
            raise PlatformError(
                "provider_unavailable", "The service is temporarily unavailable.", 503
            )
        generation = (
            enqueue_generation_for_publish(db, context, agent, version, payload.generation)
            if payload.generation is not None
            else None
        )
        # ``create_snapshot`` owns the heavy staging/finalization transaction
        # and intentionally rolls back before its final re-check.  The guard
        # survives that boundary, so mark it committed in the same transaction
        # as the immutable version and idempotency completion.
        guard = db.get(FileOperation, guard_id)
        if guard is None or guard.state != "prepared":
            raise invalid_state("The Agent publish guard is no longer active.")
        guard.state = "committed"
        guard.updated_at = _time()
        _touch_last_editor(db, agent.id, context.user.id)
        result = _version_dto_for_actor(db, version, agent, context)
        if generation is not None:
            result = result.model_copy(
                update={"knowledge_generation": generation_receipt(generation.run)}
            )
        finish_idempotency(db, record, 200, result.model_dump(mode="json"))
        db.flush()
        saga_checkpoint("publish.after_final_db_prepare")
        db.commit()
        saga_checkpoint("publish.after_final_commit")
        # Teams holding this Agent follow its new version on their own.
        from app.modules.teams.service import follow_published_agent

        follow_published_agent(db, agent.id)
        # Open chats with this Agent move to the new version (history kept).
        from app.modules.agents.cascade import retarget_agent_chats
        from app.modules.real_delete import prune_agent_versions

        retarget_agent_chats(db, agent.id)
        try:
            prune_agent_versions(db, agent.id, settings.resolved_data_root)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("agent_version_prune_failed agent_id=%s", agent.id)
        if generation is not None and not settings.is_test:
            task_manager = getattr(request.app.state, "knowledge_generation_task_manager", None)
            if task_manager is not None:
                task_manager.wake(generation.run.id)
        return result
    except ObjectDeletedError as exc:
        # A legacy caller or a process-local race may still hand us a deleted
        # ORM instance.  End the guard/claim and expose the same stable 404 as
        # the guarded re-query instead of leaking a 503 infrastructure error.
        _recover_publish_guard(db, guard_id)
        abandon_claim(db, record)
        raise not_found() from exc
    except PlatformError:
        _recover_publish_guard(db, guard_id)
        abandon_claim(db, record)
        raise
    except Exception:
        # Keep the operation/claim journal durable for startup recovery when
        # an injected crash or unexpected infrastructure error occurs.
        _recover_publish_guard(db, guard_id)
        abandon_claim(db, record)
        raise


@router.post(
    "/agents/preview",
    response_model=AgentPreviewResponse,
    operation_id="previewAgent",
    responses={
        200: {
            "model": AgentPreviewResponse,
            "description": "Disposable single-sentence reply and optional voice.",
        },
        409: {"model": Error, "description": "Publish the first Agent version first."},
        404: {"model": Error, "description": "Agent or source not found."},
        422: {"model": Error, "description": "Invalid Preview input."},
    },
)
def preview_agent_route(
    payload: AgentPreviewRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AgentPreviewResponse:
    from app.modules.agents.preview import preview_agent

    try:
        return preview_agent(db, context, payload, settings)
    except PlatformError as exc:
        logger.warning("agent_preview_failed safe_code=%s", exc.code)
        raise


@router.post(
    "/agent-versions/{version_id}/chat",
    response_model=TestChatResponse,
    operation_id="testAgentDraft",
    responses={
        200: {"model": TestChatResponse, "description": "Non-persistent test answer."},
        404: {"model": Error, "description": "Draft not found."},
        422: {"model": Error, "description": "Draft is not testable."},
    },
)
def test_agent_draft(
    version_id: UUID,
    payload: TestChatRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> TestChatResponse:
    scoped = visible_student_version(db, context, str(version_id))
    if scoped.version.state != "draft":
        raise not_found()
    docs = _enabled_documents(db, scoped.version.id)
    if not scoped.version.agent_md.strip():
        raise validation_failure(
            "The draft needs AGENT.md.",
            code="agent_md_missing",
        )
    if any(document.index_status != "ready" for document in docs):
        if any(document.index_status == "failed" for document in docs):
            raise validation_failure(
                "All enabled documents must be indexed before test chat.",
                code="rag_index_failed",
            )
        raise validation_failure(
            "All enabled documents must be indexed before test chat.",
            code="rag_index_pending",
        )
    return retrieval_response(db, scoped.version, payload.message)


@router.get(
    "/courses/{course_id}/published-agents",
    response_model=list[PublishedAgentSummary],
    operation_id="listPublishedAgentsForTeacher",
    responses={
        200: {"model": list[PublishedAgentSummary], "description": "Current published candidates."},
        404: {"model": Error, "description": "Course not found."},
    },
)
def list_published_agents_for_teacher(
    course_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[PublishedAgentSummary]:
    with request_read_memo():
        return _published_agents_for_teacher(db, context, str(course_id))


def _published_agents_for_teacher(
    db: Session, context: AuthContext, course_id: str
) -> list[PublishedAgentSummary]:
    from app.modules.agents.readiness import readiness_issues
    from app.modules.agents.schemas import AgentReadinessIssue

    member_role = course_member_role(db, context.user.id, course_id)
    if member_role not in {"teacher", "student"}:
        raise not_found()
    rows = db.execute(
        select(Agent, AgentVersion, Group.name)
        .join(AgentVersion, AgentVersion.id == Agent.current_published_version_id)
        .outerjoin(Group, Group.id == Agent.group_id)
        .where(
            Agent.course_id == course_id,
            Agent.status == "active",
            Agent.deleted_at.is_(None),
            Agent.visibility == "public",
            AgentVersion.state == "published",
            AgentVersion.published_visibility == "public",
            AgentVersion.authorization_epoch == Agent.authorization_epoch,
        )
        .order_by(Agent.created_at.desc(), Agent.id.desc())
    ).all()
    prefetch_agent_reads(
        db, [(agent, version) for agent, version, _group in rows], viewer_id=context.user.id
    )
    public_rows: list[tuple[Agent, AgentVersion, str]] = [
        (agent, version, group_name or "")
        for agent, version, group_name in rows
        if can_invoke_version(db, context, version, agent)
    ]
    return [
        PublishedAgentSummary(
            group_name=group_name,
            author=_published_author(db, agent, version),
            agent=_summary_with_metadata(
                db,
                agent,
                include_draft=False,
                role="teacher",
                context=context,
            ),
            # A list card shows a name, a version and an avatar. The full
            # AGENT.md and document list of every Agent were three quarters of
            # a 480 KB response (production, 60 Agents) that each page load
            # downloaded and parsed; the editor reads its own version.
            current_version=version_dto(db, version, agent).model_copy(
                update={"agent_md": "", "enabled_documents": []}
            ),
            readiness_issues=[
                AgentReadinessIssue.model_validate(item) for item in readiness_issues(db, agent)
            ],
        )
        for agent, version, group_name in public_rows
    ]


def _published_author(
    db: Session, agent: Agent, version: AgentVersion
) -> PublishedAgentAuthor | None:
    user_id = agent.owner_user_id or version.persona_confirming_user_id
    user = prefetched(db, "user", user_id, lambda: db.get(User, user_id)) if user_id else None
    if user is None:
        return None
    return PublishedAgentAuthor(
        user_id=UUID(user.id), display_name=user.display_name, avatar=user.avatar
    )
