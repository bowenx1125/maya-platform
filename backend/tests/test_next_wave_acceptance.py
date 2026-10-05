"""Focused checks for the predeclared next Wave RAG acceptance harness."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from _pytest.capture import CaptureFixture

from tests.fixtures.next_wave_rag import (
    FIXTURE_ROOT,
    FixtureValidationError,
    load_fixture_bundle,
    validate_report,
    validate_reports,
)


def _report_for(case: Any) -> dict[str, object]:
    policy = case.condition.answer_policy
    answer = " ".join(group[0] for group in policy.required_any_groups)
    evidence = [
        {
            "evidence_id": item.evidence_id,
            "corpus_path": item.corpus_path,
            "locator": item.locator,
            "observed_excerpt": item.marker,
        }
        for item in case.condition.expected_evidence
        if case.condition.condition in {"correct", "updated"}
    ]
    return {
        "case_id": case.case_id,
        "question_id": case.question.question_id,
        "condition": case.condition.condition,
        "repeat": case.repeat,
        "answer": answer,
        "retrieval_status": "no_match" if case.condition.condition == "disabled" else "matched",
        "grounding_mode": "rag_grounded"
        if case.condition.condition in {"correct", "updated"}
        else "general_reasoning",
        "retrieved_evidence_ids": (
            [str(item["evidence_id"]) for item in evidence]
            if case.condition.condition != "irrelevant"
            else list(case.condition.allowed_retrieved_evidence)
        ),
        "evidence": evidence,
    }


@pytest.fixture
def bundle() -> Any:
    return load_fixture_bundle()


def test_manifest_has_fixed_shape_and_rag_matrices(bundle: Any) -> None:
    assert len(bundle.questions) == 6
    assert {question.language for question in bundle.questions} == {"en", "zh"}
    assert sum(question.language == "en" for question in bundle.questions) == 3
    assert sum(question.language == "zh" for question in bundle.questions) == 3
    assert len(bundle.sessions) == 37
    assert sum(session.expected_turns for session in bundle.sessions) == 412
    assert len(bundle.rag_cases) == 72
    assert bundle.barrage_assignments == {"with_barrage": 19, "without_barrage": 18}
    assert {
        (session.agent_count, session.round_count, session.language)
        for session in bundle.sessions
        if session.session_kind == "shape"
    } == {
        (agents, rounds, language)
        for agents in range(2, 6)
        for rounds in range(2, 6)
        for language in ("en", "zh")
    }


def test_all_predeclared_reports_are_structural_only_and_need_semantic_review(bundle: Any) -> None:
    reports = [_report_for(case) for case in bundle.rag_cases]
    results = [validate_report(bundle, report) for report in reports]
    assert all(not result.passed for result in results)
    assert all(result.structural_valid for result in results)
    assert all(result.semantic_verdict == "pending" for result in results)
    assert all(result.human_review_required for result in results)

    summary = validate_reports(bundle, reports)
    assert summary.status == "semantic_review_required"
    assert summary.passed_reports == 0
    assert summary.structurally_valid_reports == 72
    assert summary.semantic_pending_reports == 72
    assert summary.failed_reports == 0
    safe = summary.as_dict()
    assert safe["real_calls_made"] == 0
    assert safe["human_review_required"] is True
    assert safe["semantic_review_required"] is True
    assert safe["semantic_verdict"] == "pending"
    assert safe["execution_scope"] == "validator_only"
    assert safe["execution_observed"] is False
    assert safe["rag_reports_passed"] == 0
    assert safe["rag_reports_structurally_valid"] == 72
    serialized = json.dumps(safe, ensure_ascii=False)
    assert "observed_excerpt" not in serialized
    assert '"answer":' not in serialized


def test_missing_evidence_fails_closed(bundle: Any) -> None:
    report = _report_for(bundle.case("q01-correct-r1"))
    report["evidence"] = report["evidence"][:-1]  # type: ignore[index]
    report["retrieved_evidence_ids"] = report["retrieved_evidence_ids"][:-1]  # type: ignore[index]
    result = validate_report(bundle, report)
    assert not result.passed
    assert "missing_evidence" in result.error_codes
    assert "retrieved_gold_evidence_missing" in result.error_codes


def test_evidence_id_alone_cannot_self_assert_source_support(bundle: Any) -> None:
    report = _report_for(bundle.case("q02-correct-r1"))
    report["evidence"][0].pop("observed_excerpt")  # type: ignore[index]
    result = validate_report(bundle, report)
    assert not result.passed
    assert "evidence_excerpt_missing" in result.error_codes


def test_observed_excerpt_must_match_immutable_corpus(bundle: Any) -> None:
    report = _report_for(bundle.case("q03-updated-r1"))
    report["evidence"][0]["observed_excerpt"] = "The provider said the prism changed."  # type: ignore[index]
    result = validate_report(bundle, report)
    assert not result.passed
    assert "evidence_excerpt_mismatch" in result.error_codes


def test_updated_condition_rejects_stale_answer(bundle: Any) -> None:
    report = _report_for(bundle.case("q01-updated-r1"))
    report["answer"] = "14 Nawal days two reed knots north terrace"
    result = validate_report(bundle, report)
    assert not result.passed
    assert "stale_fact" in result.error_codes
    assert result.answer_check == "manual_review_required"
    assert "answer_alias_missing" in result.review_warnings


def test_disabled_and_irrelevant_conditions_reject_facts_or_citations(bundle: Any) -> None:
    disabled = _report_for(bundle.case("q04-disabled-r1"))
    disabled["answer"] = "没有足够证据。"
    disabled["evidence"] = [
        {
            "evidence_id": "q04-correct-e01",
            "corpus_path": "corpus/q04/correct.md",
            "locator": "Evidence q04-correct-e01",
            "observed_excerpt": "月影谷用紫色石墨在雨簿上记录第一场雨。",
        }
    ]
    disabled["retrieved_evidence_ids"] = ["q04-correct-e01"]
    disabled_result = validate_report(bundle, disabled)
    assert not disabled_result.passed
    assert "unsupported_evidence" in disabled_result.error_codes
    assert "disabled_retrieval_not_empty" in disabled_result.error_codes

    irrelevant = _report_for(bundle.case("q05-irrelevant-r1"))
    irrelevant["answer"] = "资料不足，无法确定是否应使用七弦架。"
    irrelevant_result = validate_report(bundle, irrelevant)
    assert not irrelevant_result.passed
    assert "unsupported_fact" in irrelevant_result.error_codes

    no_match = _report_for(bundle.case("q05-irrelevant-r2"))
    no_match["answer"] = "The available source does not establish this rule."
    no_match["retrieval_status"] = "no_match"
    no_match["retrieved_evidence_ids"] = []
    no_match_result = validate_report(bundle, no_match)
    assert not no_match_result.passed
    assert no_match_result.structural_valid
    assert no_match_result.semantic_verdict == "pending"
    assert no_match_result.answer_check == "uncertainty_review_required"


def test_irrelevant_known_citation_is_pending_semantic_review(bundle: Any) -> None:
    case = bundle.case("q01-irrelevant-r1")
    assert case is not None
    evidence = case.condition.expected_evidence[0]
    report = {
        "case_id": case.case_id,
        "question_id": case.question.question_id,
        "condition": case.condition.condition,
        "repeat": case.repeat,
        "answer": "The cited record is about another place and does not establish this rule.",
        "retrieval_status": "matched",
        "grounding_mode": "mixed",
        "retrieved_evidence_ids": [evidence.evidence_id],
        "evidence": [
            {
                "evidence_id": evidence.evidence_id,
                "corpus_path": evidence.corpus_path,
                "locator": evidence.locator,
                "observed_excerpt": evidence.marker,
            }
        ],
    }
    result = validate_report(bundle, report)
    assert result.structural_valid
    assert not result.passed
    assert result.semantic_verdict == "pending"
    assert result.semantic_review_required
    assert "unsupported_evidence" not in result.error_codes


def test_irrelevant_forged_citation_id_fails_structural_validation(bundle: Any) -> None:
    case = bundle.case("q01-irrelevant-r1")
    assert case is not None
    report = {
        "case_id": case.case_id,
        "question_id": case.question.question_id,
        "condition": case.condition.condition,
        "repeat": case.repeat,
        "answer": "The available source does not establish this rule.",
        "retrieval_status": "matched",
        "grounding_mode": "mixed",
        "retrieved_evidence_ids": ["forged-source-id"],
        "evidence": [
            {
                "evidence_id": "forged-source-id",
                "corpus_path": case.condition.corpus_path,
                "locator": "forged-locator",
                "observed_excerpt": "forged excerpt",
            }
        ],
    }
    result = validate_report(bundle, report)
    assert not result.structural_valid
    assert not result.passed
    assert result.semantic_verdict == "not_evaluable"
    assert "evidence_id_not_predeclared" in result.error_codes
    assert "retrieved_evidence_not_predeclared" in result.error_codes


def test_complete_batch_requires_every_case(bundle: Any) -> None:
    summary = validate_reports(bundle, [_report_for(bundle.rag_cases[0])])
    assert summary.status == "reports_failed"
    assert summary.failed_reports == 0  # the supplied report itself is valid
    assert "missing_case" in summary.errors


def test_acceptance_keeps_real_runner_metadata_separate_from_fixture_validation(
    bundle: Any, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts))
    import next_wave_acceptance

    envelope = {
        "status": "semantic_review_required",
        "real_execution_status": "completed_pending_semantic_review",
        "execution_check_status": "passed",
        "structural_validation_status": "valid",
        "real_calls_made": 123,
        "reports": [_report_for(case) for case in bundle.rag_cases],
        "fixture_validation": {
            "status": "semantic_review_required",
            "real_execution_status": "pending_integration",
            "real_calls_made": 0,
        },
    }
    path = tmp_path / "rag-real-report.json"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    try:
        assert next_wave_acceptance.main(["--report", str(path)]) == 2
    finally:
        sys.path.remove(str(scripts))
    safe = json.loads(capsys.readouterr().out)
    assert safe["status"] == "semantic_review_required"
    assert safe["real_execution_status"] == "completed_pending_semantic_review"
    assert safe["real_calls_made"] == 123
    assert safe["execution_scope"] == "real_runner"
    assert safe["execution_observed"] is True
    assert safe["execution_status"] == "completed"
    assert safe["execution_check_status"] == "passed"
    assert safe["structural_validation_status"] == "valid"
    assert safe["pending_integrations"] == []
    assert safe["rag_reports_passed"] == 0
    assert safe["rag_reports_structurally_valid"] == 72
    assert safe["semantic_verdict"] == "pending"


def test_acceptance_keeps_structural_failure_below_execution_success(
    bundle: Any, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts))
    import next_wave_acceptance

    reports = [_report_for(case) for case in bundle.rag_cases]
    reports[0]["retrieved_evidence_ids"] = ["forged-source-id"]
    envelope = {
        "status": "structural_validation_failed",
        "real_execution_status": "completed_structural_validation_failed",
        "execution_check_status": "passed",
        "structural_validation_status": "failed",
        "real_calls_made": 7,
        "reports": reports,
        "fixture_validation": {
            "status": "reports_failed",
            "real_execution_status": "pending_integration",
            "real_calls_made": 0,
        },
    }
    path = tmp_path / "rag-structural-failure.json"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    try:
        assert next_wave_acceptance.main(["--report", str(path)]) == 1
    finally:
        sys.path.remove(str(scripts))
    safe = json.loads(capsys.readouterr().out)
    assert safe["status"] == "reports_failed"
    assert safe["execution_status"] == "completed"
    assert safe["execution_check_status"] == "passed"
    assert safe["structural_validation_status"] == "failed"
    assert safe["semantic_verdict"] == "not_evaluable"
    assert safe["real_calls_made"] == 7


def test_acceptance_ignores_progress_snapshot_when_final_report_exists(
    bundle: Any, tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts))
    import next_wave_acceptance

    report_dir = tmp_path / "run"
    report_dir.mkdir()
    (report_dir / "rag-real-progress.json").write_text(
        json.dumps({"reports": [_report_for(bundle.rag_cases[0])]}), encoding="utf-8"
    )
    (report_dir / "rag-real-report.json").write_text(
        json.dumps(
            {
                "status": "semantic_review_required",
                "real_execution_status": "completed_pending_semantic_review",
                "execution_check_status": "passed",
                "real_calls_made": 91,
                "reports": [_report_for(case) for case in bundle.rag_cases],
            }
        ),
        encoding="utf-8",
    )
    try:
        assert next_wave_acceptance.main(["--reports-dir", str(report_dir)]) == 2
    finally:
        sys.path.remove(str(scripts))
    safe = json.loads(capsys.readouterr().out)
    assert safe["rag_reports_seen"] == 72
    assert safe["real_calls_made"] == 91
    assert safe["status"] == "semantic_review_required"


def test_corpus_drift_invalidates_fixture(tmp_path: Path) -> None:
    copied = tmp_path / "next_wave_rag"
    shutil.copytree(FIXTURE_ROOT, copied)
    corpus = copied / "corpus/q01/correct.md"
    corpus.write_text(
        corpus.read_text(encoding="utf-8")
        + "\nThe Tz'ikin Basin opens water exchange at first light after 14 Nawal days.\n",
        encoding="utf-8",
    )
    with pytest.raises(FixtureValidationError) as error:
        load_fixture_bundle(copied)
    assert "manifest_hash_mismatch" not in error.value.codes
    assert "fixture_file_hash_mismatch" in error.value.codes


def test_fixture_hashes_are_stable_across_checkout_line_endings(tmp_path: Path) -> None:
    copied = tmp_path / "next_wave_rag"
    shutil.copytree(FIXTURE_ROOT, copied)
    for path in copied.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".md"}:
            content = path.read_bytes().replace(b"\r\n", b"\n")
            path.write_bytes(content.replace(b"\n", b"\r\n"))

    bundle = load_fixture_bundle(copied)
    assert len(bundle.sessions) == 37
    assert len(bundle.rag_cases) == 72


def test_real_execution_boundary_is_explicit_and_network_free() -> None:
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts))
    import next_wave_acceptance

    try:
        assert next_wave_acceptance.main(["--execute-real"]) == 2
    finally:
        sys.path.remove(str(scripts))
