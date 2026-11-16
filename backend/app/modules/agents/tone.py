"""Extract a TTS Tone line from AGENT.md without inventing persona."""

from __future__ import annotations

import re

# Matches the Persona Speaking-style bullet: "- Tone: …"
_TONE_LINE = re.compile(r"(?im)^\s*[-*]\s*Tone\s*:\s*(.+?)\s*$")
# Debate card voice lines stay short; Preview instruction may be longer.
_CARD_LINE_CHARS = 120
_INSTRUCTION_CHARS = 500


def extract_tone(
    agent_md: str | None,
    *,
    fallback: str | None = None,
    max_chars: int = _INSTRUCTION_CHARS,
) -> str | None:
    """Return the AGENT.md Tone bullet, else a non-blank fallback, else None."""

    if isinstance(agent_md, str):
        match = _TONE_LINE.search(agent_md)
        if match is not None:
            text = " ".join(match.group(1).split())
            if text:
                return text[:max_chars]
    if isinstance(fallback, str):
        text = fallback.strip()
        if text:
            return text[:max_chars]
    return None


def extract_card_tone(agent_md: str | None, *, fallback: str | None = None) -> str | None:
    """Tone for a debate card / Check-card Preview (card line length)."""

    return extract_tone(agent_md, fallback=fallback, max_chars=_CARD_LINE_CHARS)
