"""Stable local Demo baseline and provider-neutral runtime disclosures."""

from .service import (
    BASELINE_AGENT_ID,
    BASELINE_DOCUMENT_ID,
    BASELINE_SNAPSHOT_ID,
    BASELINE_VERSION_ID,
    DemoBaselineConflict,
    ensure_demo_baseline,
    is_system_baseline_agent,
)

__all__ = [
    "BASELINE_AGENT_ID",
    "BASELINE_DOCUMENT_ID",
    "BASELINE_SNAPSHOT_ID",
    "BASELINE_VERSION_ID",
    "DemoBaselineConflict",
    "ensure_demo_baseline",
    "is_system_baseline_agent",
]
