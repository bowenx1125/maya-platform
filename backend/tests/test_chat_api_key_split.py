"""Chatform uses DASHSCOPE_CHAT_API_KEY; everything else keeps DASHSCOPE_API_KEY."""

from __future__ import annotations

from typing import Any

import pytest
from app.core.config import Settings
from app.providers import factory


def _settings(**values: object) -> Settings:
    base: dict[str, object] = {
        "dashscope_api_key": "main-key",
        "dashscope_workspace_id": "workspace123",
        "dashscope_region": "cn-beijing",
    }
    base.update(values)
    return Settings(**base)  # type: ignore[arg-type]


def test_chat_settings_swap_in_the_chat_key() -> None:
    settings = _settings(dashscope_chat_api_key="chat-key")
    assert settings.chat_settings().dashscope_api_key == "chat-key"
    assert settings.dashscope_api_key == "main-key"  # the original is untouched


@pytest.mark.parametrize("unset", [None, "", "   "])
def test_chat_falls_back_to_the_shared_key(unset: str | None) -> None:
    settings = _settings(dashscope_chat_api_key=unset)
    assert settings.chat_settings().dashscope_api_key == "main-key"


def test_voices_and_debates_keep_the_shared_key() -> None:
    settings = _settings(dashscope_chat_api_key="chat-key")
    assert factory._dashscope_config(settings).api_key == "main-key"


class _Seen(Exception):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings


def _capture(settings: Settings) -> Any:
    raise _Seen(settings)


def test_agent_chat_model_call_uses_the_chat_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.workspace import chat_provider

    monkeypatch.setattr(chat_provider, "llm_provider", _capture)
    with pytest.raises(_Seen) as seen:
        chat_provider.real_reply(
            None,  # type: ignore[arg-type]
            _settings(dashscope_chat_api_key="chat-key"),
            scope_id="c",
            request_id="r",
            course_id="course",
            messages=[],
            persona_hash="p",
        )
    assert seen.value.settings.dashscope_api_key == "chat-key"


def test_team_chat_model_call_uses_the_chat_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.workspace import chat_team_provider

    monkeypatch.setattr(chat_team_provider, "llm_provider", _capture)
    with pytest.raises(_Seen) as seen:
        chat_team_provider.dispatch_team_model(
            None,  # type: ignore[arg-type]
            _settings(dashscope_chat_api_key="chat-key"),
            None,  # type: ignore[arg-type]
            [],
            None,
            None,
            ordinal=1,
            selected_binding_ids=set(),
            actor_context=None,
        )
    assert seen.value.settings.dashscope_api_key == "chat-key"
