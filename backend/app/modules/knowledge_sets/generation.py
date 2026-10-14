"""Durable, permission-fenced Knowledge generation and recovery intents."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import conflict, not_found
from app.core.models import (
    Agent,
    AgentVersion,
    IdempotencyRecord,
    Job,
    KnowledgeDocument,
    ProviderOperation,
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
    KnowledgeAsset,
    KnowledgeAssetVersion,
    KnowledgeDocumentVersion,
    KnowledgeGenerationAcceptedStage,
    KnowledgeGenerationItem,
    KnowledgeGenerationRun,
    KnowledgeGenerationSourceReceipt,
    KnowledgeGenerationTargetSnapshot,
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
_GENERATION_ACTION_OPERATION = "knowledgeGenerationAction"


@dataclass(frozen=True)
class GenerationEnqueue:
    run: KnowledgeGenerationRun
    job: Job
    created: bool
    action_id: str | None = None


def _generation_action_key(action_id: str) -> str:
    return f"action:{action_id}"


def _generation_action_request_hash(
    owner_user_id: str, set_id: str, action_id: str, payload_hash: str
) -> str:
    return _sha256(
        _canonical_json(
            {
                "owner_user_id": owner_user_id,
                "knowledge_set_id": set_id,
                "action_id": action_id,
                "payload_hash": payload_hash,
            }
        )
    )


def _generation_action_replay(
    db: Session,
    *,
    owner_user_id: str,
    set_id: str,
    action_id: str,
    payload_hash: str,
) -> GenerationEnqueue | None:
    record = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_user_id == owner_user_id,
            IdempotencyRecord.operation == _GENERATION_ACTION_OPERATION,
            IdempotencyRecord.key == _generation_action_key(action_id),
        )
    )
    if record is None:
        return None
    expected_hash = _generation_action_request_hash(owner_user_id, set_id, action_id, payload_hash)
    if record.request_hash != expected_hash or record.state != "completed":
        raise conflict(
            "knowledge_generation_action_conflict",
            "This Knowledge generation action is already bound to another request.",
        )
    try:
        response = json.loads(record.response_json or "{}")
        run_id = response["run_id"]
    except (TypeError, ValueError, KeyError):
        raise conflict(
            "knowledge_generation_action_unavailable",
            "The saved Knowledge generation action is unavailable.",
        ) from None
    if response.get("action_id") != action_id:
        raise conflict(
            "knowledge_generation_action_unavailable",
            "The saved Knowledge generation action is unavailable.",
        )
    run = db.get(KnowledgeGenerationRun, run_id)
    if run is None or run.knowledge_set_id != set_id or run.owner_user_id != owner_user_id:
        raise conflict(
            "knowledge_generation_action_unavailable",
            "The saved Knowledge generation action is unavailable.",
        )
    job = db.get(Job, run.job_id)
    if job is None or response.get("job_id") != job.id:
        raise conflict(
            "knowledge_generation_action_unavailable",
            "The saved Knowledge generation action is unavailable.",
        )
    return GenerationEnqueue(run, job, False, action_id)


def _record_generation_action(
    db: Session,
    *,
    owner_user_id: str,
    set_id: str,
    action_id: str,
    payload_hash: str,
    run: KnowledgeGenerationRun,
    job: Job,
) -> None:
    """Persist an explicit action-to-run alias independently of HTTP request keys."""

    timestamp = now_utc()
    record = IdempotencyRecord(
        id=str(uuid4()),
        actor_user_id=owner_user_id,
        operation=_GENERATION_ACTION_OPERATION,
        key=_generation_action_key(action_id),
        request_hash=_generation_action_request_hash(
            owner_user_id, set_id, action_id, payload_hash
        ),
        state="completed",
        claim_token=str(uuid4()),
        lease_expires_at=timestamp,
        status_code=202,
        response_json=_canonical_json({"run_id": run.id, "job_id": job.id, "action_id": action_id}),
        created_at=timestamp,
        updated_at=timestamp,
    )
    try:
        with db.begin_nested():
            db.add(record)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.actor_user_id == owner_user_id,
                IdempotencyRecord.operation == _GENERATION_ACTION_OPERATION,
                IdempotencyRecord.key == _generation_action_key(action_id),
            )
        )
        if (
            existing is None
            or existing.request_hash != record.request_hash
            or existing.state != "completed"
        ):
            raise
        try:
            response = json.loads(existing.response_json or "{}")
        except (TypeError, ValueError):
            raise conflict(
                "knowledge_generation_action_conflict",
                "This Knowledge generation action is already bound to another run.",
            ) from None
        if (
            not isinstance(response, dict)
            or response.get("run_id") != run.id
            or response.get("job_id") != job.id
            or response.get("action_id") != action_id
        ):
            raise conflict(
                "knowledge_generation_action_conflict",
                "This Knowledge generation action is already bound to another run.",
            ) from None


def record_generation_action_alias_for_run(
    db: Session,
    *,
    owner_user_id: str,
    action_id: str,
    run: KnowledgeGenerationRun,
) -> None:
    """Bind a stable teacher-action identity to an already-created exact run."""

    agent = db.get(Agent, run.agent_id)
    version = db.get(AgentVersion, run.agent_version_id)
    set_row = db.get(KnowledgeSet, run.knowledge_set_id)
    job = db.get(Job, run.job_id)
    try:
        source_manifest = json.loads(run.source_manifest_json)
    except (TypeError, ValueError):
        raise conflict(
            "knowledge_generation_action_unavailable",
            "The Knowledge generation inputs are unavailable.",
        ) from None
    if (
        agent is None
        or version is None
        or set_row is None
        or job is None
        or run.owner_user_id != owner_user_id
        or run.course_id != agent.course_id
        or run.agent_id != agent.id
        or run.agent_version_id != version.id
        or version.agent_id != agent.id
        or run.knowledge_set_id != set_row.id
        or set_row.course_id != agent.course_id
        or not isinstance(source_manifest, list)
        or _sha256(_canonical_json(source_manifest)) != run.source_manifest_hash
    ):
        raise conflict(
            "knowledge_generation_action_unavailable",
            "The Knowledge generation inputs are unavailable.",
        )
    payload_hash = _generation_action_payload_hash(
        agent=agent,
        version=version,
        set_row=set_row,
        agent_md_hash=run.agent_md_hash,
        source_manifest=source_manifest,
    )
    _record_generation_action(
        db,
        owner_user_id=owner_user_id,
        set_id=set_row.id,
        action_id=action_id,
        payload_hash=payload_hash,
        run=run,
        job=job,
    )


def replay_generation_action_alias_for_run(
    db: Session,
    *,
    owner_user_id: str,
    action_id: str,
    run: KnowledgeGenerationRun,
) -> GenerationEnqueue | None:
    """Replay a teacher action only when it is bound to these exact inputs."""

    agent = db.get(Agent, run.agent_id)
    version = db.get(AgentVersion, run.agent_version_id)
    set_row = db.get(KnowledgeSet, run.knowledge_set_id)
    try:
        source_manifest = json.loads(run.source_manifest_json)
    except (TypeError, ValueError):
        raise conflict(
            "knowledge_generation_action_unavailable",
            "The Knowledge generation inputs are unavailable.",
        ) from None
    if (
        agent is None
        or version is None
        or set_row is None
        or run.owner_user_id != owner_user_id
        or run.agent_id != agent.id
        or run.agent_version_id != version.id
        or version.agent_id != agent.id
        or run.knowledge_set_id != set_row.id
        or not isinstance(source_manifest, list)
        or _sha256(_canonical_json(source_manifest)) != run.source_manifest_hash
    ):
        raise conflict(
            "knowledge_generation_action_unavailable",
            "The Knowledge generation inputs are unavailable.",
        )
    payload_hash = _generation_action_payload_hash(
        agent=agent,
        version=version,
        set_row=set_row,
        agent_md_hash=run.agent_md_hash,
        source_manifest=source_manifest,
    )
    return _generation_action_replay(
        db,
        owner_user_id=owner_user_id,
        set_id=set_row.id,
        action_id=action_id,
        payload_hash=payload_hash,
    )


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
        if document.course_id != agent.course_id:
            raise not_found()
        # Enabled bindings can outlive a Brainform hide/delete. Check that before
        # the active-only read ACL, so the Teacher Tool can name the real fault
        # instead of a bare not_found.
        if (
            document.workspace_state != "active"
            or stored is None
            or stored.state != "active"
            or len(stored.sha256) != 64
        ):
            raise conflict(
                "knowledge_generation_sources_unavailable",
                "This Agent's selected RAG is no longer available. Choose active "
                "Brainform RAG on the Agent and publish again before generating Knowledge.",
            )
        if not can_read_source(db, context, document):
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
        ):
            raise not_found()
        # Stable generation Sets are uuid5(owner, course, agent). Soft-delete
        # must not strand that identity: the next authorized enqueue revives it
        # instead of failing closed as a bare not_found.
        if existing.deleted_at is not None:
            timestamp = now_utc()
            existing.deleted_at = None
            existing.display_name = f"{agent.name} Knowledge"
            existing.metadata_revision += 1
            existing.authorization_epoch += 1
            existing.updated_at = timestamp
            db.flush()
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
    action_id: str | None = None,
    intent_generation: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
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
    if action_id is not None:
        payload["action_id"] = action_id
        payload["intent_generation"] = intent_generation
    return payload


def _generation_action_payload_hash(
    *,
    agent: Agent,
    version: AgentVersion,
    set_row: KnowledgeSet,
    agent_md_hash: str,
    source_manifest: list[dict[str, Any]],
) -> str:
    payload = _input_payload(
        agent=agent,
        set_row=set_row,
        agent_md_hash=agent_md_hash,
        source_manifest=source_manifest,
    )
    payload["agent_version_id"] = version.id
    return _sha256(_canonical_json(payload))


def _generation_run_matches_action_payload(
    run: KnowledgeGenerationRun,
    *,
    owner_user_id: str,
    agent: Agent,
    version: AgentVersion,
    set_row: KnowledgeSet,
    agent_md_hash: str,
    source_manifest_json: str,
    source_manifest_hash: str,
) -> bool:
    return (
        run.owner_user_id == owner_user_id
        and run.course_id == agent.course_id
        and run.agent_id == agent.id
        and run.agent_version_id == version.id
        and run.knowledge_set_id == set_row.id
        and run.agent_md_hash == agent_md_hash
        and run.agent_authorization_epoch == agent.authorization_epoch
        and run.set_authorization_epoch == set_row.authorization_epoch
        and run.source_manifest_json == source_manifest_json
        and run.source_manifest_hash == source_manifest_hash
    )


def _target_asset_heads(db: Session, set_row: KnowledgeSet) -> str:
    """Freeze each generated lineage's exact head before a later AI write."""

    assets = db.scalars(
        select(KnowledgeAsset)
        .where(
            KnowledgeAsset.knowledge_set_id == set_row.id,
            KnowledgeAsset.generation_lineage_key.is_not(None),
            KnowledgeAsset.current_version_seq >= 1,
        )
        .order_by(KnowledgeAsset.generation_lineage_key, KnowledgeAsset.id)
    ).all()
    heads: list[dict[str, object]] = []
    for asset in assets:
        version = db.scalar(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == asset.id,
                KnowledgeAssetVersion.version_seq == asset.current_version_seq,
            )
        )
        if version is None or asset.generation_lineage_key is None:
            raise RuntimeError("Generated Knowledge Set has a broken Asset head.")
        heads.append(
            {
                "lineage_key": asset.generation_lineage_key,
                "asset_id": asset.id,
                "version_seq": asset.current_version_seq,
                "origin": version.origin,
            }
        )
    return _canonical_json(heads)


def _resume_unconfirmed_blocked_generation(
    db: Session,
    run: KnowledgeGenerationRun,
    job: Job | None,
    *,
    owner_user_id: str,
    agent: Agent,
    set_row: KnowledgeSet,
    agent_md_hash: str,
    source_manifest_json: str,
    source_manifest_hash: str,
) -> bool:
    """Resume only an exact run that stopped before creating a Provider operation."""

    if (
        job is None
        or job.operation != GENERATION_OPERATION
        or job.state != "failed"
        or job.safe_error_code != "provider_confirmation_required"
        or run.state != "blocked"
        or run.safe_error_code != "provider_confirmation_required"
        or run.owner_user_id != owner_user_id
        or run.agent_id != agent.id
        or run.course_id != agent.course_id
        or run.knowledge_set_id != set_row.id
        or run.agent_md_hash != agent_md_hash
        or run.source_manifest_json != source_manifest_json
        or run.source_manifest_hash != source_manifest_hash
        or run.agent_authorization_epoch != agent.authorization_epoch
        or run.set_authorization_epoch != set_row.authorization_epoch
        or run.intent_generation != set_row.generation_intent_seq
        or run.provider_operation_id is not None
        or run.request_hash is not None
    ):
        return False
    if db.scalar(select(ProviderOperation.id).where(ProviderOperation.scope_id == run.id).limit(1)):
        return False
    if not _current_generation_authorized(db, run):
        return False

    timestamp = now_utc()
    run.state = "pending"
    run.safe_error_code = None
    run.claim_token = None
    run.lease_expires_at = None
    run.updated_at = timestamp
    job.state = "pending"
    job.safe_error_code = None
    job.claim_token = None
    job.updated_at = timestamp
    db.flush()
    return True


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
    base_payload = _input_payload(
        agent=agent,
        set_row=set_row,
        agent_md_hash=agent_md_hash,
        source_manifest=source_manifest,
    )
    base_input_key = _sha256(_canonical_json(base_payload))
    action_id = str(uuid5(_GENERATION_SET_NAMESPACE, f"publish:{base_input_key}"))
    existing_run = db.scalar(
        select(KnowledgeGenerationRun).where(
            KnowledgeGenerationRun.knowledge_set_id == set_row.id,
            KnowledgeGenerationRun.action_id == action_id,
        )
    )
    if existing_run is None:
        # Preserve the original K2 content-addressed replay for a run created
        # before action IDs were introduced.
        existing_run = db.scalar(
            select(KnowledgeGenerationRun).where(
                KnowledgeGenerationRun.knowledge_set_id == set_row.id,
                KnowledgeGenerationRun.input_key == base_input_key,
            )
        )
    if existing_run is not None:
        existing_job = db.get(Job, existing_run.job_id)
        if existing_job is None:
            raise RuntimeError("Knowledge generation run lost its Job row.")
        return GenerationEnqueue(existing_run, existing_job, False)

    previous_intent_generation = set_row.generation_intent_seq
    intent_generation = previous_intent_generation + 1
    input_key = _sha256(
        _canonical_json(
            _input_payload(
                agent=agent,
                set_row=set_row,
                agent_md_hash=agent_md_hash,
                source_manifest=source_manifest,
                action_id=action_id,
                intent_generation=intent_generation,
            )
        )
    )
    bumped = db.execute(
        update(KnowledgeSet)
        .where(
            KnowledgeSet.id == set_row.id,
            KnowledgeSet.generation_intent_seq == set_row.generation_intent_seq,
        )
        .values(generation_intent_seq=intent_generation, updated_at=now_utc())
        .execution_options(synchronize_session=False)
    )
    if getattr(bumped, "rowcount", 0) != 1:
        raise conflict(
            "knowledge_generation_intent_stale",
            "A newer Knowledge generation intent was created. Retry the action.",
        )
    set_row.generation_intent_seq = intent_generation

    timestamp = now_utc()
    target_asset_heads_json = _target_asset_heads(db, set_row)
    job_id = str(uuid4())
    run = KnowledgeGenerationRun(
        id=str(uuid4()),
        job_id=job_id,
        input_key=input_key,
        action_id=action_id,
        intent_generation=intent_generation,
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
            db.add(
                KnowledgeGenerationTargetSnapshot(
                    run_id=run.id,
                    asset_heads_json=target_asset_heads_json,
                    created_at=timestamp,
                )
            )
            for receipt_source in source_manifest:
                db.add(
                    KnowledgeGenerationSourceReceipt(
                        id=str(uuid4()),
                        run_id=run.id,
                        source_binding_id=str(receipt_source["binding_id"]),
                        document_id=str(receipt_source["document_id"]),
                        stored_file_id=str(receipt_source["stored_file_id"]),
                        source_content_hash=str(receipt_source["content_hash"]),
                        source_file_sha256=str(receipt_source["file_sha256"]),
                        source_authorization_epoch=int(receipt_source["authorization_epoch"]),
                        source_index_revision=int(receipt_source["index_revision"]),
                        created_at=timestamp,
                    )
                )
            db.flush()
    except IntegrityError as exc:
        existing_run = db.scalar(
            select(KnowledgeGenerationRun).where(
                KnowledgeGenerationRun.knowledge_set_id == set_row.id,
                KnowledgeGenerationRun.action_id == action_id,
            )
        )
        if existing_run is None:
            raise
        existing_job = db.get(Job, existing_run.job_id)
        if existing_job is None:
            raise RuntimeError("Knowledge generation run lost its Job row.") from exc
        return GenerationEnqueue(existing_run, existing_job, False)
    return GenerationEnqueue(run, job, True)


def enqueue_generation_for_existing_set(
    db: Session,
    *,
    set_id: str,
    owner_user_id: str,
    action_id: str,
    allow_empty_blocked: bool = False,
    resume_blocked_unconfirmed: bool = False,
    selected_source_document_ids: list[str] | None = None,
) -> GenerationEnqueue:
    """Enqueue an explicit intent, optionally limited to current Agent sources."""

    set_row = db.scalar(select(KnowledgeSet).where(KnowledgeSet.id == set_id).with_for_update())
    prior_run = db.scalar(
        select(KnowledgeGenerationRun)
        .where(
            KnowledgeGenerationRun.knowledge_set_id == set_id,
            KnowledgeGenerationRun.owner_user_id == owner_user_id,
        )
        .order_by(KnowledgeGenerationRun.created_at.desc(), KnowledgeGenerationRun.id.desc())
        .limit(1)
    )
    if (
        set_row is None
        or set_row.deleted_at is not None
        or set_row.owner_user_id != owner_user_id
        or set_row.ownership_scope != "personal"
        or set_row.group_id is not None
        or prior_run is None
        or prior_run.owner_user_id != owner_user_id
    ):
        raise not_found()
    agent = db.get(Agent, prior_run.agent_id)
    if (
        agent is None
        or agent.deleted_at is not None
        or agent.status != "active"
        or agent.owner_user_id != owner_user_id
        or agent.course_id != set_row.course_id
        or agent.current_published_version_id is None
        or course_member_role(db, owner_user_id, agent.course_id) != "teacher"
        or _agent_workspace_role(db, owner_user_id, agent) != "owner"
    ):
        raise not_found()
    binding = db.get(AgentKnowledgeSet, (agent.id, set_id))
    if binding is None:
        raise not_found()
    version = db.get(AgentVersion, agent.current_published_version_id)
    if version is None or version.agent_id != agent.id or version.state != "published":
        raise not_found()

    bindings = _active_sources(db, set_id)
    if selected_source_document_ids is None:
        source_bindings = bindings
    else:
        current_selection = [document.id for document in _enabled_documents(db, version.id)]
        if selected_source_document_ids != current_selection:
            raise conflict(
                "generation_source_selection_stale",
                "The selected courseware changed before this Agent was finished.",
            )
        active_by_document = {source.document_id: source for source in bindings}
        source_bindings = []
        for document_id in selected_source_document_ids:
            source = active_by_document.get(document_id)
            if source is None:
                raise not_found()
            source_bindings.append(source)

    if not source_bindings and not allow_empty_blocked:
        raise conflict(
            "knowledge_generation_sources_missing",
            "Knowledge cannot be regenerated without an available bound source.",
        )
    source_manifest: list[dict[str, Any]] = []
    for source in source_bindings:
        if not _source_matches_current(db, owner_user_id, source, role="owner", for_write=True):
            raise not_found()
        document = db.get(KnowledgeDocument, source.document_id)
        stored_file = db.get(StoredFile, source.stored_file_id)
        if (
            document is None
            or stored_file is None
            or document.course_id != agent.course_id
            or document.index_status != "ready"
            or stored_file.state != "active"
        ):
            raise not_found()
        source_manifest.append(
            {
                "binding_id": source.id,
                "document_id": source.document_id,
                "stored_file_id": source.stored_file_id,
                "content_hash": source.source_content_hash,
                "file_sha256": source.source_file_sha256,
                "authorization_epoch": source.source_authorization_epoch,
                "index_revision": source.source_index_revision,
                "order_index": source.order_index,
            }
        )
    manifest_json = _canonical_json(source_manifest)
    manifest_hash = _sha256(manifest_json)
    agent_md_hash = _sha256(version.agent_md)
    action_payload_hash = _generation_action_payload_hash(
        agent=agent,
        version=version,
        set_row=set_row,
        agent_md_hash=agent_md_hash,
        source_manifest=source_manifest,
    )
    if resume_blocked_unconfirmed:
        replay = _generation_action_replay(
            db,
            owner_user_id=owner_user_id,
            set_id=set_id,
            action_id=action_id,
            payload_hash=action_payload_hash,
        )
        if replay is not None:
            return replay

    existing = db.scalar(
        select(KnowledgeGenerationRun).where(
            KnowledgeGenerationRun.knowledge_set_id == set_id,
            KnowledgeGenerationRun.action_id == action_id,
        )
    )
    if existing is not None:
        job = db.get(Job, existing.job_id)
        if job is None:
            raise RuntimeError("Knowledge generation run lost its Job row.")
        if not _generation_run_matches_action_payload(
            existing,
            owner_user_id=owner_user_id,
            agent=agent,
            version=version,
            set_row=set_row,
            agent_md_hash=agent_md_hash,
            source_manifest_json=manifest_json,
            source_manifest_hash=manifest_hash,
        ):
            raise conflict(
                "knowledge_generation_action_conflict",
                "This Knowledge generation action is already bound to another request.",
            )
        if resume_blocked_unconfirmed:
            _record_generation_action(
                db,
                owner_user_id=owner_user_id,
                set_id=set_id,
                action_id=action_id,
                payload_hash=action_payload_hash,
                run=existing,
                job=job,
            )
        return GenerationEnqueue(
            existing,
            job,
            False,
            action_id if resume_blocked_unconfirmed else None,
        )

    if resume_blocked_unconfirmed:
        blocked_run = db.scalar(
            select(KnowledgeGenerationRun)
            .where(
                KnowledgeGenerationRun.knowledge_set_id == set_id,
                KnowledgeGenerationRun.owner_user_id == owner_user_id,
                KnowledgeGenerationRun.state == "blocked",
                KnowledgeGenerationRun.safe_error_code == "provider_confirmation_required",
            )
            .order_by(KnowledgeGenerationRun.created_at.desc(), KnowledgeGenerationRun.id.desc())
            .limit(1)
        )
        if blocked_run is not None:
            blocked_job = db.get(Job, blocked_run.job_id)
            if _resume_unconfirmed_blocked_generation(
                db,
                blocked_run,
                blocked_job,
                owner_user_id=owner_user_id,
                agent=agent,
                set_row=set_row,
                agent_md_hash=agent_md_hash,
                source_manifest_json=manifest_json,
                source_manifest_hash=manifest_hash,
            ):
                assert blocked_job is not None
                _record_generation_action(
                    db,
                    owner_user_id=owner_user_id,
                    set_id=set_id,
                    action_id=action_id,
                    payload_hash=action_payload_hash,
                    run=blocked_run,
                    job=blocked_job,
                )
                return GenerationEnqueue(blocked_run, blocked_job, False, action_id)
    previous_intent_generation = set_row.generation_intent_seq
    intent_generation = previous_intent_generation + 1
    input_key = _sha256(
        _canonical_json(
            _input_payload(
                agent=agent,
                set_row=set_row,
                agent_md_hash=agent_md_hash,
                source_manifest=source_manifest,
                action_id=action_id,
                intent_generation=intent_generation,
            )
        )
    )
    blocked_for_missing_sources = not source_manifest
    initial_state = "blocked" if blocked_for_missing_sources else "pending"
    initial_error = "knowledge_generation_sources_missing" if blocked_for_missing_sources else None
    timestamp = now_utc()
    job_id = str(uuid4())
    run = KnowledgeGenerationRun(
        id=str(uuid4()),
        job_id=job_id,
        input_key=input_key,
        action_id=action_id,
        intent_generation=intent_generation,
        owner_user_id=owner_user_id,
        course_id=agent.course_id,
        agent_id=agent.id,
        agent_version_id=version.id,
        knowledge_set_id=set_id,
        agent_md_hash=agent_md_hash,
        agent_authorization_epoch=agent.authorization_epoch,
        set_authorization_epoch=set_row.authorization_epoch,
        source_manifest_json=manifest_json,
        source_manifest_hash=manifest_hash,
        state=initial_state,
        safe_error_code=initial_error,
        claim_token=None,
        lease_expires_at=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    job = Job(
        id=job_id,
        operation=GENERATION_OPERATION,
        state="failed" if blocked_for_missing_sources else "pending",
        idempotency_key=input_key,
        claim_token=None,
        attempt=0,
        safe_error_code=initial_error,
        created_at=timestamp,
        updated_at=timestamp,
    )
    try:
        with db.begin_nested():
            # Reserve the intent in the same SAVEPOINT as the action/run's
            # unique identity. If another request won after our first lookup,
            # the duplicate insert rolls this counter bump back with the run.
            bumped = db.execute(
                update(KnowledgeSet)
                .where(
                    KnowledgeSet.id == set_id,
                    KnowledgeSet.generation_intent_seq == previous_intent_generation,
                )
                .values(generation_intent_seq=intent_generation, updated_at=timestamp)
                .execution_options(synchronize_session=False)
            )
            if getattr(bumped, "rowcount", 0) != 1:
                db.refresh(set_row)
                duplicate_action = db.scalar(
                    select(KnowledgeGenerationRun).where(
                        KnowledgeGenerationRun.knowledge_set_id == set_id,
                        KnowledgeGenerationRun.action_id == action_id,
                    )
                )
                if duplicate_action is not None:
                    duplicate_job = db.get(Job, duplicate_action.job_id)
                    if duplicate_job is None:
                        raise RuntimeError("Knowledge generation run lost its Job row.")
                    if not _generation_run_matches_action_payload(
                        duplicate_action,
                        owner_user_id=owner_user_id,
                        agent=agent,
                        version=version,
                        set_row=set_row,
                        agent_md_hash=agent_md_hash,
                        source_manifest_json=manifest_json,
                        source_manifest_hash=manifest_hash,
                    ):
                        raise conflict(
                            "knowledge_generation_action_conflict",
                            "This Knowledge generation action is already bound to another request.",
                        )
                    if resume_blocked_unconfirmed:
                        _record_generation_action(
                            db,
                            owner_user_id=owner_user_id,
                            set_id=set_id,
                            action_id=action_id,
                            payload_hash=action_payload_hash,
                            run=duplicate_action,
                            job=duplicate_job,
                        )
                    return GenerationEnqueue(
                        duplicate_action,
                        duplicate_job,
                        False,
                        action_id if resume_blocked_unconfirmed else None,
                    )
                raise conflict(
                    "knowledge_generation_intent_stale",
                    "A newer Knowledge generation intent was created. Retry the action.",
                )
            db.add(job)
            db.add(run)
            db.flush()
            db.add(
                KnowledgeGenerationTargetSnapshot(
                    run_id=run.id,
                    asset_heads_json=_target_asset_heads(db, set_row),
                    created_at=timestamp,
                )
            )
            for receipt_source in source_manifest:
                db.add(
                    KnowledgeGenerationSourceReceipt(
                        id=str(uuid4()),
                        run_id=run.id,
                        source_binding_id=str(receipt_source["binding_id"]),
                        document_id=str(receipt_source["document_id"]),
                        stored_file_id=str(receipt_source["stored_file_id"]),
                        source_content_hash=str(receipt_source["content_hash"]),
                        source_file_sha256=str(receipt_source["file_sha256"]),
                        source_authorization_epoch=int(receipt_source["authorization_epoch"]),
                        source_index_revision=int(receipt_source["index_revision"]),
                        created_at=timestamp,
                    )
                )
            db.flush()
    except IntegrityError:
        # The duplicate-action winner owns the current intent. Refresh the
        # identity map after the SAVEPOINT rolled back the losing bump.
        db.refresh(set_row)
        existing = db.scalar(
            select(KnowledgeGenerationRun).where(
                KnowledgeGenerationRun.knowledge_set_id == set_id,
                KnowledgeGenerationRun.action_id == action_id,
            )
        )
        if existing is None:
            raise
        existing_job = db.get(Job, existing.job_id)
        if existing_job is None:
            raise RuntimeError("Knowledge generation run lost its Job row.") from None
        if not _generation_run_matches_action_payload(
            existing,
            owner_user_id=owner_user_id,
            agent=agent,
            version=version,
            set_row=set_row,
            agent_md_hash=agent_md_hash,
            source_manifest_json=manifest_json,
            source_manifest_hash=manifest_hash,
        ):
            raise conflict(
                "knowledge_generation_action_conflict",
                "This Knowledge generation action is already bound to another request.",
            ) from None
        if resume_blocked_unconfirmed:
            _record_generation_action(
                db,
                owner_user_id=owner_user_id,
                set_id=set_id,
                action_id=action_id,
                payload_hash=action_payload_hash,
                run=existing,
                job=existing_job,
            )
        return GenerationEnqueue(
            existing,
            existing_job,
            False,
            action_id if resume_blocked_unconfirmed else None,
        )
    set_row.generation_intent_seq = intent_generation
    set_row.updated_at = timestamp
    if resume_blocked_unconfirmed:
        _record_generation_action(
            db,
            owner_user_id=owner_user_id,
            set_id=set_id,
            action_id=action_id,
            payload_hash=action_payload_hash,
            run=run,
            job=job,
        )
    return GenerationEnqueue(run, job, True, action_id if resume_blocked_unconfirmed else None)


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
            or binding.order_index != item.get("order_index")
        ):
            return None
        document = db.get(KnowledgeDocument, binding.document_id)
        stored_file = db.get(StoredFile, binding.stored_file_id)
        if (
            document is None
            or stored_file is None
            or document.course_id != run.course_id
            or document.stored_file_id != binding.stored_file_id
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
        source_head_is_exact = (
            binding.stored_file_id == item.get("stored_file_id")
            and binding.source_file_sha256 == item.get("file_sha256")
            and binding.source_content_hash == item.get("content_hash")
            and binding.source_authorization_epoch == item.get("authorization_epoch")
            and binding.source_index_revision == item.get("index_revision")
        )
        if source_head_is_exact:
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
            continue

        # Newline/byte-representation-only saves may retain a generation
        # intent: the normalized indexed content, revision and current ACL
        # must be identical, and the old manifest file/hash must be proven by
        # an immutable KnowledgeDocumentVersion row.
        historical = db.scalar(
            select(KnowledgeDocumentVersion.id).where(
                KnowledgeDocumentVersion.document_id == binding.document_id,
                KnowledgeDocumentVersion.stored_file_id == item.get("stored_file_id"),
                KnowledgeDocumentVersion.content_hash == item.get("content_hash"),
                KnowledgeDocumentVersion.file_sha256 == item.get("file_sha256"),
                KnowledgeDocumentVersion.authorization_epoch == item.get("authorization_epoch"),
                KnowledgeDocumentVersion.index_revision == item.get("index_revision"),
            )
        )
        if (
            historical is None
            or document.content_hash != item.get("content_hash")
            or binding.source_content_hash != item.get("content_hash")
            or document.authorization_epoch != item.get("authorization_epoch")
            or binding.source_authorization_epoch != item.get("authorization_epoch")
            or document.index_revision != item.get("index_revision")
            or binding.source_index_revision != item.get("index_revision")
        ):
            return None
        # Keep the exact frozen source manifest identity so its accepted
        # Provider input remains auditable and does not imply a fresh charge.
        result.append(item)
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
        or set_row.generation_intent_seq != run.intent_generation
    ):
        return False
    current_manifest = _current_source_manifest(db, run, agent, set_row)
    if current_manifest is None:
        return False
    if _sha256(_canonical_json(current_manifest)) != run.source_manifest_hash:
        return False
    current_payload = _input_payload(
        agent=agent,
        set_row=set_row,
        agent_md_hash=run.agent_md_hash,
        source_manifest=current_manifest,
        action_id=run.action_id,
        intent_generation=run.intent_generation,
    )
    if _sha256(_canonical_json(current_payload)) == run.input_key:
        return True
    # Runs created before action identity was added retain their exact old
    # input hash and remain recoverable until a newer intent/source fences them.
    if run.action_id == run.id and run.intent_generation == 0:
        legacy_payload = _input_payload(
            agent=agent,
            set_row=set_row,
            agent_md_hash=run.agent_md_hash,
            source_manifest=current_manifest,
        )
        return _sha256(_canonical_json(legacy_payload)) == run.input_key
    return False


def current_generation_authorized_on_connection(
    connection: Connection,
    run_id: str,
    claim_token: str,
) -> bool:
    """Evaluate current owner/source ACLs inside a caller's write transaction."""

    # A SAVEPOINT keeps this short-lived ORM view from taking ownership of the
    # outer provider-ledger transaction while making its reads share the same
    # snapshot and SQLite writer lock.
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        return bool(
            run is not None
            and run.state == "running"
            and run.claim_token == claim_token
            and _current_generation_authorized(db, run)
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
    """Reconcile interrupted K2b runs with the Provider ledger, never resend.

    A claim with no prepared operation, or one whose operation is still only
    prepared, can be reclaimed because no request crossed the dispatch fence.
    Reserved operations become ``not_sent`` in Provider startup recovery and
    are terminal for this one-shot intent; sending operations become unknown.
    An accepted operation is usable only when its canonical stage was committed
    atomically with acceptance.
    """

    db.rollback()
    _start_immediate(db)
    rows = db.scalars(
        select(KnowledgeGenerationRun).where(KnowledgeGenerationRun.state == "running")
    ).all()
    now = now_utc()
    for run in rows:
        job = db.get(Job, run.job_id)
        operation = (
            db.get(ProviderOperation, run.provider_operation_id)
            if run.provider_operation_id is not None
            else None
        )
        accepted_stage = db.get(KnowledgeGenerationAcceptedStage, run.id)
        safe_error_code: str | None = None
        if operation is not None:
            if operation.provider_operation != "llm_knowledge_generate":
                safe_error_code = "knowledge_generation_ledger_invalid"
            elif operation.state == "prepared":
                pass
            elif operation.state == "accepted" and accepted_stage is not None:
                if accepted_stage.safe_error_code is not None:
                    safe_error_code = accepted_stage.safe_error_code
                elif (
                    accepted_stage.canonical_stage_json is not None
                    and _current_generation_authorized(db, run)
                ):
                    safe_error_code = "accepted_stage_ready"
                else:
                    safe_error_code = "authorization_revoked"
            else:
                safe_error_code = operation.safe_error_code or {
                    "reserved": "knowledge_generation_not_sent",
                    "not_sent": "knowledge_generation_not_sent",
                    "sending": "acceptance_unknown",
                    "acceptance_unknown": "acceptance_unknown",
                    "failed": "provider_failed",
                    "abandoned": "provider_abandoned",
                    "succeeded": "knowledge_generation_stage_missing",
                }.get(operation.state, "knowledge_generation_recovery_blocked")

        run.claim_token = None
        run.lease_expires_at = None
        run.updated_at = now
        if job is not None and job.operation == GENERATION_OPERATION:
            job.claim_token = None
            job.updated_at = now
        if safe_error_code is None or safe_error_code == "accepted_stage_ready":
            run.state = "pending"
            run.safe_error_code = None
            if job is not None and job.operation == GENERATION_OPERATION:
                job.state = "pending"
                job.safe_error_code = None
        else:
            run.state = "blocked"
            run.safe_error_code = safe_error_code
            if job is not None and job.operation == GENERATION_OPERATION:
                job.state = "failed"
                job.safe_error_code = safe_error_code
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
    stage = db.get(KnowledgeGenerationAcceptedStage, run.id)
    item_states = db.scalars(
        select(KnowledgeGenerationItem.state).where(KnowledgeGenerationItem.run_id == run.id)
    ).all()
    return KnowledgeGenerationStatus(
        run_id=UUID(run.id),
        job_id=UUID(run.job_id),
        knowledge_set_id=UUID(run.knowledge_set_id),
        state=cast(_GenerationState, state),
        provider_manifest_hash=run.provider_manifest_hash,
        safe_error_code=error_code,
        accepted_item_count=(
            stage.item_count if stage is not None and stage.canonical_stage_json is not None else 0
        ),
        materialized_item_count=sum(1 for item_state in item_states if item_state == "applied"),
        failed_item_count=sum(
            1 for item_state in item_states if item_state in {"failed", "skipped"}
        ),
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
