"""Teacher-scoped service for the bounded Real-Core Demo run ledger.

This module records only the local identities and counters needed to audit one
bounded Demo run.  It never selects a provider and never performs I/O to an
external supplier.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import conflict, forbidden, not_found
from app.core.models import (
    Agent,
    AgentVersion,
    CourseMember,
    DemoAcceptanceRun,
    Group,
    KnowledgeSnapshot,
    ProviderExportManifest,
    ProviderOperation,
)
from app.modules.debates.models import Debate, DebateParticipant
from app.modules.demo_baseline.service import (
    BASELINE_AGENT_ID,
    BASELINE_SNAPSHOT_ID,
    BASELINE_VERSION_ID,
    baseline_is_usable,
)
from app.modules.reports.models import CivilizationReportRevision
from app.providers.control import (
    DEMO_ACCEPTANCE_PLAN_VERSION,
    ProviderControlError,
    validate_demo_acceptance_call_no,
)
from app.providers.control_repository import ProviderRepository, ProviderRepositoryError
from app.seed import GROUP_BOWEN_ID

from .schemas import (
    AcceptanceRunState,
    DemoAcceptanceCallRequest,
    DemoAcceptanceRunBindDebateRequest,
    DemoAcceptanceRunBindReportRequest,
    DemoAcceptanceRunCreateRequest,
    DemoAcceptanceRunResponse,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _now() -> datetime:
    return datetime.now(UTC)


def _raise_conflict(code: str, message: str) -> NoReturn:
    raise conflict(code, message)


def _require_teacher_target(
    db: Session,
    actor_user_id: str,
    *,
    agent_id: str,
    version_id: str,
) -> tuple[Agent, AgentVersion, str]:
    """Resolve target ownership through Agent -> Group -> Course membership."""

    row = db.execute(
        select(Agent, AgentVersion, Group.course_id, CourseMember.role)
        .join(AgentVersion, AgentVersion.agent_id == Agent.id)
        .join(Group, Group.id == Agent.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .where(
            Agent.id == agent_id,
            AgentVersion.id == version_id,
            CourseMember.user_id == actor_user_id,
        )
    ).first()
    if row is None:
        raise not_found()
    agent, version, course_id, role = row
    if role != "teacher":
        raise forbidden()
    if version.agent_id != agent.id:
        _raise_conflict("demo_acceptance_target_invalid", "The Demo target is invalid.")
    return agent, version, str(course_id)


def _require_teacher_debate(db: Session, actor_user_id: str, debate_id: str) -> Debate:
    row = db.execute(
        select(Debate, CourseMember.role)
        .join(CourseMember, CourseMember.course_id == Debate.course_id)
        .where(Debate.id == debate_id, CourseMember.user_id == actor_user_id)
    ).first()
    if row is None:
        raise not_found()
    debate, role = row
    if role != "teacher":
        raise forbidden()
    if not isinstance(debate, Debate):
        raise not_found()
    return debate


def _require_teacher_run(db: Session, actor_user_id: str, run_id: str) -> DemoAcceptanceRun:
    run = db.get(DemoAcceptanceRun, run_id)
    if run is None:
        raise not_found()
    role = db.scalar(
        select(CourseMember.role)
        .join(Group, Group.course_id == CourseMember.course_id)
        .join(Agent, Agent.group_id == Group.id)
        .where(Agent.id == run.target_agent_id, CourseMember.user_id == actor_user_id)
    )
    if role is None:
        raise not_found()
    if role != "teacher":
        raise forbidden()
    return run


def _require_run_open(run: DemoAcceptanceRun) -> None:
    if run.state not in {"prepared", "executing"}:
        _raise_conflict("demo_acceptance_run_terminal", "The Demo acceptance run is terminal.")


def _verify_baseline(db: Session) -> None:
    agent = db.get(Agent, BASELINE_AGENT_ID)
    version = db.get(AgentVersion, BASELINE_VERSION_ID)
    snapshot = db.get(KnowledgeSnapshot, BASELINE_SNAPSHOT_ID)
    if (
        agent is None
        or version is None
        or snapshot is None
        or agent.group_id != GROUP_BOWEN_ID
        or version.agent_id != BASELINE_AGENT_ID
        or snapshot.agent_version_id != BASELINE_VERSION_ID
        or not baseline_is_usable(db)
    ):
        _raise_conflict(
            "demo_acceptance_baseline_unavailable",
            "The fixed Demo baseline is not usable.",
        )


def _manifest_hashes_for_version(version_id: str) -> Any:
    return select(ProviderExportManifest.manifest_hash).where(
        ProviderExportManifest.agent_version_id == version_id
    )


def _manifest_hashes_for_debate(debate_id: str) -> Any:
    return select(ProviderExportManifest.manifest_hash).where(
        ProviderExportManifest.debate_id == debate_id
    )


def _assert_no_provider_history(
    db: Session,
    *,
    target_version_id: str,
    debate_id: str | None,
) -> None:
    """Reject any prior provider operation or manifest for the fresh target."""

    target_manifests = _manifest_hashes_for_version(target_version_id)
    target_manifest = db.scalar(
        select(ProviderExportManifest.id)
        .where(ProviderExportManifest.agent_version_id == target_version_id)
        .limit(1)
    )
    target_operation = db.scalar(
        select(ProviderOperation.id)
        .where(
            or_(
                ProviderOperation.scope_id == target_version_id,
                ProviderOperation.export_manifest_hash.in_(target_manifests),
            )
        )
        .limit(1)
    )
    if target_manifest is not None or target_operation is not None:
        _raise_conflict(
            "demo_acceptance_target_not_clean",
            "The Demo target already has provider history.",
        )
    if debate_id is None:
        return
    debate_manifest = db.scalar(
        select(ProviderExportManifest.id)
        .where(ProviderExportManifest.debate_id == debate_id)
        .limit(1)
    )
    debate_operation = db.scalar(
        select(ProviderOperation.id)
        .where(
            or_(
                ProviderOperation.scope_id == debate_id,
                ProviderOperation.export_manifest_hash.in_(_manifest_hashes_for_debate(debate_id)),
            )
        )
        .limit(1)
    )
    if debate_manifest is not None or debate_operation is not None:
        _raise_conflict(
            "demo_acceptance_debate_not_clean",
            "The Demo Debate already has provider history.",
        )


def _assert_debate_matches_target(
    db: Session,
    actor_user_id: str,
    *,
    debate_id: str,
    target_agent_id: str,
    target_version_id: str,
    course_id: str,
) -> None:
    debate = _require_teacher_debate(db, actor_user_id, debate_id)
    if debate.course_id != course_id:
        raise not_found()
    participant = db.scalar(
        select(DebateParticipant.id).where(
            DebateParticipant.debate_id == debate_id,
            DebateParticipant.agent_id == target_agent_id,
            DebateParticipant.agent_version_id == target_version_id,
        )
    )
    if participant is None:
        _raise_conflict(
            "demo_acceptance_target_invalid",
            "The target AgentVersion is not selected in the Demo Debate.",
        )


def _operation_belongs_to_run(
    db: Session,
    operation: ProviderOperation,
    run: DemoAcceptanceRun,
) -> bool:
    if operation.scope_id == run.target_version_id:
        return True
    manifest = db.scalar(
        select(ProviderExportManifest).where(
            ProviderExportManifest.manifest_hash == operation.export_manifest_hash
        )
    )
    if manifest is None:
        return False
    if manifest.agent_version_id == run.target_version_id:
        return True
    return run.debate_id is not None and manifest.debate_id == run.debate_id


def _run_response(db: Session, run_id: str) -> DemoAcceptanceRunResponse:
    run = db.get(DemoAcceptanceRun, run_id)
    if run is None:
        raise not_found()
    operations = db.scalars(
        select(ProviderOperation)
        .where(
            ProviderOperation.acceptance_run_id == run.id,
            ProviderOperation.call_no.is_not(None),
        )
        .order_by(ProviderOperation.call_no, ProviderOperation.id)
    ).all()
    seen: set[int] = set()
    for operation in operations:
        call_no = operation.call_no
        if call_no is None or call_no in seen:
            _raise_conflict(
                "demo_acceptance_ledger_invalid",
                "The Demo acceptance ledger is inconsistent.",
            )
        try:
            validate_demo_acceptance_call_no(call_no)
            UUID(operation.id)
        except (ProviderControlError, ValueError):
            _raise_conflict(
                "demo_acceptance_ledger_invalid",
                "The Demo acceptance ledger is inconsistent.",
            )
        seen.add(call_no)
        if operation.charged_request_count > operation.request_count:
            _raise_conflict(
                "demo_acceptance_ledger_invalid",
                "The Demo acceptance ledger is inconsistent.",
            )
    charged = sum(operation.charged_request_count for operation in operations)
    return DemoAcceptanceRunResponse(
        id=UUID(run.id),
        plan_version=DEMO_ACCEPTANCE_PLAN_VERSION,
        fixture_hash=run.fixture_hash,
        baseline_agent_id=UUID(run.baseline_agent_id),
        baseline_version_id=UUID(run.baseline_version_id),
        baseline_snapshot_id=UUID(run.baseline_snapshot_id),
        target_agent_id=UUID(run.target_agent_id),
        target_version_id=UUID(run.target_version_id),
        debate_id=UUID(run.debate_id) if run.debate_id is not None else None,
        report_revision_id=(
            UUID(run.report_revision_id) if run.report_revision_id is not None else None
        ),
        state=cast(AcceptanceRunState, run.state),
        starting_charged_requests=0,
        call_count=len(operations),
        charged_request_count=charged,
    )


def create_acceptance_run(
    db: Session,
    *,
    actor_user_id: str,
    request: DemoAcceptanceRunCreateRequest,
) -> DemoAcceptanceRunResponse:
    """Create one clean, fixed-plan run or return its exact idempotent row."""

    fixture_hash = request.fixture_hash
    if _SHA256_RE.fullmatch(fixture_hash) is None:
        _raise_conflict("demo_acceptance_fixture_invalid", "The Demo fixture is invalid.")
    target_agent_id = str(request.target_agent_id)
    target_version_id = str(request.target_version_id)
    agent, version, course_id = _require_teacher_target(
        db,
        actor_user_id,
        agent_id=target_agent_id,
        version_id=target_version_id,
    )
    if agent.id == BASELINE_AGENT_ID or version.id == BASELINE_VERSION_ID:
        _raise_conflict(
            "demo_acceptance_target_invalid",
            "The system baseline cannot be the Demo target.",
        )
    _verify_baseline(db)
    debate_id = str(request.debate_id) if request.debate_id is not None else None
    existing = db.scalars(
        select(DemoAcceptanceRun)
        .where(
            DemoAcceptanceRun.target_agent_id == target_agent_id,
            DemoAcceptanceRun.target_version_id == target_version_id,
        )
        .order_by(DemoAcceptanceRun.created_at, DemoAcceptanceRun.id)
    ).all()
    for run in existing:
        if run.fixture_hash == fixture_hash and run.debate_id == debate_id:
            return _run_response(db, run.id)
    if existing:
        _raise_conflict(
            "demo_acceptance_target_already_registered",
            "The Demo target already belongs to another acceptance run.",
        )
    if debate_id is not None:
        debate_run = db.scalar(
            select(DemoAcceptanceRun.id).where(DemoAcceptanceRun.debate_id == debate_id).limit(1)
        )
        if debate_run is not None:
            _raise_conflict(
                "demo_acceptance_debate_already_registered",
                "The Debate is already registered.",
            )
        _assert_debate_matches_target(
            db,
            actor_user_id,
            debate_id=debate_id,
            target_agent_id=target_agent_id,
            target_version_id=target_version_id,
            course_id=course_id,
        )
    _assert_no_provider_history(
        db,
        target_version_id=target_version_id,
        debate_id=debate_id,
    )
    now = _now()
    run = DemoAcceptanceRun(
        id=str(uuid4()),
        plan_version=DEMO_ACCEPTANCE_PLAN_VERSION,
        fixture_hash=fixture_hash,
        baseline_agent_id=BASELINE_AGENT_ID,
        baseline_version_id=BASELINE_VERSION_ID,
        baseline_snapshot_id=BASELINE_SNAPSHOT_ID,
        target_agent_id=target_agent_id,
        target_version_id=target_version_id,
        debate_id=debate_id,
        report_revision_id=None,
        state="prepared",
        starting_charged_requests=0,
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    db.flush()
    return _run_response(db, run.id)


def get_acceptance_run(
    db: Session,
    *,
    actor_user_id: str,
    run_id: str,
) -> DemoAcceptanceRunResponse:
    _require_teacher_run(db, actor_user_id, run_id)
    return _run_response(db, run_id)


def bind_acceptance_run_debate(
    db: Session,
    *,
    actor_user_id: str,
    run_id: str,
    request: DemoAcceptanceRunBindDebateRequest,
) -> DemoAcceptanceRunResponse:
    run = _require_teacher_run(db, actor_user_id, run_id)
    debate_id = str(request.debate_id)
    if run.debate_id == debate_id:
        return _run_response(db, run.id)
    _require_run_open(run)
    if run.debate_id is not None:
        _raise_conflict(
            "demo_acceptance_debate_already_bound",
            "A different Debate is already bound.",
        )
    _require_teacher_target(
        db,
        actor_user_id,
        agent_id=run.target_agent_id,
        version_id=run.target_version_id,
    )
    _assert_debate_matches_target(
        db,
        actor_user_id,
        debate_id=debate_id,
        target_agent_id=run.target_agent_id,
        target_version_id=run.target_version_id,
        course_id=str(
            db.scalar(
                select(Group.course_id)
                .join(Agent, Agent.group_id == Group.id)
                .where(Agent.id == run.target_agent_id)
            )
        ),
    )
    duplicate = db.scalar(
        select(DemoAcceptanceRun.id).where(
            DemoAcceptanceRun.debate_id == debate_id,
            DemoAcceptanceRun.id != run.id,
        )
    )
    if duplicate is not None:
        _raise_conflict(
            "demo_acceptance_debate_already_registered",
            "The Debate is already registered.",
        )
    _assert_no_provider_history(
        db,
        target_version_id=run.target_version_id,
        debate_id=debate_id,
    )
    run.debate_id = debate_id
    run.updated_at = _now()
    db.flush()
    return _run_response(db, run.id)


def bind_acceptance_run_report(
    db: Session,
    *,
    actor_user_id: str,
    run_id: str,
    request: DemoAcceptanceRunBindReportRequest,
) -> DemoAcceptanceRunResponse:
    run = _require_teacher_run(db, actor_user_id, run_id)
    report_revision_id = str(request.report_revision_id)
    if run.report_revision_id == report_revision_id:
        return _run_response(db, run.id)
    _require_run_open(run)
    if run.debate_id is None:
        _raise_conflict("demo_acceptance_debate_required", "Bind the Demo Debate first.")
    if run.report_revision_id is not None:
        _raise_conflict(
            "demo_acceptance_report_already_bound",
            "A different Report is already bound.",
        )
    _require_teacher_debate(db, actor_user_id, run.debate_id)
    revision = db.get(CivilizationReportRevision, report_revision_id)
    if revision is None or revision.debate_id != run.debate_id:
        raise not_found()
    duplicate = db.scalar(
        select(DemoAcceptanceRun.id).where(
            DemoAcceptanceRun.report_revision_id == report_revision_id,
            DemoAcceptanceRun.id != run.id,
        )
    )
    if duplicate is not None:
        _raise_conflict(
            "demo_acceptance_report_already_registered",
            "The Report is already registered.",
        )
    run.report_revision_id = report_revision_id
    run.updated_at = _now()
    db.flush()
    return _run_response(db, run.id)


def attach_acceptance_call(
    db: Session,
    *,
    actor_user_id: str,
    run_id: str,
    request: DemoAcceptanceCallRequest,
) -> DemoAcceptanceRunResponse:
    run = _require_teacher_run(db, actor_user_id, run_id)
    _require_run_open(run)
    operation = db.get(ProviderOperation, str(request.operation_id))
    if operation is None:
        raise not_found()
    if not _operation_belongs_to_run(db, operation, run):
        _raise_conflict(
            "demo_acceptance_operation_mismatch",
            "The provider operation does not belong to this Demo run.",
        )
    db.flush()
    try:
        ProviderRepository(db).attach_acceptance_call(
            operation.id,
            acceptance_run_id=run.id,
            call_no=request.call_no,
        )
    except (ProviderControlError, ProviderRepositoryError):
        _raise_conflict("demo_acceptance_call_conflict", "The Demo call could not be attached.")
    db.expire_all()
    return _run_response(db, run.id)


# Descriptive aliases keep the route and future driver seam discoverable.
create_run = create_acceptance_run
get_run = get_acceptance_run
bind_debate = bind_acceptance_run_debate
bind_report = bind_acceptance_run_report
attach_call = attach_acceptance_call
summary = get_acceptance_run
summarize_acceptance_run = get_acceptance_run


__all__ = [
    "attach_acceptance_call",
    "attach_call",
    "bind_acceptance_run_debate",
    "bind_acceptance_run_report",
    "bind_debate",
    "bind_report",
    "create_acceptance_run",
    "create_run",
    "get_acceptance_run",
    "get_run",
    "summary",
    "summarize_acceptance_run",
]
