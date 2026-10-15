from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.main import create_app
from app.modules.debates.playback import router as playback_router
from app.modules.knowledge.providers import DashScopeEmbeddingAdapter
from app.providers.dashscope import DashScopeTTSProvider
from app.providers.factory import embedding_provider
from app.providers.tts import MockTTSProvider


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
        "report_provider": "mock",
        "provider_policy_hash": "a" * 64,
        # Pin the per-slice hashes so a developer .env (EMBEDDING/LLM/REPORT_
        # PROVIDER_POLICY_HASH) cannot shadow the shared fixture hash.
        "embedding_provider_policy_hash": None,
        "llm_provider_policy_hash": None,
        "report_provider_policy_hash": None,
    }
    values.update(updates)
    return Settings(**values)


def test_all_mock_runtime_and_main_composition_stay_unchanged(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.validate_provider_configuration()
    database = Database(settings.database_url, settings.data_root)
    try:
        app = create_app(settings, database, initialize_database=False)
        service = app.state.playback_service
        assert isinstance(service.tts_provider, MockTTSProvider)
        assert service.audio_store is not None
        assert service.audio_store.tts_provider is service.tts_provider
    finally:
        database.dispose()


def test_tts_dashscope_only_is_allowed_and_one_factory_instance_is_shared(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        tts_provider="dashscope",
        dashscope_api_key="fixture-key",
        dashscope_workspace_id="workspace123",
        dashscope_region="cn-beijing",
    )
    settings.validate_provider_configuration()
    database = Database(settings.database_url, settings.data_root)
    try:
        app = create_app(settings, database, initialize_database=False)
        service = app.state.playback_service
        assert isinstance(service.tts_provider, DashScopeTTSProvider)
        assert service.audio_store is not None
        assert service.audio_store.tts_provider is service.tts_provider
    finally:
        database.dispose()


def test_embedding_dashscope_only_is_allowed_without_network(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        embedding_provider="dashscope",
        dashscope_api_key="fixture-key",
        dashscope_workspace_id="workspace123",
        dashscope_region="cn-beijing",
    )
    settings.validate_provider_configuration()

    class NoCallTransport:
        def post(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            raise AssertionError("selector construction performed network I/O")

    selected = embedding_provider(settings, transport=NoCallTransport())  # type: ignore[arg-type]
    assert isinstance(selected, DashScopeEmbeddingAdapter)
    assert selected.config.region == "cn-beijing"


def test_embedding_dashscope_requires_exact_frozen_policy_hash(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        embedding_provider="dashscope",
        dashscope_api_key="fixture-key",
        dashscope_workspace_id="workspace123",
        dashscope_region="cn-beijing",
        provider_policy_hash=None,
    )
    with pytest.raises(RuntimeError, match="PROVIDER_POLICY_HASH"):
        settings.validate_provider_configuration()

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _settings(tmp_path, provider_policy_hash="not-a-policy-hash")


def test_embedding_only_slice_keeps_mock_playback_provider_allowed(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        embedding_provider="dashscope",
        dashscope_api_key="fixture-key",
        dashscope_workspace_id="workspace123",
        dashscope_region="cn-beijing",
    )
    database = Database(settings.database_url, settings.data_root)
    try:
        app = create_app(settings, database, initialize_database=False)
        service = app.state.playback_service
        assert isinstance(service.tts_provider, MockTTSProvider)
        service._provider_allowed()
    finally:
        database.dispose()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dashscope_api_key", None),
        ("dashscope_workspace_id", None),
        ("dashscope_region", "cn-shanghai"),
    ],
)
def test_tts_dashscope_requires_beijing_credentials(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    settings = _settings(
        tmp_path,
        tts_provider="dashscope",
        dashscope_api_key="fixture-key",
        dashscope_workspace_id="workspace123",
        dashscope_region="cn-beijing",
    )
    object.__setattr__(settings, field, value)
    with pytest.raises(RuntimeError):
        settings.validate_provider_configuration()


def test_tts_and_voice_share_the_configured_dashscope_key(tmp_path: Path) -> None:
    """Voice clone is allowed beside TTS when both read the one server key."""

    settings = _settings(
        tmp_path,
        tts_provider="dashscope",
        voice_provider="dashscope",
        dashscope_api_key="fixture-key",
        dashscope_workspace_id="workspace123",
        dashscope_region="cn-beijing",
    )
    settings.validate_provider_configuration()


def test_llm_beside_tts_still_requires_its_policy_hash(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        tts_provider="dashscope",
        llm_provider="dashscope",
        dashscope_api_key="fixture-key",
        dashscope_workspace_id="workspace123",
        dashscope_region="cn-beijing",
    )
    settings.validate_provider_configuration()
    cleared = settings.model_copy(
        update={"provider_policy_hash": None, "llm_provider_policy_hash": None}
    )
    with pytest.raises(RuntimeError, match="LLM_PROVIDER_POLICY_HASH"):
        cleared.validate_provider_configuration()


def test_main_calls_factory_once_and_injects_same_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.main as main_module

    settings = _settings(tmp_path)
    database = Database(settings.database_url, settings.data_root)
    sentinel = MockTTSProvider()
    calls: list[Settings] = []

    def factory(value: Settings) -> MockTTSProvider:
        calls.append(value)
        return sentinel

    monkeypatch.setattr(main_module, "tts_provider", factory)
    try:
        app = main_module.create_app(settings, database, initialize_database=False)
        service = app.state.playback_service
        assert calls == [settings]
        assert service.tts_provider is sentinel
        assert service.audio_store is not None
        assert service.audio_store.tts_provider is sentinel
    finally:
        database.dispose()


def test_router_fallback_factory_once_and_same_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    database = Database(settings.database_url, settings.data_root)
    sentinel = MockTTSProvider()
    calls: list[Settings] = []

    def factory(value: Settings) -> MockTTSProvider:
        calls.append(value)
        return sentinel

    monkeypatch.setattr(playback_router, "tts_provider", factory)
    app = SimpleNamespace(state=SimpleNamespace(database=database, settings=settings))
    request = SimpleNamespace(app=app)
    try:
        first = playback_router.get_playback_service(request)  # type: ignore[arg-type]
        second = playback_router.get_playback_service(request)  # type: ignore[arg-type]
        assert first is second
        assert calls == [settings]
        assert first.tts_provider is sentinel
        assert first.audio_store is not None
        assert first.audio_store.tts_provider is sentinel
    finally:
        database.dispose()


def test_browser_voice_profile_schema_has_no_provider_fields(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database(settings.database_url, settings.data_root)
    try:
        app = create_app(settings, database, initialize_database=False)
        schema = app.openapi()
        properties = schema["components"]["schemas"]["VoiceProfile"]["properties"]
        assert "provider" not in properties
        assert "provider_key" not in properties
        assert "external_id" not in properties
        assert "external_id_encrypted" not in properties
    finally:
        database.dispose()
