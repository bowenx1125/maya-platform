"""HTTP routes for versioned manual Knowledge Set assets."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import Error, PlatformError
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import (
    abandon_claim,
    assert_claim_owned,
    claim_idempotency,
    finish_idempotency,
    parse_json_payload_hash,
)
from app.modules.knowledge_sets import service
from app.modules.knowledge_sets.generation import get_generation_status
from app.modules.knowledge_sets.schemas import (
    AgentKnowledgeSets,
    AssetVersionFullDTO,
    AssetVersionStudentDTO,
    CreateKnowledgeAssetRequest,
    CreateKnowledgeSetRequest,
    DeleteKnowledgeSetRequest,
    KnowledgeAssetDTO,
    KnowledgeAssetFullDTO,
    KnowledgeAssetStudentDTO,
    KnowledgeAssetVersionHistoryFull,
    KnowledgeAssetVersionHistoryStudent,
    KnowledgeGenerationStatus,
    KnowledgeGraph,
    KnowledgeSetDetail,
    KnowledgeSetRevocation,
    KnowledgeSetSourceDTO,
    KnowledgeSetSummary,
    RemoveKnowledgeSetSourceRequest,
    ReplaceAgentKnowledgeSetsRequest,
    ReplaceKnowledgeSetSourcesRequest,
    UpdateKnowledgeAssetRequest,
    UpdateKnowledgeSetRequest,
)

router = APIRouter(tags=["knowledge-sets"])


@router.get(
    "/knowledge-generation-jobs/{job_id}",
    response_model=KnowledgeGenerationStatus,
    operation_id="getKnowledgeGenerationJob",
    responses={404: {"model": Error, "description": "Job not found."}},
)
def get_knowledge_generation_job(
    job_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> KnowledgeGenerationStatus:
    """Expose safe generation state to the current Teacher owner only."""

    return get_generation_status(db, context, str(job_id))


def _idempotent_mutation[T: BaseModel](
    db: Session,
    context: AuthContext,
    *,
    operation_id: str,
    idempotency_key: str,
    scope: list[str],
    payload: BaseModel,
    status_code: int,
    response_model: type[T],
    operation: Callable[[], T],
    replay: Callable[[dict[str, Any]], T],
    preserve_replay_body: bool = False,
) -> T:
    body_hash = parse_json_payload_hash(
        operation_id,
        context,
        scope,
        payload.model_dump(mode="json"),
    )
    record, cached = claim_idempotency(db, context, operation_id, idempotency_key, body_hash)
    if cached is not None:
        replayed = replay(json.loads(bytes(cached.body)))
        if preserve_replay_body:
            # Asset ACL/source checks above must run on every retry, while
            # accepted JSON values and timestamp spellings remain stable.
            return cast(T, cached)
        return response_model.model_validate(replayed.model_dump(mode="json"))
    try:
        assert_claim_owned(db, record)
        result = operation()
        finish_idempotency(db, record, status_code, result.model_dump(mode="json"))
        db.commit()
        return response_model.model_validate(result.model_dump(mode="json"))
    except Exception:
        abandon_claim(db, record)
        raise


def _replay_set_detail(
    db: Session, context: AuthContext, response_body: dict[str, Any]
) -> KnowledgeSetDetail:
    saved = KnowledgeSetDetail.model_validate(response_body)
    current = service.get_knowledge_set(db, context, str(saved.id))
    current_sources = {str(source.id): source for source in current.sources}
    sources: list[KnowledgeSetSourceDTO] = []
    for source in saved.sources:
        live = current_sources.get(str(source.id))
        if live is not None and live.available:
            sources.append(source)
        elif live is not None:
            sources.append(live)
        else:
            sources.append(
                KnowledgeSetSourceDTO(
                    id=source.id,
                    document_id=None,
                    source_filename=None,
                    char_count=None,
                    content_hash=None,
                    authorization_epoch=None,
                    order_index=source.order_index,
                    is_active=False,
                    available=False,
                )
            )
    return saved.model_copy(update={"sources": sources})


def _replay_agent_sets(
    db: Session,
    context: AuthContext,
    agent_id: UUID,
    response_body: dict[str, Any],
) -> AgentKnowledgeSets:
    saved = AgentKnowledgeSets.model_validate(response_body)
    # Re-check current Agent ACL, then replay the original Set binding result
    # only for Sets the caller can still read. Binding edits after the first
    # request do not rewrite an already-completed idempotency result.
    service.get_agent_knowledge_sets(db, context, str(agent_id))
    readable_ids: set[str] = set()
    for row in saved.sets:
        try:
            service.get_knowledge_set(db, context, str(row.id))
        except PlatformError as error:
            if error.status_code != 404:
                raise
        else:
            readable_ids.add(str(row.id))
    return saved.model_copy(
        update={"sets": [row for row in saved.sets if str(row.id) in readable_ids]}
    )


def _replay_set_revocation(
    db: Session, context: AuthContext, response_body: dict[str, Any]
) -> KnowledgeSetRevocation:
    return service.replay_knowledge_set_revocation(
        db, context, KnowledgeSetRevocation.model_validate(response_body)
    )


@router.get(
    "/courses/{course_id}/knowledge-sets",
    response_model=list[KnowledgeSetSummary],
    operation_id="listKnowledgeSets",
    responses={404: {"model": Error, "description": "Course not found."}},
)
def list_knowledge_sets(
    course_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[KnowledgeSetSummary]:
    return service.list_knowledge_sets(db, context, str(course_id))


@router.post(
    "/courses/{course_id}/knowledge-sets",
    response_model=KnowledgeSetDetail,
    status_code=201,
    operation_id="createKnowledgeSet",
    responses={
        201: {"model": KnowledgeSetDetail, "description": "Knowledge Set created."},
        404: {"model": Error, "description": "Course or group not found."},
        422: {"model": Error, "description": "Invalid Set name or scope."},
    },
)
def create_knowledge_set(
    course_id: UUID,
    payload: CreateKnowledgeSetRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> KnowledgeSetDetail:
    return _idempotent_mutation(
        db,
        context,
        operation_id="createKnowledgeSet",
        idempotency_key=idempotency_key,
        scope=[str(course_id)],
        payload=payload,
        status_code=201,
        response_model=KnowledgeSetDetail,
        operation=lambda: service.create_knowledge_set(db, context, str(course_id), payload),
        replay=lambda body: _replay_set_detail(db, context, body),
    )


@router.get(
    "/knowledge-sets/{set_id}",
    response_model=KnowledgeSetDetail,
    operation_id="getKnowledgeSet",
    responses={404: {"model": Error, "description": "Knowledge Set not found."}},
)
def get_knowledge_set(
    set_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> KnowledgeSetDetail:
    return service.get_knowledge_set(db, context, str(set_id))


@router.patch(
    "/knowledge-sets/{set_id}",
    response_model=KnowledgeSetDetail,
    operation_id="updateKnowledgeSetMetadata",
    responses={
        404: {"model": Error, "description": "Knowledge Set not found."},
        409: {"model": Error, "description": "Metadata revision is stale."},
        422: {"model": Error, "description": "Invalid Set metadata or source visibility."},
    },
)
def update_knowledge_set(
    set_id: UUID,
    payload: UpdateKnowledgeSetRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> KnowledgeSetDetail:
    return _idempotent_mutation(
        db,
        context,
        operation_id="updateKnowledgeSetMetadata",
        idempotency_key=idempotency_key,
        scope=[str(set_id)],
        payload=payload,
        status_code=200,
        response_model=KnowledgeSetDetail,
        operation=lambda: service.update_knowledge_set(
            db,
            context,
            str(set_id),
            expected_metadata_revision=payload.expected_metadata_revision,
            display_name=payload.display_name,
            visibility=payload.visibility,
        ),
        replay=lambda body: _replay_set_detail(db, context, body),
    )


@router.delete(
    "/knowledge-sets/{set_id}",
    response_model=KnowledgeSetRevocation,
    operation_id="deleteKnowledgeSet",
    responses={
        200: {"model": KnowledgeSetRevocation, "description": "Knowledge Set revoked."},
        404: {"model": Error, "description": "Knowledge Set not found."},
        409: {"model": Error, "description": "Set metadata or content revision is stale."},
    },
)
def delete_knowledge_set(
    set_id: UUID,
    payload: DeleteKnowledgeSetRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> KnowledgeSetRevocation:
    return _idempotent_mutation(
        db,
        context,
        operation_id="deleteKnowledgeSet",
        idempotency_key=idempotency_key,
        scope=[str(set_id)],
        payload=payload,
        status_code=200,
        response_model=KnowledgeSetRevocation,
        operation=lambda: service.delete_knowledge_set(
            db,
            context,
            str(set_id),
            expected_metadata_revision=payload.expected_metadata_revision,
            expected_content_revision=payload.expected_content_revision,
        ),
        replay=lambda body: _replay_set_revocation(db, context, body),
    )


@router.put(
    "/knowledge-sets/{set_id}/sources",
    response_model=KnowledgeSetDetail,
    operation_id="replaceKnowledgeSetSources",
    responses={
        404: {"model": Error, "description": "Set or source not found."},
        409: {"model": Error, "description": "Set content revision is stale."},
        422: {"model": Error, "description": "Invalid or unauthorized source selection."},
    },
)
def replace_knowledge_set_sources(
    set_id: UUID,
    payload: ReplaceKnowledgeSetSourcesRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> KnowledgeSetDetail:
    return _idempotent_mutation(
        db,
        context,
        operation_id="replaceKnowledgeSetSources",
        idempotency_key=idempotency_key,
        scope=[str(set_id)],
        payload=payload,
        status_code=200,
        response_model=KnowledgeSetDetail,
        operation=lambda: service.replace_knowledge_set_sources(
            db,
            context,
            str(set_id),
            expected_content_revision=payload.expected_content_revision,
            source_document_ids=payload.source_document_ids,
        ),
        replay=lambda body: _replay_set_detail(db, context, body),
    )


@router.delete(
    "/knowledge-sets/{set_id}/sources/{binding_id}",
    response_model=KnowledgeSetDetail,
    operation_id="removeKnowledgeSetSource",
    responses={
        404: {"model": Error, "description": "Set or source binding not found."},
        409: {"model": Error, "description": "Set content revision is stale."},
    },
)
def remove_knowledge_set_source(
    set_id: UUID,
    binding_id: UUID,
    payload: RemoveKnowledgeSetSourceRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> KnowledgeSetDetail:
    return _idempotent_mutation(
        db,
        context,
        operation_id="removeKnowledgeSetSource",
        idempotency_key=idempotency_key,
        scope=[str(set_id), str(binding_id)],
        payload=payload,
        status_code=200,
        response_model=KnowledgeSetDetail,
        operation=lambda: service.remove_knowledge_set_source(
            db,
            context,
            str(set_id),
            str(binding_id),
            expected_content_revision=payload.expected_content_revision,
        ),
        replay=lambda body: _replay_set_detail(db, context, body),
    )


@router.get(
    "/knowledge-sets/{set_id}/assets",
    response_model=list[KnowledgeAssetDTO],
    operation_id="listKnowledgeSetAssets",
    responses={404: {"model": Error, "description": "Knowledge Set not found."}},
)
def list_knowledge_set_assets(
    set_id: UUID,
    kind: Literal["concept", "question", "note"] | None = Query(default=None),
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[KnowledgeAssetFullDTO | KnowledgeAssetStudentDTO]:
    return service.list_knowledge_assets(db, context, str(set_id), kind=kind)


@router.post(
    "/knowledge-sets/{set_id}/assets",
    response_model=KnowledgeAssetFullDTO,
    status_code=201,
    operation_id="createKnowledgeSetAsset",
    responses={
        201: {"model": KnowledgeAssetFullDTO, "description": "Asset saved as version 1."},
        404: {"model": Error, "description": "Knowledge Set or referenced resource not found."},
        409: {"model": Error, "description": "Set content revision is stale."},
        422: {"model": Error, "description": "Invalid asset content or source reference."},
    },
)
def create_knowledge_set_asset(
    set_id: UUID,
    payload: CreateKnowledgeAssetRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> KnowledgeAssetFullDTO:
    return _idempotent_mutation(
        db,
        context,
        operation_id="createKnowledgeSetAsset",
        idempotency_key=idempotency_key,
        scope=[str(set_id)],
        payload=payload,
        status_code=201,
        response_model=KnowledgeAssetFullDTO,
        operation=lambda: service.create_knowledge_asset(
            db,
            context,
            str(set_id),
            expected_content_revision=payload.expected_content_revision,
            content=payload.content,
            data_root=settings.resolved_data_root,
        ),
        replay=lambda body: service.get_knowledge_asset_version(
            db,
            context,
            str(body["id"]),
            int(body["current_version_seq"]),
        ),
        preserve_replay_body=True,
    )


@router.get(
    "/knowledge-assets/{asset_id}",
    response_model=KnowledgeAssetDTO,
    operation_id="getKnowledgeSetAsset",
    responses={404: {"model": Error, "description": "Knowledge Asset not found."}},
)
def get_knowledge_set_asset(
    asset_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> KnowledgeAssetFullDTO | KnowledgeAssetStudentDTO:
    return service.get_knowledge_asset(db, context, str(asset_id))


@router.patch(
    "/knowledge-assets/{asset_id}",
    response_model=KnowledgeAssetFullDTO,
    operation_id="updateKnowledgeSetAsset",
    responses={
        404: {"model": Error, "description": "Knowledge Asset not found."},
        409: {"model": Error, "description": "Asset or Set revision is stale."},
        422: {"model": Error, "description": "Invalid asset content or source reference."},
    },
)
def update_knowledge_set_asset(
    asset_id: UUID,
    payload: UpdateKnowledgeAssetRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> KnowledgeAssetFullDTO:
    return _idempotent_mutation(
        db,
        context,
        operation_id="updateKnowledgeSetAsset",
        idempotency_key=idempotency_key,
        scope=[str(asset_id)],
        payload=payload,
        status_code=200,
        response_model=KnowledgeAssetFullDTO,
        operation=lambda: service.update_knowledge_asset(
            db,
            context,
            str(asset_id),
            expected_content_revision=payload.expected_content_revision,
            expected_asset_version_seq=payload.expected_asset_version_seq,
            content=payload.content,
            data_root=settings.resolved_data_root,
        ),
        replay=lambda body: service.get_knowledge_asset_version(
            db,
            context,
            str(body["id"]),
            int(body["current_version_seq"]),
        ),
        preserve_replay_body=True,
    )


@router.get(
    "/knowledge-assets/{asset_id}/versions",
    response_model=KnowledgeAssetVersionHistoryFull | KnowledgeAssetVersionHistoryStudent,
    operation_id="listKnowledgeSetAssetVersions",
    responses={404: {"model": Error, "description": "Knowledge Asset not found."}},
)
def list_knowledge_set_asset_versions(
    asset_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> KnowledgeAssetVersionHistoryFull | KnowledgeAssetVersionHistoryStudent:
    resolved_asset_id, versions = service.list_knowledge_asset_versions(db, context, str(asset_id))
    if versions and isinstance(versions[0], AssetVersionStudentDTO):
        return KnowledgeAssetVersionHistoryStudent(
            audience="student",
            asset_id=UUID(resolved_asset_id),
            versions=versions,
        )
    return KnowledgeAssetVersionHistoryFull(
        audience="full",
        asset_id=UUID(resolved_asset_id),
        versions=cast(list[AssetVersionFullDTO], versions),
    )


@router.get(
    "/knowledge-sets/{set_id}/graph",
    response_model=KnowledgeGraph,
    operation_id="getKnowledgeSetGraph",
    responses={404: {"model": Error, "description": "Knowledge Set not found."}},
)
def get_knowledge_set_graph(
    set_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> KnowledgeGraph:
    return service.get_knowledge_graph(db, context, str(set_id))


@router.get(
    "/agents/{agent_id}/knowledge-sets",
    response_model=AgentKnowledgeSets,
    operation_id="getAgentKnowledgeSets",
    responses={404: {"model": Error, "description": "Agent not found."}},
)
def get_agent_knowledge_sets(
    agent_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> AgentKnowledgeSets:
    revision, sets = service.get_agent_knowledge_sets(db, context, str(agent_id))
    return AgentKnowledgeSets(
        agent_id=agent_id,
        agent_metadata_revision=revision,
        sets=sets,
    )


@router.put(
    "/agents/{agent_id}/knowledge-sets",
    response_model=AgentKnowledgeSets,
    operation_id="replaceAgentKnowledgeSets",
    responses={
        404: {"model": Error, "description": "Agent or Knowledge Set not found."},
        409: {"model": Error, "description": "Agent metadata revision is stale."},
        422: {"model": Error, "description": "Invalid or unauthorized Set binding."},
    },
)
def replace_agent_knowledge_sets(
    agent_id: UUID,
    payload: ReplaceAgentKnowledgeSetsRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> AgentKnowledgeSets:
    return _idempotent_mutation(
        db,
        context,
        operation_id="replaceAgentKnowledgeSets",
        idempotency_key=idempotency_key,
        scope=[str(agent_id)],
        payload=payload,
        status_code=200,
        response_model=AgentKnowledgeSets,
        operation=lambda: _agent_sets_result(
            db,
            context,
            agent_id,
            payload.expected_agent_metadata_revision,
            payload.set_ids,
        ),
        replay=lambda body: _replay_agent_sets(db, context, agent_id, body),
    )


def _agent_sets_result(
    db: Session,
    context: AuthContext,
    agent_id: UUID,
    expected_metadata_revision: int,
    set_ids: list[UUID],
) -> AgentKnowledgeSets:
    revision, sets = service.replace_agent_knowledge_sets(
        db,
        context,
        str(agent_id),
        expected_agent_metadata_revision=expected_metadata_revision,
        set_ids=set_ids,
    )
    return AgentKnowledgeSets(
        agent_id=agent_id,
        agent_metadata_revision=revision,
        sets=sets,
    )


def _get_agent_sets_result(db: Session, context: AuthContext, agent_id: UUID) -> AgentKnowledgeSets:
    revision, sets = service.get_agent_knowledge_sets(db, context, str(agent_id))
    return AgentKnowledgeSets(
        agent_id=agent_id,
        agent_metadata_revision=revision,
        sets=sets,
    )
