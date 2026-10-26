"""HTTP routes for owner-managed Teams and the minimal Maya Team directory."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from app.core.create_admission import create_admission_slot
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
from app.modules.teams import service
from app.modules.teams.schemas import (
    CreateTeamRequest,
    MayaTeamDirectoryEntry,
    SaveTeamVersionRequest,
    TeamDetail,
    TeamSummary,
)
from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

router = APIRouter(tags=["teams"])
LOGGER = logging.getLogger(__name__)


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
) -> T:
    body_hash = parse_json_payload_hash(
        operation_id,
        context,
        scope,
        payload.model_dump(mode="json"),
    )
    record, cached = claim_idempotency(db, context, operation_id, idempotency_key, body_hash)
    if cached is not None:
        saved_body = json.loads(bytes(cached.body))
        replay(saved_body)  # Recheck current Team/course ownership before replaying.
        return cast(T, cached)
    try:
        assert_claim_owned(db, record)
        result = operation()
        finish_idempotency(db, record, status_code, result.model_dump(mode="json"))
        db.commit()
        return response_model.model_validate(result.model_dump(mode="json"))
    except Exception:
        abandon_claim(db, record)
        raise


def _replay_team_detail(db: Session, context: AuthContext, response: dict[str, Any]) -> TeamDetail:
    current = service.get_team_detail(db, context, str(response["id"]))
    # Replies saved before can_delete/updated_at/last_edited_by_name existed
    # replay with those three filled from the Team as it is now.
    backfill = current.model_dump(
        mode="json", include={"can_delete", "updated_at", "last_edited_by_name"}
    )
    return TeamDetail.model_validate({**backfill, **response})


@router.post(
    "/courses/{course_id}/teams",
    response_model=TeamDetail,
    status_code=201,
    operation_id="createTeam",
    responses={
        201: {"model": TeamDetail, "description": "Team and immutable version 1 created."},
        404: {"model": Error, "description": "Course, Agent version, or Set not found."},
        422: {"model": Error, "description": "Invalid Team membership or scope."},
    },
)
def create_team(
    course_id: UUID,
    payload: CreateTeamRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> TeamDetail:
    # The sign-in check above opened a read transaction; end it so a
    # request queued for admission holds no pooled connection while it waits.
    db.commit()
    with create_admission_slot():
        return _idempotent_mutation(
            db,
            context,
            operation_id="createTeam",
            idempotency_key=idempotency_key,
            scope=[str(course_id)],
            payload=payload,
            status_code=201,
            response_model=TeamDetail,
            operation=lambda: service.create_team(db, context, str(course_id), payload),
            replay=lambda body: _replay_team_detail(db, context, body),
        )


@router.delete(
    "/teams/{team_id}",
    status_code=204,
    operation_id="deleteTeam",
    responses={
        204: {"description": "Team removed from lists; existing chats stay read-only."},
        404: {"model": Error, "description": "Team not found."},
    },
)
def delete_team(
    team_id: UUID,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> Response:
    body_hash = parse_json_payload_hash("deleteTeam", context, [str(team_id)], {})
    record, replay = claim_idempotency(db, context, "deleteTeam", idempotency_key, body_hash)
    if replay is not None:
        return Response(status_code=204)
    assert_claim_owned(db, record)
    try:
        service.delete_team(db, context, str(team_id))
        finish_idempotency(db, record, 204, {})
        db.commit()
        return Response(status_code=204)
    except PlatformError:
        if db.in_transaction():
            db.rollback()
        abandon_claim(db, record)
        raise
    except Exception:
        if db.in_transaction():
            db.rollback()
        abandon_claim(db, record)
        raise


@router.get(
    "/courses/{course_id}/teams",
    response_model=list[TeamSummary],
    operation_id="listCourseTeams",
    responses={
        200: {"model": list[TeamSummary], "description": "Teams owned by or visible in the scope."},
        404: {"model": Error, "description": "Course not found."},
    },
)
def list_course_teams(
    course_id: UUID,
    group_id: UUID | None = Query(default=None),
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[TeamSummary]:
    return service.list_course_teams(
        db, context, str(course_id), str(group_id) if group_id is not None else None
    )


@router.get(
    "/courses/{course_id}/maya-teams",
    response_model=list[MayaTeamDirectoryEntry],
    operation_id="listMayaTeams",
    responses={
        200: {
            "model": list[MayaTeamDirectoryEntry],
            "description": "Current published Maya Teams.",
        },
        404: {"model": Error, "description": "Course not found."},
    },
)
def list_maya_teams(
    course_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[MayaTeamDirectoryEntry]:
    return service.list_maya_teams(db, context, str(course_id))


@router.get(
    "/teams/{team_id}",
    response_model=TeamDetail,
    operation_id="getTeam",
    responses={404: {"model": Error, "description": "Team not found."}},
)
def get_team(
    team_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> TeamDetail:
    return service.get_team_detail(db, context, str(team_id))


@router.put(
    "/teams/{team_id}",
    response_model=TeamDetail,
    operation_id="saveTeamVersion",
    responses={
        200: {"model": TeamDetail, "description": "A new immutable Team version was saved."},
        404: {"model": Error, "description": "Team, Agent version, or Set not found."},
        409: {"model": Error, "description": "Team metadata revision is stale."},
        422: {"model": Error, "description": "Invalid Team membership or scope."},
    },
)
def save_team_version(
    team_id: UUID,
    payload: SaveTeamVersionRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> TeamDetail:
    result = _idempotent_mutation(
        db,
        context,
        operation_id="saveTeamVersion",
        idempotency_key=idempotency_key,
        scope=[str(team_id)],
        payload=payload,
        status_code=200,
        response_model=TeamDetail,
        operation=lambda: service.save_team_version(db, context, str(team_id), payload),
        replay=lambda body: _replay_team_detail(db, context, body),
    )
    # The save has committed. A chat that was mid-reply stays for the sweep.
    try:
        from app.modules.teams.retarget import retarget_team_chats

        retarget_team_chats(db, str(team_id))
    except Exception:  # noqa: BLE001
        LOGGER.exception("Team chat retarget failed team_id=%s", team_id)
    return result
