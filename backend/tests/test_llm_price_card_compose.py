"""Verify reviewed LLM price-card settings cross the Compose boundary safely."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from app.core.config import Settings
from app.providers.factory import llm_provider
from app.providers.llm_adapter import DashScopeLLMAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRICE_CARD_VARIABLES = (
    "LLM_PRICE_CARD_VERSION",
    "LLM_INPUT_PRICE_CNY_PER_MILLION",
    "LLM_CACHED_INPUT_PRICE_CNY_PER_MILLION",
    "LLM_OUTPUT_PRICE_CNY_PER_MILLION",
    "LLM_PRICE_CARD_RETRIEVED_AT",
    "LLM_PRICE_CARD_SOURCE_CONTENT_SHA256",
)


def _backend_environment() -> dict[str, str]:
    document = yaml.safe_load((PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    environment = document["services"]["backend"]["environment"]
    assert isinstance(environment, dict)
    return environment


def _env_example_names() -> set[str]:
    return {
        line.split("=", 1)[0].strip()
        for line in (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }


def _set_dual_llm_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "LLM_PROVIDER": "dashscope",
        "EMBEDDING_PROVIDER": "mock",
        "TTS_PROVIDER": "mock",
        "VOICE_PROVIDER": "mock",
        "DASHSCOPE_API_KEY": "fixture-key",
        "DASHSCOPE_WORKSPACE_ID": "fixture-workspace",
        "DASHSCOPE_REGION": "cn-beijing",
        "LLM_PROVIDER_POLICY_HASH": "a" * 64,
        "LLM_PRICE_CARD_VERSION": "fixture-price-card-v1",
        "LLM_INPUT_PRICE_CNY_PER_MILLION": "1",
        "LLM_CACHED_INPUT_PRICE_CNY_PER_MILLION": "0.5",
        "LLM_OUTPUT_PRICE_CNY_PER_MILLION": "2",
        "LLM_PRICE_CARD_RETRIEVED_AT": "2026-08-31T00:00:00Z",
        "LLM_PRICE_CARD_SOURCE_CONTENT_SHA256": "c" * 64,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_compose_and_env_example_expose_all_price_card_slots() -> None:
    environment = _backend_environment()
    for name in PRICE_CARD_VARIABLES:
        assert re.fullmatch(rf"\$\{{{name}:-\}}", environment[name])
    assert "PROVIDER_POLICY_HASH" in environment
    assert set(PRICE_CARD_VARIABLES) <= _env_example_names()


def test_environment_values_reach_settings_and_factory_without_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_dual_llm_environment(monkeypatch)
    settings = Settings(maya_env="test")
    settings.validate_provider_configuration()
    selected = llm_provider(settings)
    assert isinstance(selected, DashScopeLLMAdapter)
    assert selected.price_card.reviewed
    assert selected.price_card.version == "fixture-price-card-v1"
    assert settings.llm_price_card_source_content_sha256 == "c" * 64


def test_mock_settings_allow_compose_empty_price_card_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in PRICE_CARD_VARIABLES:
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    settings = Settings(maya_env="test")
    settings.validate_provider_configuration()
    assert settings.llm_price_card_version is None


def test_debate_budget_cap_matches_the_frozen_fixtures() -> None:
    """The derived cap reproduces the two shapes that were hard-coded before.

    Those constants were the whole cap: a 3-Agent debate was rejected while a
    5-Agent one was allowed, and every round count but two was refused, even
    though the RuleSet accepts 2-5 Agents over 2-5 rounds.
    """

    from decimal import Decimal

    from app.providers.llm_price_card import (
        LLM_FULL_DEBATE_MAX_ATTEMPTS,
        LLM_FULL_DEBATE_MAX_COST,
        LLM_SMALL_DEBATE_MAX_ATTEMPTS,
        LLM_SMALL_DEBATE_MAX_COST,
        LLMPriceCardError,
        debate_budget_cap,
    )

    small = debate_budget_cap(2, round_count=2)
    assert small.max_requests == LLM_SMALL_DEBATE_MAX_ATTEMPTS
    assert Decimal(str(small.max_cost_cny)) == LLM_SMALL_DEBATE_MAX_COST
    full = debate_budget_cap(5, round_count=2)
    assert full.max_requests == LLM_FULL_DEBATE_MAX_ATTEMPTS
    assert Decimal(str(full.max_cost_cny)) == LLM_FULL_DEBATE_MAX_COST

    # Every shape the RuleSet allows now resolves, including the ones a teacher
    # can create in the product but the fixture-era cap refused.
    for agents in range(2, 6):
        for rounds in range(2, 6):
            cap = debate_budget_cap(agents, round_count=rounds)
            assert cap.max_requests == agents * rounds * 2

    for agents, rounds in ((1, 2), (6, 2), (2, 1), (2, 6)):
        with pytest.raises(LLMPriceCardError):
            debate_budget_cap(agents, round_count=rounds)
