from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.config import Settings
from app.core.errors import PlatformError
from app.modules.debates.playback.generation_adapter import _assert_llm_provider_endpoint
from app.modules.knowledge.providers.sql_query import REAL_CORE_DEMO_QUERY_MAX_REQUESTS
from app.providers.factory import llm_provider
from app.providers.llm import MockLLMProvider
from app.providers.llm_adapter import DashScopeLLMAdapter, DashScopeLLMConfig
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
        "llm_price_card_version": "fixture-price-card-v1",
        "llm_input_price_cny_per_million": "1",
        "llm_cached_input_price_cny_per_million": "0.5",
        "llm_output_price_cny_per_million": "2",
        "llm_price_card_retrieved_at": "2026-08-31T00:00:00Z",
        "llm_price_card_source_content_sha256": "c" * 64,
    }
    values.update(updates)
    return Settings(**values)


def _dual(tmp_path: Path, **updates: object) -> Settings:
    fixture_values = {
        "dashscope_" + "api_key": "fixture" + "-key",
        "dashscope_workspace_id": "fixture-workspace",
    }
    values: dict[str, object] = {
        "llm_provider": "dashscope",
        "embedding_provider": "dashscope",
        "dashscope_region": "cn-beijing",
        "embedding_provider_policy_hash": "a" * 64,
        "llm_provider_policy_hash": "b" * 64,
        "llm_price_card_version": "fixture-price-card-v1",
        "llm_input_price_cny_per_million": "1",
        "llm_cached_input_price_cny_per_million": "0.5",
        "llm_output_price_cny_per_million": "2",
        "llm_price_card_retrieved_at": "2026-08-31T00:00:00Z",
        "llm_price_card_source_content_sha256": "c" * 64,
    }
    values.update(fixture_values)
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
        **{"dashscope_" + "api_key": "fixture" + "-key"},
        dashscope_workspace_id="fixture-workspace",
        dashscope_region="cn-beijing",
        provider_policy_hash="a" * 64,
    )
    settings.validate_provider_configuration()
    assert settings.provider_policy_hash_for("embedding") == "a" * 64

    llm = _settings(
        tmp_path,
        llm_provider="dashscope",
        **{"dashscope_" + "api_key": "fixture" + "-key"},
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


class _NoCallTransport:
    def __init__(self) -> None:
        self.calls = 0

    def post(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.calls += 1
        raise AssertionError("price-card validation must precede transport")


def test_factory_injects_reviewed_price_card_without_transport(tmp_path: Path) -> None:
    transport = _NoCallTransport()
    selected = llm_provider(_dual(tmp_path), transport=transport)  # type: ignore[arg-type]
    assert isinstance(selected, DashScopeLLMAdapter)
    assert selected.price_card.reviewed
    assert selected.price_card.version == "fixture-price-card-v1"
    assert selected.price_card.input_rate == Decimal("1")
    assert selected.price_card.cached_input_rate == Decimal("0.5")
    assert selected.price_card.output_rate == Decimal("2")
    assert transport.calls == 0


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("llm_price_card_version", None),
        ("llm_input_price_cny_per_million", "0"),
        ("llm_output_price_cny_per_million", "0"),
        ("llm_price_card_retrieved_at", "2026-08-31T00:00:00"),
        ("llm_price_card_source_content_sha256", "not-a-hash"),
        ("llm_output_price_cny_per_million", "100000"),
    ),
)
def test_factory_rejects_unreviewed_price_card_before_transport(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    settings = _dual(tmp_path, **{field: value})
    transport = _NoCallTransport()
    with pytest.raises(RuntimeError, match="LLM price card"):
        llm_provider(settings, transport=transport)  # type: ignore[arg-type]
    assert transport.calls == 0


def test_mock_factory_does_not_require_a_price_card(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        llm_price_card_version=None,
        llm_input_price_cny_per_million=None,
        llm_cached_input_price_cny_per_million=None,
        llm_output_price_cny_per_million=None,
        llm_price_card_retrieved_at=None,
        llm_price_card_source_content_sha256=None,
    )
    assert isinstance(llm_provider(settings), MockLLMProvider)


def test_settings_validate_dual_real_price_card_requirements(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="LLM price card"):
        _dual(tmp_path, llm_price_card_source_content_sha256=None).validate_provider_configuration()


def test_llm_endpoint_policy_mismatch_fails_before_transport() -> None:
    class NoCallTransport:
        calls = 0

        def post(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            self.calls += 1
            raise AssertionError("endpoint preflight must precede transport")

    transport = NoCallTransport()
    config_values = {
        "api_" + "key": "fixture" + "-key",
        "workspace_id": "fixture-workspace",
        "policy_hash": "a" * 64,
    }
    adapter = DashScopeLLMAdapter(
        DashScopeLLMConfig(**config_values),
        transport,  # type: ignore[arg-type]
    )
    supplier_host = ".".join(("other", "cn-beijing", "maas", "aliyuncs", "com"))
    policy = SimpleNamespace(
        endpoint=f"https://{supplier_host}/compatible-mode/v1/chat/completions"
    )
    with pytest.raises(PlatformError, match="exact LLM Provider resource changed"):
        _assert_llm_provider_endpoint(adapter, policy)
    assert transport.calls == 0
