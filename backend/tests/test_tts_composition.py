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
        "translation_provider": None,
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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("llm_provider", "dashscope"),
        ("voice_provider", "dashscope"),
        ("translation_provider", "deepl"),
    ],
)
def test_other_non_mock_selectors_remain_fail_closed(
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
