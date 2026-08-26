"""Agent/version and teacher published projections."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import (
    Error,
    PlatformError,
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
    Group,
    GroupMember,
)
from app.modules.agents.schemas import (
    AgentCreateRequest,
    AgentDetail,
    AgentSummary,
    ExpectedRevisionRequest,
    PublishedAgentSummary,
    TestChatRequest,
    TestChatResponse,
    UpdateAgentDraftRequest,
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
from app.modules.knowledge.markdown import MAX_RAG_CHARS, MarkdownInputError, normalize_markdown
from app.modules.knowledge.multipart import integer_field, parse_upload
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
    include_archived: bool = Query(False),
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
    return [agent_summary(db, row[0], include_draft=role != "teacher") for row in agents]


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
        description=payload.description,
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
        avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add_all([agent, version])
    db.flush()
    result = agent_detail(db, agent, "student")
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
    return agent_detail(db, scoped.agent, scoped.role)


def _archive_agent(
    agent_id: UUID,
    *,
    status: str,
    operation: str,
    idempotency_key: str,
    context: AuthContext,
    db: Session,
) -> AgentSummary:
    scoped = visible_student_agent(db, context, str(agent_id))
    body_hash = parse_json_payload_hash(operation, context, [str(agent_id)], {"status": status})
    record, replay = claim_idempotency(db, context, operation, idempotency_key, body_hash)
    if replay is not None:
        return replay  # type: ignore[return-value]
    assert_claim_owned(db, record)
    scoped.agent.status = status
    scoped.agent.updated_at = _time()
    result = agent_summary(db, scoped.agent)
    finish_idempotency(db, record, 200, result.model_dump(mode="json"))
    saga_checkpoint(f"{operation}.before_final_commit")
    db.commit()
    saga_checkpoint(f"{operation}.after_final_commit")
    return result


@router.post(
    "/agents/{agent_id}/archive",
    response_model=AgentSummary,
    operation_id="archiveAgent",
    responses={
        200: {"model": AgentSummary, "description": "Agent archived; history retained."},
        404: {"model": Error, "description": "Agent not found."},
        409: {"model": Error, "description": "Invalid archive transition."},
    },
)
def archive_agent(
    agent_id: UUID,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> AgentSummary:
    return _archive_agent(
        agent_id,
        status="archived",
        operation="archiveAgent",
        idempotency_key=idempotency_key,
        context=context,
        db=db,
    )


@router.post(
    "/agents/{agent_id}/unarchive",
    response_model=AgentSummary,
    operation_id="unarchiveAgent",
    responses={
        200: {"model": AgentSummary, "description": "Agent returned to active state."},
        404: {"model": Error, "description": "Agent not found."},
    },
)
def unarchive_agent(
    agent_id: UUID,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> AgentSummary:
    return _archive_agent(
        agent_id,
        status="active",
        operation="unarchiveAgent",
        idempotency_key=idempotency_key,
        context=context,
        db=db,
    )


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
    scoped = visible_student_version(db, context, str(version_id))
    if scoped.version.state != "draft":
        raise version_immutable()
    if scoped.version.revision != payload.expected_revision:
        raise stale_revision(scoped.version.revision)
    values: dict[str, object] = {
        "revision": AgentVersion.revision + 1,
        "updated_at": _time(),
    }
    if "agent_md" in payload.model_fields_set:
        values["agent_md"] = payload.agent_md.replace("\r\n", "\n").replace("\r", "\n")
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
    payload: ExpectedRevisionRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AgentVersionDTO:
    scoped = visible_student_version(db, context, str(version_id))
    body_hash = parse_json_payload_hash(
        "publishAgentVersion", context, [str(version_id)], payload.model_dump()
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
    try:
        if scoped.version.state != "draft":
            raise version_immutable()
        if scoped.agent.status != "active":
            raise invalid_state("Archived Agents cannot be published.")
        if scoped.version.revision != payload.expected_revision:
            raise stale_revision(scoped.version.revision)
        create_snapshot(
            db,
            settings.resolved_data_root,
            scoped.version,
            scoped.agent,
            expected_revision=payload.expected_revision,
            idempotency_record_id=record.id,
            claim_token=record.claim_token,
        )
        result = version_dto(db, scoped.version, scoped.agent)
        finish_idempotency(db, record, 200, result.model_dump(mode="json"))
        db.flush()
        saga_checkpoint("publish.after_final_db_prepare")
        db.commit()
        saga_checkpoint("publish.after_final_commit")
        return result
    except PlatformError:
        abandon_claim(db, record)
        raise
    except Exception:
        # Keep the operation/claim journal durable for startup recovery when
        # an injected crash or unexpected infrastructure error occurs.
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
            agent=agent_summary(db, agent, include_draft=False),
            current_version=version_dto(db, version, agent),
        )
        for agent, version in rows
    ]
