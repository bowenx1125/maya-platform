"""Durable, permission-fenced Knowledge preparation intents.

This slice records eligible Done requests and safely blocks them until the
Provider-backed worker is implemented. It deliberately never makes a model
request or creates an AI asset.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.core.models import (
    Agent,
    AgentVersion,
    Job,
    KnowledgeDocument,
    StoredFile,
)
from app.modules.agents.schemas import KnowledgeGenerationIntent, KnowledgeGenerationReceipt
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import (
    _agent_workspace_role,
    _enabled_documents,
    can_read_source,
    course_member_role,
    scoped_group_role_for_user,
)
from app.modules.knowledge_sets.models import (
    AgentKnowledgeSet,
    KnowledgeGenerationRun,
    KnowledgeSet,
    KnowledgeSetSource,
)
from app.modules.knowledge_sets.schemas import KnowledgeGenerationStatus
from app.modules.knowledge_sets.service import (
    _active_sources,
    _source_matches_current,
    now_utc,
    replace_agent_knowledge_sets,
    replace_knowledge_set_sources,
)

GENERATION_OPERATION = "knowledge_set.generate"
GENERATION_POLICY_VERSION = "knowledge_set_generation_v1"
_GENERATION_SET_NAMESPACE = UUID("ae685827-e790-4a04-a751-464238414263")
_LEASE_SECONDS = 60
_GenerationState = Literal["pending", "running", "blocked", "completed", "failed", "interrupted"]


@dataclass(frozen=True)
class GenerationEnqueue:
    run: KnowledgeGenerationRun
    job: Job
    created: bool


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: bytes | str) -> str:
    encoded = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(encoded).hexdigest()


def _generation_set_id(agent: Agent) -> str:
    stable_target = f"{agent.owner_user_id}:{agent.course_id}:{agent.id}"
    return str(uuid5(_GENERATION_SET_NAMESPACE, stable_target))


def _authorize_generation_owner(
    db: Session, context: AuthContext, agent: Agent, version: AgentVersion, *, state: str
) -> None:
    actor_id = context.user.id
    if (
        agent.deleted_at is not None
        or agent.status != "active"
        or agent.owner_user_id != actor_id
        or version.agent_id != agent.id
        or version.state != state
        or course_member_role(db, actor_id, agent.course_id) != "teacher"
        or _agent_workspace_role(db, actor_id, agent) != "owner"
    ):
        raise not_found()


def _selected_documents(
    db: Session,
    context: AuthContext,
    agent: Agent,
    version: AgentVersion,
    intent: KnowledgeGenerationIntent,
    *,
    state: str,
) -> list[KnowledgeDocument]:
    _authorize_generation_owner(db, context, agent, version, state=state)
    documents = _enabled_documents(db, version.id)
    selected_ids = [str(value) for value in intent.source_document_ids]
    if selected_ids != [document.id for document in documents]:
        raise conflict(
            "generation_source_selection_stale",
            "The selected courseware changed before this Agent was finished.",
        )
    for document in documents:
        stored = db.get(StoredFile, document.stored_file_id)
        if (
            document.course_id != agent.course_id
            or document.workspace_state != "active"
            or stored is None
            or stored.state != "active"
            or len(stored.sha256) != 64
            or not can_read_source(db, context, document)
        ):
            raise not_found()
    return documents


def validate_generation_intent(
    db: Session,
    context: AuthContext,
    agent: Agent,
    version: AgentVersion,
    intent: KnowledgeGenerationIntent,
    *,
    state: str = "draft",
) -> None:
    """Check owner, Teacher course role and the exact active source selection."""

    _selected_documents(db, context, agent, version, intent, state=state)


def _new_private_set(db: Session, context: AuthContext, agent: Agent, set_id: str) -> KnowledgeSet:
    existing = db.get(KnowledgeSet, set_id)
    if existing is not None:
        if (
            existing.owner_user_id != context.user.id
            or existing.course_id != agent.course_id
            or existing.ownership_scope != "personal"
            or existing.group_id is not None
            or existing.deleted_at is not None
        ):
            raise not_found()
        return existing
    timestamp = now_utc()
    row = KnowledgeSet(
        id=set_id,
        owner_user_id=context.user.id,
        course_id=agent.course_id,
        group_id=None,
        ownership_scope="personal",
        visibility="private",
        display_name=f"{agent.name} Knowledge",
        metadata_revision=0,
        content_revision=0,
        authorization_epoch=0,
        deleted_at=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(row)
    db.flush()
    return row


def _ensure_set_sources(
    db: Session,
    context: AuthContext,
    set_row: KnowledgeSet,
    selected: list[KnowledgeDocument],
) -> list[KnowledgeSetSource]:
    current = _active_sources(db, set_row.id)
    current_document_ids = [
        binding.document_id
        for binding in current
        if _source_matches_current(db, context, binding, role="owner", for_write=True)
    ]
    union_ids = list(
        dict.fromkeys([*current_document_ids, *(document.id for document in selected)])
    )
    detail = replace_knowledge_set_sources(
        db,
        context,
        set_row.id,
        expected_content_revision=set_row.content_revision,
        source_document_ids=[UUID(value) for value in union_ids],
    )
    del detail
    return _active_sources(db, set_row.id)


def _source_manifest(
    bindings: list[KnowledgeSetSource], selected_ids: list[str]
) -> list[dict[str, Any]]:
    by_document = {binding.document_id: binding for binding in bindings}
    manifest: list[dict[str, Any]] = []
    for document_id in selected_ids:
        binding = by_document.get(document_id)
        if binding is None or not binding.is_active:
            raise not_found()
        manifest.append(
            {
                "binding_id": binding.id,
                "document_id": binding.document_id,
                "stored_file_id": binding.stored_file_id,
                "content_hash": binding.source_content_hash,
                "file_sha256": binding.source_file_sha256,
                "authorization_epoch": binding.source_authorization_epoch,
                "index_revision": binding.source_index_revision,
                "order_index": binding.order_index,
            }
        )
    return manifest


def _input_payload(
    *,
    agent: Agent,
    set_row: KnowledgeSet,
    agent_md_hash: str,
    source_manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "policy_version": GENERATION_POLICY_VERSION,
        "owner_user_id": agent.owner_user_id,
        "course_id": agent.course_id,
        "agent_id": agent.id,
        "agent_domain": {
            "ownership_scope": agent.ownership_scope,
            "group_id": agent.group_id,
            "visibility": agent.visibility,
            "authorization_epoch": agent.authorization_epoch,
        },
        "target_set": {
            "id": set_row.id,
            "ownership_scope": set_row.ownership_scope,
            "group_id": set_row.group_id,
            "visibility": set_row.visibility,
            "authorization_epoch": set_row.authorization_epoch,
        },
        "agent_md_hash": agent_md_hash,
        "sources": source_manifest,
    }


def enqueue_generation_for_publish(
    db: Session,
    context: AuthContext,
    agent: Agent,
    version: AgentVersion,
    intent: KnowledgeGenerationIntent,
) -> GenerationEnqueue:
    """Persist one stable Job/run in the caller's final publish transaction."""

    documents = _selected_documents(db, context, agent, version, intent, state="published")
    set_row = _new_private_set(db, context, agent, _generation_set_id(agent))
    bindings = _ensure_set_sources(db, context, set_row, documents)

    existing_agent_sets = list(
        db.scalars(
            select(AgentKnowledgeSet)
            .where(AgentKnowledgeSet.agent_id == agent.id)
            .order_by(AgentKnowledgeSet.order_index, AgentKnowledgeSet.knowledge_set_id)
        ).all()
    )
    set_ids = [row.knowledge_set_id for row in existing_agent_sets]
    if set_row.id not in set_ids:
        set_ids.append(set_row.id)
        replace_agent_knowledge_sets(
            db,
            context,
            agent.id,
            expected_agent_metadata_revision=agent.metadata_revision,
            set_ids=[UUID(value) for value in set_ids],
        )

    source_manifest = _source_manifest(bindings, [document.id for document in documents])
    manifest_json = _canonical_json(source_manifest)
    manifest_hash = _sha256(manifest_json)
    agent_md_hash = _sha256(version.agent_md)
    input_key = _sha256(
        _canonical_json(
            _input_payload(
                agent=agent,
                set_row=set_row,
                agent_md_hash=agent_md_hash,
                source_manifest=source_manifest,
            )
        )
    )
    existing_run = db.scalar(
        select(KnowledgeGenerationRun).where(KnowledgeGenerationRun.input_key == input_key)
    )
    if existing_run is not None:
        existing_job = db.get(Job, existing_run.job_id)
        if existing_job is None:
            raise RuntimeError("Knowledge generation run lost its Job row.")
        return GenerationEnqueue(existing_run, existing_job, False)

    timestamp = now_utc()
    job_id = str(uuid4())
    run = KnowledgeGenerationRun(
        id=str(uuid4()),
        job_id=job_id,
        input_key=input_key,
        owner_user_id=context.user.id,
        course_id=agent.course_id,
        agent_id=agent.id,
        agent_version_id=version.id,
        knowledge_set_id=set_row.id,
        agent_md_hash=agent_md_hash,
        agent_authorization_epoch=agent.authorization_epoch,
        set_authorization_epoch=set_row.authorization_epoch,
        source_manifest_json=manifest_json,
        source_manifest_hash=manifest_hash,
        state="pending",
        safe_error_code=None,
        claim_token=None,
        lease_expires_at=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    job = Job(
        id=job_id,
        operation=GENERATION_OPERATION,
        state="pending",
        idempotency_key=input_key,
        claim_token=None,
        attempt=0,
        safe_error_code=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    try:
        with db.begin_nested():
            db.add(job)
            db.add(run)
            db.flush()
    except IntegrityError as exc:
        existing_run = db.scalar(
            select(KnowledgeGenerationRun).where(KnowledgeGenerationRun.input_key == input_key)
        )
        if existing_run is None:
            raise
        existing_job = db.get(Job, existing_run.job_id)
        if existing_job is None:
            raise RuntimeError("Knowledge generation run lost its Job row.") from exc
        return GenerationEnqueue(existing_run, existing_job, False)
    return GenerationEnqueue(run, job, True)


def _current_source_manifest(
    db: Session, run: KnowledgeGenerationRun, agent: Agent, set_row: KnowledgeSet
) -> list[dict[str, Any]] | None:
    try:
        stored_manifest = json.loads(run.source_manifest_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(stored_manifest, list):
        return None
    result: list[dict[str, Any]] = []
    for item in stored_manifest:
        if not isinstance(item, dict) or not isinstance(item.get("binding_id"), str):
            return None
        binding = db.get(KnowledgeSetSource, item["binding_id"])
        if (
            binding is None
            or binding.knowledge_set_id != set_row.id
            or not binding.is_active
            or binding.document_id != item.get("document_id")
            or binding.stored_file_id != item.get("stored_file_id")
        ):
            return None
        document = db.get(KnowledgeDocument, binding.document_id)
        stored_file = db.get(StoredFile, binding.stored_file_id)
        if (
            document is None
            or stored_file is None
            or document.course_id != run.course_id
            or document.workspace_state != "active"
            or document.authorization_epoch != binding.source_authorization_epoch
            or document.content_hash != binding.source_content_hash
            or document.index_revision != binding.source_index_revision
            or stored_file.state != "active"
            or stored_file.sha256 != binding.source_file_sha256
            or not can_read_source(db, run.owner_user_id, document)
            or (
                set_row.ownership_scope == "personal"
                and document.ownership_scope == "group"
                and document.group_id is not None
                and scoped_group_role_for_user(db, run.owner_user_id, document.group_id)
                != "student"
            )
        ):
            return None
        result.append(
            {
                "binding_id": binding.id,
                "document_id": binding.document_id,
                "stored_file_id": binding.stored_file_id,
                "content_hash": binding.source_content_hash,
                "file_sha256": binding.source_file_sha256,
                "authorization_epoch": binding.source_authorization_epoch,
                "index_revision": binding.source_index_revision,
                "order_index": binding.order_index,
            }
        )
    return result


def _current_generation_authorized(db: Session, run: KnowledgeGenerationRun) -> bool:
    agent = db.get(Agent, run.agent_id)
    version = db.get(AgentVersion, run.agent_version_id)
    set_row = db.get(KnowledgeSet, run.knowledge_set_id)
    if (
        agent is None
        or version is None
        or set_row is None
        or agent.deleted_at is not None
        or agent.status != "active"
        or agent.owner_user_id != run.owner_user_id
        or agent.course_id != run.course_id
        or agent.authorization_epoch != run.agent_authorization_epoch
        or version.agent_id != agent.id
        or version.state not in {"published", "superseded"}
        or _sha256(version.agent_md) != run.agent_md_hash
        or course_member_role(db, run.owner_user_id, run.course_id) != "teacher"
        or _agent_workspace_role(db, run.owner_user_id, agent) != "owner"
        or set_row.owner_user_id != run.owner_user_id
        or set_row.course_id != run.course_id
        or set_row.deleted_at is not None
        or set_row.authorization_epoch != run.set_authorization_epoch
    ):
        return False
    current_manifest = _current_source_manifest(db, run, agent, set_row)
    if current_manifest is None:
        return False
    if _sha256(_canonical_json(current_manifest)) != run.source_manifest_hash:
        return False
    return (
        _sha256(
            _canonical_json(
                _input_payload(
                    agent=agent,
                    set_row=set_row,
                    agent_md_hash=run.agent_md_hash,
                    source_manifest=current_manifest,
                )
            )
        )
        == run.input_key
    )


def _start_immediate(db: Session) -> None:
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))


def claim_generation_run(db: Session, run_id: str) -> str | None:
    """Claim one pending or expired lease and recheck every source fence."""

    db.rollback()
    _start_immediate(db)
    run = db.scalar(
        select(KnowledgeGenerationRun).where(KnowledgeGenerationRun.id == run_id).with_for_update()
    )
    if run is None:
        db.rollback()
        return None
    job = db.get(Job, run.job_id)
    if job is None or job.operation != GENERATION_OPERATION:
        db.rollback()
        return None
    now = now_utc()
    lease_expires_at = run.lease_expires_at
    if lease_expires_at is not None and lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
    expired = run.state == "running" and (lease_expires_at is None or lease_expires_at <= now)
    if run.state != "pending" and not expired:
        db.rollback()
        return None
    if not _current_generation_authorized(db, run):
        _finish_blocked(db, run, job, "authorization_revoked")
        db.commit()
        return None
    token = str(uuid4())
    run.state = "running"
    run.claim_token = token
    run.lease_expires_at = now + timedelta(seconds=_LEASE_SECONDS)
    run.safe_error_code = None
    run.updated_at = now
    job.state = "running"
    job.claim_token = token
    job.attempt += 1
    job.safe_error_code = None
    job.updated_at = now
    db.commit()
    return token


def _finish_blocked(db: Session, run: KnowledgeGenerationRun, job: Job, error_code: str) -> None:
    now = now_utc()
    run.state = "blocked"
    run.safe_error_code = error_code
    run.claim_token = None
    run.lease_expires_at = None
    run.updated_at = now
    job.state = "failed"
    job.safe_error_code = error_code
    job.claim_token = None
    job.updated_at = now


def block_claimed_generation(session_factory: Any, run_id: str) -> None:
    """K2a safe stop: the durable worker exists, but no Provider is wired."""

    with session_factory() as db:
        token = claim_generation_run(db, run_id)
    if token is None:
        return
    with session_factory() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        if run is None or run.state != "running" or run.claim_token != token:
            db.rollback()
            return
        job = db.get(Job, run.job_id)
        if job is None or job.claim_token != token:
            db.rollback()
            return
        code = (
            "provider_not_configured"
            if _current_generation_authorized(db, run)
            else "authorization_revoked"
        )
        _finish_blocked(db, run, job, code)
        db.commit()


def mark_generation_worker_failure(session_factory: Any, run_id: str) -> None:
    """Record an unexpected local failure without retaining a stale lease."""

    with session_factory() as db:
        db.rollback()
        _start_immediate(db)
        run = db.get(KnowledgeGenerationRun, run_id)
        if run is None or run.state != "running":
            db.rollback()
            return
        job = db.get(Job, run.job_id)
        if job is None or job.operation != GENERATION_OPERATION:
            db.rollback()
            return
        _finish_blocked(db, run, job, "generation_worker_failed")
        db.commit()


def recover_generation_runs_at_startup(db: Session) -> int:
    """Return interrupted K2a in-process claims to the durable pending queue.

    K2a has no outbound Provider path, so every running run from a previous
    process is safe to reclaim. K2b must reconcile ProviderOperation state
    before retaining this recovery rule.
    """

    db.rollback()
    _start_immediate(db)
    rows = db.scalars(
        select(KnowledgeGenerationRun).where(KnowledgeGenerationRun.state == "running")
    ).all()
    now = now_utc()
    for run in rows:
        job = db.get(Job, run.job_id)
        run.state = "pending"
        run.claim_token = None
        run.lease_expires_at = None
        run.safe_error_code = None
        run.updated_at = now
        if job is not None and job.operation == GENERATION_OPERATION:
            job.state = "pending"
            job.claim_token = None
            job.safe_error_code = None
            job.updated_at = now
    db.commit()
    return len(rows)


def list_pending_generation_runs(db: Session) -> list[str]:
    return list(
        db.scalars(
            select(KnowledgeGenerationRun.id)
            .where(KnowledgeGenerationRun.state == "pending")
            .order_by(KnowledgeGenerationRun.created_at, KnowledgeGenerationRun.id)
        ).all()
    )


def get_generation_status(
    db: Session, context: AuthContext, job_id: str
) -> KnowledgeGenerationStatus:
    run = db.scalar(select(KnowledgeGenerationRun).where(KnowledgeGenerationRun.job_id == job_id))
    if (
        run is None
        or run.owner_user_id != context.user.id
        or course_member_role(db, context.user.id, run.course_id) != "teacher"
    ):
        raise not_found()
    agent = db.get(Agent, run.agent_id)
    if (
        agent is None
        or agent.owner_user_id != context.user.id
        or _agent_workspace_role(db, context.user.id, agent) != "owner"
    ):
        raise not_found()
    state = run.state
    error_code = run.safe_error_code
    if state in {"pending", "running"} and not _current_generation_authorized(db, run):
        state = "blocked"
        error_code = "authorization_revoked"
    return KnowledgeGenerationStatus(
        run_id=UUID(run.id),
        job_id=UUID(run.job_id),
        knowledge_set_id=UUID(run.knowledge_set_id),
        state=cast(_GenerationState, state),
        safe_error_code=error_code,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def generation_receipt(run: KnowledgeGenerationRun) -> KnowledgeGenerationReceipt:
    return KnowledgeGenerationReceipt(
        run_id=UUID(run.id),
        job_id=UUID(run.job_id),
        knowledge_set_id=UUID(run.knowledge_set_id),
        state=cast(_GenerationState, run.state),
    )
