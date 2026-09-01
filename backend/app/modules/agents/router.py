"""Agent/version and teacher published projections."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NoReturn, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import and_, exists, or_, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError

from app.core.config import Settings, get_settings
from app.core.errors import (
    Error,
    PlatformError,
    conflict,
    forbidden,
    invalid_state,
    not_found,
    rag_over_limit,
    stale_revision,
    validation_failure,
    version_immutable,
)
from app.core.models import (
    Agent,
    AgentVersion,
    AgentVersionDocument,
    CourseMember,
    DemoAcceptanceRun,
    FileOperation,
    Group,
    GroupMember,
    IdempotencyRecord,
    KnowledgeSnapshot,
)
from app.modules.agents.persona import (
    raw_agent_md_hash,
)
from app.modules.agents.persona_repository import SqlAlchemyPersonaStore
from app.modules.agents.persona_service import (
    PersonaConfirmationRequest as PersonaConfirmationDomainRequest,
)
from app.modules.agents.persona_service import (
    PersonaDomainError,
    PersonaService,
    persona_publication_blocker,
)
from app.modules.agents.schemas import (
    AgentCreateRequest,
    AgentDetail,
    AgentSummary,
    CompilePersonaRequest,
    ConfirmPersonaRequest,
    PersonaCompileResponse,
    PublishAgentVersionRequest,
    PublishedAgentSummary,
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
from app.modules.demo_baseline.service import (
    reject_baseline_agent_mutation,
    reject_baseline_version_mutation,
)
from app.modules.knowledge.files import content_disposition, frozen_download_filename
from app.modules.knowledge.markdown import MAX_RAG_CHARS, MarkdownInputError, normalize_markdown
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
    abandon_claim,
    agent_detail,
    agent_summary,
    assert_claim_owned,
    claim_idempotency,
    create_snapshot,
    finish_idempotency,
    parse_json_payload_hash,
    renew_idempotency_lease,
    retrieval_response,
    saga_checkpoint,
    scoped_group_role,
    scoped_student_group_role,
    version_dto,
    visible_agent,
    visible_student_agent,
    visible_student_version,
    visible_version,
)
from app.providers.control_repository import ProviderRepository
from app.providers.factory import embedding_provider as select_embedding_provider

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


def _raise_persona_domain_error(error: PersonaDomainError) -> NoReturn:
    """Map the pure Persona port error to Maya's stable error envelope."""

    if error.code == "stale_revision":
        current = error.details.get("current_revision")
        raise stale_revision(int(current) if isinstance(current, int) else None)
    if error.code == "version_immutable":
        raise version_immutable()
    if error.code == "forbidden":
        raise forbidden(error.message)
    if error.code in {
        "persona_confirmation_required",
        "persona_integrity_mismatch",
        "persona_compile_required",
        "persona_compile_failed",
    }:
        raise validation_failure(error.message, error.details, code=error.code)
    raise invalid_state(error.message)


def _summary_with_metadata(
    db: Session, agent: Agent, *, include_draft: bool = True
) -> AgentSummary:
    """Build the shared projection with its authoritative metadata CAS."""

    return agent_summary(db, agent, include_draft=include_draft)


def _detail_with_metadata(db: Session, agent: Agent, role: str) -> AgentDetail:
    """Return an Agent detail whose mutable metadata is current and explicit."""

    detail = agent_detail(db, agent, role)
    return detail.model_copy(update={"metadata_revision": agent.metadata_revision})


def _student_delete_scope(db: Session, context: AuthContext, agent_id: str) -> Agent:
    """Resolve delete visibility and preserve the teacher/other-group split.

    A student must be a member of the owning group.  A teacher in the owning
    course is deliberately recognized before the student-only check so the
    operation returns ``403 forbidden`` rather than accidentally making a
    same-course teacher look like a missing resource.  Other courses/groups
    remain indistinguishable from a missing Agent and return 404.
    """

    row = db.execute(
        select(Agent, CourseMember.role)
        .join(Group, Group.id == Agent.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .outerjoin(
            GroupMember,
            and_(GroupMember.group_id == Group.id, GroupMember.user_id == context.user.id),
        )
        .where(
            Agent.id == agent_id,
            CourseMember.user_id == context.user.id,
            or_(
                CourseMember.role == "teacher",
                and_(CourseMember.role == "student", GroupMember.user_id.is_not(None)),
            ),
        )
    ).first()
    if row is None:
        raise not_found()
    if row[1] != "student":
        raise forbidden()
    return cast(Agent, row[0])


def _agent_has_history(db: Session, agent_id: str) -> bool:
    """Check every retained Agent history source while the writer lock is held."""

    # A publish claim has to exclude a concurrent hard delete even while its
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
    if publish_guard is not None:
        return True

    # A non-null current pointer is itself a historical reference.  Keep a
    # malformed legacy pointer conservative rather than deleting an Agent
    # whose published lineage may only be partially represented in the DB.
    if db.scalar(
        select(Agent.current_published_version_id).where(
            Agent.id == agent_id,
            Agent.current_published_version_id.is_not(None),
        )
    ):
        return True

    # A non-draft version or any snapshot binding is historical even if a
    # malformed/legacy row lost the current pointer.  This is intentionally
    # broader than only checking ``current_published_version_id``.
    version_history = db.scalar(
        select(AgentVersion.id).where(
            AgentVersion.agent_id == agent_id,
            or_(
                AgentVersion.state.in_(("published", "superseded")),
                AgentVersion.knowledge_snapshot_id.is_not(None),
            ),
        )
    )
    if version_history is not None:
        return True

    snapshot_history = db.scalar(
        select(KnowledgeSnapshot.id)
        .join(AgentVersion, AgentVersion.id == KnowledgeSnapshot.agent_version_id)
        .where(AgentVersion.agent_id == agent_id)
    )
    if snapshot_history is not None:
        return True

    # Debate models are a vertical Wave 2 module.  Importing lazily keeps the
    # earlier isolated Agent/schema tests free of a circular module import,
    # while production and migration schemas always register this table.
    from app.modules.debates.models import DebateParticipant

    return (
        db.scalar(select(DebateParticipant.id).where(DebateParticipant.agent_id == agent_id))
        is not None
    )


def _begin_immediate(db: Session) -> None:
    """Start the final serialized Agent writer transaction.

    Scoped authorization reads may have opened a WAL snapshot.  Roll it back
    before issuing ``BEGIN IMMEDIATE`` so the final eligibility check cannot
    fail with ``SQLITE_BUSY_SNAPSHOT`` and so publish/debate writers cannot
    interleave between the check and the delete.
    """

    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))


def _acquire_publish_guard(
    db: Session,
    context: AuthContext,
    version_id: str,
    expected_revision: int,
    record: IdempotencyRecord,
) -> tuple[AgentVersion, Agent, str]:
    """Re-read a publish target under SQLite's writer lock and fence deletion.

    The idempotency claim is committed before this function is called.  The
    immediate transaction then re-resolves the student-visible version and
    inserts a durable Agent-scoped guard before releasing the lock.  A delete
    that wins the lock first sees a missing version and the publish caller gets
    a stable 404; a publish that wins leaves a guard for the delete's final
    history check.
    """

    _begin_immediate(db)
    try:
        scoped = visible_student_version(db, context, version_id)
        if scoped.version.state != "draft":
            raise version_immutable()
        if scoped.agent.status != "active":
            raise invalid_state("Archived Agents cannot be published.")
        if scoped.version.revision != expected_revision:
            raise stale_revision(scoped.version.revision)
        # Keep an explicit CAS fence in the locked transaction as well as the
        # ORM re-read.  This makes the publish winner observable to SQLite and
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
    db.execute(text("BEGIN IMMEDIATE"))
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

    if error.code == "provider_confirmation_required":
        raise conflict(
            "provider_confirmation_required",
            "The course teacher must confirm the exact provider disclosure.",
        ) from error
    if error.code == "persona_confirmation_required":
        raise validation_failure(
            "The Persona must be compiled and confirmed before publication.",
            {"publish_blockers": ["persona_confirmation_required"]},
            code="persona_confirmation_required",
        ) from error
    if error.code == "version_immutable":
        raise version_immutable() from error
    if error.code == "rag_over_limit":
        raise rag_over_limit() from error
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
    group = db.get(Group, agent.group_id)
    if group is None:
        raise not_found()
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
            course_id=group.course_id,
            group_id=group.id,
            agent_version_id=version.id,
            expected_revision=expected_revision,
        )
        manifest = ensure_real_embedding_export_manifest(
            db,
            build,
            course_id=group.course_id,
            group_id=group.id,
            agent_version_id=version.id,
            policy=policy,
        )
        confirmation = require_exact_confirmation(
            db,
            manifest,
            policy,
            course_id=group.course_id,
            group_id=group.id,
            agent_version_id=version.id,
        )
        renew_idempotency_lease(db, record, lease_seconds=900)
        selected_provider = select_embedding_provider(settings)
        result = run_confirmed_real_embedding_publication(
            db,
            data_root=settings.resolved_data_root,
            course_id=group.course_id,
            group_id=group.id,
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
            AgentVersion.agent_id == Agent.id,
            AgentVersion.state.in_(("published", "superseded")),
        )
    )
    rows = db.execute(
        select(Agent, CourseMember.role)
        .join(Group, Group.id == Agent.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .outerjoin(
            GroupMember,
            and_(GroupMember.group_id == Group.id, GroupMember.user_id == context.user.id),
        )
        .where(
            Agent.group_id == str(group_id),
            CourseMember.user_id == context.user.id,
            or_(
                and_(CourseMember.role == "teacher", published_version),
                and_(CourseMember.role == "student", GroupMember.user_id.is_not(None)),
            ),
        )
    ).all()
    agents = [row for row in rows if include_archived or row[0].status == "active"]
    return [_summary_with_metadata(db, row[0], include_draft=role != "teacher") for row in agents]


@router.post(
    "/groups/{group_id}/agents",
    response_model=AgentDetail,
    status_code=201,
    operation_id="createAgent",
    responses={
        201: {"model": AgentDetail, "description": "Agent and V1.0 draft created."},
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
    scoped_student_group_role(db, context, str(group_id))
    body_hash = parse_json_payload_hash(
        "createAgent", context, [str(group_id)], payload.model_dump()
    )
    record, replay = claim_idempotency(db, context, "createAgent", idempotency_key, body_hash)
    if replay is not None:
        return replay  # type: ignore[return-value]
    assert_claim_owned(db, record)
    timestamp = _time()
    agent = Agent(
        id=str(uuid4()),
        group_id=str(group_id),
        name=payload.name,
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
        persona_required=True,
        avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add_all([agent, version])
    db.flush()
    result = _detail_with_metadata(db, agent, "student")
    finish_idempotency(db, record, 201, result.model_dump(mode="json"))
    saga_checkpoint("create_agent.before_final_commit")
    db.commit()
    saga_checkpoint("create_agent.after_final_commit")
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
    scoped = visible_agent(db, context, str(agent_id))
    return _detail_with_metadata(db, scoped.agent, scoped.role)


@router.patch(
    "/agents/{agent_id}",
    response_model=AgentDetail,
    operation_id="updateAgentMetadata",
    responses={
        200: {"model": AgentDetail, "description": "Mutable Agent metadata updated."},
        404: {"model": Error, "description": "Agent not found."},
        409: {"model": Error, "description": "Metadata revision conflict."},
    },
)
def update_agent_metadata(
    agent_id: UUID,
    payload: UpdateAgentMetadataRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> AgentDetail:
    """CAS-update description without touching any versioned Agent data."""

    reject_baseline_agent_mutation(str(agent_id))
    scoped = visible_student_agent(db, context, str(agent_id))
    # Close the authorization read snapshot before taking the final writer
    # lock.  This also makes concurrent updates resolve to one deterministic
    # winner instead of a SQLite WAL snapshot error.
    _begin_immediate(db)
    try:
        current = db.scalar(
            select(Agent).where(
                Agent.id == str(agent_id),
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
        description = payload.description
        current.description = description if description and description.strip() else ""
        current.metadata_revision += 1
        current.updated_at = _time()
        db.flush()
        result = _detail_with_metadata(db, current, "student")
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
        204: {"description": "Eligible Agent and its draft state deleted."},
        403: {"model": Error, "description": "Teachers cannot delete Agents."},
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
) -> Response:
    """Hard-delete only an Agent with no immutable or debate history.

    The final eligibility query and delete run under one ``BEGIN IMMEDIATE``
    transaction.  SQLite's writer lock therefore serializes this operation
    with publish and Debate creation, leaving exactly one committed winner.
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
        _begin_immediate(db)
        # Re-resolve both the actor scope and the Agent under the writer lock;
        # no publish/Debate writer can slip between this read and the delete.
        agent = _student_delete_scope(db, context, str(agent_id))
        if _agent_has_history(db, agent.id):
            db.rollback()
            abandon_claim(db, record)
            raise conflict(
                "agent_history_retained",
                "This Agent has published or classroom history and must be retained.",
            )

        # AgentVersion -> AgentVersionDocument are Agent-owned draft state and
        # are removed by the ORM cascade.  KnowledgeDocument, VoiceProfile,
        # AuditLog, StoredFile and other group/Agent rows have no cascade from
        # this delete and therefore remain intact.
        db.delete(agent)
        db.flush()
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
    scoped = visible_agent(db, context, str(agent_id))
    query = select(AgentVersion).where(AgentVersion.agent_id == scoped.agent.id)
    if scoped.role == "teacher":
        query = query.where(AgentVersion.state.in_(("published", "superseded")))
    versions = list(db.scalars(query.order_by(AgentVersion.version_seq)).all())
    if scoped.role == "teacher" and not versions:
        raise not_found()
    return [version_dto(db, version, scoped.agent) for version in versions]


@router.post(
    "/agents/{agent_id}/versions",
    response_model=AgentVersionDTO,
    status_code=201,
    operation_id="createNextAgentVersion",
    responses={
        201: {"model": AgentVersionDTO, "description": "Current published version cloned."},
        404: {"model": Error, "description": "Agent not found."},
        409: {"model": Error, "description": "Version creation conflict."},
    },
)
def create_next_agent_version(
    agent_id: UUID,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> AgentVersionDTO:
    reject_baseline_agent_mutation(str(agent_id))
    scoped = visible_student_agent(db, context, str(agent_id))
    body_hash = parse_json_payload_hash("createNextAgentVersion", context, [str(agent_id)], {})
    record, replay = claim_idempotency(
        db, context, "createNextAgentVersion", idempotency_key, body_hash
    )
    if replay is not None:
        return replay  # type: ignore[return-value]
    assert_claim_owned(db, record)
    if scoped.agent.status != "active" or not scoped.agent.current_published_version_id:
        abandon_claim(db, record)
        raise invalid_state(
            "An active published version is required before creating the next draft."
        )
    current = db.scalar(
        select(AgentVersion)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .join(Group, Group.id == Agent.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .join(
            GroupMember,
            and_(GroupMember.group_id == Group.id, GroupMember.user_id == context.user.id),
        )
        .where(
            AgentVersion.id == scoped.agent.current_published_version_id,
            AgentVersion.agent_id == scoped.agent.id,
            CourseMember.user_id == context.user.id,
            CourseMember.role == "student",
        )
    )
    if current is None or current.state != "published":
        abandon_claim(db, record)
        raise invalid_state("The current published version is unavailable.")
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
        persona_required=True,
        avatar_config_json=current.avatar_config_json,
        voice_profile_id=current.voice_profile_id,
        knowledge_snapshot_id=None,
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
    result = version_dto(db, version, scoped.agent)
    finish_idempotency(db, record, 201, result.model_dump(mode="json"))
    saga_checkpoint("create_next_agent_version.before_final_commit")
    db.commit()
    saga_checkpoint("create_next_agent_version.after_final_commit")
    return result


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
    scoped = visible_version(db, context, str(version_id))
    return version_dto(db, scoped.version, scoped.agent)


@router.post(
    "/agent-versions/{version_id}/persona/compile",
    response_model=PersonaCompileResponse,
    operation_id="compileAgentPersona",
    responses={
        200: {"model": PersonaCompileResponse, "description": "Deterministic Persona preview."},
        404: {"model": Error, "description": "Version not found."},
        409: {"model": Error, "description": "Revision or immutability conflict."},
    },
)
def compile_agent_persona(
    version_id: UUID,
    payload: CompilePersonaRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> PersonaCompileResponse:
    reject_baseline_version_mutation(str(version_id))
    scoped = visible_student_version(db, context, str(version_id))
    if scoped.version.state != "draft":
        raise version_immutable()
    store = SqlAlchemyPersonaStore(db)
    service = PersonaService(store)
    try:
        result = service.compile_draft(str(version_id), expected_revision=payload.expected_revision)
    except PersonaDomainError as error:
        _raise_persona_domain_error(error)
    state = store.get_persona_version(str(version_id))
    if state is None:  # pragma: no cover - compile CAS already loaded the row
        raise not_found()
    return PersonaCompileResponse(
        version_id=version_id,
        revision=state.revision,
        compiled=result.compiled,
        raw_agent_md_hash=result.source_agent_md_hash,
        persona_spec=result.spec,
        persona_spec_hash=result.persona_spec_hash,
        compiler_version=result.compiler_version,
        diagnostics=list(result.diagnostics),
        persona_confirmed=False,
    )


@router.post(
    "/agent-versions/{version_id}/persona/confirm",
    response_model=AgentVersionDTO,
    operation_id="confirmAgentPersona",
    responses={
        200: {"model": AgentVersionDTO, "description": "Persona confirmed for the exact draft."},
        403: {"model": Error, "description": "A current group member is required."},
        404: {"model": Error, "description": "Version not found."},
        409: {"model": Error, "description": "Revision conflict."},
        422: {"model": Error, "description": "Persona confirmation required."},
    },
)
def confirm_agent_persona(
    version_id: UUID,
    payload: ConfirmPersonaRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> AgentVersionDTO:
    reject_baseline_version_mutation(str(version_id))
    visible = visible_student_version(db, context, str(version_id))
    if visible.version.state != "draft":
        raise version_immutable()
    request = PersonaConfirmationDomainRequest(
        version_id=str(version_id),
        expected_revision=payload.expected_revision,
        raw_agent_md_hash=payload.raw_agent_md_hash,
        persona_spec_hash=payload.persona_spec_hash,
        compiler_version=payload.compiler_version,
    )
    service = PersonaService(SqlAlchemyPersonaStore(db))
    try:
        service.confirm(request, confirming_user_id=context.user.id)
    except PersonaDomainError as error:
        _raise_persona_domain_error(error)
    refreshed = visible_student_version(db, context, str(version_id))
    return version_dto(db, refreshed.version, refreshed.agent)


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
) -> AgentVersionDTO:
    reject_baseline_version_mutation(str(version_id))
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
    db.refresh(scoped.version)
    db.flush()
    return version_dto(db, scoped.version, scoped.agent)


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
            revision=AgentVersion.revision + 1,
            updated_at=_time(),
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        current_revision = db.scalar(
            select(AgentVersion.revision).where(AgentVersion.id == scoped.version.id)
        )
        raise stale_revision(current_revision)
    db.refresh(scoped.version)
    db.flush()
    return version_dto(db, scoped.version, scoped.agent)


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

    scoped = visible_version(db, context, str(version_id))
    if scoped.version.state not in {"published", "superseded"}:
        raise not_found()
    filename = frozen_download_filename(
        "AGENT.md",
        scoped.agent.name,
        f"V1.{scoped.version.version_seq}",
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
        persona_blocker = persona_publication_blocker(version)
        if persona_blocker is not None:
            raise validation_failure(
                "The Persona must be compiled and confirmed before publication.",
                {"publish_blockers": [persona_blocker]},
                code=persona_blocker,
            )
        if settings.embedding_provider == "mock":
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
        # ``create_snapshot`` owns the heavy staging/finalization transaction
        # and intentionally rolls back before its final re-check.  The guard
        # survives that boundary, so mark it committed in the same transaction
        # as the immutable version and idempotency completion.
        guard = db.get(FileOperation, guard_id)
        if guard is None or guard.state != "prepared":
            raise invalid_state("The Agent publish guard is no longer active.")
        guard.state = "committed"
        guard.updated_at = _time()
        result = version_dto(db, version, agent)
        finish_idempotency(db, record, 200, result.model_dump(mode="json"))
        db.flush()
        saga_checkpoint("publish.after_final_db_prepare")
        db.commit()
        saga_checkpoint("publish.after_final_commit")
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
    if not scoped.version.agent_md.strip() or not docs:
        if not scoped.version.agent_md.strip():
            raise validation_failure(
                "The draft needs AGENT.md.",
                code="agent_md_missing",
            )
        raise validation_failure(
            "The draft needs one enabled ready document.",
            code="rag_missing",
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
    if sum(document.char_count for document in docs) > MAX_RAG_CHARS:
        raise rag_over_limit()
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
    rows = db.execute(
        select(Agent, AgentVersion)
        .join(Group, Group.id == Agent.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .join(AgentVersion, AgentVersion.id == Agent.current_published_version_id)
        .where(
            Group.course_id == str(course_id),
            CourseMember.user_id == context.user.id,
            CourseMember.role == "teacher",
            Agent.status == "active",
            AgentVersion.state == "published",
        )
        .order_by(Agent.name)
    ).all()
    if not rows:
        course_exists = db.scalar(
            select(CourseMember.course_id).where(
                CourseMember.course_id == str(course_id),
                CourseMember.user_id == context.user.id,
                CourseMember.role == "teacher",
            )
        )
        if course_exists is None:
            raise not_found()
    return [
        PublishedAgentSummary(
            agent=_summary_with_metadata(db, agent, include_draft=False),
            current_version=version_dto(db, version, agent),
        )
        for agent, version in rows
    ]
