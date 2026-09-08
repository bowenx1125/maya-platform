"""Focused fake-only checks for the Real Maya Report service seam."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from app.core.db import Database
from app.modules.debates.generation.prompt_budget import PromptBudgetV1
from app.modules.reports import service
from app.modules.reports.models import CivilizationReport, CivilizationReportRevision
from app.modules.reports.real_prompt import ReportMessage, ReportWireRequest
from app.modules.reports.real_schema import REPORT_SECTION_FIELDS, ReportRequest
from app.modules.reports.schemas import (
    ManifestInsight,
    ManifestParticipant,
    ManifestTurn,
    ManifestVote,
    ReportInputManifestV1,
    ReportSectionOutput,
)
from app.providers.control import (
    FIXED_MODELS,
    LLM_MAYA_REPORT_BUCKET,
    ExportFieldV1,
    ExportManifestV1,
    ProviderPolicySnapshotV1,
    ProviderReservationRequestV1,
    ProviderScopeBudgetV1,
)
from app.providers.control_repository import ProviderRepository


def _context(debate_id: str) -> service.ReportContext:
    participants = [
        ManifestParticipant(
            participant_id=uuid4(),
            slot=cast(Any, slot),
            order_index=index,
            agent_name=f"Agent {slot}",
            stance_mode="open",
            initial_stance=None,
            current_stance=None,
            initial_position_summary="an initial position",
            current_position_summary="a final position",
        )
        for index, slot in enumerate(("A", "B"))
    ]
    turns = [
        ManifestTurn(
            turn_id=uuid4(),
            participant_id=participants[index % 2].participant_id,
            round_no=1 if index < 2 else 2,
            turn_index=index,
            text_hash="a" * 64,
        )
        for index in range(4)
    ]
    manifest = ReportInputManifestV1(
        debate_id=uuid4(),
        topic="How can classrooms share cultural knowledge responsibly?",
        participants=participants,
        turns=turns,
        turn_sources=[],
        votes=[
            ManifestVote(participant_id=item.participant_id, order_index=item.order_index, count=0)
            for item in participants
        ],
        insight=ManifestInsight(
            snapshot_id=uuid4(), revision=1, included_count=0, filtered_count=0, items=[]
        ),
    )
    turn_context = tuple(
        service.ReportTurnContext(
            turn_id=item.turn_id,
            participant_id=item.participant_id,
            participant_name=(
                f"Agent {
                    next(
                        participant.slot
                        for participant in participants
                        if participant.participant_id == item.participant_id
                    )
                }"
            ),
            round_no=item.round_no,
            turn_index=item.turn_index,
            speech="Careful reasoning keeps context and uncertainty visible.",
        )
        for item in turns
    )
    return service.ReportContext(
        debate=SimpleNamespace(id=debate_id, topic=manifest.topic),  # type: ignore[arg-type]
        manifest=manifest,
        turns=turn_context,
        sources=(),
        vote_total=0,
        barrage_total=0,
    )


def _sections() -> ReportSectionOutput:
    return ReportSectionOutput(
        **{
            field: f"A concise English section about {field.replace('_', ' ')}."
            for field in REPORT_SECTION_FIELDS
        }
    )


def _policy() -> ProviderPolicySnapshotV1:
    return ProviderPolicySnapshotV1(
        privacy_notice_retrieved_at="2026-08-31T00:00:00Z",
        privacy_notice_sha256="a" * 64,
        service_terms_retrieved_at="2026-08-31T00:00:00Z",
        service_terms_sha256="b" * 64,
        faq_retrieved_at="2026-08-31T00:00:00Z",
        faq_sha256="c" * 64,
        no_training_basis="reviewed pay-as-you-go account",
        prompt_response_logging_disabled=True,
        inference_log_backflow_disabled=True,
        optional_content_logging_disabled=True,
        service_improvement_disabled=True,
        storage_disclosed=True,
    )


class _PreparedProvider:
    def __init__(self, policy_hash: str) -> None:
        self.policy_hash = policy_hash
        self.build_calls = 0
        self.execute_calls = 0
        self.prepared_wires: list[ReportWireRequest] = []

    def build_request(self, value: object) -> ReportWireRequest:
        self.build_calls += 1
        report = cast(ReportRequest, value)
        return ReportWireRequest(
            endpoint="https://fixture.invalid/report",
            method="POST",
            body={},
            messages=(
                ReportMessage(role="system", content="fixture"),
                ReportMessage(role="user", content=report.canonical_json()),
            ),
            report=report,
            budget=PromptBudgetV1(input_tokens=100, request_bytes=100),
            request_hash="d" * 64,
            input_hash=report.input_hash(),
            schema_hash="e" * 64,
            tokenizer_id="fixture-tokenizer",
            tokenizer_asset_hash="f" * 64,
            policy_hash=self.policy_hash,
            estimated_cost_cny=Decimal("0.01"),
        )

    def execute_prepared(self, wire: ReportWireRequest) -> ReportSectionOutput:
        self.execute_calls += 1
        self.prepared_wires.append(wire)
        return _sections()


class _DriftingProvider(_PreparedProvider):
    """A fake builder whose second build changes the durable wire hash."""

    def build_request(self, value: object) -> ReportWireRequest:
        wire = super().build_request(value)
        return replace(wire, request_hash="d" * 64 if self.build_calls == 1 else "c" * 64)


class _PrepareSession:
    def __init__(self, revision: CivilizationReportRevision, policy: object) -> None:
        self.revision = revision
        self.policy = policy
        self.scalar_count = 0

    def get(self, model: Any, identifier: str) -> Any:
        if model is CivilizationReportRevision and identifier == self.revision.id:
            return self.revision
        return None

    def scalar(self, _statement: object) -> Any:
        self.scalar_count += 1
        if self.scalar_count == 1:
            return self.policy
        if self.scalar_count == 2:
            return "policy-row"
        return None

    def scalars(self, _statement: object) -> Any:
        return SimpleNamespace(all=lambda: [])


@dataclass
class _Repository:
    policy_hash: str

    def __post_init__(self) -> None:
        self.created: list[object] = []
        self.executed: list[str] = []

    def ensure_scope_budget(self, *_args: object, **_kwargs: object) -> None:
        self.executed.append("budget")

    def ensure_export_manifest(self, manifest: object, **_kwargs: object) -> str:
        self.created.append(manifest)
        return "manifest-row"

    def create_prepared(self, request: object) -> object:
        self.created.append(request)
        return SimpleNamespace(id="operation-id")


def _revision() -> CivilizationReportRevision:
    now = service.utc_now()
    return CivilizationReportRevision(
        id="revision-id",
        report_id="report-id",
        debate_id="debate-id",
        insight_snapshot_id="insight-id",
        revision_no=1,
        status="generating",
        attempt=1,
        input_manifest_json="{}",
        input_manifest_hash="a" * 64,
        trigger="automatic",
        created_at=now,
        updated_at=now,
    )


class _ProcessSession:
    def __init__(
        self,
        revision: CivilizationReportRevision,
        job: object,
        operation: object,
        report: object,
        run: object,
    ) -> None:
        self.revision = revision
        self.job = job
        self.operation: Any = operation
        self.report: Any = report
        self.run: Any = run
        self.added: list[object] = []

    def get(self, model: Any, identifier: str) -> Any:
        if model is CivilizationReportRevision and identifier == self.revision.id:
            return self.revision
        if model is CivilizationReport and identifier == self.revision.report_id:
            return self.report
        if model.__name__ == "ProviderOperation" and identifier == self.operation.id:
            return self.operation
        if model.__name__ == "DemoAcceptanceRun" and identifier == self.run.id:
            return self.run
        return None

    def scalar(self, _statement: object) -> Any:
        if not getattr(self, "job_read", False):
            self.job_read = True
            return self.job
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class _ProcessRepository(_Repository):
    def __init__(self, operation: Any) -> None:
        super().__init__("a" * 64)
        self.operation = operation
        self.transitions: list[str] = []

    def get(self, _operation_id: str) -> Any:
        return self.operation

    def assert_hashes_current(self, _request: object) -> None:
        self.transitions.append("confirmed")

    def reserve(self, _operation_id: str) -> None:
        self.operation.state = "reserved"
        self.operation.request_count = 1
        self.operation.charged_request_count = 1
        self.transitions.append("reserved")

    def transition(self, _operation_id: str, **_kwargs: object) -> None:
        self.operation.state = "sending"
        self.transitions.append("sending")

    def mark_accepted(self, _operation_id: str, *, response_hash: str) -> None:
        self.operation.state = "accepted"
        self.operation.staged_response_hash = response_hash
        self.transitions.append("accepted")

    def mark_succeeded(self, _operation_id: str) -> None:
        self.operation.state = "succeeded"
        self.transitions.append("succeeded")

    def mark_failed(self, _operation_id: str, *, safe_error_code: str) -> None:
        self.operation.state = "failed"
        self.operation.safe_error_code = safe_error_code

    def mark_not_sent(self, _operation_id: str, *, safe_error_code: str) -> None:
        self.operation.state = "not_sent"
        self.operation.safe_error_code = safe_error_code

    def mark_acceptance_unknown(self, _operation_id: str, *, safe_error_code: str) -> None:
        self.operation.state = "acceptance_unknown"
        self.operation.safe_error_code = safe_error_code

    def complete_report_in_session(
        self,
        _db: object,
        _operation_id: str,
        *,
        response_hash: str,
    ) -> None:
        self.operation.state = "succeeded"
        self.operation.staged_response_hash = response_hash
        self.transitions.append("succeeded")


def test_prepare_persists_manifest_and_prepared_operation_without_transport(
    monkeypatch: Any,
) -> None:
    policy = _policy()
    revision = _revision()
    context = _context(revision.debate_id)
    provider = _PreparedProvider(policy.policy_hash)
    repository = _Repository(policy.policy_hash)
    database = _PrepareSession(revision, policy)
    monkeypatch.setattr(service, "_report_context", lambda *_args, **_kwargs: context)

    prepared = service.prepare_real_report_operation(
        database,
        revision.id,
        runtime=service.RealReportRuntime(provider, repository),  # type: ignore[arg-type]
    )

    assert prepared.manifest_hash and prepared.operation_id == "operation-id"
    assert provider.execute_calls == 0
    assert provider.build_calls == 1
    manifest = cast(
        ExportManifestV1,
        next(item for item in repository.created if getattr(item, "provider_operation", None)),
    )
    assert {field.field_class for field in manifest.fields} == {
        "topic_and_platform_rules",
        "public_agent_name",
        "public_predecessor_speech",
        "current_evidence_excerpt",
        "opaque_local_id",
        "anonymous_insight_summary",
        "aggregate_vote_count",
    }


def test_real_report_context_projection_uses_opaque_evidence_keys() -> None:
    context = _context("debate-id")
    request = service.build_real_report_request(context)
    assert request.topic == context.manifest.topic
    assert set(request.model_dump()) == {
        # A validation input, not something the provider is asked; the
        # canonical payload drops it.
        "source_language",
        "topic",
        "participants",
        "speeches",
        "sources",
        "votes",
        "insights",
    }


def test_real_report_auto_job_pauses_before_confirmation_and_transport(
    monkeypatch: Any,
) -> None:
    revision = _revision()
    context = _context(revision.debate_id)
    policy = _policy()
    provider = _PreparedProvider(policy.policy_hash)
    repository = _Repository(policy.policy_hash)
    job = SimpleNamespace(state="pending", attempt=0, safe_error_code=None, updated_at=None)
    database = _ProcessSession(
        revision,
        job,
        SimpleNamespace(id="unused"),
        SimpleNamespace(),
        SimpleNamespace(),
    )
    prepared = service.RealReportPreparedOperation(
        revision.id,
        revision.debate_id,
        "m" * 64,
        "operation-id",
        provider.build_request(service.build_real_report_request(context)),
        context,
    )
    monkeypatch.setattr(service, "_mark_job_running", lambda *_args: True)
    monkeypatch.setattr(service, "_mark_job_failed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        service,
        "prepare_real_report_operation",
        lambda *_args, **_kwargs: prepared,
    )

    result = service.process_report_revision(
        database,  # type: ignore[arg-type]
        revision.id,
        runtime=service.RealReportRuntime(provider, repository),
    )

    assert result.status == "generating"
    assert job.state == "interrupted"
    assert job.safe_error_code == "provider_confirmation_required"
    assert provider.execute_calls == 0


def test_real_report_continue_requires_independent_acceptance_binding(
    monkeypatch: Any,
) -> None:
    revision = _revision()
    context = _context(revision.debate_id)
    provider = _PreparedProvider("a" * 64)
    operation = SimpleNamespace(
        id="operation-id",
        export_manifest_hash="b" * 64,
        acceptance_run_id=None,
        call_no=None,
        state="prepared",
        request_count=0,
        charged_request_count=0,
    )
    report = SimpleNamespace(id=revision.report_id)
    job = SimpleNamespace(
        state="interrupted",
        attempt=1,
        safe_error_code="provider_confirmation_required",
    )
    database = _ProcessSession(
        revision,
        job,
        operation,
        report,
        SimpleNamespace(
            id="run-id",
            state="executing",
            report_revision_id=revision.id,
            debate_id=revision.debate_id,
        ),
    )
    prepared = service.RealReportPreparedOperation(
        revision.id,
        revision.debate_id,
        "m" * 64,
        operation.id,
        provider.build_request(service.build_real_report_request(context)),
        context,
    )
    repository = _ProcessRepository(operation)
    monkeypatch.setattr(service, "_mark_job_running", lambda *_args: True)
    monkeypatch.setattr(service, "_mark_job_failed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_mark_job_completed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_mark_debate_completed", lambda *_args: None)
    monkeypatch.setattr(
        service,
        "prepare_real_report_operation",
        lambda *_args, **_kwargs: prepared,
    )

    # The operation is still unbound, so a caller-supplied ordinal cannot
    # make the service pick or attach a call behind the driver's back.
    result = service.continue_real_report_revision(
        database,  # type: ignore[arg-type]
        revision.id,
        manifest_hash=prepared.manifest_hash,
        call_no=3,
        runtime=service.RealReportRuntime(provider, repository),
    )
    assert result.status == "failed"
    assert provider.execute_calls == 0


def test_continue_rejects_drifted_rebuilt_wire_before_transport(
    monkeypatch: Any,
) -> None:
    revision = _revision()
    context = _context(revision.debate_id)
    provider = _DriftingProvider("a" * 64)
    request = service.build_real_report_request(context)
    first_wire = provider.build_request(request)
    drifted_wire = provider.build_request(request)
    operation = SimpleNamespace(
        id="operation-id",
        export_manifest_hash="b" * 64,
        acceptance_run_id="run-id",
        call_no=3,
        state="prepared",
        request_count=0,
        charged_request_count=0,
        request_hash=first_wire.request_hash,
        policy_hash="a" * 64,
        max_cost_cny=0.01,
    )
    job = SimpleNamespace(
        state="interrupted",
        attempt=1,
        safe_error_code="provider_confirmation_required",
    )
    database = _ProcessSession(
        revision,
        job,
        operation,
        SimpleNamespace(id=revision.report_id),
        SimpleNamespace(
            id="run-id",
            state="executing",
            report_revision_id=revision.id,
            debate_id=revision.debate_id,
        ),
    )
    prepared = service.RealReportPreparedOperation(
        revision.id,
        revision.debate_id,
        operation.export_manifest_hash,
        operation.id,
        drifted_wire,
        context,
    )
    repository = _ProcessRepository(operation)
    monkeypatch.setattr(service, "_mark_job_running", lambda *_args: True)
    monkeypatch.setattr(service, "_mark_job_failed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        service,
        "prepare_real_report_operation",
        lambda *_args, **_kwargs: prepared,
    )

    result = service.continue_real_report_revision(
        database,  # type: ignore[arg-type]
        revision.id,
        manifest_hash=prepared.manifest_hash,
        call_no=3,
        runtime=service.RealReportRuntime(provider, repository),
    )

    assert result.status == "failed"
    assert result.safe_error_code == "report_wire_hash_stale"
    assert provider.execute_calls == 0
    assert provider.prepared_wires == []


def test_bound_real_report_continues_once_and_publishes_immutable_ready_revision(
    monkeypatch: Any,
) -> None:
    revision = _revision()
    context = _context(revision.debate_id)
    policy_hash = "a" * 64
    provider = _PreparedProvider(policy_hash)
    operation = SimpleNamespace(
        id="operation-id",
        export_manifest_hash="b" * 64,
        acceptance_run_id="run-id",
        call_no=3,
        state="prepared",
        request_count=0,
        charged_request_count=0,
        request_hash="d" * 64,
        policy_hash=policy_hash,
        max_cost_cny=0.01,
    )
    report = SimpleNamespace(
        id=revision.report_id,
        generation_status="generating",
        latest_attempt_status="generating",
    )
    job = SimpleNamespace(
        state="interrupted",
        attempt=1,
        safe_error_code="provider_confirmation_required",
    )
    run = SimpleNamespace(
        id="run-id",
        state="executing",
        report_revision_id=revision.id,
        debate_id=revision.debate_id,
    )
    database = _ProcessSession(revision, job, operation, report, run)
    prepared = service.RealReportPreparedOperation(
        revision.id,
        revision.debate_id,
        operation.export_manifest_hash,
        operation.id,
        provider.build_request(service.build_real_report_request(context)),
        context,
    )
    repository = _ProcessRepository(operation)
    monkeypatch.setattr(service, "_mark_job_running", lambda *_args: True)
    monkeypatch.setattr(service, "_mark_job_failed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_mark_job_completed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_mark_debate_completed", lambda *_args: None)
    monkeypatch.setattr(
        service,
        "prepare_real_report_operation",
        lambda *_args, **_kwargs: prepared,
    )

    result = service.continue_real_report_revision(
        database,  # type: ignore[arg-type]
        revision.id,
        manifest_hash=prepared.manifest_hash,
        call_no=3,
        runtime=service.RealReportRuntime(provider, repository),
    )

    assert result.status == "ready"
    assert result.english_markdown
    assert result.word_count is not None and result.word_count >= 0
    assert provider.execute_calls == 1
    assert provider.prepared_wires == [prepared.wire]
    assert repository.transitions == ["confirmed", "reserved", "sending", "succeeded"]
    assert operation.state == "succeeded"


def test_sqlite_report_success_stays_sending_when_caller_rolls_back(tmp_path: Any) -> None:
    database = Database(f"sqlite:///{tmp_path / 'report-rollback.sqlite3'}")
    database.upgrade_schema()
    repository = ProviderRepository(database, require_export_confirmation=False)
    policy = _policy()
    policy_id = repository.save_policy_snapshot(policy, snapshot_id="report-policy")
    manifest = ExportManifestV1(
        scope_id="debate-id",
        provider_operation="llm_maya_report",
        model_key=FIXED_MODELS["llm_maya_report"],
        policy_hash=policy.policy_hash,
        build_manifest_hash="b" * 64,
        persona_spec_hash="c" * 64,
        fields=(ExportFieldV1("aggregate_vote_count", "d" * 64),),
        max_attempts=1,
        max_total_tokens=200,
        max_cost_cny=0.01,
    )
    repository.save_export_manifest(manifest, policy_snapshot_id=policy_id)
    repository.save_scope_budget(
        "debate-id",
        ProviderScopeBudgetV1(
            max_requests=1,
            max_total_tokens=200,
            max_cost_cny=0.01,
            budget_bucket=LLM_MAYA_REPORT_BUCKET,
        ),
    )
    operation = repository.create_prepared(
        ProviderReservationRequestV1(
            operation_id="report-operation",
            scope_id="debate-id",
            provider_operation="llm_maya_report",
            logical_item_id="revision-id",
            attempt_no=1,
            request_hash="e" * 64,
            max_tokens=200,
            max_cost_cny=0.01,
            policy_hash=policy.policy_hash,
            export_manifest_hash=manifest.manifest_hash,
            model_key=manifest.model_key,
            budget_bucket=LLM_MAYA_REPORT_BUCKET,
        )
    )
    repository.reserve(operation.id)
    repository.transition(operation.id, expected="reserved", state="sending")

    caller = database.session_factory()
    try:
        repository.complete_report_in_session(
            caller,
            operation.id,
            response_hash="f" * 64,
        )
        caller.rollback()
    finally:
        caller.close()

    durable = repository.get(operation.id)
    assert durable is not None
    assert durable.state == "sending"
    assert durable.staged_response_hash is None
    assert repository.reservation(operation.id).state == "sending"
    database.dispose()
