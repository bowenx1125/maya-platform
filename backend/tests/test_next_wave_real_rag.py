"""Offline contract checks for the explicit next Wave real-RAG runner.

These tests never construct Maya's provider selector and never contact a
supplier.  The two transport fakes are used only for one disposable end to
end wiring check; the CLI and disabled-retrieval checks remain entirely
offline.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch
from app.core.db import Database
from app.modules.knowledge.providers.adapters import (
    DashScopeEmbeddingAdapter,
    DashScopeEmbeddingConfig,
    EmbeddingTransportResponse,
)
from app.providers.control import ProviderPolicySnapshotV1
from app.providers.control_repository import ProviderRepository
from app.providers.llm_adapter import DashScopeLLMAdapter, DashScopeLLMConfig
from app.providers.llm_tokenizer import ConservativeLLMTokenizer
from app.providers.llm_transport import LLMTransportResponse

from tests.fixtures.next_wave_rag import load_fixture_bundle, validate_report
from tests.postgres_db import named_url

_EMBEDDING_ENDPOINT = DashScopeEmbeddingConfig(workspace_id="fixture").resolved_endpoint
_LLM_ENDPOINT = DashScopeLLMConfig(workspace_id="fixture").resolved_endpoint


@pytest.fixture(scope="module")
def runner() -> Any:
    """Import the standalone script without adding a package convention."""

    path = Path(__file__).resolve().parents[2] / "scripts/next_wave_real_rag.py"
    spec = importlib.util.spec_from_file_location("next_wave_real_rag_test_module", path)
    if spec is None or spec.loader is None:
        raise AssertionError("real RAG runner could not be imported")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _policy(policy_id: str, endpoint: str) -> ProviderPolicySnapshotV1:
    digest = "a" * 64
    return ProviderPolicySnapshotV1(
        policy_id=policy_id,
        supplier="Alibaba Cloud Model Studio",
        region="cn-beijing",
        account_product="payg_api",
        endpoint=endpoint,
        privacy_notice_url="https://example.com/privacy",
        privacy_notice_retrieved_at="2026-09-07T00:00:00+00:00",
        privacy_notice_sha256=digest,
        service_terms_url="https://example.com/terms",
        service_terms_retrieved_at="2026-09-07T00:00:00+00:00",
        service_terms_sha256=digest,
        faq_url="https://example.com/faq",
        faq_retrieved_at="2026-09-07T00:00:00+00:00",
        faq_sha256=digest,
        no_training_basis="reviewed fixture basis",
        prompt_response_logging_disabled=True,
        inference_log_backflow_disabled=True,
        optional_content_logging_disabled=True,
        service_improvement_disabled=True,
        storage_disclosed=True,
        retention_setting="provider-defined",
    )


class _FakeEmbeddingTransport:
    def __init__(self) -> None:
        self.calls: list[Mapping[str, object]] = []

    def post(
        self,
        _url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> EmbeddingTransportResponse:
        del headers, timeout
        self.calls.append(json)
        input_value = json.get("input")
        texts = input_value.get("texts") if isinstance(input_value, Mapping) else None
        if not isinstance(texts, list):
            raise AssertionError("fake received a non-DashScope embedding envelope")
        return EmbeddingTransportResponse(
            200,
            {
                "output": {
                    "embeddings": [
                        {"text_index": index, "embedding": [1.0] + [0.0] * 1023}
                        for index, _text in enumerate(texts)
                    ]
                }
            },
        )


class _FakeLLMTransport:
    def __init__(self) -> None:
        self.calls: list[Mapping[str, object]] = []

    def post(
        self,
        _url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: object,
    ) -> LLMTransportResponse:
        del headers, timeout
        self.calls.append(json)
        messages = json.get("messages")
        if not isinstance(messages, list) or len(messages) != 2:
            raise AssertionError("fake received an unexpected LLM message envelope")
        user_message = messages[1]
        if not isinstance(user_message, Mapping):
            raise AssertionError("fake received an invalid LLM user message")
        user_content = user_message.get("content")
        if not isinstance(user_content, str):
            raise AssertionError("fake received non-text LLM content")
        snapshot = json_module.loads(user_content)
        sources = snapshot.get("sources") if isinstance(snapshot, Mapping) else None
        source_ids = [str(item["id"]) for item in sources[:1]] if isinstance(sources, list) else []
        output = json_module.dumps(
            {
                "segments": [
                    {
                        "text": "The returned paragraph remains bounded by the available source.",
                        "source_ids": source_ids,
                        "reply_to": None,
                    }
                ]
            },
            ensure_ascii=False,
        )
        return LLMTransportResponse(
            200,
            {
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": output},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20,
                },
            },
        )


json_module = json


def _llm_adapter(
    policy: ProviderPolicySnapshotV1, transport: _FakeLLMTransport
) -> DashScopeLLMAdapter:
    return DashScopeLLMAdapter(
        DashScopeLLMConfig(
            api_key="fixture-key",
            workspace_id="fixture",
            endpoint=policy.endpoint,
            policy_hash=policy.policy_hash,
        ),
        transport,
        tokenizer=ConservativeLLMTokenizer(),
    )


def test_dry_run_reads_the_pinned_72_case_set_without_provider_or_db(
    runner: Any, capsys: CaptureFixture[str]
) -> None:
    exit_code = runner.main(["--case-id", "q01-disabled-r1", "--limit", "1", "--list-cases"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert (
        payload["fixture_hash"]
        == "dd65888c670198d974b5dfda58ae3e0bee7bf5a2a6ed9d23b549333ff0d5a297"
    )
    assert payload["real_calls_made"] == 0
    assert payload["database_created"] is False
    assert payload["provider_constructed"] is False
    assert payload["selection"]["case_ids"] == ["q01-disabled-r1"]
    assert payload["cases"][0]["corpus_available"] is False


def test_selection_rejects_duplicates_unknown_ids_and_empty_prefix(runner: Any) -> None:
    bundle = load_fixture_bundle()
    selected = runner.select_cases(bundle, case_ids=("q02-correct-r2",), limit=1)
    assert selected.safe_dict()["case_ids"] == ["q02-correct-r2"]
    for case_ids, code in (
        (("q01-disabled-r1", "q01-disabled-r1"), "selection_duplicate_case"),
        (("unknown-case",), "selection_case_unknown"),
    ):
        with pytest.raises(runner.RealRAGRunError) as error:
            runner.select_cases(bundle, case_ids=case_ids)
        assert error.value.code == code
    with pytest.raises(runner.RealRAGRunError) as error:
        runner.select_cases(bundle, limit=0)
    assert error.value.code == "selection_limit_invalid"


def test_execute_real_requires_an_explicit_output_and_reviewed_policy_files(
    runner: Any, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    exit_code = runner.main(["--execute-real", "--output-dir", str(tmp_path)])
    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["errors"] == ["real_output_and_policy_files_required"]
    assert payload["real_calls_made"] == 0
    assert list(tmp_path.iterdir()) == []


def test_disabled_case_never_enters_source_or_query_retrieval(
    runner: Any, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    bundle = load_fixture_bundle()
    case = bundle.case("q01-disabled-r1")
    assert case is not None
    embedding_policy = _policy(
        "embedding",
        _EMBEDDING_ENDPOINT,
    )
    llm_policy = _policy(
        "llm",
        _LLM_ENDPOINT,
    )
    llm_transport = _FakeLLMTransport()
    llm_adapter = _llm_adapter(llm_policy, llm_transport)
    reviewed = runner.RealRAGSettings(SimpleNamespace(), embedding_policy, llm_policy)

    def should_not_retrieve(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("disabled case attempted query retrieval")

    monkeypatch.setattr(runner, "_query_service", should_not_retrieve)
    monkeypatch.setattr(runner, "_seed_owner", should_not_retrieve)
    monkeypatch.setattr(runner, "_publish_owner", should_not_retrieve)
    report = runner._execute_case(
        None,
        tmp_path,
        reviewed,
        case,
        fixture_root=bundle.root,
        embedding_adapter=object(),
        llm_adapter=llm_adapter,
    )
    assert report["retrieval_status"] == "no_match"
    assert report["retrieval_receipt_ids"] == []
    assert report["retrieved_evidence_ids"] == []
    assert report["provider_ledger"].keys() == {"llm"}
    assert report["timing_ms"]["embedding"] == 0
    assert report["timing_ms"]["query"] == 0
    assert len(llm_transport.calls) == 1
    message = cast(list[Mapping[str, object]], llm_transport.calls[0]["messages"])[1]
    assert json.loads(cast(str, message["content"]))["sources"] == []


def test_disposable_enabled_case_reports_real_seams_and_ledger_counts(
    runner: Any, tmp_path: Path
) -> None:
    bundle = load_fixture_bundle()
    case = bundle.case("q01-correct-r1")
    assert case is not None
    embedding_policy = _policy(
        "embedding",
        _EMBEDDING_ENDPOINT,
    )
    llm_policy = _policy(
        "llm",
        _LLM_ENDPOINT,
    )
    embedding_transport = _FakeEmbeddingTransport()
    embedding_adapter = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(api_key="fixture-key", workspace_id="fixture"),
        embedding_transport,
    )
    llm_transport = _FakeLLMTransport()
    llm_adapter = _llm_adapter(llm_policy, llm_transport)
    reviewed = runner.RealRAGSettings(SimpleNamespace(), embedding_policy, llm_policy)
    database = Database(named_url(f"{tmp_path / 'maya.sqlite3'}"), tmp_path)
    database.initialize_schema()
    repository = ProviderRepository(database)
    repository.save_policy_snapshot(embedding_policy, snapshot_id="rag-policy-1")
    repository.save_policy_snapshot(llm_policy, snapshot_id="rag-policy-2")
    try:
        report = runner._execute_case(
            database,
            tmp_path,
            reviewed,
            case,
            fixture_root=bundle.root,
            embedding_adapter=embedding_adapter,
            llm_adapter=llm_adapter,
        )
    finally:
        database.dispose()
    assert report["safe_error_code"] is None
    assert report["retrieval_status"] == "matched"
    assert report["retrieval_receipt_ids"]
    assert report["evidence"]
    assert report["cited_paragraphs"][0]["source_ids"]
    ledger = cast(Mapping[str, Mapping[str, Any]], report["provider_ledger"])
    assert ledger["embedding"]["charged_request_count"] >= 1
    assert ledger["query"]["charged_request_count"] >= 1
    assert ledger["llm"]["charged_request_count"] >= 1
    timing = cast(Mapping[str, int], report["timing_ms"])
    assert set(timing) >= {"embedding", "query", "llm"}
    validation = validate_report(bundle, report)
    assert validation.structural_valid
    assert not validation.passed
    assert validation.semantic_verdict == "pending"
    assert validation.human_review_required
    serialized = json.dumps(report, ensure_ascii=False)
    assert "fixture-key" not in serialized


def test_failed_real_selection_stops_and_preserves_runtime(
    runner: Any, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    bundle = load_fixture_bundle()
    embedding_policy = _policy("embedding", _EMBEDDING_ENDPOINT)
    llm_policy = _policy("llm", _LLM_ENDPOINT)
    adapter = _llm_adapter(llm_policy, _FakeLLMTransport())

    def settings(**kwargs: Any) -> Any:
        root = kwargs["runtime_root"]
        return runner.RealRAGSettings(
            SimpleNamespace(database_url=named_url(f"{root / 'maya.sqlite3'}")),
            embedding_policy,
            llm_policy,
        )

    calls: list[str] = []

    def fail_case(*args: Any, **_kwargs: Any) -> Any:
        calls.append(args[3].case_id)
        raise runner.RealRAGRunError("acceptance_unknown")

    monkeypatch.setattr(runner, "_real_settings", settings)
    monkeypatch.setattr(runner, "embedding_provider", lambda _settings: object())
    monkeypatch.setattr(runner, "llm_provider", lambda _settings: adapter)
    monkeypatch.setattr(runner, "_execute_case", fail_case)
    result = runner.execute_real(
        bundle,
        runner.select_cases(bundle, limit=2),
        output_dir=tmp_path,
        embedding_policy=embedding_policy,
        llm_policy=llm_policy,
    )
    assert len(calls) == 1
    assert result["status"] == "real_failed"
    assert result["stopped_early"] is True
    assert len([path for path in tmp_path.glob(".next-wave-rag-*") if path.is_dir()]) == 1
    assert (tmp_path / "rag-real-progress.json").is_file()


def test_existing_persisted_policy_requires_matching_hash(runner: Any, tmp_path: Path) -> None:
    from dataclasses import asdict

    policy = _policy("embedding", _EMBEDDING_ENDPOINT)
    document = {**asdict(policy), "policy_hash": policy.policy_hash}
    path = tmp_path / "reviewed.json"
    path.write_text(json.dumps(document))
    assert runner._load_policy(path, kind="embedding") == policy
    document["policy_hash"] = "0" * 64
    path.write_text(json.dumps(document))
    with pytest.raises(runner.RealRAGRunError) as error:
        runner._load_policy(path, kind="embedding")
    assert error.value.code == "reviewed_policy_invalid"
