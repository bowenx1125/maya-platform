"""Check that the dual-Real policy hashes cross the Compose boundary safely."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from app.core.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DUAL_REAL_POLICY_VARIABLES = (
    "EMBEDDING_PROVIDER_POLICY_HASH",
    "LLM_PROVIDER_POLICY_HASH",
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


def test_compose_forwards_dual_real_policy_hashes_to_backend_without_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _backend_environment()
    assert environment["PROVIDER_POLICY_HASH"] == "${PROVIDER_POLICY_HASH:-}"
    expected_variables = {
        "LLM_PROVIDER": "dashscope",
        "EMBEDDING_PROVIDER": "dashscope",
        "TTS_PROVIDER": "mock",
        "VOICE_PROVIDER": "mock",
        "TRANSLATION_PROVIDER": "mock",
        "DASHSCOPE_API_KEY": "fixture-key",
        "DASHSCOPE_WORKSPACE_ID": "fixture-workspace",
        "DASHSCOPE_REGION": "cn-beijing",
        DUAL_REAL_POLICY_VARIABLES[0]: "a" * 64,
        DUAL_REAL_POLICY_VARIABLES[1]: "b" * 64,
    }
    for name, value in expected_variables.items():
        expression = environment[name]
        assert re.fullmatch(rf"\$\{{{name}:-[^}}]*\}}", expression)
        monkeypatch.setenv(name, value)

    settings = Settings(maya_env="test")
    settings.validate_provider_configuration()
    assert settings.embedding_provider == "dashscope"
    assert settings.llm_provider == "dashscope"
    assert settings.provider_policy_hash_for("embedding") == "a" * 64
    assert settings.provider_policy_hash_for("llm") == "b" * 64


def test_env_example_and_manual_demo_use_compose_variable_names() -> None:
    assert set(DUAL_REAL_POLICY_VARIABLES) <= _env_example_names()
    assert "PROVIDER_POLICY_HASH" in _env_example_names()

    readme = (PROJECT_ROOT / "manual-tests/real-core-demo/README.md").read_text(encoding="utf-8")
    for name in (
        "LLM_PROVIDER=dashscope",
        "EMBEDDING_PROVIDER=dashscope",
        "TTS_PROVIDER=mock",
        "VOICE_PROVIDER=mock",
        "TRANSLATION_PROVIDER=mock",
        "EMBEDDING_PROVIDER_POLICY_HASH=",
        "LLM_PROVIDER_POLICY_HASH=",
        "PROVIDER_POLICY_HASH=",
        "docker compose up -d --build",
    ):
        assert name in readme


@pytest.mark.parametrize("name", DUAL_REAL_POLICY_VARIABLES)
def test_compose_policy_hash_slots_are_explicit_empty_defaults(name: str) -> None:
    expression = _backend_environment()[name]
    assert re.fullmatch(rf"\$\{{{name}:-\}}", expression)
