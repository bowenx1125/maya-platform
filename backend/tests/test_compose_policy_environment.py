"""Check that the Real-Core policy hashes cross the Compose boundary safely."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from app.core.config import DEFAULT_LLM_MODEL, Settings
from app.providers.factory import llm_provider
from app.providers.llm_adapter import DashScopeLLMAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_PROVIDER_POLICY_VARIABLES = (
    "EMBEDDING_PROVIDER_POLICY_HASH",
    "LLM_PROVIDER_POLICY_HASH",
    "REPORT_PROVIDER_POLICY_HASH",
)


def _backend_environment() -> dict[str, str]:
    document = yaml.safe_load((PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    environment = document["services"]["backend"]["environment"]
    assert isinstance(environment, dict)
    return environment


def _env_example_names() -> set[str]:
    lines = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    return {
        line.split("=", 1)[0].strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }


def test_compose_forwards_real_core_policy_hashes_to_backend_without_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _backend_environment()
    assert environment["PROVIDER_POLICY_HASH"] == "${PROVIDER_POLICY_HASH:-}"
    expected_variables = {
        "LLM_PROVIDER": "dashscope",
        "MAYA_REPORT_PROVIDER": "dashscope",
        "EMBEDDING_PROVIDER": "dashscope",
        "TTS_PROVIDER": "mock",
        "VOICE_PROVIDER": "mock",
        "DASHSCOPE_API_KEY": "fixture-key",
        "DASHSCOPE_WORKSPACE_ID": "fixture-workspace",
        "DASHSCOPE_REGION": "cn-beijing",
        REAL_PROVIDER_POLICY_VARIABLES[0]: "a" * 64,
        REAL_PROVIDER_POLICY_VARIABLES[1]: "b" * 64,
        REAL_PROVIDER_POLICY_VARIABLES[2]: "d" * 64,
        "LLM_MODEL": "qwen-future-model",
    }
    for name, value in expected_variables.items():
        expression = environment[name]
        assert re.fullmatch(rf"\$\{{{name}:-[^}}]*\}}", expression)
        monkeypatch.setenv(name, value)

    settings = Settings(maya_env="test")
    settings.validate_provider_configuration()
    assert settings.embedding_provider == "dashscope"
    assert settings.llm_provider == "dashscope"
    assert settings.report_provider == "dashscope"
    assert settings.provider_policy_hash_for("embedding") == "a" * 64
    assert settings.provider_policy_hash_for("llm") == "b" * 64
    assert settings.provider_policy_hash_for("report") == "d" * 64
    assert settings.llm_model == "qwen-future-model"


def test_env_example_declares_every_compose_provider_variable() -> None:
    names = _env_example_names()
    assert set(REAL_PROVIDER_POLICY_VARIABLES) <= names
    assert "PROVIDER_POLICY_HASH" in names
    for selector in (
        "LLM_PROVIDER",
        "MAYA_REPORT_PROVIDER",
        "EMBEDDING_PROVIDER",
        "TTS_PROVIDER",
        "VOICE_PROVIDER",
    ):
        assert selector in names


@pytest.mark.parametrize("name", REAL_PROVIDER_POLICY_VARIABLES)
def test_compose_policy_hash_slots_are_explicit_empty_defaults(name: str) -> None:
    expression = _backend_environment()[name]
    assert re.fullmatch(rf"\$\{{{name}:-\}}", expression)


def test_compose_and_env_example_expose_llm_model() -> None:
    environment = _backend_environment()
    assert environment["LLM_MODEL"] == "${LLM_MODEL:-}"
    names = {
        line.split("=", 1)[0].strip()
        for line in (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    assert "LLM_MODEL" in names


def test_environment_model_reaches_settings_and_factory_without_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "LLM_PROVIDER": "dashscope",
        "EMBEDDING_PROVIDER": "mock",
        "TTS_PROVIDER": "mock",
        "VOICE_PROVIDER": "mock",
        "DASHSCOPE_API_KEY": "fixture-key",
        "DASHSCOPE_WORKSPACE_ID": "fixture-workspace",
        "DASHSCOPE_REGION": "cn-beijing",
        "LLM_PROVIDER_POLICY_HASH": "a" * 64,
        "LLM_MODEL": "qwen-future-model",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    settings = Settings(maya_env="test")
    settings.validate_provider_configuration()
    selected = llm_provider(settings)
    assert isinstance(selected, DashScopeLLMAdapter)
    assert settings.llm_model == "qwen-future-model"
    assert selected.config.model_key == "qwen-future-model"


def test_blank_llm_model_uses_the_dated_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    settings = Settings(maya_env="test")
    assert settings.llm_model == DEFAULT_LLM_MODEL
