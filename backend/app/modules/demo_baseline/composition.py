"""Provider-neutral Real/Mock composition disclosure for the Demo browser."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.models import ProviderPolicySnapshot
from app.providers.control import DEMO_UNREVIEWED_POLICY_PREFIX

from .schemas import DemoComponent, DemoComponentMode, DemoComposition


def _has_unreviewed_policy(db: Session | None) -> bool:
    """Whether any installed provider policy was derived rather than reviewed."""

    if db is None:
        return False
    return (
        db.scalar(
            select(ProviderPolicySnapshot.id).where(
                ProviderPolicySnapshot.policy_id.startswith(DEMO_UNREVIEWED_POLICY_PREFIX)
            )
        )
        is not None
    )


def demo_composition(settings: Settings, db: Session | None = None) -> DemoComposition:
    """Project server-selected modes without exposing provider identities."""

    unreviewed = _has_unreviewed_policy(db)

    def real(selector: str) -> tuple[DemoComponentMode, bool]:
        is_real = selector == "dashscope"
        mode: DemoComponentMode = "real" if is_real else "mock"
        return mode, is_real and unreviewed

    embedding_mode, embedding_unreviewed = real(settings.embedding_provider)
    llm_mode, llm_unreviewed = real(settings.llm_provider)
    report_mode, report_unreviewed = real(settings.report_provider)
    return DemoComposition(
        components=(
            DemoComponent(
                key="embedding",
                label="Embedding",
                mode=embedding_mode,
                policy_unreviewed=embedding_unreviewed,
            ),
            DemoComponent(
                key="llm",
                label="Debate LLM",
                mode=llm_mode,
                policy_unreviewed=llm_unreviewed,
            ),
            DemoComponent(key="tts", label="TTS", mode="mock"),
            DemoComponent(key="voice", label="Voice", mode="mock"),
            DemoComponent(
                key="report",
                label="Maya Report",
                mode=report_mode,
                policy_unreviewed=report_unreviewed,
            ),
        )
    )
