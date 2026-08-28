"""Scoped repositories and deterministic Wave 1A domain services."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from fastapi.responses import JSONResponse
from sqlalchemy import and_, delete, exists, or_, select, text, update
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
    AgentVersion,
    AgentVersionDocument,
    CourseMember,
    FileOperation,
    FileReference,
    Group,
    GroupMember,
    IdempotencyRecord,
    Job,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeSnapshot,
    SnapshotDocument,
    StoredFile,
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
    write_atomic,
)
from app.modules.knowledge.markdown import (
    EMBEDDING_DIMENSION,
    EMBEDDING_KEY,
    MAX_RAG_CHARS,
    build_chunks,
    normalize_markdown,
    query_embedding,
)
from app.modules.knowledge.schemas import JobStatus
from app.modules.knowledge.schemas import KnowledgeDocument as KnowledgeDocumentDTO


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


def scoped_group_role(db: Session, context: AuthContext, group_id: str) -> str | None:
    """Resolve a group's course/group membership without loading the group first."""

    row = db.execute(
        select(CourseMember.role, GroupMember.user_id)
        .select_from(Group)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .outerjoin(
            GroupMember,
            and_(GroupMember.group_id == Group.id, GroupMember.user_id == context.user.id),
        )
        .where(
            Group.id == group_id,
            CourseMember.user_id == context.user.id,
            or_(CourseMember.role == "teacher", GroupMember.user_id.is_not(None)),
        )
    ).first()
    if row is None:
        return None
    return "teacher" if row[0] == "teacher" else "student"


def scoped_student_group_role(db: Session, context: AuthContext, group_id: str) -> str:
    role = scoped_group_role(db, context, group_id)
    if role != "student":
        raise not_found()
    return role


def visible_agent(db: Session, context: AuthContext, agent_id: str) -> ScopedAgent:
    published_version = exists(
        select(AgentVersion.id).where(
            AgentVersion.agent_id == Agent.id,
            AgentVersion.state.in_(("published", "superseded")),
        )
    )
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
                and_(CourseMember.role == "teacher", published_version),
                and_(CourseMember.role == "student", GroupMember.user_id.is_not(None)),
            ),
        )
    ).first()
    if row is None:
        raise not_found()
    return ScopedAgent(row[0], "teacher" if row[1] == "teacher" else "student")


def visible_version(db: Session, context: AuthContext, version_id: str) -> ScopedVersion:
    row = db.execute(
        select(AgentVersion, Agent, CourseMember.role)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .join(Group, Group.id == Agent.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .outerjoin(
            GroupMember,
            and_(GroupMember.group_id == Group.id, GroupMember.user_id == context.user.id),
        )
        .where(
            AgentVersion.id == version_id,
            CourseMember.user_id == context.user.id,
            or_(
                and_(
                    CourseMember.role == "teacher",
                    AgentVersion.state.in_(("published", "superseded")),
                ),
                and_(CourseMember.role == "student", GroupMember.user_id.is_not(None)),
            ),
        )
    ).first()
    if row is None:
        raise not_found()
    return ScopedVersion(row[0], row[1], "teacher" if row[2] == "teacher" else "student")


def visible_document(db: Session, context: AuthContext, document_id: str) -> ScopedDocument:
    row = db.execute(
        select(KnowledgeDocument, CourseMember.role)
        .join(Group, Group.id == KnowledgeDocument.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .outerjoin(
            GroupMember,
            and_(GroupMember.group_id == Group.id, GroupMember.user_id == context.user.id),
        )
        .where(
            KnowledgeDocument.id == document_id,
            CourseMember.user_id == context.user.id,
            or_(CourseMember.role == "teacher", GroupMember.user_id.is_not(None)),
        )
    ).first()
    if row is None:
        raise not_found()
    return ScopedDocument(row[0], "teacher" if row[1] == "teacher" else "student")


def visible_snapshot(db: Session, context: AuthContext, snapshot_id: str) -> ScopedSnapshot:
    row = db.execute(
        select(KnowledgeSnapshot, AgentVersion, Agent, CourseMember.role)
        .join(AgentVersion, AgentVersion.id == KnowledgeSnapshot.agent_version_id)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .join(Group, Group.id == Agent.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .outerjoin(
            GroupMember,
            and_(GroupMember.group_id == Group.id, GroupMember.user_id == context.user.id),
        )
        .where(
            KnowledgeSnapshot.id == snapshot_id,
            AgentVersion.state.in_(("published", "superseded")),
            CourseMember.user_id == context.user.id,
            or_(CourseMember.role == "teacher", GroupMember.user_id.is_not(None)),
        )
    ).first()
    if row is None:
        raise not_found()
    return ScopedSnapshot(row[0], row[1], row[2], "teacher" if row[3] == "teacher" else "student")


def visible_student_version(db: Session, context: AuthContext, version_id: str) -> ScopedVersion:
    row = db.execute(
        select(AgentVersion, Agent)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .join(Group, Group.id == Agent.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .join(
            GroupMember,
            and_(GroupMember.group_id == Group.id, GroupMember.user_id == context.user.id),
        )
        .where(
            AgentVersion.id == version_id,
            CourseMember.user_id == context.user.id,
            CourseMember.role == "student",
        )
    ).first()
    if row is None:
        raise not_found()
    return ScopedVersion(row[0], row[1], "student")


def visible_student_agent(db: Session, context: AuthContext, agent_id: str) -> ScopedAgent:
    row = db.execute(
        select(Agent)
        .join(Group, Group.id == Agent.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .join(
            GroupMember,
            and_(GroupMember.group_id == Group.id, GroupMember.user_id == context.user.id),
        )
        .where(
            Agent.id == agent_id,
            CourseMember.user_id == context.user.id,
            CourseMember.role == "student",
        )
    ).first()
    if row is None:
        raise not_found()
    return ScopedAgent(row[0], "student")


def visible_student_document(db: Session, context: AuthContext, document_id: str) -> ScopedDocument:
    row = db.execute(
        select(KnowledgeDocument)
        .join(Group, Group.id == KnowledgeDocument.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .join(
            GroupMember,
            and_(GroupMember.group_id == Group.id, GroupMember.user_id == context.user.id),
        )
        .where(
            KnowledgeDocument.id == document_id,
            CourseMember.user_id == context.user.id,
            CourseMember.role == "student",
        )
    ).first()
    if row is None:
        raise not_found()
    return ScopedDocument(row[0], "student")


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
        raise invalid_state("The idempotency claim is no longer owned by this request.")


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


def _document_dto(document: KnowledgeDocument) -> KnowledgeDocumentDTO:
    return KnowledgeDocumentDTO(
        id=UUID(document.id),
        group_id=UUID(document.group_id),
        source_filename=document.source_filename,
        char_count=document.char_count,
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
    if len(version.agent_md) > 12_000:
        result.append("agent_md_too_large")
    docs = _enabled_documents(db, version.id)
    if not docs:
        result.append("rag_missing")
    total = sum(document.char_count for document in docs)
    if total > MAX_RAG_CHARS:
        result.append("rag_over_limit")
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


def version_dto(
    db: Session,
    version: AgentVersion,
    agent: Agent,
    settings: Settings | None = None,
) -> AgentVersionDTO:
    docs = _enabled_documents(db, version.id)
    from app.modules.voices.preview import resolve_effective_voice_profile

    effective_voice = resolve_effective_voice_profile(
        db,
        version.voice_profile_id,
        agent.group_id,
        settings or db.info.get("maya_settings") or get_settings(),
    )
    return AgentVersionDTO(
        id=UUID(version.id),
        agent_id=UUID(version.agent_id),
        version_label=f"V1.{version.version_seq}",
        state=cast(Literal["draft", "published", "superseded"], version.state),
        revision=version.revision,
        agent_md=version.agent_md,
        avatar_config=_avatar(version.avatar_config_json),
        voice_profile_id=UUID(version.voice_profile_id) if version.voice_profile_id else None,
        effective_voice_profile_id=(
            UUID(effective_voice.profile_id) if effective_voice.profile_id else None
        ),
        voice_fallback_active=effective_voice.fallback_active,
        knowledge_snapshot_id=(
            UUID(version.knowledge_snapshot_id) if version.knowledge_snapshot_id else None
        ),
        enabled_documents=[_document_dto(document) for document in docs],
        publish_blockers=blockers(db, version, agent) if version.state == "draft" else [],
    )


def agent_summary(db: Session, agent: Agent, *, include_draft: bool = True) -> AgentSummary:
    draft_id = (
        db.scalar(
            select(AgentVersion.id).where(
                AgentVersion.agent_id == agent.id,
                AgentVersion.state == "draft",
            )
        )
        if include_draft
        else None
    )
    return AgentSummary(
        id=UUID(agent.id),
        group_id=UUID(agent.group_id),
        name=agent.name,
        description=agent.description,
        metadata_revision=agent.metadata_revision,
        status=cast(Literal["active", "archived"], agent.status),
        current_published_version_id=(
            UUID(agent.current_published_version_id) if agent.current_published_version_id else None
        ),
        current_draft_version_id=UUID(draft_id) if draft_id else None,
    )


def agent_detail(db: Session, agent: Agent, role: str) -> AgentDetail:
    query = select(AgentVersion).where(AgentVersion.agent_id == agent.id)
    if role == "teacher":
        query = query.where(AgentVersion.state.in_(("published", "superseded")))
    versions = list(db.scalars(query.order_by(AgentVersion.version_seq)).all())
    if role == "teacher" and not versions:
        raise not_found()
    return AgentDetail(
        **agent_summary(db, agent, include_draft=role == "student").model_dump(),
        versions=[version_dto(db, version, agent) for version in versions],
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
        limit=100000,
        document_count=len(docs),
        index_status=cast(Literal["pending", "ready", "failed"], state),
        combined_markdown=combined_markdown(db, version.id, data_root),
    )


def _write_stored_file(
    db: Session,
    data_root: Any,
    relative_path: str,
    content: bytes,
    *,
    file_id: str | None = None,
    now: datetime | None = None,
) -> StoredFile:
    digest, size = write_atomic(data_root, relative_path, content)
    timestamp = now or now_utc()
    stored = StoredFile(
        id=file_id or str(uuid4()),
        relative_path=relative_path,
        sha256=digest,
        size_bytes=size,
        state="active",
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(stored)
    db.flush()
    return stored


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


def persist_document_chunks(db: Session, document: KnowledgeDocument, text: str) -> None:
    """Compatibility wrapper that computes before mutating the old index."""

    replace_document_chunks(db, document, build_chunks(text))


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


def retrieval_response(db: Session, version: AgentVersion, message: str) -> TestChatResponse:
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
    top = ranked[:6]
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
) -> KnowledgeSnapshot:
    expected = version.revision if expected_revision is None else expected_revision
    blockers_list = blockers(db, version, agent)
    if blockers_list:
        raise publish_blockers(blockers_list)
    selected = _enabled_documents(db, version.id)
    captured_current_pointer = agent.current_published_version_id

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
        chunks = list(
            db.scalars(
                select(KnowledgeDocumentChunk)
                .where(KnowledgeDocumentChunk.document_id == document.id)
                .order_by(KnowledgeDocumentChunk.chunk_index)
            ).all()
        )
        captured.append(
            {
                "document": document,
                "source_bytes": source_bytes,
                "source_sha": source_sha,
                "normalized": normalized,
                "index_revision": document.index_revision,
                "content_hash": document.content_hash,
                "snapshot_document_id": str(uuid4()),
                "frozen_file_id": str(uuid4()),
                "chunks": [
                    (
                        chunk.chunk_index,
                        chunk.chunk_text,
                        chunk.start_offset,
                        chunk.end_offset,
                        chunk.embedding_blob,
                        chunk.embedding_dimension,
                        chunk.embedding_key,
                    )
                    for chunk in chunks
                ],
                "order": order,
            }
        )
    combined = "\n\n".join(
        f"{_source_marker(item['document'])}\n{item['normalized']}" for item in captured
    )
    combined_bytes = combined.encode("utf-8")
    combined_sha = hashlib.sha256(combined_bytes).hexdigest()
    timestamp = now_utc()
    snapshot_id = str(uuid4())
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
        db.execute(text("BEGIN IMMEDIATE"))
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
                published_at=timestamp,
                updated_at=timestamp,
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
            embedding_key=EMBEDDING_KEY,
            chunking_json=json.dumps({"token_target": 600, "token_hard": 800, "overlap": 100}),
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
                        id=str(uuid4()),
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
