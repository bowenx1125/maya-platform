"""The frozen OpenAPI contract documents the chat SSE event stream."""

from pathlib import Path

import yaml
from app.main import app

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "openapi-v0.1.yaml"
STREAM_PATH = "/conversations/{conversation_id}/messages:stream"


def _frozen_spec() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_stream_description_names_every_event() -> None:
    description = _frozen_spec()["paths"][STREAM_PATH]["post"]["responses"]["200"]["description"]
    for token in (
        "tts_ready",
        "audio_url",
        "audio_duration_ms",
        "tts_speech_empty",
        "text_done",
        "delta",
        "error",
    ):
        assert token in description


def test_chat_turn_requires_audio_fields() -> None:
    chat_turn = _frozen_spec()["components"]["schemas"]["ChatTurn"]
    assert "audio_url" in chat_turn["required"]
    assert "audio_duration_ms" in chat_turn["required"]


def test_fastapi_spec_has_identical_description() -> None:
    frozen = _frozen_spec()["paths"][STREAM_PATH]["post"]["responses"]["200"]["description"]
    generated = app.openapi()["paths"][STREAM_PATH]["post"]["responses"]["200"]["description"]
    assert generated == frozen


def test_project_doc_mentions_events_and_audio_fields() -> None:
    doc = (Path(__file__).resolve().parents[2] / "docs" / "PROJECT.md").read_text(encoding="utf-8")
    for token in ("tts_speech_empty", "audio_url", "audio_duration_ms"):
        assert token in doc
