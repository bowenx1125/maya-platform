"""Stable local Demo baselines and provider-neutral runtime disclosures."""

from .service import (
    BASELINE_A,
    BASELINE_AGENT_ID,
    BASELINE_AGENT_IDS,
    BASELINE_B,
    BASELINE_DOCUMENT_ID,
    BASELINE_SNAPSHOT_ID,
    BASELINE_SPECS,
    BASELINE_VERSION_ID,
    BaselineSpec,
    DemoBaselineConflict,
    ensure_demo_baseline,
    is_system_baseline_agent,
)

__all__ = [
    "BASELINE_A",
    "BASELINE_AGENT_ID",
    "BASELINE_AGENT_IDS",
    "BASELINE_B",
    "BASELINE_DOCUMENT_ID",
    "BASELINE_SNAPSHOT_ID",
    "BASELINE_SPECS",
    "BASELINE_VERSION_ID",
    "BaselineSpec",
    "DemoBaselineConflict",
    "ensure_demo_baseline",
    "is_system_baseline_agent",
]
