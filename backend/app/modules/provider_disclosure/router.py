"""Standalone teacher routes for ProviderDataCallV1 disclosure."""

from __future__ import annotations

from datetime import UTC
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import Error, PlatformError, conflict, forbidden, invalid_state, not_found
from app.core.models import Job, ProviderExportManifest
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext
from app.modules.knowledge_sets.generation import GENERATION_OPERATION
from app.modules.knowledge_sets.models import KnowledgeGenerationRun
from app.modules.workspace.access import course_member

from .schemas import (
    ProviderDataCallConfirmationRequestV1,
    ProviderDataCallDebateManifestListResponseV1,
    ProviderDataCallDisclosureResponseV1,
    ProviderDataCallManifestListResponseV1,
    ProviderDataCallPublicationManifestListResponseV1,
    TeamStandingGrantConfirmationRequestV1,
    TeamStandingGrantConfirmationV1,
    TeamStandingGrantPreviewV1,
    TeamStandingGrantRequestV1,
)
from .service import (
    ProviderDisclosureError,
    ProviderDisclosureService,
    prepare_chat_standing_disclosure,
)
from .team_standing import StandingGrantPlan

router = APIRouter(prefix="/provider/data-call", tags=["Provider"])


def get_provider_disclosure_service(request: Request) -> ProviderDisclosureService:
    """Resolve the app-provided service without composing a provider here."""

    service = getattr(request.app.state, "provider_disclosure_service", None)
    if service is None or any(
        not callable(getattr(service, method, None))
        for method in (
            "disclose",
            "confirm",
            "list_embedding_query_manifests",
            "list_embedding_manifests_for_agent_version",
            "list_llm_manifests_for_debate",
        )
    ):
        raise invalid_state("Provider disclosure is not configured.")
    return cast(ProviderDisclosureService, service)


def _raise_domain_error(error: ProviderDisclosureError) -> None:
    if error.code == "not_found":
        raise not_found()
    if error.code == "forbidden":
        raise forbidden()
    if error.code in {"provider_preflight_stale", "provider_confirmation_conflict"}:
        raise conflict("provider_preflight_stale", "Provider disclosure confirmation is stale.")
    if error.code == "provider_confirmation_required":
        raise conflict(
            "provider_confirmation_required",
            "Confirm the exact provider disclosure before any external request.",
        )
    raise PlatformError(
        error.code if error.code.startswith("provider_") else "provider_preflight_blocked",
        "Provider preflight is unavailable until every account and privacy control is verified.",
        422,
    )


def _disclose(
    service: ProviderDisclosureService,
    context: AuthContext,
    manifest_hash: str,
) -> ProviderDataCallDisclosureResponseV1:
    try:
        return service.disclose(str(context.user.id), manifest_ref=manifest_hash)
    except ProviderDisclosureError as error:
        _raise_domain_error(error)
    raise AssertionError("unreachable")  # pragma: no cover


def _team_standing_preview(
    payload: TeamStandingGrantRequestV1,
    plan: StandingGrantPlan,
) -> TeamStandingGrantPreviewV1:
    safe = plan.safe_disclosure
    return TeamStandingGrantPreviewV1(
        team_version_id=payload.team_version_id,
        policy_hash=payload.policy_hash,
        resource_hash=plan.resource_hash,
        team_epoch=plan.team_epoch,
        publication_epoch=plan.publication_epoch,
        member_count=int(safe["member_count"]),
        knowledge_set_count=int(safe["knowledge_set_count"]),
        source_count=int(safe["source_count"]),
    )


@router.post(
    "/team-standing-grants/preview",
    response_model=TeamStandingGrantPreviewV1,
    operation_id="previewTeamProviderStandingGrant",
    responses={
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
def preview_team_provider_standing_grant(
    payload: TeamStandingGrantRequestV1,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> TeamStandingGrantPreviewV1:
    from .team_standing import prepare_team_standing_grant

    plan = prepare_team_standing_grant(
        db,
        context,
        team_version_id=payload.team_version_id,
        policy_hash=payload.policy_hash,
        provider_operation=payload.provider_operation,
    )
    return _team_standing_preview(payload, plan)


@router.post(
    "/team-standing-grants/confirm",
    response_model=TeamStandingGrantConfirmationV1,
    operation_id="confirmTeamProviderStandingGrant",
    responses={
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
def confirm_team_provider_standing_grant(
    payload: TeamStandingGrantConfirmationRequestV1,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> TeamStandingGrantConfirmationV1:
    from .team_standing import (
        confirm_team_standing_grant,
        prepare_team_standing_grant,
    )

    grant = confirm_team_standing_grant(
        db,
        context,
        team_version_id=payload.team_version_id,
        policy_hash=payload.policy_hash,
        provider_operation=payload.provider_operation,
        expected_resource_hash=payload.expected_resource_hash,
        expected_team_epoch=payload.expected_team_epoch,
        expected_publication_epoch=payload.expected_publication_epoch,
    )
    plan = prepare_team_standing_grant(
        db,
        context,
        team_version_id=payload.team_version_id,
        policy_hash=payload.policy_hash,
        provider_operation=payload.provider_operation,
    )
    preview = _team_standing_preview(payload, plan)
    db.commit()
    confirmed_at = grant.confirmed_at
    if confirmed_at.tzinfo is None:
        confirmed_at = confirmed_at.replace(tzinfo=UTC)
    else:
        confirmed_at = confirmed_at.astimezone(UTC)
    return TeamStandingGrantConfirmationV1(
        **preview.model_dump(),
        standing_grant_id=grant.id,
        confirmed_at=confirmed_at.isoformat(),
    )


@router.get(
    "/disclosure",
    response_model=ProviderDataCallDisclosureResponseV1,
    operation_id="getProviderDataCallDisclosure",
    responses={
        401: {"model": Error, "description": "Authentication is required."},
        403: {"model": Error, "description": "Teacher authorization is required."},
        404: {"model": Error, "description": "Provider disclosure is unavailable."},
        409: {"model": Error, "description": "Provider disclosure is stale."},
        422: {"model": Error, "description": "Provider preflight is blocked."},
    },
)
def provider_data_call_disclosure(
    manifest_hash: str = Query(..., pattern=r"^[0-9a-f]{64}$"),
    context: AuthContext = Depends(require_auth),
    service: ProviderDisclosureService = Depends(get_provider_disclosure_service),
) -> ProviderDataCallDisclosureResponseV1:
    return _disclose(service, context, manifest_hash)


@router.get(
    "/chat-standing/disclosure",
    response_model=ProviderDataCallDisclosureResponseV1,
    operation_id="getChatStandingProviderDisclosure",
    responses={
        401: {"model": Error, "description": "Authentication is required."},
        403: {"model": Error, "description": "A course Teacher is required."},
        404: {"model": Error, "description": "Course or Provider policy was not found."},
        409: {"model": Error, "description": "Provider policy is stale."},
        422: {"model": Error, "description": "Provider disclosure could not be prepared."},
    },
)
def chat_standing_provider_disclosure(
    course_id: UUID = Query(...),
    provider_operation: Literal["llm_agent_chat", "embedding_query"] = Query(
        default="llm_agent_chat"
    ),
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProviderDataCallDisclosureResponseV1:
    """Create/reuse a static course Chat disclosure, with no student Chat inputs."""

    course = str(course_id)
    course_member(db, context, course, teacher=True)
    policy_component = "llm" if provider_operation == "llm_agent_chat" else "embedding"
    policy_hash = settings.provider_policy_hash_for(policy_component)
    if policy_hash is None:
        raise PlatformError("provider_preflight_blocked", "Provider policy is unavailable.", 409)
    db.commit()
    try:
        return prepare_chat_standing_disclosure(
            db,
            actor_user_id=str(context.user.id),
            course_id=course,
            policy_hash=policy_hash,
            provider_operation=provider_operation,
        )
    except ProviderDisclosureError as error:
        _raise_domain_error(error)
    raise AssertionError("unreachable")  # pragma: no cover


@router.get(
    "/pending",
    response_model=ProviderDataCallManifestListResponseV1,
    operation_id="listProviderDataCallManifests",
    responses={
        401: {"model": Error, "description": "Authentication is required."},
        403: {"model": Error, "description": "Teacher authorization is required."},
        404: {"model": Error, "description": "Provider export scope was not found."},
        422: {"model": Error, "description": "Provider manifest listing is blocked."},
    },
)
def provider_data_call_manifests(
    scope_id: str = Query(..., min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_.:-]+$"),
    context: AuthContext = Depends(require_auth),
    service: ProviderDisclosureService = Depends(get_provider_disclosure_service),
) -> ProviderDataCallManifestListResponseV1:
    """List teacher-visible ``embedding_query`` manifests for one scope."""

    try:
        return service.list_embedding_query_manifests(
            str(context.user.id),
            scope_id=scope_id,
        )
    except ProviderDisclosureError as error:
        _raise_domain_error(error)
    raise AssertionError("unreachable")  # pragma: no cover


@router.get(
    "/pending/agent-versions/{agent_version_id}",
    response_model=ProviderDataCallPublicationManifestListResponseV1,
    operation_id="listProviderDataCallPublicationManifests",
    responses={
        401: {"model": Error, "description": "Authentication is required."},
        403: {"model": Error, "description": "Teacher authorization is required."},
        404: {"model": Error, "description": "AgentVersion was not found."},
        422: {"model": Error, "description": "Provider manifest listing is blocked."},
    },
)
def provider_data_call_agent_version_manifests(
    agent_version_id: str = Path(
        ...,
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    ),
    context: AuthContext = Depends(require_auth),
    service: ProviderDisclosureService = Depends(get_provider_disclosure_service),
) -> ProviderDataCallPublicationManifestListResponseV1:
    """List teacher-visible ``embedding`` publication manifests for one version."""

    try:
        return service.list_embedding_manifests_for_agent_version(
            str(context.user.id),
            agent_version_id=agent_version_id,
        )
    except ProviderDisclosureError as error:
        _raise_domain_error(error)
    raise AssertionError("unreachable")  # pragma: no cover


@router.get(
    "/pending/debates/{debate_id}",
    response_model=ProviderDataCallDebateManifestListResponseV1,
    operation_id="listProviderDataCallDebateManifests",
    responses={
        401: {"model": Error, "description": "Authentication is required."},
        403: {"model": Error, "description": "Teacher authorization is required."},
        404: {"model": Error, "description": "Debate was not found."},
        422: {"model": Error, "description": "Provider manifest listing is blocked."},
    },
)
def provider_data_call_debate_manifests(
    debate_id: str = Path(
        ...,
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    ),
    context: AuthContext = Depends(require_auth),
    service: ProviderDisclosureService = Depends(get_provider_disclosure_service),
) -> ProviderDataCallDebateManifestListResponseV1:
    """List exact LLM turn manifests through Debate -> Course ownership."""

    try:
        return service.list_llm_manifests_for_debate(
            str(context.user.id),
            debate_id=debate_id,
        )
    except ProviderDisclosureError as error:
        _raise_domain_error(error)
    raise AssertionError("unreachable")  # pragma: no cover


@router.post(
    "/disclosure/confirm",
    response_model=ProviderDataCallDisclosureResponseV1,
    operation_id="confirmProviderDataCallDisclosure",
    responses={
        401: {"model": Error, "description": "Authentication is required."},
        403: {"model": Error, "description": "Teacher authorization is required."},
        404: {"model": Error, "description": "Provider disclosure is unavailable."},
        409: {"model": Error, "description": "Provider disclosure confirmation is stale."},
        422: {"model": Error, "description": "Provider preflight is blocked."},
    },
)
def confirm_provider_data_call_disclosure(
    payload: ProviderDataCallConfirmationRequestV1,
    request: Request,
    context: AuthContext = Depends(require_authenticated_mutation),
    service: ProviderDisclosureService = Depends(get_provider_disclosure_service),
) -> ProviderDataCallDisclosureResponseV1:
    try:
        response = service.confirm(
            payload,
            actor_user_id=str(context.user.id),
            manifest_ref=payload.manifest_hash,
        )
    except ProviderDisclosureError as error:
        _raise_domain_error(error)
    store = getattr(service, "store", None)
    db = getattr(store, "db", None)
    if not isinstance(db, Session):
        return response
    wake_run_id: str | None = None
    manifest = db.scalar(
        select(ProviderExportManifest).where(
            ProviderExportManifest.manifest_hash == response.manifest_hash,
            ProviderExportManifest.provider_operation == "llm_knowledge_generate",
        )
    )
    if manifest is None:
        return response
    run = db.scalar(
        select(KnowledgeGenerationRun).where(
            KnowledgeGenerationRun.id == manifest.scope_id,
            KnowledgeGenerationRun.provider_manifest_hash == manifest.manifest_hash,
            KnowledgeGenerationRun.owner_user_id == str(context.user.id),
            KnowledgeGenerationRun.course_id == manifest.course_id,
        )
    )
    if (
        run is not None
        and run.state == "blocked"
        and run.safe_error_code == "provider_confirmation_required"
    ):
        job = db.get(Job, run.job_id)
        if job is not None and job.operation == GENERATION_OPERATION and job.state == "failed":
            # Confirmation is bound to the exact run manifest. Requeue only
            # that owner-authorized intent, then commit before waking the worker.
            run.state = "pending"
            run.safe_error_code = None
            run.claim_token = None
            run.lease_expires_at = None
            job.state = "pending"
            job.safe_error_code = None
            job.claim_token = None
            db.flush()
            wake_run_id = run.id
    if wake_run_id is None:
        return response
    db.commit()
    task_manager = getattr(request.app.state, "knowledge_generation_task_manager", None)
    wake = getattr(task_manager, "wake", None)
    if callable(wake):
        wake(wake_run_id)
    return response


# A small explicit factory lets the main window mount this router under its
# existing ``/api/v1`` prefix without importing provider-control internals.
def provider_disclosure_router() -> APIRouter:
    return router


__all__ = [
    "get_provider_disclosure_service",
    "provider_data_call_disclosure",
    "provider_data_call_manifests",
    "provider_data_call_agent_version_manifests",
    "provider_data_call_debate_manifests",
    "confirm_provider_data_call_disclosure",
    "provider_disclosure_router",
    "router",
]
