"""Scoped repositories and deterministic Wave 1A domain services."""

from __future__ import annotations

import hashlib
import json
import secrets
import struct
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from fastapi.responses import JSONResponse
from sqlalchemy import and_, case, delete, exists, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import (
    PlatformError,
    conflict,
    idempotency_conflict,
    invalid_request,
    invalid_state,
    not_found,
    publish_blockers,
    stale_revision,
)
from app.core.models import (
    Agent,
    AgentEditAudit,
    AgentVersion,
    AgentVersionDocument,
    CourseMember,
    FileOperation,
    FileReference,
    Group,
    IdempotencyRecord,
    Job,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeSnapshot,
    ProviderOperation,
    ProviderReservation,
    SnapshotDocument,
    StoredFile,
    User,
)
from app.core.read_memo import memoized
from app.core.sqlutil import begin_immediate
from app.core.version_label import agent_version_label
from app.modules.agents.markdown import markdown_hash
from app.modules.agents.persona import (
    PersonaCompilerVersion,
    PersonaDiagnostic,
    PersonaSpecVersion,
    parse_persona_spec,
)
from app.modules.agents.persona_service import (
    is_persona_confirmed,
)
from app.modules.agents.schemas import (
    AgentDetail,
    AgentSummary,
    AvatarConfig,
    RagPreview,
    RetrievalSource,
    TestChatResponse,
)
from app.modules.agents.schemas import (
    AgentVersion as AgentVersionDTO,
)
from app.modules.agents.schemas import (
    KnowledgeSnapshot as KnowledgeSnapshotDTO,
)
from app.modules.agents.schemas import (
    SnapshotDocument as SnapshotDocumentDTO,
)
from app.modules.auth.service import AuthContext
from app.modules.knowledge.files import (
    promote_atomic,
    read_contained,
    stage_atomic,
    verify_staged,
)
from app.modules.knowledge.markdown import (
    EMBEDDING_DIMENSION,
    EMBEDDING_KEY,
    MAX_CHUNK_UTF8_BYTES,
    normalize_markdown,
    query_embedding,
)
from app.modules.knowledge.mock_lexical import (
    MOCK_LEXICAL_ANCHOR_POLICY_ID,
    MockLexicalAnchorV2,
)
from app.modules.knowledge.providers.snapshot_build import (
    DEFAULT_CHUNKING_VERSION,
    SnapshotPublishCandidateV1,
)
from app.modules.knowledge.schemas import JobStatus
from app.modules.knowledge.schemas import KnowledgeDocument as KnowledgeDocumentDTO
from app.modules.knowledge.source_versions import source_version_filename
from app.modules.org.access import WorkspaceMember


@dataclass(frozen=True)
class ScopedAgent:
    agent: Agent
    role: str


@dataclass(frozen=True)
class ScopedVersion:
    version: AgentVersion
    agent: Agent
    role: str


@dataclass(frozen=True)
class ScopedDocument:
    document: KnowledgeDocument
    role: str


@dataclass(frozen=True)
class ScopedSnapshot:
    snapshot: KnowledgeSnapshot
    version: AgentVersion
    agent: Agent
    role: str


def now_utc() -> datetime:
    return datetime.now(UTC)


def _utc_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _actor_user_id(actor: AuthContext | str) -> str:
    return actor.user.id if isinstance(actor, AuthContext) else actor


def scoped_group_role_for_user(db: Session, user_id: str, group_id: str) -> str | None:
    """Resolve how a group answers this caller, without loading the group first.

    Membership outranks the course role.  A teacher who joined the group is
    inside it and is answered the way its students are; a teacher who has not
    joined still gets the teacher view, which is a summary of published work
    rather than a window into drafts.
    """

    row = db.execute(
        select(CourseMember.role, WorkspaceMember.user_id)
        .select_from(Group)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .outerjoin(
            WorkspaceMember,
            and_(WorkspaceMember.group_id == Group.id, WorkspaceMember.user_id == user_id),
        )
        .where(
            Group.id == group_id,
            CourseMember.user_id == user_id,
            or_(CourseMember.role == "teacher", WorkspaceMember.user_id.is_not(None)),
        )
    ).first()
    if row is None:
        return None
    return "teacher" if row[1] is None else "student"


def scoped_group_role(db: Session, context: AuthContext, group_id: str) -> str | None:
    return scoped_group_role_for_user(db, context.user.id, group_id)


def observes_group(db: Session, user_id: str, group_id: str | None) -> bool:
    """Whether a course teacher has entered this group to look round it.

    Entering is the membership row the roster's Enter creates for the visit.
    That row is a temporary membership: the group library answers the teacher
    the way it answers a groupmate. Private Agents stay readable and not
    editable. The read routes below are the only places that grant the
    ``observer`` role, so it never edits, publishes, chats with or reuses a
    student's private Agent.
    """

    if group_id is None:
        return False
    return (
        db.scalar(
            select(WorkspaceMember.user_id)
            .join(Group, Group.id == WorkspaceMember.group_id)
            .join(
                CourseMember,
                and_(
                    CourseMember.course_id == Group.course_id,
                    CourseMember.user_id == WorkspaceMember.user_id,
                ),
            )
            .where(
                WorkspaceMember.group_id == group_id,
                WorkspaceMember.user_id == user_id,
                CourseMember.role == "teacher",
            )
        )
        is not None
    )


def observes_private_agent(db: Session, context: AuthContext, agent: Agent) -> bool:
    """A private group Agent the caller does not own, in a group they observe."""

    return (
        agent.deleted_at is None
        and agent.ownership_scope == "group"
        and agent.visibility != "public"
        and agent.owner_user_id != context.user.id
        and observes_group(db, context.user.id, agent.group_id)
    )


def scoped_student_group_role(db: Session, context: AuthContext, group_id: str) -> str:
    """Require the student side of a group's workspace.

    A teacher reaches it by joining the group, which is a deliberate act
    recorded as a membership row rather than a standing power over every group
    in the course.  Teachers who have not joined stay outside student drafts,
    which is what keeps the teacher view a summary rather than a window into
    unfinished work.
    """

    if scoped_group_role(db, context, group_id) != "student":
        raise not_found()
    return "student"


def course_member_role(db: Session, user_id: str, course_id: str) -> str | None:
    return memoized(
        db,
        ("course_member_role", str(user_id), str(course_id)),
        lambda: db.scalar(
            select(CourseMember.role).where(
                CourseMember.user_id == user_id,
                CourseMember.course_id == course_id,
            )
        ),
        across_sessions=True,
    )


def _owner_has_course_access(db: Session, actor: AuthContext | str, course_id: str) -> bool:
    return course_member_role(db, _actor_user_id(actor), course_id) is not None


def _publisher_is_teacher(db: Session, agent: Agent) -> bool:
    if agent.owner_user_id is None:
        return False
    return course_member_role(db, agent.owner_user_id, agent.course_id) == "teacher"


def teacher_public_agent_hidden_from(db: Session, actor: AuthContext | str, agent: Agent) -> bool:
    """Studyform: a teacher's public Agent is not a student-facing Agent.

    Students may still meet it as a member of a teacher's public Team (the Team
    runs it server-side), but they cannot list it, open its detail/prompt, or
    start a single-Agent chat with it. Owners and teachers are unaffected.
    """

    user_id = _actor_user_id(actor)
    if agent.owner_user_id == user_id or agent.visibility != "public":
        return False
    if course_member_role(db, user_id, agent.course_id) != "student":
        return False
    return _publisher_is_teacher(db, agent)


def can_use_agent(db: Session, actor: AuthContext | str, agent: Agent) -> bool:
    """Public is who may use the Agent. Private stays on the owner account.

    A teacher-published public Agent is usable by the course. A
    student-published public Agent is usable by that group and by teachers.
    """

    user_id = _actor_user_id(actor)
    if agent.deleted_at is not None or agent.status != "active":
        return False
    if not _owner_has_course_access(db, user_id, agent.course_id):
        return False
    if agent.owner_user_id == user_id:
        return True
    if agent.visibility != "public":
        return False
    viewer = course_member_role(db, user_id, agent.course_id)
    if viewer == "teacher" or _publisher_is_teacher(db, agent):
        return viewer in {"student", "teacher"}
    if agent.group_id is None or viewer != "student":
        return False
    return scoped_group_role_for_user(db, user_id, agent.group_id) is not None


def _agent_workspace_role(db: Session, actor: AuthContext | str, agent: Agent) -> str | None:
    user_id = _actor_user_id(actor)
    if agent.deleted_at is not None or not _owner_has_course_access(db, user_id, agent.course_id):
        return None
    if agent.ownership_scope == "group" and agent.group_id is not None:
        group_role = scoped_group_role_for_user(db, user_id, agent.group_id)
        if agent.owner_user_id == user_id and group_role == "student":
            return "owner"
        if group_role == "teacher" and agent.visibility == "public":
            return "teacher"
        if agent.owner_user_id == user_id:
            return None
        if group_role and agent.visibility == "public":
            return group_role
        if can_use_agent(db, actor, agent):
            return "teacher"
        return None
    if agent.owner_user_id == user_id:
        return "owner"
    if can_use_agent(db, actor, agent):
        return "teacher"
    return None


def _workspace_role_can_read_published(role: str | None, state: str) -> bool:
    return (
        role == "owner"
        or role == "student"
        or (role == "teacher" and state in {"published", "superseded"})
    )


def version_is_currently_public(version: AgentVersion, agent: Agent) -> bool:
    return (
        version.state in {"published", "superseded"}
        and version.published_visibility == "public"
        and version.authorization_epoch == agent.authorization_epoch
        and agent.visibility == "public"
        and agent.deleted_at is None
    )


def draft_is_currently_public(db: Session, version: AgentVersion, agent: Agent) -> bool:
    """Whether a group draft is deliberately shared in the current epoch.

    This marker is sticky: once a draft has private provenance, changing the
    Agent or its sources back to Public cannot expose the draft. Publication
    creates a new immutable public revision when the owner chooses to share it.
    """

    if not (
        version.state == "draft"
        and version.draft_visibility == "public"
        and agent.ownership_scope == "group"
        and agent.visibility == "public"
        and version.authorization_epoch == agent.authorization_epoch
        and agent.deleted_at is None
    ):
        return False
    return all(
        document.visibility == "public"
        and document.workspace_state == "active"
        and document.course_id == agent.course_id
        for document in _enabled_documents(db, version.id)
    )


def can_read_version(
    db: Session,
    version: AgentVersion,
    agent: Agent,
    role: str | None,
    *,
    context: AuthContext | str | None = None,
) -> bool:
    """Single version-visibility rule shared by summaries, history and routes."""

    if role == "observer":
        return True
    if role == "owner":
        return context is None or version_sources_are_readable(
            db,
            context,
            version,
            agent=agent,
            allow_historical_epoch_for_owner=True,
        )
    if version.state == "draft":
        visible = role == "student" and draft_is_currently_public(db, version, agent)
    else:
        visible = _workspace_role_can_read_published(role, version.state) and (
            version_is_currently_public(version, agent)
        )
    if not visible:
        return False
    return context is None or version_sources_are_readable(db, context, version, agent=agent)


def can_invoke_version(
    db: Session,
    context: AuthContext | str,
    version: AgentVersion,
    agent: Agent,
) -> bool:
    """Resolve current workspace access before allowing a Chat invocation.

    Usage follows the Agent's public/private right: a teacher's public Agent
    for the course, a student's public Agent for its group and for teachers,
    and a private Agent for its owner.
    """

    role = _agent_workspace_role(db, context, agent)
    return role is not None and can_read_version(db, version, agent, role, context=context)


def can_read_source(
    db: Session,
    context: AuthContext | str,
    document: KnowledgeDocument,
    *,
    require_active: bool = True,
) -> bool:
    if require_active and document.workspace_state != "active":
        return False
    user_id = _actor_user_id(context)
    if not _owner_has_course_access(db, user_id, document.course_id):
        return False
    if document.ownership_scope == "personal":
        return document.owner_user_id == user_id
    if document.group_id is None:
        return False
    role = scoped_group_role_for_user(db, user_id, document.group_id)
    if role is None or (role == "teacher" and document.visibility != "public"):
        return False
    return document.owner_user_id == user_id or document.visibility == "public"


def can_mutate_source(
    db: Session,
    actor: AuthContext | str,
    document: KnowledgeDocument,
    *,
    require_active: bool = True,
) -> bool:
    """Source mutation is owner-only and requires the active workspace scope."""

    user_id = _actor_user_id(actor)
    if (
        require_active and document.workspace_state != "active"
    ) or document.owner_user_id != user_id:
        return False
    if not _owner_has_course_access(db, user_id, document.course_id):
        return False
    if document.ownership_scope == "personal":
        return document.group_id is None
    if document.group_id is None:
        return False
    # A same-course Teacher can read a published Group summary without
    # entering it. That read role must not become authority to replace, hide,
    # reindex, or change the source's visibility.
    return scoped_group_role_for_user(db, user_id, document.group_id) == "student"


def can_bind_source(
    db: Session, context: AuthContext, agent: Agent, document: KnowledgeDocument
) -> bool:
    if (
        document.workspace_state != "active"
        or document.course_id != agent.course_id
        or not _owner_has_course_access(db, context, agent.course_id)
    ):
        return False
    if document.ownership_scope == "personal":
        return document.owner_user_id == context.user.id and agent.owner_user_id == context.user.id
    if document.group_id is None:
        return False
    source_role = scoped_group_role(db, context, document.group_id)
    if source_role != "student":
        return False
    source_is_owned = document.owner_user_id == context.user.id
    if document.visibility != "public" and not (
        source_is_owned and agent.owner_user_id == context.user.id
    ):
        return False
    if agent.ownership_scope == "group":
        return document.group_id == agent.group_id
    # Attaching a shared Group source to a personal Agent is allowed only
    # when the owner has actually entered that Group workspace. A course role
    # alone is not a grant to enumerate or bind another Group's materials.
    return agent.owner_user_id == context.user.id and source_role == "student"


def _public_snapshot_source_follows_use(
    db: Session,
    context: AuthContext | str,
    document: KnowledgeDocument,
    agent: Agent | None,
) -> bool:
    """Using a public Agent includes the public sources published with it.

    The group library stays closed. This does not grant the raw document.
    """

    if (
        agent is None
        or document.visibility != "public"
        or document.workspace_state != "active"
        or document.course_id != agent.course_id
    ):
        return False
    return can_use_agent(db, context, agent)


def snapshot_sources_are_readable(
    db: Session,
    context: AuthContext | str,
    snapshot_id: str,
    *,
    agent: Agent | None = None,
    allow_historical_epoch_for_owner: bool = False,
) -> bool:
    rows = db.execute(
        select(SnapshotDocument, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeDocument.id == SnapshotDocument.document_id)
        .where(SnapshotDocument.snapshot_id == snapshot_id)
    ).all()
    actor_id = _actor_user_id(context)
    owner_can_read_history = bool(
        allow_historical_epoch_for_owner
        and agent is not None
        and agent.owner_user_id == actor_id
        and _agent_workspace_role(db, actor_id, agent) == "owner"
    )
    return all(
        (
            owner_can_read_history
            or document.authorization_epoch == source_row.source_authorization_epoch
        )
        and (
            can_read_source(db, context, document, require_active=False)
            or _public_snapshot_source_follows_use(db, context, document, agent)
        )
        for source_row, document in rows
    )


def version_sources_are_readable(
    db: Session,
    context: AuthContext | str,
    version: AgentVersion,
    *,
    agent: Agent,
    allow_historical_epoch_for_owner: bool = False,
) -> bool:
    if version.state in {"published", "superseded"}:
        return version.knowledge_snapshot_id is None or snapshot_sources_are_readable(
            db,
            context,
            version.knowledge_snapshot_id,
            agent=agent,
            allow_historical_epoch_for_owner=allow_historical_epoch_for_owner,
        )
    return all(
        can_read_source(db, context, document) for document in _enabled_documents(db, version.id)
    )


def visible_agent(db: Session, context: AuthContext, agent_id: str) -> ScopedAgent:
    agent = db.get(Agent, agent_id)
    if agent is None or teacher_public_agent_hidden_from(db, context, agent):
        raise not_found()
    role = _agent_workspace_role(db, context, agent)
    if role == "owner":
        return ScopedAgent(agent, role)
    current_version = (
        db.get(AgentVersion, agent.current_published_version_id)
        if agent.current_published_version_id
        else None
    )
    if role == "student":
        return ScopedAgent(agent, role)
    if (
        role == "teacher"
        and current_version
        and can_read_version(db, current_version, agent, role, context=context)
    ):
        return ScopedAgent(agent, role)
    raise not_found()


def readable_agent(db: Session, context: AuthContext, agent_id: str) -> ScopedAgent:
    """``visible_agent`` for the read routes, plus an observing teacher."""

    agent = db.get(Agent, agent_id)
    if agent is not None and observes_private_agent(db, context, agent):
        return ScopedAgent(agent, "observer")
    return visible_agent(db, context, agent_id)


def readable_version(db: Session, context: AuthContext, version_id: str) -> ScopedVersion:
    """``visible_version`` for the read routes, plus an observing teacher."""

    row = db.execute(
        select(AgentVersion, Agent)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(AgentVersion.id == version_id)
    ).first()
    if row is not None and observes_private_agent(db, context, row[1]):
        return ScopedVersion(row[0], row[1], "observer")
    return visible_version(db, context, version_id)


def visible_version(db: Session, context: AuthContext, version_id: str) -> ScopedVersion:
    row = db.execute(
        select(AgentVersion, Agent)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(AgentVersion.id == version_id)
    ).first()
    if row is None:
        raise not_found()
    version, agent = row
    if teacher_public_agent_hidden_from(db, context, agent):
        raise not_found()
    role = _agent_workspace_role(db, context, agent)
    if can_read_version(db, version, agent, role, context=context):
        return ScopedVersion(version, agent, cast(str, role))
    if public_agent_editor_role(db, context, agent) in {
        "groupmate",
        "course_teacher",
    } and draft_shared_with_editors(db, version, agent):
        return ScopedVersion(version, agent, role or "student")
    raise not_found()


def visible_snapshot(db: Session, context: AuthContext, snapshot_id: str) -> ScopedSnapshot:
    row = db.execute(
        select(KnowledgeSnapshot, AgentVersion, Agent)
        .join(AgentVersion, AgentVersion.id == KnowledgeSnapshot.agent_version_id)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(KnowledgeSnapshot.id == snapshot_id)
    ).first()
    if row is None:
        raise not_found()
    snapshot, version, agent = row
    if teacher_public_agent_hidden_from(db, context, agent):
        raise not_found()
    if observes_private_agent(db, context, agent):
        if version.state not in {"published", "superseded"}:
            raise not_found()
        return ScopedSnapshot(snapshot, version, agent, "observer")
    role = _agent_workspace_role(db, context, agent)
    if role != "owner" and not can_read_version(db, version, agent, role, context=context):
        raise not_found()
    if version.state not in {"published", "superseded"} or not _workspace_role_can_read_published(
        role, version.state
    ):
        raise not_found()
    if not snapshot_sources_are_readable(
        db,
        context,
        snapshot.id,
        agent=agent,
        allow_historical_epoch_for_owner=role == "owner",
    ):
        raise not_found()
    return ScopedSnapshot(snapshot, version, agent, cast(str, role))


def public_agent_editor_role(db: Session, actor: AuthContext | str, agent: Agent) -> str | None:
    """Who may edit/publish/delete an Agent.

    The creator always ("owner"). A *public*, live Agent is also editable by
    the teachers of its own course ("course_teacher") and by student members
    of its own group ("groupmate"). Private Agents stay creator-only; nobody
    outside the course or group gains anything here.
    """

    user_id = _actor_user_id(actor)
    if agent.deleted_at is not None or agent.owner_user_id is None:
        return None
    role = course_member_role(db, user_id, agent.course_id)
    if role is None:
        return None
    if agent.owner_user_id == user_id:
        return "owner" if _agent_workspace_role(db, user_id, agent) == "owner" else None
    if agent.visibility != "public" or agent.status != "active":
        return None
    if role == "teacher":
        # Teachers meet a student's public Agent once it is published; an
        # unpublished draft stays undiscoverable to them (pre-publication rule).
        if agent.current_published_version_id is None:
            return None
        return "course_teacher"
    if (
        role == "student"
        and agent.group_id is not None
        and scoped_group_role_for_user(db, user_id, agent.group_id) == "student"
    ):
        return "groupmate"
    return None


def draft_shared_with_editors(db: Session, version: AgentVersion, agent: Agent) -> bool:
    """A non-creator editor touches only a draft with no private provenance."""

    if not (
        version.state == "draft"
        and version.draft_visibility == "public"
        and agent.visibility == "public"
        and version.authorization_epoch == agent.authorization_epoch
        and agent.deleted_at is None
    ):
        return False
    return all(
        document.visibility == "public"
        and document.workspace_state == "active"
        and document.course_id == agent.course_id
        for document in _enabled_documents(db, version.id)
    )


def visible_student_version(db: Session, context: AuthContext, version_id: str) -> ScopedVersion:
    row = db.execute(
        select(AgentVersion, Agent)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(AgentVersion.id == version_id)
    ).first()
    if row is None:
        raise not_found()
    version, agent = row
    role = _agent_workspace_role(db, context, agent)
    # Draft writes belong to the publishing account. A public reader stays on visible_version.
    if role == "owner" and can_read_version(db, version, agent, role, context=context):
        return ScopedVersion(version, agent, role)
    editor = public_agent_editor_role(db, context, agent)
    if editor in {"groupmate", "course_teacher"} and (
        draft_shared_with_editors(db, version, agent) or version_is_currently_public(version, agent)
    ):
        return ScopedVersion(version, agent, editor)
    raise not_found()


def visible_student_agent(db: Session, context: AuthContext, agent_id: str) -> ScopedAgent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise not_found()
    role = _agent_workspace_role(db, context, agent)
    if role == "owner":
        return ScopedAgent(agent, role)
    editor = public_agent_editor_role(db, context, agent)
    if editor in {"groupmate", "course_teacher"}:
        return ScopedAgent(agent, editor)
    raise not_found()


def visible_student_document(db: Session, context: AuthContext, document_id: str) -> ScopedDocument:
    document = db.get(KnowledgeDocument, document_id)
    # The library does not grow an observer view. An entered teacher reads a
    # document only when a groupmate could: they own it, or it is public.
    if document is None or not can_read_source(db, context, document):
        raise not_found()
    if document.owner_user_id == context.user.id:
        return ScopedDocument(document, "owner")
    if document.visibility == "public":
        return ScopedDocument(document, "student")
    raise not_found()


def visible_mutable_document(
    db: Session,
    context: AuthContext,
    document_id: str,
    *,
    require_active: bool = True,
) -> ScopedDocument:
    document = db.get(KnowledgeDocument, document_id)
    if document is None or not can_mutate_source(
        db, context, document, require_active=require_active
    ):
        raise not_found()
    return ScopedDocument(document, "owner")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def request_hash(operation: str, actor_id: str, scope: Iterable[str], body: Any) -> str:
    payload = _canonical([operation, actor_id, list(scope), body])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _independent_session(db: Session) -> Session:
    """Open a short-lived transaction on the same Engine as ``db``.

    Idempotency claims and journal transitions must be durable before the
    request transaction performs a file or domain side effect.  A separate
    Session keeps those commits independent while still using the configured
    SQLite connection/pool.
    """

    bind = db.get_bind()
    return Session(bind=bind, autoflush=False, expire_on_commit=False)


def _replay(record: IdempotencyRecord) -> JSONResponse:
    return JSONResponse(
        status_code=record.status_code or 200,
        content=json.loads(record.response_json or "{}"),
    )


def _claim_lookup(
    session: Session,
    context: AuthContext,
    operation: str,
    key: str,
) -> IdempotencyRecord | None:
    return session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_user_id == context.user.id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.key == key,
        )
    )


def claim_idempotency(
    db: Session,
    context: AuthContext,
    operation: str,
    key: str,
    body_hash: str,
    *,
    data_root: Path | None = None,
    takeover_recovery: Callable[[Session, IdempotencyRecord], bool] | None = None,
) -> tuple[IdempotencyRecord, JSONResponse | None]:
    """Atomically claim a keyed command in its own committed transaction.

    Same-hash requests briefly poll a live claim for its committed replay.
    Lease takeover is a compare-and-swap and only happens after any durable
    file journal for the old claim has been recovered.
    """

    if len(key) < 16:
        raise invalid_request("Idempotency-Key must contain at least 16 characters.")

    # The caller only performs authorization/validation reads before the
    # claim.  End that read transaction before a separate writer commits so a
    # SQLite WAL snapshot cannot later fail to upgrade to a write transaction.
    db.rollback()
    poll_deadline = time.monotonic() + 1.0
    while True:
        session = _independent_session(db)
        try:
            existing = _claim_lookup(session, context, operation, key)
            if existing is None:
                timestamp = now_utc()
                record = IdempotencyRecord(
                    id=str(uuid4()),
                    actor_user_id=context.user.id,
                    operation=operation,
                    key=key,
                    request_hash=body_hash,
                    state="pending",
                    claim_token=secrets.token_urlsafe(32),
                    lease_expires_at=timestamp + timedelta(seconds=10),
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(record)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    # Another worker won the unique key race.  Resolve it
                    # below through the same hash/state rules.
                    existing = _claim_lookup(session, context, operation, key)
                else:
                    db.expire_all()
                    claimed = db.get(IdempotencyRecord, record.id)
                    if claimed is None:  # pragma: no cover - defensive DB fault
                        raise invalid_state("The idempotency claim could not be loaded.")
                    return claimed, None

            if existing is None or existing.request_hash != body_hash:
                raise idempotency_conflict()
            if existing.state == "completed" and existing.response_json is not None:
                db.expire_all()
                claimed = db.get(IdempotencyRecord, existing.id)
                if claimed is None:  # pragma: no cover - defensive DB fault
                    raise invalid_state("The idempotency replay could not be loaded.")
                return claimed, _replay(existing)
            timestamp = now_utc()
            if existing.state == "pending" and _utc_datetime(existing.lease_expires_at) > timestamp:
                if time.monotonic() < poll_deadline:
                    # Do not hold the transaction while waiting.  A separate
                    # short read lets the owner commit its final replay.
                    pass
                else:
                    raise conflict(
                        "invalid_state",
                        "An identical request is already in progress; retry shortly.",
                        {"retry_after_seconds": 1},
                    )
            elif existing.state == "pending":
                # Recovery is intentionally explicit.  A stale worker may
                # have promoted an orphan before its lease expired; cleanup
                # must complete before a new token is allowed to run.
                if takeover_recovery is not None and takeover_recovery(session, existing):
                    session.commit()
                    continue

                from app.modules.knowledge.recovery import recover_file_operations

                operations = session.scalars(
                    select(FileOperation).where(
                        FileOperation.idempotency_record_id == existing.id,
                        FileOperation.state.in_(
                            ("prepared", "staged", "promoted", "cleanup_required")
                        ),
                    )
                ).all()
                if operations:
                    if data_root is None:
                        raise invalid_state("The previous request requires recovery before retry.")
                    recover_file_operations(
                        session,
                        data_root,
                        idempotency_record_id=existing.id,
                    )
                    session.commit()
                    continue
                new_token = secrets.token_urlsafe(32)
                new_expiry = timestamp + timedelta(seconds=10)
                changed = session.execute(
                    update(IdempotencyRecord)
                    .where(
                        IdempotencyRecord.id == existing.id,
                        IdempotencyRecord.state == "pending",
                        IdempotencyRecord.request_hash == body_hash,
                        IdempotencyRecord.claim_token == existing.claim_token,
                        IdempotencyRecord.lease_expires_at <= timestamp,
                    )
                    .execution_options(synchronize_session=False)
                    .values(
                        claim_token=new_token,
                        lease_expires_at=new_expiry,
                        updated_at=timestamp,
                    )
                )
                if getattr(changed, "rowcount", 0) == 1:
                    session.commit()
                    db.expire_all()
                    claimed = db.get(IdempotencyRecord, existing.id)
                    if claimed is None:  # pragma: no cover
                        raise invalid_state("The idempotency claim could not be loaded.")
                    return claimed, None
                session.rollback()
            elif existing.state == "abandoned":
                timestamp = now_utc()
                new_token = secrets.token_urlsafe(32)
                changed = session.execute(
                    update(IdempotencyRecord)
                    .where(
                        IdempotencyRecord.id == existing.id,
                        IdempotencyRecord.state == "abandoned",
                        IdempotencyRecord.request_hash == body_hash,
                    )
                    .values(
                        claim_token=new_token,
                        lease_expires_at=timestamp + timedelta(seconds=10),
                        state="pending",
                        updated_at=timestamp,
                    )
                )
                if getattr(changed, "rowcount", 0) == 1:
                    session.commit()
                    db.expire_all()
                    claimed = db.get(IdempotencyRecord, existing.id)
                    if claimed is None:  # pragma: no cover
                        raise invalid_state("The idempotency claim could not be loaded.")
                    return claimed, None
                session.rollback()
        finally:
            session.close()
        if time.monotonic() >= poll_deadline:
            raise conflict(
                "invalid_state",
                "An identical request is already in progress; retry shortly.",
                {"retry_after_seconds": 1},
            )
        time.sleep(0.05)


def finish_idempotency(
    db: Session,
    record: IdempotencyRecord,
    status_code: int,
    payload: Any,
) -> None:
    """Guard final completion by the exact claim token in the final DB tx."""

    response_json = _canonical(payload)
    changed = db.execute(
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.id == record.id,
            IdempotencyRecord.state == "pending",
            IdempotencyRecord.claim_token == record.claim_token,
        )
        .values(
            state="completed",
            status_code=status_code,
            response_json=response_json,
            updated_at=now_utc(),
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        raise invalid_state("The idempotency claim is no longer owned by this request.")
    record.state = "completed"
    record.status_code = status_code
    record.response_json = response_json
    record.updated_at = now_utc()


def abandon_idempotency(db: Session, record: IdempotencyRecord) -> None:
    """Durably abandon a claim that failed before any journal side effect."""

    changed = db.execute(
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.id == record.id,
            IdempotencyRecord.state == "pending",
            IdempotencyRecord.claim_token == record.claim_token,
        )
        .values(state="abandoned", updated_at=now_utc())
    )
    if getattr(changed, "rowcount", 0) == 1:
        db.commit()
    record.state = "abandoned"
    record.updated_at = now_utc()


def abandon_claim(db: Session, record: IdempotencyRecord) -> None:
    """Reload and durably abandon a claim after pre-side-effect rejection."""

    db.rollback()
    current = db.get(IdempotencyRecord, record.id)
    if current is not None:
        abandon_idempotency(db, current)


def create_file_operation(
    db: Session,
    *,
    operation_id: str,
    idempotency_record_id: str | None,
    operation_kind: str,
    entity_id: str,
    request_id: str,
    source_relative_path: str | None,
    target_relative_path: str | None,
    expected_sha256: str | None = None,
    claim_token: str | None = None,
) -> str:
    """Persist a ``prepared`` journal row in an independent commit."""

    timestamp = now_utc()
    session = _independent_session(db)
    try:
        if idempotency_record_id is not None and claim_token is not None:
            owned = session.scalar(
                select(IdempotencyRecord.id).where(
                    IdempotencyRecord.id == idempotency_record_id,
                    IdempotencyRecord.claim_token == claim_token,
                    IdempotencyRecord.state == "pending",
                )
            )
            if owned is None:
                raise invalid_state("The idempotency claim is no longer owned by this request.")
        session.add(
            FileOperation(
                id=operation_id,
                idempotency_record_id=idempotency_record_id,
                operation_kind=operation_kind,
                entity_id=entity_id,
                request_id=request_id,
                source_relative_path=source_relative_path,
                target_relative_path=target_relative_path,
                expected_sha256=expected_sha256,
                state="prepared",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        session.commit()
    finally:
        session.close()
    return operation_id


def transition_file_operation(
    db: Session,
    operation_id: str,
    state: str,
    *,
    expected_state: str | None = None,
    expected_sha256: str | None = None,
    safe_error_code: str | None = None,
    idempotency_record_id: str | None = None,
    claim_token: str | None = None,
) -> None:
    """CAS a durable journal transition and commit it independently."""

    values: dict[str, object] = {"state": state, "updated_at": now_utc()}
    if expected_sha256 is not None:
        values["expected_sha256"] = expected_sha256
    if safe_error_code is not None:
        values["safe_error_code"] = safe_error_code
    session = _independent_session(db)
    try:
        query = update(FileOperation).where(FileOperation.id == operation_id)
        if expected_state is not None:
            query = query.where(FileOperation.state == expected_state)
        if idempotency_record_id is not None and claim_token is not None:
            query = query.where(
                FileOperation.idempotency_record_id == idempotency_record_id,
                exists(
                    select(IdempotencyRecord.id).where(
                        IdempotencyRecord.id == idempotency_record_id,
                        IdempotencyRecord.claim_token == claim_token,
                        IdempotencyRecord.state == "pending",
                    )
                ),
            )
        changed = session.execute(query.values(**values))
        if getattr(changed, "rowcount", 0) != 1:
            session.rollback()
            raise invalid_state("The file operation journal is no longer at the expected boundary.")
        session.commit()
    finally:
        session.close()


def load_file_operation(db: Session, operation_id: str) -> FileOperation:
    operation = db.get(FileOperation, operation_id)
    if operation is None:
        raise invalid_state("The file operation journal could not be loaded.")
    return operation


def _claim_lost_error(db: Session, record: IdempotencyRecord) -> PlatformError:
    """Tell a lapsed lease apart from a real takeover.

    Under DB pool pressure a request can wait longer than its short claim
    lease for a connection.  If the claim is still pending with our token,
    nobody else owns it: answer a retryable 503 so the same Idempotency-Key
    can take the lease over and finish.  A replaced token stays a conflict.
    """

    session = _independent_session(db)
    try:
        ours = session.scalar(
            select(IdempotencyRecord.id).where(
                IdempotencyRecord.id == record.id,
                IdempotencyRecord.claim_token == record.claim_token,
                IdempotencyRecord.state == "pending",
            )
        )
    finally:
        session.close()
    if ours is not None:
        return PlatformError(
            "idempotency_lease_expired",
            "The server was busy and this request paused too long. Try again.",
            503,
            {"retryable": True, "retry_after_seconds": 5},
        )
    return invalid_state("The idempotency claim is no longer owned by this request.")


def assert_claim_owned(db: Session, record: IdempotencyRecord) -> None:
    """Fail before a side effect if a lease was taken over by another worker."""

    session = _independent_session(db)
    try:
        owned = session.scalar(
            select(IdempotencyRecord.id).where(
                IdempotencyRecord.id == record.id,
                IdempotencyRecord.claim_token == record.claim_token,
                IdempotencyRecord.state == "pending",
                IdempotencyRecord.lease_expires_at > now_utc(),
            )
        )
    finally:
        session.close()
    if owned is None:
        raise _claim_lost_error(db, record)


def renew_idempotency_lease(
    db: Session,
    record: IdempotencyRecord,
    *,
    lease_seconds: int = 900,
) -> datetime:
    """Extend an actively owned claim before bounded Provider work.

    The CAS runs in its own short transaction and never surrounds network I/O.
    An expired or replaced token cannot be revived.  Wave 4 Embedding permits
    at most twenty bounded requests, so fifteen minutes is the hard renewal
    ceiling rather than an open-ended heartbeat.
    """

    if isinstance(lease_seconds, bool) or not 30 <= lease_seconds <= 900:
        raise ValueError("idempotency lease renewal must be between 30 and 900 seconds")
    timestamp = now_utc()
    new_expiry = timestamp + timedelta(seconds=lease_seconds)
    session = _independent_session(db)
    try:
        changed = session.execute(
            update(IdempotencyRecord)
            .where(
                IdempotencyRecord.id == record.id,
                IdempotencyRecord.state == "pending",
                IdempotencyRecord.claim_token == record.claim_token,
                IdempotencyRecord.lease_expires_at > timestamp,
            )
            .values(lease_expires_at=new_expiry, updated_at=timestamp)
        )
        if getattr(changed, "rowcount", 0) != 1:
            session.rollback()
            lost = True
        else:
            session.commit()
            lost = False
    finally:
        session.close()
    if lost:
        raise _claim_lost_error(db, record)
    db.expire_all()
    return new_expiry


def saga_checkpoint(boundary: str) -> None:
    """Crash-injection seam used by deterministic recovery tests.

    Production has no behavior here.  Tests may replace this narrow seam to
    terminate a request at every durable journal boundary without changing
    business code or touching the filesystem outside the operation's UUID
    tree.
    """

    del boundary


def recover_operation_now(db: Session, data_root: Path, operation_id: str) -> None:
    """Synchronously recover one operation after an expected business error."""

    from app.modules.knowledge.recovery import recover_file_operations

    # The caller commonly rejected a stale CAS after a scoped read.  Close
    # that read snapshot before opening the independent recovery writer; WAL
    # cannot upgrade a live reader while another publication is committing.
    db.rollback()
    for attempt in range(3):
        session = _independent_session(db)
        try:
            recover_file_operations(session, data_root, operation_id=operation_id)
            session.commit()
            return
        except OperationalError:
            session.rollback()
            if attempt == 2:
                raise
            time.sleep(0.05 * (attempt + 1))
        finally:
            session.close()


def _avatar(value: str) -> AvatarConfig:
    try:
        parsed = json.loads(value)
        from app.modules.avatars import validate_avatar_config

        return validate_avatar_config(parsed)
    except Exception:
        return AvatarConfig(
            template_id="wave1-default-head",
            material_theme="demo",
            eye_color=None,
            default_expression="neutral",
            expression_strength="medium",
            motion_style="calm",
        )


def _document_dto(
    document: KnowledgeDocument,
    *,
    can_manage_visibility: bool = False,
) -> KnowledgeDocumentDTO:
    return KnowledgeDocumentDTO(
        id=UUID(document.id),
        group_id=UUID(document.group_id) if document.group_id else None,
        course_id=UUID(document.course_id),
        ownership_scope=cast(Literal["group", "personal"], document.ownership_scope),
        visibility=cast(Literal["private", "public"], document.visibility),
        can_manage_visibility=can_manage_visibility,
        source_filename=document.source_filename,
        source_owner_role=cast(Literal["student", "teacher"], document.source_owner_role),
        char_count=document.char_count,
        authorization_epoch=document.authorization_epoch,
        content_hash=document.content_hash,
        index_revision=document.index_revision,
        index_status=cast(Literal["pending", "indexing", "ready", "failed"], document.index_status),
        workspace_state=cast(Literal["active", "hidden"], document.workspace_state),
        safe_error_code=document.safe_error_code,
        created_at=document.created_at,
    )


def _enabled_documents(db: Session, version_id: str) -> list[KnowledgeDocument]:
    return list(
        db.scalars(
            select(KnowledgeDocument)
            .join(AgentVersionDocument, AgentVersionDocument.document_id == KnowledgeDocument.id)
            .where(
                AgentVersionDocument.agent_version_id == version_id,
                AgentVersionDocument.enabled.is_(True),
            )
            .order_by(AgentVersionDocument.order_index)
        ).all()
    )


def blockers(db: Session, version: AgentVersion, agent: Agent) -> list[str]:
    result: list[str] = []
    if not version.agent_md.strip():
        result.append("agent_md_missing")
    docs = _enabled_documents(db, version.id)
    statuses = {document.index_status for document in docs}
    if statuses & {"pending", "indexing"}:
        result.append("rag_index_pending")
    if "failed" in statuses:
        result.append("rag_index_failed")
    try:
        from app.modules.avatars import validate_avatar_config

        validate_avatar_config(json.loads(version.avatar_config_json))
    except Exception:
        result.append("avatar_missing")
    return result


def publish_without_snapshot(
    db: Session,
    version: AgentVersion,
    agent: Agent,
    *,
    expected_revision: int,
) -> None:
    """Publish an owner-authorized version whose enabled source set is empty."""

    blockers_list = blockers(db, version, agent)
    if blockers_list:
        raise publish_blockers(blockers_list)
    if _enabled_documents(db, version.id):
        raise invalid_state("A version with enabled sources needs a SnapshotBuild.")
    captured_pointer = agent.current_published_version_id

    db.rollback()
    begin_immediate(db)
    current_version = db.get(AgentVersion, version.id)
    current_agent = db.get(Agent, agent.id)
    if current_version is None or current_agent is None:
        raise not_found()
    if (
        current_version.state != "draft"
        or current_version.revision != expected_revision
        or current_agent.status != "active"
        or current_agent.deleted_at is not None
        or current_agent.current_published_version_id != captured_pointer
        or _enabled_documents(db, current_version.id)
    ):
        raise stale_revision(current_version.revision)

    timestamp = now_utc()
    changed = db.execute(
        update(AgentVersion)
        .where(
            AgentVersion.id == current_version.id,
            AgentVersion.state == "draft",
            AgentVersion.revision == expected_revision,
        )
        .values(
            state="published",
            revision=AgentVersion.revision + 1,
            knowledge_snapshot_id=None,
            published_visibility=current_agent.visibility,
            authorization_epoch=current_agent.authorization_epoch,
            published_at=timestamp,
            updated_at=timestamp,
            persona_confirmation_revision=case(
                (
                    AgentVersion.persona_confirmation_revision.is_not(None),
                    AgentVersion.revision + 1,
                ),
                else_=None,
            ),
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        raise stale_revision(current_version.revision)

    if captured_pointer:
        previous = db.scalar(
            select(AgentVersion).where(
                AgentVersion.id == captured_pointer,
                AgentVersion.agent_id == current_agent.id,
                AgentVersion.state == "published",
            )
        )
        if previous is None:
            raise invalid_state("The current published version is unavailable.")
        previous.state = "superseded"
        previous.updated_at = timestamp

    pointer_condition = (
        Agent.current_published_version_id.is_(None)
        if captured_pointer is None
        else Agent.current_published_version_id == captured_pointer
    )
    pointer_changed = db.execute(
        update(Agent)
        .where(Agent.id == current_agent.id, pointer_condition)
        .values(
            current_published_version_id=current_version.id,
            updated_at=timestamp,
        )
    )
    if getattr(pointer_changed, "rowcount", 0) != 1:
        raise invalid_state("The current published version changed during publication.")
    db.refresh(current_version)
    db.refresh(current_agent)
    version.state = current_version.state
    version.revision = current_version.revision
    version.knowledge_snapshot_id = None
    version.published_visibility = current_version.published_visibility
    version.authorization_epoch = current_version.authorization_epoch
    version.published_at = current_version.published_at
    version.updated_at = current_version.updated_at
    agent.current_published_version_id = current_agent.current_published_version_id
    agent.updated_at = current_agent.updated_at


def version_dto(
    db: Session,
    version: AgentVersion,
    agent: Agent,
    settings: Settings | None = None,
    *,
    include_private_sources: bool = False,
) -> AgentVersionDTO:
    docs = [
        document
        for document in _enabled_documents(db, version.id)
        if document.visibility == "public"
        or (include_private_sources and document.owner_user_id == agent.owner_user_id)
    ]
    from app.modules.voices.preview import resolve_effective_voice_profile

    effective_voice = resolve_effective_voice_profile(
        db,
        version.voice_profile_id,
        agent.group_id,
        settings or db.info.get("maya_settings") or get_settings(),
        owner_user_id=agent.owner_user_id,
    )
    persona_spec: PersonaSpecVersion | None = None
    if version.persona_spec_json:
        try:
            persona_spec = parse_persona_spec(version.persona_spec_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            # A malformed stored Persona is not exposed as a partially trusted
            # browser DTO; publication/confirmation eligibility remains false.
            persona_spec = None
    persona_diagnostics: list[PersonaDiagnostic] = []
    if version.persona_diagnostics_json:
        try:
            raw_diagnostics = json.loads(version.persona_diagnostics_json)
            if isinstance(raw_diagnostics, list):
                persona_diagnostics = [
                    PersonaDiagnostic.model_validate(item)
                    for item in raw_diagnostics
                    if isinstance(item, dict)
                ]
        except (TypeError, ValueError, json.JSONDecodeError):
            persona_diagnostics = []
    persona_compiler_version: PersonaCompilerVersion | None = (
        cast(PersonaCompilerVersion, version.persona_compiler_version)
        if version.persona_compiler_version in {"persona_template_v1", "persona_template_v2"}
        else None
    )
    return AgentVersionDTO(
        id=UUID(version.id),
        agent_id=UUID(version.agent_id),
        version_label=agent_version_label(version.version_seq),
        state=cast(Literal["draft", "published", "superseded"], version.state),
        revision=version.revision,
        agent_md=version.agent_md,
        raw_agent_md_hash=version.raw_agent_md_hash,
        persona_spec=persona_spec,
        persona_spec_hash=version.persona_spec_hash,
        persona_compiler_version=persona_compiler_version,
        persona_diagnostics=persona_diagnostics,
        persona_confirmation_revision=version.persona_confirmation_revision,
        student_confirmed_at=version.student_confirmed_at,
        persona_confirmed=is_persona_confirmed(version),
        avatar_config=_avatar(version.avatar_config_json),
        voice_profile_id=UUID(version.voice_profile_id) if version.voice_profile_id else None,
        effective_voice_profile_id=(
            UUID(effective_voice.profile_id) if effective_voice.profile_id else None
        ),
        voice_fallback_active=effective_voice.fallback_active,
        knowledge_snapshot_id=(
            UUID(version.knowledge_snapshot_id) if version.knowledge_snapshot_id else None
        ),
        published_visibility=cast(
            Literal["private", "public"] | None, version.published_visibility
        ),
        enabled_documents=[
            _document_dto(
                document,
                can_manage_visibility=(
                    include_private_sources and document.owner_user_id == agent.owner_user_id
                ),
            )
            for document in docs
        ],
        publish_blockers=blockers(db, version, agent) if version.state == "draft" else [],
    )


def _current_version_label(db: Session, agent: Agent) -> str | None:
    from app.core.version_label import agent_version_label

    if not agent.current_published_version_id:
        return None
    seq = db.scalar(
        select(AgentVersion.version_seq).where(
            AgentVersion.id == agent.current_published_version_id
        )
    )
    return agent_version_label(seq) if seq is not None else None


def agent_summary(
    db: Session,
    agent: Agent,
    *,
    include_draft: bool = True,
    role: str | None = "owner",
    context: AuthContext | None = None,
) -> AgentSummary:
    draft = (
        db.scalar(
            select(AgentVersion).where(
                AgentVersion.agent_id == agent.id,
                AgentVersion.state == "draft",
            )
        )
        if include_draft
        else None
    )
    if (
        draft is not None
        and role not in {"owner", "observer"}
        and not can_read_version(db, draft, agent, role, context=context)
    ):
        draft = None
    editor = (
        public_agent_editor_role(db, context, agent)
        if context is not None
        else ("owner" if role == "owner" else None)
    )
    if draft is None and include_draft and editor in {"groupmate", "course_teacher"}:
        shared = db.scalar(
            select(AgentVersion).where(
                AgentVersion.agent_id == agent.id, AgentVersion.state == "draft"
            )
        )
        if shared is not None and draft_shared_with_editors(db, shared, agent):
            draft = shared
    audit = db.get(AgentEditAudit, agent.id)
    # The hover tooltip names the latest editor; before anyone else edits,
    # that is the creator.
    last_editor_id = (
        audit.last_edited_by_user_id
        if audit is not None and audit.last_edited_by_user_id
        else agent.owner_user_id
    )
    last_editor = (
        db.scalar(select(User.display_name).where(User.id == last_editor_id))
        if last_editor_id
        else None
    )
    return AgentSummary(
        id=UUID(agent.id),
        group_id=UUID(agent.group_id) if agent.group_id else None,
        course_id=UUID(agent.course_id),
        ownership_scope=cast(Literal["group", "personal"], agent.ownership_scope),
        visibility=cast(Literal["private", "public"], agent.visibility),
        can_edit=editor is not None,
        can_delete=editor is not None,
        is_creator=context is not None and agent.owner_user_id == context.user.id,
        last_edited_by_name=last_editor,
        last_edited_at=audit.last_edited_at if audit is not None else None,
        current_version_label=_current_version_label(db, agent),
        name=agent.name,
        description=agent.description,
        metadata_revision=agent.metadata_revision,
        status=cast(Literal["active", "archived"], agent.status),
        current_published_version_id=(
            UUID(agent.current_published_version_id) if agent.current_published_version_id else None
        ),
        current_draft_version_id=UUID(draft.id) if draft else None,
    )


def agent_detail(
    db: Session,
    agent: Agent,
    role: str,
    *,
    context: AuthContext | None = None,
) -> AgentDetail:
    query = select(AgentVersion).where(AgentVersion.agent_id == agent.id)
    if role == "teacher":
        query = query.where(AgentVersion.state.in_(("published", "superseded")))
    versions = list(db.scalars(query.order_by(AgentVersion.version_seq)).all())
    if role != "owner":
        versions = [
            version
            for version in versions
            if can_read_version(db, version, agent, role, context=context)
        ]
    if role == "teacher" and not versions:
        raise not_found()
    return AgentDetail(
        **agent_summary(
            db,
            agent,
            include_draft=role in {"owner", "student", "observer"},
            role=role,
            context=context,
        ).model_dump(),
        versions=[
            version_dto(
                db,
                version,
                agent,
                include_private_sources=role in {"owner", "observer"},
            )
            for version in versions
        ],
    )


def parse_json_payload_hash(
    operation: str, context: AuthContext, scope: Iterable[str], body: Any
) -> str:
    return request_hash(operation, context.user.id, scope, body)


def _source_marker(document: KnowledgeDocument) -> str:
    return f"<!-- source: {document.source_filename}; document_id: {document.id} -->"


def normalized_document_content(data_root: Path, document: KnowledgeDocument) -> str:
    stored = document.stored_file
    if stored is None:
        raise not_found()
    raw = read_contained(data_root, stored.relative_path)
    try:
        return normalize_markdown(document.source_filename, raw).normalized
    except ValueError:
        raise PlatformError(
            "provider_unavailable", "The service is temporarily unavailable.", 503
        ) from None


def combined_markdown(db: Session, version_id: str, data_root: Path) -> str:
    docs = _enabled_documents(db, version_id)
    return "\n\n".join(
        f"{_source_marker(document)}\n{normalized_document_content(data_root, document)}"
        for document in docs
    )


def rag_preview(db: Session, version: AgentVersion, data_root: Path) -> RagPreview:
    docs = _enabled_documents(db, version.id)
    statuses = {document.index_status for document in docs}
    state = (
        "failed"
        if "failed" in statuses
        else "pending"
        if statuses & {"pending", "indexing"}
        else "ready"
    )
    return RagPreview(
        version_id=UUID(version.id),
        total_char_count=sum(document.char_count for document in docs),
        limit=None,
        document_count=len(docs),
        index_status=cast(Literal["pending", "ready", "failed"], state),
        combined_markdown=combined_markdown(db, version.id, data_root),
    )


def replace_document_chunks(db: Session, document: KnowledgeDocument, chunks: Any) -> None:
    """Atomically swap a complete, already-computed chunk replacement."""

    db.execute(
        delete(KnowledgeDocumentChunk).where(KnowledgeDocumentChunk.document_id == document.id)
    )
    for chunk in chunks:
        db.add(
            KnowledgeDocumentChunk(
                id=str(uuid4()),
                document_id=document.id,
                chunk_index=chunk.index,
                chunk_text=chunk.text,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                embedding_blob=chunk.embedding,
                embedding_dimension=EMBEDDING_DIMENSION,
                embedding_key=EMBEDDING_KEY,
            )
        )


def document_file_content(data_root: Any, document: KnowledgeDocument) -> bytes:
    stored = document.stored_file
    if stored is None:
        raise not_found()
    return read_contained(data_root, stored.relative_path)


def job_dto(job: Job) -> JobStatus:
    return JobStatus(
        id=UUID(job.id),
        kind=job.operation,
        status=cast(Literal["pending", "running", "completed", "failed", "interrupted"], job.state),
        safe_error_code=job.safe_error_code,
    )


def retrieval_response(
    db: Session,
    version: AgentVersion,
    message: str,
    *,
    mock_retrieval_policy_id: str = MOCK_LEXICAL_ANCHOR_POLICY_ID,
) -> TestChatResponse:
    """Run the non-persistent draft test against the current Mock policy.

    The student message is the authoritative topic anchor for this draft-only
    surface.  Published snapshot bytes and chunk vectors are read as-is.
    """

    if mock_retrieval_policy_id != MOCK_LEXICAL_ANCHOR_POLICY_ID:
        raise ValueError("unsupported Mock retrieval policy")
    lexical_anchor = MockLexicalAnchorV2.from_topic(message)
    docs = _enabled_documents(db, version.id)
    relations = {
        relation.document_id: relation
        for relation in db.scalars(
            select(AgentVersionDocument).where(AgentVersionDocument.agent_version_id == version.id)
        ).all()
        if relation.enabled
    }
    query = query_embedding(message)
    import struct

    query_values = struct.unpack("<256f", query)
    ranked: list[tuple[float, int, int, str, KnowledgeDocumentChunk, KnowledgeDocument]] = []
    for document in docs:
        if document.index_status != "ready":
            continue
        order = relations[document.id].order_index
        for chunk in db.scalars(
            select(KnowledgeDocumentChunk)
            .where(KnowledgeDocumentChunk.document_id == document.id)
            .order_by(KnowledgeDocumentChunk.chunk_index)
        ).all():
            if (
                chunk.embedding_dimension != EMBEDDING_DIMENSION
                or chunk.embedding_key != EMBEDDING_KEY
                or len(chunk.embedding_blob) != 4 * EMBEDDING_DIMENSION
            ):
                raise PlatformError(
                    "provider_unavailable", "The service is temporarily unavailable.", 503
                )
            values = struct.unpack("<256f", chunk.embedding_blob)
            score = sum(a * b for a, b in zip(query_values, values, strict=True))
            ranked.append((score, order, chunk.chunk_index, chunk.id, chunk, document))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    top = [item for item in ranked if lexical_anchor.accepts(item[4].chunk_text)][:6]
    selected = [item for item in top if item[0] >= 0.20]
    if not selected:
        selected = [item for item in top if item[0] >= 0.08]
    if not selected:
        return TestChatResponse(
            answer=(
                "No relevant passage was found in this draft knowledge base. "
                "This Mock test cannot provide a factual answer without evidence."
            ),
            retrieval_status="no_match",
            grounding_mode="general_reasoning",
            sources=[],
        )
    best = selected[0]
    document = best[5]
    return TestChatResponse(
        answer=f"Mock grounded excerpt from {document.source_filename}: {best[4].chunk_text[:320]}",
        retrieval_status="matched",
        grounding_mode="rag_grounded",
        sources=[
            RetrievalSource(source_filename=item[5].source_filename, chunk_id=UUID(item[4].id))
            for item in selected
        ],
    )


def snapshot_dto(db: Session, snapshot: KnowledgeSnapshot) -> KnowledgeSnapshotDTO:
    docs = list(
        db.scalars(
            select(SnapshotDocument)
            .where(SnapshotDocument.snapshot_id == snapshot.id)
            .order_by(SnapshotDocument.order_index)
        ).all()
    )
    return KnowledgeSnapshotDTO(
        id=UUID(snapshot.id),
        agent_version_id=UUID(snapshot.agent_version_id),
        content_hash=snapshot.content_hash,
        total_char_count=snapshot.total_char_count,
        documents=[
            SnapshotDocumentDTO(
                id=UUID(document.id),
                source_filename=document.source_filename,
                char_count=document.char_count,
                order_index=document.order_index,
            )
            for document in docs
        ],
        created_at=snapshot.created_at,
    )


def create_snapshot(
    db: Session,
    data_root: Any,
    version: AgentVersion,
    agent: Agent,
    *,
    expected_revision: int | None = None,
    idempotency_record_id: str | None = None,
    claim_token: str | None = None,
    embedding_candidate: SnapshotPublishCandidateV1 | None = None,
    provider_operation_ids: tuple[str, ...] = (),
) -> KnowledgeSnapshot:
    expected = version.revision if expected_revision is None else expected_revision
    blockers_list = blockers(db, version, agent)
    if blockers_list:
        raise publish_blockers(blockers_list)
    selected = _enabled_documents(db, version.id)
    if not selected:
        raise invalid_state("A version without sources must publish without a Snapshot.")
    captured_current_pointer = agent.current_published_version_id
    vector_by_chunk: dict[str, tuple[float, ...]] = {}
    if embedding_candidate is not None:
        build = embedding_candidate.build
        if (
            embedding_candidate.agent_version_id != version.id
            or build.draft_revision != expected
            or build.persona_spec_hash != markdown_hash(version.agent_md)
            or not provider_operation_ids
        ):
            raise invalid_state("The confirmed embedding build no longer matches this draft.")
        if len(embedding_candidate.vectors) != len(build.chunks):
            raise invalid_state("The embedding build vector set is incomplete.")
        vector_by_chunk = dict(
            zip(embedding_candidate.chunk_ids, embedding_candidate.vectors, strict=True)
        )
    else:
        build = None

    # Capture all mutable inputs and chunk payloads before staging.  Every
    # item is revalidated after the file promotion and again in the final DB
    # transaction, so a changed draft/document cannot publish a mixed
    # snapshot.
    relation_rows = list(
        db.scalars(
            select(AgentVersionDocument)
            .where(AgentVersionDocument.agent_version_id == version.id)
            .order_by(AgentVersionDocument.order_index, AgentVersionDocument.document_id)
        ).all()
    )
    relation_capture = [
        (row.document_id, bool(row.enabled), row.order_index) for row in relation_rows
    ]
    captured: list[dict[str, Any]] = []
    for order, document in enumerate(selected):
        source_bytes = document_file_content(data_root, document)
        source_sha = hashlib.sha256(source_bytes).hexdigest()
        if document.stored_file is None or source_sha != document.stored_file.sha256:
            raise invalid_state("A source Markdown document failed integrity verification.")
        try:
            normalized = normalize_markdown(document.source_filename, source_bytes).normalized
        except ValueError:
            raise PlatformError(
                "provider_unavailable", "The service is temporarily unavailable.", 503
            ) from None
        if build is None:
            chunks = list(
                db.scalars(
                    select(KnowledgeDocumentChunk)
                    .where(KnowledgeDocumentChunk.document_id == document.id)
                    .order_by(KnowledgeDocumentChunk.chunk_index)
                ).all()
            )
            captured_chunks = [
                (
                    str(uuid4()),
                    chunk.chunk_index,
                    chunk.chunk_text,
                    chunk.start_offset,
                    chunk.end_offset,
                    chunk.embedding_blob,
                    chunk.embedding_dimension,
                    chunk.embedding_key,
                )
                for chunk in chunks
            ]
        else:
            assert embedding_candidate is not None
            if order >= len(build.documents):
                raise invalid_state("The embedding build document order changed.")
            build_document = build.documents[order]
            if (
                build_document.document_id != document.id
                or build_document.source_filename != source_version_filename(db, document)
                or build_document.order_index != order
                or build_document.normalized_text != normalized
                or build_document.source_sha256 != source_sha
            ):
                raise invalid_state("A source document changed after embedding confirmation.")
            captured_chunks = []
            for chunk in build_document.chunks:
                vector = vector_by_chunk.get(chunk.chunk_id)
                if vector is None:
                    raise invalid_state("The embedding build vector set is incomplete.")
                captured_chunks.append(
                    (
                        chunk.chunk_id,
                        chunk.chunk_index,
                        chunk.text,
                        chunk.start_offset,
                        chunk.end_offset,
                        struct.pack(f"<{len(vector)}f", *vector),
                        embedding_candidate.dimension,
                        embedding_candidate.model_key,
                    )
                )
        captured.append(
            {
                "document": document,
                "source_bytes": source_bytes,
                "source_sha": source_sha,
                "normalized": normalized,
                "index_revision": document.index_revision,
                "content_hash": document.content_hash,
                "authorization_epoch": document.authorization_epoch,
                "snapshot_document_id": str(uuid4()),
                "frozen_file_id": str(uuid4()),
                "chunks": captured_chunks,
                "order": order,
            }
        )
    combined = "\n\n".join(
        f"{_source_marker(item['document'])}\n{item['normalized']}" for item in captured
    )
    combined_bytes = combined.encode("utf-8")
    combined_sha = hashlib.sha256(combined_bytes).hexdigest()
    timestamp = now_utc()
    snapshot_id = (
        embedding_candidate.knowledge_snapshot_id
        if embedding_candidate is not None
        else str(uuid4())
    )
    operation_id = str(uuid4())
    staging_relative = f"tmp/publish/{operation_id}"
    target_relative = f"snapshots/{snapshot_id}"
    snapshot_relative = f"{target_relative}/rag.md"
    try:
        # Independent durable journal boundary: prepared.
        create_file_operation(
            db,
            operation_id=operation_id,
            idempotency_record_id=idempotency_record_id,
            operation_kind="snapshot_publish",
            entity_id=snapshot_id,
            request_id=str(uuid4()),
            source_relative_path=staging_relative,
            target_relative_path=target_relative,
            expected_sha256=combined_sha,
            claim_token=claim_token,
        )
        saga_checkpoint("publish.prepared")

        if idempotency_record_id is not None and claim_token is not None:
            record = db.get(IdempotencyRecord, idempotency_record_id)
            if record is None:
                raise invalid_state("The idempotency claim could not be loaded.")
            assert_claim_owned(db, record)
        stage_atomic(data_root, f"{staging_relative}/rag.md", combined_bytes)
        verify_staged(data_root, f"{staging_relative}/rag.md", combined_sha, len(combined_bytes))
        for item in captured:
            stage_relative = f"{staging_relative}/documents/{item['snapshot_document_id']}.md"
            stage_atomic(data_root, stage_relative, item["source_bytes"])
            verify_staged(
                data_root,
                stage_relative,
                item["source_sha"],
                len(item["source_bytes"]),
            )
        transition_file_operation(
            db,
            operation_id,
            "staged",
            expected_state="prepared",
            expected_sha256=combined_sha,
            idempotency_record_id=idempotency_record_id,
            claim_token=claim_token,
        )
        saga_checkpoint("publish.staged")

        for item in captured:
            current = document_file_content(data_root, item["document"])
            if hashlib.sha256(current).hexdigest() != item["source_sha"]:
                raise invalid_state("A source Markdown document changed during publication.")
        if idempotency_record_id is not None and claim_token is not None:
            record = db.get(IdempotencyRecord, idempotency_record_id)
            if record is None:
                raise invalid_state("The idempotency claim could not be loaded.")
            assert_claim_owned(db, record)
        promote_atomic(data_root, staging_relative, target_relative)
        transition_file_operation(
            db,
            operation_id,
            "promoted",
            expected_state="staged",
            idempotency_record_id=idempotency_record_id,
            claim_token=claim_token,
        )
        saga_checkpoint("publish.promoted")
        verify_staged(data_root, f"{target_relative}/rag.md", combined_sha, len(combined_bytes))
        for item in captured:
            verify_staged(
                data_root,
                f"{target_relative}/documents/{item['snapshot_document_id']}.md",
                item["source_sha"],
                len(item["source_bytes"]),
            )

        # Final transaction revalidates the complete captured relation and
        # source/index state before inserting immutable snapshot rows.
        db.rollback()
        begin_immediate(db)
        if idempotency_record_id is not None and claim_token is not None:
            record = db.get(IdempotencyRecord, idempotency_record_id)
            if record is None:
                raise invalid_state("The idempotency claim could not be loaded.")
            assert_claim_owned(db, record)
        final_version = db.get(AgentVersion, version.id)
        final_agent = db.get(Agent, agent.id)
        if final_version is None or final_agent is None:
            raise not_found()
        if (
            final_version.state != "draft"
            or final_version.revision != expected
            or final_agent.status != "active"
            or final_agent.current_published_version_id != captured_current_pointer
        ):
            raise stale_revision(final_version.revision)
        final_relations = list(
            db.scalars(
                select(AgentVersionDocument)
                .where(AgentVersionDocument.agent_version_id == final_version.id)
                .order_by(AgentVersionDocument.order_index, AgentVersionDocument.document_id)
            ).all()
        )
        if [
            (row.document_id, bool(row.enabled), row.order_index) for row in final_relations
        ] != relation_capture:
            raise invalid_state("The enabled document set changed during publication.")
        final_documents = {
            document.id: document
            for document in db.scalars(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.id.in_([item["document"].id for item in captured])
                )
            ).all()
        }
        for item in captured:
            final_document = final_documents.get(item["document"].id)
            if (
                final_document is None
                or final_document.index_status != "ready"
                or final_document.index_revision != item["index_revision"]
                or final_document.content_hash != item["content_hash"]
                or final_document.authorization_epoch != item["authorization_epoch"]
                or final_document.workspace_state != "active"
            ):
                raise invalid_state("A source index changed during publication.")
            current = document_file_content(data_root, final_document)
            current_sha = hashlib.sha256(current).hexdigest()
            if (
                current_sha != item["source_sha"]
                or final_document.stored_file is None
                or current_sha != final_document.stored_file.sha256
            ):
                raise invalid_state("A source Markdown document changed during publication.")

        changed = db.execute(
            update(AgentVersion)
            .where(
                AgentVersion.id == final_version.id,
                AgentVersion.state == "draft",
                AgentVersion.revision == expected,
            )
            .values(
                state="published",
                revision=AgentVersion.revision + 1,
                knowledge_snapshot_id=snapshot_id,
                published_visibility=final_agent.visibility,
                authorization_epoch=final_agent.authorization_epoch,
                published_at=timestamp,
                updated_at=timestamp,
                # Confirmation is bound to the immutable published revision.
                # Publishing increments the draft revision, so carry the
                # exact confirmation forward atomically instead of violating
                # the all-or-none/revision check constraint.
                persona_confirmation_revision=case(
                    (
                        AgentVersion.persona_confirmation_revision.is_not(None),
                        AgentVersion.revision + 1,
                    ),
                    else_=None,
                ),
            )
        )
        if getattr(changed, "rowcount", 0) != 1:
            current_revision = db.scalar(
                select(AgentVersion.revision).where(AgentVersion.id == final_version.id)
            )
            raise stale_revision(current_revision)
        db.refresh(final_version)
        db.refresh(final_agent)

        snapshot_file_id = str(uuid4())
        db.add(
            StoredFile(
                id=snapshot_file_id,
                kind="snapshot_rag",
                relative_path=snapshot_relative,
                sha256=combined_sha,
                size_bytes=len(combined_bytes),
                state="active",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        snapshot = KnowledgeSnapshot(
            id=snapshot_id,
            agent_version_id=final_version.id,
            stored_file_id=snapshot_file_id,
            content_hash=combined_sha,
            total_char_count=sum(item["document"].char_count for item in captured),
            embedding_key=(
                embedding_candidate.model_key if embedding_candidate is not None else EMBEDDING_KEY
            ),
            embedding_provider=(
                embedding_candidate.embedding_provider
                if embedding_candidate is not None
                else "mock"
            ),
            embedding_region=(
                embedding_candidate.embedding_region if embedding_candidate is not None else "local"
            ),
            embedding_dimension=(
                embedding_candidate.dimension
                if embedding_candidate is not None
                else EMBEDDING_DIMENSION
            ),
            embedding_policy_version=(
                embedding_candidate.policy_version
                if embedding_candidate is not None
                else "w4-mock-v1"
            ),
            chunking_json=(
                json.dumps(
                    {
                        "version": embedding_candidate.build.chunking_version,
                        "dimension": embedding_candidate.dimension,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if embedding_candidate is not None
                else json.dumps(
                    {
                        "version": DEFAULT_CHUNKING_VERSION,
                        "token_target": 600,
                        "token_hard": 800,
                        "overlap": 100,
                        "max_chunk_utf8_bytes": MAX_CHUNK_UTF8_BYTES,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
            created_at=timestamp,
        )
        db.add(snapshot)
        db.flush()
        db.add(
            FileReference(
                id=str(uuid4()),
                stored_file_id=snapshot_file_id,
                owner_type="knowledge_snapshot",
                owner_id=snapshot.id,
                purpose="rag",
                created_at=timestamp,
            )
        )
        for item in captured:
            frozen_relative = f"{target_relative}/documents/{item['snapshot_document_id']}.md"
            db.add(
                StoredFile(
                    id=item["frozen_file_id"],
                    kind="snapshot_source",
                    relative_path=frozen_relative,
                    sha256=item["source_sha"],
                    size_bytes=len(item["source_bytes"]),
                    state="active",
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
            db.flush()
            db.add(
                SnapshotDocument(
                    id=item["snapshot_document_id"],
                    snapshot_id=snapshot.id,
                    document_id=item["document"].id,
                    stored_file_id=item["frozen_file_id"],
                    source_filename=item["document"].source_filename,
                    char_count=item["document"].char_count,
                    order_index=item["order"],
                    source_authorization_epoch=item["authorization_epoch"],
                )
            )
            db.flush()
            db.add(
                FileReference(
                    id=str(uuid4()),
                    stored_file_id=item["frozen_file_id"],
                    owner_type="snapshot_document",
                    owner_id=item["snapshot_document_id"],
                    purpose="source",
                    created_at=timestamp,
                )
            )
            for (
                chunk_id,
                chunk_index,
                chunk_text,
                start_offset,
                end_offset,
                embedding_blob,
                embedding_dimension,
                embedding_key,
            ) in item["chunks"]:
                db.add(
                    KnowledgeChunk(
                        id=chunk_id,
                        snapshot_id=snapshot.id,
                        snapshot_document_id=item["snapshot_document_id"],
                        document_id=item["document"].id,
                        chunk_index=chunk_index,
                        chunk_text=chunk_text,
                        start_offset=start_offset,
                        end_offset=end_offset,
                        embedding_blob=embedding_blob,
                        embedding_dimension=embedding_dimension,
                        embedding_key=embedding_key,
                    )
                )
        if embedding_candidate is not None:
            for provider_operation_id in provider_operation_ids:
                operation_changed = db.execute(
                    update(ProviderOperation)
                    .where(
                        ProviderOperation.id == provider_operation_id,
                        ProviderOperation.scope_id == embedding_candidate.build.build_id,
                        ProviderOperation.provider_operation == "embedding",
                        ProviderOperation.build_manifest_hash
                        == embedding_candidate.build_manifest_hash,
                        ProviderOperation.model_key == embedding_candidate.model_key,
                        ProviderOperation.state == "accepted",
                    )
                    .values(state="succeeded", updated_at=timestamp)
                )
                if getattr(operation_changed, "rowcount", 0) != 1:
                    raise invalid_state("The embedding operation success fence changed.")
                reservation_changed = db.execute(
                    update(ProviderReservation)
                    .where(
                        ProviderReservation.operation_id == provider_operation_id,
                        ProviderReservation.state == "accepted",
                    )
                    .values(state="succeeded", updated_at=timestamp)
                )
                if getattr(reservation_changed, "rowcount", 0) != 1:
                    raise invalid_state("The embedding reservation success fence changed.")
        previous = None
        if final_agent.current_published_version_id:
            previous = db.scalar(
                select(AgentVersion).where(
                    AgentVersion.id == final_agent.current_published_version_id,
                    AgentVersion.agent_id == final_agent.id,
                    AgentVersion.state == "published",
                )
            )
            if previous is None:
                raise invalid_state("The current published version is unavailable.")
            previous.state = "superseded"
            previous.updated_at = timestamp
        pointer_condition = (
            Agent.current_published_version_id.is_(None)
            if captured_current_pointer is None
            else Agent.current_published_version_id == captured_current_pointer
        )
        pointer_changed = db.execute(
            update(Agent)
            .where(Agent.id == final_agent.id, pointer_condition)
            .execution_options(synchronize_session=False)
            .values(current_published_version_id=final_version.id, updated_at=timestamp)
        )
        if getattr(pointer_changed, "rowcount", 0) != 1:
            raise invalid_state("The current published version changed during publication.")
        db.refresh(final_agent)
        operation = load_file_operation(db, operation_id)
        operation.state = "committed"
        operation.updated_at = now_utc()
        db.flush()
        saga_checkpoint("publish.before_final_commit")
        # The caller commits this transaction together with its guarded
        # idempotency completion so publication and replay are indivisible.
        version.knowledge_snapshot_id = snapshot.id
        version.published_visibility = final_version.published_visibility
        version.authorization_epoch = final_version.authorization_epoch
        version.state = "published"
        version.revision = final_version.revision
        version.published_at = final_version.published_at
        version.updated_at = final_version.updated_at
        agent.current_published_version_id = final_agent.current_published_version_id
        agent.updated_at = final_agent.updated_at
        return snapshot
    except PlatformError:
        try:
            recover_operation_now(db, data_root, operation_id)
        except Exception:
            try:
                transition_file_operation(
                    db,
                    operation_id,
                    "cleanup_required",
                    safe_error_code="file_operation_failed",
                )
            except Exception:
                pass
        raise
    except Exception:
        # The final publication transaction may already hold SQLite's writer
        # lock.  Release it before recording the durable cleanup marker so a
        # fault at DB/CAS boundaries cannot leave a promoted orphan merely
        # because the independent journal writer was blocked by this session.
        db.rollback()
        try:
            transition_file_operation(
                db,
                operation_id,
                "cleanup_required",
                safe_error_code="file_operation_failed",
            )
        except Exception:
            pass
        raise
