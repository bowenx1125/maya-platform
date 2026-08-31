"""Standalone teacher routes for ProviderDataCallV1 disclosure."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, Path, Query, Request

from app.core.errors import Error, PlatformError, conflict, forbidden, invalid_state, not_found
from app.modules.auth.dependencies import require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext

from .schemas import (
    ProviderDataCallConfirmationRequestV1,
    ProviderDataCallDebateManifestListResponseV1,
    ProviderDataCallDisclosureResponseV1,
    ProviderDataCallManifestListResponseV1,
    ProviderDataCallPublicationManifestListResponseV1,
)
from .service import ProviderDisclosureError, ProviderDisclosureService

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
    context: AuthContext = Depends(require_authenticated_mutation),
    service: ProviderDisclosureService = Depends(get_provider_disclosure_service),
) -> ProviderDataCallDisclosureResponseV1:
    try:
        return service.confirm(
            payload,
            actor_user_id=str(context.user.id),
            manifest_ref=payload.manifest_hash,
        )
    except ProviderDisclosureError as error:
        _raise_domain_error(error)
    raise AssertionError("unreachable")  # pragma: no cover


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
