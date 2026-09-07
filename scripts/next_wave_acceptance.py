"""Validate or enumerate the predeclared next Wave RAG acceptance set.

The default command is an offline dry run.  It reads only the committed
synthetic manifest/corpus and makes zero Provider, runtime or network calls.
Real execution intentionally has no fallback in this foundation: passing
``--execute-real`` exits with a machine-readable pending status until the main
window supplies an adapter that performs real import, embedding, retrieval,
generation and report capture.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tests.fixtures.next_wave_rag.harness import (  # noqa: E402
    AUDIT_SCHEMA_VERSION,
    FixtureBundle,
    FixtureValidationError,
    load_fixture_bundle,
    validate_reports,
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _invalid_summary(error: FixtureValidationError) -> dict[str, object]:
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "fixtures_invalid",
        "real_execution_status": "pending_integration",
        "execution_scope": "validator_only",
        "execution_observed": False,
        "semantic_verdict": "not_evaluable",
        "real_calls_made": 0,
        "errors": list(dict.fromkeys(error.codes or ("fixture_validation_failed",))),
        "reports": [],
    }


def _case_list(bundle: FixtureBundle) -> list[dict[str, object]]:
    """Project all 72 cases without answer text, source text or Provider data."""

    return [
        {
            "case_id": case.case_id,
            "question_id": case.question.question_id,
            "language": case.question.language,
            "condition": case.condition.condition,
            "repeat": case.repeat,
            "corpus_available": case.condition.corpus_path is not None,
            "expected_evidence_count": len(case.condition.expected_evidence),
        }
        for case in bundle.rag_cases
    ]


def _safe_execution_metadata(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    metadata: dict[str, object] = {}
    for key in (
        "status",
        "real_execution_status",
        "execution_check_status",
        "structural_validation_status",
    ):
        item = value.get(key)
        if isinstance(item, str) and item:
            metadata[key] = item
    calls = value.get("real_calls_made")
    if isinstance(calls, int) and not isinstance(calls, bool) and calls >= 0:
        metadata["real_calls_made"] = calls
    for key in ("case_count", "selected_case_count", "case_succeeded", "case_failed"):
        item = value.get(key)
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
            metadata[key] = item
    stopped = value.get("stopped_early")
    if isinstance(stopped, bool):
        metadata["stopped_early"] = stopped
    return metadata


def _read_report_file(path: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("report_json_invalid") from exc
    metadata = _safe_execution_metadata(value)
    if isinstance(value, dict) and isinstance(value.get("reports"), list):
        values = value["reports"]
    else:
        values = [value]
    if not all(isinstance(item, dict) for item in values):
        raise ValueError("report_object_required")
    return [cast(dict[str, object], item) for item in values], metadata


def _report_inputs(
    report_paths: list[Path], report_dir: Path | None
) -> tuple[list[dict[str, object]], dict[str, object]]:
    paths = list(report_paths)
    if report_dir is not None:
        try:
            directory_paths = sorted(
                path for path in report_dir.iterdir() if path.suffix == ".json"
            )
            # A real run keeps a restart-safe progress snapshot beside its
            # final report.  If the final envelope exists, validate it once;
            # treating the progress snapshot as another batch would create
            # false duplicate-case failures.  A progress-only directory is
            # still accepted as an incomplete read-only report set.
            if any(path.name == "rag-real-report.json" for path in directory_paths):
                directory_paths = [
                    path for path in directory_paths if path.name != "rag-real-progress.json"
                ]
            paths.extend(directory_paths)
        except OSError as exc:
            raise ValueError("report_directory_unreadable") from exc
    reports: list[dict[str, object]] = []
    execution: dict[str, object] = {}
    for path in paths:
        values, metadata = _read_report_file(path)
        reports.extend(values)
        execution.update(metadata)
    return reports, execution


def _charged_requests(reports: list[dict[str, object]]) -> int:
    total = 0
    for report in reports:
        ledger = report.get("provider_ledger")
        if not isinstance(ledger, Mapping):
            continue
        for name in ("embedding", "query", "llm"):
            row = ledger.get(name)
            if not isinstance(row, Mapping):
                continue
            value = row.get("charged_request_count")
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                total += value
    return total


def _apply_execution_metadata(
    summary: dict[str, object],
    reports: list[dict[str, object]],
    metadata: Mapping[str, object],
) -> dict[str, object]:
    """Keep real-run execution facts separate from fixture validation facts."""

    observed = metadata.get("real_execution_status")
    real_run = isinstance(observed, str) and observed not in {
        "not_started",
        "pending_integration",
        "not_observed",
    }
    summary["execution_scope"] = "real_runner" if real_run else "validator_only"
    summary["execution_observed"] = real_run
    summary["real_execution_status"] = (
        observed if isinstance(observed, str) and observed else "not_observed"
    )
    calls = metadata.get("real_calls_made")
    summary["real_calls_made"] = (
        calls
        if isinstance(calls, int) and not isinstance(calls, bool) and calls >= 0
        else _charged_requests(reports)
    )
    if real_run:
        # The case validator did not own this run's Provider lifecycle. Avoid
        # exposing its fixture-only pending integration defaults as run state.
        summary["pending_integrations"] = []
        execution_check = metadata.get("execution_check_status")
        if isinstance(execution_check, str) and execution_check:
            summary["execution_check_status"] = execution_check
            summary["execution_status"] = (
                "completed" if execution_check == "passed" else execution_check
            )
        else:
            # Older real envelopes exposed only the overall semantic status;
            # infer the execution outcome from the separate execution fence.
            summary["execution_status"] = "failed" if "failed" in str(observed) else "completed"
            summary["execution_check_status"] = summary["execution_status"]
        structural = metadata.get("structural_validation_status")
        summary["structural_validation_status"] = (
            structural
            if isinstance(structural, str) and structural
            else (
                "valid"
                if summary.get("status") == "semantic_review_required"
                else "failed"
                if summary.get("status") == "reports_failed"
                else "not_run"
            )
        )
    else:
        summary["execution_status"] = "validator_only"
        summary["execution_check_status"] = "not_run"
        summary["structural_validation_status"] = (
            "valid" if summary.get("status") == "semantic_review_required" else "not_run"
        )
    return summary


def _blocked_real_summary() -> dict[str, object]:
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "real_execution_blocked",
        "code": "real_acceptance_integration_pending",
        "real_execution_status": "pending_integration",
        "execution_scope": "validator_only",
        "execution_observed": False,
        "execution_check_status": "not_run",
        "structural_validation_status": "not_run",
        "semantic_verdict": "not_evaluable",
        "semantic_review_required": False,
        "real_calls_made": 0,
        "pending_integrations": [
            "knowledge_import_publish",
            "snapshot_embedding",
            "query_embedding_retrieval",
            "turn_generation",
            "report_export",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=ROOT / "backend/tests/fixtures/next_wave_rag",
        help="fixture directory (defaults to the committed synthetic set)",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="include all predeclared RAG case IDs in the dry-run JSON",
    )
    parser.add_argument(
        "--report",
        type=Path,
        action="append",
        default=[],
        help="read one adapted report JSON (repeatable; validation is read-only)",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        help="read every .json report in a directory (validation is read-only)",
    )
    parser.add_argument(
        "--execute-real",
        action="store_true",
        help="reserved explicit boundary; refuses until a real adapter is integrated",
    )
    args = parser.parse_args(argv)

    if args.execute_real:
        print(_json(_blocked_real_summary()))
        return 2

    try:
        bundle = load_fixture_bundle(args.fixture_root)
    except FixtureValidationError as exc:
        print(_json(_invalid_summary(exc)))
        return 1

    try:
        reports, execution_metadata = _report_inputs(args.report, args.reports_dir)
    except ValueError as exc:
        print(
            _json(
                {
                    **bundle.plan_summary().as_dict(),
                    "status": "reports_failed",
                    "errors": [str(exc)],
                    "reports": [],
                }
            )
        )
        return 1

    if reports or args.report or args.reports_dir is not None:
        summary = _apply_execution_metadata(
            validate_reports(bundle, reports).as_dict(),
            reports,
            execution_metadata,
        )
    else:
        summary = bundle.plan_summary().as_dict()
    if args.list_cases:
        summary["case_list"] = _case_list(bundle)
    print(_json(summary))
    if summary["status"] == "fixtures_valid":
        return 0
    if summary["status"] == "semantic_review_required":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
