from __future__ import annotations

from pathlib import Path

import pytest
from app.core.config import Settings
from app.modules.knowledge.providers.sql_query import REAL_CORE_DEMO_QUERY_MAX_REQUESTS
from app.providers.factory import llm_provider
from app.providers.llm_adapter import DashScopeLLMAdapter
from app.providers.llm_price_card import (
    REAL_CORE_DEMO_LLM_MAX_REQUESTS,
    real_core_demo_budget_cap,
)


def _settings(tmp_path: Path, **updates: object) -> Settings:
    values: dict[str, object] = {
        "maya_env": "test",
        "session_secret": "s" * 32,
        "database_url": f"sqlite:///{tmp_path / 'maya.sqlite3'}",
        "data_root": tmp_path,
        "tts_provider": "mock",
        "voice_provider": "mock",
        "translation_provider": None,
        "llm_provider": "mock",
        "embedding_provider": "mock",
    }
    values.update(updates)
    return Settings(**values)


def _dual(tmp_path: Path, **updates: object) -> Settings:
    values: dict[str, object] = {
        "llm_provider": "dashscope",
        "embedding_provider": "dashscope",
        "dashscope_api_key": "fixture-key",
        "dashscope_workspace_id": "fixture-workspace",
        "dashscope_region": "cn-beijing",
        "embedding_provider_policy_hash": "a" * 64,
        "llm_provider_policy_hash": "b" * 64,
    }
    values.update(updates)
    return _settings(tmp_path, **values)


def test_dual_real_pair_is_the_only_multi_real_demo_composition(tmp_path: Path) -> None:
    settings = _dual(tmp_path)
    settings.validate_provider_configuration()
    assert settings.provider_policy_hash_for("embedding") == "a" * 64
    assert settings.provider_policy_hash_for("llm") == "b" * 64

    selected = llm_provider(settings)
    assert isinstance(selected, DashScopeLLMAdapter)
    assert selected.config.policy_hash == "b" * 64


def test_legacy_hash_remains_valid_for_one_real_slice(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        embedding_provider="dashscope",
        dashscope_api_key="fixture-key",
        dashscope_workspace_id="fixture-workspace",
        dashscope_region="cn-beijing",
        provider_policy_hash="a" * 64,
    )
    settings.validate_provider_configuration()
    assert settings.provider_policy_hash_for("embedding") == "a" * 64

    llm = _settings(
        tmp_path,
        llm_provider="dashscope",
        dashscope_api_key="fixture-key",
        dashscope_workspace_id="fixture-workspace",
        dashscope_region="cn-beijing",
        provider_policy_hash="b" * 64,
    )
    llm.validate_provider_configuration()
    assert llm.provider_policy_hash_for("llm") == "b" * 64
    assert llm_provider(llm).config.policy_hash == "b" * 64  # type: ignore[union-attr]


def test_legacy_hash_is_rejected_when_two_real_slices_are_selected(tmp_path: Path) -> None:
    settings = _dual(
        tmp_path,
        provider_policy_hash="c" * 64,
        llm_provider_policy_hash=None,
    )
    with pytest.raises(RuntimeError, match="separate.*EMBEDDING_PROVIDER_POLICY_HASH"):
        settings.validate_provider_configuration()

    settings = _dual(tmp_path, llm_provider_policy_hash=None)
    with pytest.raises(RuntimeError, match="LLM_PROVIDER_POLICY_HASH"):
        settings.validate_provider_configuration()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("tts_provider", "dashscope"),
        ("voice_provider", "dashscope"),
        ("translation_provider", "deepl"),
    ),
)
def test_dual_pair_rejects_real_companions(tmp_path: Path, field: str, value: str) -> None:
    settings = _dual(tmp_path, **{field: value})
    with pytest.raises(RuntimeError, match="provider gate"):
        settings.validate_provider_configuration()


def test_dual_demo_caps_llm_and_query_requests(tmp_path: Path) -> None:
    cap = real_core_demo_budget_cap(2, round_count=2)
    assert cap.max_requests == REAL_CORE_DEMO_LLM_MAX_REQUESTS == 4
    assert REAL_CORE_DEMO_QUERY_MAX_REQUESTS == 2
    with pytest.raises(ValueError):
        real_core_demo_budget_cap(2, round_count=3)


def test_hash_validators_reject_non_sha256_slice_values(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _dual(tmp_path, llm_provider_policy_hash="not-a-hash")
