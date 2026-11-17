"""FastAPI routes for the M10 Debate draft surface.

Playback and generation routes remain owned by sibling modules. These endpoints
only expose the teacher-scoped create/list/get/update/start setup boundary.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app.core.errors import Error
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext
from app.modules.debates.schemas import (
    DebateDetail,
    DebateDraftRequest,
    DebateDraftUpdateRequest,
    DebateLLMDefaults,
    DebateRoundUnitCapDefaults,
    DebateRulesetContract,
    DebateRulesetDefaults,
    DebateSummary,
)
from app.modules.debates.setup.service import (
    create_debate_draft,
    get_debate,
    list_debates,
    require_teacher_course,
    update_debate_draft,
)

router = APIRouter(tags=["Debates"])


@router.get(
    "/courses/{course_id}/debate-ruleset",
    response_model=DebateRulesetDefaults,
    operation_id="getDebateRulesetDefaults",
    responses={
        200: {"model": DebateRulesetDefaults},
        403: {"model": Error},
        404: {"model": Error},
    },
)
def get_ruleset_defaults(
    course_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DebateRulesetDefaults:
    from app.modules.debates.teaching_rules import (
        default_teaching_prompts,
        execution_contracts_v5,
    )

    require_teacher_course(db, context.user.id, str(course_id))
    return DebateRulesetDefaults(
        **default_teaching_prompts(),
        contract=DebateRulesetContract(**execution_contracts_v5()),
    )


@router.get(
    "/courses/{course_id}/debate-llm-defaults",
    response_model=DebateLLMDefaults,
    operation_id="getDebateLLMDefaults",
    responses={
        200: {"model": DebateLLMDefaults},
        403: {"model": Error},
        404: {"model": Error},
    },
)
def get_llm_defaults(
    course_id: UUID,
    request: Request,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DebateLLMDefaults:
    """The DEBATE_LLM_* defaults and ranges the parameter card starts from."""

    from app.modules.debates.generation_params import defaults_payload

    require_teacher_course(db, context.user.id, str(course_id))
    return DebateLLMDefaults.model_validate(defaults_payload(request.app.state.settings))


@router.get(
    "/courses/{course_id}/debate-round-unit-cap-defaults",
    response_model=DebateRoundUnitCapDefaults,
    operation_id="getDebateRoundUnitCapDefaults",
    responses={
        200: {"model": DebateRoundUnitCapDefaults},
        403: {"model": Error},
        404: {"model": Error},
        422: {"model": Error},
    },
)
def get_round_unit_cap_defaults(
    course_id: UUID,
    language: Literal["en", "zh"],
    participants: int = Query(..., ge=2, le=5),
    rate: float = Query(1.0, ge=0.5, le=2.0, allow_inf_nan=False),
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DebateRoundUnitCapDefaults:
    """Default four-round caps from turn_unit_cap(..., minutes=5)."""

    from app.modules.debates.generation.four_round import (
        default_round_unit_caps,
        estimated_duration_minutes,
    )

    require_teacher_course(db, context.user.id, str(course_id))
    caps = default_round_unit_caps(language, participants=participants, voice_rate=rate)
    return DebateRoundUnitCapDefaults(
        language=language,
        participants=participants,
        rate=rate,
        round_unit_caps=caps,
        estimated_duration_minutes=estimated_duration_minutes(
            caps, language=language, participants=participants, voice_rate=rate
        ),
    )


@router.get(
    "/courses/{course_id}/debates",
    response_model=list[DebateSummary],
    operation_id="listDebates",
    responses={
        200: {"model": list[DebateSummary]},
        403: {"model": Error},
        404: {"model": Error},
    },
)
def list_debates_route(
    course_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[DebateSummary]:
    return list_debates(db, actor_user_id=context.user.id, course_id=str(course_id))


@router.post(
    "/courses/{course_id}/debates",
    response_model=DebateDetail,
    status_code=201,
    operation_id="createDebate",
    responses={
        201: {"model": DebateDetail},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
        422: {"model": Error},
    },
)
def create_debate_route(
    course_id: UUID,
    payload: DebateDraftRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> DebateDetail:
    detail = create_debate_draft(
        db,
        actor_user_id=context.user.id,
        course_id=str(course_id),
        payload=payload,
        idempotency_key=idempotency_key,
    )
    # A new draft is the one the teacher is about to run, so it starts warming
    # the moment they land back on the list. The Job rows have to be durable
    # before the scheduler looks for them, and get_db commits after this
    # handler returns.
    db.commit()
    scheduler = getattr(request.app.state, "prewarm_scheduler", None)
    focus = getattr(scheduler, "focus", None)
    if callable(focus):
        focus(str(detail.id))
    return detail


@router.get(
    "/debates/{debate_id}",
    response_model=DebateDetail,
    operation_id="getDebate",
    responses={
        200: {"model": DebateDetail},
        403: {"model": Error},
        404: {"model": Error},
    },
)
def get_debate_route(
    debate_id: UUID,
    request: Request,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DebateDetail:
    detail = get_debate(db, actor_user_id=context.user.id, debate_id=str(debate_id))
    # Opening a debate is what says which one the teacher is about to run, so
    # it takes the pre-warm bandwidth and whatever held it yields at its next
    # turn boundary.
    scheduler = getattr(request.app.state, "prewarm_scheduler", None)
    focus = getattr(scheduler, "focus", None)
    if callable(focus):
        focus(str(debate_id))
    return detail


@router.patch(
    "/debates/{debate_id}",
    response_model=DebateDetail,
    operation_id="updateDebateDraft",
    responses={
        200: {"model": DebateDetail},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
        422: {"model": Error},
    },
)
def update_debate_route(
    debate_id: UUID,
    payload: DebateDraftUpdateRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> DebateDetail:
    return update_debate_draft(
        db,
        actor_user_id=context.user.id,
        debate_id=str(debate_id),
        payload=payload,
        expected_revision=payload.expected_revision,
    )


__all__ = ["router"]
