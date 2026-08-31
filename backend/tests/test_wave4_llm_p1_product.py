"""Focused P1-A/P1-B product seams; all provider calls are fake/local."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.models import Job, StoredFile
from app.modules.debates.generation import (
    GenerationContext,
    LLMTurnRuntime,
    MutualLearningPolicy,
    build_provider_prompt,
)
from app.modules.debates.generation.recovery_input import build_llm_recovery_input
from app.modules.debates.generation.runtime import LLMDeferredPublicationV1
from app.modules.debates.models import Debate, DebatePlaybackState, DebateTurn, TurnSource
from app.modules.debates.playback.audio import AudioStore, audio_relative_path
from app.modules.debates.playback.generation_adapter import SqlTurnPreparer
from app.modules.debates.playback.llm_publication import SqlLLMPublication
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository
from app.modules.debates.playback.task_manager import TaskManager
from app.providers.control import (
    LLM_DEBATE_TURN_BUCKET,
    InMemoryProviderOperationRepository,
    LLMRecoveryInputV1,
    ProviderScopeBudgetV1,
)
from app.providers.control_repository import ProviderRepository
from app.providers.llm import MockLLMProvider
from app.providers.llm_adapter import (
    DashScopeLLMAdapter,
    DashScopeLLMConfig,
    LLMUsageV1,
    _stage_candidate,
)
from app.providers.llm_price_card import LLMPriceCardV1
from app.providers.llm_privacy import LLMOutboundManifestV1
from app.providers.llm_tokenizer import PinnedLLMTokenizer
from app.providers.tts import MockTTSProvider, TTSProviderTimeout
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from tests.conftest import login
from tests.test_wave2_playback import (
    COURSE_ID,
    GROUP_BOWEN_ID,
    GROUP_KAIKAI_ID,
    TOPIC,
    _headers,
    _insert_published_agent,
    _wait_for_ready,
)
from tests.test_wave4_llm_runtime import _disclosure_policy, _FakeAdapter, _participants


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class _FakeDashScopeAdapter(DashScopeLLMAdapter):
    """DashScope-shaped adapter whose accepted result is generated locally."""

    def __init__(self) -> None:
        tokenizer = PinnedLLMTokenizer(
            tokenizer_id="pinned-product-test-tokenizer",
            asset_hash=_hash("pinned-product-test-tokenizer"),
            counter=lambda value: max(1, len(value.split())),
        )
        price_card = LLMPriceCardV1(
            input_price_per_million=Decimal("1"),
            cached_input_price_per_million=Decimal("1"),
            output_price_per_million=Decimal("1"),
            retrieved_at="2026-08-31T00:00:00Z",
            source_content_sha256=_hash("product-price-card"),
        )
        super().__init__(
            DashScopeLLMConfig(
                api_key="fake-product-key",
                workspace_id="fake-product-workspace",
                policy_hash=_hash("product-policy"),
            ),
            tokenizer=tokenizer,
            price_card=price_card,
            outbound_manifest=LLMOutboundManifestV1(),
        )
        self._mock = MockLLMProvider()
        self.call_count = 0

    def send_accepted(self, request: object, **_metadata: object) -> object:
        self.call_count += 1
        result = self._mock.generate_turn(request.prompt)  # type: ignore[attr-defined]
        prompt_request = request.prompt.request  # type: ignore[attr-defined]
        evidence_refs = {
            item.evidence_id: index for index, item in enumerate(prompt_request.evidence_catalog)
        }
        provider_output = {
            "schema_version": "llm_turn_output_v1",
            "phase": prompt_request.phase,
            "speech": result.speech,
            "key_claims": [
                {
                    "claim_text": claim.claim_text,
                    "claim_type": (
                        "interpretation" if claim.claim_type == "background" else claim.claim_type
                    ),
                    "used_evidence_refs": [
                        evidence_refs[evidence_id]
                        for evidence_id in claim.used_evidence_ids
                        if evidence_id in evidence_refs
                    ],
                }
                for claim in result.key_claims
            ],
            "engagements": [],
            "answered_required_question": False,
            "learned_from_others": list(result.learned_from_others),
            "position_summary": result.position_summary,
            "position_update": result.position_update or "unchanged",
            "position_update_reason": (
                result.position_update_reason or "The opening establishes the position."
            ),
            "remaining_uncertainty": list(result.remaining_uncertainty),
            "unresolved_issue": result.unresolved_issue or "",
            "question": {"mode": "none", "target_participant_ref": -1, "text": ""},
            "missing_information": list(result.missing_information),
            "unresolved_questions": list(result.unresolved_questions),
            "change_from_opening": result.change_from_opening or "",
            "final_consensus": list(result.final_consensus),
            "final_disagreements": [
                {"summary": item.summary, "category": item.category}
                for item in result.final_disagreements
            ],
            "final_recommendation": result.final_recommendation or "",
        }
        return _stage_candidate(
            request,
            http_status=200,
            finish_reason="stop",
            usage=LLMUsageV1(1, 0, 1, 2),
            price_card=self.price_card,
            provider_output=provider_output,
            actual_cost_cny=Decimal("0"),
        )


class _FailingTTS(MockTTSProvider):
    def synthesize(self, text: str, external_voice_id: str, *, language: str = "en") -> object:
        del text, external_voice_id, language
        self.synthesize_calls += 1
        raise TTSProviderTimeout("local test interruption", safe_code="tts_timeout")


def _seed_running_product_debate(
    app_factory: object,
    *,
    cancellation_generation: int = 0,
) -> tuple[object, Database, object, str, str]:
    """Create a real seeded two-participant Debate with its initial job."""

    app, database, settings = app_factory()  # type: ignore[operator]
    with TestClient(app) as client:
        bowen_id = _insert_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="P1 Product Bowen",
            evidence=(
                f"{TOPIC} A classroom snapshot records transparency, privacy, "
                "accountability, and meaningful user choice for platform governance."
            ),
        )
        kaikai_id = _insert_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="P1 Product KaiKai",
            evidence=(
                f"{TOPIC} A second snapshot records proportional safeguards, public "
                "review, and space for responsible innovation."
            ),
        )
        _session, csrf = login(client)
        response = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": f"p1-product-create-{uuid4()}"}),
            json={
                "topic": TOPIC,
                "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
                "participants": [
                    {"agent_id": bowen_id, "stance_mode": "assigned", "assigned_stance": "support"},
                    {"agent_id": kaikai_id, "stance_mode": "assigned", "assigned_stance": "oppose"},
                ],
                "round_count": 2,
            },
        )
        assert response.status_code == 201, response.text
        debate_id = response.json()["id"]
        started = client.post(
            f"/api/v1/debates/{debate_id}/start",
            headers=_headers(
                csrf,
                **{"Idempotency-Key": f"p1-product-start-{uuid4()}"},
            ),
            json={
                "expected_revision": 0,
                "expected_current_audio_debate_id": None,
                "confirm_previous_audio_cleanup": False,
            },
        )
        assert started.status_code == 200, started.text
        _wait_for_ready(client, debate_id)
    prior_audio_path: str | None = None
    with database.session() as db:
        debate = db.get(Debate, debate_id)
        assert debate is not None
        first = db.scalar(
            select(DebateTurn)
            .where(DebateTurn.debate_id == debate_id)
            .order_by(DebateTurn.turn_index)
        )
        assert first is not None
        playback = db.scalar(
            select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
        )
        assert playback is not None
        debate.status = "running"
        debate.finished_at = None
        debate.cancellation_generation = cancellation_generation
        playback.status = "ready"
        playback.mode = "live"
        playback.current_turn_id = first.id
        playback.control_version = 0
        first.generation_status = "pending"
        first.preparation_stage = "generation"
        first.publication_status = "unpublished"
        first.speech = None
        first.structured_json = None
        first.transcript_hash = None
        first.retrieval_status = None
        first.grounding_mode = None
        first.retrieval_receipts_json = "[]"
        first.evidence_trace_json = "[]"
        first.word_count = None
        first.audio_duration_ms = None
        first.actual_tts_voice_kind = None
        first.actual_tts_voice_profile_id = None
        first.safe_error_code = None
        if first.audio_file_id is not None:
            stored = db.get(StoredFile, first.audio_file_id)
            if stored is not None:
                prior_audio_path = stored.relative_path
            first.audio_file_id = None
            db.flush()
            if stored is not None:
                db.delete(stored)
        for source in db.scalars(select(TurnSource).where(TurnSource.turn_id == first.id)).all():
            db.delete(source)
        job = db.scalar(select(Job).where(Job.turn_id == first.id))
        assert job is not None
        job.state = "pending"
        job.claim_token = None
        job.cancellation_generation = cancellation_generation
        job.attempt = 0
    if prior_audio_path is not None:
        (Path(settings.resolved_data_root) / prior_audio_path).unlink(missing_ok=True)
    return app, database, settings, debate_id, str(first.id)


def _product_service(
    database: Database,
    settings: object,
    *,
    preparer: object,
    tts_provider: object,
    tasks: TaskManager | None = None,
) -> PlaybackService:
    task_manager = tasks or TaskManager()
    return PlaybackService(
        SqlPlaybackRepository(session_factory=database.session_factory),
        audio_store=AudioStore(settings.resolved_data_root, tts_provider=tts_provider),  # type: ignore[attr-defined]
        task_manager=task_manager,
        session_factory=database.session_factory,
        settings=settings,
        tts_provider=tts_provider,
        turn_preparer=preparer,
    )


def _product_preparer(settings: object, adapter: _FakeDashScopeAdapter) -> SqlTurnPreparer:
    return SqlTurnPreparer(settings=settings, llm=adapter)


def _install_fake_dashscope_product_path(
    database: Database,
    settings: object,
    adapter: _FakeDashScopeAdapter,
) -> None:
    # Bind the fake's explicit workspace endpoint to the reviewed fixture
    # policy. Production endpoint preflight must remain strict; this test
    # fixture simply makes its local fake resource internally consistent.
    policy = replace(_disclosure_policy(), endpoint=adapter.config.resolved_endpoint)
    repository = ProviderRepository(database, require_export_confirmation=False)
    policy_id = repository.save_policy_snapshot(policy, snapshot_id="product-policy")
    settings.provider_policy_hash = policy.policy_hash  # type: ignore[attr-defined]
    settings.llm_provider = "dashscope"  # type: ignore[attr-defined]
    settings.dashscope_api_key = "fake-product-key"  # type: ignore[attr-defined]
    settings.dashscope_workspace_id = "fake-product-workspace"  # type: ignore[attr-defined]
    settings.dashscope_region = "cn-beijing"  # type: ignore[attr-defined]
    assert repository.get_policy_snapshot(policy_id) is not None
    # The product preparer asks the same exact confirmation seam that the
    # teacher disclosure route owns.  This test supplies a local, reviewed
    # approval so no external provider or network is involved.


def _patch_local_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.debates.playback import generation_adapter

    monkeypatch.setattr(
        generation_adapter,
        "require_exact_confirmation",
        lambda *_args, **_kwargs: SimpleNamespace(confirmation_revision=1),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancellation_generation", [0, 7])
async def test_restart_requeues_complete_bundle_without_llm_call_and_publishes_product(
    app_factory: object,
    monkeypatch: pytest.MonkeyPatch,
    cancellation_generation: int,
) -> None:
    _app, database, settings, debate_id, turn_id = _seed_running_product_debate(
        app_factory,
        cancellation_generation=cancellation_generation,
    )
    adapter = _FakeDashScopeAdapter()
    _install_fake_dashscope_product_path(database, settings, adapter)
    _patch_local_confirmation(monkeypatch)
    first_tts = _FailingTTS()
    first_tasks = TaskManager()
    preparer = _product_preparer(settings, adapter)
    service = _product_service(
        database,
        settings,
        preparer=preparer,
        tts_provider=first_tts,
        tasks=first_tasks,
    )
    try:
        with database.session() as db:
            await service.prepare_turn(db, debate_id, turn_id)
        with database.engine.connect() as connection:
            staged = connection.execute(
                text(
                    "SELECT p.state,s.generation_status,s.safe_error_code "
                    "FROM provider_operations AS p "
                    "JOIN llm_accepted_stages AS a ON a.operation_id=p.id "
                    "JOIN debate_turns AS s ON s.id=a.turn_id "
                    "WHERE s.id=:turn_id AND p.state='accepted'"
                ),
                {"turn_id": turn_id},
            ).one()
            assert staged == ("accepted", "pending", "tts_timeout")
            assert (
                connection.execute(text("SELECT COUNT(*) FROM llm_recovery_inputs")).scalar_one()
                == adapter.call_count
            )
        calls_before_restart = adapter.call_count
        assert calls_before_restart in {1, 2}
        await first_tasks.close()

        restart_tts = MockTTSProvider()
        restart_tasks = TaskManager()
        restarted = _product_service(
            database,
            settings,
            preparer=_product_preparer(settings, adapter),
            tts_provider=restart_tts,
            tasks=restart_tasks,
        )
        with database.session() as db:
            await restarted.recover_startup(db)
        await restart_tasks.wait_debate(debate_id)
        assert adapter.call_count == calls_before_restart
        assert restart_tts.synthesize_calls == 1
        with database.engine.connect() as connection:
            turn = connection.execute(
                text(
                    "SELECT generation_status,publication_status,evidence_trace_json,"
                    "retrieval_receipts_json FROM debate_turns WHERE id=:turn_id"
                ),
                {"turn_id": turn_id},
            ).one()
            assert turn[0:2] == ("final_ready", "unpublished")
            assert json.loads(str(turn[2]))
            receipts = json.loads(str(turn[3]))
            assert receipts
            operation = connection.execute(
                text(
                    "SELECT p.state,r.state FROM provider_operations AS p "
                    "JOIN provider_reservations AS r ON r.operation_id=p.id "
                    "WHERE p.logical_item_id=:turn_id"
                ),
                {"turn_id": turn_id},
            ).one()
            assert operation == ("succeeded", "succeeded")
            assert (
                connection.execute(
                    text("SELECT state FROM jobs WHERE turn_id=:turn_id"), {"turn_id": turn_id}
                ).scalar_one()
                == "completed"
            )
            source = connection.execute(
                text(
                    "SELECT snapshot_id,chunk_id FROM turn_sources WHERE turn_id=:turn_id "
                    "ORDER BY rank LIMIT 1"
                ),
                {"turn_id": turn_id},
            ).one()
            assert (receipts[0]["snapshot_id"], receipts[0]["chunk_id"]) == tuple(source)
    finally:
        await first_tasks.close()
        database.dispose()


@pytest.mark.asyncio
async def test_legacy_accepted_stage_without_recovery_input_stays_blocked_and_zero_call(
    app_factory: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app, database, settings, debate_id, turn_id = _seed_running_product_debate(app_factory)
    adapter = _FakeDashScopeAdapter()
    _install_fake_dashscope_product_path(database, settings, adapter)
    _patch_local_confirmation(monkeypatch)
    first_tasks = TaskManager()
    service = _product_service(
        database,
        settings,
        preparer=_product_preparer(settings, adapter),
        tts_provider=_FailingTTS(),
        tasks=first_tasks,
    )
    try:
        with database.session() as db:
            await service.prepare_turn(db, debate_id, turn_id)
        calls_before_restart = adapter.call_count
        assert calls_before_restart in {1, 2}
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM llm_recovery_inputs WHERE operation_id IN "
                    "(SELECT id FROM provider_operations WHERE logical_item_id=:turn_id "
                    "AND state='accepted')"
                ),
                {"turn_id": turn_id},
            )
        await first_tasks.close()

        restart_tts = MockTTSProvider()
        restart_tasks = TaskManager()
        restarted = _product_service(
            database,
            settings,
            preparer=_product_preparer(settings, adapter),
            tts_provider=restart_tts,
            tasks=restart_tasks,
        )
        with database.session() as db:
            await restarted.recover_startup(db)
        await restart_tasks.wait_debate(debate_id)
        assert adapter.call_count == calls_before_restart
        assert restart_tts.synthesize_calls == 0
        with database.engine.connect() as connection:
            blocked = connection.execute(
                text(
                    "SELECT d.status,t.generation_status,t.safe_error_code,j.state,"
                    "j.safe_error_code,p.state,r.state FROM debates AS d "
                    "JOIN debate_turns AS t ON t.debate_id=d.id "
                    "JOIN jobs AS j ON j.turn_id=t.id "
                    "JOIN provider_operations AS p ON p.logical_item_id=t.id "
                    "JOIN provider_reservations AS r ON r.operation_id=p.id "
                    "WHERE t.id=:turn_id AND p.state='accepted'"
                ),
                {"turn_id": turn_id},
            ).one()
            assert blocked == (
                "running",
                "pending",
                "llm_recovery_input_unavailable",
                "pending",
                "llm_recovery_input_unavailable",
                "accepted",
                "accepted",
            )
    finally:
        await first_tasks.close()
        database.dispose()


@pytest.mark.asyncio
async def test_playback_publication_failure_rolls_back_turn_files_and_operation(
    app_factory: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app, database, settings, debate_id, turn_id = _seed_running_product_debate(app_factory)
    adapter = _FakeDashScopeAdapter()
    _install_fake_dashscope_product_path(database, settings, adapter)
    _patch_local_confirmation(monkeypatch)

    def reject_publication(_self: object, **_kwargs: object) -> object:
        raise RuntimeError("injected publication failure")

    monkeypatch.setattr(SqlLLMPublication, "commit_llm_turn_success", reject_publication)
    tasks = TaskManager()
    tts = MockTTSProvider()
    service = _product_service(
        database,
        settings,
        preparer=_product_preparer(settings, adapter),
        tts_provider=tts,
        tasks=tasks,
    )
    relative_audio_path = audio_relative_path(COURSE_ID, debate_id, turn_id)
    try:
        with database.session() as db:
            await service.prepare_turn(db, debate_id, turn_id)
        assert tts.synthesize_calls == 1
        with database.engine.connect() as connection:
            state = connection.execute(
                text(
                    "SELECT d.status,t.generation_status,t.speech,t.structured_json,j.state,"
                    "p.state,r.state FROM debates AS d "
                    "JOIN debate_turns AS t ON t.debate_id=d.id "
                    "JOIN jobs AS j ON j.turn_id=t.id "
                    "JOIN provider_operations AS p ON p.logical_item_id=t.id "
                    "JOIN provider_reservations AS r ON r.operation_id=p.id "
                    "WHERE t.id=:turn_id AND p.state='accepted'"
                ),
                {"turn_id": turn_id},
            ).one()
            assert state == (
                "failed",
                "turn_generation_failed",
                None,
                None,
                "failed",
                "accepted",
                "accepted",
            )
            assert (
                connection.execute(
                    text("SELECT COUNT(*) FROM turn_sources WHERE turn_id=:turn_id"),
                    {"turn_id": turn_id},
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM stored_files "
                        "WHERE kind='debate_audio' AND relative_path=:relative_path"
                    ),
                    {"relative_path": relative_audio_path},
                ).scalar_one()
                == 0
            )
        path = Path(settings.resolved_data_root) / relative_audio_path
        assert not path.exists()
    finally:
        await tasks.close()
        database.dispose()


def test_deferred_runtime_keeps_accepted_operation_until_playback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.debates.generation import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "scan_llm_outbound_messages", lambda *args, **kwargs: None)
    people = _participants()
    plan = MutualLearningPolicy().plan(people, round_count=2)[0]
    context = GenerationContext(
        debate_id="debate-p1",
        topic="A safe topic",
        turn=plan,
        participant=people[0],
        participants=people,
    )
    prompt = build_provider_prompt(context, persona=people[0].persona)
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=8,
            max_total_tokens=100_000,
            max_cost_cny=5,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    runtime = LLMTurnRuntime(ledger=ledger, adapter=_FakeAdapter(), defer_publication=True)
    prepared = runtime.prepare(
        prompt,
        debate_id=context.debate_id,
        turn_id=plan.turn_id,
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
        fence={
            "predecessor_turn_ids": [],
            "transcript_hash": prompt.request.transcript_hash,
            "cutoff_turn_index": -1,
            "generation": 0,
        },
    )
    outcome = runtime.run(prepared, context=context, confirmed=True)
    assert outcome.status == "succeeded"
    assert outcome.operation is not None
    assert getattr(outcome.operation, "state", None) == "accepted"
    assert isinstance(outcome.deferred_publication, LLMDeferredPublicationV1)


def _create_atomic_schema(database: Database) -> None:
    with database.engine.begin() as connection:
        for statement in (
            "CREATE TABLE debates (id TEXT PRIMARY KEY, cancellation_generation INTEGER NOT NULL)",
            (
                "CREATE TABLE debate_turns (id TEXT PRIMARY KEY, debate_id TEXT NOT NULL, "
                "participant_id TEXT NOT NULL, knowledge_snapshot_id TEXT NOT NULL, "
                "generation_status TEXT NOT NULL, structured_json TEXT, "
                "evidence_trace_json TEXT, predecessor_turn_ids_json TEXT NOT NULL, "
                "transcript_hash TEXT, cutoff_turn_index INTEGER)"
            ),
            (
                "CREATE TABLE provider_operations (id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, "
                "provider_operation TEXT NOT NULL, logical_item_id TEXT NOT NULL, "
                "attempt_no INTEGER NOT NULL, request_hash TEXT NOT NULL, "
                "staged_response_hash TEXT, state TEXT NOT NULL, updated_at TEXT)"
            ),
            "CREATE TABLE provider_reservations (operation_id TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT)",  # noqa: E501
            (
                "CREATE TABLE llm_accepted_stages (operation_id TEXT PRIMARY KEY, "
                "turn_id TEXT NOT NULL, attempt_no INTEGER NOT NULL, request_hash TEXT NOT NULL, "
                "prompt_hash TEXT NOT NULL, prompt_contract_version TEXT NOT NULL, "
                "schema_hash TEXT NOT NULL, tokenizer_id TEXT NOT NULL, tokenizer_hash TEXT NOT NULL, "  # noqa: E501
                "rule_set_hash TEXT NOT NULL, persona_spec_hash TEXT NOT NULL, "
                "transcript_hash TEXT NOT NULL, receipt_hash TEXT NOT NULL, policy_hash TEXT NOT NULL, "  # noqa: E501
                "export_manifest_hash TEXT NOT NULL, build_manifest_hash TEXT NOT NULL, "
                "repair_policy_hash TEXT, generation_fence TEXT NOT NULL, model_key TEXT NOT NULL, "
                "output_json TEXT NOT NULL, output_hash TEXT NOT NULL)"
            ),
            (
                "CREATE TABLE llm_recovery_inputs (operation_id TEXT PRIMARY KEY, "
                "turn_id TEXT NOT NULL, attempt_no INTEGER NOT NULL, input_version TEXT NOT NULL, "
                "input_json TEXT NOT NULL, input_hash TEXT NOT NULL)"
            ),
            (
                "CREATE TABLE provider_export_manifests (manifest_hash TEXT PRIMARY KEY, "
                "scope_id TEXT NOT NULL, provider_operation TEXT NOT NULL, model_key TEXT NOT NULL, "  # noqa: E501
                "policy_hash TEXT NOT NULL, build_manifest_hash TEXT NOT NULL, debate_id TEXT, "
                "turn_id TEXT, max_attempts INTEGER NOT NULL, max_total_tokens INTEGER NOT NULL, "
                "max_cost_cny TEXT NOT NULL, repair_policy_version TEXT, repair_policy_hash TEXT)"
            ),
            "CREATE TABLE knowledge_chunks (id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, chunk_text TEXT NOT NULL)",  # noqa: E501
        ):
            connection.execute(text(statement))


def _atomic_fixture(database: Database) -> tuple[SimpleNamespace, SimpleNamespace]:
    operation_id = "operation-p1"
    turn_id = "turn-p1"
    debate_id = "debate-p1"
    request_hash = _hash("request")
    request_payload = {
        "request_version": "prompt_request_v1",
        "debate_id": debate_id,
        "turn_id": turn_id,
        "participant_id": "participant",
        "transcript_hash": _hash("transcript"),
    }
    prompt_hash = _hash(request_payload)
    schema_hash = _hash("schema")
    tokenizer_hash = _hash("tokenizer")
    rule_set_hash = _hash("rule-set")
    persona_spec_hash = _hash("persona")
    transcript_hash = _hash("transcript")
    receipt_hash = _hash("receipt")
    policy_hash = _hash("policy")
    manifest_hash = _hash("manifest")
    build_manifest_hash = _hash("build")
    fence = {
        "predecessor_turn_ids": [],
        "transcript_hash": transcript_hash,
        "cutoff_turn_index": -1,
        "generation": 0,
    }
    fence_hash = _hash(fence)
    identity = {
        "request_hash": request_hash,
        "prompt_hash": prompt_hash,
        "prompt_contract_version": "prompt_request_v1",
        "schema_hash": schema_hash,
        "tokenizer_id": "tokenizer",
        "tokenizer_hash": tokenizer_hash,
        "rule_set_hash": rule_set_hash,
        "persona_spec_hash": persona_spec_hash,
        "transcript_hash": transcript_hash,
        "receipt_hash": receipt_hash,
        "policy_hash": policy_hash,
        "export_manifest_hash": manifest_hash,
        "build_manifest_hash": build_manifest_hash,
        "repair_policy_hash": None,
        "generation_fence": fence_hash,
        "model_key": "qwen3.7-plus-2026-05-26",
        "debate_id": debate_id,
        "turn_id": turn_id,
        "attempt_no": 1,
    }
    envelope = {
        "identity": identity,
        "input": {
            "request": request_payload,
            "context": {"debate_id": debate_id},
            "receipts": [],
            "queries": [],
            "fence": fence,
        },
    }
    input_json = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    input_hash = hashlib.sha256(input_json.encode()).hexdigest()
    stage = SimpleNamespace(
        operation_id=operation_id,
        turn_id=turn_id,
        attempt_no=1,
        request_hash=request_hash,
        prompt_hash=prompt_hash,
        prompt_contract_version="prompt_request_v1",
        schema_hash=schema_hash,
        tokenizer_id="tokenizer",
        tokenizer_hash=tokenizer_hash,
        rule_set_hash=rule_set_hash,
        persona_spec_hash=persona_spec_hash,
        transcript_hash=transcript_hash,
        receipt_hash=receipt_hash,
        policy_hash=policy_hash,
        export_manifest_hash=manifest_hash,
        build_manifest_hash=build_manifest_hash,
        repair_policy_hash=None,
        generation_fence=fence_hash,
        model_key="qwen3.7-plus-2026-05-26",
        output_hash="o" * 64,
        output_json='{"speech":"ok"}',
        repair_policy_version=None,
    )
    recovery = LLMRecoveryInputV1(
        operation_id=operation_id,
        turn_id=turn_id,
        attempt_no=1,
        input_version="llm_recovery_input_v1",
        input_json=input_json,
        input_hash=input_hash,
    )
    with database.engine.begin() as connection:
        connection.execute(text("INSERT INTO debates VALUES (:id,0)"), {"id": debate_id})
        connection.execute(
            text(
                "INSERT INTO debate_turns VALUES (:id,:debate_id,:participant,:snapshot,'final_ready','{}','[]','[]',:transcript,-1)"  # noqa: E501
            ),
            {
                "id": turn_id,
                "debate_id": debate_id,
                "participant": "participant",
                "snapshot": "snapshot",
                "transcript": transcript_hash,
            },
        )
        connection.execute(
            text(
                "INSERT INTO provider_operations VALUES (:id,:scope,'llm_debate_turn',:turn,1,:request,:output,'accepted','now')"  # noqa: E501
            ),
            {
                "id": operation_id,
                "scope": debate_id,
                "turn": turn_id,
                "request": request_hash,
                "output": "o" * 64,
            },  # noqa: E501
        )
        connection.execute(
            text("INSERT INTO provider_reservations VALUES (:id,'accepted','now')"),
            {"id": operation_id},
        )  # noqa: E501
        connection.execute(
            text(
                "INSERT INTO llm_accepted_stages (operation_id,turn_id,attempt_no,request_hash,prompt_hash,prompt_contract_version,schema_hash,tokenizer_id,tokenizer_hash,rule_set_hash,persona_spec_hash,transcript_hash,receipt_hash,policy_hash,export_manifest_hash,build_manifest_hash,repair_policy_hash,generation_fence,model_key,output_json,output_hash) VALUES (:operation_id,:turn_id,1,:request_hash,:prompt_hash,:prompt_contract_version,:schema_hash,:tokenizer_id,:tokenizer_hash,:rule_set_hash,:persona_spec_hash,:transcript_hash,:receipt_hash,:policy_hash,:export_manifest_hash,:build_manifest_hash,NULL,:generation_fence,:model_key,:output_json,:output_hash)"  # noqa: E501
            ),
            vars(stage),
        )
        connection.execute(
            text(
                "INSERT INTO llm_recovery_inputs VALUES "
                "(:operation_id,:turn_id,1,'llm_recovery_input_v1',:input_json,:input_hash)"
            ),
            recovery.as_record(),
        )
        connection.execute(
            text(
                "INSERT INTO provider_export_manifests VALUES (:manifest,:scope,'llm_debate_turn','qwen3.7-plus-2026-05-26',:policy,:build,:debate,:turn,2,100000,'5',NULL,NULL)"  # noqa: E501
            ),
            {
                "manifest": manifest_hash,
                "scope": debate_id,
                "policy": policy_hash,
                "build": build_manifest_hash,
                "debate": debate_id,
                "turn": turn_id,
            },
        )
    return stage, recovery


def test_sql_publication_promotes_operation_and_reservation_atomically(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'p1.sqlite3'}")
    _create_atomic_schema(database)
    stage, recovery = _atomic_fixture(database)
    with database.session() as db:
        db.execute(text("UPDATE debate_turns SET structured_json='ready' WHERE id='turn-p1'"))
        publication = SqlLLMPublication(db)
        publication.commit_llm_turn_success(
            operation_id=stage.operation_id,
            turn_id=stage.turn_id,
            debate_id="debate-p1",
            request_hash=stage.request_hash,
            stage=stage,
            recovery_input=recovery,
            final_ready=SimpleNamespace(
                turn_id=stage.turn_id,
                participant_id="participant",
                snapshot_id="snapshot",
                transcript_hash=stage.transcript_hash,
                cutoff_turn_index=-1,
                predecessor_turn_ids=(),
                used_receipts=(),
            ),
        )
    with database.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT state FROM provider_operations")).scalar_one()
            == "succeeded"
        )  # noqa: E501
        assert (
            connection.execute(text("SELECT state FROM provider_reservations")).scalar_one()
            == "succeeded"
        )  # noqa: E501
    database.dispose()


def test_sql_publication_failure_rolls_turn_and_operation_back(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'p1-rollback.sqlite3'}")
    _create_atomic_schema(database)
    stage, recovery = _atomic_fixture(database)
    with pytest.raises(RuntimeError, match="reservation CAS"):
        with database.session() as db:
            db.execute(text("UPDATE debate_turns SET structured_json='changed' WHERE id='turn-p1'"))
            db.execute(
                text("DELETE FROM provider_reservations WHERE operation_id=:operation_id"),
                {"operation_id": stage.operation_id},
            )
            SqlLLMPublication(db).commit_llm_turn_success(
                operation_id=stage.operation_id,
                turn_id=stage.turn_id,
                debate_id="debate-p1",
                request_hash=stage.request_hash,
                stage=stage,
                recovery_input=recovery,
                final_ready=SimpleNamespace(
                    turn_id=stage.turn_id,
                    participant_id="participant",
                    snapshot_id="snapshot",
                    transcript_hash=stage.transcript_hash,
                    cutoff_turn_index=-1,
                    predecessor_turn_ids=(),
                    used_receipts=(),
                ),
            )
    with database.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT state FROM provider_operations")).scalar_one()
            == "accepted"
        )  # noqa: E501
        assert (
            connection.execute(text("SELECT structured_json FROM debate_turns")).scalar_one()
            == "{}"
        )  # noqa: E501
        assert (
            connection.execute(text("SELECT COUNT(*) FROM provider_reservations")).scalar_one() == 1
        )  # noqa: E501
    database.dispose()


def test_recovery_projection_is_closed_and_hash_bound() -> None:
    people = _participants()
    plan = MutualLearningPolicy().plan(people, round_count=2)[0]
    context = GenerationContext(
        debate_id="debate-p1",
        topic="A safe topic",
        turn=plan,
        participant=people[0],
        participants=people,
    )
    prompt = build_provider_prompt(context, persona=people[0].persona)
    prepared = SimpleNamespace(
        operation_id="operation-p1",
        turn_id=plan.turn_id,
        attempt_no=1,
        request_hash=_hash("request"),
        debate_id="debate-p1",
        prompt=prompt,
        request=SimpleNamespace(
            prompt_contract_version="prompt_request_v1",
            schema_hash="s" * 64,
            tokenizer_id="tokenizer",
            tokenizer_asset_hash="k" * 64,
            model_key="qwen3.7-plus-2026-05-26",
        ),
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
        repair_policy_hash="",
        fence=SimpleNamespace(
            as_record=lambda: {
                "predecessor_turn_ids": [],
                "transcript_hash": prompt.request.transcript_hash,
                "cutoff_turn_index": -1,
                "generation": 0,
            }
        ),
        receipts=(),
        queries=(),
    )
    fence_hash = _hash(prepared.fence.as_record())
    stage = SimpleNamespace(
        operation_id="operation-p1",
        turn_id=plan.turn_id,
        attempt_no=1,
        request_hash=prepared.request_hash,
        prompt_hash=prompt.request.request_hash,
        prompt_contract_version="prompt_request_v1",
        schema_hash=_hash("schema"),
        tokenizer_id="tokenizer",
        tokenizer_hash=_hash("tokenizer"),
        rule_set_hash=prompt.request.rule_set_hash,
        persona_spec_hash=prompt.request.persona_spec_hash,
        transcript_hash=prompt.request.transcript_hash,
        receipt_hash=prompt.request.receipt_hash,
        policy_hash=prepared.policy_hash,
        export_manifest_hash=prepared.manifest_hash,
        build_manifest_hash=prepared.build_manifest_hash,
        repair_policy_hash=None,
        generation_fence=fence_hash,
        model_key="qwen3.7-plus-2026-05-26",
    )
    recovery = build_llm_recovery_input(prepared, context, stage=stage)
    payload = json.loads(recovery.input_json)
    assert set(payload) == {"identity", "input"}
    serialized = recovery.input_json
    assert "agent_md" not in serialized
    assert "teacher_note" not in serialized
    assert hashlib.sha256(serialized.encode()).hexdigest() == recovery.input_hash
