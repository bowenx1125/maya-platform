"""Provider-neutral Real/Mock composition disclosure for the Demo browser."""

from __future__ import annotations

from app.core.config import Settings

from .schemas import DemoComponent, DemoComposition


def demo_composition(settings: Settings) -> DemoComposition:
    """Project server-selected modes without exposing provider identities."""

    return DemoComposition(
        components=(
            DemoComponent(
                key="embedding",
                label="Embedding",
                mode="real" if settings.embedding_provider == "dashscope" else "mock",
            ),
            DemoComponent(
                key="llm",
                label="Debate LLM",
                mode="real" if settings.llm_provider == "dashscope" else "mock",
            ),
            DemoComponent(key="tts", label="TTS", mode="mock"),
            DemoComponent(key="voice", label="Voice", mode="mock"),
            DemoComponent(key="translation", label="Translation", mode="mock"),
            DemoComponent(
                key="report",
                label="Maya Report",
                mode="real" if settings.report_provider == "dashscope" else "mock",
            ),
        )
    )
