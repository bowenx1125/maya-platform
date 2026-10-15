from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.config import Settings
from app.core.errors import PlatformError
from app.modules.debates.playback.generation_adapter import _assert_llm_provider_endpoint
from app.modules.demo_baseline.composition import demo_composition
from app.modules.knowledge.providers.sql_query import REAL_CORE_DEMO_QUERY_MAX_REQUESTS
from app.providers.factory import llm_provider
from app.providers.llm import MockLLMProvider
from app.providers.llm_adapter import DashScopeLLMAdapter, DashScopeLLMConfig
from app.providers.llm_price_card import (
    LLM_ATTEMPT_CAP,
    LLM_FULL_DEBATE_MAX_ATTEMPTS,
    LLM_FULL_DEBATE_MAX_COST,
    LLM_SMALL_DEBATE_MAX_ATTEMPTS,
    LLM_SMALL_DEBATE_MAX_COST,
    REAL_CORE_DEMO_LLM_MAX_REQUESTS,
    LLMPriceCardError,
    debate_budget_cap,
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
        "llm_provider": "mock",
        "embedding_provider": "mock",
        # Explicitly pin the report selector and the credential so a developer
        # .env (MAYA_REPORT_PROVIDER / DASHSCOPE_*) cannot leak into fixtures.
        "report_provider": "mock",
        "dashscope_api_key": None,
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
        "report_provider": "mock",
        "dashscope_region": "cn-beijing",
        "embedding_provider_policy_hash": "a" * 64,
        "llm_provider_policy_hash": "b" * 64,
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


def test_report_selector_is_independent_and_disclosed_as_real(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        report_provider="dashscope",
        report_provider_policy_hash="d" * 64,
        **{"dashscope_" + "api_key": "fixture" + "-key"},
        dashscope_workspace_id="fixture-workspace",
        dashscope_region="cn-beijing",
    )
    settings.validate_provider_configuration()
    modes = {item.key: item.mode for item in demo_composition(settings).components}
    assert modes["report"] == "real"
    assert modes["llm"] == "mock"


def test_legacy_hash_remains_valid_for_one_real_slice(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        embedding_provider="dashscope",
        **{"dashscope_" + "api_key": "fixture" + "-key"},
        dashscope_workspace_id="fixture-workspace",
        dashscope_region="cn-beijing",
        provider_policy_hash="a" * 64,
        # Clear the per-slice hashes so .env values cannot shadow the legacy
        # shared hash, which must apply to each individually selected slice.
        embedding_provider_policy_hash=None,
        llm_provider_policy_hash=None,
        report_provider_policy_hash=None,
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
        embedding_provider_policy_hash=None,
        llm_provider_policy_hash=None,
        report_provider_policy_hash=None,
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


def test_dual_pair_shares_one_dashscope_key_with_tts_and_voice(tmp_path: Path) -> None:
    """TASK-20260924-001A: TTS and voice clone use the LLM key, not a second secret.

    The previous gate rejected those companions.  The approved scheme admits
    them beside the dual pair when DASHSCOPE_API_KEY is the only credential.
    """

    settings = _dual(tmp_path, tts_provider="dashscope", voice_provider="dashscope")
    settings.validate_provider_configuration()
    missing = _dual(
        tmp_path,
        tts_provider="dashscope",
        voice_provider="dashscope",
        **{"dashscope_" + "api_key": "  "},
    )
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        missing.validate_provider_configuration()


def test_dual_demo_caps_llm_and_query_requests(tmp_path: Path) -> None:
    # The cap funds what the runtime may attempt: one request per turn plus its
    # one structure repair. Funding a single request per turn meant the first
    # repair borrowed a later turn's allowance and the debate's last turn failed
    # for want of budget.
    cap = real_core_demo_budget_cap(2, round_count=2)
    assert cap.max_requests == REAL_CORE_DEMO_LLM_MAX_REQUESTS * LLM_ATTEMPT_CAP == 8
    assert REAL_CORE_DEMO_QUERY_MAX_REQUESTS == 2

    # One request per turn is the rule; the shape is not. This used to assert
    # that any round count but two raised, which pinned a fixture's shape as
    # if it were the policy and made a fully real Demo refuse every debate the
    # product lets a teacher create.
    for agents in range(2, 6):
        for rounds in range(2, 6):
            assert (
                real_core_demo_budget_cap(agents, round_count=rounds).max_requests
                == agents * rounds * LLM_ATTEMPT_CAP
            )
    for agents, rounds in ((1, 2), (6, 2), (2, 1), (2, 6)):
        with pytest.raises(ValueError):
            real_core_demo_budget_cap(agents, round_count=rounds)


def test_debate_budget_cap_matches_the_frozen_fixtures() -> None:
    small = debate_budget_cap(2, round_count=2)
    assert small.max_requests == LLM_SMALL_DEBATE_MAX_ATTEMPTS
    assert Decimal(str(small.max_cost_cny)) == LLM_SMALL_DEBATE_MAX_COST
    full = debate_budget_cap(5, round_count=2)
    assert full.max_requests == LLM_FULL_DEBATE_MAX_ATTEMPTS
    assert Decimal(str(full.max_cost_cny)) == LLM_FULL_DEBATE_MAX_COST
    for agents in range(2, 6):
        for rounds in range(2, 6):
            cap = debate_budget_cap(agents, round_count=rounds)
            assert cap.max_requests == agents * rounds * 2
    for agents, rounds in ((1, 2), (6, 2), (2, 1), (2, 6)):
        with pytest.raises(LLMPriceCardError):
            debate_budget_cap(agents, round_count=rounds)


def test_hash_validators_reject_non_sha256_slice_values(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _dual(tmp_path, llm_provider_policy_hash="not-a-hash")


def test_factory_uses_the_settings_llm_model_without_transport(tmp_path: Path) -> None:
    settings = _dual(tmp_path, llm_model="qwen-future-model")
    selected = llm_provider(settings)
    assert isinstance(selected, DashScopeLLMAdapter)
    assert selected.config.model_key == "qwen-future-model"


def test_mock_factory_ignores_the_llm_model(tmp_path: Path) -> None:
    settings = _settings(tmp_path, llm_model="qwen-future-model")
    assert isinstance(llm_provider(settings), MockLLMProvider)


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
