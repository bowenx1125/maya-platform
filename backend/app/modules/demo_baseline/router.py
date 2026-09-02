"""Small local-Demo endpoints for baseline status and safe composition labels."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.modules.auth.dependencies import get_db
from app.seed import GROUP_DEMO_ID

from .composition import demo_composition
from .schemas import DemoBaseline, DemoComposition, DemoRuntimeStatus
from .service import (
    BASELINE_AGENT_ID,
    BASELINE_SNAPSHOT_ID,
    BASELINE_VERSION_ID,
    baseline_is_usable,
    dirty_counts,
)

router = APIRouter(tags=["Demo"], include_in_schema=False)


@router.get("/demo/composition", response_model=DemoComposition)
def get_demo_composition(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DemoComposition:
    return demo_composition(settings, db)


@router.get("/demo/baseline", response_model=DemoBaseline)
def get_demo_baseline(db: Session = Depends(get_db)) -> DemoBaseline:
    return DemoBaseline(
        agent_id=UUID(BASELINE_AGENT_ID),
        version_id=UUID(BASELINE_VERSION_ID),
        snapshot_id=UUID(BASELINE_SNAPSHOT_ID),
        group_id=UUID(GROUP_DEMO_ID),
        usable=baseline_is_usable(db),
    )


@router.get("/demo/status", response_model=DemoRuntimeStatus)
def get_demo_status(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DemoRuntimeStatus:
    agents, debates, interactions = dirty_counts(db)
    return DemoRuntimeStatus(
        baseline=DemoBaseline(
            agent_id=UUID(BASELINE_AGENT_ID),
            version_id=UUID(BASELINE_VERSION_ID),
            snapshot_id=UUID(BASELINE_SNAPSHOT_ID),
            group_id=UUID(GROUP_DEMO_ID),
            usable=baseline_is_usable(db),
        ),
        composition=demo_composition(settings, db),
        dirty_agents=agents,
        dirty_debates=debates,
        dirty_interactions=interactions,
    )
