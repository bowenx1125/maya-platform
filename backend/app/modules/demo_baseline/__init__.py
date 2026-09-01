"""Stable local Demo baselines and provider-neutral runtime disclosures."""

from .service import (
    BASELINE_AGENT_ID,
    BASELINE_AGENT_IDS,
    BASELINE_DOCUMENT_ID,
    BASELINE_PLATO,
    BASELINE_SNAPSHOT_ID,
    BASELINE_SOCRATES,
    BASELINE_SPECS,
    BASELINE_VERSION_ID,
    BaselineSpec,
    DemoBaselineConflict,
    ensure_demo_baseline,
    is_system_baseline_agent,
)

__all__ = [
    "BASELINE_SOCRATES",
    "BASELINE_AGENT_ID",
    "BASELINE_AGENT_IDS",
    "BASELINE_PLATO",
    "BASELINE_DOCUMENT_ID",
    "BASELINE_SNAPSHOT_ID",
    "BASELINE_SPECS",
    "BASELINE_VERSION_ID",
    "BaselineSpec",
    "DemoBaselineConflict",
    "ensure_demo_baseline",
    "is_system_baseline_agent",
]
