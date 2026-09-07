"""Predeclared synthetic RAG acceptance fixtures and read-only validators."""

from .harness import (
    FIXTURE_ROOT,
    AuditSummary,
    FixtureBundle,
    FixtureValidationError,
    ReportValidationResult,
    load_fixture_bundle,
    validate_report,
    validate_reports,
)

__all__ = [
    "AuditSummary",
    "FIXTURE_ROOT",
    "FixtureBundle",
    "FixtureValidationError",
    "ReportValidationResult",
    "load_fixture_bundle",
    "validate_report",
    "validate_reports",
]
