"""Debate speech and the Maya report pass global pressure protection.

2026-10-19: Debate turn text already waited for an LLM slot while its call
was only reserved. Two Debate provider paths did not: the speech (TTS) call
held no slot at all, and the report took its slot only inside the transport,
after the operation was "sending" -- a refusal under pressure then failed the
report for good. Both now wait in the lowest ("llm") class; a refusal is a
degraded or deferred outcome, never a stuck lesson or a lost report.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.core.llm_admission import llm_admission_held
from app.modules.debates.playback import audio as audio_module
from app.modules.debates.playback.audio import AudioStore
from app.modules.reports import service, task_manager
from app.providers.tts import MockTTSProvider, TTSProviderError, TTSResult

from tests.test_real_report_service import (
    _context,
    _PreparedProvider,
    _ProcessRepository,
    _ProcessSession,
    _revision,
)


def _busy() -> PlatformError:
    return PlatformError(
        "llm_admission_busy",
        "busy",
        503,
        {"retryable": True, "retry_after_seconds": 4},
    )


@contextmanager
def _refused() -> Any:
    raise _busy()
    yield  # pragma: no cover


class _RealishTTS:
    """A non-Mock provider key with Mock audio bytes."""

    key = "dashscope"
    target_model_key = "fixture-tts"

    def __init__(self) -> None:
        self.inner = MockTTSProvider()
        self.held_slot: list[bool] = []

    def synthesize(self, text: str, voice: str, **kwargs: Any) -> TTSResult:
        self.held_slot.append(llm_admission_held())
        return self.inner.synthesize(text, voice, **kwargs)


def _ids() -> dict[str, str]:
    return {"course_id": str(uuid4()), "debate_id": str(uuid4()), "turn_id": str(uuid4())}


def test_debate_speech_holds_an_llm_slot(tmp_path: Any) -> None:
    provider = _RealishTTS()
    store = AudioStore(tmp_path, tts_provider=provider)  # type: ignore[arg-type]
    store.synthesize_and_store(**_ids(), speech="Hello class.", voice_token="voice")
    store.stage_synthesis(**_ids(), speech="Second turn.", voice_token="voice")
    assert provider.held_slot == [True, True]


def test_mock_speech_takes_no_slot(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_module, "llm_admission_slot", _refused)
    store = AudioStore(tmp_path)  # the local Mock makes no outbound call
    metadata = store.synthesize_and_store(**_ids(), speech="Hello.", voice_token="voice")
    assert metadata.size_bytes > 0


def test_refused_speech_slot_plays_the_turn_as_text(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _RealishTTS()
    monkeypatch.setattr(audio_module, "llm_admission_slot", _refused)
    store = AudioStore(tmp_path, tts_provider=provider)  # type: ignore[arg-type]
    with pytest.raises(TTSProviderError) as refused:
        store.synthesize_and_store(**_ids(), speech="Hello.", voice_token="voice")
    # The existing degraded outcome: the turn is ready as text, audio later.
    assert refused.value.safe_code == "tts_provider_unavailable"
    assert provider.held_slot == []


def _report_fixture(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
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
        id=revision.report_id, generation_status="generating", latest_attempt_status="generating"
    )
    job = SimpleNamespace(
        state="interrupted", attempt=1, safe_error_code="provider_confirmation_required"
    )
    run = SimpleNamespace(
        id="run-id", state="executing", report_revision_id=revision.id, debate_id=revision.debate_id
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
    monkeypatch.setattr(service, "prepare_real_report_operation", lambda *_a, **_k: prepared)
    return revision, provider, operation, database, prepared, repository


def test_report_takes_its_slot_before_reserving_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    revision, provider, operation, database, prepared, repository = _report_fixture(monkeypatch)
    order: list[str] = []

    @contextmanager
    def slot() -> Any:
        order.append(f"slot after {list(repository.transitions)}")
        yield

    monkeypatch.setattr(service, "llm_admission_slot", slot)
    result = service.continue_real_report_revision(
        database,  # type: ignore[arg-type]
        revision.id,
        manifest_hash=prepared.manifest_hash,
        call_no=3,
        runtime=service.RealReportRuntime(provider, repository),
    )
    assert result.status == "ready"
    # Admitted while the operation was still only prepared.
    assert order == ["slot after ['confirmed']"]
    assert repository.transitions == ["confirmed", "reserved", "sending", "succeeded"]


def test_refused_report_slot_defers_the_job_without_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision, provider, operation, database, prepared, repository = _report_fixture(monkeypatch)
    deferred: list[str] = []
    monkeypatch.setattr(service, "llm_admission_slot", _refused)
    monkeypatch.setattr(service, "_defer_real_report_job", lambda _db, rid: deferred.append(rid))

    with pytest.raises(service.ReportAdmissionDeferred) as busy:
        service.continue_real_report_revision(
            database,  # type: ignore[arg-type]
            revision.id,
            manifest_hash=prepared.manifest_hash,
            call_no=3,
            runtime=service.RealReportRuntime(provider, repository),
        )
    # A route answers the usual retryable 503; the worker retries later.
    assert busy.value.status_code == 503
    assert busy.value.details == {"retryable": True, "retry_after_seconds": 4}
    assert deferred == [revision.id]
    assert provider.execute_calls == 0
    assert repository.transitions == ["confirmed"]
    assert operation.state == "prepared"
    assert revision.status == "generating"


def test_report_worker_retries_a_deferred_job_instead_of_failing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = task_manager.ReportTaskManager(lambda: None, lambda *_args: True)  # type: ignore[arg-type,return-value]
    jobs = iter([("report.generate", "revision-id")])
    monkeypatch.setattr(manager, "_next_job", lambda _debate: next(jobs, None))

    def deferred(_debate: str, _revision: str) -> None:
        raise service.ReportAdmissionDeferred(7)

    retries: list[tuple[str, float]] = []
    failures: list[str] = []
    monkeypatch.setattr(manager, "_run_report", deferred)
    monkeypatch.setattr(manager, "_retry_later", lambda d, s: retries.append((d, s)))
    monkeypatch.setattr(manager, "_fail_stuck_job", lambda d, *_a: failures.append(d))

    manager._run_chain("debate-id")

    assert retries == [("debate-id", 7)]
    assert failures == []
